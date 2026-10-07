# ==================================================
# 📁 ملف: bot_enhanced.py - الإصدار v5.6
# 🔧 التعديلات v5.6:
#    - 🔥 إصلاح عرض "التعلم التلقائي" في حالة النظام
#    - 🔥 قراءة مباشرة من config
# 🔧 التعديلات v5.5:
#    - عرض Firebase Backup
#    - Health Check
# 📅 التاريخ: 2026-09-26
# ==================================================

import logging, os, json, threading, time, asyncio
from datetime import datetime
from telegram import ReplyKeyboardMarkup, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, CallbackContext
from telegram.ext import filters
import concurrent.futures

logger = logging.getLogger("bot_enhanced")
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")

# 🔥 v5.8: حفظ السجل في ملف ليمكن تحميله من Telegram (زر 📥 تحميل السجل)
try:
    import log_capture
    log_capture.setup()
except Exception as _e:
    log_capture = None
    print(f"⚠️ log_capture غير متاح: {_e}")

# إخفاء التوكن من اللوجات (أمان)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("telegram").setLevel(logging.WARNING)
logging.getLogger("telegram.ext").setLevel(logging.WARNING)
logging.getLogger("telegram.request").setLevel(logging.WARNING)
logging.getLogger("urllib3").setLevel(logging.WARNING)

from config import *
import core_functions as core

try:
    import bot_strategies_enhanced as strat
    logger.info("✅ تم تحميل النظام المحسن")
except ImportError as e:
    logger.warning(f"❌ لم يتم العثور على النظام المحسن: {e}")
    try:
        import bot_strategies as strat
        logger.info("✅ تم تحميل النظام الأساسي")
    except ImportError as e:
        logger.error(f"❌ فشل تحميل أي نظام: {e}")
        raise

try:
    from groq_integration import enhance_signal_with_groq, is_groq_available
    GROQ_AVAILABLE = is_groq_available()
    if GROQ_AVAILABLE:
        logger.info("✅ تم تحميل وحدة Groq")
    else:
        logger.warning("⚠️ وحدة Groq غير متاحة")
except ImportError as e:
    logger.warning(f"❌ Groq غير متاح: {e}")
    GROQ_AVAILABLE = False
    enhance_signal_with_groq = lambda x: x

STATE_FILE = "open_positions.json"
_lock = threading.Lock()
_bot_running = True


# ==================== دوال async آمنة ====================

def run_async_safe(coro):
    try:
        try:
            loop = asyncio.get_event_loop()
            if loop.is_closed():
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
            elif loop.is_running():
                future = asyncio.run_coroutine_threadsafe(coro, loop)
                return future.result(timeout=30)
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

        try:
            return loop.run_until_complete(coro)
        finally:
            pass
    except Exception as e:
        if "Event loop is closed" not in str(e):
            logger.error(f"❌ خطأ async آمن: {e}")
        return None


def run_async_new_loop(coro):
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


# ==================== دوال مساعدة ====================

def get_accurate_balance():
    try:
        client_obj = core.get_client()
        if not client_obj:
            return 0.0
        account = client_obj.futures_account()
        for asset in account.get('assets', []):
            if asset.get('asset') == 'USDT':
                return float(asset.get('availableBalance', 0))
        return 0.0
    except Exception as e:
        logger.error(f"خطأ في جلب الرصيد: {e}")
        return 0.0


def get_full_balance_info():
    try:
        client_obj = core.get_client()
        if not client_obj:
            return {}
        account = client_obj.futures_account()
        for asset in account.get('assets', []):
            if asset.get('asset') == 'USDT':
                return {
                    'available': float(asset.get('availableBalance', 0)),
                    'wallet': float(asset.get('walletBalance', 0)),
                    'unrealized_pnl': float(asset.get('unrealizedProfit', 0)),
                    'margin': float(asset.get('totalPositionInitialMargin', 0)),
                    'maint_margin': float(asset.get('totalMaintMargin', 0)),
                    'cross_wallet': float(asset.get('crossWalletBalance', 0))
                }
        return {}
    except Exception as e:
        logger.error(f"خطأ في جلب معلومات الرصيد: {e}")
        return {}


def analyze_with_timeout(symbol, timeout_seconds=30):
    try:
        with concurrent.futures.ThreadPoolExecutor() as executor:
            future = executor.submit(strat.generate_smart_analysis, symbol)
            try:
                return future.result(timeout=timeout_seconds)
            except concurrent.futures.TimeoutError:
                logger.error(f"⏰ انتهت مهلة التحليل لـ {symbol}")
                return None
    except Exception as e:
        logger.error(f"❌ خطأ في التحليل: {e}")
        return None


def analyze_signal_with_timeout(symbol, timeout_seconds=25):
    try:
        with concurrent.futures.ThreadPoolExecutor() as executor:
            future = executor.submit(strat.generate_premium_signal_light, symbol)
            try:
                return future.result(timeout=timeout_seconds)
            except concurrent.futures.TimeoutError:
                logger.error(f"⏰ انتهت المهلة لـ {symbol}")
                return None
    except Exception as e:
        logger.error(f"❌ خطأ: {e}")
        return None


# لوحة المفاتيح الرئيسية
main_kb = ReplyKeyboardMarkup([
    ["📥 تحميل السجل", "📦 تصدير البيانات"],
    ["💰 الرصيد", "📊 الصفقات المفتوحة"],
    ["📈 الأرباح اليومية", "🔍 البحث عن إشارات"],
    ["🤖 تشغيل/إوقف التلقائي", "🔄 تحديث الأوامر"],
    ["📊 حالة النظام", "🔒 قفل الصفقات الرابحة"],
    ["📋 تقرير الأداء", "🔄 تشغيل/إيقاف البوت"],
    ["📊 الأرباح الأسبوعية", "📈 الأرباح الشهرية"],
    ["⚡ إغلاق جميع الصفقات", "🛑 إغلاق الصفقات الخاسرة"],
    ["🔎 فحص الأوامر المشروطة", "🧠 التعلم التلقائي"],
    ["📊 تقرير سريع", "👻 تقرير الظل"],
    ["🧠 تقرير التشخيص"]
], resize_keyboard=True)


def ensure_state():
    if not os.path.exists(STATE_FILE):
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump([], f)


