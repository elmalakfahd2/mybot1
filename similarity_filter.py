# ==================================================
# 📁 ملف: similarity_filter.py - v1.0
# 🎯 الفكرة: مقارنة بيانات الإشارة الحالية بصفقات سابقة موثّقة
#    (أقرب K صفقات) ومعرفة هل تشبه الرابحة أم الخاسرة.
#
# ⚠️ اختبار على 89 صفقة موثّقة (walk-forward) أظهر أن "الشبيهة بالرابحة"
#    خسرت أكثر من المتوسط (ارتباط −0.29). لذلك الوضع الافتراضي = "log":
#    يسجّل الحكم فقط ولا يمنع أي صفقة. شغّل evaluate_similarity.py بعد
#    جمع صفقات جديدة، ولا تفعّل "block" إلا إذا أثبتت النتائج فائدته.
#
# الإعدادات (config.py):
#   SIMILARITY_FILTER_MODE      = "log" | "block" | "off"
#   SIMILARITY_K                = 10     عدد الجيران
#   SIMILARITY_MIN_HISTORY      = 40     أقل عدد صفقات موثّقة لتفعيل الحكم
#   SIMILARITY_MIN_WIN_RATE     = 0.35   في وضع block: امنع إن كان نجاح الجيران أقل
#                                        (ضعها 0.5 لتنفيذ ما يشبه الرابحة فقط)
# ==================================================

import json
import logging
import math
import os
import time

logger = logging.getLogger("similarity_filter")

try:
    import config as _cfg
except Exception:  # pragma: no cover
    _cfg = None


def _c(name, default):
    return getattr(_cfg, name, default) if _cfg else default


MEMORY_FILE = _c("MEMORY_FILE", "trade_memory.json")

# مكوّنات النقاط قبل الذكاء الاصطناعي (AI مستبعد عمداً: غير متاح وقت الحكم)
_COMPS = [
    ("timeframe_points", 20), ("volume_points", 15), ("rsi_points", 10),
    ("momentum_points", 10), ("price_action_points", 8),
    ("order_book_points", 10), ("funding_oi_points", 10), ("market_points", 5),
]
_WIN_EPS = 0.10  # |الصافي| أقل من هذا = تعادل ويُتجاهل

_cache = {"ts": 0.0, "rows": []}
_CACHE_SECONDS = 300


def _vector(score_details, volume_ratio, direction):
    v = []
    for key, mx in _COMPS:
        v.append(float(score_details.get(key, 0) or 0) / mx)
    v.append(min(float(volume_ratio or 0), 4.0) / 4.0)
    v.append(1.0 if str(direction).upper() == "BUY" else 0.0)
    return v


def _dist(a, b):
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b)))


def _load_rows(force=False):
    now = time.time()
    if not force and _cache["rows"] and now - _cache["ts"] < _CACHE_SECONDS:
        return _cache["rows"]
    rows = []
    try:
        if os.path.exists(MEMORY_FILE):
            with open(MEMORY_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            for t in data.get("trades", []):
                if not t.get("pnl_verified"):
                    continue
                pnl = t.get("pnl", 0) or 0
                if abs(pnl) < _WIN_EPS:
                    continue
                sd = t.get("score_details") or {}
                if not sd:
                    continue
                rows.append({
                    "vec": _vector(sd, t.get("volume_ratio", 0), t.get("direction", "")),
                    "win": 1 if pnl > 0 else 0,
                    "symbol": t.get("symbol", ""),
                })
    except Exception as e:
        logger.warning(f"⚠️ similarity: تعذر تحميل الذاكرة: {e}")
    _cache["rows"] = rows
    _cache["ts"] = now
    return rows


def assess(symbol, direction, score_details, volume_ratio):
    """
    يرجع dict: {'verdict', 'win_rate', 'n_neighbors', 'allow', 'mode', 'reason'}
    allow=False فقط في وضع block عند تشابه ضعيف النجاح. لا يرمي استثناءً أبداً.
    """
    mode = str(_c("SIMILARITY_FILTER_MODE", "log")).lower()
    out = {"verdict": "unknown", "win_rate": None, "n_neighbors": 0,
           "allow": True, "mode": mode, "reason": ""}
    try:
        if mode == "off":
            out["reason"] = "معطل"
            return out

        k = int(_c("SIMILARITY_K", 10))
        min_hist = int(_c("SIMILARITY_MIN_HISTORY", 40))
        min_wr = float(_c("SIMILARITY_MIN_WIN_RATE", 0.35))

        rows = _load_rows()
        if len(rows) < min_hist:
            out["reason"] = f"تاريخ غير كافٍ ({len(rows)}/{min_hist})"
            return out

        vec = _vector(score_details or {}, volume_ratio, direction)
        nbrs = sorted(rows, key=lambda r: _dist(vec, r["vec"]))[:k]
        wr = sum(r["win"] for r in nbrs) / len(nbrs)
        out["win_rate"] = round(wr, 2)
        out["n_neighbors"] = len(nbrs)

        if wr >= 0.6:
            out["verdict"] = "similar_to_winners"
        elif wr <= 0.35:
            out["verdict"] = "similar_to_losers"
        else:
            out["verdict"] = "mixed"

        if mode == "block" and wr < min_wr:
            out["allow"] = False
            out["reason"] = f"نجاح أقرب {len(nbrs)} صفقات سابقة {wr:.0%} < {min_wr:.0%}"
        return out
    except Exception as e:
        logger.warning(f"⚠️ similarity: {e}")
        out["reason"] = f"خطأ: {e}"
        return out
