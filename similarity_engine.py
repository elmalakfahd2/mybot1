# ==================================================
# 📁 ملف: similarity_filter.py - v2.0  (التعلّم من إغلاق الصفقات)
# ==================================================
# الفكرة:
#   كل صفقة تُغلق تُسجَّل في trade_memory.json ببياناتها عند الدخول (مكوّنات النقاط،
#   الحجم، الاتجاه...) ونتيجتها الحقيقية (ربحت/خسرت). قبل كل دخول جديد يقارن البوت
#   بيانات الإشارة بأقرب K صفقات سابقة مغلقة:
#       - تشبه صفقات خاسرة     → لا ينفّذ
#       - تشبه صفقات رابحة     → ينفّذ
#       - لا تشبه شيئاً (جديدة) → ينفّذ (نقص معرفة، وليس دليلاً على الخسارة)
#
# 🛡️ بوابة التدقيق الذاتي (SIMILARITY_REQUIRE_AUDIT):
#   قبل أن يُسمح للفلتر بحجب أي صفقة فعلياً، يختبر نفسه على تاريخك (walk-forward:
#   كل صفقة تُقارن بما سبقها فقط) ويحسب هل توقّعاته ارتبطت فعلاً بالنتيجة.
#   - إن ارتبطت (ارتباط >= SIMILARITY_AUDIT_MIN_CORR) يحجب فعلياً.
#   - وإلا يبقى يسجّل الحكم في السجل دون أن يمنع شيئاً، ويعيد الاختبار بعد كل إغلاق.
#   (اختبار 144 صفقة سابقة أعطى ارتباطاً ≈ −0.06، أي لا قدرة تنبؤية بعد.)
#   لتجاوز التدقيق وفرض الحجب دائماً:  SIMILARITY_REQUIRE_AUDIT = False
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
REPORT_FILE = "similarity_report.json"

# مكوّنات النقاط وقت الدخول (قبل AI) وحدّها الأعلى لتطبيعها 0..1
_COMPS = [
    ("timeframe_points", 20), ("volume_points", 15), ("rsi_points", 10),
    ("momentum_points", 10), ("price_action_points", 8),
    ("order_book_points", 10), ("funding_oi_points", 10), ("market_points", 5),
]
_WIN_EPS = 0.10          # |الصافي| < 0.10$ = تعادل ويُتجاهل
_CACHE_SECONDS = 300
_AUDIT_SECONDS = 600

_cache = {"ts": 0.0, "rows": []}
_audit_cache = {"ts": 0.0, "result": None}
_last_audit_log = {"ok": None}


def _vector(score_details, volume_ratio, direction):
    v = []
    sd = score_details or {}
    for key, mx in _COMPS:
        try:
            v.append(float(sd.get(key, 0) or 0) / mx)
        except Exception:
            v.append(0.0)
    try:
        v.append(min(float(volume_ratio or 0), 4.0) / 4.0)
    except Exception:
        v.append(0.0)
    v.append(1.0 if str(direction).upper() in ("BUY", "LONG") else 0.0)
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
            trades = sorted(data.get("trades", []), key=lambda t: t.get("entry_time", ""))
            for t in trades:
                if not t.get("pnl_verified"):
                    continue
                pnl = t.get("pnl", 0) or 0
                sd = t.get("score_details") or {}
                if not sd:
                    continue
                rows.append({
                    "vec": _vector(sd, t.get("volume_ratio", 0), t.get("direction", "")),
                    "win": 1 if pnl > _WIN_EPS else (0 if pnl < -_WIN_EPS else None),
                    "pct": float(t.get("pnl_percent", 0) or 0),
                    "symbol": t.get("symbol", ""),
                    "direction": t.get("direction", ""),
                    "exit_reason": t.get("exit_reason", ""),
                })
    except Exception as e:
        logger.warning(f"⚠️ similarity: تعذر تحميل الذاكرة: {e}")
    _cache["rows"] = rows
    _cache["ts"] = now
    return rows


