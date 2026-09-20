# ==================================================
# 📁 ملف: main_enhanced.py - الإصدار v4.1.8
# 🔧 التعديلات v4.1.8:
#    - 🔥 إصلاح bad operand type for unary -: 'str'
#    - 🔥 تحويل آمن للأنواع في record_closed_trade
#    - 🔥 تحويل آمن للأنواع في send_close_notification
# 🔧 التعديلات v4.1.7:
#    - إضافة إشعار إغلاق الصفقات
# 🔧 التعديلات v4.1.6:
#    - تبسيط start_scanner_threads
#    - logs في كل خطوة
#    - WebSocket في thread منفصل
# 🔧 التعديلات v4.1.4:
#    - تمييز صفقات البوت عن اليدوية
# 📅 التاريخ: 2026-09-20
# ==================================================

import logging
import threading
import time
import asyncio
import json
import os
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
    logger.info(f"🧠 Groq: {'✅' if GROQ_AVAILABLE else '❌'}")
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


_last_auto_scan = 0
_last_tp_sl_monitor = 0
_auto_scan_enabled = True
_auto_trading_enabled = True

_open_trades_tracking = {}

STATE_FILE = "open_positions.json"


FALLBACK_SYMBOLS = [
    "BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT",
    "ADAUSDT", "DOGEUSDT", "AVAXUSDT", "DOTUSDT", "LINKUSDT",
    "MATICUSDT", "LTCUSDT", "ATOMUSDT", "NEARUSDT", "FILUSDT",
    "AAVEUSDT", "UNIUSDT", "ETCUSDT", "APTUSDT", "ARBUSDT"
]


# ==================== 🔥 دوال تحويل آمنة ====================

def safe_float(value, default=0.0):
    """تحويل آمن إلى float"""
    try:
        return float(value)
    except (ValueError, TypeError):
        return default


def safe_int(value, default=0):
    """تحويل آمن إلى int"""
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

        msg = (
            f"🚀 <b>بوت القناص الذكي v4.1.8</b>\n\n"
            f"💰 <b>رأس المال:</b> {TRADE_USDT} USDT\n"
            f"⚡ <b>الرافعة:</b> {LEVERAGE}x\n"
            f"⏰ <b>المسح:</b> كل {AUTO_SCAN_INTERVAL // 60} دقيقة\n\n"
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
            f"🔔 <b>إشعار إغلاق الصفقات:</b> ✅ مفعل\n\n"
            f"✅ <b>النظام جاهز!</b>"
        )

        async def send_async():
            await bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=msg, parse_mode="HTML")

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


# ==================== خيط مراقبة TP/SL ====================

def monitor_tp_sl_loop():
    try:
        logger.info("🔍 [THREAD] بدء مراقبة TP/SL...")

        global _last_tp_sl_monitor

        while _auto_scan_enabled:
            try:
                current_time = time.time()

                if current_time - _last_tp_sl_monitor >= MONITOR_TP_SL_INTERVAL:
                    _last_tp_sl_monitor = current_time

                    bot_positions = get_bot_owned_positions()

                    if bot_positions:
                        for position in bot_positions:
                            symbol = position['symbol']
                            position_side = position['positionSide']

                            has_tp, has_sl, details = core.verify_tp_sl_created(symbol, position_side)

                            if not has_sl or not has_tp:
                                logger.warning(f"⚠️ {symbol} {position_side} ناقص TP/SL")
                                fixed = core.check_and_add_tp_sl_to_existing_positions()
                                if fixed > 0:
                                    break

            except Exception as e:
                logger.error(f"خطأ في المراقبة: {e}")

            time.sleep(30)

        logger.info("🛑 [THREAD] توقف مراقبة TP/SL")

    except Exception as e:
        logger.error(f"❌ [THREAD] فشل مراقبة TP/SL: {e}")
        traceback.print_exc()


# ==================== خيط مراقبة Trailing SL + الصفقات المغلقة ====================

def monitor_positions_loop():
    try:
        logger.info("📈 [THREAD] بدء مراقبة Trailing SL...")

        while _auto_scan_enabled:
            try:
                updated = core.monitor_trailing_sl()
                if updated > 0:
                    logger.info(f"📊 تحديث {updated} صفقة")

                check_closed_trades()

            except Exception as e:
                logger.error(f"خطأ في Trailing: {e}")

            time.sleep(30)

        logger.info("🛑 [THREAD] توقف Trailing SL")

    except Exception as e:
        logger.error(f"❌ [THREAD] فشل Trailing SL: {e}")
        traceback.print_exc()


