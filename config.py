# -*- coding: utf-8 -*-
"""
config.py - الإعدادات النهائية
🔒 هذا الملف آمن للرفع على GitHub: لا يحتوي على أي مفاتيح حقيقية.
    كل الأسرار (مفاتيح Binance, Telegram, Groq) تُقرأ من environment variables.

    للتشغيل محليًا:
        1. انسخ .env.example باسم .env
        2. حط قيمك الحقيقية جوه .env
        3. شغّل: pip install python-dotenv (موجودة بالفعل في requirements.txt)

    على Railway:
        حط نفس المتغيرات (بدون ملف .env) في تبويب Variables الخاص بالمشروع.

📅 آخر تعديل: إصلاح TP/SL + SL أوسع + تحويل الأسرار لـ env vars
"""

import os

# تحميل ملف .env محليًا إذا كان موجودًا (على Railway المتغيرات بتيجي من النظام مباشرة)
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

USE_TESTNET = _get_bool("USE_TESTNET", default=True)  # ✅ الافتراضي Testnet للأمان، فعّلها False فقط لما تكون متأكد

# ==================== التداول ====================
TRADE_USDT = 20
LEVERAGE = 5                          # ✅ خفض من 10 → 5 (أمان أكبر)
MAX_OPEN_POSITIONS = 6                # ✅ رفع من 3 → 6 (فرص أكثر)

# ==================== TP المتعدد ====================
ENABLE_MULTIPLE_TP = True
TP_MULTIPLE_LEVELS = [1.0, 2.0, 3.0]  # ✅ رفع من [0.5, 0.7, 1.0] (أرباح أوضح)
TP_QUANTITY_RATIOS = [0.5, 0.3, 0.2]  # نفس النسب (مجموعها 1.0)
SL_PERCENT = 2.0                       # ✅ رفع من 0.4 → 2.0 (حماية أكبر)
TP_PERCENT = 1.0                       # ✅ رفع من 0.5 → 1.0

# ==================== SL ديناميكي ====================
DYNAMIC_SL_ENABLED = True
SL_ATR_MULTIPLIER = 2.5                # ✅ رفع من 1.5 → 2.5 (SL يتكيف مع التقلب)
SL_MIN_PERCENT = 1.5                   # ✅ رفع من 0.3 → 1.5 (حد أدنى آمن)
SL_MAX_PERCENT = 3.0                   # ✅ رفع من 0.8 → 3.0 (حد أقصى محترم)

# ==================== 🔥 إصلاح TP/SL ====================
VERIFY_TP_SL_AFTER_CREATION = True    # التحقق الإجباري
TP_SL_MAX_RETRIES = 3                  # إعادة المحاولة
CLOSE_ON_TP_SL_FAIL = True             # إغلاق عند فشل
TP_SL_RETRY_DELAY_SECONDS = 1          # تأخير بين المحاولات
MONITOR_TP_SL_INTERVAL = 60            # مراقبة كل 60 ثانية

# ==================== 🔥 فلتر السيولة ====================
ENABLE_VOLUME_FILTER = True
MIN_VOLUME_24H_USDT = 50000000         # 50 مليون USDT
MIN_MARKET_CAP_RANK = 200              # ضمن أفضل 200 عملة

# ==================== شروط الدخول ====================
MIN_TIMEFRAME_ALIGNMENT = 4.0
MIN_VOLUME_FACTOR = 1.2
MIN_GROQ_CONFIDENCE = 60
MIN_CONFIDENCE_AUTO = 55
MIN_SIGNAL_STRENGTH = 5

# ==================== نظام النقاط ====================
MIN_SCORE_REQUIRED = 60

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
MAX_CORRELATION = 0.65                # ✅ خفض من 0.75 → 0.65 (تنويع أفضل مع 6 صفقات)

# ==================== 🔥 قاطع الخسارة اليومية ====================
ENABLE_DAILY_DRAWDOWN_LIMIT = True
DAILY_MAX_LOSS_PERCENT = 5.0          # ✅ خفض من 8.0 → 5.0 (حماية أقوى مع 6 صفقات)

# ==================== Trailing SL ====================
TRAILING_SL_ENABLED = True
TRAILING_SL_TRIGGER = 1.0              # ✅ رفع من 0.3 → 1.0 (يبدأ بعد ربح 1%)
TRAILING_SL_DISTANCE = 0.5             # ✅ رفع من 0.15 → 0.5 (مسافة أوسع)
BREAKEVEN_TRIGGER = 0.8                # ✅ رفع من 0.25 → 0.8 (Breakeven بعد ربح 0.8%)

# ==================== الحماية ====================
MAX_CONSECUTIVE_LOSSES = 3
PAUSE_DURATION_MINUTES = 60

# ==================== ذاكرة الصفقات ====================
ENABLE_TRADE_MEMORY = True
MEMORY_MIN_TRADES_FOR_SCORE = 3
MEMORY_MIN_WIN_RATE = 30
MEMORY_MAX_CONSECUTIVE_LOSSES = 3

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
AUTO_SCAN_INTERVAL = 900               # 15 دقيقة
TOP_SYMBOLS_TO_SCAN = 20               # ✅ خفض من 50 → 20 (توفير Groq)
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

# ==================== التنفيذ ====================
ENABLE_AUTO_EXECUTION = True

# ==================== إضافات ====================
ENABLE_DETAILED_LOGGING = True
LOG_LEVEL = "INFO"
REQUEST_TIMEOUT = 90
MAX_RETRIES = 3
