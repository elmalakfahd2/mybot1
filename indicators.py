# ==================================================
# 📁 ملف: indicators.py - حسابات المؤشرات الفنية الدقيقة
# 🔧 الوصف:
#    - RSI بطريقة Wilder الصحيحة (متطابقة مع TradingView)
#    - EMA (Exponential Moving Average)
#    - ATR (Average True Range)
#    - MACD
#    - Bollinger Bands
# 📅 التاريخ: 2024-01-15
# ==================================================

import logging
from typing import Optional, List, Dict, Tuple

logger = logging.getLogger("indicators")


class TechnicalIndicators:
    """
    حسابات المؤشرات الفنية الدقيقة
    جميع الحسابات متطابقة مع المعايير المستخدمة في TradingView
    """
    
    # ==================== RSI (Wilder Method) ====================
    
    @staticmethod
    def calculate_rsi(closes: List[float], period: int = 14) -> Optional[float]:
        """
        حساب RSI بطريقة Wilder الصحيحة
        
        Args:
            closes: قائمة أسعار الإغلاق (الأقدم أولاً)
            period: الفترة (افتراضي 14)
        
        Returns:
            قيمة RSI (0-100) أو None إذا لم تكن البيانات كافية
        """
        try:
            if not closes or len(closes) < period + 1:
                logger.warning(f"بيانات غير كافية لحساب RSI: {len(closes) if closes else 0} < {period + 1}")
                return None
            
            # حساب التغيرات
            deltas = [closes[i] - closes[i-1] for i in range(1, len(closes))]
            
            # فصل المكاسب والخسائر
            gains = [d if d > 0 else 0 for d in deltas]
            losses = [-d if d < 0 else 0 for d in deltas]
            
            # 🔥 الطريقة الصحيحة: حساب المتوسط الأول (SMA) لأول period
            avg_gain = sum(gains[:period]) / period
            avg_loss = sum(losses[:period]) / period
            
            # 🔥 ثم تطبيق Wilder Smoothing للباقي
            for i in range(period, len(gains)):
                avg_gain = (avg_gain * (period - 1) + gains[i]) / period
                avg_loss = (avg_loss * (period - 1) + losses[i]) / period
            
            # حساب RSI
            if avg_loss == 0:
                return 100.0
            
            rs = avg_gain / avg_loss
            rsi = 100 - (100 / (1 + rs))
            
            return round(rsi, 2)
            
        except Exception as e:
            logger.error(f"خطأ في حساب RSI: {e}")
            return None
    
    # ==================== EMA ====================
    
    @staticmethod
    def calculate_ema(values: List[float], period: int) -> Optional[float]:
        """
        حساب EMA (Exponential Moving Average)
        
        Args:
            values: قائمة القيم
            period: الفترة
        
        Returns:
            قيمة EMA أو None
        """
        try:
            if not values or len(values) < period:
                return None
            
            # حساب SMA للبداية
            sma = sum(values[:period]) / period
            
            # معامل الضرب
            multiplier = 2 / (period + 1)
            
            # تطبيق EMA
            ema = sma
            for value in values[period:]:
                ema = (value - ema) * multiplier + ema
            
            return round(ema, 8)
            
        except Exception as e:
            logger.error(f"خطأ في حساب EMA: {e}")
            return None
    
    @staticmethod
    def calculate_ema_series(values: List[float], period: int) -> List[float]:
        """حساب سلسلة EMA كاملة"""
        try:
            if not values or len(values) < period:
                return []
            
            ema_values = []
            sma = sum(values[:period]) / period
            ema_values.append(sma)
            
            multiplier = 2 / (period + 1)
            ema = sma
            
            for value in values[period:]:
                ema = (value - ema) * multiplier + ema
                ema_values.append(ema)
            
            return ema_values
            
        except Exception as e:
            logger.error(f"خطأ في حساب سلسلة EMA: {e}")
            return []
    
    # ==================== ATR ====================
    
    @staticmethod
    def calculate_atr(highs: List[float], lows: List[float], 
                     closes: List[float], period: int = 14) -> Optional[float]:
        """
        حساب ATR (Average True Range) بطريقة Wilder
        
        Args:
            highs: أسعار الأعلى
            lows: أسعار الأدنى
            closes: أسعار الإغلاق
            period: الفترة
        
        Returns:
            قيمة ATR أو None
        """
        try:
            if not highs or not lows or not closes:
                return None
            
            if len(highs) < period + 1:
                return None
            
            # حساب True Range
            true_ranges = []
            for i in range(1, len(highs)):
                tr1 = highs[i] - lows[i]
                tr2 = abs(highs[i] - closes[i-1])
                tr3 = abs(lows[i] - closes[i-1])
                true_ranges.append(max(tr1, tr2, tr3))
            
            if len(true_ranges) < period:
                return None
            
            # حساب ATR بطريقة Wilder
            atr = sum(true_ranges[:period]) / period
            
            for i in range(period, len(true_ranges)):
                atr = (atr * (period - 1) + true_ranges[i]) / period
            
            return round(atr, 8)
            
        except Exception as e:
            logger.error(f"خطأ في حساب ATR: {e}")
            return None
    
    # ==================== MACD ====================
    
    @staticmethod
    def calculate_macd(closes: List[float], fast: int = 12, 
                      slow: int = 26, signal: int = 9) -> Dict:
        """
        حساب MACD
        
        Returns:
            {'macd': float, 'signal': float, 'histogram': float, 'trend': str}
        """
        try:
            if not closes or len(closes) < slow + signal:
                return {'macd': 0, 'signal': 0, 'histogram': 0, 'trend': 'محايد'}
            
            # حساب EMA السريع والبطيء
            ema_fast_series = TechnicalIndicators.calculate_ema_series(closes, fast)
            ema_slow_series = TechnicalIndicators.calculate_ema_series(closes, slow)
            
            if not ema_fast_series or not ema_slow_series:
                return {'macd': 0, 'signal': 0, 'histogram': 0, 'trend': 'محايد'}
            
            # محاذاة السلسلتين
            min_len = min(len(ema_fast_series), len(ema_slow_series))
            offset_fast = len(ema_fast_series) - min_len
            offset_slow = len(ema_slow_series) - min_len
            
            macd_line = [
                ema_fast_series[i + offset_fast] - ema_slow_series[i + offset_slow]
                for i in range(min_len)
            ]
            
            # حساب خط الإشارة
            if len(macd_line) < signal:
                return {'macd': 0, 'signal': 0, 'histogram': 0, 'trend': 'محايد'}
            
            signal_line = TechnicalIndicators.calculate_ema_series(macd_line, signal)
            
            if not signal_line:
                return {'macd': 0, 'signal': 0, 'histogram': 0, 'trend': 'محايد'}
            
            current_macd = macd_line[-1]
            current_signal = signal_line[-1]
            histogram = current_macd - current_signal
            
            # تحديد الاتجاه
            if histogram > 0:
                trend = "صاعد"
            elif histogram < 0:
                trend = "هابط"
            else:
                trend = "محايد"
            
            return {
                'macd': round(current_macd, 8),
                'signal': round(current_signal, 8),
                'histogram': round(histogram, 8),
                'trend': trend
            }
            
        except Exception as e:
            logger.error(f"خطأ في حساب MACD: {e}")
            return {'macd': 0, 'signal': 0, 'histogram': 0, 'trend': 'محايد'}
    
    # ==================== Bollinger Bands ====================
    
    @staticmethod
    def calculate_bollinger_bands(closes: List[float], period: int = 20, 
                                  std_dev: float = 2.0) -> Dict:
        """
        حساب Bollinger Bands
        
        Returns:
            {'upper': float, 'middle': float, 'lower': float, 'position': str}
        """
        try:
            if not closes or len(closes) < period:
                return {'upper': 0, 'middle': 0, 'lower': 0, 'position': 'غير محدد'}
            
            recent = closes[-period:]
            middle = sum(recent) / period
            
            # حساب الانحراف المعياري
            variance = sum((x - middle) ** 2 for x in recent) / period
            std = variance ** 0.5
            
            upper = middle + (std * std_dev)
            lower = middle - (std * std_dev)
            
            current_price = closes[-1]
            
            if current_price > upper:
                position = "فوق النطاق"
            elif current_price < lower:
                position = "تحت النطاق"
            else:
                position = "في النطاق"
            
            return {
                'upper': round(upper, 8),
                'middle': round(middle, 8),
                'lower': round(lower, 8),
                'position': position,
                'bandwidth': round((upper - lower) / middle * 100, 4) if middle > 0 else 0
            }
            
        except Exception as e:
            logger.error(f"خطأ في حساب Bollinger Bands: {e}")
            return {'upper': 0, 'middle': 0, 'lower': 0, 'position': 'غير محدد'}
    
    # ==================== Momentum ====================
    
    @staticmethod
    def calculate_momentum(closes: List[float], period: int = 10) -> Dict:
        """
        حساب الزخم بناءً على عدة عوامل
        
        Returns:
            {
                'direction': str,  # صاعد / هابط / محايد
                'strength': float,  # 0-10
                'consecutive_candles': int,
                'momentum_score': float
            }
        """
        try:
            if not closes or len(closes) < period:
                return {
                    'direction': 'محايد',
                    'strength': 0,
                    'consecutive_candles': 0,
                    'momentum_score': 0
                }
            
            recent = closes[-period:]
            
            # 1. عدد الشمعات المتتالية في نفس الاتجاه
            consecutive_up = 0
            consecutive_down = 0
            
            for i in range(len(recent) - 1, 0, -1):
                if recent[i] > recent[i-1]:
                    if consecutive_down > 0:
                        break
                    consecutive_up += 1
                elif recent[i] < recent[i-1]:
                    if consecutive_up > 0:
                        break
                    consecutive_down += 1
                else:
                    break
            
            consecutive = max(consecutive_up, consecutive_down)
            direction = "صاعد" if consecutive_up > consecutive_down else "هابط" if consecutive_down > 0 else "محايد"
            
            # 2. قوة الحركة (نسبة التغير)
            price_change = ((recent[-1] - recent[0]) / recent[0]) * 100 if recent[0] > 0 else 0
            
            # 3. حساب قوة الزخم
            strength = 0
            strength += min(5, consecutive * 1.5)  # حتى 5 نقاط للشمعات المتتالية
            strength += min(5, abs(price_change) * 2)  # حتى 5 نقاط لقوة الحركة
            
            return {
                'direction': direction,
                'strength': round(min(10, strength), 2),
                'consecutive_candles': consecutive,
                'price_change_percent': round(price_change, 4),
                'momentum_score': round(min(10, strength), 2)
            }
            
        except Exception as e:
            logger.error(f"خطأ في حساب Momentum: {e}")
            return {
                'direction': 'محايد',
                'strength': 0,
                'consecutive_candles': 0,
                'momentum_score': 0
            }
    
    # ==================== Volatility ====================
    
    @staticmethod
    def calculate_volatility(closes: List[float], period: int = 20) -> Dict:
        """
        حساب التقلب
        
        Returns:
            {
                'level': str,  # منخفض / متوسط / عالي
                'atr_percent': float,
                'std_percent': float
            }
        """
        try:
            if not closes or len(closes) < period:
                return {'level': 'غير محدد', 'atr_percent': 0, 'std_percent': 0}
            
            recent = closes[-period:]
            current_price = recent[-1]
            
            if current_price <= 0:
                return {'level': 'غير محدد', 'atr_percent': 0, 'std_percent': 0}
            
            # حساب الانحراف المعياري
            mean = sum(recent) / len(recent)
            variance = sum((x - mean) ** 2 for x in recent) / len(recent)
            std = variance ** 0.5
            std_percent = (std / mean) * 100 if mean > 0 else 0
            
            # حساب أعلى وأدنى تغير
            max_change = (max(recent) - min(recent)) / min(recent) * 100 if min(recent) > 0 else 0
            
            # تحديد المستوى
            if std_percent < 0.3:
                level = "منخفض جداً"
            elif std_percent < 0.6:
                level = "منخفض"
            elif std_percent < 1.2:
                level = "متوسط"
            elif std_percent < 2.0:
                level = "عالي"
            else:
                level = "عالي جداً"
            
            return {
                'level': level,
                'std_percent': round(std_percent, 4),
                'max_change_percent': round(max_change, 4)
            }
            
        except Exception as e:
            logger.error(f"خطأ في حساب Volatility: {e}")
            return {'level': 'غير محدد', 'atr_percent': 0, 'std_percent': 0}
    
    # ==================== Price Action ====================
    
    @staticmethod
    def analyze_candle(open_price: float, high: float, low: float, 
                      close: float) -> Dict:
        """
        تحليل شمعة واحدة
        
        Returns:
            {
                'type': str,  # صاعدة / هابطة / دوجي
                'body_ratio': float,
                'upper_wick_ratio': float,
                'lower_wick_ratio': float,
                'strength': str  # قوي / متوسط / ضعيف
            }
        """
        try:
            total_range = high - low
            if total_range <= 0:
                return {
                    'type': 'دوجي',
                    'body_ratio': 0,
                    'upper_wick_ratio': 0,
                    'lower_wick_ratio': 0,
                    'strength': 'ضعيف'
                }
            
            body = abs(close - open_price)
            body_ratio = body / total_range
            
            upper_wick = high - max(open_price, close)
            lower_wick = min(open_price, close) - low
            upper_wick_ratio = upper_wick / total_range
            lower_wick_ratio = lower_wick / total_range
            
            # نوع الشمعة
            if close > open_price:
                candle_type = "صاعدة"
            elif close < open_price:
                candle_type = "هابطة"
            else:
                candle_type = "دوجي"
            
            # قوة الشمعة
            if body_ratio > 0.7:
                strength = "قوي"
            elif body_ratio > 0.4:
                strength = "متوسط"
            else:
                strength = "ضعيف"
            
            return {
                'type': candle_type,
                'body_ratio': round(body_ratio, 4),
                'upper_wick_ratio': round(upper_wick_ratio, 4),
                'lower_wick_ratio': round(lower_wick_ratio, 4),
                'strength': strength,
                'is_rejection_upper': upper_wick_ratio > 0.3,
                'is_rejection_lower': lower_wick_ratio > 0.3
            }
            
        except Exception as e:
            logger.error(f"خطأ في تحليل الشمعة: {e}")
            return {
                'type': 'غير محدد',
                'body_ratio': 0,
                'upper_wick_ratio': 0,
                'lower_wick_ratio': 0,
                'strength': 'ضعيف'
            }
    
    # ==================== Trend Detection ====================
    
    @staticmethod
    def detect_trend(closes: List[float], period: int = 20) -> Dict:
        """
        اكتشاف الاتجاه باستخدام EMA20 و EMA50
        
        Returns:
            {
                'trend': str,  # صاعد قوي / صاعد / محايد / هابط / هابط قوي
                'strength': float,  # 0-10
                'ema20': float,
                'ema50': float,
                'price_vs_ema20': float
            }
        """
        try:
            if not closes or len(closes) < 50:
                # استخدام EMA20 فقط إذا البيانات غير كافية
                if len(closes) >= 20:
                    ema20 = TechnicalIndicators.calculate_ema(closes, 20)
                    if ema20:
                        current = closes[-1]
                        diff = ((current - ema20) / ema20) * 100
                        
                        if diff > 1.0:
                            trend = "صاعد"
                            strength = min(10, diff * 3)
                        elif diff < -1.0:
                            trend = "هابط"
                            strength = min(10, abs(diff) * 3)
                        else:
                            trend = "محايد"
                            strength = 3
                        
                        return {
                            'trend': trend,
                            'strength': round(strength, 2),
                            'ema20': ema20,
                            'ema50': None,
                            'price_vs_ema20': round(diff, 4)
                        }
                
                return {
                    'trend': 'محايد',
                    'strength': 0,
                    'ema20': None,
                    'ema50': None,
                    'price_vs_ema20': 0
                }
            
            ema20 = TechnicalIndicators.calculate_ema(closes, 20)
            ema50 = TechnicalIndicators.calculate_ema(closes, 50)
            current_price = closes[-1]
            
            if not ema20 or not ema50:
                return {
                    'trend': 'محايد',
                    'strength': 0,
                    'ema20': ema20,
                    'ema50': ema50,
                    'price_vs_ema20': 0
                }
            
            # حساب الفرق
            price_vs_ema20 = ((current_price - ema20) / ema20) * 100
            ema20_vs_ema50 = ((ema20 - ema50) / ema50) * 100
            
            # تحديد الاتجاه
            if price_vs_ema20 > 0.5 and ema20_vs_ema50 > 0.3:
                trend = "صاعد قوي"
                strength = min(10, abs(price_vs_ema20) * 3 + abs(ema20_vs_ema50) * 2)
            elif price_vs_ema20 > 0.2:
                trend = "صاعد"
                strength = min(8, abs(price_vs_ema20) * 3)
            elif price_vs_ema20 < -0.5 and ema20_vs_ema50 < -0.3:
                trend = "هابط قوي"
                strength = min(10, abs(price_vs_ema20) * 3 + abs(ema20_vs_ema50) * 2)
            elif price_vs_ema20 < -0.2:
                trend = "هابط"
                strength = min(8, abs(price_vs_ema20) * 3)
            else:
                trend = "محايد"
                strength = 3
            
            return {
                'trend': trend,
                'strength': round(strength, 2),
                'ema20': round(ema20, 8),
                'ema50': round(ema50, 8),
                'price_vs_ema20': round(price_vs_ema20, 4),
                'ema20_vs_ema50': round(ema20_vs_ema50, 4)
            }
            
        except Exception as e:
            logger.error(f"خطأ في اكتشاف الاتجاه: {e}")
            return {
                'trend': 'محايد',
                'strength': 0,
                'ema20': None,
                'ema50': None,
                'price_vs_ema20': 0
            }


