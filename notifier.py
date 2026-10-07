# ==================================================
# 📁 ملف: notifier.py - v1.0
# 🔔 إشعارات Telegram: بدء التشغيل / فتح صفقة / إغلاق صفقة
#
# - مستقل تماماً (requests فقط) → لا مشاكل event loop أو threads
# - إعادة محاولة تلقائية + تقسيم الرسائل الطويلة + fallback بدون HTML
# - PositionTracker: يكتشف إغلاق الصفقات (TP/SL/يدوي) بمقارنة لقطات Binance
# ==================================================

import re
import time
import html
import logging
import threading

import requests

logger = logging.getLogger(__name__)

try:
    import config as _config
except Exception:  # pragma: no cover
    _config = None


def _cfg(name, default=None):
    try:
        return getattr(_config, name, default)
    except Exception:
        return default


_TOKEN = str(_cfg("TELEGRAM_TOKEN", "") or "").strip()
_CHAT_ID = str(_cfg("TELEGRAM_CHAT_ID", "") or "").strip()
_API = "https://api.telegram.org/bot{token}/sendMessage"
_send_lock = threading.Lock()


# ==================== الإرسال الأساسي ====================

def _strip_tags(text):
    return html.unescape(re.sub(r"<[^>]+>", "", text))


def _split(text, limit=3900):
    if len(text) <= limit:
        return [text]
    parts, cur = [], ""
    for line in text.split("\n"):
        if len(cur) + len(line) + 1 > limit:
            parts.append(cur)
            cur = ""
        cur += line + "\n"
    if cur.strip():
        parts.append(cur)
    return parts


def send_text(text, parse_mode="HTML", retries=3):
    """يرسل رسالة Telegram. يرجع True عند النجاح. لا يرفع استثناءات أبداً."""
    if not _TOKEN or not _CHAT_ID:
        logger.error("❌ [NOTIFY] TELEGRAM_TOKEN/TELEGRAM_CHAT_ID غير مضبوطين")
        return False
    if not text or not str(text).strip():
        return False

    ok_all = True
    for chunk in _split(str(text)):
        ok = False
        mode = parse_mode
        payload_text = chunk
        for attempt in range(1, retries + 1):
            try:
                with _send_lock:
                    r = requests.post(
                        _API.format(token=_TOKEN),
                        json={
                            "chat_id": _CHAT_ID,
                            "text": payload_text,
                            "parse_mode": mode,
                            "disable_web_page_preview": True,
                        } if mode else {
                            "chat_id": _CHAT_ID,
                            "text": payload_text,
                            "disable_web_page_preview": True,
                        },
                        timeout=15,
                    )
                if r.status_code == 200:
                    ok = True
                    logger.info(f"📨 [NOTIFY] أُرسلت: {_strip_tags(chunk)[:60]!r}")
                    break

                desc = ""
                retry_after = 0
                try:
                    j = r.json()
                    desc = j.get("description", "")
                    retry_after = int(j.get("parameters", {}).get("retry_after", 0))
                except Exception:
                    desc = r.text[:150]

                if r.status_code == 429:
                    time.sleep(min(retry_after or 3, 30))
                    continue
                if r.status_code == 400 and "parse" in desc.lower() and mode:
                    # خطأ HTML → أعد الإرسال كنص عادي
                    mode = None
                    payload_text = _strip_tags(chunk)
                    continue
                if r.status_code in (401, 403, 404):
                    logger.error(f"❌ [NOTIFY] Telegram رفض ({r.status_code}): {desc} "
                                 f"— تحقق من TELEGRAM_TOKEN / TELEGRAM_CHAT_ID، "
                                 f"وأرسل /start للبوت من حسابك")
                    break
                logger.warning(f"⚠️ [NOTIFY] HTTP {r.status_code} (محاولة {attempt}): {desc}")
            except Exception as e:
                logger.warning(f"⚠️ [NOTIFY] خطأ اتصال (محاولة {attempt}): {e}")
            time.sleep(2 * attempt)

        if not ok:
            ok_all = False
            logger.error(f"❌ [NOTIFY] فشل إرسال الرسالة: {_strip_tags(chunk)[:80]!r}")
    return ok_all


def send_async(text, parse_mode="HTML"):
    """إرسال في خيط خلفي كي لا يعطل التداول."""
    threading.Thread(target=send_text, args=(text, parse_mode), daemon=True,
                     name="Notify").start()


def _fmt(n, d=4):
    try:
        if n is None:
            return "-"
        return f"{float(n):.{d}f}"
    except Exception:
        return str(n)


# ==================== بدء التشغيل ====================

_startup_sent = False


