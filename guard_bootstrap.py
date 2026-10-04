# -*- coding: utf-8 -*-
"""
guard_bootstrap.py — الحماية الخارجية للبوت (بدون تعديل config.py أو bot_strategies_enhanced.py)
================================================================================================
يُستورد في السطر الأول من main_enhanced.py (قبل أي استيراد آخر):

    import guard_bootstrap; guard_bootstrap.apply_patches()

أو شغّله كمدخل بديل:  python guard_bootstrap.py

ماذا يربط (كل التعديلات في الذاكرة على كائنات الوحدات المحمّلة):
  1) groq_integration.analyze_signal_with_groq / enhance_signal_with_groq
     → كاش 30 د + سقف 12/ساعة + بوابات الساعة/النمط (تُرجع "رفض" فيرافضها
     كود البوت الحالي بنفسه عبر آلية الفيتو الموجودة أصلاً)
  2) core_functions.place_market_order_with_multiple_tp (+ alias tp_sl)
     → شبكة أمان التنفيذ: لا فتح صفقة بدون قرار AI ناجح حديث —
     يُغلق ثغرة AI_FAIL_MIN_SCORE=70 نهائياً من الخارج
  3) trade_memory.record_trade
     → التعلم: تسجيل بصمة كل صفقة في condition_stats + إعادة بناء القواعد
  4) smart_scheduler.run_learning_session
     → إعادة بناء قواعد pattern_guard بعد جلسة التعلم المعتادة
"""

import functools
import importlib
import logging
import time
from datetime import datetime

import pattern_guard as pg

logger = logging.getLogger("guard_bootstrap")

LOG_ONLY = pg.LOG_ONLY           # وضع التسجيل فقط (ابدأ به True 2-3 أيام)
FEATURE_TTL = 60 * 60            # صلاحية مؤشرات الإشارة المحفوظة
AI_FRESH_SEC = 45 * 60           # قرار AI يُقبل خلال 45 دقيقة من التنفيذ

# آخر مؤشرات إشارة لكل عملة (تُملأ من غلاف AI وتُقرأ عند التنفيذ)
_last_signal = {}


# ═══════════════════ استخراج المؤشرات من الإشارة ═══════════════════

def _extract(signal_data):
    sd = signal_data or {}
    analysis = sd.get("analysis", {}) or {}
    tech = analysis.get("technical_indicators", {}) or {}
    vol = analysis.get("volume_analysis", {}) or {}
    return {
        "symbol": sd.get("symbol", ""),
        "direction": sd.get("direction", ""),
        "score": sd.get("confidence", 0) or 0,
        "rsi": float(tech.get("rsi", 50) or 50),
        "vol_ratio": float(vol.get("volume_5m_ratio", 1.0) or 1.0),
    }


def _rsi_points_proxy(direction: str, rsi: float) -> int:
    """
    تقريب لمنطق الماسح في تحويل RSI إلى نقاط (اتجاه-واعٍ).
    مبني على 200+ عينة من اللوجات: BUY RSI 76→3 نقاط، RSI 41→10 ...
    اختلاف ±فئة نادراً مقبول — بوابة الساعة تحمل الجزء الأكبر من الحماية.
    """
    if direction == "BUY":
        if rsi >= 90:
            return 0
        if rsi >= 75:
            return 3
        if rsi >= 38:
            return 10
        if rsi >= 32:
            return 8
        return 5
    else:  # SELL
        if rsi <= 10:
            return 0
        if rsi >= 78:
            return 10
        if rsi >= 40:
            return 10
        if rsi >= 36:
            return 8
        return 5


def _stash(symbol, direction, hour, rsi_pts, vr, score, ai_ok):
    if not symbol:
        return
    _last_signal[symbol] = {
        "direction": direction, "hour": hour, "rsi_pts": rsi_pts,
        "vr": vr, "score": score,
        "ai_ok": ai_ok, "ai_ts": time.time(), "ts": time.time(),
    }


def _reject(reason: str) -> dict:
    """نتيجة رفض صناعية — كود البوت الحالي يطبق فيتو عند 'رفض'"""
    return {
        "groq_recommendation": "رفض",
        "groq_confidence": 90,
        "groq_analysis": f"مرفوع بواسطة pattern_guard: {reason}",
        "groq_reasoning": reason,
        "groq_risk_level": "عالي",
        "ai_provider": "pattern_guard",
    }


