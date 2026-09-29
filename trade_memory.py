# ==================================================
# 📁 ملف: trade_memory.py - ذاكرة الصفقات الذكية v7.0
# 🔧 التعديلات v7.0 (إصلاح التعلم):
#    - 🔥 PnL الحقيقي من Binance (REALIZED_PNL + COMMISSION + FUNDING) منذ الدخول
#    - 🔥 ساعة الدخول الصحيحة (كانت ساعة الإغلاق)
#    - 🔥 الحظر مؤقت ومبني على نافذة زمنية (لا حظر دائم من أرقام قديمة)
#    - 🔥 الصفقات غير الموثقة (pnl_verified=False) لا تدخل في قرارات الحظر أو التعلم
#    - 🔥 reconcile_legacy_trades: تصحيح الصفقات القديمة من سجل Binance
# 🔧 التعديلات v6.0:
#    - 🔥 إضافة is_symbol_permanently_blocked (حظر دائم)
#    - 🔥 Firebase Backup
#    - 🔥 مزامنة عند البدء
#    - 🔥 حفظ فوري بعد كل صفقة
# 📅 التاريخ: 2026-09-28
# ==================================================

import json
import os
import logging
import threading
import time
from datetime import datetime, timedelta
from threading import Lock

logger = logging.getLogger("trade_memory")

MEMORY_FILE = "trade_memory.json"
MAX_TRADES_TO_KEEP = 100
_lock = Lock()

try:
    from config import COMMISSION_RATE
except ImportError:
    COMMISSION_RATE = 0.0004

try:
    import config as _cfg_module
except ImportError:
    _cfg_module = None


def _c(name, default):
    """قراءة إعداد من config بأمان"""
    try:
        return getattr(_cfg_module, name, default) if _cfg_module else default
    except Exception:
        return default


def _loss_eps():
    return float(_c('LOSS_EPSILON', 0.10))

# 🔥 Firebase Backup
try:
    import firebase_backup
    FIREBASE_AVAILABLE = True
except ImportError:
    FIREBASE_AVAILABLE = False
    firebase_backup = None

# 🔥 إعدادات Firebase
try:
    from config import (
        ENABLE_FIREBASE_BACKUP,
        FIREBASE_BACKUP_INTERVAL
    )
except ImportError:
    ENABLE_FIREBASE_BACKUP = False
    FIREBASE_BACKUP_INTERVAL = 30


def _ensure_memory_file():
    if not os.path.exists(MEMORY_FILE):
        initial_data = {
            "trades": [], "symbol_stats": {}, "hourly_stats": {},
            "condition_stats": {}, "last_updated": datetime.now().isoformat(),
            "total_trades": 0, "total_wins": 0,
            "total_losses": 0, "total_pnl": 0.0
        }
        with open(MEMORY_FILE, "w", encoding="utf-8") as f:
            json.dump(initial_data, f, indent=2, ensure_ascii=False)


def load_memory():
    try:
        _ensure_memory_file()
        with open(MEMORY_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"خطأ في تحميل الذاكرة: {e}")
        return {
            "trades": [], "symbol_stats": {}, "hourly_stats": {},
            "condition_stats": {}, "total_trades": 0, "total_wins": 0,
            "total_losses": 0, "total_pnl": 0.0
        }


