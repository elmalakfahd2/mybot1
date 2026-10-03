# ==================================================
# 📁 ملف: bot_strategies_enhanced.py - الإصدار v5.9
# 🔧 التعديلات v5.9:
#    - 🔥 فيتو gemini لا يقتل إلا بثقة 50+ (رفض 30% من gemini كان يقتل عشوائياً)
#    - 🔥 AI_FAIL_MIN_SCORE الافتراضي 65 بدل 70 (كان يقتل إشارات 60-69 وقت أعطال AI الجماعية)
# 🔧 التعديلات v5.8:
#    - 🔥 فيتو AI فقط من النموذج الأساسي (gemini) أو بثقة 75+ —
#      رفض النماذج الاحتياطية ضعيف الثقة يُعامل "تحذير" لا رفضاً قاتلاً
#    - 🔥 إصلاح مقياس دفتر الأوامر: مضاعف العمق /100000 + نقاط جزئية للدفتر المحايد
#    - 🔥 قيم افتراضية آمنة إذا غابت GROQ_MIN_SCORE_BEFORE_CALL / AI_FAIL_MIN_SCORE من config
# 🔧 التعديلات v5.7:
#    - 🔥 التعلم يؤثر فعلياً: حد النقاط الديناميكي + عقوبة الاتجاه + حظر الساعات (adaptive_rules)
#    - 🔥 الحظر بنافذة زمنية وصفقات موثقة (ينتهي تلقائياً)
#    - 🔥 التبريد يُحسب عند الإغلاق بنتيجة حقيقية ويُحفظ في ملف
#    - 🔥 سياق حقيقي للذكاء الاصطناعي (السوق + سجل العملة + أداء البوت)
# 🔧 التعديلات v5.1:
#    - 🔥 AI إلزامي (75+ استثناء)
#    - 🔥 لا نقاط مجانية لـ AI
#    - 🔥 Cooldown تصاعدي (60/120/240)
#    - 🔥 حظر دائم للعملات السيئة
# 📅 التاريخ: 2026-10-01
# ==================================================

import logging
import time
import asyncio
import concurrent.futures
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup

logger = logging.getLogger("bot_strategies_enhanced")

try:
    from config import *
except ImportError as e:
    print(f"خطأ config: {e}")
    TELEGRAM_TOKEN = ""
    TELEGRAM_CHAT_ID = ""

# 🔥 v5.8: قيم افتراضية آمنة إذا غابت من config.py (تمنع توقف التداول كاملاً)
try:
    GROQ_MIN_SCORE_BEFORE_CALL = int(GROQ_MIN_SCORE_BEFORE_CALL)
except NameError:
    GROQ_MIN_SCORE_BEFORE_CALL = 50
if GROQ_MIN_SCORE_BEFORE_CALL > 55:
    logger.warning(
        f"⚠️ GROQ_MIN_SCORE_BEFORE_CALL={GROQ_MIN_SCORE_BEFORE_CALL} مرتفع جداً ويمنع الوصول لـ AI - "
        f"يُنصح بـ 50-55 في config.py حتى يبدأ التداول"
    )
try:
    AI_FAIL_MIN_SCORE = int(AI_FAIL_MIN_SCORE)
except NameError:
    AI_FAIL_MIN_SCORE = 65
if AI_FAIL_MIN_SCORE > 65:
    logger.warning(
        f"⚠️ AI_FAIL_MIN_SCORE={AI_FAIL_MIN_SCORE} مرتفع - وقت أعطال AI الجماعية سيُرفض "
        f"كل شيء تحته؛ يُنصح بـ 65 في config.py"
    )

try:
    import core_functions as core
except ImportError as e:
    logger.error(f"خطأ core: {e}")
    core = None

try:
    from groq_integration import enhance_signal_with_groq, is_groq_available
    GROQ_AVAILABLE = is_groq_available()
    if GROQ_AVAILABLE:
        logger.info("✅ تم تحميل AI")
except ImportError as e:
    logger.warning(f"❌ AI: {e}")
    GROQ_AVAILABLE = False
    enhance_signal_with_groq = lambda x: None

try:
    from indicators import (
        TechnicalIndicators,
        get_rsi_signal,
        is_rsi_ideal_for_direction
    )
    logger.info("✅ تم تحميل indicators")
except ImportError as e:
    logger.error(f"❌ indicators: {e}")
    raise

try:
    import trade_memory as memory
    logger.info("✅ تم تحميل trade_memory")
    MEMORY_AVAILABLE = True
except ImportError as e:
    logger.warning(f"⚠️ trade_memory غير متاح: {e}")
    MEMORY_AVAILABLE = False

try:
    from market_regime import MarketRegime
    logger.info("✅ تم تحميل market_regime")
    MARKET_REGIME_AVAILABLE = True
except ImportError as e:
    logger.warning(f"⚠️ market_regime غير متاح: {e}")
    MARKET_REGIME_AVAILABLE = False

try:
    import realtime_data
    REALTIME_AVAILABLE = True
    logger.info("✅ تم تحميل realtime_data")
except ImportError as e:
    logger.warning(f"⚠️ realtime_data غير متاح: {e}")
    REALTIME_AVAILABLE = False
    realtime_data = None


try:
    import adaptive_rules
    ADAPTIVE_AVAILABLE = True
    logger.info("✅ تم تحميل adaptive_rules")
except ImportError as e:
    logger.warning(f"⚠️ adaptive_rules غير متاح: {e}")
    adaptive_rules = None
    ADAPTIVE_AVAILABLE = False

import json as _json
import os as _os

COOLDOWN_FILE = "cooldowns.json"
_symbol_cooldown = {}
_pending_auto_signals = {}


def _save_cooldowns():
    try:
        with open(COOLDOWN_FILE, "w", encoding="utf-8") as f:
            _json.dump(_symbol_cooldown, f)
    except Exception:
        pass


def _load_cooldowns():
    """استرجاع التبريد بعد إعادة التشغيل (فقط غير المنتهي)"""
    try:
        if _os.path.exists(COOLDOWN_FILE):
            with open(COOLDOWN_FILE, "r", encoding="utf-8") as f:
                data = _json.load(f)
            now = time.time()
            for sym, end in data.items():
                if float(end) > now:
                    _symbol_cooldown[sym] = float(end)
    except Exception:
        pass


_load_cooldowns()


# ==================== دوال مساعدة ====================

def get_price(symbol):
    try:
        return core.get_price(symbol)
    except:
        return None


def get_klines_data(symbol, timeframe="5m", limit=50):
    try:
        klines = core.get_klines(symbol, timeframe, limit=limit)
        if klines:
            return {
                'closes': [float(k[4]) for k in klines],
                'highs': [float(k[2]) for k in klines],
                'lows': [float(k[3]) for k in klines],
                'volumes': [float(k[5]) for k in klines]
            }
        return None
    except:
        return None


def calculate_atr(symbol, period=14):
    try:
        data = get_klines_data(symbol, "5m", period + 1)
        if not data or len(data['highs']) < period + 1:
            return 0
        return TechnicalIndicators.calculate_atr(
            data['highs'], data['lows'], data['closes'], period
        )
    except:
        return 0


# ==================== 🔥 Cooldown تصاعدي ====================

