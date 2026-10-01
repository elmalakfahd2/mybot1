# -*- coding: utf-8 -*-
"""
config.py - الإعدادات النهائية v5.7
🔧 v5.7: إصلاح التعلم + الاستمرارية
    - إعدادات التعلم التكيفي (ADAPTIVE_*) التي تؤثر فعلياً على القرار
    - إيقاف متصاعد بعد الخسائر + حد خسارة يومي حقيقي + تقليل الحجم
    - حظر العملات مؤقت بنافذة زمنية (كان دائماً)
    - AUTO_TUNE_WEIGHTS = False (الأوزان لا تُقرأ في حساب النقاط)
🔧 التعديلات السابقة:
    - GROQ_MIN_SCORE_BEFORE_CALL: 55 (كان 25) - يقلل استدعاءات AI
    - COOLDOWN_MINUTES_AFTER_LOSS: 60 (كان 30)
    - MAX_CONSECUTIVE_LOSSES: 2 (كان 3)
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
        raise RuntimeError(f"❌ متغير البيئة '{name}' غير موجود.")
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

# ==================== Gemini AI ====================
GEMINI_API_KEY = _get_env("GEMINI_API_KEY", default="")
ENABLE_GEMINI_ANALYSIS = _get_bool("ENABLE_GEMINI_ANALYSIS", default=True)
GEMINI_MODEL = "gemini-flash-latest"
GEMINI_FALLBACK_MODELS = [
    "gemini-flash-latest",
    "gemini-2.5-flash-lite",
    "gemini-2.5-flash",
    "gemini-flash-lite-latest",
]
GEMINI_API_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"

# ==================== Groq AI ====================
GROQ_API_KEY = _get_env("GROQ_API_KEY", default="")
ENABLE_GROQ_ANALYSIS = _get_bool("ENABLE_GROQ_ANALYSIS", default=True)
GROQ_MODEL = "openai/gpt-oss-120b"
GROQ_API_BASE_URL = "https://api.groq.com/openai/v1"

# ==================== SambaNova (معطل) ====================
SAMBANOVA_API_KEY = _get_env("SAMBANOVA_API_KEY", default="")
ENABLE_SAMBANOVA_ANALYSIS = False
SAMBANOVA_MODEL = "Meta-Llama-3.3-70B-Instruct"
SAMBANOVA_API_BASE_URL = "https://api.sambanova.ai/v1"

# ==================== HuggingFace ====================
HUGGINGFACE_API_KEY = _get_env("HUGGINGFACE_API_KEY", default="")
ENABLE_HUGGINGFACE_ANALYSIS = _get_bool("ENABLE_HUGGINGFACE_ANALYSIS", default=True)
HUGGINGFACE_MODEL = "meta-llama/Llama-3.3-70B-Instruct"
HUGGINGFACE_API_BASE_URL = "https://router.huggingface.co/v1"

# ==================== OpenRouter ====================
OPENROUTER_API_KEY = _get_env("OPENROUTER_API_KEY", default="")
ENABLE_OPENROUTER_ANALYSIS = _get_bool("ENABLE_OPENROUTER_ANALYSIS", default=True)
OPENROUTER_MODEL = _get_env("OPENROUTER_MODEL", default="nvidia/nemotron-3-ultra-550b-a55b:free")
OPENROUTER_FALLBACK_MODELS = [
    "nvidia/nemotron-3-ultra-550b-a55b:free",
    "nvidia/nemotron-3-super-120b-a12b:free",
    "openrouter/free",
]
OPENROUTER_API_BASE_URL = "https://openrouter.ai/api/v1"

AI_PROVIDER = "gemini"
AI_FALLBACK_ENABLED = True

# ==================== Firebase Backup ====================
FIREBASE_KEY_JSON = _get_env("FIREBASE_KEY", default="")
FIREBASE_PROJECT_ID = _get_env("FIREBASE_PROJECT_ID", default="mybot1-backup-91f59")
ENABLE_FIREBASE_BACKUP = _get_bool("ENABLE_FIREBASE_BACKUP", default=True)
FIREBASE_BACKUP_INTERVAL = 30

# ==================== GitHub Backup (معطل) ====================
GITHUB_TOKEN = _get_env("GITHUB_TOKEN", default="")
GITHUB_REPO = _get_env("GITHUB_REPO", default="elmalakfahd2/mybot1")
GITHUB_BRANCH = _get_env("GITHUB_BRANCH", default="main")
ENABLE_AUTO_BACKUP = False
BACKUP_INTERVAL_MINUTES = 30

# ==================== إعدادات الملفات ====================
MEMORY_FILE = "trade_memory.json"
PROFIT_HISTORY_FILE = "profit_history.json"
OPEN_POSITIONS_FILE = "open_positions.json"
LEARNING_HISTORY_FILE = "learning_history.json"
TUNING_HISTORY_FILE = "tuning_history.json"

USE_TESTNET = _get_bool("USE_TESTNET", default=True)

# ==================== التداول ====================
TRADE_USDT = 10
LEVERAGE = 15
MAX_OPEN_POSITIONS = 4

# ==================== TP المتعدد ====================
ENABLE_MULTIPLE_TP = True
TP_MULTIPLE_LEVELS = [2.5, 3.5, 5.0]
TP_QUANTITY_RATIOS = [0.4, 0.35, 0.25]
SL_PERCENT = 1.3
TP_PERCENT = 2.5

# ==================== SL ديناميكي ====================
DYNAMIC_SL_ENABLED = True
SL_ATR_MULTIPLIER = 2.0
SL_MIN_PERCENT = 1.0
SL_MAX_PERCENT = 1.6

# ==================== إصلاح TP/SL ====================
VERIFY_TP_SL_AFTER_CREATION = True
TP_SL_MAX_RETRIES = 3
CLOSE_ON_TP_SL_FAIL = True
TP_SL_RETRY_DELAY_SECONDS = 1
MONITOR_TP_SL_INTERVAL = 60

# ==================== تنظيف الأوامر ====================
ENABLE_ORPHAN_CLEANUP = True
ORPHAN_CLEANUP_INTERVAL = 300

# ==================== فلتر السيولة ====================
ENABLE_VOLUME_FILTER = True
MIN_VOLUME_24H_USDT = 50000000
MIN_MARKET_CAP_RANK = 200

# ==================== شروط الدخول ====================
MIN_TIMEFRAME_ALIGNMENT = 2.5
MIN_VOLUME_FACTOR = 0.8
MIN_GROQ_CONFIDENCE = 55
MIN_CONFIDENCE_AUTO = 55
MIN_SIGNAL_STRENGTH = 4

# ==================== RSI ====================
RSI_BUY_HARD_REJECT = 90
RSI_SELL_HARD_REJECT = 10
RSI_BUY_WARNING = 78
RSI_SELL_WARNING = 22

# ==================== نظام النقاط ====================
MIN_SCORE_REQUIRED = 65
MIN_ORDER_BOOK_POINTS = 3
MIN_RSI_POINTS = 0

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

# ==================== فلتر الذاكرة ====================
# v5.7: صفقة SL كاملة برافعة 15x ≈ -2$. الحظر صار بنافذة زمنية (SYMBOL_BLOCK_*) وصفقات موثقة.
MEMORY_MIN_TRADES_FOR_SCORE = 2
MEMORY_MIN_WIN_RATE = 30
MEMORY_MAX_CONSECUTIVE_LOSSES = 2
MEMORY_MAX_LOSSES_TOTAL = 2
MEMORY_BLOCK_LOSS_THRESHOLD = -0.5
MEMORY_AVG_PNL_THRESHOLD = -0.2

# ==================== فلاتر ====================
ENABLE_ORDER_BOOK_FILTER = True
MAX_SPREAD_PERCENT = 0.15
MIN_DEPTH_MULTIPLIER = 15

ENABLE_FUNDING_OI_FILTER = True
FUNDING_RATE_EXTREME_PERCENT = 0.05

ENABLE_CORRELATION_FILTER = False
MAX_CORRELATION = 0.75
ENABLE_OPPOSITE_DIRECTION_FILTER = False

ENABLE_DAILY_DRAWDOWN_LIMIT = True     # v5.7: مفعل (من دخل Binance الحقيقي)
DAILY_MAX_LOSS_USDT = 7.0              # توقف حتى منتصف الليل عند خسارة صافية 7$ في اليوم
DAILY_MAX_LOSS_PERCENT = 5.0           # أو 5% من رصيد المحفظة (أيهما أقرب)

# ==================== Trailing SL ====================
TRAILING_SL_ENABLED = True
TRAILING_SL_TRIGGER = 1.0
TRAILING_SL_DISTANCE = 0.5
BREAKEVEN_TRIGGER = 1.2
BREAKEVEN_OFFSET_PERCENT = 0.1

# ==================== الحماية ====================
MAX_CONSECUTIVE_LOSSES = 3
PAUSE_DURATION_MINUTES = 30

ENABLE_TRADE_MEMORY = True
COMMISSION_RATE = 0.0004

# ==================== كشف حالة السوق ====================
ENABLE_MARKET_REGIME = True
MARKET_REGIME_CACHE_SECONDS = 300
BLOCK_IN_STRONG_BEARISH = False
BLOCK_IN_STRONG_BULLISH_SELL = False

# ==================== أوقات التداول ====================
ENABLE_TIME_FILTER = False
GOOD_HOURS = [8, 9, 10, 11, 12, 13, 14, 15, 16, 17]
AVOID_HOURS = [0, 1, 2, 3, 4, 5]

# ==================== المسح ====================
AUTO_SCAN_INTERVAL = 900
TOP_SYMBOLS_TO_SCAN = 20

# ==================== 🔥 Cooldown (معدل) ====================
COOLDOWN_MINUTES = 5
COOLDOWN_MULTIPLIER_AFTER_LOSS = 2
COOLDOWN_MINUTES_AFTER_LOSS = 60     # ← كان 30

# ==================== الفريمات ====================
TIMEFRAMES = ['1m', '3m', '5m', '15m']
PRIMARY_TIMEFRAME = '5m'
CONFIRMATION_TIMEFRAME = '15m'

# ==================== 🔥 AI Settings (معدل) ====================
GROQ_SEND_FULL_DATA = True
GROQ_MIN_SCORE_BEFORE_CALL = 55       # ← كان 25 (يقلل استدعاءات AI بـ 70%)
GROQ_REJECT_IS_VETO = True

# ==================== التنفيذ ====================
ENABLE_AUTO_EXECUTION = True

ENABLE_DETAILED_LOGGING = True
LOG_LEVEL = "INFO"
REQUEST_TIMEOUT = 90
MAX_RETRIES = 3

# ==================== البيانات اللحظية ====================
ENABLE_REALTIME_DATA = False
REALTIME_ADJUSTMENT_ENABLED = True
REALTIME_MIN_ADJUSTMENT = -5
REALTIME_MAX_ADJUSTMENT = 10
REALTIME_PRESSURE_WINDOW = 30
REALTIME_DEPTH_LEVELS = 20
REALTIME_LIQUIDATION_THRESHOLD = 50000
REALTIME_MAX_SUBSCRIPTIONS = 25

# ==================== التعلم التلقائي ====================
ENABLE_AUTO_LEARNING = True
AUTO_LEARN_INTERVAL_HOURS = 12
AUTO_LEARN_MIN_TRADES = 20
AUTO_LEARN_MIN_PER_SYMBOL = 3
AUTO_TUNE_WEIGHTS = False   # v5.7: معطل - التعلم الفعلي عبر ADAPTIVE_*
AUTO_RESTART_AFTER_TUNE = False
AUTO_PROTECTION_ENABLED = True
DAILY_REPORT_HOUR = 10
AUTO_LEARN_MAX_ADJUSTMENT = 0.30
AUTO_LEARN_BACKUP_ENABLED = True

# ==================== الحماية الذاتية ====================
AUTO_PAUSE_ON_LOSS_STREAK = 4
AUTO_PAUSE_DURATION_MINUTES = 60
AUTO_REDUCE_RISK_ON_LOSS = True
AUTO_RISK_REDUCTION_FACTOR = 0.5

# ==================== التقارير ====================
ENABLE_DAILY_REPORT = True
ENABLE_WEEKLY_REPORT = True
REPORT_INCLUDE_SUGGESTIONS = True


# ==================== 🔥 v5.7: الحماية والاستمرارية ====================
LOSS_EPSILON = 0.10                     # |الصافي| أقل من هذا = تعادل (لا يُعد خسارة ولا ربحاً)

# إيقاف متصاعد: (عدد الخسائر المتتالية, دقائق الإيقاف)
PAUSE_ESCALATION = [(3, 60), (5, 240), (7, 720)]
STREAK_RESET_HOURS = 24                 # تصفير عداد الخسائر بعد 24 ساعة بلا خسارة
AUTO_REDUCE_RISK_ON_LOSS = True
RISK_REDUCE_AFTER_LOSSES = 3            # بعد 3 خسائر متتالية
AUTO_RISK_REDUCTION_FACTOR = 0.5        # حجم الصفقة 50%

STALL_RESTART_MINUTES = 30              # إعادة تشغيل العملية إن تجمّد الماسح/المراقب

# ==================== 🔥 v5.7: حظر العملات المؤقت ====================
SYMBOL_BLOCK_WINDOW_HOURS = 48          # الصفقات الأقدم من هذا لا تُحسب
SYMBOL_BLOCK_LOSS_USDT = 3.0            # خسارتان متتاليتان بمجموع أسوأ من -3$
SYMBOL_BLOCK_TOTAL_LOSS_USDT = 6.0      # أو إجمالي أسوأ من -6$ في النافذة

# ==================== 🔥 v5.7: التعلم التكيفي (يؤثر على القرار فعلاً) ====================
ENABLE_ADAPTIVE_RULES = True
ADAPTIVE_MIN_TRADES = 12                # أقل عدد صفقات موثقة قبل تفعيل أي قاعدة
ADAPTIVE_LOOKBACK_DAYS = 14
ADAPTIVE_RECENT_WINDOW = 15             # نافذة الأداء الأخير
ADAPTIVE_MAX_SCORE_BOOST = 10           # أقصى رفع لحد النقاط بسبب الأداء الضعيف
ADAPTIVE_MAX_TOTAL_BOOST = 12           # سقف الرفع الكلي (أداء + اتجاه)
ADAPTIVE_MIN_TRADES_PER_DIRECTION = 6
ADAPTIVE_MIN_TRADES_PER_HOUR = 10       # كان 4: حظر ساعة من 4-5 صفقات ضوضاء إحصائية

# ==================== 🔥 v5.8: من تحليل 65 صفقة موثقة ====================
# عدد الصفقات المفتوحة بنفس الاتجاه عند الدخول مقابل النتيجة:
#   0 → نجاح 52% | 1 → 44% | 2 → 33% | 3 → 25%
MAX_SAME_DIRECTION_POSITIONS = 1