# ═══════════════════ 1) غلاف استدعاء AI ═══════════════════

def _wrap_groq(orig):
    @functools.wraps(orig)
    def inner(signal_data, analysis_data=None):
        f = _extract(signal_data)
        hour = datetime.now().hour
        rsi_pts = _rsi_points_proxy(f["direction"], f["rsi"])
        sym = f["symbol"]

        # أ) بوابات الساعة/النمط/عتبة الاستدعاء — قبل الكاش حتى لا تتجاوزه نتيجة قديمة
        gate = pg.check_gates(sym, f["direction"], hour, rsi_pts, f["vol_ratio"],
                              f["score"], None)
        if gate["will_block"]:
            reason = "; ".join(gate["reasons"])
            logger.info(f"🛡️ {sym}: بوابات تمنع ({reason})")
            if not LOG_ONLY:
                _stash(sym, f["direction"], hour, rsi_pts, f["vol_ratio"], f["score"], False)
                return _reject(reason)

        # ب) الكاش (توفير طلبات) — بعد البوابات
        cached = pg.get_cached_ai(sym, f["direction"]) if sym else None
        if cached:
            _stash(sym, f["direction"], hour, rsi_pts, f["vol_ratio"], f["score"], True)
            return cached

        # ج) سقف الاستدعاءات
        if not pg.ai_call_available():
            msg = "سقف استدعاءات AI/ساعة"
            logger.warning(f"🛡️ {msg}")
            if not LOG_ONLY:
                return _reject(msg)

        # د) الاستدعاء الحقيقي
        result = orig(signal_data, analysis_data)
        if sym:
            if result:
                pg.cache_ai(sym, f["direction"], result)
            _stash(sym, f["direction"], hour, rsi_pts, f["vol_ratio"], f["score"], bool(result))
        return result
    return inner


# ═══════════════════ 2) شبكة أمان التنفيذ ═══════════════════

def _open_gate(symbol, side):
    """ترجع قائمة أسباب المنع (فارغة = مسموح)"""
    reasons = []
    now = time.time()
    hour = datetime.now().hour
    direction = (side or "").upper()
    feats = _last_signal.get(symbol)

    if feats and now - feats["ts"] < FEATURE_TTL:
        rsi_pts, vr = feats["rsi_pts"], feats["vr"]
    else:
        rsi_pts, vr = 5, 1.0  # محايد

    if hour in pg.get_blocked_hours():
        reasons.append(f"ساعة {hour} محظورة")

    verdict, sig = pg._pattern_verdict(direction, hour, rsi_pts, vr)
    if verdict == "red":
        reasons.append(f"نمط خاسر متكرر [{sig}]")

    ai_ok = (feats and feats.get("ai_ok") and
             now - feats.get("ai_ts", 0) < AI_FRESH_SEC and
             feats.get("direction") == direction)
    if not ai_ok:
        reasons.append("لا يوجد قرار AI ناجح حديث")

    return reasons


def _wrap_open(orig):
    @functools.wraps(orig)
    def inner(symbol, side, amount_usdt, leverage, *args, **kwargs):
        reasons = _open_gate(symbol, side)
        if reasons:
            logger.info(f"🛡️ حماية التنفيذ: {symbol} {side} — {'; '.join(reasons)}")
            if not LOG_ONLY:
                return None   # البوت يعاملها كفشل فتح — لا صفقة، لا خسارة
        return orig(symbol, side, amount_usdt, leverage, *args, **kwargs)
    return inner


# ═══════════════════ 3) غلاف التسجيل (التعلم) ═══════════════════

