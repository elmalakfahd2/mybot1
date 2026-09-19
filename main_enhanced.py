# ==================================================
# 📁 ملف: main_enhanced.py - الإصدار v4.1.4
# 🔧 التعديلات v4.1.4:
#    - 🔥 التمييز بين صفقات البوت والصفقات اليدوية
#    - 🔥 البوت يتجاهل صفقاتك تماماً
#    - 🔥 MAX_POSITIONS يُحسب على صفقات البوت فقط
#    - 🔥 المراقبة تطبق فقط على صفقات البوت
# 🔧 التعديلات v4.1.2:
#    - لا تشغّل start_scanner_threads من main
# 📅 التاريخ: 2026-09-19
# ==================================================

import logging
import threading
import time
import asyncio
import json
import os
from datetime import datetime

from config import *
import bot_enhanced as tgbot
import core_functions as core

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("main_enhanced")

# 🔥 إخفاء httpx
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


# ==================== 🔥 قائمة احتياطية للرموز ====================

FALLBACK_SYMBOLS = [
    "BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT",
    "ADAUSDT", "DOGEUSDT", "AVAXUSDT", "DOTUSDT", "LINKUSDT",
    "MATICUSDT", "LTCUSDT", "ATOMUSDT", "NEARUSDT", "FILUSDT",
    "AAVEUSDT", "UNIUSDT", "ETCUSDT", "APTUSDT", "ARBUSDT"
]


# ==================== 🔥 التمييز بين صفقات البوت واليدوية ====================

def _load_bot_owned_keys():
    """قراءة (symbol, positionSide) من ملف صفقات البوت"""
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
    """
    🔥 إرجاع صفقات البوت فقط (المسجلة في open_positions.json)
    الصفقات اليدوية تُستثنى تلقائياً
    """
    try:
        bot_keys = _load_bot_owned_keys()
        if not bot_keys:
            return []
        
        all_real = core.get_open_positions()
        bot_positions = [
            p for p in all_real
            if f"{p['symbol']}_{p['positionSide']}" in bot_keys
        ]
        
        return bot_positions
    except Exception as e:
        logger.error(f"خطأ في get_bot_owned_positions: {e}")
        return []


def get_manual_positions():
    """صفقاتك اليدوية (غير مسجلة في open_positions.json)"""
    try:
        bot_keys = _load_bot_owned_keys()
        all_real = core.get_open_positions()
        manual = [
            p for p in all_real
            if f"{p['symbol']}_{p['positionSide']}" not in bot_keys
        ]
        return manual
    except Exception as e:
        logger.error(f"خطأ في get_manual_positions: {e}")
        return []


