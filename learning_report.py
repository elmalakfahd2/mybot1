"""
تقرير تشخيصي مختصر يساعدنا نفهم لماذا الصفقات تربح أو تخسر.
يستخدم فقط الصفقات المغلقة/الموثقة.
"""
import json
import os
import statistics
from collections import defaultdict
from datetime import datetime

MEM_FILE = "trade_memory.json"


def _load_trades():
    try:
        with open(MEM_FILE, encoding="utf-8") as f:
            data = json.load(f)
        return data.get("trades", []) or []
    except Exception:
        return []


def _verified_closed(trades):
    out = []
    for t in trades:
        if not isinstance(t, dict):
            continue
        if not (t.get("pnl_verified") or t.get("is_win") or t.get("is_loss")):
            continue
        if t.get("pnl") is None:
            continue
        out.append(t)
    return out


def _fmt(x, n=2):
    try:
        return f"{float(x):.{n}f}"
    except Exception:
        return str(x)


def _band(score):
    try:
        s = float(score)
    except Exception:
        return "غير معروف"
    if s >= 80:
        return "80+"
    if s >= 75:
        return "75-79"
    if s >= 65:
        return "65-74"
    return "<65"


def build_report():
    trades = _verified_closed(_load_trades())
    if not trades:
        return "لا توجد صفقات موثقة مغلقة بعد."

    wins = [t for t in trades if t.get("pnl", 0) > 0]
    losses = [t for t in trades if t.get("pnl", 0) < 0]
    gross_w = sum(t.get("pnl", 0) for t in wins)
    gross_l = sum(t.get("pnl", 0) for t in losses)
    pf = gross_w / abs(gross_l) if gross_l else 0.0

    lines = []
    lines.append("🧠 <b>تقرير تشخيص الأداء</b>")
    lines.append(f"الصفقات الموثقة: <b>{len(trades)}</b> | رابحة: <b>{len(wins)}</b> | خاسرة: <b>{len(losses)}</b>")
    lines.append(f"الصافي: <b>{_fmt(sum(t.get('pnl',0) for t in trades))}$</b> | PF: <b>{_fmt(pf)}</b>")
    if wins:
        lines.append(f"متوسط الربح: <b>+{_fmt(statistics.mean([t.get('pnl',0) for t in wins]))}$</b>")
    if losses:
        lines.append(f"متوسط الخسارة: <b>{_fmt(statistics.mean([t.get('pnl',0) for t in losses]))}$</b>")
    lines.append("")

    # Score bands
    bands = defaultdict(list)
    for t in trades:
        bands[_band((t.get("score_details") or {}).get("total"))].append(t)
    lines.append("📊 <b>حسب النقاط:</b>")
    for b in ["80+", "75-79", "65-74", "<65", "غير معروف"]:
        arr = bands.get(b, [])
        if not arr:
            continue
        net = sum(t.get("pnl", 0) for t in arr)
        wr = len([t for t in arr if t.get("pnl", 0) > 0]) / len(arr)
        lines.append(f"• {b}: n={len(arr)} | صافي={_fmt(net)}$ | فوز={wr:.0%}")
    lines.append("")

    # Symbols
    sym = defaultdict(list)
    for t in trades:
        sym[t.get("symbol", "?")].append(t)
    lines.append("📉 <b>أسوأ الرموز (n>=3):</b>")
    worst = sorted(sym.items(), key=lambda kv: sum(t.get("pnl", 0) for t in kv[1]))[:6]
    for s, arr in worst:
        if len(arr) < 3:
            continue
        net = sum(t.get("pnl", 0) for t in arr)
        wr = len([t for t in arr if t.get("pnl", 0) > 0]) / len(arr)
        lines.append(f"• {s}: n={len(arr)} | صافي={_fmt(net)}$ | فوز={wr:.0%}")
    lines.append("")

    # AI
    ai = defaultdict(list)
    for t in trades:
        ai[t.get("groq_recommendation") or "بدون AI"].append(t)
    lines.append("🧠 <b>حسب AI:</b>")
    for k, arr in ai.items():
        net = sum(t.get("pnl", 0) for t in arr)
        wr = len([t for t in arr if t.get("pnl", 0) > 0]) / len(arr)
        lines.append(f"• {k}: n={len(arr)} | صافي={_fmt(net)}$ | فوز={wr:.0%}")
    lines.append("")

    # Recent trades
    lines.append("🕘 <b>آخر 10 صفقات:</b>")
    recent = sorted(trades, key=lambda t: str(t.get("entry_time") or ""))[-10:]
    for t in recent:
        score = (t.get("score_details") or {}).get("total", "?")
        ai_rec = t.get("groq_recommendation") or "?"
        mfe = t.get("mfe_pct")
        mae = t.get("mae_pct")
        lines.append(
            f"• {t.get('symbol')} {t.get('direction')} | نقاط={score} | AI={ai_rec} | "
            f"pnl={_fmt(t.get('pnl'))}$ | MFE={_fmt(mfe) if mfe is not None else '?'}% | MAE={_fmt(mae) if mae is not None else '?'}%"
        )
    lines.append("")

    # Insights
    lines.append("💡 <b>الخلاصة:</b>")
    if bands.get("75-79") and sum(t.get("pnl", 0) for t in bands["75-79"]) > 0 and bands.get("65-74") and sum(t.get("pnl", 0) for t in bands["65-74"]) < 0:
        lines.append("• الحد الأفضل حالياً هو 75+؛ فترة 65-74 خاسرة.")
    if pf and pf < 1:
        lines.append("• PF أقل من 1: المشكلة الأساسية في حجم الخسارة مقابل الربح أو جودة الدخول.")
    if wins and losses and abs(statistics.mean([t.get('pnl',0) for t in losses])) > statistics.mean([t.get('pnl',0) for t in wins]):
        lines.append("• الخسارة الواحدة أكبر من الربح الواحد؛ يجب تقليل SL أو تحسين نقاط الدخول.")
    lines.append("أرسل هذا التقرير مع آخر لوج لتحليل أدق.")

    return "\n".join(lines)


if __name__ == "__main__":
    print(build_report())