def add_symbol_cooldown(symbol, duration_minutes=None):
    """
    🔥 v5.7: يُستدعى عند إغلاق الصفقة (بعد تسجيل نتيجتها الحقيقية).
    التبريد يعتمد على الخسائر المتتالية الموثقة للعملة خلال 48 ساعة:
    - لا خسائر → COOLDOWN_MINUTES
    - خسارة 1 → COOLDOWN_MINUTES_AFTER_LOSS
    - خسارتان → ضعف ذلك
    - 3+ → 4 أضعاف
    """
    try:
        if duration_minutes is None:
            duration_minutes = COOLDOWN_MINUTES
            if MEMORY_AVAILABLE:
                stats = memory.get_windowed_stats(symbol)
                streak = stats.get('consecutive_losses', 0)
                if streak >= 3:
                    duration_minutes = COOLDOWN_MINUTES_AFTER_LOSS * 4
                    logger.warning(f"🚫 {symbol}: {streak} خسائر متتالية - تبريد {duration_minutes} دقيقة")
                elif streak == 2:
                    duration_minutes = COOLDOWN_MINUTES_AFTER_LOSS * 2
                    logger.warning(f"⚠️ {symbol}: خسارتان - تبريد {duration_minutes} دقيقة")
                elif streak == 1:
                    duration_minutes = COOLDOWN_MINUTES_AFTER_LOSS
                    logger.info(f"⚠️ {symbol}: خسارة - تبريد {duration_minutes} دقيقة")

        _symbol_cooldown[symbol] = time.time() + (duration_minutes * 60)
        _save_cooldowns()
        logger.info(f"⏳ {symbol} في التبريد {duration_minutes} دقيقة")
    except Exception as e:
        logger.error(f"خطأ: {e}")


def is_symbol_in_cooldown(symbol):
    try:
        if symbol in _symbol_cooldown:
            end = _symbol_cooldown[symbol]
            if time.time() < end:
                remaining = int((end - time.time()) / 60)
                return True, remaining
            else:
                del _symbol_cooldown[symbol]
        return False, 0
    except:
        return False, 0


def cleanup_expired_cooldowns():
    try:
        current = time.time()
        expired = [s for s, e in _symbol_cooldown.items() if current >= e]
        for s in expired:
            del _symbol_cooldown[s]
    except:
        pass


def get_cooldown_status():
    try:
        current = time.time()
        active = {}
        for symbol, end in _symbol_cooldown.items():
            if current < end:
                active[symbol] = int((end - current) / 60)
        return {'total_active': len(active), 'active_symbols': active}
    except:
        return {'total_active': 0, 'active_symbols': {}}


# ==================== فلتر الذاكرة ====================

def check_memory_filter(symbol):
    try:
        if not MEMORY_AVAILABLE or not ENABLE_TRADE_MEMORY:
            return True, "ذاكرة معطلة", {}

        # 🔥 1. الحظر المؤقت (نافذة زمنية، صفقات موثقة)
        perm_blocked, perm_reason = memory.is_symbol_permanently_blocked(symbol)
        if perm_blocked:
            logger.warning(f"🚫 {symbol} محظور مؤقتاً: {perm_reason}")
            return False, f"🚫 {perm_reason}", {'blocked': True}

        # 2. الحظر العادي
        is_blocked, reason = memory.is_symbol_blacklisted(
            symbol,
            min_trades=MEMORY_MIN_TRADES_FOR_SCORE,
            max_win_rate=0.25,
            max_consecutive_losses=MEMORY_MAX_CONSECUTIVE_LOSSES
        )

        if is_blocked:
            logger.warning(f"🚫 {symbol} محظور: {reason}")
            return False, f"🚫 {reason}", {'blocked': True}

        score = memory.get_symbol_score(symbol)
        return True, score.get('reason', ''), score
    except Exception as e:
        logger.error(f"خطأ في check_memory_filter: {e}")
        return True, "خطأ", {}


def check_market_filter(direction):
    try:
        if not MARKET_REGIME_AVAILABLE or not ENABLE_MARKET_REGIME:
            return True, "سوق معطل", {}

        regime = MarketRegime.get_regime()
        regime_type = regime.get('regime', 'unknown')

        if BLOCK_IN_STRONG_BEARISH and regime_type == 'strong_bearish' and direction == "BUY":
            return False, f"⚠️ سوق هابط قوي", regime

        if BLOCK_IN_STRONG_BULLISH_SELL and regime_type == 'strong_bullish' and direction == "SELL":
            return False, f"⚠️ سوق صاعد قوي", regime

        return True, "متوافق", regime
    except:
        return True, "خطأ", {}


# ==================== محرك التحليل ====================

