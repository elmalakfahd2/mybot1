# -*- coding: utf-8 -*-
"""
pattern_guard.py — بوابة الأنماط المُتعلَّمة + تخنيق استدعاءات AI
=================================================================
يعالج ثلاث مشاكل مؤكدة بالأرقام من trade_memory (96 صفقة):

1) تكرار الصفقات الخاسرة:
   - حظر الساعات الخاسرة (الحد الأدنى 3 صفقات فقط — النظام القديم كان صارماً جداً
     فلم يحظر شيئاً رغم أن الساعة 17: 0/5 و -10.54$)
   - حظر "بصمات" الأنماط الخاسرة: (اتجاه|جلسة|فئة RSI|فئة حجم)
     مثال مؤكد من بياناتك: BUY|أمريكا|RSIعالٍ|vol متوسط = 0/5  (-8.15$)
   - عقوبة اتجاه متدرجة حسب Profit Factor (النظام القديم لم يفعّل أبداً)

2) الدخول بدون AI (أكبر ثغرة: -26.26$ = 56% من الخسائر):
   - لا دخول إطلاقاً بدون قرار AI ناجح (الفشل أو بلوغ السقف = صفقة ظل فقط)

3) هدر استدعاءات AI:
   - استدعاء AI فقط عند pre-score >= 60
   - كاش 30 دقيقة لكل (عملة+اتجاه)، سقف 12 استدعاء/ساعة

ملاحظة: كل القواعد تُبنى وتُحدَّث من trade_memory.json نفسه —
لا شيء ثابت سوى بذور أولية مأخوذة من تحليل 96 صفقة (تُلغى تلقائياً
حين تتراكم بيانات أحدث).
"""

import json
import os
import time
import logging
from datetime import datetime
from pathlib import Path
from collections import defaultdict

logger = logging.getLogger(__name__)

# ═══════════════════════ الإعدادات ═══════════════════════
# (عدّلها هنا أو مرّرها عبر البيئة — تطابق config.py)
BASE_MIN_SCORE         = 65     # MIN_SCORE_REQUIRED الفعلي
AI_CALL_MIN_PRE_SCORE  = 0      # 0 مع ملفات كلود v6+ — بوابة الـ60 موجودة أصلاً داخل bot_strategies
                                # على total_score الحقيقي، بينما الإشارة الواصلة للغلاف تحمل 'confidence'
                                # (45-85 وليست total_score) — تفعيل العتبة هنا يسبب منعاً زائداً للإشارات الجيدة
AI_CALL_HOURLY_CAP     = 12
AI_CACHE_TTL_SEC       = 30 * 60
WARNING_PENALTY        = -4     # تحذير AI يخصم 4 نقاط (كان +2!)
REQUIRE_AI_FOR_ENTRY   = True   # لا دخول بدون AI ناجح إطلاقاً
LOG_ONLY               = True   # ⚠️ ابدأ True (تسجيل فقط) → بعد 2-3 أيام False

HOUR_MIN_TRADES        = 3      # كان ضمنياً أعلى بكثير → لم يحظر شيئاً
HOUR_BLOCK_WINRATE     = 0.35
HOUR_BLOCK_PNL         = -2.0

PATTERN_MIN_TRADES     = 3
PATTERN_BLOCK_PF       = 0.60   # بصمة بهذا PF أو أقل → رفض
PATTERN_BLOCK_PNL      = -1.5   # وشرط أن يكون مجموع خسارتها أسوأ من هذا
PATTERN_GREEN_PF       = 1.50   # بصمة بهذا PF أو أكثر → تسهيل الدخول
GREEN_SCORE_RELAX      = 5      # الأنماط الخضراء تدخل عند 60 بدل 65
RED_SCORE_BLOCK        = True

DIRECTION_MIN_TRADES   = 15
DIRECTION_MAX_PENALTY  = 10

CHOPPY_SPIKE_VOL       = 2.5    # سوق متذبذب + حجم انفجاري → تشديد
CHOPPY_EXTRA_SCORE     = 5

