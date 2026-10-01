# ==================================================
# 📁 ملف: main_enhanced.py - الإصدار v5.7
# 🔧 التعديلات v5.7 (إصلاح التعلم + الاستمرارية):
#    - 🔥 تسجيل PnL الحقيقي الصافي من Binance (كل الأهداف الجزئية + العمولة)
#    - 🔥 تتبع الصفقات المفتوحة يُحفظ (ملف + Firebase) ولا يضيع عند إعادة التشغيل
#    - 🔥 لا يُعتبر فشل API إغلاقاً للصفقات (get_open_positions_strict)
#    - 🔥 التبريد يُحسب عند الإغلاق بنتيجة حقيقية
#    - 🔥 تقليل حجم الصفقة بعد خسائر متتالية + حد خسارة يومي
#    - 🔥 مراقب (Supervisor) يعيد تشغيل الخيوط المتوقفة ويعيد تشغيل العملية عند التجمّد
#    - 🔥 تعلم تكيفي فوري بعد كل صفقة (adaptive_rules)
# 🔧 التعديلات v5.6:
#    - 🔥 تنظيف الأوامر اليتيمة دورياً
#    - 🔥 تنظيف عند بدء البوت
#    - 🔥 حماية الصفقات اليدوية
# 📅 التاريخ: 2026-09-26
# ==================================================

import logging
import threading
import time
import asyncio
import json
import os
import gc
import traceback
from datetime import datetime

from config import *
import bot_enhanced as tgbot
import core_functions as core

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("main_enhanced")

logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

try:
    import bot_strategies_enhanced as strat
    logger.info("✅ تم تحميل النظام")
except ImportError as e:
    logger.error(f"❌ فشل: {e}")
    raise

try:
    from groq_integration import is_groq_available
    GROQ_AVAILABLE = is_groq_available()
    logger.info(f"🧠 Groq/Gemini: {'✅' if GROQ_AVAILABLE else '❌'}")
except ImportError:
    GROQ_AVAILABLE = False

try:
    import trade_memory as memory
    MEMORY_AVAILABLE = True
    logger.info("✅ ذاكرة الصفقات متاحة")
except ImportError:
    MEMORY_AVAILABLE = False
    logger.warning("⚠️ ذاكرة الصفقات غير متاحة")

try:
    from market_regime import MarketRegime
    MARKET_REGIME_AVAILABLE = True
    logger.info("✅ كشف حالة السوق متاح")
except ImportError:
    MARKET_REGIME_AVAILABLE = False
    logger.warning("⚠️ كشف حالة السوق غير متاح")

try:
    import realtime_data
    REALTIME_AVAILABLE = True
    logger.info("✅ realtime_data متاح")
except ImportError as e:
    REALTIME_AVAILABLE = False
    realtime_data = None
    logger.warning(f"⚠️ realtime_data غير متاح: {e}")

try:
    import smart_scheduler
    SCHEDULER_AVAILABLE = True
    logger.info("✅ نظام التعلم التلقائي متاح")
except ImportError as e:
    SCHEDULER_AVAILABLE = False
    smart_scheduler = None
    logger.warning(f"⚠️ smart_scheduler غير متاح: {e}")

try:
    import auto_learner
    LEARNER_AVAILABLE = True
    logger.info("✅ auto_learner متاح")
except ImportError:
    LEARNER_AVAILABLE = False

try:
    import auto_tuner
    TUNER_AVAILABLE = True
    logger.info("✅ auto_tuner متاح")
except ImportError:
    TUNER_AVAILABLE = False

try:
    import performance_tracker
    TRACKER_AVAILABLE = True
    logger.info("✅ performance_tracker متاح")
except ImportError:
    TRACKER_AVAILABLE = False

try:
    import daily_reporter
    REPORTER_AVAILABLE = True
    logger.info("✅ daily_reporter متاح")
except ImportError:
    REPORTER_AVAILABLE = False

try:
    import firebase_backup
    FIREBASE_AVAILABLE = True
    logger.info("✅ firebase_backup متاح")
except ImportError as e:
    FIREBASE_AVAILABLE = False
    firebase_backup = None
    logger.warning(f"⚠️ firebase_backup غير متاح: {e}")


try:
    import adaptive_rules
    ADAPTIVE_AVAILABLE = True
    logger.info("✅ adaptive_rules متاح")
except ImportError as e:
    ADAPTIVE_AVAILABLE = False
    adaptive_rules = None
    logger.warning(f"⚠️ adaptive_rules غير متاح: {e}")


_last_auto_scan = 0
_last_tp_sl_monitor = 0
_last_orphan_cleanup = 0
_auto_scan_enabled = True
_auto_trading_enabled = True

_open_trades_tracking = {}
_tracking_lock = threading.Lock()
_heartbeats = {}
_daily_limit_notified_date = None

STATE_FILE = "open_positions.json"
TRACKING_FILE = "open_trades_tracking.json"
TRACKING_FIREBASE_DOC = "open_trades_tracking"
MAX_CLOSE_ATTEMPTS = 6


def _beat(name):
    _heartbeats[name] = time.time()


def _notify(text):
    """إشعار Telegram (لا يفشل أبداً)"""
    try:
        if REPORTER_AVAILABLE:
            daily_reporter.send_telegram_message(text)
    except Exception as e:
        logger.debug(f"تعذر إرسال الإشعار: {e}")


# ==================== 🔥 حفظ تتبع الصفقات المفتوحة ====================

def _save_tracking():
    """حفظ _open_trades_tracking محلياً + Firebase"""
    try:
        with _tracking_lock:
            snapshot = json.loads(json.dumps(_open_trades_tracking, default=str))
        try:
            with open(TRACKING_FILE, "w", encoding="utf-8") as f:
                json.dump(snapshot, f, ensure_ascii=False)
        except Exception as e:
            logger.debug(f"تعذر حفظ tracking محلياً: {e}")

        if FIREBASE_AVAILABLE and firebase_backup and firebase_backup.is_available():
            threading.Thread(
                target=firebase_backup.save_doc,
                args=(TRACKING_FIREBASE_DOC, {"items": snapshot}),
                daemon=True
            ).start()
    except Exception as e:
        logger.debug(f"_save_tracking: {e}")