class SmartAnalysisEngine:

    @staticmethod
    def analyze_symbol_detailed(symbol):
        try:
            current_price = get_price(symbol)
            if not current_price:
                return None

            analysis = {
                'symbol': symbol,
                'timestamp': datetime.now().strftime("%H:%M:%S"),
                'current_price': current_price,
                'timeframes': {},
                'technical_indicators': {},
                'volume_analysis': {},
                'price_action': {},
                'momentum': {},
                'recommendation': {},
                'strength_metrics': {},
                'risk_assessment': {}
            }

            try:
                analysis['timeframes'] = SmartAnalysisEngine.analyze_all_timeframes(symbol)
            except Exception as e:
                logger.error(f"فريمات: {e}")

            try:
                analysis['technical_indicators'] = SmartAnalysisEngine.analyze_technical_indicators(symbol)
            except Exception as e:
                logger.error(f"مؤشرات: {e}")

            try:
                analysis['volume_analysis'] = SmartAnalysisEngine.analyze_volume(symbol)
            except Exception as e:
                logger.error(f"حجم: {e}")

            try:
                analysis['price_action'] = SmartAnalysisEngine.analyze_price_action(symbol)
            except Exception as e:
                logger.error(f"PA: {e}")

            try:
                analysis['momentum'] = SmartAnalysisEngine.analyze_momentum(symbol)
            except Exception as e:
                logger.error(f"مومنتوم: {e}")

            try:
                analysis['recommendation'] = generate_balanced_recommendation(analysis)
            except Exception as e:
                logger.error(f"توصية: {e}")
                analysis['recommendation'] = {'action': 'HOLD', 'confidence': 0, 'reasons': []}

            try:
                analysis['strength_metrics'] = SmartAnalysisEngine.calculate_strength_metrics(analysis)
            except Exception as e:
                logger.error(f"قوة: {e}")
                analysis['strength_metrics'] = {
                    'overall_strength': 0,
                    'quality': 'غير معروف',
                    'timeframe_alignment': 0
                }

            try:
                analysis['risk_assessment'] = SmartAnalysisEngine.assess_risk(symbol, analysis)
            except Exception as e:
                logger.error(f"مخاطر: {e}")
                analysis['risk_assessment'] = {'risk_level': 'متوسط', 'risk_factors': []}

            return analysis

        except Exception as e:
            logger.error(f"خطأ: {e}")
            return None

    @staticmethod
    def analyze_all_timeframes(symbol):
        result = {}
        timeframes = ['1m', '3m', '5m', '15m']

        for tf in timeframes:
            try:
                klines = core.get_klines(symbol, tf, limit=60)
                if not klines or len(klines) < 30:
                    continue

                closes = [float(k[4]) for k in klines]
                trend_data = TechnicalIndicators.detect_trend(closes, 20)

                result[tf] = {
                    'trend': trend_data['trend'],
                    'trend_strength': trend_data['strength'],
                    'ema20': trend_data.get('ema20'),
                    'ema50': trend_data.get('ema50'),
                    'price_vs_ema20': trend_data.get('price_vs_ema20', 0),
                    'current_price': closes[-1]
                }
            except:
                continue

        return result

    @staticmethod
    def analyze_technical_indicators(symbol):
        try:
            klines = core.get_klines(symbol, "5m", limit=100)
            if not klines or len(klines) < 50:
                return {}

            closes = [float(k[4]) for k in klines]
            highs = [float(k[2]) for k in klines]
            lows = [float(k[3]) for k in klines]

            rsi = TechnicalIndicators.calculate_rsi(closes, 14)
            macd = TechnicalIndicators.calculate_macd(closes)
            bb = TechnicalIndicators.calculate_bollinger_bands(closes)
            atr = TechnicalIndicators.calculate_atr(highs, lows, closes, 14)
            volatility = TechnicalIndicators.calculate_volatility(closes, 20)

            return {
                'rsi': rsi if rsi else 50,
                'rsi_signal': get_rsi_signal(rsi) if rsi else "غير محدد",
                'macd': macd['macd'],
                'macd_signal': macd['signal'],
                'macd_trend': macd['trend'],
                'bollinger_upper': bb['upper'],
                'bollinger_lower': bb['lower'],
                'bollinger_position': bb['position'],
                'atr': atr if atr else 0,
                'volatility': volatility['level'],
                'volatility_std': volatility['std_percent']
            }
        except:
            return {}

    @staticmethod
    def analyze_volume(symbol):
        try:
            klines_5m = core.get_klines(symbol, "5m", limit=35)

            if not klines_5m or len(klines_5m) < 25:
                return {
                    'volume_5m_ratio': 1.0,
                    'volume_1h_ratio': 1.0,
                    'volume_confidence': 'متوسط'
                }

            volumes_5m = [float(k[5]) for k in klines_5m]

            if len(volumes_5m) >= 22:
                completed_volume = sum(volumes_5m[-4:-1]) / 3
                avg_volume = sum(volumes_5m[-22:-2]) / 20
                ratio_5m = completed_volume / avg_volume if avg_volume > 0 else 1.0
            else:
                ratio_5m = 1.0

            ratio_1h = 1.0
            try:
                klines_1h = core.get_klines(symbol, "1h", limit=30)
                if klines_1h and len(klines_1h) >= 22:
                    volumes_1h = [float(k[5]) for k in klines_1h]
                    completed_1h = sum(volumes_1h[-4:-1]) / 3
                    avg_1h = sum(volumes_1h[-22:-2]) / 20
                    ratio_1h = completed_1h / avg_1h if avg_1h > 0 else 1.0
            except:
                pass

            if ratio_5m > 2.5:
                confidence = "عالي جداً"
            elif ratio_5m > 1.8:
                confidence = "عالي"
            elif ratio_5m > 1.2:
                confidence = "متوسط"
            elif ratio_5m > 0.8:
                confidence = "منخفض"
            else:
                confidence = "منخفض جداً"

            logger.info(f"🔊 {symbol} - حجم 5m: {ratio_5m:.2f}x ({confidence})")

            return {
                'volume_5m_ratio': round(ratio_5m, 2),
                'volume_1h_ratio': round(ratio_1h, 2),
                'volume_confidence': confidence
            }

        except Exception as e:
            logger.error(f"خطأ في تحليل الحجم: {e}")
            return {
                'volume_5m_ratio': 1.0,
                'volume_1h_ratio': 1.0,
                'volume_confidence': 'متوسط'
            }

    @staticmethod
    def analyze_price_action(symbol):
        try:
            klines = core.get_klines(symbol, "5m", limit=10)
            if not klines or len(klines) < 3:
                return {}

            latest = klines[-2] if len(klines) >= 2 else klines[-1]
            candle = TechnicalIndicators.analyze_candle(
                float(latest[1]), float(latest[2]), float(latest[3]), float(latest[4])
            )

            return {
                'candle_type': candle['type'],
                'body_ratio': candle['body_ratio'],
                'body_strength': candle['strength'],
                'upper_wick_ratio': candle['upper_wick_ratio'],
                'lower_wick_ratio': candle['lower_wick_ratio'],
                'rejection_upper': candle['is_rejection_upper'],
                'rejection_lower': candle['is_rejection_lower']
            }
        except:
            return {}

    @staticmethod
    def analyze_momentum(symbol):
        try:
            klines = core.get_klines(symbol, "5m", limit=20)
            if not klines or len(klines) < 15:
                return {'direction': 'محايد', 'strength': 0, 'consecutive_candles': 0}

            closes = [float(k[4]) for k in klines[:-1]]
            return TechnicalIndicators.calculate_momentum(closes, 10)
        except:
            return {'direction': 'محايد', 'strength': 0, 'consecutive_candles': 0}

    @staticmethod
    def calculate_strength_metrics(analysis):
        try:
            rec = analysis.get('recommendation', {})
            confidence = rec.get('confidence', 50)

            timeframes = analysis.get('timeframes', {})
            alignment = calculate_enhanced_timeframe_alignment(timeframes)

            strength = confidence * 0.6 + alignment * 4

            if strength >= 75:
                quality = "ممتاز"
            elif strength >= 60:
                quality = "جيد"
            elif strength >= 45:
                quality = "متوسط"
            else:
                quality = "ضعيف"

            return {
                'overall_strength': round(min(100, strength), 2),
                'quality': quality,
                'timeframe_alignment': alignment
            }
        except:
            return {'overall_strength': 0, 'quality': 'غير معروف', 'timeframe_alignment': 0}

    @staticmethod
    def assess_risk(symbol, analysis):
        try:
            technical = analysis.get('technical_indicators', {})
            volatility = technical.get('volatility', 'منخفض')
            current_price = analysis.get('current_price', 0)
            atr = technical.get('atr', 0)

            risk_level = "منخفض"
            risk_factors = []

            if volatility in ['عالي', 'عالي جداً']:
                risk_level = "عالي"
                risk_factors.append("تقلبات عالية")
            elif volatility == 'متوسط':
                risk_level = "متوسط"
                risk_factors.append("تقلبات متوسطة")

            if current_price > 0 and atr / current_price > 0.015:
                risk_level = "عالي"
                risk_factors.append("ATR عالي")

            return {
                'risk_level': risk_level,
                'risk_factors': risk_factors,
                'suggested_sl_percent': 0.5 if risk_level == "عالي" else 0.4,
                'suggested_tp_percent': 0.5
            }
        except:
            return {'risk_level': 'متوسط', 'risk_factors': [], 'suggested_sl_percent': 0.4, 'suggested_tp_percent': 0.5}


# ==================== دوال التحليل ====================

def calculate_enhanced_timeframe_alignment(timeframes):
    try:
        if not timeframes:
            return 0.0

        weights = {'1m': 0.5, '3m': 0.7, '5m': 0.9, '15m': 1.0}

        weighted_scores = []
        total_weight = 0
        bullish = 0
        bearish = 0
        total = 0

        for tf, data in timeframes.items():
            trend = data.get('trend', '')
            strength = data.get('trend_strength', 0)
            weight = weights.get(tf, 0.5)

            if 'صاعد' in trend:
                trend_value = 1
                bullish += 1
            elif 'هابط' in trend:
                trend_value = -1
                bearish += 1
            else:
                trend_value = 0

            total += 1
            weighted_scores.append(trend_value * strength * weight)
            total_weight += strength * weight

        if total_weight == 0:
            return 0.0

        alignment = abs(sum(weighted_scores)) / total_weight * 10

        if total > 0:
            dominant = max(bullish, bearish) / total
            if dominant >= 0.75:
                alignment = min(10.0, alignment * 1.3)
            elif dominant >= 0.5:
                alignment = min(10.0, alignment * 1.1)

        return round(min(10.0, alignment), 2)
    except:
        return 0.0