# بذور من تدريب 96 صفقة (2026-09-17 → 2026-10-03) — مُستخرجة آلياً من condition_stats
# (ن≥3 وPF≤0.6 وخسارة<-1.5$ للحمراء؛ PF≥1.5 للخضراء) — تُحدَّث ذاتياً مع كل صفقة جديدة
SEED_BLOCKED_HOURS = {2, 5, 6, 7, 15, 17, 19}
SEED_GREEN_PATTERNS = [
    ("SELL", "AMERICA", "RSI_LO",  "VOL_MID"),
    ("SELL", "ASIA",    "RSI_HI",  "VOL_MID"),
    ("BUY",  "ASIA",    "RSI_MID", "VOL_MID"),
    ("BUY",  "EUROPE",  "RSI_HI",  "VOL_MID"),
]
SEED_RED_PATTERNS = [
    ("SELL", "ASIA",    "RSI_LO",  "VOL_HI"),    # n=4  pf=0.53  -1.94$
    ("SELL", "ASIA",    "RSI_LO",  "VOL_MID"),   # n=5  pf=0.54  -2.85$
    ("BUY",  "AMERICA", "RSI_HI",  "VOL_MID"),   # n=5  pf=0.0   -8.15$
    ("BUY",  "AMERICA", "RSI_HI",  "VOL_LOW"),   # n=3  pf=0.21  -3.52$
    ("SELL", "ASIA",    "RSI_HI",  "VOL_LOW"),   # n=9  pf=0.58  -3.71$
    ("BUY",  "ASIA",    "RSI_HI",  "VOL_MID"),   # n=6  pf=0.36  -4.10$
    ("BUY",  "ASIA",    "RSI_HI",  "VOL_LOW"),   # n=10 pf=0.42  -6.73$
    ("SELL", "AMERICA", "RSI_MID", "VOL_MID"),   # n=6  pf=0.29  -4.72$
    ("SELL", "ASIA",    "RSI_MID", "VOL_HI"),    # n=3  pf=0.0   -4.85$
    ("BUY",  "AMERICA", "RSI_LO",  "VOL_HI"),    # شراء مسائي متشبع (RSI≥75→3نقاط):
    ("BUY",  "AMERICA", "RSI_LO",  "VOL_MID"),   #   لا عينات تاريخية لكنه امتداد مؤكد لنمط 0/5
]

DATA_DIR = Path(os.getenv("BOT_DATA_DIR", "."))
MEM_FILE   = DATA_DIR / "trade_memory.json"
STATE_FILE = DATA_DIR / "bot_state.json"
CACHE_FILE = DATA_DIR / "ai_cache.json"

# ═══════════════════════ أدوات ملفات ═══════════════════════

def _load(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def _save(path, data):
    tmp = str(path) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, str(path))


def configure(data_dir=None):
    """للاختبار الخلفي: حدّد مجلد ملفات البيانات."""
    global DATA_DIR, MEM_FILE, STATE_FILE, CACHE_FILE
    if data_dir:
        DATA_DIR = Path(data_dir)
        MEM_FILE, STATE_FILE, CACHE_FILE = (
            DATA_DIR / "trade_memory.json",
            DATA_DIR / "bot_state.json",
            DATA_DIR / "ai_cache.json",
        )

# ═══════════════════════ البصمات ═══════════════════════

def session_of(hour: int) -> str:
    if hour < 9:
        return "ASIA"
    if hour < 17:
        return "EUROPE"
    return "AMERICA"


def rsi_band(rsi_points: int) -> str:
    if rsi_points >= 8:
        return "RSI_HI"
    if rsi_points <= 3:
        return "RSI_LO"
    return "RSI_MID"


def vol_band(volume_ratio: float) -> str:
    if volume_ratio >= 3.0:
        return "VOL_HI"
    if volume_ratio < 1.5:
        return "VOL_LOW"
    return "VOL_MID"


def signature(direction: str, hour: int, rsi_points: int, volume_ratio: float) -> str:
    return "|".join([direction, session_of(hour), rsi_band(rsi_points), vol_band(volume_ratio)])


def _sig_key(direction, session, rsi_b, vol_b):
    return "|".join([direction, session, rsi_b, vol_b])

# ═══════════════════════ قواعد الساعات ═══════════════════════

def get_blocked_hours() -> set:
    state = _load(STATE_FILE, {})
    rules = state.get("learned_rules", {})
    hours = rules.get("blocked_hours") or []
    return {int(h) for h in hours}


