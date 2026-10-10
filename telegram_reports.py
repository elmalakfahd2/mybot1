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
        notional = abs(float(t.get("entry_price", 0) or 0) * float(t.get("quantity", 0) or 0))
        plausible_cap = max(1.0, notional * 0.005)  # أي عمولة أكبر من 0.5% من الحجم مريبة
        if t.get("fees") is not None:
            fees = abs(float(t.get("fees")))
            if fees <= plausible_cap:
                return fees
    except Exception:
        pass
    try:
        notional = abs(float(t.get("entry_price", 0) or 0) * float(t.get("quantity", 0) or 0))
        if notional > 0:
            return notional * 0.0008
    except Exception:
        pass
    return 0.0


def _dedupe_trades(trades):
    seen = set()
    out = []
    for t in sorted(trades, key=lambda x: str(x.get("entry_time") or x.get("closed_at") or "")):
        key = (
            t.get("symbol"),
            t.get("direction"),
            str(t.get("entry_time") or "")[:16],
            round(float(t.get("pnl", 0) or 0), 2),
        )
        if key in seen:
            continue
        seen.add(key)
        out.append(t)
    return out


def _fmt(x, n=4):
    try:
        return f"{float(x):.{n}f}"
    except Exception:
        return str(x)


def build_fees_report(last_n=20, today_only=True):
    trades = _dedupe_trades(_verified_closed(_load_trades()))
    today = datetime.now().strftime("%Y-%m-%d")

    if today_only:
        trades = [t for t in trades if _trade_date(t) == today]

    if not trades:
        return f"💸 <b>تقرير عمولات اليوم</b>\n📅 التاريخ: {today}\n\nلا توجد صفقات موثقة مغلقة اليوم بعد."

    total_fees = sum(_fees(t) for t in trades)
    total_pnl = sum(float(t.get("pnl", 0) or 0) for t in trades)
    net_after_fees = total_pnl - total_fees

    wins = [t for t in trades if float(t.get("pnl", 0) or 0) > 0]
    losses = [t for t in trades if float(t.get("pnl", 0) or 0) < 0]

    lines = []
    lines.append("💸 <b>تقرير عمولات اليوم فقط</b>")
    lines.append(f"📅 التاريخ: <b>{today}</b>")
    lines.append(f"عدد صفقات اليوم: <b>{len(trades)}</b>")
    lines.append(f"الصفقات الرابحة: <b>{len(wins)}</b> | الخاسرة: <b>{len(losses)}</b>")
    lines.append("")
    lines.append(f"العمولات اليوم: <b>{_fmt(total_fees, 3)} USDT</b>")
    lines.append(f"PnL المسجل اليوم: <b>{_fmt(total_pnl, 3)} USDT</b>")
    lines.append(f"بعد تقدير العمولات: <b>{_fmt(net_after_fees, 3)} USDT</b>")
    lines.append("")
    lines.append(f"🧾 <b>صفقات اليوم ({min(last_n, len(trades))}):</b>")
    recent = sorted(trades, key=lambda t: str(t.get("entry_time") or t.get("closed_at") or ""))[-last_n:]
    for t in reversed(recent):
        lines.append(
            f"• {t.get('symbol')} {t.get('direction')} | العمولة: {_fmt(_fees(t), 3)}$ | "
            f"pnl: {_fmt(t.get('pnl'), 3)}$"
        )
    return "\n".join(lines)