def generate_balanced_recommendation(analysis):
    try:
        symbol = analysis['symbol']
        timeframes = analysis.get('timeframes', {})
        technical = analysis.get('technical_indicators', {})
        volume = analysis.get('volume_analysis', {})
        price_action = analysis.get('price_action', {})

        current_price = get_price(symbol)
        if not current_price:
            return {'action': 'HOLD', 'confidence': 0, 'reasons': []}

        weights = {'1m': 0.4, '3m': 0.6, '5m': 0.8, '15m': 1.0}

        buy_score = 0
        sell_score = 0
        reasons = []

        for tf, data in timeframes.items():
            trend = data.get('trend', '')
            strength = data.get('trend_strength', 0)
            weight = weights.get(tf, 0.5)

            if 'صاعد' in trend:
                buy_score += strength * weight
                reasons.append(f"{tf}: {trend}")
            elif 'هابط' in trend:
                sell_score += strength * weight
                reasons.append(f"{tf}: {trend}")

        rsi = technical.get('rsi', 50)
        if rsi < 30:
            buy_score += 8
            reasons.append(f"RSI: {rsi:.1f} (تشبع بيعي)")
        elif rsi > 70:
            sell_score += 8
            reasons.append(f"RSI: {rsi:.1f} (تشبع شرائي)")
        elif 40 <= rsi <= 60:
            buy_score += 3
            sell_score += 3
            reasons.append(f"RSI: {rsi:.1f} (محايد)")

        macd_trend = technical.get('macd_trend', 'محايد')
        if macd_trend == "صاعد":
            buy_score += 5
        elif macd_trend == "هابط":
            sell_score += 5

        vol_conf = volume.get('volume_confidence', 'منخفض')
        vol_multiplier = 1.0
        if vol_conf in ['عالي', 'عالي جداً']:
            vol_multiplier = 1.2
        elif vol_conf == 'منخفض جداً':
            vol_multiplier = 0.8
        elif vol_conf == 'منخفض':
            vol_multiplier = 0.9

        buy_score *= vol_multiplier
        sell_score *= vol_multiplier

        body_strength = price_action.get('body_strength', '')
        candle_type = price_action.get('candle_type', '')
        if body_strength == "قوي":
            if candle_type == "صاعدة":
                buy_score += 5
            elif candle_type == "هابطة":
                sell_score += 5

        if buy_score > sell_score and buy_score >= 3:
            action = "BUY"
            base_conf = min(85, 45 + buy_score * 1.5)
        elif sell_score > buy_score and sell_score >= 3:
            action = "SELL"
            base_conf = min(85, 45 + sell_score * 1.5)
        else:
            action = "HOLD"
            base_conf = 40

        return {
            'action': action,
            'confidence': round(base_conf, 1),
            'reasons': reasons,
            'buy_score': round(buy_score, 2),
            'sell_score': round(sell_score, 2)
        }
    except:
        return {'action': 'HOLD', 'confidence': 0, 'reasons': []}


# ==================== نظام النقاط ====================