def notify_startup(core=None):
    """رسالة 'بدأ البوت العمل' — مرة واحدة لكل تشغيل."""
    global _startup_sent
    if _startup_sent or not _cfg("ENABLE_STARTUP_NOTIFICATION", True):
        return
    _startup_sent = True

    def _run():
        try:
            balance, n_pos = None, None
            if core:
                try:
                    balance = core.get_futures_balance()
                except Exception:
                    pass
                try:
                    pos = core.get_open_positions_strict()
                    n_pos = len(pos) if pos is not None else None
                except Exception:
                    pass
            mode = "🧪 تجريبي (Testnet)" if _cfg("USE_TESTNET", False) else "💰 حقيقي"
            msg = (
                "🚀 <b>بدأ البوت العمل</b>\n\n"
                f"🏦 <b>الحساب:</b> {mode}\n"
                f"💵 <b>الرصيد:</b> <code>{_fmt(balance, 2)}</code> USDT\n"
                f"📂 <b>صفقات مفتوحة:</b> {n_pos if n_pos is not None else '-'}\n\n"
                f"⚙️ <b>الإعدادات:</b>\n"
                f"   • مبلغ الصفقة: {_cfg('TRADE_USDT', 10)}$\n"
                f"   • الرافعة: {_cfg('LEVERAGE', 15)}x\n"
                f"   • الحد الأقصى للصفقات: {_cfg('MAX_OPEN_POSITIONS', 6)}\n"
                f"   • المسح كل {int(_cfg('AUTO_SCAN_INTERVAL', 420)) // 60} دقيقة\n\n"
                f"⏰ {time.strftime('%Y-%m-%d %H:%M:%S')} (UTC)"
            )
            send_text(msg)
        except Exception as e:
            logger.error(f"❌ [NOTIFY] startup: {e}")

    threading.Thread(target=_run, daemon=True, name="NotifyStartup").start()


# ==================== فتح صفقة ====================

def notify_trade_opened(result, signal=None, amount=None, leverage=None):
    """إشعار فتح صفقة (يُستدعى بعد نجاح أمر الدخول)."""
    if not _cfg("ENABLE_OPEN_NOTIFICATIONS", True):
        return
    try:
        symbol = result.get("symbol")
        side = str(result.get("side", "")).upper()
        pside = result.get("positionSide", "LONG" if side == "BUY" else "SHORT")
        entry = result.get("entry_price")
        qty = result.get("quantity")

        if result.get("closed_due_to_failure"):
            send_async(
                "⚠️ <b>فشل إنشاء TP/SL</b>\n\n"
                f"💰 <b>العملة:</b> {symbol}\n"
                "🔒 <b>الإجراء:</b> أُغلقت الصفقة فوراً حمايةً لرأس المال"
            )
            return

        arrow = "🟢 شراء (LONG)" if pside == "LONG" else "🔴 بيع (SHORT)"
        msg = (
            "✅ <b>تم فتح صفقة جديدة</b>\n\n"
            f"💰 <b>العملة:</b> {symbol}\n"
            f"📈 <b>الاتجاه:</b> {arrow}\n"
            f"💵 <b>سعر الدخول:</b> <code>{_fmt(entry)}</code>\n"
            f"⚖️ <b>الكمية:</b> <code>{_fmt(qty, 6)}</code>\n"
        )
        if amount is not None:
            msg += f"💼 <b>المبلغ:</b> {amount}$"
            if leverage:
                msg += f" × {leverage}x"
            msg += "\n"

        tp = result.get("tp_results", {}) or {}
        tps = [t for t in tp.get("tp_orders", []) if t.get("success")]
        if tps:
            msg += "\n🎯 <b>الأهداف:</b>\n"
            for t in tps:
                try:
                    pct = (float(t["tp_price"]) - float(entry)) / float(entry) * 100
                    if pside == "SHORT":
                        pct = -pct
                    pct_s = f" ({pct:+.2f}%)"
                except Exception:
                    pct_s = ""
                msg += f"   • TP{t.get('level')}: <code>{_fmt(t.get('tp_price'))}</code>{pct_s}\n"

        if tp.get("sl_success"):
            sl_pct_s = ""
            try:
                sl_pct = (float(tp.get("sl_price")) - float(entry)) / float(entry) * 100
                if pside == "SHORT":
                    sl_pct = -sl_pct
                sl_pct_s = f" ({sl_pct:+.2f}%)"
            except Exception:
                pass
            msg += f"\n🛡️ <b>SL:</b> <code>{_fmt(tp.get('sl_price'))}</code>{sl_pct_s}\n"
        else:
            msg += "\n🚨 <b>تحذير: لا يوجد SL!</b>\n"

        if signal:
            try:
                score = signal.get("score") or signal.get("total_score")
                if score is not None:
                    msg += f"\n📊 <b>التقييم:</b> {score}/100"
            except Exception:
                pass

        send_async(msg)
    except Exception as e:
        logger.error(f"❌ [NOTIFY] opened: {e}")


# ==================== إغلاق صفقة ====================