def _load_tracking():
    """استرجاع تتبع الصفقات (الأحدث بين المحلي و Firebase) ودمجه"""
    try:
        loaded = {}
        try:
            if os.path.exists(TRACKING_FILE):
                with open(TRACKING_FILE, "r", encoding="utf-8") as f:
                    loaded.update(json.load(f))
        except Exception:
            pass

        try:
            if FIREBASE_AVAILABLE and firebase_backup and firebase_backup.is_available():
                doc = firebase_backup.load_doc(TRACKING_FIREBASE_DOC)
                if doc and isinstance(doc.get("items"), dict):
                    for k, v in doc["items"].items():
                        loaded.setdefault(k, v)
        except Exception:
            pass

        if loaded:
            with _tracking_lock:
                for k, v in loaded.items():
                    _open_trades_tracking.setdefault(k, v)
            logger.info(f"✅ استرجاع تتبع {len(loaded)} صفقة مفتوحة")
    except Exception as e:
        logger.warning(f"⚠️ تعذر استرجاع التتبع: {e}")


# ==================== دوال آمنة ====================

def safe_float(value, default=0.0):
    try:
        return float(value)
    except (ValueError, TypeError):
        return default


def safe_int(value, default=0):
    try:
        return int(value)
    except (ValueError, TypeError):
        return default


# ==================== التمييز بين صفقات البوت واليدوية ====================

def _load_bot_owned_keys():
    try:
        if not os.path.exists(STATE_FILE):
            return set()
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        keys = set()
        for p in data:
            sym = p.get('symbol')
            side = p.get('positionSide')
            if sym and side:
                keys.add(f"{sym}_{side}")
        return keys
    except Exception as e:
        logger.error(f"خطأ في قراءة {STATE_FILE}: {e}")
        return set()


def get_bot_owned_positions():
    try:
        bot_keys = _load_bot_owned_keys()
        if not bot_keys:
            return []
        all_real = core.get_open_positions()
        return [p for p in all_real if f"{p['symbol']}_{p['positionSide']}" in bot_keys]
    except Exception as e:
        logger.error(f"خطأ في get_bot_owned_positions: {e}")
        return []


def get_manual_positions():
    try:
        bot_keys = _load_bot_owned_keys()
        all_real = core.get_open_positions()
        return [p for p in all_real if f"{p['symbol']}_{p['positionSide']}" not in bot_keys]
    except:
        return []


_last_trailing_restore = 0


def _restore_trailing_tracking():
    """
    حالة Breakeven/Trailing تُحفظ في الذاكرة فقط، فتضيع عند كل إعادة تشغيل/نشر.
    هنا نعيد تسجيل صفقات البوت المفتوحة التي فقدت تتبعها (بدونه لا يتحرك الوقف أبداً).
    """
    global _last_trailing_restore
    now = time.time()
    if now - _last_trailing_restore < 120:
        return
    _last_trailing_restore = now
    try:
        for p in get_bot_owned_positions():
            symbol = p['symbol']
            side = p['positionSide']
            key = f"{symbol}_{side}"
            if key in core._trailing_sl_positions:
                continue
            entry = safe_float(p.get('entryPrice', 0))
            qty = abs(safe_float(p.get('positionAmt', 0)))
            if entry <= 0 or qty <= 0:
                continue

            cur_sl = None
            for o in core.get_open_algo_orders(symbol):
                if o.get('type') == 'STOP_MARKET' and o.get('positionSide', side) == side:
                    cur_sl = safe_float(o.get('triggerPrice') or o.get('stopPrice')) or None
                    break

            core.setup_trailing_sl(symbol, side, entry, qty, sl_price=cur_sl)
            d = core._trailing_sl_positions.get(key)
            if not d:
                continue
            if cur_sl:
                locked = (cur_sl >= entry) if side == "LONG" else (cur_sl <= entry)
                if locked:
                    d['breakeven_set'] = True
            price = core.get_price(symbol)
            if price:
                d['highest_price'] = max(entry, price)
                d['lowest_price'] = min(entry, price)
            logger.info(f"♻️ [TRAILING] أُعيد تسجيل {key} بعد إعادة التشغيل (SL={cur_sl})")
    except Exception as e:
        logger.warning(f"⚠️ استعادة Trailing: {e}")


# ==================== دوال مساعدة ====================

def get_full_balance_info():
    try:
        client_obj = core.get_client()
        if not client_obj:
            return {}
        account = client_obj.futures_account()
        for asset in account.get('assets', []):
            if asset.get('asset') == 'USDT':
                return {
                    'available': safe_float(asset.get('availableBalance', 0)),
                    'wallet': safe_float(asset.get('walletBalance', 0)),
                    'unrealized_pnl': safe_float(asset.get('unrealizedProfit', 0)),
                    'margin': safe_float(asset.get('totalPositionInitialMargin', 0)),
                }
        return {}
    except:
        return {}


def run_async_safe(coro):
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()
    except Exception as e:
        if "Event loop is closed" not in str(e):
            logger.error(f"❌ خطأ async: {e}")
        return None


# ==================== البدء ====================