def _wrap_record(orig):
    import inspect
    try:
        sig = inspect.signature(orig)
    except Exception:
        sig = None

    @functools.wraps(orig)
    def inner(*args, **kwargs):
        result = orig(*args, **kwargs)
        try:
            trade_like = {}
            if sig:
                bound = sig.bind_partial(*args, **kwargs)
                d = bound.arguments
                trade_like = {
                    "symbol": d.get("symbol"),
                    "direction": d.get("direction", "BUY"),
                    "volume_ratio": d.get("volume_ratio", 1.0),
                    "pnl": d.get("net_pnl") if d.get("net_pnl") is not None else d.get("pnl", 0),
                    "is_win": False, "is_loss": False,
                    "hour": datetime.now().hour,
                    "score_details": d.get("score_details") or {},
                }
            # الأرقام الحقيقية من الذاكرة (سُجلت للتو داخل orig)
            mem = pg._load(pg.MEM_FILE, {})
            if mem.get("trades"):
                last = mem["trades"][-1]
                if not trade_like.get("symbol") or last.get("symbol") == trade_like["symbol"]:
                    for k in ("is_win", "is_loss", "hour", "volume_ratio", "pnl",
                              "score_details", "direction"):
                        if k in last:
                            trade_like[k] = last[k]
            if trade_like.get("direction"):
                pg.record_trade(trade_like)
        except Exception as e:
            logger.debug(f"guard learning skipped: {e}")
        return result
    return inner


# ═══════════════════ 4) غلاف جلسة التعلم ═══════════════════

def _wrap_learning(orig):
    @functools.wraps(orig)
    def inner(*args, **kwargs):
        result = orig(*args, **kwargs)
        try:
            pg.rebuild_rules()
        except Exception as e:
            logger.debug(f"guard rebuild skipped: {e}")
        return result
    return inner


# ═══════════════════ التطبيق ═══════════════════

def _patch(module, name, factory, kind="wrap"):
    orig = getattr(module, name, None)
    if orig is None:
        logger.warning(f"⚠️ لم يُعثر على {module.__name__}.{name} — تخطّي")
        return False
    if getattr(orig, "_guard_patched", False):
        return True
    wrapped = factory(orig)
    wrapped._guard_patched = True
    setattr(module, name, wrapped)
    logger.info(f"🔌 رُبط {module.__name__}.{name} ({kind})")
    return True


def apply_patches(registry=None):
    """
    registry: اختياري — dict {اسم_الوحدة: كائن_وهمي} لأغراض الاختبار فقط.
    """
    def _imp(name):
        if registry and name in registry:
            return registry[name]
        return importlib.import_module(name)

    ok = []
    try:
        g = _imp("groq_integration")
        ok.append(_patch(g, "analyze_signal_with_groq", _wrap_groq, "AI+cache+cap"))
        ok.append(_patch(g, "enhance_signal_with_groq", _wrap_groq, "AI-alias"))
    except Exception as e:
        logger.warning(f"⚠️ groq_integration: {e}")

    try:
        c = _imp("core_functions")
        ok.append(_patch(c, "place_market_order_with_multiple_tp", _wrap_open, "execution-gate"))
        # الـ alias في المستودع ينادي الدالة الرئيسية بنفس المعاملات —
        # نشيره لنفس الغلاف مباشرة (نفس الحماية الكاملة، بدون استيراد هش)
        setattr(c, "place_market_order_with_tp_sl",
                getattr(c, "place_market_order_with_multiple_tp"))
    except Exception as e:
        logger.warning(f"⚠️ core_functions: {e}")

    try:
        tm = _imp("trade_memory")
        ok.append(_patch(tm, "record_trade", _wrap_record, "learning"))
    except Exception as e:
        logger.warning(f"⚠️ trade_memory: {e}")

    try:
        ss = _imp("smart_scheduler")
        ok.append(_patch(ss, "run_learning_session", _wrap_learning, "rules-rebuild"))
    except Exception as e:
        logger.warning(f"⚠️ smart_scheduler: {e}")

    mode = "تسجيل فقط (LOG_ONLY)" if LOG_ONLY else "تنفيذ فعلي"
    logger.info(f"🛡️ guard_bootstrap جاهز ({mode}) — نجح {sum(ok)}/6 ربط")
    # بناء القواعد أول مرة من الذاكرة الحالية
    try:
        pg.rebuild_rules()
    except Exception as e:
        logger.debug(f"rebuild first-run: {e}")
    return all(ok)


def _run_main():
    import runpy
    import sys
    sys.argv = [sys.argv[0]]  # نظّف وسائط سطر الأوامر
    runpy.run_module("main_enhanced", run_name="__main__")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    apply_patches()
    _run_main()
