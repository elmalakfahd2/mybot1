# -*- coding: utf-8 -*-
"""
config.py - الإعدادات النهائية v4.2.1
🔒 آمن للرفع على GitHub: لا يحتوي على أي مفاتيح حقيقية.

🔧 التعديلات v4.2.1 (محسّنة للسوق الخامل):
    - 🔥 MIN_SCORE_REQUIRED: 65 → 55
    - 🔥 MIN_VOLUME_FACTOR: 0.99 → 0.4
    - 🔥 MIN_TIMEFRAME_ALIGNMENT: 4.0 → 2.5
    - 🔥 MIN_CONFIDENCE_AUTO: 55 → 50
    - 🔥 MIN_GROQ_CONFIDENCE: 60 → 55
    - 🔥 MIN_SIGNAL_STRENGTH: 5 → 4

🔧 التعديلات v4.2.0:
    - OpenRouter (AI أساسي)
    - تصحيح نماذج Gemini
    - Firebase Backup
    - Memory Blacklist محسّن
    - Cooldown ذكي

📅 آخر تعديل: 2026-09-27
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

# ==================== 🔥 OpenRouter (AI أساسي) ====================
OPENROUTER_API_KEY = _get_env("OPENROUTER_API_KEY", default="")
ENABLE_OPENROUTER_ANALYSIS = _get_bool("ENABLE_OPENROUTER_ANALYSIS", default=True)
OPENROUTER_MODEL = _get_env("OPENROUTER_MODEL", default="nvidia/nemotron-3-ultra-550b-a55b:free")
OPENROUTER_FALLBACK_MODELS = [
    "nvidia/nemotron-3-ultra-550b-a55b:free",
    "nvidia/nemotron-3-super-120b-a12b:free",
    "openrouter/free",
]
OPENROUTER_API_BASE_URL = "https://openrouter.ai/api/v1"

# ==================== Groq AI (احتياطي) ====================
GROQ_API_KEY = _get_env("GROQ_API_KEY", default="")
ENABLE_GROQ_ANALYSIS = _get_bool("ENABLE_GROQ_ANALYSIS", default=True)
GROQ_MODEL = "openai/gpt-oss-120b"
GROQ_API_BASE_URL = "https://api.groq.com/openai/v1"

# ==================== 🔥 Gemini AI (احتياطي 2) ====================
GEMINI_API_KEY = _get_env("GEMINI_API_KEY", default="")
ENABLE_GEMINI_ANALYSIS = _get_bool("ENABLE_GEMINI_ANALYSIS", default=True)
GEMINI_MODEL = "gemini-2.0-flash-exp"
GEMINI_FALLBACK_MODELS = [
    "gemini-2.0-flash-exp",
    "gemini-1.5-flash",
    "gemini-1.5-flash-8b",
]
GEMINI_API_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"

# 🔥 استراتيجية AI: openrouter / gemini / groq / auto
# ⚠️ غيرها من Railway: AI_PROVIDER=groq
AI_PROVIDER = _get_env("AI_PROVIDER", default="openrouter")
AI_FALLBACK_ENABLED = True

# ==================== 🔥 Firebase Backup ====================
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
TRADE_USDT = 15
LEVERAGE = 10
MAX_OPEN_POSITIONS = 5

# ==================== TP المتعدد (v4.1.5 - يعمل جيداً) ====================
ENABLE_MULTIPLE_TP = True
TP_MULTIPLE_LEVELS = [1.2, 2.0, 3.0]
TP_QUANTITY_RATIOS = [0.5, 0.3, 0.2]
SL_PERCENT = 2.0
TP_PERCENT = 1.2

# ==================== SL ديناميكي (v4.1.5) ====================
DYNAMIC_SL_ENABLED = True
SL_ATR_MULTIPLIER = 2.5
SL_MIN_PERCENT = 1.5
SL_MAX_PERCENT = 3.0

# ==================== إصلاح TP/SL ====================
VERIFY_TP_SL_AFTER_CREATION = True
TP_SL_MAX_RETRIES = 3
CLOSE_ON_TP_SL_FAIL = True
TP_SL_RETRY_DELAY_SECONDS = 1
MONITOR_TP_SL_INTERVAL = 60

# ==================== تنظيف الأوامر اليتيمة ====================
ENABLE_ORPHAN_CLEANUP = True
ORPHAN_CLEANUP_INTERVAL = 300

# ==================== فلتر السيولة ====================
ENABLE_VOLUME_FILTER = True
MIN_VOLUME_24H_USDT = 50000000
MIN_MARKET_CAP_RANK = 200

# ==================== 🔥 شروط الدخول (v4.2.1 - محسّنة) ====================
MIN_TIMEFRAME_ALIGNMENT = 2.5      # 🔥 من 4.0 → 2.5
MIN_VOLUME_FACTOR = 0.4            # 🔥 من 0.99 → 0.4
MIN_GROQ_CONFIDENCE = 55           # 🔥 من 60 → 55
MIN_CONFIDENCE_AUTO = 50           # 🔥 من 55 → 50
MIN_SIGNAL_STRENGTH = 4            # 🔥 من 5 → 4

# ==================== 🔥 RSI - Scalp Mode ====================
RSI_BUY_HARD_REJECT = 90
RSI_SELL_HARD_REJECT = 10
RSI_BUY_WARNING = 78
RSI_SELL_WARNING = 22

# ==================== 🔥 نظام النقاط (v4.2.1) ====================
MIN_SCORE_REQUIRED = 55            # 🔥 من 65 → 55
MIN_ORDER_BOOK_POINTS = 2
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

# ==================== 🔥 Memory Blacklist ====================
MEMORY_MIN_TRADES_FOR_SCORE = 3
MEMORY_MIN_WIN_RATE = 30
MEMORY_MAX_CONSECUTIVE_LOSSES = 3
MEMORY_MAX_LOSSES_TOTAL = 3
MEMORY_BLOCK_LOSS_THRESHOLD = -1.0
MEMORY_AVG_PNL_THRESHOLD = -0.5

# ==================== فلتر دفتر الأوامر والتنفيذ ====================
ENABLE_ORDER_BOOK_FILTER = True
MAX_SPREAD_PERCENT = 0.15
MIN_DEPTH_MULTIPLIER = 10

# ==================== فلتر Funding Rate + Open Interest ====================
ENABLE_FUNDING_OI_FILTER = True
FUNDING_RATE_EXTREME_PERCENT = 0.05

# ==================== فلتر الارتباط (معطل مؤقتاً) ====================
ENABLE_CORRELATION_FILTER = False
MAX_CORRELATION = 0.75

# ==================== منع الصفقات المتعاكسة (معطل مؤقتاً) ====================
ENABLE_OPPOSITE_DIRECTION_FILTER = False

# ==================== 🔥 قاطع الخسارة اليومية ====================
ENABLE_DAILY_DRAWDOWN_LIMIT = True
DAILY_MAX_LOSS_PERCENT = 15.0

# ==================== Trailing SL (v4.1.5) ====================
TRAILING_SL_ENABLED = True
TRAILING_SL_TRIGGER = 1.0
TRAILING_SL_DISTANCE = 0.5
BREAKEVEN_TRIGGER = 1.2
BREAKEVEN_OFFSET_PERCENT = 0.1

# ==================== الحماية ====================
MAX_CONSECUTIVE_LOSSES = 3
PAUSE_DURATION_MINUTES = 60

# ==================== ذاكرة الصفقات ====================
ENABLE_TRADE_MEMORY = True
COMMISSION_RATE = 0.0004

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

# ==================== 🔥 Cooldown ذكي ====================
COOLDOWN_MINUTES = 5
COOLDOWN_MULTIPLIER_AFTER_LOSS = 2
COOLDOWN_MINUTES_AFTER_LOSS = 15

# ==================== الفريمات ====================
TIMEFRAMES = ['1m', '3m', '5m', '15m']
PRIMARY_TIMEFRAME = '5m'
CONFIRMATION_TIMEFRAME = '15m'

# ==================== Groq AI Settings ====================
GROQ_SEND_FULL_DATA = True
GROQ_MIN_SCORE_BEFORE_CALL = 45
GROQ_REJECT_IS_VETO = True

# ==================== التنفيذ ====================
ENABLE_AUTO_EXECUTION = True

# ==================== إضافات ====================
ENABLE_DETAILED_LOGGING = True
LOG_LEVEL = "INFO"
REQUEST_TIMEOUT = 90
MAX_RETRIES = 3

# ==================== ⚡ البيانات اللحظية (WebSocket) ====================
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
AUTO_LEARN_INTERVAL_HOURS = 24
AUTO_LEARN_MIN_TRADES = 10
AUTO_LEARN_MIN_PER_SYMBOL = 3
AUTO_TUNE_WEIGHTS = True
AUTO_RESTART_AFTER_TUNE = False
AUTO_PROTECTION_ENABLED = True
DAILY_REPORT_HOUR = 10
AUTO_LEARN_MAX_ADJUSTMENT = 0.30
AUTO_LEARN_BACKUP_ENABLED = True

# ==================== الحماية الذاتية ====================
AUTO_PAUSE_ON_LOSS_STREAK = 5
AUTO_PAUSE_DURATION_MINUTES = 120
AUTO_REDUCE_RISK_ON_LOSS = True
AUTO_RISK_REDUCTION_FACTOR = 0.5

# ==================== التقارير ====================
ENABLE_DAILY_REPORT = True
ENABLE_WEEKLY_REPORT = True
REPORT_INCLUDE_SUGGESTIONS = True