def is_bot_owned_position(symbol, position_side):
    """هل الصفقة مملوكة للبوت؟"""
    try:
        bot_keys = _load_bot_owned_keys()
        return f"{symbol}_{position_side}" in bot_keys
    except:
        return False


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

        groq_status = "✅ نشط" if GROQ_AVAILABLE else "❌ غير متاح"
        memory_status = "✅ نشط" if MEMORY_AVAILABLE else "❌ معطل"
        regime_status = "✅ نشط" if MARKET_REGIME_AVAILABLE else "❌ معطل"
        realtime_status = "✅ نشط" if REALTIME_AVAILABLE else "❌ معطل"

        msg = (
            f"🚀 <b>بوت القناص الذكي v4.1.4</b>\n\n"
            f"💰 <b>رأس المال:</b> {TRADE_USDT} USDT\n"
            f"⚡ <b>الرافعة:</b> {LEVERAGE}x\n"
            f"🎯 <b>نظام:</b> القناص + TP/SL محقق\n"
            f"⏰ <b>المسح:</b> كل {AUTO_SCAN_INTERVAL // 60} دقيقة\n\n"
            f"🧠 <b>المكونات:</b>\n"
            f"   • Groq AI: {groq_status}\n"
            f"   • ذاكرة الصفقات: {memory_status}\n"
            f"   • كشف السوق: {regime_status}\n"
            f"   • ⚡ بيانات لحظية: {realtime_status}\n"
            f"   • SL ديناميكي: {'✅' if DYNAMIC_SL_ENABLED else '❌'}\n"
            f"   • Trailing SL: {'✅' if TRAILING_SL_ENABLED else '❌'}\n"
            f"   • Breakeven بعد TP1: ✅\n"
            f"   • منع الصفقات المتعاكسة: {'✅' if ENABLE_OPPOSITE_DIRECTION_FILTER else '❌'}\n"
            f"   • 🔥 تمييز الصفقات اليدوية: ✅\n\n"
            f"📊 <b>الحالة:</b>\n"
            f"   • الأزواج: {count}\n"
            f"   • الرصيد المتاح: {available:.2f} USDT\n"
            f"   • الرصيد الإجمالي: {wallet:.2f} USDT\n"
            f"   • صفقات البوت: {len(bot_positions)}/{MAX_OPEN_POSITIONS}\n"
            f"   • صفقاتك اليدوية: {len(manual_positions)} (يتجاهلها البوت)\n\n"
            f"📈 <b>الأرباح:</b>\n"
            f"   • اليوم: {daily['daily_pnl']:.2f}\n"
            f"   • الأسبوع: {weekly['weekly_pnl']:.2f}\n"
            f"   • الشهر: {monthly['monthly_pnl']:.2f}\n\n"
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


# ==================== مراقبة TP/SL (صفقات البوت فقط) ====================

def monitor_tp_sl_loop():
    """🔍 مراقبة TP/SL لصفقات البوت فقط (تتجاهل صفقاتك اليدوية)"""
    logger.info("🔍 بدء مراقبة TP/SL (صفقات البوت فقط)...")

    global _last_tp_sl_monitor

    while _auto_scan_enabled:
        try:
            current_time = time.time()

            if current_time - _last_tp_sl_monitor >= MONITOR_TP_SL_INTERVAL:
                _last_tp_sl_monitor = current_time

                # 🔥 صفقات البوت فقط
                bot_positions = get_bot_owned_positions()
                manual_positions = get_manual_positions()

                if manual_positions:
                    logger.info(f"ℹ️ يوجد {len(manual_positions)} صفقة يدوية (يتجاهلها البوت)")

                if not bot_positions:
                    time.sleep(30)
                    continue

                for position in bot_positions:
                    symbol = position['symbol']
                    position_side = position['positionSide']

                    has_tp, has_sl, details = core.verify_tp_sl_created(symbol, position_side)

                    if not has_sl:
                        logger.warning(f"⚠️ {symbol} {position_side} بدون SL (صفقة بوت)!")
                        fixed = core.check_and_add_tp_sl_to_existing_positions()
                        if fixed > 0:
                            send_tp_sl_recovery_notification(symbol, position_side)
                            break

                    elif not has_tp:
                        logger.warning(f"⚠️ {symbol} {position_side} بدون TP (صفقة بوت)!")
                        fixed = core.check_and_add_tp_sl_to_existing_positions()
                        if fixed > 0:
                            send_tp_sl_recovery_notification(symbol, position_side)
                            break

        except Exception as e:
            logger.error(f"خطأ في المراقبة: {e}")

        time.sleep(30)


def send_tp_sl_recovery_notification(symbol, position_side):
    try:
        from telegram import Bot
        bot = Bot(token=TELEGRAM_TOKEN)

        msg = (
            f"🔧 <b>إصلاح TP/SL</b>\n\n"
            f"💰 <b>العملة:</b> {symbol}\n"
            f"📊 <b>الجانب:</b> {position_side}\n"
            f"✅ تم إعادة إنشاء الأوامر\n"
            f"⏰ {datetime.now().strftime('%H:%M:%S')}"
        )

        async def send_async():
            await bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=msg, parse_mode="HTML")

        threading.Thread(target=run_async_safe, args=(send_async(),), daemon=True).start()

    except Exception as e:
        logger.error(f"❌ خطأ: {e}")


# ==================== مراقبة Trailing SL ====================

def monitor_positions_loop():
    logger.info("📈 بدء مراقبة Trailing SL...")

    while _auto_scan_enabled:
        try:
            updated = core.monitor_trailing_sl()
            if updated > 0:
                logger.info(f"📊 تحديث {updated} صفقة")

            check_closed_trades()

        except Exception as e:
            logger.error(f"خطأ: {e}")

        time.sleep(30)