def send_startup():
    try:
        from telegram import Bot
        bot = Bot(token=TELEGRAM_TOKEN)

        count = len(core.get_all_futures_symbols())
        balance_info = get_full_balance_info()
        available = balance_info.get('available', 0)
        wallet = balance_info.get('wallet', 0)

        all_positions = core.get_open_positions()
        bot_positions = get_bot_owned_positions()
        manual_positions = get_manual_positions()

        daily = core.get_accurate_daily_pnl()
        weekly = core.get_accurate_weekly_pnl()
        monthly = core.get_accurate_monthly_pnl()

        firebase_status = "✅ مفعل" if ENABLE_FIREBASE_BACKUP and FIREBASE_AVAILABLE else "❌ معطل"

        memory_trades = 0
        if MEMORY_AVAILABLE:
            try:
                mem_stats = memory.get_memory_stats()
                memory_trades = mem_stats.get('total_trades', 0)
            except:
                pass

        msg = (
            f"🚀 <b>بوت القناص الذكي v5.6</b>\n\n"
            f"💰 <b>رأس المال:</b> {TRADE_USDT} USDT\n"
            f"⚡ <b>الرافعة:</b> {LEVERAGE}x\n"
            f"⏰ <b>المسح:</b> كل {AUTO_SCAN_INTERVAL // 60} دقيقة\n\n"
            f"🔥 <b>Firebase Backup:</b> {firebase_status}\n"
            f"📊 <b>الصفقات في الذاكرة:</b> {memory_trades}\n"
            f"🧹 <b>تنظيف الأوامر:</b> ✅\n"
            f"🏥 <b>Health Check:</b> ✅\n\n"
            f"📊 <b>الحالة:</b>\n"
            f"   • الأزواج: {count}\n"
            f"   • الرصيد المتاح: {available:.2f} USDT\n"
            f"   • الرصيد الإجمالي: {wallet:.2f} USDT\n"
            f"   • صفقات البوت: {len(bot_positions)}/{MAX_OPEN_POSITIONS}\n"
            f"   • صفقاتك اليدوية: {len(manual_positions)}\n\n"
            f"📈 <b>الأرباح:</b>\n"
            f"   • اليوم: {safe_float(daily.get('daily_pnl', 0)):.2f}\n"
            f"   • الأسبوع: {safe_float(weekly.get('weekly_pnl', 0)):.2f}\n"
            f"   • الشهر: {safe_float(monthly.get('monthly_pnl', 0)):.2f}\n\n"
            f"✅ <b>النظام جاهز!</b>"
        )

        async def send_async():
            # إرسال لوحة المفاتيح مع رسالة البدء ليتحدث شكلها تلقائياً بعد كل نشر
            await bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=msg, parse_mode="HTML",
                                   reply_markup=getattr(tgbot, 'main_kb', None))

        threading.Thread(target=run_async_safe, args=(send_async(),), daemon=True).start()

    except Exception as e:
        logger.error(f"خطأ في البدء: {e}")


# ==================== التوقف ====================

def check_trading_pause():
    is_paused, remaining = core.is_trading_paused()
    if is_paused:
        logger.warning(f"⏸️ توقف - {remaining} د")
        return True
    return False


# ==================== 🔥 خيط المراقبة الشاملة ====================

_last_excursion_save = 0


def _update_excursions():
    """
    يحدّث mfe_pct (أقصى ربح لحظي %) و mae_pct (أقصى خسارة لحظية %) لكل صفقة متتبعة.
    % من حركة السعر (لا من الهامش). يعتمد على unrealizedProfit فلا يحتاج طلبات إضافية ثقيلة.
    """
    global _last_excursion_save
    if not _open_trades_tracking:
        return

    positions = core.get_open_positions_strict()
    if not positions:
        return

    changed = False
    for p in positions:
        key = f"{p['symbol']}_{p['positionSide']}"
        with _tracking_lock:
            td = _open_trades_tracking.get(key)
            if not td:
                continue
            entry = safe_float(p.get('entryPrice', 0))
            amt = abs(safe_float(p.get('positionAmt', 0)))
            upnl = safe_float(p.get('unrealizedProfit', 0))
            notional = entry * amt
            if notional <= 0:
                continue
            pct = upnl / notional * 100
            if pct > td.get('mfe_pct', 0):
                td['mfe_pct'] = round(pct, 3)
                changed = True
            if pct < td.get('mae_pct', 0):
                td['mae_pct'] = round(pct, 3)
                changed = True

    # حفظ دوري كل 5 دقائق (لا مع كل تغيير)
    if changed and time.time() - _last_excursion_save > 300:
        _last_excursion_save = time.time()
        _save_tracking()


def monitor_positions_loop():
    """
    🔥 v5.6: مراقبة شاملة + تنظيف الأوامر اليتيمة
    """
    try:
        logger.info("📈 [THREAD] بدء المراقبة الشاملة...")

        global _last_tp_sl_monitor, _last_orphan_cleanup

        while _auto_scan_enabled:
            try:
                _beat('monitor')
                current_time = time.time()

                # 0. 🔥 v5.8: تتبع أقصى ربح/خسارة % لكل صفقة (MFE/MAE) لضبط SL/TP مستقبلاً
                try:
                    _update_excursions()
                except Exception as e:
                    logger.debug(f"excursions: {e}")

                # 1. Trailing SL
                _restore_trailing_tracking()
                updated = core.monitor_trailing_sl()
                if updated > 0:
                    logger.info(f"📊 تحديث Trailing: {updated} صفقة")

                # 2. TP/SL Check (كل دقيقة)
                if current_time - _last_tp_sl_monitor >= MONITOR_TP_SL_INTERVAL:
                    _last_tp_sl_monitor = current_time

                    bot_positions = get_bot_owned_positions()
                    if bot_positions:
                        for position in bot_positions:
                            symbol = position['symbol']
                            position_side = position['positionSide']

                            has_tp, has_sl, details = core.verify_tp_sl_created(symbol, position_side)

                            if not has_sl or not has_tp:
                                logger.warning(f"⚠️ {symbol} ناقص TP/SL")
                                core.check_and_add_tp_sl_to_existing_positions()
                                break

                # 🔥 3. تنظيف الأوامر اليتيمة (كل 5 دقائق)
                if current_time - _last_orphan_cleanup >= ORPHAN_CLEANUP_INTERVAL:
                    _last_orphan_cleanup = current_time
                    try:
                        cancelled = core.cleanup_orphan_algo_orders()
                        if cancelled > 0:
                            logger.info(f"🧹 تنظيف: {cancelled} أمر يتيم")
                    except Exception as e:
                        logger.warning(f"⚠️ فشل تنظيف الأوامر: {e}")

                # 4. الصفقات المغلقة
                check_closed_trades()

                # 5. تنظيف الذاكرة
                gc.collect()

            except Exception as e:
                logger.error(f"خطأ في المراقبة: {e}")

            time.sleep(30)

        logger.info("🛑 [THREAD] توقف المراقبة")

    except Exception as e:
        logger.error(f"❌ [THREAD] فشل المراقبة: {e}")
        traceback.print_exc()