def calculate_total_score(signal, analysis):
    try:
        symbol = signal['symbol']
        direction = signal['direction']

        score = 0
        details = {
            'timeframe_points': 0, 'volume_points': 0, 'groq_points': 0,
            'rsi_points': 0, 'momentum_points': 0, 'price_action_points': 0,
            'market_points': 0, 'order_book_points': 0, 'funding_oi_points': 0,
            'realtime_adjustment': 0, 'total': 0, 'max_total': 100,
            'rejected': False, 'reject_reason': ''
        }

        # 1. ترابط (20)
        timeframes = analysis.get('timeframes', {})
        alignment = calculate_enhanced_timeframe_alignment(timeframes)

        if alignment >= 8.0:
            details['timeframe_points'] = 20
        elif alignment >= 6.0:
            details['timeframe_points'] = 16
        elif alignment >= 4.0:
            details['timeframe_points'] = 12
        elif alignment >= 3.0:
            details['timeframe_points'] = 8
        elif alignment >= 2.0:
            details['timeframe_points'] = 4

        score += details['timeframe_points']
        logger.info(f"📊 ترابط: {alignment:.1f}/10 → {details['timeframe_points']}/20")

        # 2. الحجم (15)
        volume = analysis.get('volume_analysis', {})
        vol_ratio = volume.get('volume_5m_ratio', 0)

        if vol_ratio >= 2.5:
            details['volume_points'] = 15
        elif vol_ratio >= 2.0:
            details['volume_points'] = 13
        elif vol_ratio >= 1.5:
            details['volume_points'] = 11
        elif vol_ratio >= 1.2:
            details['volume_points'] = 9
        elif vol_ratio >= 1.0:
            details['volume_points'] = 7
        elif vol_ratio >= 0.8:
            details['volume_points'] = 5
        elif vol_ratio >= 0.5:
            details['volume_points'] = 3
        else:
            details['volume_points'] = 1

        score += details['volume_points']
        logger.info(f"📊 حجم: {vol_ratio:.2f}x → {details['volume_points']}/15")

        # 3. RSI (10)
        technical = analysis.get('technical_indicators', {})
        rsi = technical.get('rsi', 50)

        if direction == "BUY":
            if rsi >= RSI_BUY_HARD_REJECT:
                logger.warning(f"🛑 {symbol}: RSI متشبع ({rsi:.1f}) - رفض")
                details['rejected'] = True
                details['reject_reason'] = f'RSI متشبع: {rsi:.1f}'
                return 0, details
        else:
            if rsi <= RSI_SELL_HARD_REJECT:
                logger.warning(f"🛑 {symbol}: RSI متشبع ({rsi:.1f}) - رفض")
                details['rejected'] = True
                details['reject_reason'] = f'RSI متشبع: {rsi:.1f}'
                return 0, details

        if direction == "BUY":
            if 40 <= rsi <= 60:
                details['rsi_points'] = 10
            elif 35 <= rsi <= 65:
                details['rsi_points'] = 8
            elif 30 <= rsi <= 70:
                details['rsi_points'] = 5
            elif 25 <= rsi <= RSI_BUY_WARNING:
                details['rsi_points'] = 3
            elif RSI_BUY_WARNING < rsi < RSI_BUY_HARD_REJECT:
                details['rsi_points'] = 1
                logger.warning(f"⚠️ {symbol}: RSI={rsi:.1f} - TP ضيق")
            else:
                details['rsi_points'] = 0
        else:
            if 40 <= rsi <= 60:
                details['rsi_points'] = 10
            elif 35 <= rsi <= 65:
                details['rsi_points'] = 8
            elif 30 <= rsi <= 70:
                details['rsi_points'] = 5
            elif RSI_SELL_WARNING <= rsi <= 75:
                details['rsi_points'] = 3
            elif RSI_SELL_HARD_REJECT < rsi < RSI_SELL_WARNING:
                details['rsi_points'] = 1
                logger.warning(f"⚠️ {symbol}: RSI={rsi:.1f} - TP ضيق")
            else:
                details['rsi_points'] = 0

        score += details['rsi_points']
        logger.info(f"📊 RSI: {rsi:.1f} → {details['rsi_points']}/10")

        # 4. Momentum (10)
        momentum = analysis.get('momentum', {})
        mom_strength = momentum.get('strength', 0)
        mom_dir = momentum.get('direction', 'محايد')

        is_aligned = (
            (direction == "BUY" and mom_dir == "صاعد") or
            (direction == "SELL" and mom_dir == "هابط")
        )

        if is_aligned:
            if mom_strength >= 7:
                details['momentum_points'] = 10
            elif mom_strength >= 5:
                details['momentum_points'] = 8
            elif mom_strength >= 3:
                details['momentum_points'] = 6
            else:
                details['momentum_points'] = 4
        else:
            if mom_strength < 3:
                details['momentum_points'] = 3
            else:
                details['momentum_points'] = 0

        score += details['momentum_points']
        logger.info(f"📊 Momentum: {mom_dir} ({mom_strength:.1f}) → {details['momentum_points']}/10")

        # 5. Price Action (8)
        price_action = analysis.get('price_action', {})
        body_ratio = price_action.get('body_ratio', 0)
        candle_type = price_action.get('candle_type', '')

        is_aligned_candle = (
            (direction == "BUY" and candle_type == "صاعدة") or
            (direction == "SELL" and candle_type == "هابطة")
        )

        if is_aligned_candle:
            if body_ratio >= 0.7:
                details['price_action_points'] = 8
            elif body_ratio >= 0.5:
                details['price_action_points'] = 6
            elif body_ratio >= 0.3:
                details['price_action_points'] = 4
            else:
                details['price_action_points'] = 2
        else:
            if body_ratio >= 0.5:
                details['price_action_points'] = 2
            else:
                details['price_action_points'] = 0

        score += details['price_action_points']
        logger.info(f"📊 PA: {candle_type} (body={body_ratio:.2f}) → {details['price_action_points']}/8")

        # 6. سوق (5)
        if MARKET_REGIME_AVAILABLE and ENABLE_MARKET_REGIME:
            try:
                regime = MarketRegime.get_regime()
                regime_type = regime.get('regime', 'unknown')

                is_compatible = True
                if regime_type == 'strong_bullish' and direction == "SELL":
                    is_compatible = False
                elif regime_type == 'strong_bearish' and direction == "BUY":
                    is_compatible = False

                if is_compatible:
                    if regime_type in ['bullish', 'strong_bullish'] and direction == "BUY":
                        details['market_points'] = 5
                    elif regime_type in ['bearish', 'strong_bearish'] and direction == "SELL":
                        details['market_points'] = 5
                    else:
                        details['market_points'] = 3
                else:
                    details['market_points'] = 1
            except:
                details['market_points'] = 2
        else:
            details['market_points'] = 2

        score += details['market_points']
        logger.info(f"📊 سوق: {details['market_points']}/5")

        # 7. دفتر الأوامر (10) - 🔥 v5.8: مضاعف عمق واقعي + نقاط جزئية للدفتر المحايد
        try:
            ob = core.get_order_book_analysis(symbol) if core else None
            if ob:
                imbalance = ob.get('imbalance', 0)
                spread = ob.get('spread_percent', 999)
                depth = ob.get('total_depth_usdt', 0)
                details['ob_imb'] = round(imbalance, 3)
                details['ob_depth'] = int(depth)

                aligned_imbalance = (
                    (direction == "BUY" and imbalance > 0) or
                    (direction == "SELL" and imbalance < 0)
                )

                # 🔥 v5.8: 100k بدل 500k — معظم الدفات أعماقها 50k-300k فكان المضاعف يقتل النقاط
                depth_multiplier = min(1.0, depth / 100000) if depth > 0 else 0.5

                if aligned_imbalance:
                    base_points = abs(imbalance) * 10 * depth_multiplier
                    details['order_book_points'] = min(10, 2 + int(base_points))
                elif abs(imbalance) < 0.3:
                    # دفتر متوازن تقريباً → نقاط جزئية بدل الصفر القاتل
                    details['order_book_points'] = 3
                else:
                    # معاكس بضعف خفيف → نقطة واحدة فقط، لا صفر كامل
                    details['order_book_points'] = 1

                if spread > MAX_SPREAD_PERCENT:
                    details['order_book_points'] = max(0, details['order_book_points'] - 3)
            else:
                details['order_book_points'] = 3
        except Exception as e:
            logger.warning(f"⚠️ خطأ دفتر الأوامر: {e}")
            details['order_book_points'] = 3

        score += details['order_book_points']
        logger.info(f"📊 دفتر الأوامر: {details['order_book_points']}/10 (imb={details.get('ob_imb', '؟')}, depth={details.get('ob_depth', '؟')})")

        # 8. Funding/OI (10)
        try:
            if ENABLE_FUNDING_OI_FILTER and core:
                funding = core.get_funding_rate(symbol)
                oi_change = core.get_open_interest_trend(symbol)

                fo_points = 5
                if funding is not None:
                    if direction == "BUY" and funding <= -FUNDING_RATE_EXTREME_PERCENT:
                        fo_points += 3
                    elif direction == "SELL" and funding >= FUNDING_RATE_EXTREME_PERCENT:
                        fo_points += 3
                    elif direction == "BUY" and funding >= FUNDING_RATE_EXTREME_PERCENT * 2:
                        fo_points -= 2
                    elif direction == "SELL" and funding <= -FUNDING_RATE_EXTREME_PERCENT * 2:
                        fo_points -= 2

                if oi_change is not None:
                    if oi_change > 0.5:
                        fo_points += 2
                    elif oi_change < -0.5:
                        fo_points += 1

                details['funding_oi_points'] = max(0, min(10, fo_points))
            else:
                details['funding_oi_points'] = 5
        except Exception as e:
            logger.warning(f"⚠️ خطأ Funding: {e}")
            details['funding_oi_points'] = 5

        score += details['funding_oi_points']
        logger.info(f"📊 Funding/OI: {details['funding_oi_points']}/10")

        # 9. AI (12) - 🔥 لا نقاط مجانية
        if GROQ_AVAILABLE and ENABLE_GROQ_ANALYSIS:
            groq_rec = signal.get('groq_recommendation', '')
            groq_conf = signal.get('groq_confidence', 0)

            if groq_rec == "تأكيد":
                if groq_conf >= 85:
                    details['groq_points'] = 12
                elif groq_conf >= 75:
                    details['groq_points'] = 11
                elif groq_conf >= 65:
                    details['groq_points'] = 9
                elif groq_conf >= 60:
                    details['groq_points'] = 7
                elif groq_conf >= 55:
                    details['groq_points'] = 5
                else:
                    details['groq_points'] = 3
            elif groq_rec == "تحذير":
                if groq_conf >= 70:
                    details['groq_points'] = 6
                elif groq_conf >= 60:
                    details['groq_points'] = 4
                else:
                    details['groq_points'] = 2
            elif groq_rec == "رفض":
                # 🔥 v5.8: الفيتو فقط من النموذج الأساسي (gemini) أو بثقة 75+
                _ai_prov = signal.get('ai_provider', '')
                # 🔥 v5.9: gemini موثوق فقط إذا كانت ثقته 50+ (رفض 30% كان فيتواً عشوائياً)
                _trusted = (_ai_prov == 'gemini' and groq_conf >= 50) or (groq_conf >= 75)
                if GROQ_REJECT_IS_VETO and _trusted:
                    logger.warning(f"🛑 {symbol}: AI رفض ({groq_conf}%) [{_ai_prov}]")
                    details['rejected'] = True
                    details['reject_reason'] = f'AI رفض ({groq_conf}%)'
                    return 0, details
                # رفض غير موثوق → لا نقاط فقط، بلا فيتو قاتل
                details['groq_points'] = 0
            else:
                # 🔥 لا نقاط إذا AI لم يعمل
                details['groq_points'] = 0
        else:
            # 🔥 لا نقاط إذا AI غير متاح
            details['groq_points'] = 0

        score += details['groq_points']
        logger.info(f"📊 AI: {details['groq_points']}/12")

        # 10. لحظي
        if REALTIME_AVAILABLE and ENABLE_REALTIME_DATA and REALTIME_ADJUSTMENT_ENABLED:
            try:
                rt_adj, rt_details = realtime_data.get_realtime_score_adjustment(symbol, direction)
                if rt_adj != 0:
                    score += rt_adj
                    score = max(0, min(100, score))
                    details['realtime_adjustment'] = rt_adj
                    logger.info(f"⚡ تعديل: {rt_adj:+d} → {score}")
                else:
                    details['realtime_adjustment'] = 0
            except:
                details['realtime_adjustment'] = 0
        else:
            details['realtime_adjustment'] = 0

        details['total'] = score
        logger.info(f"🎯 المجموع: {score}/100")

        return score, details

    except Exception as e:
        logger.error(f"خطأ في حساب النقاط: {e}")
        return 0, {'total': 0, 'max_total': 100, 'rejected': True, 'reject_reason': str(e)}