def check_closed_trades():
    try:
        if not MEMORY_AVAILABLE or not ENABLE_TRADE_MEMORY:
            return

        current_positions = core.get_open_positions()
        current_keys = set(f"{p['symbol']}_{p['positionSide']}" for p in current_positions)

        closed_keys = []
        for key in list(_open_trades_tracking.keys()):
            if key not in current_keys:
                closed_keys.append(key)

        for key in closed_keys:
            trade_data = _open_trades_tracking[key]
            try:
                record_closed_trade(trade_data)
            except Exception as e:
                logger.error(f"خطأ في تسجيل: {e}")
            del _open_trades_tracking[key]

    except Exception as e:
        logger.error(f"خطأ: {e}")


def record_closed_trade(trade_data):
    try:
        if not MEMORY_AVAILABLE:
            return

        symbol = trade_data.get('symbol')
        entry_time_iso = trade_data.get('entry_time_iso') or datetime.now().isoformat()

        client_obj = core.get_client()
        if client_obj:
            income = client_obj.futures_income_history(
                incomeType="REALIZED_PNL",
                symbol=symbol,
                limit=5
            )

            if income:
                last_income = income[-1]
                pnl = float(last_income['income'])

                memory.record_trade(
                    symbol=symbol,
                    direction=trade_data.get('direction', 'UNKNOWN'),
                    entry_price=trade_data.get('entry_price', 0),
                    exit_price=0,
                    quantity=trade_data.get('quantity', 0),
                    pnl=pnl,
                    confidence=trade_data.get('confidence', 0),
                    timeframe_alignment=trade_data.get('timeframe_alignment', 0),
                    volume_ratio=trade_data.get('volume_ratio', 0),
                    groq_recommendation=trade_data.get('groq_recommendation', ''),
                    groq_confidence=trade_data.get('groq_confidence', 0),
                    score_details=trade_data.get('sniper_score', {}),
                    exit_reason="auto_detected",
                    entry_time_iso=entry_time_iso
                )

                logger.info(f"📝 تسجيل: {symbol} PnL: {pnl:+.4f}")
                core.record_trade_result(pnl)

                try:
                    memory.sync_profit_history()
                except:
                    pass

    except Exception as e:
        logger.error(f"خطأ: {e}")


# ==================== التنفيذ ====================