def notify_trade_closed(symbol, pside, entry, exit_price, qty, pnl, partial=False):
    if not _cfg("ENABLE_CLOSE_NOTIFICATIONS", True):
        return
    try:
        if pnl is None:
            icon, label = "ℹ️", "تم الإغلاق"
        elif pnl > 0.0001:
            icon, label = "✅", "ربح"
        elif pnl < -0.0001:
            icon, label = "❌", "خسارة"
        else:
            icon, label = "➖", "تعادل"

        title = "إغلاق جزئي (هدف تحقق)" if partial else "تم إغلاق الصفقة"
        side_txt = "LONG 🟢" if pside == "LONG" else "SHORT 🔴"
        msg = (
            f"{icon} <b>{title}</b>\n\n"
            f"💰 <b>العملة:</b> {symbol}\n"
            f"📈 <b>الاتجاه:</b> {side_txt}\n"
            f"💵 <b>الدخول:</b> <code>{_fmt(entry)}</code>\n"
        )
        if exit_price:
            msg += f"🏁 <b>الخروج:</b> <code>{_fmt(exit_price)}</code>\n"
        msg += f"⚖️ <b>الكمية المغلقة:</b> <code>{_fmt(qty, 6)}</code>\n"
        if pnl is not None:
            msg += f"\n{icon} <b>النتيجة ({label}):</b> <code>{pnl:+.3f}</code> USDT"
        send_async(msg)
    except Exception as e:
        logger.error(f"❌ [NOTIFY] closed: {e}")


# ==================== كشف الإغلاق ====================

class PositionTracker:
    """
    يقارن لقطة الصفقات المفتوحة على Binance بين دورتين:
      - صفقة اختفت       → إغلاق كامل
      - كمية نقصت        → إغلاق جزئي (TP1/TP2)
    يستخدم get_open_positions_strict كي لا يعتبر فشل الاتصال إغلاقاً.
    """

    def __init__(self, core):
        self.core = core
        self.prev = None
        self.last_check = time.time()
        self._lock = threading.Lock()

    @staticmethod
    def _key(p):
        return f"{p.get('symbol')}_{p.get('positionSide')}"

    def _snapshot(self):
        positions = self.core.get_open_positions_strict()
        if positions is None:
            return None
        snap = {}
        for p in positions:
            try:
                snap[self._key(p)] = {
                    "symbol": p["symbol"],
                    "positionSide": p["positionSide"],
                    "qty": abs(float(p["positionAmt"])),
                    "entry": float(p["entryPrice"]),
                }
            except Exception:
                continue
        return snap

    def _realized(self, symbol, since_ts):
        """مجموع (الربح المحقق + العمولة + التمويل) للعملة منذ since_ts + سعر الخروج التقريبي."""
        pnl, exit_price = None, None
        try:
            client = self.core.get_client()
            start = int((since_ts - 90) * 1000)
            rows = client.futures_income_history(symbol=symbol, startTime=start, limit=200) or []
            total, found = 0.0, False
            for r in rows:
                if r.get("incomeType") in ("REALIZED_PNL", "COMMISSION", "FUNDING_FEE"):
                    total += float(r.get("income", 0))
                    found = True
            if found:
                pnl = total
        except Exception as e:
            logger.debug(f"[TRACKER] income {symbol}: {e}")
        try:
            client = self.core.get_client()
            start = int((since_ts - 90) * 1000)
            trades = client.futures_account_trades(symbol=symbol, startTime=start, limit=100) or []
            reduce_fills = [t for t in trades if abs(float(t.get("realizedPnl", 0))) > 0]
            if reduce_fills:
                q = sum(float(t["qty"]) for t in reduce_fills)
                exit_price = sum(float(t["price"]) * float(t["qty"]) for t in reduce_fills) / q
        except Exception as e:
            logger.debug(f"[TRACKER] trades {symbol}: {e}")
        if exit_price is None:
            try:
                exit_price = self.core.get_price(symbol)
            except Exception:
                pass
        return pnl, exit_price

    def check(self):
        with self._lock:
            snap = self._snapshot()
            now = time.time()
            if snap is None:
                return
            if self.prev is None:          # أول لقطة بعد التشغيل
                self.prev, self.last_check = snap, now
                return

            events = []
            for key, old in self.prev.items():
                cur = snap.get(key)
                if cur is None:
                    events.append((old, old["qty"], False))
                elif cur["qty"] < old["qty"] * 0.98:
                    events.append((old, old["qty"] - cur["qty"], True))

            since = self.last_check
            self.prev, self.last_check = snap, now

        if events:
            time.sleep(3)  # دع Binance يسجل الدخل المحقق
        for old, closed_qty, partial in events:
            pnl, exit_price = self._realized(old["symbol"], since)
            logger.info(f"🔔 [TRACKER] {'جزئي' if partial else 'إغلاق'} {old['symbol']} "
                        f"{old['positionSide']} pnl={pnl}")
            notify_trade_closed(old["symbol"], old["positionSide"], old["entry"],
                                exit_price, closed_qty, pnl, partial=partial)