# ==================== 🔥 توليد الإشارة - AI إلزامي ====================


# ==================== 🔥 v6.0: تقليل استدعاءات الذكاء الاصطناعي ====================
# - لا يُستدعى AI إلا للإشارات الجيدة (نقاط قبل-AI >= AI_CALL_MIN_PRE_SCORE)
# - نتيجة AI تُخزَّن مؤقتاً لنفس (العملة، الاتجاه) AI_CACHE_MINUTES دقيقة
# - سقف AI_MAX_CALLS_PER_HOUR استدعاء في الساعة (عند بلوغه = لا دخول ما لم يُسمح عبر AI_UNAVAILABLE_ALLOW_ENTRY)
def _cfgv(name, default):
    try:
        return type(default)(globals().get(name, default))
    except Exception:
        return default

_ai_cache = {}          # (symbol, direction) -> (timestamp, result_dict)
_ai_call_times = []     # أوقات الاستدعاءات الفعلية


def _ai_call_limited(symbol, direction, signal, analysis):
    """يرجع (result, source) حيث source: 'cache' | 'call' | 'cap' | 'fail'"""
    now = time.time()
    ttl = _cfgv('AI_CACHE_MINUTES', 30) * 60
    key = (symbol, direction)

    cached = _ai_cache.get(key)
    if cached and now - cached[0] < ttl:
        return dict(cached[1]), 'cache'

    cap = _cfgv('AI_MAX_CALLS_PER_HOUR', 12)
    while _ai_call_times and now - _ai_call_times[0] > 3600:
        _ai_call_times.pop(0)
    if cap > 0 and len(_ai_call_times) >= cap:
        return None, 'cap'

    _ai_call_times.append(now)
    result = enhance_signal_with_groq(signal, analysis)
    if result:
        _ai_cache[key] = (now, dict(result))
        return result, 'call'
    return None, 'fail'



def _ai_unavailable_ok(symbol, direction, price, total_score, required_score, details):
    """هل يُسمح بالدخول عند عدم توفر AI (فشل/سقف/معطل)؟
    الافتراضي: لا (AI_UNAVAILABLE_ALLOW_ENTRY=False) + تسجيل صفقة ظل للتعلم."""
    if not bool(globals().get('AI_UNAVAILABLE_ALLOW_ENTRY', False)):
        logger.warning(f"🛑 {symbol}: AI غير متاح - لا دخول (AI_UNAVAILABLE_ALLOW_ENTRY=False)")
        _shadow(symbol, direction, price, total_score, 'ai_unavailable', details)
        return False
    need = max(AI_FAIL_MIN_SCORE, required_score)
    if total_score < need:
        logger.warning(f"🛑 {symbol}: AI غير متاح والنقاط {total_score} < {need}")
        return False
    logger.warning(f"⚠️ {symbol}: AI غير متاح - قبول استثنائي ({total_score})")
    return True


def _shadow(symbol, direction, price, score, tier, details=None, ai_rec='', ai_conf=0):
    """تسجيل إشارة مرفوضة كصفقة ظل (تعلّم بدون مال). لا يؤثر أبداً على القرار."""
    try:
        import shadow_tracker
        floor = int(getattr(__import__('config'), 'SHADOW_MIN_SCORE', 50))
        if score >= floor:
            shadow_tracker.record(symbol, direction, price, score, tier,
                                  ai_rec=ai_rec, ai_conf=ai_conf, details=details)
    except Exception:
        pass


def generate_sniper_signal(symbol):
    try:
        current_price = get_price(symbol)
        if not current_price:
            return None

        # 🔥 v5.7: ساعة محظورة بالتعلم (قبل أي تحليل لتوفير الطلبات)
        if ADAPTIVE_AVAILABLE and adaptive_rules.is_hour_blocked():
            logger.info(f"🕐 {symbol} - الساعة الحالية محظورة بالتعلم")
            return None

        memory_ok, memory_reason, memory_score = check_memory_filter(symbol)
        if not memory_ok:
            logger.info(f"🚫 {symbol} - {memory_reason}")
            return None

        analysis = SmartAnalysisEngine.analyze_symbol_detailed(symbol)
        if not analysis or not analysis.get('recommendation'):
            return None

        rec = analysis['recommendation']
        direction = rec['action']
        confidence = rec['confidence']

        if direction == "HOLD":
            return None
        if confidence < MIN_CONFIDENCE_AUTO:
            return None

        market_ok, market_reason, regime_data = check_market_filter(direction)
        if not market_ok:
            return None

        signal = {
            "symbol": symbol,
            "direction": direction,
            "entry_price": current_price,
            "confidence": confidence,
            "strength": min(10, max(1, int(confidence / 10))),
            "quality": "قناص",
            "timestamp": datetime.now().strftime("%H:%M:%S"),
            "sl_percent": SL_PERCENT,
            "tp_percent": TP_PERCENT,
            "analysis": analysis,
            "timeframe_alignment": analysis.get('strength_metrics', {}).get('timeframe_alignment', 0),
            "memory_score": memory_score,
            "market_regime": regime_data
        }

        total_score, score_details = calculate_total_score(signal, analysis)

        if score_details.get('rejected'):
            logger.info(f"🛑 {symbol} - مرفوض: {score_details.get('reject_reason', '')}")
            return None

        # 🔥 v5.7: الحد الأدنى الفعلي للنقاط (الأساس + ما تعلمه البوت)
        if ADAPTIVE_AVAILABLE:
            required_score = adaptive_rules.get_required_score(direction)
        else:
            required_score = MIN_SCORE_REQUIRED
        signal['required_score'] = required_score

        # AI يضيف حداً أقصى 12 نقطة؛ لا فائدة من استدعائه إن لم يكن الوصول للحد ممكناً
        ai_call_threshold = max(GROQ_MIN_SCORE_BEFORE_CALL, required_score - 12,
                                _cfgv('AI_CALL_MIN_PRE_SCORE', 0))

        # 🔥 AI إلزامي (فقط إذا النقاط كافية للوصول للحد)
        if total_score >= ai_call_threshold:

            # 🔥 v6.0: مقارنة بصفقات سابقة (محلي ومجاني؛ في وضع block يوفّر استدعاء AI)
            try:
                import similarity_filter
                _vol = (analysis.get('volume_analysis', {}) or {}).get('volume_5m_ratio', 0)
                sim = similarity_filter.assess(symbol, direction, score_details, _vol)
                signal['similarity'] = sim
                if sim['verdict'] != 'unknown':
                    logger.info(f"🧬 {symbol}: {sim['verdict']} (نجاح الجيران {sim['win_rate']:.0%}) "
                                f"[{sim['mode']}]")
                if not sim['allow']:
                    logger.warning(f"🛑 {symbol}: تشابه ضعيف - {sim['reason']}")
                    _shadow(symbol, direction, current_price, total_score, 'similarity_block', score_details)
                    return None
            except Exception as e:
                logger.debug(f"similarity: {e}")

            # 🔥 v5.7: سياق حقيقي للذكاء الاصطناعي
            if ADAPTIVE_AVAILABLE:
                try:
                    signal['ai_context'] = adaptive_rules.build_ai_context(symbol, direction)
                except Exception as e:
                    logger.debug(f"ai_context: {e}")

            if not GROQ_AVAILABLE:
                if not _ai_unavailable_ok(symbol, direction, current_price, total_score, required_score, score_details):
                    return None
            else:
                try:
                    groq_result, _ai_src = _ai_call_limited(symbol, direction, signal, analysis)
                    if _ai_src == 'cache':
                        logger.info(f"♻️ {symbol}: استخدام نتيجة AI المخزنة (بدون استدعاء)")
                    elif _ai_src == 'cap':
                        logger.warning(f"⏸️ {symbol}: بلغنا سقف استدعاءات AI/ساعة - يُعامل كـ AI غير متاح")

                    if not groq_result:
                        # AI فشل أو بلغنا السقف
                        if not _ai_unavailable_ok(symbol, direction, current_price, total_score, required_score, score_details):
                            return None
                    else:
                        rec_ai = groq_result.get('groq_recommendation', '')
                        ai_conf = groq_result.get('groq_confidence', 0)

                        # 🔥 v5.8: الفيتو فقط من النموذج الأساسي (gemini) أو بثقة 75+
                        ai_provider = groq_result.get('ai_provider', '')
                        # 🔥 v5.9: gemini موثوق فقط بثقة 50+، وغير ذلك يحتاج 75+
                        trusted_ai = (ai_provider == 'gemini' and ai_conf >= 50) or (ai_conf >= 75)

                        # AI رفض صريح من نموذج موثوق → فيتو
                        if rec_ai == 'رفض' and GROQ_REJECT_IS_VETO and trusted_ai:
                            logger.warning(f"🛑 {symbol}: AI رفض ({ai_conf}%) [{ai_provider}]")
                            _shadow(symbol, direction, current_price, total_score, 'ai_veto',
                                    score_details, rec_ai, ai_conf)
                            return None

                        # 🔥 v5.8: رفض من نموذج احتياطي ضعيف الثقة → تحذير فقط لا فيتو
                        if rec_ai == 'رفض' and not trusted_ai:
                            logger.info(f"⚠️ {symbol}: رفض {ai_provider} ضعيف الثقة ({ai_conf}%) — يُعامل كتحذير")
                            groq_result['groq_recommendation'] = 'تحذير'
                            rec_ai = 'تحذير'

                        # تحذير قوي من نموذج موثوق فقط
                        if rec_ai == 'تحذير' and ai_conf >= 75 and trusted_ai:
                            logger.warning(f"🛑 {symbol}: AI تحذير قوي ({ai_conf}%) [{ai_provider}]")
                            _shadow(symbol, direction, current_price, total_score, 'ai_veto',
                                    score_details, rec_ai, ai_conf)
                            return None

                        signal.update(groq_result)
                        total_score, score_details = calculate_total_score(signal, analysis)

                        if rec_ai == 'تأكيد':
                            logger.info(f"✅ {symbol}: AI تأكيد ({ai_conf}%) [{ai_provider}]")
                        else:
                            logger.info(f"⚠️ {symbol}: AI تحذير خفيف ({ai_conf}%) [{ai_provider}] - نقاط: {total_score}")

                except Exception as e:
                    logger.error(f"🛑 {symbol}: خطأ AI: {e}")
                    if not _ai_unavailable_ok(symbol, direction, current_price, total_score, required_score, score_details):
                        return None
        else:
            logger.info(f"🛑 {symbol}: نقاط {total_score} < {ai_call_threshold} - لا استدعاء AI")
            _shadow(symbol, direction, current_price, total_score, 'below_ai_gate', score_details)
            return None

        signal['total_score'] = total_score
        signal['score_details'] = score_details
        signal['auto_executable'] = total_score >= required_score

        if total_score >= required_score:
            logger.info(f"✅ {symbol} - مقبول! النقاط: {total_score}/{100} (الحد {required_score})")
            return signal
        else:
            logger.info(f"🛑 {symbol} - نقاط غير كافية: {total_score} < {required_score}")
            _shadow(symbol, direction, current_price, total_score, 'below_required', score_details,
                    signal.get('groq_recommendation', ''), signal.get('groq_confidence', 0))
            return None

    except Exception as e:
        logger.error(f"خطأ: {e}")
        return None