def execute_sniper_trade(signal):
    try:
        symbol = signal['symbol']
        direction = signal['direction']

        logger.info(f"🚀 فحص {symbol} {direction}")

        total_score = signal.get('total_score', 0)
        if total_score < MIN_SCORE_REQUIRED:
            logger.warning(f"🛑 {symbol}: نقاط {total_score} < {MIN_SCORE_REQUIRED}")
            return False

        analysis = signal.get('analysis', {})
        volume = analysis.get('volume_analysis', {})
        vol_ratio = volume.get('volume_5m_ratio', 0)

        if vol_ratio < MIN_VOLUME_FACTOR:
            logger.warning(f"🛑 {symbol}: حجم {vol_ratio}x < {MIN_VOLUME_FACTOR}")
            return False

        groq_rec = signal.get('groq_recommendation', '')
        groq_conf = signal.get('groq_confidence', 0)

        if groq_rec == 'رفض' and groq_conf >= 70:
            logger.warning(f"🛑 {symbol}: Groq رفض ({groq_conf}%)")
            return False

        confidence = signal.get('confidence', 0)
        if confidence < MIN_CONFIDENCE_AUTO:
            logger.warning(f"🛑 {symbol}: ثقة {confidence}% < {MIN_CONFIDENCE_AUTO}%")
            return False

        # ==================== 🔥 صفقات البوت فقط ====================
        all_positions = core.get_open_positions()
        bot_positions = get_bot_owned_positions()
        manual_positions = get_manual_positions()
        
        logger.info(f"📊 صفقات البوت: {len(bot_positions)}/{MAX_OPEN_POSITIONS} | يدوية: {len(manual_positions)} | إجمالي: {len(all_positions)}")
        
        # الحد الأقصى يُحسب على صفقات البوت فقط
        if len(bot_positions) >= MAX_OPEN_POSITIONS:
            logger.warning(f"⏸️ حد أقصى للبوت: {len(bot_positions)}/{MAX_OPEN_POSITIONS}")
            return False

        # منع التكرار على صفقات البوت فقط
        if any(p['symbol'] == symbol for p in bot_positions):
            logger.warning(f"⚠️ البوت لديه صفقة على {symbol}")
            return False

        # منع الاتجاهات المتعاكسة مع صفقات البوت فقط
        if ENABLE_OPPOSITE_DIRECTION_FILTER:
            for pos in bot_positions:
                pos_amt = float(pos.get('positionAmt', 0))
                pos_direction = "BUY" if pos_amt > 0 else "SELL"

                if pos_direction != direction:
                    logger.warning(f"🛑 {symbol}: اتجاه معاكس لصفقة البوت على {pos['symbol']} ({pos_direction})")
                    return False

        # ==================== قاطع الخسارة اليومية ====================
        drawdown_ok, drawdown_reason = core.check_daily_drawdown()
        if not drawdown_ok:
            logger.error(f"🛑 {drawdown_reason}")
            return False

        # ==================== فلتر الارتباط ====================
        # 🔥 نمرر صفقات البوت فقط للارتباط (صفقاتك اليدوية لا تُحسب)
        corr_ok, corr_reason = core.check_correlation_exposure(symbol, direction, bot_positions)
        if not corr_ok:
            logger.warning(f"🛑 {symbol}: {corr_reason}")
            return False

        # ==================== فلتر السبريد والسيولة ====================
        liquidity_ok, liquidity_reason = core.check_spread_and_liquidity(symbol, TRADE_USDT)
        if not liquidity_ok:
            logger.warning(f"🛑 {symbol}: {liquidity_reason}")
            return False

        logger.info(f"✅ {symbol}: اجتاز كل الفحوص - جاري التنفيذ")

        if ENABLE_MULTIPLE_TP:
            result = core.place_market_order_with_multiple_tp(
                symbol, direction, TRADE_USDT, LEVERAGE
            )
        else:
            result = core.place_market_order_with_tp_sl(
                symbol, direction, TRADE_USDT, LEVERAGE
            )

        if result:
            if result.get('closed_due_to_failure'):
                logger.error(f"❌ {symbol} أُغلقت بسبب فشل TP/SL")
                send_failed_trade_notification(signal, result)
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
                    'confidence': signal.get('confidence', 0),
                    'timeframe_alignment': signal.get('timeframe_alignment', 0),
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
        return False


def send_failed_trade_notification(signal, result):
    try:
        from telegram import Bot
        bot = Bot(token=TELEGRAM_TOKEN)

        msg = (
            f"⚠️ <b>فشل التنفيذ</b>\n\n"
            f"💰 <b>العملة:</b> {signal['symbol']}\n"
            f"📈 <b>الاتجاه:</b> {signal['direction']}\n"
            f"❌ <b>السبب:</b> فشل إنشاء TP/SL\n"
            f"🔒 <b>الإجراء:</b> تم إغلاق الصفقة فوراً"
        )

        async def send_async():
            await bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=msg, parse_mode="HTML")

        threading.Thread(target=run_async_safe, args=(send_async(),), daemon=True).start()

    except Exception as e:
        logger.error(f"❌ خطأ: {e}")