def check_closed_trades():
    try:
        if not _open_trades_tracking:
            return

        # 🔥 لا نستنتج الإغلاق من فشل API
        current_positions = core.get_open_positions_strict()
        if current_positions is None:
            logger.warning("⚠️ تعذر قراءة الصفقات - تخطي فحص الإغلاق")
            return

        current_keys = set(f"{p['symbol']}_{p['positionSide']}" for p in current_positions)

        with _tracking_lock:
            closed_keys = [k for k in list(_open_trades_tracking.keys()) if k not in current_keys]

        if closed_keys:
            logger.info(f"🔔 اكتشف {len(closed_keys)} صفقة مغلقة")

        changed = False
        for key in closed_keys:
            with _tracking_lock:
                trade_data = _open_trades_tracking.get(key)
            if not trade_data:
                continue
            try:
                done = record_closed_trade(trade_data)
            except Exception as e:
                logger.error(f"خطأ في تسجيل الصفقة المغلقة: {e}")
                done = False

            if done:
                with _tracking_lock:
                    _open_trades_tracking.pop(key, None)
                changed = True
            else:
                # سيُعاد المحاولة في الدورة التالية (حتى MAX_CLOSE_ATTEMPTS)
                changed = True

        if changed:
            _save_tracking()

    except Exception as e:
        logger.error(f"خطأ في check_closed_trades: {e}")


def record_closed_trade(trade_data):
    """
    🔥 v5.7: يسجل النتيجة الحقيقية الصافية (كل الأهداف الجزئية + العمولة + التمويل).
    يرجع True عند اكتمال المعالجة، و False لإعادة المحاولة لاحقاً.
    """
    try:
        symbol = trade_data.get('symbol')
        direction = trade_data.get('direction', 'UNKNOWN')
        entry_price = safe_float(trade_data.get('entry_price', 0))
        quantity = safe_float(trade_data.get('quantity', 0))
        position_side = trade_data.get('positionSide', 'LONG')
        entry_time_iso = trade_data.get('entry_time_iso') or datetime.now().isoformat()
        attempts = safe_int(trade_data.get('_attempts', 0))

        logger.info(f"🔔 معالجة إغلاق: {symbol} {position_side} (محاولة {attempts + 1})")

        # ---- PnL الحقيقي ----
        real = None
        if MEMORY_AVAILABLE:
            if attempts == 0:
                time.sleep(4)  # انتظار ظهور آخر سجل REALIZED_PNL
            real = memory.get_real_net_pnl(symbol, entry_time_iso)

        if real is None and attempts < MAX_CLOSE_ATTEMPTS - 1:
            trade_data['_attempts'] = attempts + 1
            logger.warning(f"⏳ {symbol}: لم يظهر PnL بعد - إعادة المحاولة")
            return False

        verified = real is not None
        net = real['net'] if verified else 0.0

        if verified:
            logger.info(
                f"💰 {symbol} صافي: {net:+.4f} "
                f"(محقق {real['realized']:+.4f} | عمولة {real['commission']:+.4f} | تمويل {real['funding']:+.4f})"
            )
        else:
            logger.warning(f"⚠️ {symbol}: تعذر جلب PnL الحقيقي - تسجيل غير موثق (لا يدخل في التعلم)")

        # ---- الذاكرة ----
        if MEMORY_AVAILABLE:
            try:
                closed_iso = None
                if verified and real.get('closed_at_ms'):
                    closed_iso = datetime.fromtimestamp(real['closed_at_ms'] / 1000).isoformat()

                memory.record_trade(
                    symbol=symbol,
                    direction=direction,
                    entry_price=entry_price,
                    exit_price=0,
                    quantity=quantity,
                    pnl=net,
                    confidence=safe_float(trade_data.get('confidence', 0)),
                    timeframe_alignment=safe_float(trade_data.get('timeframe_alignment', 0)),
                    volume_ratio=safe_float(trade_data.get('volume_ratio', 0)),
                    groq_recommendation=trade_data.get('groq_recommendation', ''),
                    groq_confidence=safe_float(trade_data.get('groq_confidence', 0)),
                    score_details=trade_data.get('sniper_score', {}),
                    exit_reason="auto_detected",
                    entry_time_iso=entry_time_iso,
                    net_pnl=net if verified else None,
                    closed_at_iso=closed_iso,
                    breakdown=real if verified else None,
                    extra={
                        'mfe_pct': trade_data.get('mfe_pct', 0),
                        'mae_pct': trade_data.get('mae_pct', 0),
                    }
                )
                try:
                    memory.sync_profit_history()
                except Exception:
                    pass
            except Exception as e:
                logger.error(f"خطأ في التسجيل: {e}")

        # ---- الحماية (فقط للنتائج الموثقة) ----
        paused_now = False
        if verified:
            try:
                paused_now = core.record_trade_result(net)
            except Exception as e:
                logger.error(f"خطأ record_trade_result: {e}")

        # ---- التبريد بعد النتيجة الحقيقية ----
        try:
            strat.add_symbol_cooldown(symbol)
        except Exception as e:
            logger.debug(f"cooldown: {e}")

        # ---- التعلم الفوري ----
        if ADAPTIVE_AVAILABLE and verified:
            try:
                adaptive_rules.update_rules()
            except Exception as e:
                logger.debug(f"adaptive update: {e}")

        # ---- إشعارات ----
        try:
            opened_at = safe_float(trade_data.get('opened_at', time.time()), time.time())
            duration_minutes = safe_int((time.time() - opened_at) / 60, 0)
        except Exception:
            duration_minutes = 0

        send_close_notification(
            symbol=symbol,
            direction=direction,
            position_side=position_side,
            entry_price=entry_price,
            quantity=quantity,
            pnl=net,
            duration_minutes=duration_minutes
        )

        if paused_now:
            paused, remaining = core.is_trading_paused()
            if paused:
                _notify(
                    f"⏸️ <b>إيقاف تلقائي للتداول</b>\n"
                    f"السبب: {core.get_pause_reason()}\n"
                    f"المدة المتبقية: {remaining} دقيقة\n"
                    f"الحجم بعد الاستئناف: {core.get_risk_multiplier()*100:.0f}% من الحجم العادي"
                )

        logger.info(f"✅ تم معالجة إغلاق: {symbol} صافي: {net:+.4f}")
        return True

    except Exception as e:
        logger.error(f"خطأ في record_closed_trade: {e}")
        traceback.print_exc()
        return False


