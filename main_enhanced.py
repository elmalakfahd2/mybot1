# ==================================================
# 📁 ملف: main_enhanced.py - الإصدار v5.4
# 🔧 التعديلات v5.4:
#    - 🔥 Health Check Server (لـ Railway)
#    - 🔥 تقليل الخيوط من 8 إلى 5
#    - 🔥 دمج TP/SL في Monitor
#    - 🔥 تنظيف الذاكرة gc.collect()
#    - 🔥 لا إعادة تشغيل تلقائي
# 📅 التاريخ: 2026-09-25
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

        backup_status = "✅ مفعل" if ENABLE_AUTO_BACKUP and GITHUB_TOKEN else "❌ معطل"

        memory_trades = 0
        if MEMORY_AVAILABLE:
            try:
                mem_stats = memory.get_memory_stats()
                memory_trades = mem_stats.get('total_trades', 0)
            except:
                pass

        msg = (
            f"🚀 <b>بوت القناص الذكي v5.4</b>\n\n"
            f"💰 <b>رأس المال:</b> {TRADE_USDT} USDT\n"
            f"⚡ <b>الرافعة:</b> {LEVERAGE}x\n"
            f"⏰ <b>المسح:</b> كل {AUTO_SCAN_INTERVAL // 60} دقيقة\n\n"
            f"💾 <b>GitHub Backup:</b> {backup_status}\n"
            f"📊 <b>الصفقات في الذاكرة:</b> {memory_trades}\n"
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


# ==================== 🔥 خيط المراقبة الشاملة (v5.4) ====================

def monitor_positions_loop():
    """
    🔥 v5.4: مراقبة شاملة (Trailing SL + TP/SL + الصفقات المغلقة)
    تم دمج 3 خيوط في خيط واحد لتقليل الاستهلاك
    """
    try:
        logger.info("📈 [THREAD] بدء المراقبة الشاملة...")

        global _last_tp_sl_monitor

        while _auto_scan_enabled:
            try:
                # ==================== 1. Trailing SL ====================
                updated = core.monitor_trailing_sl()
                if updated > 0:
                    logger.info(f"📊 تحديث Trailing: {updated} صفقة")

                # ==================== 2. TP/SL Check (كل دقيقة) ====================
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
                                logger.warning(f"⚠️ {symbol} ناقص TP/SL")
                                core.check_and_add_tp_sl_to_existing_positions()
                                break

                # ==================== 3. الصفقات المغلقة ====================
                check_closed_trades()

                # 🔥 v5.4: تنظيف دوري للذاكرة
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
    try:
        symbol = trade_data.get('symbol')
        direction = trade_data.get('direction', 'UNKNOWN')
        entry_price = safe_float(trade_data.get('entry_price', 0))
        quantity = safe_float(trade_data.get('quantity', 0))
        position_side = trade_data.get('positionSide', 'LONG')
        entry_time_iso = trade_data.get('entry_time_iso') or datetime.now().isoformat()

        logger.info(f"🔔 معالجة إغلاق: {symbol} {position_side}")

        # جلب PnL
        pnl = 0.0
        try:
            client_obj = core.get_client()
            if client_obj:
                income = client_obj.futures_income_history(
                    incomeType="REALIZED_PNL", symbol=symbol, limit=5
                )
                if income:
                    raw_income = income[-1].get('income', 0)
                    pnl = safe_float(raw_income, 0.0)
                    logger.info(f"💰 PnL: {pnl:+.4f}")
        except Exception as e:
            logger.warning(f"⚠️ فشل جلب PnL: {e}")

        # تسجيل
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
                logger.error(f"خطأ في التسجيل: {e}")

        core.record_trade_result(pnl)

        # إشعار الإغلاق
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

                    # 🔥 v5.4: تنظيف الذاكرة بعد كل مسح
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


# ==================== 🔥 التشغيل v5.4 ====================

def start_scanner_threads():
    """
    🔥 v5.4: تقليل الخيوط + Health Check Server
    """
    logger.info("=" * 60)
    logger.info("🔧 [START] بدء تشغيل الخيوط v5.4...")
    logger.info("=" * 60)

    # ==================== 1. Health Check Server ====================
    try:
        import health_server
        if health_server.run_in_background():
            logger.info("✅ [START] Health Check Server")
        else:
            logger.warning("⚠️ [START] فشل Health Check")
    except Exception as e:
        logger.error(f"❌ [START] خطأ Health Check: {e}")

    # ==================== 2. Scanner (رئيسي) ====================
    try:
        scanner = threading.Thread(target=auto_sniper_scanner, daemon=True, name="SniperScanner")
        scanner.start()
        logger.info("✅ [START] SniperScanner")
    except Exception as e:
        logger.error(f"❌ [START] فشل scanner: {e}")

    # ==================== 3. Monitor (Trailing + TP/SL + Closed) ====================
    try:
        monitor = threading.Thread(target=monitor_positions_loop, daemon=True, name="Monitor")
        monitor.start()
        logger.info("✅ [START] Monitor (Trailing + TP/SL)")
    except Exception as e:
        logger.error(f"❌ [START] فشل monitor: {e}")

    # ==================== 4. Smart Scheduler (التعلم) ====================
    if SCHEDULER_AVAILABLE and ENABLE_AUTO_LEARNING:
        try:
            if smart_scheduler.start_scheduler():
                logger.info("✅ [START] Smart Scheduler")
            else:
                logger.warning("⚠️ [START] فشل scheduler")
        except Exception as e:
            logger.error(f"❌ [START] فشل scheduler: {e}")
    else:
        logger.info("ℹ️ [START] التعلم التلقائي معطل")

    # ==================== 5. GitHub Backup ====================
    if MEMORY_AVAILABLE and ENABLE_AUTO_BACKUP:
        try:
            if memory.start_auto_backup():
                logger.info("✅ [START] GitHub Backup")
            else:
                logger.warning("⚠️ [START] فشل Backup")
        except Exception as e:
            logger.error(f"❌ [START] فشل Backup: {e}")
    else:
        logger.info("ℹ️ [START] GitHub Backup معطل")

    time.sleep(2)
    logger.info(f"✅ [START] عدد الخيوط: {threading.active_count()}")
    logger.info("=" * 60)


def main():
    try:
        logger.info("=" * 60)
        logger.info("🚀 [MAIN] بدء main_enhanced v5.4...")
        logger.info("=" * 60)

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

            try:
                mem_stats = memory.get_memory_stats()
                logger.info(f"📊 [MAIN] عدد الصفقات: {mem_stats.get('total_trades', 0)}")
                logger.info(f"📊 [MAIN] نسبة النجاح: {mem_stats.get('win_rate', 0):.1f}%")
            except:
                pass

        logger.info("=" * 60)
        logger.info("🎯 [MAIN] نظام القناص v5.4 مفعل")
        logger.info("=" * 60)
        logger.info(f"⏰ [MAIN] المسح كل {AUTO_SCAN_INTERVAL // 60} دقيقة")
        logger.info(f"🎯 [MAIN] MIN_SCORE: {MIN_SCORE_REQUIRED}")
        logger.info(f"📈 [MAIN] MAX_POSITIONS: {MAX_OPEN_POSITIONS}")
        logger.info(f"💰 [MAIN] TRADE_USDT: {TRADE_USDT}")
        logger.info(f"⚡ [MAIN] LEVERAGE: {LEVERAGE}x")
        logger.info(f"🔔 [MAIN] إشعار إغلاق: ✅")
        logger.info(f"🧠 [MAIN] التعلم التلقائي: {'✅' if ENABLE_AUTO_LEARNING else '❌'}")
        logger.info(f"📊 [MAIN] التقارير اليومية: {'✅' if ENABLE_DAILY_REPORT else '❌'}")
        logger.info(f"🛡️ [MAIN] الحماية الذاتية: {'✅' if AUTO_PROTECTION_ENABLED else '❌'}")
        logger.info(f"💾 [MAIN] GitHub Backup: {'✅' if ENABLE_AUTO_BACKUP else '❌'}")
        logger.info(f"🏥 [MAIN] Health Check: ✅")
        logger.info("=" * 60)

        logger.info("🚀 [MAIN] بدء البوت...")
        tgbot.run_bot()

    except Exception as e:
        logger.error(f"❌ [MAIN] خطأ: {e}")
        traceback.print_exc()


if __name__ == "__main__":
    main()