def check_closed_trades():
    """فحص الصفقات المغلقة وإرسال إشعار لكل واحدة"""
    try:
        if not _open_trades_tracking:
            return

        current_positions = core.get_open_positions()
        current_keys = set(f"{p['symbol']}_{p['positionSide']}" for p in current_positions)

        closed_keys = [k for k in list(_open_trades_tracking.keys()) if k not in current_keys]

        if closed_keys:
            logger.info(f"🔔 اكتشف {len(closed_keys)} صفقة مغلقة")

        for key in closed_keys:
            trade_data = _open_trades_tracking[key]
            try:
                record_closed_trade(trade_data)
            except Exception as e:
                logger.error(f"خطأ في تسجيل الصفقة المغلقة: {e}")
            del _open_trades_tracking[key]

    except Exception as e:
        logger.error(f"خطأ في check_closed_trades: {e}")


def record_closed_trade(trade_data):
    """
    🔥 v4.1.8: تسجيل الصفقة + إشعار إغلاق (مع تحويل آمن)
    """
    try:
        symbol = trade_data.get('symbol')
        direction = trade_data.get('direction', 'UNKNOWN')
        entry_price = safe_float(trade_data.get('entry_price', 0))
        quantity = safe_float(trade_data.get('quantity', 0))
        position_side = trade_data.get('positionSide', 'LONG')
        entry_time_iso = trade_data.get('entry_time_iso') or datetime.now().isoformat()

        logger.info(f"🔔 معالجة إغلاق: {symbol} {position_side}")

        # ==================== جلب PnL الحقيقي (تحويل آمن) ====================
        pnl = 0.0
        try:
            client_obj = core.get_client()
            if client_obj:
                income = client_obj.futures_income_history(
                    incomeType="REALIZED_PNL",
                    symbol=symbol,
                    limit=5
                )
                if income:
                    # 🔥 v4.1.8: تحويل آمن
                    raw_income = income[-1].get('income', 0)
                    pnl = safe_float(raw_income, 0.0)
                    logger.info(f"💰 PnL من Binance: {pnl:+.4f} (raw: {raw_income}, type: {type(raw_income).__name__})")
        except Exception as e:
            logger.warning(f"⚠️ فشل جلب PnL لـ {symbol}: {e}")
            pnl = 0.0

        # ==================== تسجيل في الذاكرة ====================
        if MEMORY_AVAILABLE:
            try:
                memory.record_trade(
                    symbol=symbol,
                    direction=direction,
                    entry_price=entry_price,
                    exit_price=0,
                    quantity=quantity,
                    pnl=pnl,
                    confidence=safe_float(trade_data.get('confidence', 0)),
                    timeframe_alignment=safe_float(trade_data.get('timeframe_alignment', 0)),
                    volume_ratio=safe_float(trade_data.get('volume_ratio', 0)),
                    groq_recommendation=trade_data.get('groq_recommendation', ''),
                    groq_confidence=safe_float(trade_data.get('groq_confidence', 0)),
                    score_details=trade_data.get('sniper_score', {}),
                    exit_reason="auto_detected",
                    entry_time_iso=entry_time_iso
                )
                try:
                    memory.sync_profit_history()
                except:
                    pass
            except Exception as e:
                logger.error(f"خطأ في تسجيل الصفقة في الذاكرة: {e}")

        core.record_trade_result(pnl)

        # ==================== إرسال إشعار الإغلاق ====================
        try:
            opened_at = safe_float(trade_data.get('opened_at', time.time()), time.time())
            duration_minutes = safe_int((time.time() - opened_at) / 60, 0)
        except:
            duration_minutes = 0

        send_close_notification(
            symbol=symbol,
            direction=direction,
            position_side=position_side,
            entry_price=entry_price,
            quantity=quantity,
            pnl=pnl,
            duration_minutes=duration_minutes
        )

        logger.info(f"✅ تم معالجة إغلاق: {symbol} PnL: {pnl:+.4f}")

    except Exception as e:
        logger.error(f"خطأ في record_closed_trade: {e}")
        traceback.print_exc()