def refresh():
    """تُستدعى بعد كل إغلاق صفقة: يتعلّم الفلتر من النتيجة الجديدة فوراً."""
    _cache["ts"] = 0.0
    _audit_cache["ts"] = 0.0
    try:
        rows = _load_rows(force=True)
        audit(force=True)
        _export_report(rows)
    except Exception as e:
        logger.debug(f"similarity.refresh: {e}")


def _predict(vec, pool, k):
    cand = [r for r in pool if r["win"] is not None]
    if len(cand) < max(3, k // 2):
        return None, None
    nb = sorted(cand, key=lambda r: _dist(vec, r["vec"]))[:k]
    wr = sum(r["win"] for r in nb) / len(nb)
    md = sum(_dist(vec, r["vec"]) for r in nb) / len(nb)
    return wr, md


def _corr(a, b):
    n = len(a)
    if n < 3:
        return 0.0
    ma, mb = sum(a) / n, sum(b) / n
    va = sum((x - ma) ** 2 for x in a)
    vb = sum((y - mb) ** 2 for y in b)
    if va * vb == 0:
        return 0.0
    return sum((x - ma) * (y - mb) for x, y in zip(a, b)) / math.sqrt(va * vb)


def audit(force=False):
    """
    اختبار ذاتي walk-forward على تاريخ الصفقات المغلقة.
    يرجع dict: {'ok','n','corr','allowed_avg','blocked_avg','reason'}
    """
    now = time.time()
    if not force and _audit_cache["result"] and now - _audit_cache["ts"] < _AUDIT_SECONDS:
        return _audit_cache["result"]

    k = int(_c("SIMILARITY_K", 10))
    min_n = int(_c("SIMILARITY_AUDIT_MIN_N", 40))
    min_corr = float(_c("SIMILARITY_AUDIT_MIN_CORR", 0.10))
    window = int(_c("SIMILARITY_AUDIT_WINDOW", 120))
    thr = float(_c("SIMILARITY_MIN_WIN_RATE", 0.5))
    res = {"ok": False, "n": 0, "corr": 0.0, "allowed_avg": None, "blocked_avg": None, "reason": ""}
    try:
        rows = _load_rows()
        start = 30
        preds, outs = [], []
        for i in range(start, len(rows)):
            wr, _md = _predict(rows[i]["vec"], rows[:i], k)
            if wr is None:
                continue
            preds.append(wr)
            outs.append(rows[i]["pct"])
        preds, outs = preds[-window:], outs[-window:]
        res["n"] = len(preds)
        if len(preds) < min_n:
            res["reason"] = f"بيانات تدقيق غير كافية ({len(preds)}/{min_n})"
        else:
            res["corr"] = round(_corr(preds, outs), 3)
            allowed = [o for p, o in zip(preds, outs) if p >= thr]
            blocked = [o for p, o in zip(preds, outs) if p < thr]
            if allowed:
                res["allowed_avg"] = round(sum(allowed) / len(allowed), 3)
            if blocked:
                res["blocked_avg"] = round(sum(blocked) / len(blocked), 3)
            better = (len(allowed) >= 10 and len(blocked) >= 10 and
                      res["allowed_avg"] is not None and res["blocked_avg"] is not None and
                      res["allowed_avg"] > res["blocked_avg"])
            if res["corr"] >= min_corr and better:
                res["ok"] = True
                res["reason"] = f"ارتباط {res['corr']:+.2f} والمسموح أفضل من المحجوب"
            else:
                res["reason"] = (f"لم يثبت التنبؤ (ارتباط {res['corr']:+.2f}، "
                                 f"مسموح {res['allowed_avg']}% / محجوب {res['blocked_avg']}%)")
    except Exception as e:
        res["reason"] = f"خطأ تدقيق: {e}"

    _audit_cache["ts"] = now
    _audit_cache["result"] = res
    if _last_audit_log["ok"] != res["ok"]:
        _last_audit_log["ok"] = res["ok"]
        logger.info(f"🧪 تدقيق الفلتر: {'✅ مُفعَّل للحجب' if res['ok'] else '⏸️ تسجيل فقط'} - {res['reason']}")
    return res


def assess(symbol, direction, score_details, volume_ratio):
    """
    يرجع dict: {'verdict','win_rate','n_neighbors','allow','mode','effective_mode','reason'}
    allow=False فقط إذا: الوضع block + اجتاز التدقيق (أو تعطّل) + الإشارة تشبه صفقات خاسرة.
    لا يرمي استثناءً أبداً (أي خطأ = السماح).
    """
    mode = str(_c("SIMILARITY_FILTER_MODE", "log")).lower()
    out = {"verdict": "unknown", "win_rate": None, "n_neighbors": 0, "allow": True,
           "mode": mode, "effective_mode": mode, "reason": ""}
    try:
        if mode == "off":
            out["reason"] = "معطل"
            return out

        k = int(_c("SIMILARITY_K", 10))
        min_hist = int(_c("SIMILARITY_MIN_HISTORY", 40))
        min_wr = float(_c("SIMILARITY_MIN_WIN_RATE", 0.5))
        max_md = float(_c("SIMILARITY_MAX_NBR_DIST", 0.8))

        rows = [r for r in _load_rows() if r["win"] is not None]
        if len(rows) < min_hist:
            out["reason"] = f"تاريخ غير كافٍ ({len(rows)}/{min_hist})"
            return out

        vec = _vector(score_details, volume_ratio, direction)
        wr, md = _predict(vec, rows, k)
        if wr is None:
            return out
        out["win_rate"] = round(wr, 2)
        out["n_neighbors"] = min(k, len(rows))

        if md > max_md:
            out["verdict"] = "novel"
            out["reason"] = f"إشارة جديدة (متوسط بُعد الجيران {md:.2f} > {max_md})"
            return out

        if wr >= 0.6:
            out["verdict"] = "similar_to_winners"
        elif wr <= 0.35:
            out["verdict"] = "similar_to_losers"
        else:
            out["verdict"] = "mixed"

        if mode == "block" and wr < min_wr:
            if bool(_c("SIMILARITY_REQUIRE_AUDIT", True)):
                a = audit()
                if not a["ok"]:
                    out["effective_mode"] = "log(audit)"
                    out["reason"] = f"كان سيُحجب لكن التدقيق لم يثبت جدواه: {a['reason']}"
                    return out
            out["allow"] = False
            out["reason"] = f"نجاح أقرب {out['n_neighbors']} صفقات مغلقة مشابهة {wr:.0%} < {min_wr:.0%}"
        return out
    except Exception as e:
        logger.warning(f"⚠️ similarity: {e}")
        out["reason"] = f"خطأ: {e}"
        return out


def _export_report(rows):
    """ملخص مقروء لما تعلّمه الفلتر من الصفقات المغلقة (similarity_report.json)."""
    try:
        decided = [r for r in rows if r["win"] is not None]
        wins = [r for r in decided if r["win"] == 1]
        losses = [r for r in decided if r["win"] == 0]

        def avg(rs):
            if not rs:
                return None
            return [round(sum(r["vec"][i] for r in rs) / len(rs), 2) for i in range(len(rs[0]["vec"]))]

        names = [c for c, _ in _COMPS] + ["volume_ratio", "is_buy"]
        reasons = {}
        for r in decided:
            key = (r.get("exit_reason") or "unknown")
            d = reasons.setdefault(key, {"wins": 0, "losses": 0})
            d["wins" if r["win"] else "losses"] += 1
        rep = {
            "updated": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "closed_trades_learned": len(decided),
            "wins": len(wins), "losses": len(losses),
            "feature_names": names,
            "avg_features_winners": avg(wins),
            "avg_features_losers": avg(losses),
            "by_exit_reason": reasons,
            "audit": _audit_cache.get("result"),
        }
        with open(REPORT_FILE, "w", encoding="utf-8") as f:
            json.dump(rep, f, ensure_ascii=False, indent=1)
    except Exception as e:
        logger.debug(f"similarity report: {e}")