def send_close_notification(symbol, direction, position_side, entry_price, quantity, pnl, duration_minutes=0):
    try:
        from telegram import Bot
        bot = Bot(token=TELEGRAM_TOKEN)

        symbol = str(symbol) if symbol else "UNKNOWN"
        direction = str(direction) if direction else "UNKNOWN"
        position_side = str(position_side) if position_side else "BOTH"
        entry_price = safe_float(entry_price, 0.0)
        quantity = safe_float(quantity, 0.0)
        pnl = safe_float(pnl, 0.0)
        duration_minutes = safe_int(duration_minutes, 0)

        if pnl > 0.01:
            emoji = "🟢"
            title = "✅ <b>تم إغلاق الصفقة بربح</b>"
        elif pnl < -0.01:
            emoji = "🔴"
            title = "❌ <b>تم إغلاق الصفقة بخسارة</b>"
        else:
            emoji = "⚪"
            title = "⚪ <b>تم إغلاق الصفقة (تعادل)</b>"

        position_value = entry_price * quantity
        pnl_percent = (pnl / position_value * 100) if position_value > 0 else 0.0

        if duration_minutes > 60:
            hours = duration_minutes // 60
            mins = duration_minutes % 60
            duration_text = f"{hours} س {mins} د"
        elif duration_minutes > 0:
            duration_text = f"{duration_minutes} دقيقة"
        else:
            duration_text = "أقل من دقيقة"

        msg = (
            f"{title}\n\n"
            f"💰 <b>العملة:</b> {symbol}\n"
            f"📈 <b>الاتجاه:</b> {direction} ({position_side})\n"
            f"💵 <b>الدخول:</b> <code>{entry_price}</code>\n"
            f"⚖️ <b>الكمية:</b> <code>{quantity}</code>\n\n"
            f"{emoji} <b>PnL:</b> <code>{pnl:+.4f}</code> USDT\n"
            f"📊 <b>النسبة:</b> <code>{pnl_percent:+.2f}%</code>\n"
            f"⏱️ <b>المدة:</b> {duration_text}\n\n"
            f"⏰ {datetime.now().strftime('%H:%M:%S')}"
        )

        async def send_async():
            await bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=msg, parse_mode="HTML")

        threading.Thread(target=run_async_safe, args=(send_async(),), daemon=True).start()

        logger.info(f"🔔 تم إرسال إشعار الإغلاق: {symbol} {pnl:+.4f}")

    except Exception as e:
        logger.error(f"❌ خطأ في إشعار الإغلاق: {e}")


# ==================== خيط المسح التلقائي ====================

def auto_sniper_scanner():
    try:
        logger.info("🎯 [THREAD] بدء مسح القناص...")

        global _last_auto_scan, _daily_limit_notified_date

        while _auto_scan_enabled:
            try:
                _beat('scanner')
                current_time = time.time()

                if check_trading_pause():
                    time.sleep(60)
                    continue

                if current_time - _last_auto_scan >= AUTO_SCAN_INTERVAL:
                    # 🔥 حد الخسارة اليومية (من Binance) قبل أي مسح
                    try:
                        dd_ok, dd_reason = core.check_daily_drawdown()
                        if not dd_ok:
                            today = datetime.now().strftime("%Y-%m-%d")
                            if _daily_limit_notified_date != today:
                                _daily_limit_notified_date = today
                                _notify(f"🛑 <b>توقف التداول اليوم</b>\n{dd_reason}\nسيستأنف البوت تلقائياً بعد منتصف الليل.")
                            time.sleep(120)
                            continue
                    except Exception as e:
                        logger.warning(f"⚠️ فحص الخسارة اليومية: {e}")

                    # 🔥 لا نمسح إذا تعذر قراءة الصفقات المفتوحة (تفادي تجاوز الحد الأقصى)
                    if core.get_open_positions_strict() is None:
                        logger.warning("⚠️ تعذر قراءة الصفقات المفتوحة - تأجيل المسح")
                        time.sleep(30)
                        continue

                    _last_auto_scan = current_time

                    bot_positions = get_bot_owned_positions()
                    manual_positions = get_manual_positions()

                    logger.info(f"📊 صفقات البوت: {len(bot_positions)}/{MAX_OPEN_POSITIONS} | يدوية: {len(manual_positions)}")

                    if len(bot_positions) >= MAX_OPEN_POSITIONS:
                        logger.info("⏸️ حد أقصى - انتظار")
                        time.sleep(30)
                        continue

                    if MARKET_REGIME_AVAILABLE:
                        try:
                            regime = MarketRegime.get_regime()
                            logger.info(f"📊 السوق: {regime.get('regime_ar')} - {regime.get('recommendation')}")
                        except:
                            pass

                    logger.info("🎯 مسح...")

                    signals = strat.scan_sniper_signals()

                    if signals:
                        logger.info(f"🎯 {len(signals)} إشارة")

                        for signal in signals:
                            bot_positions = get_bot_owned_positions()
                            if len(bot_positions) >= MAX_OPEN_POSITIONS:
                                break

                            if execute_sniper_trade(signal):
                                logger.info(f"✅ {signal['symbol']}")
                                time.sleep(2)
                    else:
                        logger.info("🔍 لا توجد إشارات")

                    logger.info(f"⏰ الدورة التالية: {AUTO_SCAN_INTERVAL // 60} دقيقة")

                    gc.collect()

                time.sleep(30)

            except Exception as e:
                logger.error(f"خطأ في المسح: {e}")
                time.sleep(60)

        logger.info("🛑 [THREAD] توقف مسح القناص")

    except Exception as e:
        logger.error(f"❌ [THREAD] فشل مسح القناص: {e}")
        traceback.print_exc()


# ==================== التنفيذ ====================