def send_close_notification(symbol, direction, position_side, entry_price, quantity, pnl, duration_minutes=0):
    """
    🔥 v4.1.8: إرسال إشعار إغلاق الصفقة (مع تحويل آمن)
    """
    try:
        from telegram import Bot
        bot = Bot(token=TELEGRAM_TOKEN)

        # 🔥 v4.1.8: تحويل آمن للأنواع
        symbol = str(symbol) if symbol else "UNKNOWN"
        direction = str(direction) if direction else "UNKNOWN"
        position_side = str(position_side) if position_side else "BOTH"
        entry_price = safe_float(entry_price, 0.0)
        quantity = safe_float(quantity, 0.0)
        pnl = safe_float(pnl, 0.0)
        duration_minutes = safe_int(duration_minutes, 0)

        # ==================== تحديد الحالة ====================
        if pnl > 0.01:
            emoji = "🟢"
            title = "✅ <b>تم إغلاق الصفقة بربح</b>"
        elif pnl < -0.01:
            emoji = "🔴"
            title = "❌ <b>تم إغلاق الصفقة بخسارة</b>"
        else:
            emoji = "⚪"
            title = "⚪ <b>تم إغلاق الصفقة (تعادل)</b>"

        # ==================== حساب النسبة ====================
        position_value = entry_price * quantity
        if position_value > 0:
            pnl_percent = (pnl / position_value) * 100
        else:
            pnl_percent = 0.0

        # ==================== حساب المدة ====================
        if duration_minutes > 60:
            hours = duration_minutes // 60
            mins = duration_minutes % 60
            duration_text = f"{hours} س {mins} د"
        elif duration_minutes > 0:
            duration_text = f"{duration_minutes} دقيقة"
        else:
            duration_text = "أقل من دقيقة"

        # ==================== بناء الرسالة ====================
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
            await bot.send_message(
                chat_id=TELEGRAM_CHAT_ID,
                text=msg,
                parse_mode="HTML"
            )

        threading.Thread(target=run_async_safe, args=(send_async(),), daemon=True).start()

        logger.info(f"🔔 تم إرسال إشعار الإغلاق: {symbol} {pnl:+.4f}")

    except Exception as e:
        logger.error(f"❌ خطأ في إشعار الإغلاق: {e}")
        traceback.print_exc()


# ==================== خيط المسح التلقائي ====================

def auto_sniper_scanner():
    try:
        logger.info("🎯 [THREAD] بدء مسح القناص...")

        global _last_auto_scan

        while _auto_scan_enabled:
            try:
                current_time = time.time()

                if check_trading_pause():
                    time.sleep(60)
                    continue

                if current_time - _last_auto_scan >= AUTO_SCAN_INTERVAL:
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

        total_score = safe_float(signal.get('total_score', 0))
        if total_score < MIN_SCORE_REQUIRED:
            logger.warning(f"🛑 {symbol}: نقاط {total_score} < {MIN_SCORE_REQUIRED}")
            return False

        analysis = signal.get('analysis', {})
        volume = analysis.get('volume_analysis', {})
        vol_ratio = safe_float(volume.get('volume_5m_ratio', 0))

        if vol_ratio < MIN_VOLUME_FACTOR:
            logger.warning(f"🛑 {symbol}: حجم {vol_ratio}x < {MIN_VOLUME_FACTOR}")
            return False

        groq_rec = signal.get('groq_recommendation', '')
        groq_conf = safe_float(signal.get('groq_confidence', 0))

        if groq_rec == 'رفض' and groq_conf >= 70:
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

        logger.info(f"✅ {symbol}: اجتاز كل الفحوص - جاري التنفيذ")

        if ENABLE_MULTIPLE_TP:
            result = core.place_market_order_with_multiple_tp(symbol, direction, TRADE_USDT, LEVERAGE)
        else:
            result = core.place_market_order_with_tp_sl(symbol, direction, TRADE_USDT, LEVERAGE)

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

            strat.add_symbol_cooldown(symbol, COOLDOWN_MINUTES)

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

            send_trade_notification(signal, result)
            logger.info(f"✅ {symbol}: تم فتح الصفقة بنجاح")
            return True

        return False

    except Exception as e:
        logger.error(f"خطأ في التنفيذ: {e}")
        traceback.print_exc()
        return False