def send_trade_notification(signal, result):
    try:
        from telegram import Bot
        bot = Bot(token=TELEGRAM_TOKEN)

        emoji = "🟢" if signal['direction'] == 'BUY' else "🔴"
        score = signal.get('score_details', {})
        verification = result.get('verification', {})

        entry_price = result['entry_price']
        position_side = result['positionSide']
        quantity = result['quantity']

        tp_results = result.get('tp_results', {})
        tp_orders = tp_results.get('tp_orders', [])
        sl_price = tp_results.get('sl_price')

        msg = (
            f"🎯 <b>تم التنفيذ بنجاح!</b>\n\n"
            f"💰 <b>العملة:</b> {signal['symbol']}\n"
            f"📈 <b>الاتجاه:</b> {emoji} {signal['direction']}\n"
            f"💵 <b>الدخول:</b> <code>{entry_price}</code>\n"
            f"⚖️ <b>الكمية:</b> <code>{quantity}</code>\n\n"
            f"📊 <b>النقاط:</b> {score.get('total', 0)}/100\n"
        )

        rt_adj = score.get('realtime_adjustment', 0)
        if rt_adj != 0:
            msg += f"   • ⚡ لحظي: {rt_adj:+d}\n"

        msg += f"\n🎯 <b>الأهداف:</b>\n"

        successful_tps = [tp for tp in tp_orders if tp.get('success')]

        for tp in successful_tps:
            tp_price = tp.get('tp_price', 0)
            tp_ratio = tp.get('ratio', 0)
            msg += f"   ✅ TP{tp['level']}: <code>{tp_price}</code> ({tp_ratio*100:.0f}%)\n"

        if sl_price:
            msg += f"   🛡️ SL: <code>{sl_price}</code>\n"

        tp_count = verification.get('details', {}).get('tp_count', 0)
        sl_count = verification.get('details', {}).get('sl_count', 0)

        msg += f"\n✅ TP: {tp_count} | SL: {sl_count}\n"
        msg += f"⏰ {datetime.now().strftime('%H:%M:%S')}"

        async def send_async():
            await bot.send_message(
                chat_id=TELEGRAM_CHAT_ID,
                text=msg,
                parse_mode="HTML"
            )

        threading.Thread(target=run_async_safe, args=(send_async(),), daemon=True).start()

    except Exception as e:
        logger.error(f"❌ خطأ في إشعار فتح الصفقة: {e}")


# ==================== المسح ====================

