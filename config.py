# -*- coding: utf-8 -*-
"""
config.py - الإعدادات النهائية v4.1
🔒 آمن للرفع على GitHub: لا يحتوي على أي مفاتيح حقيقية.

🔧 التعديلات v4.1:
    - ⚡ إضافة إعدادات البيانات اللحظية (WebSocket)

🔧 التعديلات v4.0:
    - رفع MIN_SCORE_REQUIRED من 60 → 68
    - رفع MIN_CONFIDENCE_AUTO من 55 → 60
    - رفع MIN_SIGNAL_STRENGTH من 5 → 6
    - خفض MAX_OPEN_POSITIONS من 6 → 3
    - خفض MAX_CORRELATION من 0.65 → 0.55
    - إضافة فلتر RSI إلزامي
    - إضافة فلتر دفتر الأوامر إلزامي
    - إضافة فلتر الحجم إلزامي
    - إضافة Breakeven بعد TP1

📅 آخر تعديل: 2026-09-18
"""

import os

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


def _get_env(name, default=None, required=False):
    value = os.environ.get(name, default)
    if required and not value:
        raise RuntimeError(
            f"❌ متغير البيئة '{name}' غير موجود. "
            f"أضفه في ملف .env محليًا أو في Variables على Railway."
        )
    return value


def _get_bool(name, default=False):
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


# ==================== Binance ====================
BINANCE_API_KEY = _get_env("BINANCE_API_KEY", required=True)
BINANCE_API_SECRET = _get_env("BINANCE_API_SECRET", required=True)

# ==================== Telegram ====================
TELEGRAM_TOKEN = _get_env("TELEGRAM_TOKEN", required=True)
TELEGRAM_CHAT_ID = _get_env("TELEGRAM_CHAT_ID", required=True)

# ==================== Groq AI ====================
GROQ_API_KEY = _get_env("GROQ_API_KEY", required=True)

USE_TESTNET = _get_bool("USE_TESTNET", default=True)

# ==================== التداول ====================
TRADE_USDT = 15
LEVERAGE = 10
MAX_OPEN_POSITIONS = 5                # ✅ خفض من 6 → 3 (تركيز أفضل)

# ==================== TP المتعدد ====================
ENABLE_MULTIPLE_TP = True
TP_MULTIPLE_LEVELS = [1.2, 2.0, 3.0]  # ✅ رفع TP1 من 1.0 → 1.2 (أعلى من SL)
TP_QUANTITY_RATIOS = [0.5, 0.3, 0.2]
SL_PERCENT = 2.0
TP_PERCENT = 1.2                       # ✅ رفع من 1.0 → 1.2

# ==================== SL ديناميكي ====================
DYNAMIC_SL_ENABLED = True
SL_ATR_MULTIPLIER = 2.5
SL_MIN_PERCENT = 1.5
SL_MAX_PERCENT = 3.0

# ==================== 🔥 إصلاح TP/SL ====================
VERIFY_TP_SL_AFTER_CREATION = True
TP_SL_MAX_RETRIES = 3
CLOSE_ON_TP_SL_FAIL = True
TP_SL_RETRY_DELAY_SECONDS = 1
MONITOR_TP_SL_INTERVAL = 60

# ==================== 🔥 فلتر السيولة ====================
ENABLE_VOLUME_FILTER = True
MIN_VOLUME_24H_USDT = 50000000
MIN_MARKET_CAP_RANK = 200

# ==================== شروط الدخول ====================
MIN_TIMEFRAME_ALIGNMENT = 4.0
MIN_VOLUME_FACTOR = 1.2                # ✅ إلزامي الآن (رفض فوري)
MIN_GROQ_CONFIDENCE = 60
MIN_CONFIDENCE_AUTO = 60               # ✅ رفع من 55 → 60
MIN_SIGNAL_STRENGTH = 6                # ✅ رفع من 5 → 6

# ==================== نظام النقاط ====================
MIN_SCORE_REQUIRED = 68                # ✅ رفع من 60 → 68
MIN_ORDER_BOOK_POINTS = 4              # ✅ جديد: حد أدنى لدفتر الأوامر
MIN_RSI_POINTS = 3                     # ✅ جديد: حد أدنى لنقاط RSI

SCORE_WEIGHTS = {
    'timeframe_alignment': 20,
    'volume': 17,
    'groq': 20,
    'rsi_ideal': 12,
    'momentum': 8,
    'price_action': 3,
    'market_regime': 5,
    'order_book': 10,
    'funding_oi': 5,
    'max_score': 100
}