def send_trade_notification(signal, result):
    """إشعار فتح الصفقة"""
    try:
        from telegram import Bot
        bot = Bot(token=TELEGRAM_TOKEN)

        emoji = "🟢" if signal['direction'] == 'BUY' else "🔴"
        score = signal.get('score_details', {})
        verification = result.get('verification', {})

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
        'consecutive_losses': core.get_consecutive_losses()
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


# ==================== التشغيل v4.1.8 ====================

def start_scanner_threads():
    """تشغيل الخيوط"""
    logger.info("🔧 [START] بدء تشغيل الخيوط...")

    if ENABLE_REALTIME_DATA and REALTIME_AVAILABLE:
        def init_websocket_background():
            try:
                logger.info("⚡ [WS-THREAD] بدء WebSocket...")
                all_symbols = core.get_all_futures_symbols()
                if not all_symbols:
                    all_symbols = FALLBACK_SYMBOLS
                top_symbols = all_symbols[:min(REALTIME_MAX_SUBSCRIPTIONS, TOP_SYMBOLS_TO_SCAN)]
                if realtime_data.init_realtime(top_symbols):
                    logger.info(f"✅ [WS-THREAD] WebSocket مفعل ({len(top_symbols)} عملة)")
                else:
                    logger.warning("⚠️ [WS-THREAD] فشل تشغيل WebSocket")
            except Exception as e:
                logger.error(f"❌ [WS-THREAD] خطأ: {e}")

        ws_thread = threading.Thread(target=init_websocket_background, daemon=True, name="WebSocketInit")
        ws_thread.start()
        logger.info("✅ [START] تم بدء WebSocket في الخلفية")
    else:
        logger.info("ℹ️ [START] WebSocket معطل")

    try:
        scanner = threading.Thread(target=auto_sniper_scanner, daemon=True, name="SniperScanner")
        scanner.start()
        logger.info("✅ [START] تم بدء scanner thread")
    except Exception as e:
        logger.error(f"❌ [START] فشل scanner: {e}")

    try:
        monitor = threading.Thread(target=monitor_positions_loop, daemon=True, name="TrailingMonitor")
        monitor.start()
        logger.info("✅ [START] تم بدء monitor thread")
    except Exception as e:
        logger.error(f"❌ [START] فشل monitor: {e}")

    try:
        tp_sl_monitor = threading.Thread(target=monitor_tp_sl_loop, daemon=True, name="TPSLMonitor")
        tp_sl_monitor.start()
        logger.info("✅ [START] تم بدء tp_sl_monitor thread")
    except Exception as e:
        logger.error(f"❌ [START] فشل tp_sl_monitor: {e}")

    time.sleep(2)
    logger.info(f"✅ [START] عدد الخيوط النشطة: {threading.active_count()}")


def main():
    try:
        logger.info("🚀 [MAIN] بدء main_enhanced v4.1.8...")

        send_startup()
        time.sleep(3)

        logger.info("🧹 [MAIN] مزامنة ملف الصفقات...")
        try:
            tgbot.cleanup_state_file()
        except Exception as e:
            logger.warning(f"⚠️ [MAIN] فشل التنظيف: {e}")

        if MEMORY_AVAILABLE:
            try:
                memory.sync_profit_history()
                logger.info("✅ [MAIN] تم مزامنة profit_history.json")
            except Exception as e:
                logger.warning(f"⚠️ [MAIN] فشل مزامنة profit_history: {e}")

        logger.info("🎯 [MAIN] نظام القناص v4.1.8 مفعل")
        logger.info(f"⏰ [MAIN] المسح كل {AUTO_SCAN_INTERVAL // 60} دقيقة")
        logger.info(f"🎯 [MAIN] MIN_SCORE: {MIN_SCORE_REQUIRED}")
        logger.info(f"📈 [MAIN] MAX_POSITIONS: {MAX_OPEN_POSITIONS}")
        logger.info(f"🔔 [MAIN] إشعار إغلاق الصفقات: ✅")

        logger.info("🚀 [MAIN] بدء البوت...")
        tgbot.run_bot()

    except Exception as e:
        logger.error(f"❌ [MAIN] خطأ: {e}")
        traceback.print_exc()


if __name__ == "__main__":
    main()