def save_memory(data):
    try:
        data["last_updated"] = datetime.now().isoformat()
        with open(MEMORY_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        return True
    except Exception as e:
        logger.error(f"خطأ في حفظ الذاكرة: {e}")
        return False


# ==================== 🔥 Firebase Backup ====================

def backup_to_firebase(memory_data=None):
    try:
        if not FIREBASE_AVAILABLE:
            return False

        if not firebase_backup.is_available():
            return False

        if memory_data is None:
            memory_data = load_memory()

        return firebase_backup.save_to_firebase(memory_data)

    except Exception as e:
        logger.error(f"❌ فشل backup_to_firebase: {e}")
        return False


def sync_from_firebase():
    try:
        if not FIREBASE_AVAILABLE:
            logger.info("ℹ️ Firebase غير متاح")
            return False

        if not firebase_backup.is_available():
            logger.info("ℹ️ Firebase غير مهيأ")
            return False

        return firebase_backup.sync_from_firebase_on_startup()

    except Exception as e:
        logger.error(f"❌ فشل sync_from_firebase: {e}")
        return False


def start_auto_backup():
    try:
        if not ENABLE_FIREBASE_BACKUP:
            logger.info("ℹ️ Firebase Backup معطل")
            return False

        if not FIREBASE_AVAILABLE:
            logger.warning("⚠️ Firebase غير متاح")
            return False

        return firebase_backup.start_auto_backup()

    except Exception as e:
        logger.error(f"❌ فشل start_auto_backup: {e}")
        return False


# ==================== 🔥 الحظر الدائم (جديد v6.0) ====================

def is_symbol_permanently_blocked(symbol):
    """
    🔥 v7: حظر مؤقت (الاسم قديم للتوافق). يعتمد على الصفقات الموثقة داخل نافذة
    SYMBOL_BLOCK_WINDOW_HOURS فقط، فينتهي تلقائياً بمرور الوقت.
    (صفقة SL كاملة ≈ -2$ برافعة 15x، لذلك العتبات بالدولار مُعايرة على ذلك)
    """
    try:
        stats = get_windowed_stats(symbol)
        if stats["count"] == 0:
            return False, ""

        hours = int(_c('SYMBOL_BLOCK_WINDOW_HOURS', 48))
        two_loss_usd = float(_c('SYMBOL_BLOCK_LOSS_USDT', 3.0))
        total_loss_usd = float(_c('SYMBOL_BLOCK_TOTAL_LOSS_USDT', 6.0))

        if stats["consecutive_losses"] >= 2 and stats["total_pnl"] < -two_loss_usd:
            return True, f"خسارتان متتاليتان ({stats['total_pnl']:.2f}$ خلال {hours}س)"

        if stats["losses"] >= 3 and stats["wins"] == 0:
            return True, f"{stats['losses']} خسائر بلا ربح خلال {hours}س"

        if stats["total_pnl"] < -total_loss_usd:
            return True, f"خسارة {stats['total_pnl']:.2f}$ خلال {hours}س"

        return False, ""
    except Exception as e:
        logger.error(f"خطأ في is_symbol_permanently_blocked: {e}")
        return False, ""


# ==================== 🔥 أدوات v7.0 ====================

def _trade_ts(t):
    """وقت الصفقة (الإغلاق إن وجد وإلا الدخول)"""
    return t.get("closed_at") or t.get("entry_time") or ""


def _is_loss(t):
    if "is_loss" in t:
        return bool(t["is_loss"])
    return t.get("pnl", 0) < -_loss_eps()


def get_verified_trades(days=None, limit=None):
    """الصفقات ذات PnL الحقيقي الموثق فقط (للتعلم والحظر)"""
    try:
        memory = load_memory()
        trades = [t for t in memory.get("trades", []) if t.get("pnl_verified")]
        if days:
            cutoff = (datetime.now() - timedelta(days=days)).isoformat()
            trades = [t for t in trades if _trade_ts(t) >= cutoff]
        if limit:
            trades = trades[-limit:]
        return trades
    except Exception as e:
        logger.error(f"خطأ في get_verified_trades: {e}")
        return []


def get_real_net_pnl(symbol, entry_time_iso, end_time_ms=None, retries=3):
    """
    🔥 PnL الحقيقي الصافي من سجل دخل Binance منذ وقت الدخول.
    يجمع: REALIZED_PNL + COMMISSION + FUNDING_FEE (كل الأهداف الجزئية تُحسب).
    يرجع dict أو None عند الفشل.
    """
    try:
        import core_functions as core
        client_obj = core.get_client()
        if not client_obj:
            return None

        try:
            entry_ts = int(datetime.fromisoformat(entry_time_iso).timestamp() * 1000)
        except Exception:
            return None

        # هامش 3 دقائق: عمولة الدخول تسبق تسجيل وقت الدخول بثوانٍ
        start_ms = entry_ts - 180000

        for attempt in range(max(1, retries)):
            kwargs = dict(symbol=symbol, startTime=start_ms, limit=1000)
            if end_time_ms:
                kwargs['endTime'] = int(end_time_ms)
            rows = client_obj.futures_income_history(**kwargs)

            realized = commission = funding = 0.0
            has_realized = False
            last_realized_time = 0
            for r in rows or []:
                typ = r.get('incomeType')
                val = float(r.get('income', 0) or 0)
                if typ == 'REALIZED_PNL':
                    realized += val
                    has_realized = True
                    last_realized_time = max(last_realized_time, int(r.get('time', 0)))
                elif typ == 'COMMISSION':
                    commission += val
                elif typ == 'FUNDING_FEE':
                    funding += val

            if has_realized:
                return {
                    'net': round(realized + commission + funding, 6),
                    'realized': round(realized, 6),
                    'commission': round(commission, 6),
                    'funding': round(funding, 6),
                    'closed_at_ms': last_realized_time,
                }

            # قد يتأخر ظهور السجل بضع ثوانٍ بعد الإغلاق
            if attempt < retries - 1:
                time.sleep(3)

        return None

    except Exception as e:
        logger.warning(f"⚠️ تعذر جلب PnL الحقيقي لـ {symbol}: {e}")
        return None


def get_windowed_stats(symbol, hours=None):
    """إحصائيات العملة من الصفقات الموثقة داخل نافذة زمنية فقط"""
    try:
        hours = hours or int(_c('SYMBOL_BLOCK_WINDOW_HOURS', 48))
        cutoff = (datetime.now() - timedelta(hours=hours)).isoformat()
        trades = [
            t for t in load_memory().get("trades", [])
            if t.get("symbol") == symbol and t.get("pnl_verified") and _trade_ts(t) >= cutoff
        ]
        wins = sum(1 for t in trades if t.get("is_win"))
        losses = sum(1 for t in trades if _is_loss(t))
        total_pnl = round(sum(t.get("pnl", 0) for t in trades), 4)

        consecutive = 0
        for t in reversed(trades):
            if _is_loss(t):
                consecutive += 1
            elif t.get("is_win"):
                break

        return {
            "wins": wins, "losses": losses, "total_pnl": total_pnl,
            "consecutive_losses": consecutive, "count": len(trades),
        }
    except Exception as e:
        logger.error(f"خطأ في get_windowed_stats: {e}")
        return {"wins": 0, "losses": 0, "total_pnl": 0.0, "consecutive_losses": 0, "count": 0}


def rebuild_stats(memory):
    """إعادة بناء symbol_stats و hourly_stats من الصفقات الموثقة فقط"""
    symbol_stats = {}
    hourly_stats = {}
    for t in memory.get("trades", []):
        if not t.get("pnl_verified"):
            continue
        sym = t.get("symbol")
        pnl = t.get("pnl", 0)
        st = symbol_stats.setdefault(sym, {
            "wins": 0, "losses": 0, "total_pnl": 0.0, "last_trade": None,
            "consecutive_losses": 0, "avg_confidence": 0, "avg_pnl": 0
        })
        if t.get("is_win"):
            st["wins"] += 1
            st["consecutive_losses"] = 0
        elif _is_loss(t):
            st["losses"] += 1
            st["consecutive_losses"] += 1
        st["total_pnl"] = round(st["total_pnl"] + pnl, 4)
        st["last_trade"] = _trade_ts(t)

        try:
            hour = str(datetime.fromisoformat(t.get("entry_time")).hour)
        except Exception:
            hour = str(t.get("hour", 0))
        hs = hourly_stats.setdefault(hour, {"wins": 0, "losses": 0, "total_pnl": 0.0})
        if t.get("is_win"):
            hs["wins"] += 1
        elif _is_loss(t):
            hs["losses"] += 1
        hs["total_pnl"] = round(hs["total_pnl"] + pnl, 4)

    for sym, st in symbol_stats.items():
        total = st["wins"] + st["losses"]
        st["avg_pnl"] = round(st["total_pnl"] / total, 4) if total else 0

    memory["symbol_stats"] = symbol_stats
    memory["hourly_stats"] = hourly_stats
    return memory


def migrate_legacy_trades():
    """
    🔥 ترحيل الصفقات القديمة: تُعلَّم غير موثقة (لا تدخل في الحظر/التعلم)
    ثم تُعاد الإحصائيات من الصفقات الموثقة فقط. آمنة للتكرار.
    """
    try:
        with _lock:
            memory = load_memory()
            changed = False
            for t in memory.get("trades", []):
                if "pnl_verified" not in t:
                    t["pnl_verified"] = False
                    t["legacy"] = True
                    changed = True
                if "is_loss" not in t:
                    t["is_loss"] = t.get("pnl", 0) < -_loss_eps()
                    changed = True

            if changed or memory.get("schema_version") != 7:
                memory["schema_version"] = 7
                rebuild_stats(memory)
                save_memory(memory)
                logger.info("✅ ترحيل الذاكرة v7: الصفقات القديمة غير موثقة حتى التصحيح")
                return True
        return False
    except Exception as e:
        logger.error(f"❌ فشل ترحيل الذاكرة: {e}")
        return False


def reconcile_legacy_trades(max_hold_hours=12, min_age_minutes=10, max_calls=120):
    """
    🔥 تصحيح الصفقات غير الموثقة من سجل Binance.
    النافذة: من الدخول حتى (الصفقة التالية على نفس العملة أو max_hold_hours).
    تعليم reconciled=True حتى يُعرف أن الرقم مُعاد حسابه.
    """
    try:
        with _lock:
            memory = load_memory()
            trades = memory.get("trades", [])

        now = datetime.now()
        fixed = 0
        calls = 0

        for idx, t in enumerate(trades):
            if t.get("pnl_verified"):
                continue
            entry_iso = t.get("entry_time")
            if not entry_iso:
                continue
            try:
                entry_dt = datetime.fromisoformat(entry_iso)
            except Exception:
                continue
            if (now - entry_dt).total_seconds() < min_age_minutes * 60:
                continue
            if calls >= max_calls:
                break

            end_dt = entry_dt + timedelta(hours=max_hold_hours)
            for nxt in trades[idx + 1:]:
                if nxt.get("symbol") == t.get("symbol") and nxt.get("entry_time"):
                    try:
                        nxt_dt = datetime.fromisoformat(nxt["entry_time"])
                        if nxt_dt > entry_dt:
                            end_dt = min(end_dt, nxt_dt - timedelta(seconds=200))
                        break
                    except Exception:
                        pass
            end_dt = min(end_dt, now)

            calls += 1
            res = get_real_net_pnl(
                t.get("symbol"), entry_iso,
                end_time_ms=int(end_dt.timestamp() * 1000), retries=1
            )
            time.sleep(0.3)
            if not res:
                continue

            net = res['net']
            t["pnl_gross"] = round(res['realized'], 4)
            t["pnl"] = round(net, 4)
            t["is_win"] = net > 0.01
            t["is_loss"] = net < -_loss_eps()
            pos_value = (t.get("entry_price", 0) or 0) * (t.get("quantity", 0) or 0)
            t["pnl_percent"] = round((net / pos_value * 100), 4) if pos_value > 0 else 0
            if res.get('closed_at_ms'):
                t["closed_at"] = datetime.fromtimestamp(res['closed_at_ms'] / 1000).isoformat()
            try:
                t["hour"] = entry_dt.hour
                t["day_of_week"] = entry_dt.weekday()
            except Exception:
                pass
            t["pnl_verified"] = True
            t["reconciled"] = True
            fixed += 1

        if fixed:
            with _lock:
                # أعد قراءة الذاكرة لتفادي دهس صفقات سُجلت أثناء العملية
                latest = load_memory()
                by_key = {(x.get("symbol"), x.get("entry_time")): x for x in trades}
                merged = []
                for x in latest.get("trades", []):
                    merged.append(by_key.get((x.get("symbol"), x.get("entry_time")), x))
                latest["trades"] = merged
                latest["total_pnl"] = round(sum(x.get("pnl", 0) for x in merged), 4)
                latest["total_wins"] = sum(1 for x in merged if x.get("is_win"))
                latest["total_losses"] = sum(1 for x in merged if _is_loss(x))
                rebuild_stats(latest)
                save_memory(latest)
                if ENABLE_FIREBASE_BACKUP and FIREBASE_AVAILABLE:
                    try:
                        threading.Thread(target=backup_to_firebase, args=(latest,), daemon=True).start()
                    except Exception:
                        pass
            logger.info(f"✅ تم تصحيح {fixed} صفقة من سجل Binance")

        return fixed

    except Exception as e:
        logger.error(f"❌ فشل reconcile_legacy_trades: {e}")
        return 0


# ==================== جلب سعر الخروج ====================

def get_exit_price(symbol, entry_time_iso):
    try:
        import core_functions as core
        client_obj = core.get_client()
        if not client_obj:
            return 0.0

        try:
            entry_dt = datetime.fromisoformat(entry_time_iso)
            entry_ts = int(entry_dt.timestamp() * 1000)
        except:
            entry_ts = int((datetime.now() - timedelta(hours=2)).timestamp() * 1000)

        trades = client_obj.futures_account_trades(
            symbol=symbol, startTime=entry_ts, limit=20
        )

        if not trades:
            return 0.0

        return float(trades[-1].get('price', 0))

    except Exception as e:
        logger.warning(f"⚠️ تعذر جلب exit_price: {e}")
        return 0.0


def calculate_net_pnl(entry_price, exit_price, quantity, direction):
    try:
        if not entry_price or not quantity:
            return 0.0

        if direction == "BUY":
            gross_pnl = (exit_price - entry_price) * quantity
        else:
            gross_pnl = (entry_price - exit_price) * quantity

        entry_commission = entry_price * quantity * COMMISSION_RATE
        exit_commission = exit_price * quantity * COMMISSION_RATE
        total_commission = entry_commission + exit_commission

        net_pnl = gross_pnl - total_commission
        return round(net_pnl, 6)

    except Exception as e:
        logger.error(f"خطأ: {e}")
        return 0.0


# ==================== تسجيل الصفقة ====================

def record_trade(symbol, direction, entry_price, exit_price,
                 quantity, pnl, confidence, timeframe_alignment,
                 volume_ratio, groq_recommendation, groq_confidence,
                 score_details=None, exit_reason="unknown",
                 entry_time_iso=None, net_pnl=None, closed_at_iso=None,
                 breakdown=None):
    """
    🔥 v7: إذا مُرِّر net_pnl (من get_real_net_pnl) يُسجَّل كصفقة موثقة.
    وإلا يُقدَّر الرقم وتُعلَّم الصفقة غير موثقة (لا تدخل في الحظر أو التعلم
    حتى يصححها reconcile_legacy_trades).
    """
    try:
        with _lock:
            memory = load_memory()

            verified = net_pnl is not None

            if not exit_price or exit_price == 0:
                try:
                    if entry_time_iso:
                        exit_price = get_exit_price(symbol, entry_time_iso)
                except Exception:
                    exit_price = 0

            if verified:
                net = float(net_pnl)
            elif exit_price and exit_price > 0:
                net = calculate_net_pnl(entry_price, exit_price, quantity, direction)
            else:
                commission = entry_price * quantity * COMMISSION_RATE * 2
                net = pnl - commission

            is_win = net > 0.01
            is_loss = net < -_loss_eps()

            position_value = entry_price * quantity
            pnl_percent = (net / position_value * 100) if position_value > 0 else 0

            try:
                entry_dt = datetime.fromisoformat(entry_time_iso) if entry_time_iso else datetime.now()
            except Exception:
                entry_dt = datetime.now()

            trade_record = {
                "id": len(memory["trades"]) + 1,
                "symbol": symbol, "direction": direction,
                "entry_price": entry_price,
                "exit_price": round(exit_price, 8) if exit_price else 0,
                "quantity": quantity,
                "pnl_gross": round((breakdown or {}).get('realized', pnl), 4),
                "pnl": round(net, 4),
                "pnl_percent": round(pnl_percent, 4),
                "is_win": is_win,
                "is_loss": is_loss,
                "pnl_verified": verified,
                "confidence": confidence,
                "timeframe_alignment": timeframe_alignment,
                "volume_ratio": volume_ratio,
                "groq_recommendation": groq_recommendation,
                "groq_confidence": groq_confidence,
                "score_details": score_details or {},
                "exit_reason": exit_reason,
                "entry_time": entry_dt.isoformat(),
                "closed_at": closed_at_iso or datetime.now().isoformat(),
                "hour": entry_dt.hour,
                "day_of_week": entry_dt.weekday(),
                "date": entry_dt.strftime("%Y-%m-%d")
            }
            if breakdown:
                trade_record["fees"] = round(breakdown.get('commission', 0) + breakdown.get('funding', 0), 6)

            memory["trades"].append(trade_record)
            memory["total_trades"] += 1
            if is_win:
                memory["total_wins"] += 1
            elif is_loss:
                memory["total_losses"] += 1
            memory["total_pnl"] = round(memory["total_pnl"] + net, 4)

            # الإحصائيات تُبنى من الصفقات الموثقة فقط
            rebuild_stats(memory)

            if len(memory["trades"]) > MAX_TRADES_TO_KEEP:
                memory["trades"] = memory["trades"][-MAX_TRADES_TO_KEEP:]

            save_memory(memory)

            if ENABLE_FIREBASE_BACKUP and FIREBASE_AVAILABLE:
                try:
                    threading.Thread(
                        target=backup_to_firebase,
                        args=(memory,),
                        daemon=True
                    ).start()
                except Exception:
                    pass

            status = "✅" if is_win else ("❌" if is_loss else "➖")
            tag = "" if verified else " (تقدير غير موثق)"
            logger.info(f"📝 تسجيل: {symbol} {status} صافي: {net:+.4f}${tag}")

            return True

    except Exception as e:
        logger.error(f"خطأ: {e}")
        return False


# ==================== نقاط العملة ====================

def get_symbol_score(symbol):
    """🔥 v7: يعتمد على الصفقات الموثقة خلال 7 أيام"""
    try:
        stats = get_windowed_stats(symbol, hours=168)
        total = stats["wins"] + stats["losses"]

        if total == 0:
            return {'score': 50, 'should_trade': True, 'reason': 'لا يوجد تاريخ موثق', 'stats': stats}

        win_rate = stats["wins"] / total
        score = 50 + (win_rate - 0.5) * 100

        if stats["consecutive_losses"] >= 3:
            score -= 30
        elif stats["consecutive_losses"] >= 2:
            score -= 15

        if stats["total_pnl"] < -6.0:
            score -= 30
        elif stats["total_pnl"] < -3.0:
            score -= 15

        if win_rate >= 0.7 and total >= 5:
            score += 20
        elif win_rate >= 0.6 and total >= 3:
            score += 10

        score = max(0, min(100, score))

        should_trade = True
        reason = f"نسبة نجاح: {win_rate*100:.1f}% ({stats['wins']}/{total})"

        if stats["consecutive_losses"] >= 3:
            should_trade = False
            reason = f"⚠️ {stats['consecutive_losses']} خسائر متتالية"
        elif stats["total_pnl"] < -6.0:
            should_trade = False
            reason = "⚠️ خسارة كلية خلال 7 أيام"
        elif score < 30:
            should_trade = False
            reason = "⚠️ أداء ضعيف"

        return {
            'score': round(score, 2),
            'should_trade': should_trade,
            'reason': reason,
            'win_rate': round(win_rate * 100, 2),
            'total_trades': total,
            'total_pnl': stats['total_pnl'],
            'consecutive_losses': stats["consecutive_losses"],
            'stats': stats
        }

    except Exception as e:
        logger.error(f"خطأ: {e}")
        return {'score': 50, 'should_trade': True, 'reason': 'خطأ', 'stats': {}}


def get_hour_score(hour=None):
    try:
        if hour is None:
            hour = datetime.now().hour

        memory = load_memory()
        hour_key = str(hour)

        if hour_key not in memory["hourly_stats"]:
            return {'score': 50, 'should_trade': True, 'reason': 'ساعة جديدة'}

        stats = memory["hourly_stats"][hour_key]
        total = stats["wins"] + stats["losses"]

        if total < 3:
            return {'score': 50, 'should_trade': True, 'reason': 'بيانات غير كافية'}

        win_rate = stats["wins"] / total

        if win_rate < 0.3:
            return {'score': 20, 'should_trade': False, 'reason': f"⚠️ ساعة سيئة", 'win_rate': round(win_rate * 100, 2)}

        return {'score': round(win_rate * 100, 2), 'should_trade': True, 'reason': f"نسبة نجاح: {win_rate*100:.0f}%", 'win_rate': round(win_rate * 100, 2)}

    except Exception as e:
        logger.error(f"خطأ: {e}")
        return {'score': 50, 'should_trade': True, 'reason': 'خطأ'}


def get_memory_stats():
    try:
        memory = load_memory()
        total = memory["total_trades"]
        wins = memory["total_wins"]
        losses = memory["total_losses"]
        win_rate = (wins / total * 100) if total > 0 else 0

        yesterday = (datetime.now() - timedelta(days=1)).isoformat()
        recent_trades = [t for t in memory["trades"] if t.get("entry_time", "") >= yesterday]
        recent_wins = len([t for t in recent_trades if t["is_win"]])
        recent_pnl = sum(t["pnl"] for t in recent_trades)

        return {
            'total_trades': total,
            'total_wins': wins,
            'total_losses': losses,
            'win_rate': round(win_rate, 2),
            'total_pnl': memory["total_pnl"],
            'recent_24h_trades': len(recent_trades),
            'recent_24h_wins': recent_wins,
            'recent_24h_pnl': round(recent_pnl, 4),
            'last_updated': memory.get("last_updated", "N/A")
        }

    except Exception as e:
        logger.error(f"خطأ: {e}")
        return {}


def get_today_pnl():
    try:
        memory = load_memory()
        today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
        today_trades = [t for t in memory["trades"] if t.get("entry_time", "") >= today_start]
        total_pnl = sum(t.get("pnl", 0) for t in today_trades)
        return round(total_pnl, 4)
    except Exception as e:
        logger.error(f"خطأ: {e}")
        return 0.0


def get_all_trades_for_analysis(min_trades=10):
    try:
        memory = load_memory()
        trades = memory.get("trades", [])
        return trades[-min_trades:] if len(trades) >= min_trades else trades
    except:
        return []


def get_symbol_history(symbol, limit=10):
    try:
        memory = load_memory()
        trades = [t for t in memory["trades"] if t["symbol"] == symbol]
        return trades[-limit:]
    except:
        return []


def is_symbol_blacklisted(symbol, min_trades=5, max_win_rate=0.25, max_consecutive_losses=3):
    """🔥 v7: نافذة زمنية وصفقات موثقة فقط (7 أيام)"""
    try:
        stats = get_windowed_stats(symbol, hours=168)
        total = stats["wins"] + stats["losses"]

        if total < min_trades:
            return False, ""

        win_rate = stats["wins"] / total if total else 0
        if win_rate < max_win_rate:
            return True, f"نسبة نجاح منخفضة: {win_rate*100:.1f}% خلال 7 أيام"

        if stats["consecutive_losses"] >= max_consecutive_losses + 1:
            return True, f"{stats['consecutive_losses']} خسائر متتالية"

        return False, ""
    except Exception as e:
        logger.error(f"خطأ: {e}")
        return False, ""


def sync_profit_history():
    try:
        memory = load_memory()
        daily_profits = {}
        weekly_profits = {}
        monthly_profits = {}

        for trade in memory.get("trades", []):
            entry_time = trade.get("entry_time", "")
            if not entry_time:
                continue
            try:
                dt = datetime.fromisoformat(entry_time)
            except:
                continue

            date_key = dt.strftime("%Y-%m-%d")
            week_key = f"{dt.year}-W{dt.isocalendar()[1]:02d}"
            month_key = dt.strftime("%Y-%m")
            pnl = trade.get("pnl", 0)

            daily_profits[date_key] = round(daily_profits.get(date_key, 0) + pnl, 4)
            weekly_profits[week_key] = round(weekly_profits.get(week_key, 0) + pnl, 4)
            monthly_profits[month_key] = round(monthly_profits.get(month_key, 0) + pnl, 4)

        profit_history = {
            "daily_profits": daily_profits,
            "weekly_profits": weekly_profits,
            "monthly_profits": monthly_profits,
            "last_sync": datetime.now().isoformat(),
            "total_profit": memory.get("total_pnl", 0),
            "total_trades": memory.get("total_trades", 0)
        }

        with open("profit_history.json", "w", encoding="utf-8") as f:
            json.dump(profit_history, f, indent=2, ensure_ascii=False)

        logger.info(f"✅ تم مزامنة profit_history.json")
        return True

    except Exception as e:
        logger.error(f"خطأ: {e}")
        return False


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print("🧪 اختبار trade_memory v6.0...")
    net = calculate_net_pnl(entry_price=100, exit_price=101, quantity=1, direction="BUY")
    print(f"صافي الربح: {net}$")
    stats = get_memory_stats()
    print(f"إحصائيات: {stats}")
    # اختبار الحظر الدائم
    blocked, reason = is_symbol_permanently_blocked("BTCUSDT")
    print(f"BTCUSDT محظور؟ {blocked} - {reason}")