# ==================== 🔥 فلتر دفتر الأوامر والتنفيذ ====================
ENABLE_ORDER_BOOK_FILTER = True
MAX_SPREAD_PERCENT = 0.15
MIN_DEPTH_MULTIPLIER = 10

# ==================== 🔥 فلتر Funding Rate + Open Interest ====================
ENABLE_FUNDING_OI_FILTER = True
FUNDING_RATE_EXTREME_PERCENT = 0.05

# ==================== 🔥 فلتر الارتباط بين العملات ====================
ENABLE_CORRELATION_FILTER = True
MAX_CORRELATION = 0.55                 # ✅ خفض من 0.65 → 0.55

# ==================== 🔥 منع الصفقات المتعاكسة ====================
ENABLE_OPPOSITE_DIRECTION_FILTER = True  # ✅ جديد

# ==================== 🔥 قاطع الخسارة اليومية ====================
ENABLE_DAILY_DRAWDOWN_LIMIT = True
DAILY_MAX_LOSS_PERCENT = 5.0

# ==================== Trailing SL ====================
TRAILING_SL_ENABLED = True
TRAILING_SL_TRIGGER = 1.0
TRAILING_SL_DISTANCE = 0.5
BREAKEVEN_TRIGGER = 1.2                # ✅ رفع من 0.8 → 1.2 (بعد TP1)
BREAKEVEN_OFFSET_PERCENT = 0.1         # ✅ جديد: هامش العمولات

# ==================== الحماية ====================
MAX_CONSECUTIVE_LOSSES = 3
PAUSE_DURATION_MINUTES = 60

# ==================== ذاكرة الصفقات ====================
ENABLE_TRADE_MEMORY = True
MEMORY_MIN_TRADES_FOR_SCORE = 3
MEMORY_MIN_WIN_RATE = 30
MEMORY_MAX_CONSECUTIVE_LOSSES = 3
COMMISSION_RATE = 0.0004               # ✅ جديد: 0.04% لكل جانب

# ==================== كشف حالة السوق ====================
ENABLE_MARKET_REGIME = True
MARKET_REGIME_CACHE_SECONDS = 300
BLOCK_IN_STRONG_BEARISH = True
BLOCK_IN_STRONG_BULLISH_SELL = True

# ==================== أوقات التداول ====================
ENABLE_TIME_FILTER = False
GOOD_HOURS = [8, 9, 10, 11, 12, 13, 14, 15, 16, 17]
AVOID_HOURS = [0, 1, 2, 3, 4, 5]

# ==================== المسح ====================
AUTO_SCAN_INTERVAL = 900
TOP_SYMBOLS_TO_SCAN = 20
COOLDOWN_MINUTES = 5

# ==================== الفريمات ====================
TIMEFRAMES = ['1m', '3m', '5m', '15m']
PRIMARY_TIMEFRAME = '5m'
CONFIRMATION_TIMEFRAME = '15m'

# ==================== Groq AI ====================
ENABLE_GROQ_ANALYSIS = True
GROQ_MODEL = "openai/gpt-oss-120b"
GROQ_API_BASE_URL = "https://api.groq.com/openai/v1"
GROQ_SEND_FULL_DATA = True
GROQ_MIN_SCORE_BEFORE_CALL = 45        # ✅ جديد: لا تستدعي Groq قبل 45 نقطة
GROQ_REJECT_IS_VETO = True             # ✅ جديد: "رفض" من Groq = فيتو مباشر

# ==================== التنفيذ ====================
ENABLE_AUTO_EXECUTION = True

# ==================== إضافات ====================
ENABLE_DETAILED_LOGGING = True
LOG_LEVEL = "INFO"
REQUEST_TIMEOUT = 90
MAX_RETRIES = 3

# ==================== ⚡ البيانات اللحظية (WebSocket) v4.1 ====================
ENABLE_REALTIME_DATA = True            # تفعيل/تعطيل النظام اللحظي
REALTIME_ADJUSTMENT_ENABLED = True     # استخدام التعديل اللحظي في النقاط

# نطاق التعديل
REALTIME_MIN_ADJUSTMENT = -5           # أدنى تعديل
REALTIME_MAX_ADJUSTMENT = 10           # أعلى تعديل

# إعدادات التدفق
REALTIME_PRESSURE_WINDOW = 30          # نافذة حساب الضغط (ثواني)
REALTIME_DEPTH_LEVELS = 20             # مستويات دفتر الأوامر
REALTIME_LIQUIDATION_THRESHOLD = 50000 # أدنى قيمة تصفية لتُعتبر حدثاً مهماً (USDT)

# عدد العملات للاشتراك
REALTIME_MAX_SUBSCRIPTIONS = 25        # لا تشترك في أكثر من هذا العدد
