# -*- coding: utf-8 -*-
"""
pattern_guard.py — بوابة الأنماط المُتعلَّمة + تخنيق استدعاءات AI
=================================================================
v6.7 هجين: التعلم من الصفقات المغلقة/الموثقة فقط + وضع مراقبة أولاً (LOG_ONLY=True)
v6.6: 🔥 تفعيل فعلي (LOG_ONLY=False) — الأنماط الحمراء الخاسرة تُمنع والساعات
      الخاسرة تُحظر فعلياً (كان v6.5 يراقب ويسجل فقط)
v6.5: إصلاح سباق الكتابة — adaptive_rules يستبدل learned_rules كاملاً بعد كل
      إغلاق صفقة فيمحو مفاتيح البوابة. الآن القواعد في الذاكرة + مفتاح منفصل
      "guard_rules" في الملف، والقراءات وقت التشغيل لا تعتمد على learned_rules

الحمايات:
  1) ساعات محظورة (3+ صفقات، نجاح ≤35%، خسارة < -2$)
  2) بصمات (اتجاه|جلسة|RSI|حجم): حمراء تُمنع، خضراء تُشجَّع — مدرَّبة من كل التاريخ
     وتُحدَّث تلقائياً مع كل صفقة جديدة
  3) لا دخول بدون AI ناجح (شبكة أمان التنفيذ)
  4) كاش AI 30-45 دقيقة + سقف استدعاءات/ساعة
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
BASE_MIN_SCORE         = 65
AI_CALL_MIN_PRE_SCORE  = 0      # 0 مع ملفات كلود v6+ — بوابة الـ60 موجودة داخل bot_strategies
                                # على total_score الحقيقي، بينما الإشارة الواصلة للغلاف تحمل 'confidence'
AI_CALL_HOURLY_CAP     = 25
AI_CACHE_TTL_SEC       = 45 * 60
WARNING_PENALTY        = -4
REQUIRE_AI_FOR_ENTRY   = True
LOG_ONLY               = True   # هجين: مراقبة فقط أولاً — لا يمنع الصفقات قبل إثبات الأنماط من إغلاقات موثقة

HOUR_MIN_TRADES        = 4
HOUR_BLOCK_WINRATE     = 0.35
HOUR_BLOCK_PNL         = -2.0

PATTERN_MIN_TRADES     = 4
PATTERN_BLOCK_PF       = 0.60
PATTERN_BLOCK_PNL      = -1.5
PATTERN_GREEN_PF       = 1.50
GREEN_SCORE_RELAX      = 5
RED_SCORE_BLOCK        = True

DIRECTION_MIN_TRADES   = 15
DIRECTION_MAX_PENALTY  = 10

CHOPPY_SPIKE_VOL       = 2.5
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
# نسخة الذاكرة من القواعد — تحمي من مسح adaptive_rules لمفاتيحنا في الملف
_RULES_CACHE = {"rules": None, "ts": 0.0}
_CACHE_TTL = 300  # 5 دقائق


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


def _load_rules():
    """قراءة القواعد: الذاكرة أولاً، ثم guard_rules (المفتاح المنفصل)، ثم learned_rules."""
    now = time.time()
    if _RULES_CACHE["rules"] is not None and now - _RULES_CACHE["ts"] < _CACHE_TTL:
        return _RULES_CACHE["rules"]
    state = _load(STATE_FILE, {})
    rules = state.get("guard_rules") or state.get("learned_rules", {}) or {}
    _RULES_CACHE["rules"] = rules
    _RULES_CACHE["ts"] = now
    return rules


def _persist_rules(state, rules):
    """حفظ القواعد: المفتاح المنفصل guard_rules (لا يمسه adaptive) + نسخة في learned_rules للعرض."""
    state["guard_rules"] = rules
    lr = state.setdefault("learned_rules", {})
    for k in ("blocked_hours", "pattern_rules", "direction_penalty",
              "pattern_guard_version", "updated"):
        if k in rules:
            lr[k] = rules[k]
    _save(STATE_FILE, state)
    _RULES_CACHE["rules"] = rules
    _RULES_CACHE["ts"] = time.time()


def is_verified_closed_trade(t) -> bool:
    """فلتر التعلم الصحيح: نتيجة نهائية فقط، لا صفقات مفتوحة/قيد التحقق."""
    if not isinstance(t, dict):
        return False
    if t.get("pnl_verified"):
        return True
    # بعض الصفقات القديمة قد لا تحمل pnl_verified لكن لها حالة نتيجة صريحة
    if t.get("is_win") or t.get("is_loss"):
        return True
    pnl = t.get("pnl")
    if t.get("closed_at") and pnl is not None:
        return True
    return False

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

# ═══════════════════════ بناء القواعد من التاريخ ═══════════════════════

def get_blocked_hours() -> set:
    rules = _load_rules()
    hours = rules.get("blocked_hours") or []
    return {int(h) for h in hours}


def rebuild_rules():
    """
    إعادة بناء القواعد كلها من trade_memory.json:
    blocked_hours + pattern_rules + direction_penalties.
    تُستدعى عند كل إغلاق صفقة وبعد جلسة التعلم.
    """
    mem = _load(MEM_FILE, {})
    trades = mem.get("trades", [])
    verified_trades = [t for t in trades if is_verified_closed_trade(t)]

    # ── الساعات ──
    hs = defaultdict(lambda: {"n": 0, "w": 0, "pnl": 0.0})
    for t in verified_trades:
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
    if len(verified_trades) < 30:
        blocked |= SEED_BLOCKED_HOURS

    # ── البصمات: تدريب مباشر من الصفقات المغلقة/الموثقة فقط ──
    sig_stats = defaultdict(lambda: {"n": 0, "w": 0, "gw": 0.0, "gl": 0.0})
    for t in verified_trades:
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

    # دمج البذور المؤكدة دائماً (أولويات مثبتة على 96+ صفقة)
    greens += ["|".join(s) for s in SEED_GREEN_PATTERNS]
    reds   += ["|".join(s) for s in SEED_RED_PATTERNS]

    # ── عقوبة الاتجاه ──
    dirs = defaultdict(lambda: {"n": 0, "gw": 0.0, "gl": 0.0})
    for t in verified_trades:
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
            dir_pen[d] = -3

    state = _load(STATE_FILE, {})
    rules = {
        "blocked_hours": sorted(blocked),
        "pattern_rules": {"green": sorted(set(greens)), "red": sorted(set(reds))},
        "direction_penalty": dir_pen,
        "pattern_guard_version": 2,
        "updated": datetime.now().isoformat(),
    }
    _persist_rules(state, rules)
    logger.info(f"🛡️ pattern_guard: ساعات محظورة={sorted(blocked)} "
                f"أنماط خضراء={len(set(greens))} حمراء={len(set(reds))} عقوبات={dir_pen}")
    return rules

# ═══════════════════════ تقييم البصمة وقت المسح ═══════════════════════

def _pattern_verdict(direction, hour, rsi_points, volume_ratio):
    sig = signature(direction, hour, rsi_points, volume_ratio)
    pr = _load_rules().get("pattern_rules", {})
    if sig in (pr.get("red") or []):
        return "red", sig
    if sig in (pr.get("green") or []):
        return "green", sig
    # تحقق إحصائي مباشر من الذاكرة (لا يعتمد على ملف الحالة)
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
    rules = _load_rules()
    score = BASE_MIN_SCORE
    score += int(rules.get("direction_penalty", {}).get(direction, 0))
    if pattern_verdict == "green":
        score = max(55, score - GREEN_SCORE_RELAX)
    return score

# ═══════════════════════ البوابة الرئيسية ═══════════════════════

def check_gates(symbol, direction, hour, rsi_points, volume_ratio,
                pre_ai_score, market_regime=None) -> dict:
    reasons = []
    allow = True

    if hour in get_blocked_hours():
        allow = False
        reasons.append(f"ساعة {hour} محظورة")

    verdict, sig = _pattern_verdict(direction, hour, rsi_points, volume_ratio)
    if verdict == "red":
        allow = False
        reasons.append(f"نمط خاسر متكرر [{sig}]")

    ai_required = pre_ai_score >= AI_CALL_MIN_PRE_SCORE
    if not ai_required:
        allow = False
        reasons.append(f"pre-score {pre_ai_score} < {AI_CALL_MIN_PRE_SCORE}")

    req = required_score(direction, hour, verdict)

    if market_regime == "متذبذب" and volume_ratio >= CHOPPY_SPIKE_VOL and verdict != "green":
        req += CHOPPY_EXTRA_SCORE
        reasons.append("سوق متذبذب + حجم انفجاري")

    if not allow and LOG_ONLY:
        logger.info(f"🛡️ [SHADOW] {symbol}: رفض بوابات ({'; '.join(reasons)})")
    return {"allow": allow or LOG_ONLY,
            "will_block": not allow,
            "reasons": reasons,
            "required_score": req,
            "pattern": verdict,
            "signature": sig,
            "ai_required": True}

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
    now = time.time()
    cache = {k: v for k, v in cache.items() if now - v.get("ts", 0) < AI_CACHE_TTL_SEC}
    cache[key] = {"ts": now, "result": result}
    cache.setdefault("_calls", {})
    cache["_calls"] = {k: v for k, v in cache["_calls"].items()
                       if k == datetime.now().strftime("%Y-%m-%dT%H") or now - v.get("ts", 0) < 3600}
    hk = datetime.now().strftime("%Y-%m-%dT%H")
    cache["_calls"][hk] = {"ts": now, "n": cache["_calls"].get(hk, {}).get("n", 0) + 1}
    _save(CACHE_FILE, cache)


def ai_call_available() -> bool:
    cache = _load(CACHE_FILE, {})
    hour_key = datetime.now().strftime("%Y-%m-%dT%H")
    n = cache.get("_calls", {}).get(hour_key, {}).get("n", 0)
    return n < AI_CALL_HOURLY_CAP


def ai_unavailable_action() -> str:
    return "skip" if REQUIRE_AI_FOR_ENTRY else "fallback_old"

# ═══════════════════════ نقاط توصية AI ═══════════════════════

def resolve_groq_points(recommendation: str, confidence: float, trusted: bool):
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
    تُستدعى بعد تسجيل الصفقة في trade_memory (عبر guard_bootstrap).
    تحدّث condition_stats (البصمات) + تعيد بناء القواعد —
    هكذا يتعلم البوت من كل صفقة خاسرة ولا يكرر نمطها.
    """
    if not is_verified_closed_trade(trade):
        logger.debug("guard learning: تخطي صفقة غير مغلقة/غير موثقة")
        return
    sd = trade.get("score_details", {}) or {}
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