def execute_sniper_trade(signal):
    try:
        symbol = signal['symbol']
        direction = signal['direction']

        logger.info(f"🚀 فحص {symbol} {direction}")

        paused, remaining = core.is_trading_paused()
        if paused:
            logger.warning(f"⏸️ {symbol}: التداول موقوف ({remaining} د)")
            return False

        total_score = safe_float(signal.get('total_score', 0))
        required_score = safe_float(signal.get('required_score', MIN_SCORE_REQUIRED))
        if total_score < required_score:
            logger.warning(f"🛑 {symbol}: نقاط {total_score} < {required_score}")
            return False

        analysis = signal.get('analysis', {})
        volume = analysis.get('volume_analysis', {})
        vol_ratio = safe_float(volume.get('volume_5m_ratio', 0))

        if vol_ratio < MIN_VOLUME_FACTOR:
            logger.warning(f"🛑 {symbol}: حجم {vol_ratio}x < {MIN_VOLUME_FACTOR}")
            return False

        groq_rec = signal.get('groq_recommendation', '')
        groq_conf = safe_float(signal.get('groq_confidence', 0))

        if groq_rec == 'رفض' and groq_conf >= 75:
            logger.warning(f"🛑 {symbol}: Groq رفض ({groq_conf}%)")
            return False

        confidence = safe_float(signal.get('confidence', 0))
        if confidence < MIN_CONFIDENCE_AUTO:
            logger.warning(f"🛑 {symbol}: ثقة {confidence}% < {MIN_CONFIDENCE_AUTO}%")
            return False

        bot_positions = get_bot_owned_positions()

        if len(bot_positions) >= MAX_OPEN_POSITIONS:
            logger.warning(f"⏸️ حد أقصى: {len(bot_positions)}/{MAX_OPEN_POSITIONS}")
            return False

        if any(p['symbol'] == symbol for p in bot_positions):
            logger.warning(f"⚠️ صفقة موجودة على {symbol}")
            return False

        # 🔥 v5.8: حد الصفقات المفتوحة في نفس الاتجاه (صفقات الكريبتو المتزامنة تتحرك معاً)
        # البيانات: 0 مفتوحة بنفس الاتجاه → نجاح 52% | 2 → 33% | 3 → 25%
        try:
            max_same = int(globals().get('MAX_SAME_DIRECTION_POSITIONS', 0) or 0)
        except Exception:
            max_same = 0
        if max_same > 0:
            same_dir = sum(
                1 for p in bot_positions
                if (safe_float(p.get('positionAmt', 0)) > 0) == (direction == "BUY")
            )
            if same_dir >= max_same:
                logger.warning(f"🛑 {symbol}: {same_dir} صفقة {direction} مفتوحة (الحد {max_same})")
                return False

        if ENABLE_OPPOSITE_DIRECTION_FILTER:
            for pos in bot_positions:
                pos_amt = safe_float(pos.get('positionAmt', 0))
                pos_direction = "BUY" if pos_amt > 0 else "SELL"
                if pos_direction != direction:
                    logger.warning(f"🛑 {symbol}: اتجاه معاكس")
                    return False

        drawdown_ok, drawdown_reason = core.check_daily_drawdown()
        if not drawdown_ok:
            logger.error(f"🛑 {drawdown_reason}")
            return False

        if ENABLE_CORRELATION_FILTER:
            corr_ok, corr_reason = core.check_correlation_exposure(symbol, direction, bot_positions)
            if not corr_ok:
                logger.warning(f"🛑 {symbol}: {corr_reason}")
                return False

        liquidity_ok, liquidity_reason = core.check_spread_and_liquidity(symbol, TRADE_USDT)
        if not liquidity_ok:
            logger.warning(f"🛑 {symbol}: {liquidity_reason}")
            return False

        # 🔥 تقليل الحجم بعد خسائر متتالية
        risk_mult = core.get_risk_multiplier()
        trade_usdt = round(TRADE_USDT * risk_mult, 2)
        if risk_mult < 1.0:
            logger.warning(f"⚠️ {symbol}: تقليل الحجم إلى {trade_usdt}$ ({risk_mult*100:.0f}%) بسبب خسائر متتالية")

        logger.info(f"✅ {symbol}: اجتاز كل الفحوص - جاري التنفيذ ({trade_usdt}$)")

        if ENABLE_MULTIPLE_TP:
            result = core.place_market_order_with_multiple_tp(symbol, direction, trade_usdt, LEVERAGE)
        else:
            result = core.place_market_order_with_tp_sl(symbol, direction, trade_usdt, LEVERAGE)

        if result:
            if result.get('closed_due_to_failure'):
                logger.error(f"❌ {symbol} أُغلقت بسبب فشل TP/SL")
                return False

            tgbot.add_open_position(result)

            sl_price = result.get('tp_results', {}).get('sl_price')
            core.setup_trailing_sl(
                symbol=symbol,
                position_side=result['positionSide'],
                entry_price=result['entry_price'],
                quantity=result['quantity'],
                sl_price=sl_price
            )

            if MEMORY_AVAILABLE and ENABLE_TRADE_MEMORY:
                track_key = f"{symbol}_{result['positionSide']}"
                _open_trades_tracking[track_key] = {
                    'symbol': symbol,
                    'direction': direction,
                    'entry_price': result['entry_price'],
                    'quantity': result['quantity'],
                    'positionSide': result['positionSide'],
                    'confidence': safe_float(signal.get('confidence', 0)),
                    'timeframe_alignment': safe_float(signal.get('timeframe_alignment', 0)),
                    'volume_ratio': vol_ratio,
                    'groq_recommendation': groq_rec,
                    'groq_confidence': groq_conf,
                    'sniper_score': signal.get('score_details', {}),
                    'opened_at': time.time(),
                    'entry_time_iso': datetime.now().isoformat()
                }
                _save_tracking()

            send_trade_notification(signal, result)
            logger.info(f"✅ {symbol}: تم فتح الصفقة بنجاح")
            return True

        return False

    except Exception as e:
        logger.error(f"خطأ في التنفيذ: {e}")
        traceback.print_exc()
        return False


def send_trade_notification(signal, result):
    try:
        from telegram import Bot
        bot = Bot(token=TELEGRAM_TOKEN)

        emoji = "🟢" if signal['direction'] == 'BUY' else "🔴"
        score = signal.get('score_details', {})

        entry_price = safe_float(result.get('entry_price', 0))
        position_side = result.get('positionSide', 'LONG')
        quantity = safe_float(result.get('quantity', 0))

        tp_results = result.get('tp_results', {})
        tp_orders = tp_results.get('tp_orders', [])
        sl_price = tp_results.get('sl_price')

        msg = (
            f"🎯 <b>تم التنفيذ بنجاح!</b>\n\n"
            f"💰 <b>العملة:</b> {signal['symbol']}\n"
            f"📈 <b>الاتجاه:</b> {emoji} {signal['direction']}\n"
            f"💵 <b>الدخول:</b> <code>{entry_price}</code>\n"
            f"⚖️ <b>الكمية:</b> <code>{quantity}</code>\n"
            f"📊 <b>النقاط:</b> {safe_int(score.get('total', 0))}/100\n\n"
            f"🎯 <b>الأهداف:</b>\n"
        )

        for tp in [tp for tp in tp_orders if tp.get('success')]:
            msg += f"   ✅ TP{tp['level']}: <code>{safe_float(tp.get('tp_price', 0))}</code>\n"

        if sl_price:
            msg += f"   🛡️ SL: <code>{safe_float(sl_price)}</code>\n"

        msg += f"\n⏰ {datetime.now().strftime('%H:%M:%S')}"

        async def send_async():
            await bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=msg, parse_mode="HTML")

        threading.Thread(target=run_async_safe, args=(send_async(),), daemon=True).start()

    except Exception as e:
        logger.error(f"❌ خطأ في إشعار: {e}")