def generate_premium_signal(symbol):
    return generate_sniper_signal(symbol)


def generate_premium_signal_light(symbol):
    try:
        in_cooldown, _ = is_symbol_in_cooldown(symbol)
        if in_cooldown:
            return None

        current_price = get_price(symbol)
        if not current_price:
            return None

        analysis = SmartAnalysisEngine.analyze_symbol_detailed(symbol)
        if not analysis:
            return None

        rec = analysis['recommendation']
        if rec['action'] == "HOLD":
            return None

        return {
            "symbol": symbol,
            "direction": rec['action'],
            "strength": min(10, max(1, int(rec['confidence'] / 10))),
            "entry_price": current_price,
            "quality": "تحليل ذكي فقط",
            "timestamp": datetime.now().strftime("%H:%M:%S"),
            "confidence": rec['confidence'],
            "sl_percent": SL_PERCENT,
            "tp_percent": TP_PERCENT,
            "analysis": analysis
        }
    except:
        return None


def scan_sniper_signals():
    try:
        all_symbols = core.get_all_futures_symbols()
        if not all_symbols:
            return []

        top_symbols = all_symbols[:TOP_SYMBOLS_TO_SCAN]

        signals = []
        stats = {'checked': 0, 'accepted': 0, 'rejected': 0, 'scores': []}

        logger.info(f"🎯 مسح القناص: {len(top_symbols)}")

        cleanup_expired_cooldowns()

        if MARKET_REGIME_AVAILABLE and ENABLE_MARKET_REGIME:
            regime = MarketRegime.get_regime()
            logger.info(f"📊 السوق: {regime.get('regime_ar', 'غير معروف')} - {regime.get('recommendation', '')}")

        for symbol in top_symbols:
            try:
                stats['checked'] += 1

                in_cooldown, remaining = is_symbol_in_cooldown(symbol)
                if in_cooldown:
                    logger.info(f"⏳ {symbol} في تبريد ({remaining} د)")
                    continue

                signal = generate_sniper_signal(symbol)

                if signal:
                    signals.append(signal)
                    stats['accepted'] += 1
                    stats['scores'].append(signal['total_score'])
                else:
                    stats['rejected'] += 1

                time.sleep(0.2)

            except:
                continue

        signals.sort(key=lambda x: x.get('total_score', 0), reverse=True)

        if stats['scores']:
            avg_score = sum(stats['scores']) / len(stats['scores'])
            max_score = max(stats['scores'])
            logger.info(f"📊 النتائج: {stats['accepted']} مقبولة / {stats['rejected']} مرفوضة")
            logger.info(f"📊 متوسط النقاط: {avg_score:.1f}/100 - أعلى: {max_score}/100")
        else:
            logger.info(f"📊 النتائج: 0 مقبولة / {stats['rejected']} مرفوضة")

        try:
            import shadow_tracker
            shadow_tracker.flush()
        except Exception:
            pass

        return signals[:MAX_OPEN_POSITIONS]

    except Exception as e:
        logger.error(f"خطأ: {e}")
        return []


def scan_premium_signals():
    return scan_sniper_signals()


def scan_premium_signals_with_cooldown():
    return scan_sniper_signals()


def scan_scalping_signals():
    return scan_sniper_signals()


# ==================== دوال مساعدة إضافية ====================

def calculate_momentum_targets(symbol, direction, current_price):
    try:
        atr = calculate_atr(symbol)
        atr_ratio = atr / current_price if atr > 0 and current_price > 0 else 0.01

        if atr_ratio > 0.02:
            sl_percent = 0.5
            tp1_percent = 0.8
        elif atr_ratio > 0.01:
            sl_percent = 0.4
            tp1_percent = 0.6
        else:
            sl_percent = 0.3
            tp1_percent = 0.5

        if direction == "BUY":
            sl_price = current_price * (1 - sl_percent / 100)
            tp1_price = current_price * (1 + tp1_percent / 100)
        else:
            sl_price = current_price * (1 + sl_percent / 100)
            tp1_price = current_price * (1 - tp1_percent / 100)

        return {
            'entry_price': round(current_price, 8),
            'sl_price': round(sl_price, 8),
            'tp1_price': round(tp1_price, 8),
            'sl_percent': sl_percent,
            'tp1_percent': tp1_percent
        }
    except:
        return {
            'entry_price': current_price,
            'sl_price': 0, 'tp1_price': 0,
            'sl_percent': 0.4, 'tp1_percent': 0.5
        }


