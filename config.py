# -*- coding: utf-8 -*-
"""
config.py - الإعدادات النهائية v5.9 (Scalp Quick Wins)
🔒 آمن للرفع على GitHub.

🔧 التعديلات v5.9:
    - 🔥 استراتيجية "Scalp Quick Wins"
    - 🔥 TP1 مضغوط (0.8%)
    - 🔥 Breakeven سريع (0.4%)
    - 🔥 Cooldown ذكي (15 د + مضاعفة)
    - 🔥 RSI مشروط حسب النطاق

📅 آخر تعديل: 2026-09-26
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

# ==================== Groq AI ====================
GROQ_API_KEY = _get_env("GROQ_API_KEY", required=True)

# ==================== Gemini AI ====================
GEMINI_API_KEY = _get_env("GEMINI_API_KEY", default="")
ENABLE_GEMINI_ANALYSIS = _get_bool("ENABLE_GEMINI_ANALYSIS", default=True)
GEMINI_MODEL = "gemini-2.5-flash"
GEMINI_API_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"

AI_PROVIDER = "auto"
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

USE_TESTNET = _get_bool("USE_TESTNET", default=False)

# ==================== التداول ====================
TRADE_USDT = 15
LEVERAGE = 10
MAX_OPEN_POSITIONS = 5

# ==================== 🔥 TP المتعدد - Scalp Quick Wins ====================
ENABLE_MULTIPLE_TP = True
TP_MULTIPLE_LEVELS = [0.8, 1.5, 2.5]      # 🔥 مضغوط للخطف السريع
TP_QUANTITY_RATIOS = [0.6, 0.25, 0.15]    # 🔥 60% للـ TP1 (خطف سريع)
SL_PERCENT = 1.2
TP_PERCENT = 0.8

# ==================== 🔥 SL ديناميكي - Scalp Mode ====================
DYNAMIC_SL_ENABLED = True
SL_ATR_MULTIPLIER = 2.0                    # من 2.5 → 2.0
SL_MIN_PERCENT = 0.8                       # من 1.2 → 0.8
SL_MAX_PERCENT = 1.5                       # من 2.0 → 1.5

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

# ==================== شروط الدخول ====================
MIN_TIMEFRAME_ALIGNMENT = 3.0
MIN_VOLUME_FACTOR = 0.5
MIN_GROQ_CONFIDENCE = 55
MIN_CONFIDENCE_AUTO = 55
MIN_SIGNAL_STRENGTH = 5

# ==================== 🔥 RSI - Scalp Mode ====================
# يسمح بـ RSI عالي لكن مع TP ضيق جداً
RSI_BUY_HARD_REJECT = 90                  # رفض فوق هذا
RSI_SELL_HARD_REJECT = 10                 # رفض تحت هذا
RSI_BUY_WARNING = 78                      # تحذير فوق هذا (يتطلب TP ضيق)
RSI_SELL_WARNING = 22                     # تحذير تحت هذا

# ==================== نظام النقاط ====================
MIN_SCORE_REQUIRED = 60                   # من 62 → 60 (مع RSI معقول)
MIN_ORDER_BOOK_POINTS = 0
MIN_RSI_POINTS = 0

SCORE_WEIGHTS = {
    'timeframe_alignment': 20,
    'volume': 15,
    'groq': 12,
    'rsi_ideal': 10,
    'momentum': 10,
    'price_action': 8,
    'market_regime': 5,
    'order_book': 10,
    'funding_oi': 10,
    'max_score': 100
}

# ==================== فلتر دفتر الأوامر ====================
ENABLE_ORDER_BOOK_FILTER = True
MAX_SPREAD_PERCENT = 0.20
MIN_DEPTH_MULTIPLIER = 5

# ==================== فلتر Funding Rate + Open Interest ====================
ENABLE_FUNDING_OI_FILTER = True
FUNDING_RATE_EXTREME_PERCENT = 0.05

# ==================== فلتر الارتباط ====================
ENABLE_CORRELATION_FILTER = True
MAX_CORRELATION = 0.80                    # من 0.75 → 0.80

# ==================== منع الصفقات المتعاكسة ====================
ENABLE_OPPOSITE_DIRECTION_FILTER = True

# ==================== قاطع الخسارة اليومية ====================
ENABLE_DAILY_DRAWDOWN_LIMIT = True
DAILY_MAX_LOSS_PERCENT = 10.0

# ==================== 🔥 Trailing SL - سريع للخطف ====================
TRAILING_SL_ENABLED = True
TRAILING_SL_TRIGGER = 0.6                 # 🔥 من 1.8 → 0.6 (بعد TP1 مباشرة)
TRAILING_SL_DISTANCE = 0.4                # 🔥 من 0.6 → 0.4 (ضيق)
BREAKEVEN_TRIGGER = 0.4                   # 🔥 من 1.5 → 0.4 (سريع جداً)
BREAKEVEN_OFFSET_PERCENT = 0.05           # من 0.1 → 0.05

# ==================== الحماية ====================
MAX_CONSECUTIVE_LOSSES = 4
PAUSE_DURATION_MINUTES = 45

# ==================== ذاكرة الصفقات ====================
ENABLE_TRADE_MEMORY = True
MEMORY_MIN_TRADES_FOR_SCORE = 3
MEMORY_MIN_WIN_RATE = 30
MEMORY_MAX_CONSECUTIVE_LOSSES = 3
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

# ==================== 🔥 Cooldown ذكي ====================
COOLDOWN_MINUTES = 15                     # 🔥 من 5 → 15 (أطول)
COOLDOWN_MULTIPLIER_AFTER_LOSS = 2        # 🔥 مضاعفة بعد خسارة
COOLDOWN_MINUTES_AFTER_LOSS = 30          # 🔥 تبريد بعد خسارة مباشرة

# ==================== الفريمات ====================
TIMEFRAMES = ['1m', '3m', '5m', '15m']
PRIMARY_TIMEFRAME = '5m'
CONFIRMATION_TIMEFRAME = '15m'

# ==================== Groq AI ====================
ENABLE_GROQ_ANALYSIS = True
GROQ_MODEL = "openai/gpt-oss-120b"
GROQ_API_BASE_URL = "https://api.groq.com/openai/v1"
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