# ==================== الحالة ====================

def get_system_status():
    all_positions = core.get_open_positions()
    bot_positions = get_bot_owned_positions()
    manual_positions = get_manual_positions()
    balance_info = get_full_balance_info()

    daily = core.get_accurate_daily_pnl()
    weekly = core.get_accurate_weekly_pnl()
    monthly = core.get_accurate_monthly_pnl()

    is_paused, pause_remaining = core.is_trading_paused()

    scheduler_status = {}
    if SCHEDULER_AVAILABLE:
        try:
            scheduler_status = smart_scheduler.get_scheduler_status()
        except:
            pass

    return {
        'auto_scan': _auto_scan_enabled,
        'auto_trading': _auto_trading_enabled,
        'open_positions': len(bot_positions),
        'max_positions': MAX_OPEN_POSITIONS,
        'manual_positions': len(manual_positions),
        'total_real_positions': len(all_positions),
        'balance_available': safe_float(balance_info.get('available', 0)),
        'balance_wallet': safe_float(balance_info.get('wallet', 0)),
        'balance_pnl': safe_float(balance_info.get('unrealized_pnl', 0)),
        'daily_pnl': safe_float(daily.get('daily_pnl', 0)),
        'weekly_pnl': safe_float(weekly.get('weekly_pnl', 0)),
        'monthly_pnl': safe_float(monthly.get('monthly_pnl', 0)),
        'cooldown_symbols': len(strat.get_cooldown_status().get('active_symbols', {})),
        'is_paused': is_paused,
        'pause_remaining': pause_remaining,
        'consecutive_losses': core.get_consecutive_losses(),
        'scheduler_status': scheduler_status,
        'auto_learning_enabled': ENABLE_AUTO_LEARNING if 'ENABLE_AUTO_LEARNING' in dir() else False,
    }


def toggle_auto_trading():
    global _auto_trading_enabled
    _auto_trading_enabled = not _auto_trading_enabled
    status = "مفعل" if _auto_trading_enabled else "معطل"
    return f"✅ <b>التنفيذ التلقائي: {status}</b>"


def toggle_auto_scan():
    global _auto_scan_enabled
    _auto_scan_enabled = not _auto_scan_enabled
    status = "مفعل" if _auto_scan_enabled else "معطل"
    return f"✅ <b>المسح التلقائي: {status}</b>"


# ==================== التشغيل ====================

_THREAD_TARGETS = {}
_thread_objects = {}


def _start_thread(key, target, name):
    """تشغيل خيط وتسجيله ليعيد المراقب تشغيله إذا توقف"""
    try:
        _THREAD_TARGETS[key] = (target, name)
        t = threading.Thread(target=target, daemon=True, name=name)
        t.start()
        _thread_objects[key] = t
        _beat(key)
        logger.info(f"✅ [START] {name}")
        return True
    except Exception as e:
        logger.error(f"❌ [START] فشل {name}: {e}")
        return False


def supervisor_loop():
    """
    🔥 المراقب: كل دقيقة
      1) إذا مات خيط (scanner/monitor) يُعاد تشغيله
      2) إذا تجمّد خيط أكثر من STALL_RESTART_MINUTES تُعاد العملية كاملة
         (Railway يعيد تشغيلها؛ أوامر SL/TP على Binance تبقى فعّالة والحالة محفوظة)
    """
    stall_minutes = float(globals().get('STALL_RESTART_MINUTES', 30))
    logger.info(f"🛡️ [SUPERVISOR] بدء المراقبة (مهلة التجمّد {stall_minutes:.0f} د)")
    time.sleep(90)

    while True:
        try:
            for key, (target, name) in list(_THREAD_TARGETS.items()):
                t = _thread_objects.get(key)
                if t is None or not t.is_alive():
                    logger.error(f"🚨 [SUPERVISOR] الخيط {name} متوقف - إعادة تشغيل")
                    _notify(f"⚠️ الخيط <b>{name}</b> توقف وتمت إعادة تشغيله تلقائياً")
                    nt = threading.Thread(target=target, daemon=True, name=name)
                    nt.start()
                    _thread_objects[key] = nt
                    _beat(key)

            now = time.time()
            for key, last in list(_heartbeats.items()):
                if now - last > stall_minutes * 60:
                    logger.error(f"🚨 [SUPERVISOR] {key} متجمّد منذ {(now - last) / 60:.0f} دقيقة - إعادة تشغيل العملية")
                    _notify(f"🚨 الخيط <b>{key}</b> تجمّد {(now - last) / 60:.0f} دقيقة - إعادة تشغيل البوت تلقائياً")
                    time.sleep(3)
                    os._exit(1)

        except Exception as e:
            logger.error(f"خطأ في المراقب: {e}")

        time.sleep(60)