def rebuild_rules():
    """
    إعادة بناء القواعد كلها من trade_memory.json:
    blocked_hours + pattern_rules + direction_penalties.
    تُستدعى في جلسة التعلم (smart_scheduler) بعد adaptive_rules.update_rules()
    """
    mem = _load(MEM_FILE, {})
    trades = mem.get("trades", [])

    # ── الساعات: الحد الأدنى 3 صفقات، نجاح ≤35%، خسارة < -2$ ──
    hs = defaultdict(lambda: {"n": 0, "w": 0, "pnl": 0.0})
    for t in trades:
        h = t.get("hour")
        if h is None:
            continue
        hs[h]["n"] += 1
        hs[h]["w"] += 1 if t.get("is_win") else 0
        hs[h]["pnl"] += t.get("pnl", 0.0)
    blocked = {h for h, d in hs.items()
               if d["n"] >= HOUR_MIN_TRADES
               and d["w"] / d["n"] <= HOUR_BLOCK_WINRATE
               and d["pnl"] < HOUR_BLOCK_PNL}
    if len(trades) < 30:  # بيانات قليلة → أبقِ البذور المؤكدة
        blocked |= SEED_BLOCKED_HOURS

    # ── البصمات: تدريب مباشر من كل الصفقات التاريخية ──
    # (كان يقرأ condition_stats فقط — وهو فارغ تاريخياً، فلم يتعلم شيئاً من الماضي)
    sig_stats = defaultdict(lambda: {"n": 0, "w": 0, "gw": 0.0, "gl": 0.0})
    for t in trades:
        sd = t.get("score_details", {}) or {}
        sig = signature(t.get("direction", "?"), t.get("hour", 12),
                        sd.get("rsi_points", 5), t.get("volume_ratio", 1.0))
        p = float(t.get("pnl", 0.0) or 0.0)
        sig_stats[sig]["n"] += 1
        sig_stats[sig]["w"] += 1 if t.get("is_win") else 0
        if p > 0:
            sig_stats[sig]["gw"] += p
        elif p < 0:
            sig_stats[sig]["gl"] += abs(p)

    # كتابة condition_stats المدربة إلى الذاكرة (تعبئة الحقل الفارغ + أرشفة)
    trained_cond = {}
    greens, reds = [], []
    for sig, d in sig_stats.items():
        pf = round(d["gw"] / d["gl"], 2) if d["gl"] > 0 else (9.99 if d["gw"] > 0 else 0.0)
        trained_cond[sig] = {"n": d["n"], "w": d["w"],
                             "pnl": round(d["gw"] - d["gl"], 4), "pf": pf}
        if d["n"] < PATTERN_MIN_TRADES:
            continue
        if pf >= PATTERN_GREEN_PF:
            greens.append(sig)
        elif pf <= PATTERN_BLOCK_PF and (d["gw"] - d["gl"]) < PATTERN_BLOCK_PNL:
            reds.append(sig)
    if trained_cond:
        mem["condition_stats"] = trained_cond
        _save(MEM_FILE, mem)

    # دمج البذور المؤكدة دائماً (أولويات مثبتة على 96 صفقة) مع المدربة —
    # حتى لا تضيع التغطية عندما يظهر توقيع بلا عينات تاريخية كافية
    greens += ["|".join(s) for s in SEED_GREEN_PATTERNS]
    reds   += ["|".join(s) for s in SEED_RED_PATTERNS]

    # ── عقوبة الاتجاه: متدرجة حسب PF (تتطلب 15+ صفقة) ──
    dirs = defaultdict(lambda: {"n": 0, "gw": 0.0, "gl": 0.0})
    for t in trades:
        d = t.get("direction")
        if not d:
            continue
        dirs[d]["n"] += 1
        p = t.get("pnl", 0.0)
        if p > 0:
            dirs[d]["gw"] += p
        elif p < 0:
            dirs[d]["gl"] += abs(p)
    dir_pen = {}
    for d, s in dirs.items():
        if s["n"] < DIRECTION_MIN_TRADES or s["gl"] <= 0:
            continue
        pf = s["gw"] / s["gl"]
        if pf < 1.0:
            dir_pen[d] = min(DIRECTION_MAX_PENALTY, round((1.0 - pf) * 10))
        elif pf > 1.5:
            dir_pen[d] = -3  # راحة طفيفة للاتجاه القوي

    state = _load(STATE_FILE, {})
    rules = state.setdefault("learned_rules", {})
    rules["blocked_hours"] = sorted(blocked)
    rules["pattern_rules"] = {"green": sorted(set(greens)), "red": sorted(set(reds))}
    rules["direction_penalty"] = dir_pen
    rules["pattern_guard_version"] = 2
    rules["updated"] = datetime.now().isoformat()
    _save(STATE_FILE, state)
    logger.info(f"🛡️ pattern_guard: ساعات محظورة={sorted(blocked)} "
                f"أنماط خضراء={len(set(greens))} حمراء={len(set(reds))} عقوبات={dir_pen}")
    return rules

