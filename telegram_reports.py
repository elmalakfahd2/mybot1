"""تقارير Telegram إضافية: العمولات اليومية ولكل صفقة."""
import json
from collections import defaultdict
from datetime import datetime

MEM_FILE = "trade_memory.json"


def _load_trades():
    try:
        with open(MEM_FILE, encoding="utf-8") as f:
            data = json.load(f) or {}
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


def _trade_date(t):
    raw = t.get("date") or t.get("entry_time") or t.get("closed_at") or ""
    try:
        return str(raw)[:10]
    except Exception:
        return "unknown"


def _fees(t):
    try:
        if t.get("fees") is not None:
            return abs(float(t.get("fees")))
    except Exception:
        pass
    try:
        return abs(float(t.get("pnl_gross", 0)) - float(t.get("pnl", 0)))
    except Exception:
        return 0.0


def _fmt(x, n=4):
    try:
        return f"{float(x):.{n}f}"
    except Exception:
        return str(x)


def build_fees_report(last_n=20):
    trades = _verified_closed(_load_trades())
    if not trades:
        return "لا توجد صفقات موثقة مغلقة بعد."

    total_fees = sum(_fees(t) for t in trades)
    total_pnl = sum(float(t.get("pnl", 0) or 0) for t in trades)
    by_day = defaultdict(float)
    for t in trades:
        by_day[_trade_date(t)] += _fees(t)

    today = datetime.now().strftime("%Y-%m-%d")
    today_fees = by_day.get(today, 0.0)

    lines = []
    lines.append("💸 <b>تقرير العمولات</b>")
    lines.append(f"إجمالي العمولات: <b>{_fmt(total_fees, 3)} USDT</b>")
    lines.append(f"عمولات اليوم: <b>{_fmt(today_fees, 3)} USDT</b>")
    lines.append(f"عدد الصفقات: <b>{len(trades)}</b>")
    lines.append(f"صافي PnL بعد العمولات: <b>{_fmt(total_pnl, 3)} USDT</b>")
    lines.append("")
    lines.append("📅 <b>العمولات اليومية:</b>")
    for day in sorted(by_day.keys(), reverse=True)[:10]:
        lines.append(f"• {day}: {_fmt(by_day[day], 3)} USDT")
    lines.append("")
    lines.append(f"🧾 <b>آخر {min(last_n, len(trades))} صفقة:</b>")
    recent = sorted(trades, key=lambda t: str(t.get("entry_time") or t.get("closed_at") or ""))[-last_n:]
    for t in reversed(recent):
        lines.append(
            f"• {t.get('symbol')} {t.get('direction')} | العمولة: {_fmt(_fees(t), 3)}$ | "
            f"pnl: {_fmt(t.get('pnl'), 3)}$ | {t.get('ai_recommendation') or t.get('groq_recommendation') or ''}"
        )
    return "\n".join(lines)