def start_scanner_threads():
    logger.info("=" * 60)
    logger.info("🔧 [START] بدء تشغيل الخيوط v5.6...")
    logger.info("=" * 60)

    # 1. Health Check
    try:
        import health_server
        if health_server.run_in_background():
            logger.info("✅ [START] Health Check Server")
    except Exception as e:
        logger.error(f"❌ [START] خطأ Health Check: {e}")

    # 2. Firebase
    if FIREBASE_AVAILABLE:
        try:
            if firebase_backup.initialize_firebase():
                logger.info("✅ [START] Firebase متصل")

                if MEMORY_AVAILABLE:
                    try:
                        if memory.sync_from_firebase():
                            logger.info("✅ [START] مزامنة من Firebase")
                    except Exception as e:
                        logger.warning(f"⚠️ [START] فشل المزامنة: {e}")

                if ENABLE_FIREBASE_BACKUP:
                    if firebase_backup.start_auto_backup():
                        logger.info("✅ [START] Firebase Backup")
            else:
                logger.warning("⚠️ [START] Firebase غير متاح")
        except Exception as e:
            logger.error(f"❌ [START] خطأ Firebase: {e}")

    # 2.5 🔥 استرجاع الحالة (المخاطر، القواعد، تتبع الصفقات) وترحيل الذاكرة
    try:
        core.load_risk_state(from_firebase=True)
    except Exception as e:
        logger.warning(f"⚠️ [START] حالة المخاطر: {e}")

    if ADAPTIVE_AVAILABLE:
        try:
            adaptive_rules.restore_from_firebase()
        except Exception as e:
            logger.warning(f"⚠️ [START] قواعد التعلم: {e}")

    try:
        _load_tracking()
    except Exception as e:
        logger.warning(f"⚠️ [START] التتبع: {e}")

    if MEMORY_AVAILABLE:
        try:
            memory.migrate_legacy_trades()
        except Exception as e:
            logger.warning(f"⚠️ [START] ترحيل الذاكرة: {e}")

        def _reconcile_and_learn():
            try:
                time.sleep(20)
                fixed = memory.reconcile_legacy_trades()
                if fixed:
                    logger.info(f"✅ [START] تم تصحيح {fixed} صفقة قديمة من سجل Binance")
                if ADAPTIVE_AVAILABLE:
                    adaptive_rules.update_rules()
            except Exception as e:
                logger.warning(f"⚠️ [START] تصحيح الصفقات القديمة: {e}")

        threading.Thread(target=_reconcile_and_learn, daemon=True, name="Reconcile").start()

    # 3. Scanner
    _start_thread('scanner', auto_sniper_scanner, "SniperScanner")

    # 4. Monitor
    _start_thread('monitor', monitor_positions_loop, "Monitor")

    # 5. Smart Scheduler
    if SCHEDULER_AVAILABLE and ENABLE_AUTO_LEARNING:
        try:
            if smart_scheduler.start_scheduler():
                logger.info("✅ [START] Smart Scheduler")
        except Exception as e:
            logger.error(f"❌ [START] فشل scheduler: {e}")

    # 6. 🔥 المراقب (Supervisor)
    try:
        threading.Thread(target=supervisor_loop, daemon=True, name="Supervisor").start()
        logger.info("✅ [START] Supervisor (إعادة تشغيل الخيوط المتوقفة)")
    except Exception as e:
        logger.error(f"❌ [START] فشل supervisor: {e}")

    time.sleep(2)
    logger.info(f"✅ [START] عدد الخيوط: {threading.active_count()}")
    logger.info("=" * 60)


def main():
    try:
        logger.info("=" * 60)
        logger.info("🚀 [MAIN] بدء main_enhanced v5.7...")
        logger.info("=" * 60)

        send_startup()
        time.sleep(3)

        logger.info("🧹 [MAIN] مزامنة ملف الصفقات...")
        try:
            tgbot.cleanup_state_file()
        except Exception as e:
            logger.warning(f"⚠️ [MAIN] فشل التنظيف: {e}")

        # 🔥 تنظيف الأوامر اليتيمة عند البدء
        try:
            logger.info("🧹 [MAIN] تنظيف الأوامر اليتيمة...")
            cancelled = core.cleanup_orphan_algo_orders()
            if cancelled > 0:
                logger.info(f"✅ [MAIN] تم حذف {cancelled} أمر يتيم")
            else:
                logger.info("✅ [MAIN] لا توجد أوامر يتيمة")
        except Exception as e:
            logger.warning(f"⚠️ [MAIN] فشل تنظيف الأوامر: {e}")

        if MEMORY_AVAILABLE:
            try:
                memory.sync_profit_history()
                logger.info("✅ [MAIN] تم مزامنة profit_history.json")
            except Exception as e:
                logger.warning(f"⚠️ [MAIN] فشل مزامنة profit_history: {e}")

            try:
                mem_stats = memory.get_memory_stats()
                logger.info(f"📊 [MAIN] عدد الصفقات: {mem_stats.get('total_trades', 0)}")
                logger.info(f"📊 [MAIN] نسبة النجاح: {mem_stats.get('win_rate', 0):.1f}%")
            except:
                pass

        logger.info("=" * 60)
        logger.info("🎯 [MAIN] نظام القناص v5.6 مفعل")
        logger.info("=" * 60)
        logger.info(f"⏰ [MAIN] المسح كل {AUTO_SCAN_INTERVAL // 60} دقيقة")
        logger.info(f"🎯 [MAIN] MIN_SCORE: {MIN_SCORE_REQUIRED}")
        logger.info(f"📈 [MAIN] MAX_POSITIONS: {MAX_OPEN_POSITIONS}")
        logger.info(f"💰 [MAIN] TRADE_USDT: {TRADE_USDT}")
        logger.info(f"⚡ [MAIN] LEVERAGE: {LEVERAGE}x")
        logger.info(f"🧹 [MAIN] تنظيف الأوامر: ✅ (كل {ORPHAN_CLEANUP_INTERVAL // 60} دقيقة)")
        logger.info(f"🔔 [MAIN] إشعار إغلاق: ✅")
        logger.info(f"🧠 [MAIN] التعلم التلقائي: {'✅' if ENABLE_AUTO_LEARNING else '❌'}")
        logger.info(f"📊 [MAIN] التقارير اليومية: {'✅' if ENABLE_DAILY_REPORT else '❌'}")
        logger.info(f"🔥 [MAIN] Firebase Backup: {'✅' if ENABLE_FIREBASE_BACKUP else '❌'}")
        logger.info("=" * 60)

        logger.info("🚀 [MAIN] بدء البوت...")
        tgbot.run_bot()

        # run_polling لا يرجع إلا عند الإيقاف أو عطل - نخرج بكود خطأ ليعيد Railway التشغيل
        logger.error("❌ [MAIN] توقف Telegram polling - إعادة تشغيل العملية")
        time.sleep(3)
        os._exit(1)

    except Exception as e:
        logger.error(f"❌ [MAIN] خطأ: {e}")
        traceback.print_exc()
        time.sleep(5)
        os._exit(1)


if __name__ == "__main__":
    main()