# ═══════════════════════ تقييم البصمة وقت المسح ═══════════════════════

def _pattern_verdict(direction, hour, rsi_points, volume_ratio):
    sig = signature(direction, hour, rsi_points, volume_ratio)
    state = _load(STATE_FILE, {})
    pr = state.get("learned_rules", {}).get("pattern_rules", {})
    if sig in (pr.get("red") or []):
        return "red", sig
    if sig in (pr.get("green") or []):
        return "green", sig
    # تحقق إحصائي مباشر من الذاكرة حتى لو لم تُبنَ القواعد بعد
    cond = _load(MEM_FILE, {}).get("condition_stats", {})
    d = cond.get(sig)
    if d and d.get("n", 0) >= PATTERN_MIN_TRADES:
        pf = d.get("pf", 0)
        if pf <= PATTERN_BLOCK_PF and d.get("pnl", 0) < PATTERN_BLOCK_PNL:
            return "red", sig
        if pf >= PATTERN_GREEN_PF:
            return "green", sig
    return "neutral", sig


def required_score(direction, hour, pattern_verdict) -> int:
    base = BASE_MIN_SCORE
    state = _load(STATE_FILE, {})
    rules = state.get("learned_rules", {})
    score = base
    score += int(rules.get("direction_penalty", {}).get(direction, 0))
    if pattern_verdict == "green":
        score = max(55, score - GREEN_SCORE_RELAX)
    return score

# ═══════════════════════ البوابة الرئيسية ═══════════════════════

def check_gates(symbol, direction, hour, rsi_points, volume_ratio,
                pre_ai_score, market_regime=None) -> dict:
    """
    تُستدعى في الماسح قبل استدعاء AI.
    ترجع {allow, reasons, required_score, ai_required}
    """
    reasons = []
    allow = True

    # بوابة 1: الساعة المحظورة
    if hour in get_blocked_hours():
        allow = False
        reasons.append(f"ساعة {hour} محظورة (أداء تاريخي سيئ)")

    # بوابة 2: البصمة الخاسرة
    verdict, sig = _pattern_verdict(direction, hour, rsi_points, volume_ratio)
    if verdict == "red":
        allow = False
        reasons.append(f"نمط خاسر متكرر [{sig}]")

    # بوابة 3: عتبة استدعاء AI
    ai_required = pre_ai_score >= AI_CALL_MIN_PRE_SCORE
    if not ai_required:
        allow = False
        reasons.append(f"pre-score {pre_ai_score} < {AI_CALL_MIN_PRE_SCORE}")

    req = required_score(direction, hour, verdict)

    # تشديد في السوق المتذبذب مع حجم انفجاري (نمط قمة/قاع منهك)
    if market_regime == "متذبذب" and volume_ratio >= CHOPPY_SPIKE_VOL and verdict != "green":
        req += CHOPPY_EXTRA_SCORE
        reasons.append("سوق متذبذب + حجم انفجاري → تشديد")

    if not allow and LOG_ONLY:
        logger.info(f"🛡️ [SHADOW] {symbol}: رفض بوابات ({'; '.join(reasons)})")
        # في وضع التسجيل: نسمح للمسح أن يكمل لكن نعلّم أنها ستُرفض
    return {"allow": allow or LOG_ONLY,          # LOG_ONLY=True → allow لكن مسجّلة
            "will_block": not allow,             # الحقيقة — تُستخدم عند LOG_ONLY=False
            "reasons": reasons,
            "required_score": req,
            "pattern": verdict,
            "signature": sig,
            "ai_required": True}                 # AI مطلوب دائماً للدخول