def auto_sniper_scanner():
    global _last_auto_scan, _auto_scan_enabled

    logger.info("🎯 بدء مسح القناص...")

    while _auto_scan_enabled:
        try:
            current_time = time.time()

            if check_trading_pause():
                time.sleep(60)
                continue

            if current_time - _last_auto_scan >= AUTO_SCAN_INTERVAL:
                _last_auto_scan = current_time

                all_positions = core.get_open_positions()
                bot_positions = get_bot_owned_positions()
                manual_positions = get_manual_positions()
                
                logger.info(f"📊 صفقات البوت: {len(bot_positions)}/{MAX_OPEN_POSITIONS} | يدوية: {len(manual_positions)} | إجمالي: {len(all_positions)}")

                if len(bot_positions) >= MAX_OPEN_POSITIONS:
                    logger.info("⏸️ حد أقصى للبوت - انتظار")
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
            logger.error(f"خطأ: {e}")
            time.sleep(60)


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

    regime_info = {}
    if MARKET_REGIME_AVAILABLE:
        try:
            regime_info = MarketRegime.get_regime()
        except:
            pass

    memory_info = {}
    if MEMORY_AVAILABLE:
        try:
            memory_info = memory.get_memory_stats()
        except:
            pass

    realtime_info = {}
    if REALTIME_AVAILABLE and ENABLE_REALTIME_DATA:
        try:
            realtime_info = realtime_data.get_realtime_status()
        except:
            pass

    return {
        'auto_scan': _auto_scan_enabled,
        'auto_trading': _auto_trading_enabled,
        'open_positions': len(bot_positions),           # 🔥 صفقات البوت فقط
        'max_positions': MAX_OPEN_POSITIONS,
        'manual_positions': len(manual_positions),      # 🔥 صفقاتك
        'total_real_positions': len(all_positions),
        'balance_available': balance_info.get('available', 0),
        'balance_wallet': balance_info.get('wallet', 0),
        'balance_pnl': balance_info.get('unrealized_pnl', 0),
        'daily_pnl': daily['daily_pnl'],
        'weekly_pnl': weekly['weekly_pnl'],
        'monthly_pnl': monthly['monthly_pnl'],
        'cooldown_symbols': len(strat.get_cooldown_status().get('active_symbols', {})),
        'strategy': 'نظام القناص v4.1.4',
        'groq_available': GROQ_AVAILABLE,
        'memory_available': MEMORY_AVAILABLE,
        'market_regime_available': MARKET_REGIME_AVAILABLE,
        'realtime_available': REALTIME_AVAILABLE,
        'realtime_info': realtime_info,
        'is_paused': is_paused,
        'pause_remaining': pause_remaining,
        'trailing_sl_status': core.get_trailing_sl_status(),
        'market_regime': regime_info,
        'memory_stats': memory_info,
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


# ==================== التشغيل ====================

def start_scanner_threads():
    """تشغيل الخيوط - تُستدعى من post_init في bot_enhanced.py"""
    logger.info("🔧 بدء تشغيل الخيوط...")

    # تهيئة WebSocket اللحظي
    if REALTIME_AVAILABLE and ENABLE_REALTIME_DATA:
        try:
            all_symbols = core.get_all_futures_symbols()

            if not all_symbols:
                logger.warning("⚠️ قائمة الرموز فارغة - استخدام القائمة الاحتياطية")
                all_symbols = FALLBACK_SYMBOLS

            top_symbols = all_symbols[:min(REALTIME_MAX_SUBSCRIPTIONS, TOP_SYMBOLS_TO_SCAN)]

            if realtime_data.init_realtime(top_symbols):
                logger.info(f"✅ WebSocket اللحظي مفعل ({len(top_symbols)} عملة)")
                logger.info("⏳ انتظار 8 ثواني لتجميع البيانات الأولية...")
                time.sleep(8)

                rt_status = realtime_data.get_realtime_status()
                logger.info(f"📊 حالة WebSocket: {rt_status}")
            else:
                logger.warning("⚠️ فشل تشغيل WebSocket اللحظي")
        except Exception as e:
            logger.error(f"❌ خطأ في تهيئة WebSocket: {e}")
            import traceback
            traceback.print_exc()

    # تشغيل خيوط المراقبة
    scanner = threading.Thread(target=auto_sniper_scanner, daemon=True)
    scanner.start()

    monitor = threading.Thread(target=monitor_positions_loop, daemon=True)
    monitor.start()

    tp_sl_monitor = threading.Thread(target=monitor_tp_sl_loop, daemon=True)
    tp_sl_monitor.start()

    logger.info("✅ تم تشغيل 3 خيوط مراقبة")


def main():
    """الدالة الرئيسية"""
    try:
        send_startup()
        time.sleep(3)

        logger.info("🧹 مزامنة ملف الصفقات مع Binance...")
        tgbot.cleanup_state_file()

        if MEMORY_AVAILABLE:
            try:
                logger.info("🔄 مزامنة profit_history.json...")
                memory.sync_profit_history()
                logger.info("✅ تم مزامنة profit_history.json")
            except Exception as e:
                logger.warning(f"⚠️ فشل مزامنة profit_history: {e}")

        logger.info("🎯 نظام القناص v4.1.4 مفعل")
        logger.info(f"⏰ المسح كل {AUTO_SCAN_INTERVAL // 60} دقيقة")
        logger.info(f"🔒 Trailing SL: {'✅' if TRAILING_SL_ENABLED else '❌'}")
        logger.info(f"🔒 Breakeven بعد TP1: ✅ ({TP_MULTIPLE_LEVELS[0]}%)")
        logger.info(f"📊 فلتر السيولة: {'✅' if ENABLE_VOLUME_FILTER else '❌'}")
        logger.info(f"🛡️ منع الصفقات المتعاكسة: {'✅' if ENABLE_OPPOSITE_DIRECTION_FILTER else '❌'}")
        logger.info(f"⚡ بيانات لحظية: {'✅' if (REALTIME_AVAILABLE and ENABLE_REALTIME_DATA) else '❌'}")
        logger.info(f"🔥 تمييز الصفقات اليدوية: ✅")
        logger.info(f"🎯 MIN_SCORE: {MIN_SCORE_REQUIRED}")
        logger.info(f"📈 MAX_POSITIONS: {MAX_OPEN_POSITIONS}")
        logger.info(f"🛑 توقف بعد {MAX_CONSECUTIVE_LOSSES} خسائر")

        tgbot.run_bot()

    except Exception as e:
        logger.error(f"خطأ: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
