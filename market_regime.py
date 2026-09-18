# ==================================================
# 📁 ملف: market_regime.py - كشف حالة السوق
# 🔧 الوصف:
#    - تحليل BTC لتحديد حالة السوق
#    - تصنيف السوق: صاعد/هابط/متذبذب
#    - توصيات لكل حالة
# 📅 التاريخ: 2024-01-15
# ==================================================

import logging
from datetime import datetime

logger = logging.getLogger("market_regime")

try:
    import core_functions as core
except ImportError:
    core = None


class MarketRegime:
    """كشف حالة السوق العامة"""
    
    _last_check = 0
    _cached_regime = None
    _cache_duration = 300  # 5 دقائق
    
    @staticmethod
    def get_btc_data():
        """الحصول على بيانات BTC"""
        try:
            # السعر الحالي
            current_price = core.get_price("BTCUSDT")
            if not current_price:
                return None
            
            # شموع 1h
            klines_1h = core.get_klines("BTCUSDT", "1h", limit=24)
            if not klines_1h or len(klines_1h) < 24:
                return None
            
            closes_1h = [float(k[4]) for k in klines_1h]
            highs_1h = [float(k[2]) for k in klines_1h]
            lows_1h = [float(k[3]) for k in klines_1h]
            
            # شموع 15m
            klines_15m = core.get_klines("BTCUSDT", "15m", limit=16)
            closes_15m = [float(k[4]) for k in klines_15m] if klines_15m else closes_1h
            
            # شموع 4h
            klines_4h = core.get_klines("BTCUSDT", "4h", limit=12)
            closes_4h = [float(k[4]) for k in klines_4h] if klines_4h else closes_1h
            
            return {
                'current_price': current_price,
                'closes_1h': closes_1h,
                'highs_1h': highs_1h,
                'lows_1h': lows_1h,
                'closes_15m': closes_15m,
                'closes_4h': closes_4h
            }
            
        except Exception as e:
            logger.error(f"خطأ في جلب BTC: {e}")
            return None
    
    @staticmethod
    def calculate_change(closes, hours):
        """حساب نسبة التغير"""
        try:
            if not closes or len(closes) < hours + 1:
                return 0.0
            
            current = closes[-1]
            past = closes[-(hours + 1)]
            
            if past == 0:
                return 0.0
            
            return ((current - past) / past) * 100
            
        except:
            return 0.0
    
    @staticmethod
    def detect_regime():
        """كشف حالة السوق الحالية"""
        try:
            btc = MarketRegime.get_btc_data()
            if not btc:
                return {
                    'regime': 'unknown',
                    'regime_ar': 'غير معروف',
                    'change_1h': 0,
                    'change_4h': 0,
                    'change_24h': 0,
                    'recommendation': 'حذر',
                    'should_trade': True,
                    'volatility': 'unknown'
                }
            
            closes_1h = btc['closes_1h']
            closes_15m = btc['closes_15m']
            closes_4h = btc['closes_4h']
            
            # حساب التغيرات
            change_1h = MarketRegime.calculate_change(closes_1h, 1)
            change_4h = MarketRegime.calculate_change(closes_1h, 4)
            change_24h = MarketRegime.calculate_change(closes_1h, 24)
            
            # حساب التقلب
            recent_high = max(btc['highs_1h'][-6:])
            recent_low = min(btc['lows_1h'][-6:])
            volatility_pct = ((recent_high - recent_low) / recent_low) * 100 if recent_low > 0 else 0
            
            if volatility_pct < 1.0:
                volatility = 'منخفض'
            elif volatility_pct < 2.5:
                volatility = 'متوسط'
            else:
                volatility = 'عالي'
            
            # تحديد حالة السوق
            regime = 'ranging'
            regime_ar = 'متذبذب'
            recommendation = 'تداول بحذر'
            should_trade = True
            
            # سوق صاعد قوي
            if change_4h > 2.0 and change_24h > 3.0:
                regime = 'strong_bullish'
                regime_ar = 'صاعد قوي'
                recommendation = 'التركيز على BUY'
                should_trade = True
            # سوق صاعد
            elif change_4h > 0.5 or change_24h > 1.0:
                regime = 'bullish'
                regime_ar = 'صاعد'
                recommendation = 'تفضيل BUY'
                should_trade = True
            # سوق هابط قوي
            elif change_4h < -2.0 and change_24h < -3.0:
                regime = 'strong_bearish'
                regime_ar = 'هابط قوي'
                recommendation = 'التركيز على SELL أو التوقف'
                should_trade = True
            # سوق هابط
            elif change_4h < -0.5 or change_24h < -1.0:
                regime = 'bearish'
                regime_ar = 'هابط'
                recommendation = 'تفضيل SELL'
                should_trade = True
            # متذبذب
            else:
                regime = 'ranging'
                regime_ar = 'متذبذب'
                recommendation = 'تداول بحذر'
                should_trade = True
            
            # تحذيرات خاصة
            if volatility == 'عالي' and regime in ['strong_bullish', 'strong_bearish']:
                should_trade = False
                recommendation = '⚠️ تقلب عالي - تجنب التداول'
            
            # إيقاف التداول في السوق الهابط القوي
            if regime == 'strong_bearish':
                should_trade = False
                recommendation = '⚠️ سوق هابط قوي - توقف'
            
            return {
                'regime': regime,
                'regime_ar': regime_ar,
                'change_1h': round(change_1h, 2),
                'change_4h': round(change_4h, 2),
                'change_24h': round(change_24h, 2),
                'volatility': volatility,
                'volatility_pct': round(volatility_pct, 2),
                'recommendation': recommendation,
                'should_trade': should_trade,
                'btc_price': btc['current_price'],
                'timestamp': datetime.now().strftime("%H:%M:%S")
            }
            
        except Exception as e:
            logger.error(f"خطأ في كشف حالة السوق: {e}")
            return {
                'regime': 'unknown',
                'regime_ar': 'غير معروف',
                'should_trade': True,
                'recommendation': 'حذر'
            }
    
    @staticmethod
    def get_regime(use_cache=True):
        """الحصول على حالة السوق (مع تخزين مؤقت)"""
        import time
        
        current_time = time.time()
        
        if use_cache and MarketRegime._cached_regime:
            if current_time - MarketRegime._last_check < MarketRegime._cache_duration:
                return MarketRegime._cached_regime
        
        regime = MarketRegime.detect_regime()
        MarketRegime._cached_regime = regime
        MarketRegime._last_check = current_time
        
        return regime
    
    @staticmethod
    def should_accept_signal(direction, regime=None):
        """التحقق من أن الإشارة مناسبة لحالة السوق"""
        try:
            if regime is None:
                regime = MarketRegime.get_regime()
            
            if not regime.get('should_trade', True):
                return False, f"السوق غير مناسب: {regime.get('recommendation', '')}"
            
            regime_type = regime.get('regime', 'unknown')
            
            # في السوق الصاعد القوي: نقبل BUY فقط
            if regime_type == 'strong_bullish':
                if direction == "SELL":
                    return False, "سوق صاعد قوي - رفض SELL"
                return True, "متوافق مع السوق الصاعد"
            
            # في السوق الهابط القوي: نقبل SELL فقط
            if regime_type == 'strong_bearish':
                if direction == "BUY":
                    return False, "سوق هابط قوي - رفض BUY"
                return True, "متوافق مع السوق الهابط"
            
            # في السوق الصاعد: نفضل BUY
            if regime_type == 'bullish':
                return True, "سوق صاعد - مقبول"
            
            # في السوق الهابط: نفضل SELL
            if regime_type == 'bearish':
                return True, "سوق هابط - مقبول"
            
            # في السوق المتذبذب: نقبل الاثنين
            return True, "سوق متذبذب - مقبول"
            
        except Exception as e:
            logger.error(f"خطأ: {e}")
            return True, "خطأ في التحقق"
    
    @staticmethod
    def get_summary():
        """ملخص حالة السوق"""
        try:
            regime = MarketRegime.get_regime()
            
            emoji_map = {
                'strong_bullish': '🚀',
                'bullish': '📈',
                'ranging': '↔️',
                'bearish': '📉',
                'strong_bearish': '💥',
                'unknown': '❓'
            }
            
            emoji = emoji_map.get(regime.get('regime', 'unknown'), '❓')
            
            msg = (
                f"{emoji} <b>حالة السوق: {regime.get('regime_ar', 'غير معروف')}</b>\n\n"
                f"💰 <b>BTC:</b> ${regime.get('btc_price', 0):,.0f}\n"
                f"📊 <b>1h:</b> {regime.get('change_1h', 0):+.2f}%\n"
                f"📊 <b>4h:</b> {regime.get('change_4h', 0):+.2f}%\n"
                f"📊 <b>24h:</b> {regime.get('change_24h', 0):+.2f}%\n"
                f"🌊 <b>التقلب:</b> {regime.get('volatility', 'غير معروف')}\n\n"
                f"💡 <b>التوصية:</b> {regime.get('recommendation', 'حذر')}\n"
                f"✅ <b>التداول:</b> {'مسموح' if regime.get('should_trade', True) else 'موقوف'}"
            )
            
            return msg
            
        except Exception as e:
            logger.error(f"خطأ: {e}")
            return "❌ خطأ في عرض حالة السوق"


if __name__ == "__main__":
    print("🧪 اختبار حالة السوق...")
    regime = MarketRegime.detect_regime()
    for k, v in regime.items():
        print(f"  {k}: {v}")