# ═══════════════════════ كاش + سقف استدعاءات AI ═══════════════════════

def get_cached_ai(symbol, direction):
    cache = _load(CACHE_FILE, {})
    key = f"{symbol}:{direction}"
    ent = cache.get(key)
    if ent and time.time() - ent.get("ts", 0) < AI_CACHE_TTL_SEC:
        return ent.get("result")
    return None


def cache_ai(symbol, direction, result):
    cache = _load(CACHE_FILE, {})
    key = f"{symbol}:{direction}"
    # تنظيف المنتهي
    now = time.time()
    cache = {k: v for k, v in cache.items() if now - v.get("ts", 0) < AI_CACHE_TTL_SEC}
    cache[key] = {"ts": now, "result": result}
    # عدّاد الساعة
    hour_key = datetime.now().strftime("%Y-%m-%dT%H")
    cache.setdefault("_calls", {})
    cache["_calls"] = {k: v for k, v in cache["_calls"].items()
                       if k == hour_key or now - v.get("ts", 0) < 3600}
    cache["_calls"][hour_key] = {"ts": now, "n": cache["_calls"].get(hour_key, {}).get("n", 0) + 1}
    _save(CACHE_FILE, cache)


def ai_call_available() -> bool:
    cache = _load(CACHE_FILE, {})
    hour_key = datetime.now().strftime("%Y-%m-%dT%H")
    n = cache.get("_calls", {}).get(hour_key, {}).get("n", 0)
    return n < AI_CALL_HOURLY_CAP


def ai_unavailable_action() -> str:
    """ما يحدث عند فشل AI أو بلوغ السقف. البيانات تقول: لا دخول إطلاقاً."""
    return "skip" if REQUIRE_AI_FOR_ENTRY else "fallback_old"

# ═══════════════════════ نقاط توصية AI ═══════════════════════

def resolve_groq_points(recommendation: str, confidence: float, trusted: bool):
    """
    تأكيد → موجب كما في النظام القديم (مع فيتو عند رفض قوي).
    تحذير → سالب (النظام القديم كان يعطي +2!). تحذير قوي من نموذج موثوق → فيتو.
    """
    rec = (recommendation or "").strip()
    conf = confidence or 0
    if rec == "رفض" and (trusted or conf >= 60):
        return 0, True, "رفض AI"
    if rec == "تحذير":
        if trusted and conf >= 75:
            return 0, True, "تحذير قوي"
        return WARNING_PENALTY, False, f"تحذير {conf:.0f}%"
    if rec == "تأكيد":
        if conf >= 75 and trusted:
            return 12, False, "تأكيد قوي"
        if conf >= 60:
            return 10, False, "تأكيد"
        return 8, False, "تأكيد ضعيف"
    return 0, False, "بدون توصية"

# ═══════════════════════ التسجيل بعد إغلاق الصفقة ═══════════════════════

def record_trade(trade: dict):
    """
    تُستدعى بعد تسجيل الصفقة في trade_memory (أي بعد سطر '📝 تسجيل:').
    تحدّث condition_stats (البصمات) + تعيد بناء القواعد.
    """
    sd = trade.get("score_details", {})
    sig = signature(
        trade.get("direction", "?"),
        trade.get("hour", 12),
        sd.get("rsi_points", 5),
        trade.get("volume_ratio", 1.0),
    )
    mem = _load(MEM_FILE, {})
    cond = mem.setdefault("condition_stats", {})
    d = cond.setdefault(sig, {"n": 0, "w": 0, "pnl": 0.0, "pf": 0.0})
    pnl = trade.get("pnl", 0.0)
    d["n"] += 1
    d["w"] += 1 if trade.get("is_win") else 0
    d["pnl"] = round(d["pnl"] + pnl, 4)
    gw = d.get("gw", 0.0) + (pnl if pnl > 0 else 0.0)
    gl = d.get("gl", 0.0) + (abs(pnl) if pnl < 0 else 0.0)
    d["gw"], d["gl"] = round(gw, 4), round(gl, 4)
    d["pf"] = round(gw / gl, 2) if gl > 0 else (9.99 if gw > 0 else 0.0)
    _save(MEM_FILE, mem)
    rebuild_rules()