def load_state():
    ensure_state()
    with open(STATE_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_state(data):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def cleanup_state_file():
    try:
        real_positions = core.get_open_positions()
        real_keys = {f"{p['symbol']}_{p['positionSide']}" for p in real_positions}
        with _lock:
            st = load_state()
            cleaned = [s for s in st if f"{s['symbol']}_{s['positionSide']}" in real_keys]
            if len(cleaned) != len(st):
                logger.info(f"🧹 تنظيف open_positions: {len(st)} → {len(cleaned)}")
                save_state(cleaned)
            else:
                logger.info(f"✅ open_positions متزامن: {len(cleaned)} صفقة")
            return len(cleaned)
    except Exception as e:
        logger.error(f"خطأ في التنظيف: {e}")
        return 0


def add_open_position(info):
    with _lock:
        st = load_state()
        existing = [s for s in st if s.get("symbol") == info.get("symbol") and s.get("positionSide") == info.get("positionSide")]
        if not existing:
            st.append(info)
            save_state(st)


def remove_open_position(symbol, positionSide=None):
    with _lock:
        st = load_state()
        if positionSide:
            st = [s for s in st if not (s.get("symbol") == symbol and s.get("positionSide") == positionSide)]
        else:
            st = [s for s in st if s.get("symbol") != symbol]
        save_state(st)


def format_number_english(number, decimals=4):
    try:
        if number is None:
            return "0"
        return f"{number:.{decimals}f}".replace(',', '')
    except:
        return str(number)


# ==================== إرسال الرسائل ====================

async def send_message_safe(update: Update, text: str, parse_mode="HTML", reply_markup=None):
    try:
        if not text or len(text.strip()) == 0:
            logger.warning("⚠️ نص فارغ")
            return

        if len(text) > 4096:
            logger.warning(f"⚠️ تقصير النص من {len(text)}")
            text = text[:4090] + "..."

        if update.callback_query:
            try:
                await update.callback_query.message.reply_text(
                    text=text, parse_mode=parse_mode, reply_markup=reply_markup,
                    disable_web_page_preview=True
                )
                logger.info(f"✅ إرسال callback: {text[:100]}...")
            except Exception as e:
                logger.error(f"❌ خطأ callback: {e}")
                try:
                    await update.callback_query.edit_message_text(
                        text=text, parse_mode=parse_mode, reply_markup=reply_markup
                    )
                except Exception as e2:
                    logger.error(f"❌ فشل تحرير: {e2}")
        elif update.message:
            try:
                await update.message.reply_text(
                    text=text, parse_mode=parse_mode, reply_markup=reply_markup,
                    disable_web_page_preview=True
                )
                logger.info(f"✅ إرسال عادي: {text[:100]}...")
            except Exception as e:
                logger.error(f"❌ خطأ إرسال: {e}")
        else:
            await send_direct_message(text, parse_mode, reply_markup)
    except Exception as e:
        logger.error(f"❌ خطأ عام: {e}")
        try:
            await send_direct_message(text, parse_mode, reply_markup)
        except Exception as final_error:
            logger.error(f"❌ فشل نهائي: {final_error}")


async def send_direct_message(text: str, parse_mode="HTML", reply_markup=None):
    try:
        from telegram import Bot
        bot = Bot(token=TELEGRAM_TOKEN)
        await bot.send_message(
            chat_id=TELEGRAM_CHAT_ID, text=text, parse_mode=parse_mode,
            reply_markup=reply_markup, disable_web_page_preview=True
        )
        logger.info(f"✅ إرسال مباشر: {text[:100]}...")
    except Exception as e:
        logger.error(f"❌ فشل الإرسال المباشر: {e}")


# ==================== التنفيذ اليدوي ====================

def execute_trade_manual(update: Update, symbol: str, side: str):
    try:
        if not _bot_running:
            run_async_safe(send_message_safe(update, "❌ البوت متوقف حالياً.", reply_markup=main_kb))
            return

        current_positions = core.get_open_positions()
        if len(current_positions) >= MAX_OPEN_POSITIONS:
            run_async_safe(send_message_safe(update, f"❌ وصلت للحد الأقصى ({MAX_OPEN_POSITIONS})", reply_markup=main_kb))
            return

        for pos in current_positions:
            if pos["symbol"] == symbol:
                run_async_safe(send_message_safe(update, f"⚠️ يوجد صفقة مفتوحة لـ {symbol}", reply_markup=main_kb))
                return

        if ENABLE_OPPOSITE_DIRECTION_FILTER:
            for pos in current_positions:
                pos_amt = float(pos.get('positionAmt', 0))
                pos_direction = "BUY" if pos_amt > 0 else "SELL"
                if pos_direction != side.upper():
                    run_async_safe(send_message_safe(
                        update,
                        f"🛑 <b>ممنوع!</b>\n\nيوجد صفقة <b>{pos_direction}</b> على <b>{pos['symbol']}</b>",
                        reply_markup=main_kb
                    ))
                    return

        run_async_safe(send_message_safe(update, f"🔄 جاري تنفيذ {side} {symbol}...", reply_markup=main_kb))

        if ENABLE_MULTIPLE_TP:
            result = core.place_market_order_with_multiple_tp(symbol, side, TRADE_USDT, LEVERAGE)
        else:
            result = core.place_market_order_with_tp_sl(symbol, side, TRADE_USDT, LEVERAGE)

        if result:
            if result.get('closed_due_to_failure'):
                msg = (f"⚠️ <b>فشل إنشاء TP/SL</b>\n\n"
                       f"💰 <b>العملة:</b> {symbol}\n"
                       f"🔒 <b>الإجراء:</b> تم إغلاق الصفقة فوراً\n"
                       f"✅ <b>لم تخسر شيئاً</b>")
                run_async_safe(send_message_safe(update, msg, reply_markup=main_kb))
                return

            add_open_position(result)

            entry_price_eng = format_number_english(result['entry_price'])
            quantity_eng = format_number_english(result['quantity'], 6)

            verification = result.get('verification', {})
            tp_count = verification.get('details', {}).get('tp_count', 0)
            sl_count = verification.get('details', {}).get('sl_count', 0)

            entry_price = result['entry_price']
            position_side = result['positionSide']

            if result.get('multiple_tp'):
                msg = (
                    f"✅ <b>تم تنفيذ الصفقة بنجاح</b>\n\n"
                    f"💰 <b>العملة:</b> {symbol}\n"
                    f"📈 <b>الاتجاه:</b> {side}\n"
                    f"💵 <b>سعر الدخول:</b> <code>{entry_price_eng}</code>\n"
                    f"⚖️ <b>الكمية:</b> <code>{quantity_eng}</code>\n\n"
                    f"🎯 <b>مستويات TP الفعلية:</b>\n"
                )

                tp_results = result.get('tp_results', {})
                successful_tps = [tp for tp in tp_results.get('tp_orders', []) if tp.get('success')]

                for tp in successful_tps:
                    tp_price_eng = format_number_english(tp['tp_price'])
                    try:
                        if position_side == "LONG":
                            actual_pct = ((float(tp['tp_price']) - entry_price) / entry_price) * 100
                        else:
                            actual_pct = ((entry_price - float(tp['tp_price'])) / entry_price) * 100
                        pct_str = f"{actual_pct:+.2f}%"
                    except:
                        pct_str = f"+{tp['tp_percent']:.1f}%"

                    msg += (
                        f"   ✅ <b>TP{tp['level']}:</b> <code>{tp_price_eng}</code>\n"
                        f"      ({pct_str} | {tp['ratio']*100:.0f}% كمية: {format_number_english(tp['quantity'], 4)})\n"
                    )

                if tp_results.get('sl_success'):
                    sl_price_eng = format_number_english(tp_results.get('sl_price'))
                    try:
                        if position_side == "LONG":
                            actual_sl_pct = ((float(tp_results.get('sl_price')) - entry_price) / entry_price) * 100
                        else:
                            actual_sl_pct = ((entry_price - float(tp_results.get('sl_price'))) / entry_price) * 100
                        sl_pct_str = f"{actual_sl_pct:.2f}%"
                    except:
                        sl_pct_str = f"-{SL_PERCENT:.2f}%"

                    msg += (
                        f"\n🛡️ <b>SL:</b> <code>{sl_price_eng}</code>\n"
                        f"      ({sl_pct_str})\n"
                    )
                else:
                    msg += f"\n🚨 <b>لا يوجد SL! - خطر!</b>\n"

                msg += (
                    f"\n✅ <b>التحقق:</b>\n"
                    f"   • أوامر TP: {tp_count}\n"
                    f"   • أوامر SL: {sl_count}\n"
                    f"   • الحالة: {'✅ محمية بالكامل' if sl_count > 0 else '⚠️ غير كاملة'}"
                )
            else:
                msg = (f"✅ <b>تم تنفيذ الصفقة</b>\n\n"
                       f"💰 <b>العملة:</b> {symbol}\n"
                       f"📈 <b>الاتجاه:</b> {side}\n"
                       f"💵 <b>الدخول:</b> <code>{entry_price_eng}</code>\n"
                       f"⚖️ <b>الكمية:</b> <code>{quantity_eng}</code>\n")
        else:
            msg = "❌ <b>فشل تنفيذ الصفقة</b>"

        run_async_safe(send_message_safe(update, msg, reply_markup=main_kb))
    except Exception as e:
        logger.error(f"خطأ في التنفيذ اليدوي: {e}")
        run_async_safe(send_message_safe(update, "❌ حدث خطأ غير متوقع", reply_markup=main_kb))


# ==================== معالج الأخطاء ====================

async def error_handler(update, context):
    error = context.error
    if "Conflict" in str(error):
        logger.warning("⚠️ Conflict: نسخة أخرى تعمل")
        return
    if "Network" in str(error) or "timed out" in str(error):
        logger.warning(f"🌐 خطأ شبكة: {error}")
        return
    if "Event loop is closed" in str(error):
        logger.warning("⚠️ Event loop مغلق")
        return
    logger.error(f"❌ خطأ Telegram: {error}")


# ==================== الأوامر ====================

def _is_owner(update: Update):
    try:
        chat = update.effective_chat
        return chat is not None and str(chat.id) == str(TELEGRAM_CHAT_ID)
    except Exception:
        return False


async def send_log_menu(update: Update):
    """قائمة اختيار نطاق السجل المراد تحميله"""
    try:
        if not _is_owner(update):
            return
        if not log_capture:
            await update.message.reply_text("❌ حفظ السجل غير مفعل (log_capture.py غير موجود)")
            return

        info = log_capture.get_info()
        keyboard = [
            [InlineKeyboardButton("⏱️ آخر ساعة", callback_data="log_1"),
             InlineKeyboardButton("🕒 آخر 3 ساعات", callback_data="log_3")],
            [InlineKeyboardButton("🕕 آخر 6 ساعات", callback_data="log_6"),
             InlineKeyboardButton("📅 آخر 24 ساعة", callback_data="log_24")],
            [InlineKeyboardButton("⚠️ الأخطاء والتحذيرات فقط (24س)", callback_data="log_err")],
            [InlineKeyboardButton("📦 كل السجل المتاح", callback_data="log_all")],
        ]
        await update.message.reply_text(
            f"📥 <b>تحميل سجل البوت</b>\n\n"
            f"المحفوظ حالياً: {info['size_mb']} MB ({info['files']} ملف)\n"
            f"اختر المدة:",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    except Exception as e:
        logger.error(f"خطأ send_log_menu: {e}")


async def send_log_file(query, choice):
    """إرسال ملف السجل المختار كمستند"""
    import io
    try:
        if str(query.message.chat_id) != str(TELEGRAM_CHAT_ID):
            return

        hours = {"1": 1, "3": 3, "6": 6, "24": 24}.get(choice)
        errors_only = (choice == "err")
        if errors_only:
            hours = 24
        label = {"1": "1h", "3": "3h", "6": "6h", "24": "24h", "err": "errors_24h", "all": "all"}.get(choice, choice)

        await query.edit_message_text("⏳ جاري تجهيز السجل...")

        data, lines, t0, t1 = log_capture.get_excerpt(hours=hours, errors_only=errors_only)
        if lines == 0:
            await query.edit_message_text("ℹ️ لا توجد أسطر في هذه المدة")
            return

        stamp = datetime.now().strftime("%Y%m%d_%H%M")
        name = f"bot_log_{label}_{stamp}.txt"
        bio = io.BytesIO(data)
        bio.name = name

        span = ""
        if t0 and t1:
            span = f"\n🕐 {t0.strftime('%m-%d %H:%M')} → {t1.strftime('%m-%d %H:%M')}"
        await query.message.reply_document(
            document=bio, filename=name,
            caption=f"📥 سجل البوت ({label})\n📄 {lines} سطر | {len(data)/1024:.0f} KB{span}"
        )
        await query.edit_message_text("✅ تم إرسال السجل")

    except Exception as e:
        logger.error(f"❌ send_log_file: {e}")
        try:
            await query.edit_message_text(f"❌ فشل إرسال السجل: {str(e)[:120]}")
        except Exception:
            pass


async def export_command(update: Update, context: CallbackContext):
    """
    🔥 v5.7: /export - يرسل ملفات الذاكرة والتعلم كملفات JSON داخل المحادثة
    (للمالك فقط: يتحقق من TELEGRAM_CHAT_ID لأن الملفات فيها بيانات تداول)
    """
    import io
    try:
        if str(update.effective_chat.id) != str(TELEGRAM_CHAT_ID):
            logger.warning(f"🚫 /export من محادثة غير مصرح بها: {update.effective_chat.id}")
            return

        await update.message.reply_text("📦 جاري تجهيز الملفات...")

        files = []

        # 1) ذاكرة الصفقات
        try:
            import trade_memory
            mem = trade_memory.load_memory()
            files.append(("trade_memory.json", mem))
        except Exception as e:
            logger.error(f"export memory: {e}")

        # 2) قواعد التعلم وحالة المخاطر
        extra = {}
        try:
            import adaptive_rules
            extra["learned_rules"] = adaptive_rules.load_rules(force=True)
        except Exception as e:
            extra["learned_rules_error"] = str(e)
        try:
            extra["risk_state"] = {
                "consecutive_losses": core.get_consecutive_losses(),
                "paused": (lambda r: bool(r[0]) if isinstance(r, (tuple, list)) else bool(r))(core.is_trading_paused()),
                "pause_reason": core.get_pause_reason(),
                "risk_multiplier": core.get_risk_multiplier(),
            }
        except Exception as e:
            extra["risk_state_error"] = str(e)
        files.append(("bot_state.json", extra))

        sent = 0
        for name, data in files:
            payload = json.dumps(data, indent=2, ensure_ascii=False, default=str).encode("utf-8")
            bio = io.BytesIO(payload)
            bio.name = name
            await update.message.reply_document(document=bio, filename=name)
            sent += 1

        trades = 0
        verified = 0
        for n, d in files:
            if n == "trade_memory.json":
                trades = len(d.get("trades", []))
                verified = sum(1 for t in d.get("trades", []) if t.get("pnl_verified"))
        await update.message.reply_text(
            f"✅ تم إرسال {sent} ملف\n📊 الصفقات: {trades} (موثقة: {verified})"
        )

    except Exception as e:
        logger.error(f"❌ export: {e}")
        try:
            await update.message.reply_text(f"❌ فشل التصدير: {e}")
        except Exception:
            pass


async def start(update: Update, context: CallbackContext):
    status = "🟢 نشط" if _bot_running else "🔴 متوقف"
    tp_system = "متعدد المستويات" if ENABLE_MULTIPLE_TP else "مستوى واحد"

    daily_data = core.get_accurate_daily_pnl()
    weekly_data = core.get_accurate_weekly_pnl()
    monthly_data = core.get_accurate_monthly_pnl()

    groq_status = "✅ مفعل" if GROQ_AVAILABLE else "❌ معطل"
    learning_status = "✅ مفعل" if ENABLE_AUTO_LEARNING else "❌ معطل"
    firebase_status = "✅ مفعل" if ENABLE_FIREBASE_BACKUP else "❌ معطل"

    await update.message.reply_text(
        f"🤖 <b>بوت القناص الذكي v5.6</b> - {status}\n\n"
        f"🎯 <b>الاستراتيجية:</b> Price Action + AI\n\n"
        f"⚙️ <b>الإعدادات:</b>\n"
        f"• رأس المال: {TRADE_USDT} USDT\n"
        f"• الرافعة: {LEVERAGE}x\n"
        f"• الحد الأقصى: {MAX_OPEN_POSITIONS} صفقات\n"
        f"• TP: {tp_system}\n"
        f"• SL: {SL_PERCENT}%\n"
        f"• Groq AI: {groq_status}\n"
        f"• التعلم: {learning_status}\n"
        f"• Firebase: {firebase_status}\n\n"
        f"🚀 <b>نظام TP:</b>\n"
        f"• L1: {TP_MULTIPLE_LEVELS[0]}% ({TP_QUANTITY_RATIOS[0]*100}%)\n"
        f"• L2: {TP_MULTIPLE_LEVELS[1]}% ({TP_QUANTITY_RATIOS[1]*100}%)\n"
        f"• L3: {TP_MULTIPLE_LEVELS[2]}% ({TP_QUANTITY_RATIOS[2]*100}%)\n\n"
        f"📊 <b>الأرباح:</b>\n"
        f"• اليوم: {daily_data['daily_pnl']:.2f}\n"
        f"• الأسبوع: {weekly_data['weekly_pnl']:.2f}\n"
        f"• الشهر: {monthly_data['monthly_pnl']:.2f}\n\n"
        f"📊 <b>الحالة: {status}</b>",
        parse_mode="HTML",
        reply_markup=main_kb
    )


async def handle_message(update: Update, context: CallbackContext):
    text = (update.message.text or "").strip()
    global _bot_running

    logger.info(f"📨 رسالة مستلمة: '{text}'")

    # ==================== 🔥 v5.8: تحميل السجل / تصدير البيانات ====================
    if text == "📥 تحميل السجل":
        await send_log_menu(update)
        return

    if text == "📦 تصدير البيانات":
        await export_command(update, context)
        return

    if text == "👻 تقرير الظل":
        if _is_owner(update):
            try:
                import shadow_tracker
                await update.message.reply_text(shadow_tracker.summary_text(), parse_mode="HTML", reply_markup=main_kb)
            except Exception as e:
                await update.message.reply_text(f"❌ خطأ: {e}", reply_markup=main_kb)
        return

    # ==================== الرصيد ====================
    if text == "💰 الرصيد":
        try:
            balance_info = get_full_balance_info()
            if balance_info:
                available = balance_info.get('available', 0)
                wallet = balance_info.get('wallet', 0)
                unrealized = balance_info.get('unrealized_pnl', 0)
                margin = balance_info.get('margin', 0)

                msg = (
                    f"💰 <b>تفاصيل الرصيد:</b>\n\n"
                    f"✅ <b>المتاح للتداول:</b> {format_number_english(available, 2)} USDT\n"
                    f"💼 <b>إجمالي المحفظة:</b> {format_number_english(wallet, 2)} USDT\n"
                    f"📊 <b>هامش الصفقات:</b> {format_number_english(margin, 2)} USDT\n"
                    f"📈 <b>ربح/خسارة غير محقق:</b> {format_number_english(unrealized, 2)} USDT\n"
                )
                await update.message.reply_text(msg, parse_mode="HTML", reply_markup=main_kb)
                return
        except Exception as e:
            logger.error(f"خطأ: {e}")

        bal = core.get_futures_balance("USDT")
        await update.message.reply_text(f"💰 <b>الرصيد:</b> {format_number_english(bal, 2)} USDT", parse_mode="HTML", reply_markup=main_kb)
        return

    # ==================== تشغيل/إيقاف البوت ====================
    if text == "🔄 تشغيل/إيقاف البوت":
        _bot_running = not _bot_running
        status = "🟢 نشط" if _bot_running else "🔴 متوقف"

        if _bot_running:
            import main_enhanced as auto_main
            auto_main._auto_scan_enabled = True
            auto_main._auto_trading_enabled = True
            msg = f"✅ <b>تم تشغيل البوت</b>\n\n📊 الحالة: {status}"
        else:
            import main_enhanced as auto_main
            auto_main._auto_scan_enabled = False
            auto_main._auto_trading_enabled = False
            msg = f"⏸️ <b>تم إيقاف البوت</b>\n\n📊 الحالة: {status}"

        await update.message.reply_text(msg, parse_mode="HTML", reply_markup=main_kb)
        return

    # ==================== تشغيل/إيقاف التلقائي ====================
    if text == "🤖 تشغيل/إوقف التلقائي":
        import main_enhanced as auto_main
        result = auto_main.toggle_auto_trading()
        await update.message.reply_text(result, parse_mode="HTML", reply_markup=main_kb)
        return

    # ==================== البحث عن إشارات ====================
    if text == "🔍 البحث عن إشارات":
        if not _bot_running:
            await update.message.reply_text("❌ البوت متوقف.", parse_mode="HTML", reply_markup=main_kb)
            return
        await update.message.reply_text("🔍 <b>جاري البحث...</b>", parse_mode="HTML", reply_markup=main_kb)
        threading.Thread(target=_scan_premium_signals, args=(update,), daemon=True).start()
        return

    # ==================== الصفقات المفتوحة ====================
    if text == "📊 الصفقات المفتوحة":
        await _show_open_positions(update)
        return

    # ==================== فحص الأوامر المشروطة ====================
    if text == "🔎 فحص الأوامر المشروطة":
        await _show_algo_orders(update)
        return

    # ==================== التعلم التلقائي ====================
    if text == "🧠 التعلم التلقائي":
        await _show_learning_status(update)
        return

    # ==================== تقرير سريع ====================
    if text == "📊 تقرير سريع":
        await _show_quick_report(update)
        return

    # ==================== الأرباح ====================
    if text == "📈 الأرباح اليومية":
        await _show_daily_pnl(update)
        return
    if text == "📊 الأرباح الأسبوعية":
        await _show_weekly_pnl(update)
        return
    if text == "📈 الأرباح الشهرية":
        await _show_monthly_pnl(update)
        return

    # ==================== إغلاق الصفقات ====================
    if text == "⚡ إغلاق جميع الصفقات":
        keyboard = [
            [InlineKeyboardButton("✅ نعم، إغلاق الكل", callback_data="confirm_close_all")],
            [InlineKeyboardButton("❌ إلغاء", callback_data="cancel_close_all")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(
            "⚠️ <b>إغلاق جميع الصفقات؟</b>",
            parse_mode="HTML", reply_markup=reply_markup
        )
        return

    if text == "🔒 قفل الصفقات الرابحة":
        keyboard = [
            [InlineKeyboardButton("✅ نعم، قفل الرابحة", callback_data="confirm_close_profitable")],
            [InlineKeyboardButton("❌ إلغاء", callback_data="cancel_close_profitable")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(
            "⚠️ <b>قفل الصفقات الرابحة فقط؟</b>",
            parse_mode="HTML", reply_markup=reply_markup
        )
        return

    if text == "🛑 إغلاق الصفقات الخاسرة":
        keyboard = [
            [InlineKeyboardButton("✅ نعم، إغلاق الخاسرة", callback_data="confirm_close_losing")],
            [InlineKeyboardButton("❌ إلغاء", callback_data="cancel_close_losing")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(
            "⚠️ <b>إغلاق الصفقات الخاسرة فقط؟</b>",
            parse_mode="HTML", reply_markup=reply_markup
        )
        return

    # ==================== تقارير ====================
    if text == "📋 تقرير الأداء":
        await _show_enhanced_performance_report(update)
        return

    if text == "🧠 تقرير التشخيص":
        try:
            import learning_report
            report = learning_report.build_report()
            await update.message.reply_text(report[:3900], parse_mode="HTML", reply_markup=main_kb)
            try:
                with open("learning_report.txt", "w", encoding="utf-8") as f:
                    f.write(report)
                await update.message.reply_document(document=open("learning_report.txt", "rb"),
                                                    caption="📎 تقرير التشخيص الكامل",
                                                    reply_markup=main_kb)
            except Exception:
                pass
        except Exception as e:
            logger.error(f"تقرير التشخيص: {e}")
            await update.message.reply_text("❌ تعذر إنشاء تقرير التشخيص", reply_markup=main_kb)
        return

    # ==================== تحديث الأوامر ====================
    if text == "🔄 تحديث الأوامر":
        await update.message.reply_text("🔄 <b>جاري التحديث...</b>", parse_mode="HTML", reply_markup=main_kb)
        threading.Thread(target=_update_orders, args=(update,), daemon=True).start()
        return

    # ==================== 🔥 حالة النظام (v5.6) ====================
    if text == "📊 حالة النظام":
        import main_enhanced as auto_main
        status = auto_main.get_system_status()

        auto_scan_status = "✅" if status['auto_scan'] else "⏸️"
        auto_trading_status = "✅" if status['auto_trading'] else "⏸️"
        bot_status = "🟢" if _bot_running else "🔴"
        tp_system = "متعدد" if ENABLE_MULTIPLE_TP else "واحد"
        groq_status = "✅" if GROQ_AVAILABLE else "❌"

        # 🔥 v5.6: حالة AI (Gemini + Groq)
        gemini_status = "❌"
        active_provider = "غير معروف"
        try:
            import groq_integration
            gemini_status = "✅" if groq_integration.gemini_available else "❌"
            ai_status = groq_integration.get_ai_status()
            provider = ai_status.get('active_provider', 'none')
            if provider == 'gemini':
                active_provider = "🟢 Gemini"
            elif provider == 'groq':
                active_provider = "🟢 Groq"
            else:
                active_provider = "❌ معطل"
        except:
            pass

        # 🔥 v5.6: Firebase status
        firebase_status = "❌"
        try:
            import firebase_backup
            if firebase_backup.is_available():
                firebase_status = "✅"
        except:
            pass

        balance_info = get_full_balance_info()
        available = balance_info.get('available', 0)
        wallet = balance_info.get('wallet', 0)

        msg = (
            f"📊 <b>حالة النظام v5.6</b>\n\n"
            f"🤖 <b>البوت:</b> {bot_status}\n"
            f"🔍 <b>المسح:</b> {auto_scan_status}\n"
            f"🤖 <b>التنفيذ:</b> {auto_trading_status}\n\n"
            f"🧠 <b>مزودو AI:</b>\n"
            f"   • Groq: {groq_status}\n"
            f"   • Gemini: {gemini_status}\n"
            f"   • النشط: {active_provider}\n\n"
            f"🔥 <b>Firebase:</b> {firebase_status}\n\n"
            f"📈 <b>الصفقات:</b> {status['open_positions']}/{status['max_positions']}\n"
            f"👤 <b>صفقاتك:</b> {status.get('manual_positions', 0)}\n\n"
            f"💰 <b>الرصيد:</b>\n"
            f"   • المتاح: {available:.2f} USDT\n"
            f"   • الإجمالي: {wallet:.2f} USDT\n\n"
            f"📊 <b>الأرباح:</b>\n"
            f"   • اليوم: {status['daily_pnl']:.2f}\n"
            f"   • الأسبوع: {status['weekly_pnl']:.2f}\n"
            f"   • الشهر: {status['monthly_pnl']:.2f}\n\n"
            f"⏳ <b>التبريد:</b> {status['cooldown_symbols']}\n"
            f"🛑 <b>خسائر متتالية:</b> {status.get('consecutive_losses', 0)}/{MAX_CONSECUTIVE_LOSSES}\n"
            f"🚀 <b>TP:</b> {tp_system}\n"
            f"⚙️ <b>SL:</b> {SL_PERCENT}% (ديناميكي)\n"
            f"🔒 <b>Trailing SL:</b> {'✅' if TRAILING_SL_ENABLED else '❌'}\n"
            f"🔒 <b>Breakeven بعد TP1:</b> ✅\n"
            f"🧠 <b>التعلم التلقائي:</b> {'✅' if ENABLE_AUTO_LEARNING else '❌'}\n"
        )

        if status.get('is_paused'):
            msg += f"\n⏸️ <b>متوقف:</b> {status.get('pause_remaining', 0)} دقيقة"

        await update.message.reply_text(msg, parse_mode="HTML", reply_markup=main_kb)
        return

    # ==================== تحليل عملة ====================
    t = text.upper().lstrip("/")
    sym = None

    if len(t) in [3, 4] and t.isalpha():
        sym = t + "USDT"
    elif t.endswith("USDT"):
        sym = t

    if sym:
        if not _bot_running:
            await update.message.reply_text("❌ البوت متوقف.", parse_mode="HTML", reply_markup=main_kb)
            return
        await update.message.reply_text(f"🧠 <b>جاري تحليل {sym}...</b>", parse_mode="HTML", reply_markup=main_kb)
        threading.Thread(target=_analyze_smart_detailed, args=(update, sym), daemon=True).start()
        return

    await update.message.reply_text(
        "❓ <b>تعليمات البوت v5.6:</b>\n\n"
        "• <code>💰 الرصيد</code>\n"
        "• <code>📊 الصفقات المفتوحة</code>\n"
        "• <code>🔎 فحص الأوامر المشروطة</code>\n"
        "• <code>🧠 التعلم التلقائي</code>\n"
        "• <code>📊 تقرير سريع</code>\n"
        "• <code>🔍 البحث عن إشارات</code>\n"
        "• <code>رمز العملة</code> (مثال: BTC)\n"
        "• <code>📊 حالة النظام</code>\n"
        "• <code>📋 تقرير الأداء</code>\n"
        "• <code>🔄 تحديث الأوامر</code>",
        parse_mode="HTML", reply_markup=main_kb
    )


# ==================== دوال مساعدة ====================

def _scan_premium_signals(update: Update):
    try:
        signals = strat.scan_premium_signals()
        if signals:
            msg = f"🎯 <b>تم العثور على {len(signals)} إشارة:</b>\n\n"
            for i, sig in enumerate(signals, 1):
                groq_info = ""
                if sig.get('groq_recommendation'):
                    emoji = "✅" if sig['groq_recommendation'] == "تأكيد" else "❌" if sig['groq_recommendation'] == "رفض" else "⚠️"
                    groq_info = f" | 🧠 {emoji}"
                msg += f"{i}. {sig['symbol']} - {sig['direction']}\n"
                msg += f"   قوة: {sig['strength']}/10 | ثقة: {sig['confidence']:.1f}% | نقاط: {sig.get('total_score', 0)}/100{groq_info}\n"
            msg += f"\n📊 <b>الصفقات:</b> {len(core.get_open_positions())}/{MAX_OPEN_POSITIONS}"
        else:
            msg = "🔍 <b>لم يتم العثور على إشارات</b>"
        run_async_safe(send_message_safe(update, msg, reply_markup=main_kb))
    except Exception as e:
        logger.error(f"خطأ: {e}")
        run_async_safe(send_message_safe(update, "❌ <b>خطأ</b>", reply_markup=main_kb))


async def _analyze_smart_detailed_async(update: Update, symbol):
    try:
        logger.info(f"🧠 تحليل {symbol}")
        analysis = analyze_with_timeout(symbol, 25)

        if analysis and analysis.get('recommendation'):
            from bot_strategies_enhanced import format_smart_analysis_for_display
            analysis_msg = format_smart_analysis_for_display(analysis)

            rec = analysis['recommendation']
            confidence = rec['confidence']

            if confidence >= 60 and rec['action'] in ['BUY', 'SELL']:
                if confidence >= 75:
                    button_text = f"🚀 تنفيذ {rec['action']}"
                elif confidence >= 65:
                    button_text = f"⚠️ تنفيذ {rec['action']}"
                else:
                    button_text = f"🛑 تنفيذ {rec['action']}"

                keyboard = [
                    [InlineKeyboardButton(button_text, callback_data=f"trade_{symbol}_{rec['action']}")],
                    [InlineKeyboardButton("🔄 تحليل جديد", callback_data=f"new_analysis_{symbol}")]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
                await send_message_safe(update, analysis_msg, reply_markup=reply_markup)
            else:
                keyboard = [[InlineKeyboardButton("🔄 تحليل جديد", callback_data=f"new_analysis_{symbol}")]]
                reply_markup = InlineKeyboardMarkup(keyboard)
                await send_message_safe(update, analysis_msg, reply_markup=reply_markup)
        else:
            await send_message_safe(update,
                f"🔍 <b>لا توجد إشارة قوية لـ {symbol}</b>\n\n"
                f"📉 <b>الأسباب:</b>\n"
                f"• اتجاه غير واضح\n"
                f"• حجم غير كافٍ\n"
                f"• مؤشرات متضاربة\n\n"
                f"⏰ <b>جرب بعد 15-30 دقيقة</b>",
                reply_markup=main_kb
            )
    except Exception as e:
        logger.error(f"❌ خطأ: {e}")
        await send_message_safe(update, f"❌ <b>خطأ في التحليل</b>", reply_markup=main_kb)


def _analyze_smart_detailed(update: Update, symbol):
    try:
        run_async_new_loop(_analyze_smart_detailed_async(update, symbol))
    except Exception as e:
        logger.error(f"❌ خطأ: {e}")


# ==================== فحص الأوامر ====================

async def _show_algo_orders(update: Update):
    try:
        positions = core.get_open_positions()
        if not positions:
            await update.message.reply_text("📭 <b>لا توجد صفقات مفتوحة</b>", parse_mode="HTML", reply_markup=main_kb)
            return

        msg = "🔎 <b>فحص الأوامر المشروطة:</b>\n\n"
        total_orders = 0
        missing_count = 0

        for pos in positions:
            try:
                symbol = pos.get("symbol", "UNKNOWN")
                position_side = pos.get("positionSide", "BOTH")
                entry_price = float(pos.get("entryPrice", 0))
                amt = float(pos.get("positionAmt", 0))
                side_emoji = "🟢" if amt > 0 else "🔴"

                msg += f"{side_emoji} <b>{symbol}</b> ({position_side})\n"
                msg += f"💰 الدخول: <code>{entry_price}</code>\n"

                algo_orders = []
                regular_orders = []

                try:
                    algo_orders = core.get_open_algo_orders(symbol) or []
                except:
                    pass
                try:
                    regular_orders = core.get_open_orders(symbol) or []
                except:
                    pass

                all_orders = list(algo_orders) + list(regular_orders)
                tp_orders = [o for o in all_orders if o.get('type') == 'TAKE_PROFIT_MARKET']
                sl_orders = [o for o in all_orders if o.get('type') == 'STOP_MARKET']

                msg += f"📊 الأوامر: Algo={len(algo_orders)}, عادية={len(regular_orders)}, TP={len(tp_orders)}, SL={len(sl_orders)}\n"
                total_orders += len(all_orders)

                if tp_orders:
                    msg += f"\n🎯 <b>أوامر TP:</b>\n"
                    tp_sorted = sorted(tp_orders, key=lambda x: float(x.get('triggerPrice') or x.get('stopPrice') or 0))
                    if amt < 0:
                        tp_sorted = list(reversed(tp_sorted))

                    for i, tp in enumerate(tp_sorted[:3], 1):
                        tp_price = tp.get('triggerPrice') or tp.get('stopPrice', 'N/A')
                        tp_qty = tp.get('origQty') or tp.get('quantity', 'N/A')
                        try:
                            if amt > 0:
                                tp_pct = ((float(tp_price) - entry_price) / entry_price) * 100
                            else:
                                tp_pct = ((entry_price - float(tp_price)) / entry_price) * 100
                            tp_pct_str = f" ({tp_pct:+.2f}%)"
                        except:
                            tp_pct_str = ""
                        msg += f"   {i}. <code>{tp_price}</code>{tp_pct_str} | كمية: {tp_qty}\n"
                else:
                    msg += f"\n⚠️ <b>لا توجد أوامر TP!</b>\n"
                    missing_count += 1

                if sl_orders:
                    msg += f"\n🛡️ <b>أوامر SL:</b>\n"
                    for sl in sl_orders:
                        sl_price = sl.get('triggerPrice') or sl.get('stopPrice', 'N/A')
                        sl_qty = sl.get('origQty') or sl.get('quantity', 'N/A')
                        try:
                            if amt > 0:
                                sl_pct = ((float(sl_price) - entry_price) / entry_price) * 100
                            else:
                                sl_pct = ((entry_price - float(sl_price)) / entry_price) * 100
                            sl_pct_str = f" ({sl_pct:+.2f}%)"
                        except:
                            sl_pct_str = ""
                        msg += f"   <code>{sl_price}</code>{sl_pct_str} | كمية: {sl_qty}\n"
                else:
                    msg += f"\n🚨 <b>لا يوجد SL! - خطر!</b>\n"
                    missing_count += 1

                if len(tp_orders) >= 3 and len(sl_orders) >= 1:
                    msg += f"\n✅ محمية بالكامل\n"
                elif len(sl_orders) >= 1:
                    msg += f"\n⚠️ SL موجود، TP ناقص\n"
                else:
                    msg += f"\n🚨 غير محمية!\n"

                msg += "━━━━━━━━━━━━━━━━\n\n"
            except Exception as e:
                logger.error(f"❌ خطأ: {e}")
                continue

        msg += f"📊 <b>الإحصائيات:</b>\n"
        msg += f"   • صفقات: {len(positions)}\n"
        msg += f"   • أوامر: {total_orders}\n"

        if missing_count > 0:
            msg += f"\n⚠️ {missing_count} صفقة ناقصة الحماية!\n"
            msg += f"💡 استخدم <code>🔄 تحديث الأوامر</code>"
        else:
            msg += f"\n✅ جميع الصفقات محمية"

        await update.message.reply_text(msg, parse_mode="HTML", reply_markup=main_kb)
    except Exception as e:
        logger.error(f"❌ خطأ: {e}")
        await update.message.reply_text(f"❌ <b>خطأ:</b> {str(e)[:200]}", parse_mode="HTML", reply_markup=main_kb)


async def _show_open_positions(update: Update):
    try:
        positions = core.get_open_positions()
        if not positions:
            await update.message.reply_text("📭 <b>لا توجد صفقات مفتوحة</b>", parse_mode="HTML", reply_markup=main_kb)
            return

        msg = "📊 <b>الصفقات المفتوحة:</b>\n\n"
        total_profit = 0

        for pos in positions:
            try:
                symbol = pos.get("symbol", "UNKNOWN")
                amt = float(pos.get("positionAmt", 0))
                entry = float(pos.get("entryPrice", 0))
                profit = float(pos.get("unrealizedProfit", 0))
                total_profit += profit
                side = "🟢 LONG" if amt > 0 else "🔴 SHORT"

                has_tp, has_sl, details = core.verify_tp_sl_created(symbol, pos.get("positionSide"))
                if has_tp and has_sl:
                    order_status = "✅ مفعل"
                elif has_sl:
                    order_status = "⚠️ TP مفقود"
                elif has_tp:
                    order_status = "⚠️ SL مفقود!"
                else:
                    order_status = "❌ لا يوجد!"

                profit_status = "🟢 رابح" if profit > 0 else "🔴 خاسر" if profit < 0 else "⚪ متعادل"

                msg += f"{side} <b>{symbol}</b> {profit_status}\n"
                msg += f"💰 الدخول: {format_number_english(entry)} | 💵 الربح: {format_number_english(profit, 2)} USDT\n"
                msg += f"📊 TP/SL: {order_status}\n—\n"
            except Exception as e:
                logger.error(f"⚠️ فشل إغلاق {position.get('symbol', '?')}: {e}")
                errors.append(str(e)[:80])
                continue

        msg += f"\n💰 <b>إجمالي الأرباح:</b> {format_number_english(total_profit, 2)} USDT"
        if total_profit < 0:
            msg += f"\n\n⚠️ يمكنك استخدام 🛑 إغلاق الصفقات الخاسرة"
        elif total_profit > 0:
            msg += f"\n\n💡 يمكنك استخدام 🔒 قفل الصفقات الرابحة"

        await update.message.reply_text(msg, parse_mode="HTML", reply_markup=main_kb)
    except Exception as e:
        logger.error(f"❌ خطأ: {e}")
        await update.message.reply_text("❌ <b>خطأ</b>", parse_mode="HTML", reply_markup=main_kb)


async def _show_daily_pnl(update: Update):
    try:
        daily_data = core.get_accurate_daily_pnl()
        msg = core.format_pnl_report(daily_data, "يومي")
        await update.message.reply_text(msg, parse_mode="HTML", reply_markup=main_kb)
    except Exception as e:
        logger.error(f"خطأ: {e}")
        await update.message.reply_text("❌ <b>خطأ</b>", parse_mode="HTML", reply_markup=main_kb)


async def _show_weekly_pnl(update: Update):
    try:
        weekly_data = core.get_accurate_weekly_pnl()
        msg = core.format_pnl_report(weekly_data, "أسبوعي")
        await update.message.reply_text(msg, parse_mode="HTML", reply_markup=main_kb)
    except Exception as e:
        logger.error(f"خطأ: {e}")
        await update.message.reply_text("❌ <b>خطأ</b>", parse_mode="HTML", reply_markup=main_kb)


async def _show_monthly_pnl(update: Update):
    try:
        monthly_data = core.get_accurate_monthly_pnl()
        msg = core.format_pnl_report(monthly_data, "شهري")
        await update.message.reply_text(msg, parse_mode="HTML", reply_markup=main_kb)
    except Exception as e:
        logger.error(f"خطأ: {e}")
        await update.message.reply_text("❌ <b>خطأ</b>", parse_mode="HTML", reply_markup=main_kb)


async def _show_enhanced_performance_report(update: Update):
    try:
        daily_data = core.get_accurate_daily_pnl()
        weekly_data = core.get_accurate_weekly_pnl()
        monthly_data = core.get_accurate_monthly_pnl()
        positions = core.get_open_positions()

        balance_info = get_full_balance_info()
        available = balance_info.get('available', 0)
        wallet = balance_info.get('wallet', 0)

        daily_trade_count = daily_data['trade_count']
        weekly_trade_count = weekly_data['trade_count']
        monthly_trade_count = monthly_data['trade_count']

        successful_daily = len([t for t in daily_data['today_trades'] if t['income'] > 0])
        successful_weekly = len([t for t in weekly_data['weekly_trades'] if t['income'] > 0])
        successful_monthly = len([t for t in monthly_data['monthly_trades'] if t['income'] > 0])

        daily_rate = (successful_daily / daily_trade_count * 100) if daily_trade_count > 0 else 0
        weekly_rate = (successful_weekly / weekly_trade_count * 100) if weekly_trade_count > 0 else 0
        monthly_rate = (successful_monthly / monthly_trade_count * 100) if monthly_trade_count > 0 else 0

        msg = (
            f"📋 <b>تقرير الأداء v5.6</b>\n\n"
            f"💰 <b>الرصيد:</b>\n"
            f"   • المتاح: {available:.2f} USDT\n"
            f"   • الإجمالي: {wallet:.2f} USDT\n\n"
            f"📊 <b>اليوم:</b>\n"
            f"   • PnL: {daily_data['daily_pnl']:.2f} USDT\n"
            f"   • الصفقات: {daily_trade_count}\n"
            f"   • الناجحة: {successful_daily}\n"
            f"   • نسبة النجاح: {daily_rate:.1f}%\n\n"
            f"📈 <b>الأسبوع:</b>\n"
            f"   • PnL: {weekly_data['weekly_pnl']:.2f} USDT\n"
            f"   • الصفقات: {weekly_trade_count}\n"
            f"   • نسبة النجاح: {weekly_rate:.1f}%\n\n"
            f"📅 <b>الشهر:</b>\n"
            f"   • PnL: {monthly_data['monthly_pnl']:.2f} USDT\n"
            f"   • الصفقات: {monthly_trade_count}\n"
            f"   • نسبة النجاح: {monthly_rate:.1f}%\n\n"
            f"🔓 <b>الصفقات المفتوحة:</b> {len(positions)}/{MAX_OPEN_POSITIONS}\n"
            f"🚀 <b>TP:</b> {TP_MULTIPLE_LEVELS}\n"
            f"🛡️ <b>SL:</b> {SL_PERCENT}%\n"
        )
        await update.message.reply_text(msg, parse_mode="HTML", reply_markup=main_kb)
    except Exception as e:
        logger.error(f"خطأ: {e}")
        await update.message.reply_text("❌ <b>خطأ</b>", parse_mode="HTML", reply_markup=main_kb)


async def _show_learning_status(update: Update):
    try:
        msg = "🧠 <b>حالة التعلم التلقائي</b>\n\n"

        # الإعدادات
        try:
            learning_status = "✅ مفعل" if ENABLE_AUTO_LEARNING else "❌ معطل"
            tuning_status = "✅ مفعل" if AUTO_TUNE_WEIGHTS else "❌ معطل"
            protection_status = "✅ مفعل" if AUTO_PROTECTION_ENABLED else "❌ معطل"

            msg += f"📊 <b>الإعدادات:</b>\n"
            msg += f"   • التعلم: {learning_status}\n"
            msg += f"   • تعديل الأوزان: {tuning_status}\n"
            msg += f"   • الحماية الذاتية: {protection_status}\n"
            msg += f"   • كل: {AUTO_LEARN_INTERVAL_HOURS} ساعة\n"
            msg += f"   • بعد: {AUTO_LEARN_MIN_TRADES} صفقة\n\n"
        except Exception as e:
            logger.error(f"خطأ في الإعدادات: {e}")

        # الصفقات
        try:
            import trade_memory as memory
            mem_stats = memory.get_memory_stats()
            total = mem_stats.get('total_trades', 0)
            win_rate = mem_stats.get('win_rate', 0)
            remaining = max(0, AUTO_LEARN_MIN_TRADES - total)

            msg += f"📊 <b>الصفقات:</b>\n"
            msg += f"   • الإجمالي: {total}\n"
            msg += f"   • نسبة النجاح: {win_rate:.1f}%\n"
            if remaining > 0:
                msg += f"   • متبقي للتعلم: {remaining} صفقة\n"
            else:
                msg += f"   • جاهز للتعلم ✅\n"
            msg += "\n"
        except Exception as e:
            logger.error(f"خطأ في الصفقات: {e}")

        # 🔥 v5.7: قواعد التعلم التكيفي الفعلية
        try:
            import adaptive_rules
            msg += adaptive_rules.get_status_text() + "\n\n"
        except Exception as e:
            logger.error(f"خطأ في قواعد التعلم: {e}")

        # الجدولة
        try:
            import smart_scheduler
            sched_status = smart_scheduler.get_scheduler_status()
            msg += f"⏰ <b>الجدولة:</b>\n"
            msg += f"   • الحالة: {'🟢 نشط' if sched_status.get('running') else '🔴 متوقف'}\n"
            last_learn = sched_status.get('last_learning')
            if last_learn:
                msg += f"   • آخر تعلم: {last_learn[:19]}\n"
            msg += "\n"
        except Exception as e:
            logger.error(f"خطأ في الجدولة: {e}")

        keyboard = [
            [InlineKeyboardButton("🚀 تشغيل التعلم الآن", callback_data="force_learning")],
            [InlineKeyboardButton("📊 تقرير الأداء الكامل", callback_data="full_performance_report")],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(msg, parse_mode="HTML", reply_markup=reply_markup)
    except Exception as e:
        logger.error(f"خطأ: {e}")
        await update.message.reply_text(f"❌ <b>خطأ:</b> {str(e)[:200]}", parse_mode="HTML")


async def _show_quick_report(update: Update):
    try:
        import performance_tracker as tracker
        perf = tracker.get_full_performance(days=7)

        if not perf:
            await update.message.reply_text(
                "📊 <b>لا توجد بيانات كافية</b>\n\nيحتاج البوت لـ 5 صفقات على الأقل.",
                parse_mode="HTML"
            )
            return

        eval_result = tracker.evaluate_performance(perf)

        msg = f"📊 <b>التقرير السريع</b>\n\n"
        msg += f"📈 <b>الأداء (7 أيام):</b>\n"
        msg += f"   • صفقات: {perf['total_trades']}\n"
        msg += f"   • رابحة: {perf['wins']} ✅\n"
        msg += f"   • خاسرة: {perf['losses']} ❌\n"
        msg += f"   • نسبة النجاح: {perf['win_rate']}%\n\n"

        msg += f"💰 <b>الأرباح:</b>\n"
        msg += f"   • الإجمالي: {perf['total_pnl']:+.4f} USDT\n"
        msg += f"   • متوسط الربح: {perf['avg_win']:+.4f}\n"
        msg += f"   • متوسط الخسارة: {perf['avg_loss']:+.4f}\n\n"

        msg += f"📊 <b>المؤشرات:</b>\n"
        msg += f"   • Profit Factor: {perf['profit_factor']}\n"
        msg += f"   • R:R Ratio: {perf['rr_ratio']}\n"
        msg += f"   • Sharpe: {perf['sharpe_ratio']}\n"
        msg += f"   • Max DD: {perf['max_drawdown']}\n\n"

        msg += f"🎯 <b>التقييم:</b> {eval_result['rating']}\n"
        msg += f"   ({eval_result['score']}/100)\n\n"

        if perf.get('best_symbol'):
            best = perf['best_symbol']
            msg += f"✅ أفضل: <b>{best[0]}</b> ({best[1]['pnl']:+.2f})\n"
        if perf.get('worst_symbol'):
            worst = perf['worst_symbol']
            msg += f"❌ أسوأ: <b>{worst[0]}</b> ({worst[1]['pnl']:+.2f})\n"

        msg += f"\n⏰ {datetime.now().strftime('%H:%M:%S')}"
        await update.message.reply_text(msg, parse_mode="HTML")
    except Exception as e:
        logger.error(f"خطأ: {e}")
        await update.message.reply_text(f"❌ <b>خطأ:</b> {str(e)[:200]}", parse_mode="HTML")


# ==================== إغلاق الصفقات ====================

def _close_all_positions(update: Update):
    try:
        positions = core.get_open_positions()
        if not positions:
            run_async_safe(send_message_safe(update, "📭 <b>لا توجد صفقات</b>", reply_markup=main_kb))
            return

        closed_count = 0
        total_profit = 0
        errors = []

        for position in positions:
            try:
                symbol = position.get("symbol")
                position_side = position.get("positionSide")
                profit = float(position.get("unrealizedProfit", 0))

                if core.close_position_safe(symbol, position_side):
                    closed_count += 1
                    total_profit += profit
                    remove_open_position(symbol, position_side)
                    time.sleep(0.5)
            except Exception as e:
                logger.error(f"⚠️ فشل إغلاق {position.get('symbol', '?')}: {e}")
                errors.append(str(e)[:80])
                continue

        if closed_count > 0:
            status = "🟢 ربح" if total_profit > 0 else "🔴 خسارة" if total_profit < 0 else "⚪ تعادل"
            msg = f"✅ <b>تم إغلاق {closed_count} صفقة</b>\n\n💰 PnL: {total_profit:.2f} USDT\n📊 {status}"
        else:
            msg = "❌ <b>فشل</b>"

        run_async_safe(send_message_safe(update, msg, reply_markup=main_kb))
    except Exception as e:
        logger.error(f"خطأ: {e}")


def _close_profitable_positions(update: Update):
    try:
        positions = core.get_open_positions()
        profitable = [p for p in positions if float(p.get("unRealizedProfit", p.get("unrealizedProfit", 0))) > 0]

        if not profitable:
            run_async_safe(send_message_safe(update, "📭 <b>لا توجد صفقات رابحة</b>", reply_markup=main_kb))
            return

        closed_count = 0
        total_profit = 0
        errors = []

        for position in profitable:
            try:
                symbol = position.get("symbol")
                position_side = position.get("positionSide")
                profit = float(position.get("unrealizedProfit", 0))
                close_reason = []

                if core.close_position_safe(symbol, position_side, error_ref=close_reason):
                    closed_count += 1
                    total_profit += profit
                    remove_open_position(symbol, position_side)
                    time.sleep(0.5)
                else:
                    reason = close_reason[0] if close_reason else "close_position_safe أعاد False — راجع اللوج"
                    errors.append(f"{symbol}: {reason}"[:160])
            except Exception as e:
                logger.error(f"⚠️ فشل إغلاق {position.get('symbol', '?')}: {e}")
                errors.append(str(e)[:80])
                continue

        if closed_count > 0:
            msg = f"🔒 <b>تم قفل {closed_count} صفقة</b>\n\n💰 الأرباح: {total_profit:.2f} USDT"
            if errors:
                msg += f"\n\n⚠️ تعذر قفل {len(errors)}:\n" + "\n".join("• " + e for e in errors[:3])
        else:
            msg = "❌ <b>فشل</b>"
            if errors:
                msg += "\n\nالأسباب:\n" + "\n".join("• " + e for e in errors[:3])
            else:
                msg += "\n\n(close_position_safe أعاد False — راجع اللوج)"

        run_async_safe(send_message_safe(update, msg, reply_markup=main_kb))
    except Exception as e:
        logger.error(f"خطأ: {e}")


def _close_losing_positions(update: Update):
    try:
        positions = core.get_open_positions()
        losing = [p for p in positions if float(p.get("unRealizedProfit", p.get("unrealizedProfit", 0))) < 0]

        if not losing:
            run_async_safe(send_message_safe(update, "📭 <b>لا توجد صفقات خاسرة</b>", reply_markup=main_kb))
            return

        closed_count = 0
        total_loss = 0
        errors = []

        for position in losing:
            try:
                symbol = position.get("symbol")
                position_side = position.get("positionSide")
                loss = float(position.get("unrealizedProfit", 0))

                if core.close_position_safe(symbol, position_side):
                    closed_count += 1
                    total_loss += loss
                    remove_open_position(symbol, position_side)
                    time.sleep(0.5)
            except Exception as e:
                logger.error(f"⚠️ فشل إغلاق {position.get('symbol', '?')}: {e}")
                errors.append(str(e)[:80])
                continue

        if closed_count > 0:
            msg = f"🛑 <b>تم إغلاق {closed_count} صفقة</b>\n\n💰 الخسائر: {abs(total_loss):.2f} USDT"
        else:
            msg = "❌ <b>فشل</b>"

        run_async_safe(send_message_safe(update, msg, reply_markup=main_kb))
    except Exception as e:
        logger.error(f"خطأ: {e}")


def _update_orders(update: Update):
    try:
        positions_updated = core.check_and_add_tp_sl_to_existing_positions()
        if positions_updated > 0:
            msg = f"✅ <b>تم تحديث {positions_updated} صفقة</b>"
        else:
            msg = "ℹ️ <b>جميع الصفقات محمية</b>"
        run_async_safe(send_message_safe(update, msg, reply_markup=main_kb))
    except Exception as e:
        logger.error(f"خطأ: {e}")


async def button_handler(update: Update, context: CallbackContext):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data.startswith("log_"):
        await send_log_file(query, data.split("_", 1)[1])
        return

    if data.startswith("trade_"):
        _, symbol, side = data.split("_")
        execute_trade_manual(update, symbol, side)

    elif data.startswith("new_analysis_"):
        parts = data.split("_", 2)
        if len(parts) >= 3:
            _analyze_smart_detailed(update, parts[2])

    elif data == "force_learning":
        try:
            await query.edit_message_text("🧠 <b>جاري تشغيل التعلم...</b>", parse_mode="HTML")
            import smart_scheduler
            result = smart_scheduler.force_learning_now()
            if result:
                await query.edit_message_text("✅ <b>تم تشغيل التعلم بنجاح</b>", parse_mode="HTML")
            else:
                await query.edit_message_text("⏳ <b>لا توجد بيانات كافية</b>", parse_mode="HTML")
        except Exception as e:
            logger.error(f"خطأ: {e}")
            await query.edit_message_text(f"❌ خطأ: {str(e)[:100]}", parse_mode="HTML")

    elif data == "full_performance_report":
        try:
            await query.edit_message_text("📊 <b>جاري إنشاء التقرير...</b>", parse_mode="HTML")
            import daily_reporter
            daily_reporter.send_daily_report()
            await query.edit_message_text("✅ <b>تم إرسال التقرير</b>", parse_mode="HTML")
        except Exception as e:
            logger.error(f"خطأ: {e}")
            await query.edit_message_text(f"❌ خطأ", parse_mode="HTML")

    elif data == "confirm_close_all":
        try:
            await query.edit_message_text("🔄 <b>جاري الإغلاق...</b>", parse_mode="HTML")
            _close_all_positions(update)
        except Exception as e:
            logger.error(f"خطأ: {e}")

    elif data == "cancel_close_all":
        try:
            await query.edit_message_text("❌ <b>تم الإلغاء</b>", parse_mode="HTML")
        except:
            pass

    elif data == "confirm_close_profitable":
        try:
            await query.edit_message_text("🔄 <b>جاري القفل...</b>", parse_mode="HTML")
            _close_profitable_positions(update)
        except:
            pass

    elif data == "cancel_close_profitable":
        try:
            await query.edit_message_text("❌ <b>تم الإلغاء</b>", parse_mode="HTML")
        except:
            pass

    elif data == "confirm_close_losing":
        try:
            await query.edit_message_text("🔄 <b>جاري الإغلاق...</b>", parse_mode="HTML")
            _close_losing_positions(update)
        except:
            pass

    elif data == "cancel_close_losing":
        try:
            await query.edit_message_text("❌ <b>تم الإلغاء</b>", parse_mode="HTML")
        except:
            pass


# ==================== التشغيل ====================

def run_bot():
    try:
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

        async def post_init(application):
            logger.info("🚀 البوت بدأ — تشغيل الخيوط في الخلفية...")

            def run_threads_in_background():
                try:
                    import main_enhanced as auto_main
                    auto_main.start_scanner_threads()
                    logger.info("✅ تم تشغيل كل الخيوط بنجاح")
                except Exception as e:
                    logger.error(f"❌ فشل تشغيل الخيوط: {e}")
                    import traceback
                    traceback.print_exc()

            threading.Thread(target=run_threads_in_background, daemon=True).start()
            logger.info("✅ تم إرسال تشغيل الخيوط للخلفية")

        application = (
            Application.builder()
            .token(TELEGRAM_TOKEN)
            .post_init(post_init)
            .build()
        )

        application.add_handler(CommandHandler("start", start))
        application.add_handler(CommandHandler("export", export_command))
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
        application.add_handler(CallbackQueryHandler(button_handler))
        application.add_error_handler(error_handler)

        logger.info("🚀 بدء البوت v5.6...")
        logger.info("📡 Starting Telegram polling...")

        application.run_polling(drop_pending_updates=True)

    except Exception as e:
        logger.error(f"❌ فشل: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    run_bot()