# ==================== دوال مساعدة ====================

def get_rsi_signal(rsi: float) -> str:
    """تحديد إشارة RSI"""
    if rsi is None:
        return "غير محدد"
    if rsi >= 70:
        return "تشبع شرائي"
    elif rsi >= 60:
        return "قوي"
    elif rsi >= 40:
        return "محايد"
    elif rsi >= 30:
        return "ضعيف"
    else:
        return "تشبع بيعي"


def is_rsi_ideal_for_direction(rsi: float, direction: str) -> bool:
    """
    التحقق من أن RSI في المنطقة المثالية للاتجاه
    
    للشراء: RSI بين 30-50 (منطقة ارتداد)
    للبيع: RSI بين 50-70 (منطقة ارتداد)
    """
    if rsi is None:
        return False
    
    if direction == "BUY":
        return 30 <= rsi <= 50
    elif direction == "SELL":
        return 50 <= rsi <= 70
    return False


if __name__ == "__main__":
    # اختبار سريع
    print("🧪 اختبار المؤشرات...")
    
    test_prices = [100 + i * 0.5 + (i % 3 - 1) * 0.3 for i in range(60)]
    
    rsi = TechnicalIndicators.calculate_rsi(test_prices)
    print(f"RSI: {rsi}")
    
    ema20 = TechnicalIndicators.calculate_ema(test_prices, 20)
    print(f"EMA20: {ema20}")
    
    trend = TechnicalIndicators.detect_trend(test_prices)
    print(f"Trend: {trend}")
    
    momentum = TechnicalIndicators.calculate_momentum(test_prices)
    print(f"Momentum: {momentum}")