def get_momentum_reason(signal):
    try:
        reasons = []
        if signal.get('conditions_met', 0) >= 2:
            reasons.append("🔥 معايير الزخم")
        if signal.get('volume_boost', 1) >= 1.3:
            reasons.append("📈 حجم معزز")
        return " | ".join(reasons) if reasons else "إشارة زخم"
    except:
        return "إشارة زخم"


def scan_early_momentum_signals():
    try:
        all_symbols = core.get_all_futures_symbols()
        early_signals = []

        for symbol in all_symbols[:20]:
            try:
                data = get_klines_data(symbol, "5m", 20)
                if not data:
                    continue

                closes = data['closes']
                volumes = data['volumes']

                if len(closes) < 10:
                    continue

                current_price = closes[-2]
                sma_5 = sum(closes[-6:-1]) / 5
                price_change = ((current_price - sma_5) / sma_5) * 100

                if len(volumes) >= 7:
                    completed_vol = volumes[-2]
                    avg_vol = sum(volumes[-7:-2]) / 5
                    volume_ratio = completed_vol / avg_vol if avg_vol > 0 else 1
                else:
                    volume_ratio = 1

                conditions_met = 0
                if abs(price_change) >= 0.5:
                    conditions_met += 1
                if volume_ratio >= 1.3:
                    conditions_met += 1

                if conditions_met >= 2:
                    direction = "BUY" if price_change > 0 else "SELL"
                    targets = calculate_momentum_targets(symbol, direction, current_price)

                    signal = {
                        'symbol': symbol,
                        'direction': direction,
                        'strength': min(8, conditions_met * 2),
                        'entry_price': current_price,
                        'targets': targets,
                        'early_signal': True,
                        'price_change_1h': price_change,
                        'volume_boost': volume_ratio,
                        'conditions_met': conditions_met,
                        'timestamp': datetime.now().strftime("%H:%M:%S")
                    }
                    signal['reason'] = get_momentum_reason(signal)
                    early_signals.append(signal)
            except:
                continue

        return early_signals[:3]
    except:
        return []


def scan_momentum_signals():
    return scan_early_momentum_signals()


# ==================== الإشعارات ====================

async def send_single_signal_notification(signal, rank=None):
    try:
        from telegram import Bot
        bot = Bot(token=TELEGRAM_TOKEN)

        emoji = "🟢" if signal['direction'] == 'BUY' else "🔴"
        details = signal.get('score_details', {})

        msg = (
            f"🎯 <b>إشارة قناص</b>\n\n"
            f"💰 <b>العملة:</b> {signal['symbol']}\n"
            f"📈 <b>الاتجاه:</b> {emoji} {signal['direction']}\n"
            f"💪 <b>القوة:</b> {signal['strength']}/10\n"
            f"🎯 <b>الثقة:</b> {signal['confidence']:.1f}%\n"
            f"📊 <b>النقاط:</b> {signal.get('total_score', 0)}/100\n\n"
            f"⏰ {signal.get('timestamp', '')}"
        )

        keyboard = [[InlineKeyboardButton(
            f"🚀 تنفيذ {signal['direction']}",
            callback_data=f"trade_{signal['symbol']}_{signal['direction']}"
        )]]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await bot.send_message(
            chat_id=TELEGRAM_CHAT_ID,
            text=msg,
            parse_mode="HTML",
            reply_markup=reply_markup
        )

        return msg
    except Exception as e:
        logger.error(f"فشل: {e}")
        return None


async def send_momentum_signal_notification(signal):
    try:
        from telegram import Bot
        bot = Bot(token=TELEGRAM_TOKEN)

        emoji = "🟢" if signal['direction'] == 'BUY' else "🔴"
        targets = signal.get('targets', {})

        msg = (
            f"🚀 <b>إشارة زخم</b>\n\n"
            f"💰 <b>العملة:</b> {signal['symbol']}\n"
            f"📈 <b>الاتجاه:</b> {emoji} {signal['direction']}\n"
            f"💪 <b>القوة:</b> {signal['strength']}/10\n\n"
        )

        if targets:
            msg += (f"💰 <b>الدخول:</b> {targets['entry_price']:.6f}\n"
                    f"🛡️ <b>SL:</b> {targets['sl_price']:.6f}\n"
                    f"🎯 <b>TP:</b> {targets['tp1_price']:.6f}\n\n")

        msg += f"📋 <b>السبب:</b> {signal.get('reason', '')}\n"
        msg += f"⏰ {signal.get('timestamp', '')}"

        keyboard = [[InlineKeyboardButton(
            f"🚀 تنفيذ {signal['direction']}",
            callback_data=f"trade_{signal['symbol']}_{signal['direction']}"
        )]]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await bot.send_message(
            chat_id=TELEGRAM_CHAT_ID,
            text=msg,
            parse_mode="HTML",
            reply_markup=reply_markup
        )

        return msg
    except Exception as e:
        logger.error(f"فشل: {e}")
        return None


# ==================== التوافق ====================

def generate_smart_signal(symbol):
    return generate_sniper_signal(symbol)


def generate_smart_analysis(symbol):
    return SmartAnalysisEngine.analyze_symbol_detailed(symbol)


def get_ai_status():
    return {
        'status': 'نشط',
        'groq_available': GROQ_AVAILABLE,
        'memory_available': MEMORY_AVAILABLE,
        'market_regime_available': MARKET_REGIME_AVAILABLE,
        'realtime_available': REALTIME_AVAILABLE
    }


def format_smart_analysis_for_display(analysis):
    try:
        symbol = analysis['symbol']
        rec = analysis['recommendation']
        strength = analysis['strength_metrics']
        timeframes = analysis.get('timeframes', {})
        technical = analysis.get('technical_indicators', {})
        volume = analysis.get('volume_analysis', {})
        current_price = analysis.get('current_price', 0)

        action_emoji = "🟢" if rec['action'] == 'BUY' else "🔴" if rec['action'] == 'SELL' else "⚪"

        msg = f"{action_emoji} <b>تحليل {symbol}</b>\n\n"
        msg += f"💰 <b>السعر:</b> {current_price:.6f}\n"
        msg += f"📈 <b>التوصية:</b> {rec['action']}\n"
        msg += f"💪 <b>الثقة:</b> {rec['confidence']:.1f}%\n"
        msg += f"📊 <b>الجودة:</b> {strength.get('quality', 'غير معروف')}\n"
        msg += f"⏰ <b>ترابط:</b> {strength.get('timeframe_alignment', 0):.1f}/10\n\n"

        msg += "⏰ <b>الفريمات:</b>\n"
        for tf in ['1m', '3m', '5m', '15m']:
            if tf in timeframes:
                t = timeframes[tf]
                e = "🟢" if "صاعد" in t['trend'] else "🔴" if "هابط" in t['trend'] else "⚪"
                msg += f"   {e} {tf}: {t['trend']} ({t['trend_strength']:.1f})\n"

        msg += f"\n📈 <b>RSI:</b> {technical.get('rsi', 0):.1f}\n"
        msg += f"📊 <b>MACD:</b> {technical.get('macd_trend', 'محايد')}\n"
        msg += f"🔊 <b>الحجم:</b> {volume.get('volume_confidence', 'منخفض')} ({volume.get('volume_5m_ratio', 1.0):.2f}x)\n"

        return msg
    except:
        return f"❌ خطأ"
