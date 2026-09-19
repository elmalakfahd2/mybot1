# ==================================================
# ًں“پ ظ…ظ„ظپ: main_enhanced.py - ط§ظ„ط¥طµط¯ط§ط± v4.1.4
# ًں”§ ط§ظ„طھط¹ط¯ظٹظ„ط§طھ v4.1.4:
#    - ًں”¥ ط§ظ„طھظ…ظٹظٹط² ط¨ظٹظ† طµظپظ‚ط§طھ ط§ظ„ط¨ظˆطھ ظˆط§ظ„طµظپظ‚ط§طھ ط§ظ„ظٹط¯ظˆظٹط©
#    - ًں”¥ ط§ظ„ط¨ظˆطھ ظٹطھط¬ط§ظ‡ظ„ طµظپظ‚ط§طھظƒ طھظ…ط§ظ…ط§ظ‹
#    - ًں”¥ MAX_POSITIONS ظٹظڈط­ط³ط¨ ط¹ظ„ظ‰ طµظپظ‚ط§طھ ط§ظ„ط¨ظˆطھ ظپظ‚ط·
#    - ًں”¥ ط§ظ„ظ…ط±ط§ظ‚ط¨ط© طھط·ط¨ظ‚ ظپظ‚ط· ط¹ظ„ظ‰ طµظپظ‚ط§طھ ط§ظ„ط¨ظˆطھ
# ًں”§ ط§ظ„طھط¹ط¯ظٹظ„ط§طھ v4.1.2:
#    - ظ„ط§ طھط´ط؛ظ‘ظ„ start_scanner_threads ظ…ظ† main
# ًں“… ط§ظ„طھط§ط±ظٹط®: 2026-09-19
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

# ًں”¥ ط¥ط®ظپط§ط، httpx
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

try:
    import bot_strategies_enhanced as strat
    logger.info("âœ… طھظ… طھط­ظ…ظٹظ„ ط§ظ„ظ†ط¸ط§ظ…")
except ImportError as e:
    logger.error(f"â‌Œ ظپط´ظ„: {e}")
    raise

try:
    from groq_integration import is_groq_available
    GROQ_AVAILABLE = is_groq_available()
    logger.info(f"ًں§  Groq: {'âœ…' if GROQ_AVAILABLE else 'â‌Œ'}")
except ImportError:
    GROQ_AVAILABLE = False

try:
    import trade_memory as memory
    MEMORY_AVAILABLE = True
    logger.info("âœ… ط°ط§ظƒط±ط© ط§ظ„طµظپظ‚ط§طھ ظ…طھط§ط­ط©")
except ImportError:
    MEMORY_AVAILABLE = False
    logger.warning("âڑ ï¸ڈ ط°ط§ظƒط±ط© ط§ظ„طµظپظ‚ط§طھ ط؛ظٹط± ظ…طھط§ط­ط©")

try:
    from market_regime import MarketRegime
    MARKET_REGIME_AVAILABLE = True
    logger.info("âœ… ظƒط´ظپ ط­ط§ظ„ط© ط§ظ„ط³ظˆظ‚ ظ…طھط§ط­")
except ImportError:
    MARKET_REGIME_AVAILABLE = False
    logger.warning("âڑ ï¸ڈ ظƒط´ظپ ط­ط§ظ„ط© ط§ظ„ط³ظˆظ‚ ط؛ظٹط± ظ…طھط§ط­")

try:
    import realtime_data
    REALTIME_AVAILABLE = True
    logger.info("âœ… realtime_data ظ…طھط§ط­")
except ImportError as e:
    REALTIME_AVAILABLE = False
    realtime_data = None
    logger.warning(f"âڑ ï¸ڈ realtime_data ط؛ظٹط± ظ…طھط§ط­: {e}")


_last_auto_scan = 0
_last_tp_sl_monitor = 0
_auto_scan_enabled = True
_auto_trading_enabled = True

_open_trades_tracking = {}

STATE_FILE = "open_positions.json"


# ==================== ًں”¥ ظ‚ط§ط¦ظ…ط© ط§ط­طھظٹط§ط·ظٹط© ظ„ظ„ط±ظ…ظˆط² ====================

FALLBACK_SYMBOLS = [
    "BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT",
    "ADAUSDT", "DOGEUSDT", "AVAXUSDT", "DOTUSDT", "LINKUSDT",
    "MATICUSDT", "LTCUSDT", "ATOMUSDT", "NEARUSDT", "FILUSDT",
    "AAVEUSDT", "UNIUSDT", "ETCUSDT", "APTUSDT", "ARBUSDT"
]


# ==================== ًں”¥ ط§ظ„طھظ…ظٹظٹط² ط¨ظٹظ† طµظپظ‚ط§طھ ط§ظ„ط¨ظˆطھ ظˆط§ظ„ظٹط¯ظˆظٹط© ====================

def _load_bot_owned_keys():
    """ظ‚ط±ط§ط،ط© (symbol, positionSide) ظ…ظ† ظ…ظ„ظپ طµظپظ‚ط§طھ ط§ظ„ط¨ظˆطھ"""
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
        logger.error(f"ط®ط·ط£ ظپظٹ ظ‚ط±ط§ط،ط© {STATE_FILE}: {e}")
        return set()


def get_bot_owned_positions():
    """
    ًں”¥ ط¥ط±ط¬ط§ط¹ طµظپظ‚ط§طھ ط§ظ„ط¨ظˆطھ ظپظ‚ط· (ط§ظ„ظ…ط³ط¬ظ„ط© ظپظٹ open_positions.json)
    ط§ظ„طµظپظ‚ط§طھ ط§ظ„ظٹط¯ظˆظٹط© طھظڈط³طھط«ظ†ظ‰ طھظ„ظ‚ط§ط¦ظٹط§ظ‹
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
        logger.error(f"ط®ط·ط£ ظپظٹ get_bot_owned_positions: {e}")
        return []


def get_manual_positions():
    """طµظپظ‚ط§طھظƒ ط§ظ„ظٹط¯ظˆظٹط© (ط؛ظٹط± ظ…ط³ط¬ظ„ط© ظپظٹ open_positions.json)"""
    try:
        bot_keys = _load_bot_owned_keys()
        all_real = core.get_open_positions()
        manual = [
            p for p in all_real
            if f"{p['symbol']}_{p['positionSide']}" not in bot_keys
        ]
        return manual
    except Exception as e:
        logger.error(f"ط®ط·ط£ ظپظٹ get_manual_positions: {e}")
        return []


def is_bot_owned_position(symbol, position_side):
    """ظ‡ظ„ ط§ظ„طµظپظ‚ط© ظ…ظ…ظ„ظˆظƒط© ظ„ظ„ط¨ظˆطھطں"""
    try:
        bot_keys = _load_bot_owned_keys()
        return f"{symbol}_{position_side}" in bot_keys
    except:
        return False


# ==================== ط¯ظˆط§ظ„ ظ…ط³ط§ط¹ط¯ط© ====================

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
        logger.error(f"ط®ط·ط£ ظپظٹ ط¬ظ„ط¨ ط§ظ„ط±طµظٹط¯: {e}")
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
            logger.error(f"â‌Œ ط®ط·ط£ async: {e}")
        return None


# ==================== ط§ظ„ط¨ط¯ط، ====================

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

        groq_status = "âœ… ظ†ط´ط·" if GROQ_AVAILABLE else "â‌Œ ط؛ظٹط± ظ…طھط§ط­"
        memory_status = "âœ… ظ†ط´ط·" if MEMORY_AVAILABLE else "â‌Œ ظ…ط¹ط·ظ„"
        regime_status = "âœ… ظ†ط´ط·" if MARKET_REGIME_AVAILABLE else "â‌Œ ظ…ط¹ط·ظ„"
        realtime_status = "âœ… ظ†ط´ط·" if REALTIME_AVAILABLE else "â‌Œ ظ…ط¹ط·ظ„"

        msg = (
            f"ًںڑ€ <b>ط¨ظˆطھ ط§ظ„ظ‚ظ†ط§طµ ط§ظ„ط°ظƒظٹ v4.1.4</b>\n\n"
            f"ًں’° <b>ط±ط£ط³ ط§ظ„ظ…ط§ظ„:</b> {TRADE_USDT} USDT\n"
            f"âڑ، <b>ط§ظ„ط±ط§ظپط¹ط©:</b> {LEVERAGE}x\n"
            f"ًںژ¯ <b>ظ†ط¸ط§ظ…:</b> ط§ظ„ظ‚ظ†ط§طµ + TP/SL ظ…ط­ظ‚ظ‚\n"
            f"âڈ° <b>ط§ظ„ظ…ط³ط­:</b> ظƒظ„ {AUTO_SCAN_INTERVAL // 60} ط¯ظ‚ظٹظ‚ط©\n\n"
            f"ًں§  <b>ط§ظ„ظ…ظƒظˆظ†ط§طھ:</b>\n"
            f"   â€¢ Groq AI: {groq_status}\n"
            f"   â€¢ ط°ط§ظƒط±ط© ط§ظ„طµظپظ‚ط§طھ: {memory_status}\n"
            f"   â€¢ ظƒط´ظپ ط§ظ„ط³ظˆظ‚: {regime_status}\n"
            f"   â€¢ âڑ، ط¨ظٹط§ظ†ط§طھ ظ„ط­ط¸ظٹط©: {realtime_status}\n"
            f"   â€¢ SL ط¯ظٹظ†ط§ظ…ظٹظƒظٹ: {'âœ…' if DYNAMIC_SL_ENABLED else 'â‌Œ'}\n"
            f"   â€¢ Trailing SL: {'âœ…' if TRAILING_SL_ENABLED else 'â‌Œ'}\n"
            f"   â€¢ Breakeven ط¨ط¹ط¯ TP1: âœ…\n"
            f"   â€¢ ظ…ظ†ط¹ ط§ظ„طµظپظ‚ط§طھ ط§ظ„ظ…طھط¹ط§ظƒط³ط©: {'âœ…' if ENABLE_OPPOSITE_DIRECTION_FILTER else 'â‌Œ'}\n"
            f"   â€¢ ًں”¥ طھظ…ظٹظٹط² ط§ظ„طµظپظ‚ط§طھ ط§ظ„ظٹط¯ظˆظٹط©: âœ…\n\n"
            f"ًں“ٹ <b>ط§ظ„ط­ط§ظ„ط©:</b>\n"
            f"   â€¢ ط§ظ„ط£ط²ظˆط§ط¬: {count}\n"
            f"   â€¢ ط§ظ„ط±طµظٹط¯ ط§ظ„ظ…طھط§ط­: {available:.2f} USDT\n"
            f"   â€¢ ط§ظ„ط±طµظٹط¯ ط§ظ„ط¥ط¬ظ…ط§ظ„ظٹ: {wallet:.2f} USDT\n"
            f"   â€¢ طµظپظ‚ط§طھ ط§ظ„ط¨ظˆطھ: {len(bot_positions)}/{MAX_OPEN_POSITIONS}\n"
            f"   â€¢ طµظپظ‚ط§طھظƒ ط§ظ„ظٹط¯ظˆظٹط©: {len(manual_positions)} (ظٹطھط¬ط§ظ‡ظ„ظ‡ط§ ط§ظ„ط¨ظˆطھ)\n\n"
            f"ًں“ˆ <b>ط§ظ„ط£ط±ط¨ط§ط­:</b>\n"
            f"   â€¢ ط§ظ„ظٹظˆظ…: {daily['daily_pnl']:.2f}\n"
            f"   â€¢ ط§ظ„ط£ط³ط¨ظˆط¹: {weekly['weekly_pnl']:.2f}\n"
            f"   â€¢ ط§ظ„ط´ظ‡ط±: {monthly['monthly_pnl']:.2f}\n\n"
            f"âœ… <b>ط§ظ„ظ†ط¸ط§ظ… ط¬ط§ظ‡ط²!</b>"
        )

        async def send_async():
            await bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=msg, parse_mode="HTML")

        threading.Thread(target=run_async_safe, args=(send_async(),), daemon=True).start()

    except Exception as e:
        logger.error(f"ط®ط·ط£ ظپظٹ ط§ظ„ط¨ط¯ط،: {e}")


# ==================== ط§ظ„طھظˆظ‚ظپ ====================

def check_trading_pause():
    is_paused, remaining = core.is_trading_paused()
    if is_paused:
        logger.warning(f"âڈ¸ï¸ڈ طھظˆظ‚ظپ - {remaining} ط¯")
        return True
    return False


# ==================== ظ…ط±ط§ظ‚ط¨ط© TP/SL (طµظپظ‚ط§طھ ط§ظ„ط¨ظˆطھ ظپظ‚ط·) ====================

def monitor_tp_sl_loop():
    """ًں”چ ظ…ط±ط§ظ‚ط¨ط© TP/SL ظ„طµظپظ‚ط§طھ ط§ظ„ط¨ظˆطھ ظپظ‚ط· (طھطھط¬ط§ظ‡ظ„ طµظپظ‚ط§طھظƒ ط§ظ„ظٹط¯ظˆظٹط©)"""
    logger.info("ًں”چ ط¨ط¯ط، ظ…ط±ط§ظ‚ط¨ط© TP/SL (طµظپظ‚ط§طھ ط§ظ„ط¨ظˆطھ ظپظ‚ط·)...")

    global _last_tp_sl_monitor

    while _auto_scan_enabled:
        try:
            current_time = time.time()

            if current_time - _last_tp_sl_monitor >= MONITOR_TP_SL_INTERVAL:
                _last_tp_sl_monitor = current_time

                # ًں”¥ طµظپظ‚ط§طھ ط§ظ„ط¨ظˆطھ ظپظ‚ط·
                bot_positions = get_bot_owned_positions()
                manual_positions = get_manual_positions()

                if manual_positions:
                    logger.info(f"â„¹ï¸ڈ ظٹظˆط¬ط¯ {len(manual_positions)} طµظپظ‚ط© ظٹط¯ظˆظٹط© (ظٹطھط¬ط§ظ‡ظ„ظ‡ط§ ط§ظ„ط¨ظˆطھ)")

                if not bot_positions:
                    time.sleep(30)
                    continue

                for position in bot_positions:
                    symbol = position['symbol']
                    position_side = position['positionSide']

                    has_tp, has_sl, details = core.verify_tp_sl_created(symbol, position_side)

                    if not has_sl:
                        logger.warning(f"âڑ ï¸ڈ {symbol} {position_side} ط¨ط¯ظˆظ† SL (طµظپظ‚ط© ط¨ظˆطھ)!")
                        fixed = core.check_and_add_tp_sl_to_existing_positions()
                        if fixed > 0:
                            send_tp_sl_recovery_notification(symbol, position_side)
                            break

                    elif not has_tp:
                        logger.warning(f"âڑ ï¸ڈ {symbol} {position_side} ط¨ط¯ظˆظ† TP (طµظپظ‚ط© ط¨ظˆطھ)!")
                        fixed = core.check_and_add_tp_sl_to_existing_positions()
                        if fixed > 0:
                            send_tp_sl_recovery_notification(symbol, position_side)
                            break

        except Exception as e:
            logger.error(f"ط®ط·ط£ ظپظٹ ط§ظ„ظ…ط±ط§ظ‚ط¨ط©: {e}")

        time.sleep(30)


def send_tp_sl_recovery_notification(symbol, position_side):
    try:
        from telegram import Bot
        bot = Bot(token=TELEGRAM_TOKEN)

        msg = (
            f"ًں”§ <b>ط¥طµظ„ط§ط­ TP/SL</b>\n\n"
            f"ًں’° <b>ط§ظ„ط¹ظ…ظ„ط©:</b> {symbol}\n"
            f"ًں“ٹ <b>ط§ظ„ط¬ط§ظ†ط¨:</b> {position_side}\n"
            f"âœ… طھظ… ط¥ط¹ط§ط¯ط© ط¥ظ†ط´ط§ط، ط§ظ„ط£ظˆط§ظ…ط±\n"
            f"âڈ° {datetime.now().strftime('%H:%M:%S')}"
        )

        async def send_async():
            await bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=msg, parse_mode="HTML")

        threading.Thread(target=run_async_safe, args=(send_async(),), daemon=True).start()

    except Exception as e:
        logger.error(f"â‌Œ ط®ط·ط£: {e}")


# ==================== ظ…ط±ط§ظ‚ط¨ط© Trailing SL ====================

def monitor_positions_loop():
    logger.info("ًں“ˆ ط¨ط¯ط، ظ…ط±ط§ظ‚ط¨ط© Trailing SL...")

    while _auto_scan_enabled:
        try:
            updated = core.monitor_trailing_sl()
            if updated > 0:
                logger.info(f"ًں“ٹ طھط­ط¯ظٹط« {updated} طµظپظ‚ط©")

            check_closed_trades()

        except Exception as e:
            logger.error(f"ط®ط·ط£: {e}")

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
                logger.error(f"ط®ط·ط£ ظپظٹ طھط³ط¬ظٹظ„: {e}")
            del _open_trades_tracking[key]

    except Exception as e:
        logger.error(f"ط®ط·ط£: {e}")


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

                logger.info(f"ًں“‌ طھط³ط¬ظٹظ„: {symbol} PnL: {pnl:+.4f}")
                core.record_trade_result(pnl)

                try:
                    memory.sync_profit_history()
                except:
                    pass

    except Exception as e:
        logger.error(f"ط®ط·ط£: {e}")


# ==================== ط§ظ„طھظ†ظپظٹط° ====================

def execute_sniper_trade(signal):
    try:
        symbol = signal['symbol']
        direction = signal['direction']

        logger.info(f"ًںڑ€ ظپط­طµ {symbol} {direction}")

        total_score = signal.get('total_score', 0)
        if total_score < MIN_SCORE_REQUIRED:
            logger.warning(f"ًں›‘ {symbol}: ظ†ظ‚ط§ط· {total_score} < {MIN_SCORE_REQUIRED}")
            return False

        analysis = signal.get('analysis', {})
        volume = analysis.get('volume_analysis', {})
        vol_ratio = volume.get('volume_5m_ratio', 0)

        if vol_ratio < MIN_VOLUME_FACTOR:
            logger.warning(f"ًں›‘ {symbol}: ط­ط¬ظ… {vol_ratio}x < {MIN_VOLUME_FACTOR}")
            return False

        groq_rec = signal.get('groq_recommendation', '')
        groq_conf = signal.get('groq_confidence', 0)

        if groq_rec == 'ط±ظپط¶' and groq_conf >= 70:
            logger.warning(f"ًں›‘ {symbol}: Groq ط±ظپط¶ ({groq_conf}%)")
            return False

        confidence = signal.get('confidence', 0)
        if confidence < MIN_CONFIDENCE_AUTO:
            logger.warning(f"ًں›‘ {symbol}: ط«ظ‚ط© {confidence}% < {MIN_CONFIDENCE_AUTO}%")
            return False

        # ==================== ًں”¥ طµظپظ‚ط§طھ ط§ظ„ط¨ظˆطھ ظپظ‚ط· ====================
        all_positions = core.get_open_positions()
        bot_positions = get_bot_owned_positions()
        manual_positions = get_manual_positions()
        
        logger.info(f"ًں“ٹ طµظپظ‚ط§طھ ط§ظ„ط¨ظˆطھ: {len(bot_positions)}/{MAX_OPEN_POSITIONS} | ظٹط¯ظˆظٹط©: {len(manual_positions)} | ط¥ط¬ظ…ط§ظ„ظٹ: {len(all_positions)}")
        
        # ط§ظ„ط­ط¯ ط§ظ„ط£ظ‚طµظ‰ ظٹظڈط­ط³ط¨ ط¹ظ„ظ‰ طµظپظ‚ط§طھ ط§ظ„ط¨ظˆطھ ظپظ‚ط·
        if len(bot_positions) >= MAX_OPEN_POSITIONS:
            logger.warning(f"âڈ¸ï¸ڈ ط­ط¯ ط£ظ‚طµظ‰ ظ„ظ„ط¨ظˆطھ: {len(bot_positions)}/{MAX_OPEN_POSITIONS}")
            return False

        # ظ…ظ†ط¹ ط§ظ„طھظƒط±ط§ط± ط¹ظ„ظ‰ طµظپظ‚ط§طھ ط§ظ„ط¨ظˆطھ ظپظ‚ط·
        if any(p['symbol'] == symbol for p in bot_positions):
            logger.warning(f"âڑ ï¸ڈ ط§ظ„ط¨ظˆطھ ظ„ط¯ظٹظ‡ طµظپظ‚ط© ط¹ظ„ظ‰ {symbol}")
            return False

        # ظ…ظ†ط¹ ط§ظ„ط§طھط¬ط§ظ‡ط§طھ ط§ظ„ظ…طھط¹ط§ظƒط³ط© ظ…ط¹ طµظپظ‚ط§طھ ط§ظ„ط¨ظˆطھ ظپظ‚ط·
        if ENABLE_OPPOSITE_DIRECTION_FILTER:
            for pos in bot_positions:
                pos_amt = float(pos.get('positionAmt', 0))
                pos_direction = "BUY" if pos_amt > 0 else "SELL"

                if pos_direction != direction:
                    logger.warning(f"ًں›‘ {symbol}: ط§طھط¬ط§ظ‡ ظ…ط¹ط§ظƒط³ ظ„طµظپظ‚ط© ط§ظ„ط¨ظˆطھ ط¹ظ„ظ‰ {pos['symbol']} ({pos_direction})")
                    return False

        # ==================== ظ‚ط§ط·ط¹ ط§ظ„ط®ط³ط§ط±ط© ط§ظ„ظٹظˆظ…ظٹط© ====================
        drawdown_ok, drawdown_reason = core.check_daily_drawdown()
        if not drawdown_ok:
            logger.error(f"ًں›‘ {drawdown_reason}")
            return False

        # ==================== ظپظ„طھط± ط§ظ„ط§ط±طھط¨ط§ط· ====================
        # ًں”¥ ظ†ظ…ط±ط± طµظپظ‚ط§طھ ط§ظ„ط¨ظˆطھ ظپظ‚ط· ظ„ظ„ط§ط±طھط¨ط§ط· (طµظپظ‚ط§طھظƒ ط§ظ„ظٹط¯ظˆظٹط© ظ„ط§ طھظڈط­ط³ط¨)
        corr_ok, corr_reason = core.check_correlation_exposure(symbol, direction, bot_positions)
        if not corr_ok:
            logger.warning(f"ًں›‘ {symbol}: {corr_reason}")
            return False

        # ==================== ظپظ„طھط± ط§ظ„ط³ط¨ط±ظٹط¯ ظˆط§ظ„ط³ظٹظˆظ„ط© ====================
        liquidity_ok, liquidity_reason = core.check_spread_and_liquidity(symbol, TRADE_USDT)
        if not liquidity_ok:
            logger.warning(f"ًں›‘ {symbol}: {liquidity_reason}")
            return False

        logger.info(f"âœ… {symbol}: ط§ط¬طھط§ط² ظƒظ„ ط§ظ„ظپط­ظˆطµ - ط¬ط§ط±ظٹ ط§ظ„طھظ†ظپظٹط°")

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
                logger.error(f"â‌Œ {symbol} ط£ظڈط؛ظ„ظ‚طھ ط¨ط³ط¨ط¨ ظپط´ظ„ TP/SL")
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
            logger.info(f"âœ… {symbol}: طھظ… ظپطھط­ ط§ظ„طµظپظ‚ط© ط¨ظ†ط¬ط§ط­")
            return True

        return False

    except Exception as e:
        logger.error(f"ط®ط·ط£ ظپظٹ ط§ظ„طھظ†ظپظٹط°: {e}")
        return False


def send_failed_trade_notification(signal, result):
    try:
        from telegram import Bot
        bot = Bot(token=TELEGRAM_TOKEN)

        msg = (
            f"âڑ ï¸ڈ <b>ظپط´ظ„ ط§ظ„طھظ†ظپظٹط°</b>\n\n"
            f"ًں’° <b>ط§ظ„ط¹ظ…ظ„ط©:</b> {signal['symbol']}\n"
            f"ًں“ˆ <b>ط§ظ„ط§طھط¬ط§ظ‡:</b> {signal['direction']}\n"
            f"â‌Œ <b>ط§ظ„ط³ط¨ط¨:</b> ظپط´ظ„ ط¥ظ†ط´ط§ط، TP/SL\n"
            f"ًں”’ <b>ط§ظ„ط¥ط¬ط±ط§ط،:</b> طھظ… ط¥ط؛ظ„ط§ظ‚ ط§ظ„طµظپظ‚ط© ظپظˆط±ط§ظ‹"
        )

        async def send_async():
            await bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=msg, parse_mode="HTML")

        threading.Thread(target=run_async_safe, args=(send_async(),), daemon=True).start()

    except Exception as e:
        logger.error(f"â‌Œ ط®ط·ط£: {e}")


def send_trade_notification(signal, result):
    try:
        from telegram import Bot
        bot = Bot(token=TELEGRAM_TOKEN)

        emoji = "ًںں¢" if signal['direction'] == 'BUY' else "ًں”´"
        score = signal.get('score_details', {})
        verification = result.get('verification', {})

        entry_price = result['entry_price']
        position_side = result['positionSide']
        quantity = result['quantity']

        tp_results = result.get('tp_results', {})
        tp_orders = tp_results.get('tp_orders', [])
        sl_price = tp_results.get('sl_price')

        msg = (
            f"ًںژ¯ <b>طھظ… ط§ظ„طھظ†ظپظٹط° ط¨ظ†ط¬ط§ط­!</b>\n\n"
            f"ًں’° <b>ط§ظ„ط¹ظ…ظ„ط©:</b> {signal['symbol']}\n"
            f"ًں“ˆ <b>ط§ظ„ط§طھط¬ط§ظ‡:</b> {emoji} {signal['direction']}\n"
            f"ًں’µ <b>ط§ظ„ط¯ط®ظˆظ„:</b> <code>{entry_price}</code>\n"
            f"âڑ–ï¸ڈ <b>ط§ظ„ظƒظ…ظٹط©:</b> <code>{quantity}</code>\n\n"
            f"ًں“ٹ <b>ط§ظ„ظ†ظ‚ط§ط·:</b> {score.get('total', 0)}/100\n"
        )

        rt_adj = score.get('realtime_adjustment', 0)
        if rt_adj != 0:
            msg += f"   â€¢ âڑ، ظ„ط­ط¸ظٹ: {rt_adj:+d}\n"

        msg += f"\nًںژ¯ <b>ط§ظ„ط£ظ‡ط¯ط§ظپ:</b>\n"

        successful_tps = [tp for tp in tp_orders if tp.get('success')]

        for tp in successful_tps:
            tp_price = tp.get('tp_price', 0)
            tp_ratio = tp.get('ratio', 0)
            msg += f"   âœ… TP{tp['level']}: <code>{tp_price}</code> ({tp_ratio*100:.0f}%)\n"

        if sl_price:
            msg += f"   ًں›،ï¸ڈ SL: <code>{sl_price}</code>\n"

        tp_count = verification.get('details', {}).get('tp_count', 0)
        sl_count = verification.get('details', {}).get('sl_count', 0)

        msg += f"\nâœ… TP: {tp_count} | SL: {sl_count}\n"
        msg += f"âڈ° {datetime.now().strftime('%H:%M:%S')}"

        async def send_async():
            await bot.send_message(
                chat_id=TELEGRAM_CHAT_ID,
                text=msg,
                parse_mode="HTML"
            )

        threading.Thread(target=run_async_safe, args=(send_async(),), daemon=True).start()

    except Exception as e:
        logger.error(f"â‌Œ ط®ط·ط£ ظپظٹ ط¥ط´ط¹ط§ط± ظپطھط­ ط§ظ„طµظپظ‚ط©: {e}")


# ==================== ط§ظ„ظ…ط³ط­ ====================

def auto_sniper_scanner():
    global _last_auto_scan, _auto_scan_enabled

    logger.info("ًںژ¯ ط¨ط¯ط، ظ…ط³ط­ ط§ظ„ظ‚ظ†ط§طµ...")

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
                
                logger.info(f"ًں“ٹ طµظپظ‚ط§طھ ط§ظ„ط¨ظˆطھ: {len(bot_positions)}/{MAX_OPEN_POSITIONS} | ظٹط¯ظˆظٹط©: {len(manual_positions)} | ط¥ط¬ظ…ط§ظ„ظٹ: {len(all_positions)}")

                if len(bot_positions) >= MAX_OPEN_POSITIONS:
                    logger.info("âڈ¸ï¸ڈ ط­ط¯ ط£ظ‚طµظ‰ ظ„ظ„ط¨ظˆطھ - ط§ظ†طھط¸ط§ط±")
                    time.sleep(30)
                    continue

                if MARKET_REGIME_AVAILABLE:
                    try:
                        regime = MarketRegime.get_regime()
                        logger.info(f"ًں“ٹ ط§ظ„ط³ظˆظ‚: {regime.get('regime_ar')} - {regime.get('recommendation')}")
                    except:
                        pass

                logger.info("ًںژ¯ ظ…ط³ط­...")

                signals = strat.scan_sniper_signals()

                if signals:
                    logger.info(f"ًںژ¯ {len(signals)} ط¥ط´ط§ط±ط©")

                    for signal in signals:
                        bot_positions = get_bot_owned_positions()
                        if len(bot_positions) >= MAX_OPEN_POSITIONS:
                            break

                        if execute_sniper_trade(signal):
                            logger.info(f"âœ… {signal['symbol']}")
                            time.sleep(2)
                else:
                    logger.info("ًں”چ ظ„ط§ طھظˆط¬ط¯ ط¥ط´ط§ط±ط§طھ")

                logger.info(f"âڈ° ط§ظ„ط¯ظˆط±ط© ط§ظ„طھط§ظ„ظٹط©: {AUTO_SCAN_INTERVAL // 60} ط¯ظ‚ظٹظ‚ط©")

            time.sleep(30)

        except Exception as e:
            logger.error(f"ط®ط·ط£: {e}")
            time.sleep(60)


# ==================== ط§ظ„ط­ط§ظ„ط© ====================

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
        'open_positions': len(bot_positions),           # ًں”¥ طµظپظ‚ط§طھ ط§ظ„ط¨ظˆطھ ظپظ‚ط·
        'max_positions': MAX_OPEN_POSITIONS,
        'manual_positions': len(manual_positions),      # ًں”¥ طµظپظ‚ط§طھظƒ
        'total_real_positions': len(all_positions),
        'balance_available': balance_info.get('available', 0),
        'balance_wallet': balance_info.get('wallet', 0),
        'balance_pnl': balance_info.get('unrealized_pnl', 0),
        'daily_pnl': daily['daily_pnl'],
        'weekly_pnl': weekly['weekly_pnl'],
        'monthly_pnl': monthly['monthly_pnl'],
        'cooldown_symbols': len(strat.get_cooldown_status().get('active_symbols', {})),
        'strategy': 'ظ†ط¸ط§ظ… ط§ظ„ظ‚ظ†ط§طµ v4.1.4',
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
    status = "ظ…ظپط¹ظ„" if _auto_trading_enabled else "ظ…ط¹ط·ظ„"
    return f"âœ… <b>ط§ظ„طھظ†ظپظٹط° ط§ظ„طھظ„ظ‚ط§ط¦ظٹ: {status}</b>"


def toggle_auto_scan():
    global _auto_scan_enabled
    _auto_scan_enabled = not _auto_scan_enabled
    status = "ظ…ظپط¹ظ„" if _auto_scan_enabled else "ظ…ط¹ط·ظ„"
    return f"âœ… <b>ط§ظ„ظ…ط³ط­ ط§ظ„طھظ„ظ‚ط§ط¦ظٹ: {status}</b>"


# ==================== ط§ظ„طھط´ط؛ظٹظ„ ====================

def start_scanner_threads():
    """طھط´ط؛ظٹظ„ ط§ظ„ط®ظٹظˆط· - طھظڈط³طھط¯ط¹ظ‰ ظ…ظ† post_init ظپظٹ bot_enhanced.py"""
    logger.info("ًں”§ ط¨ط¯ط، طھط´ط؛ظٹظ„ ط§ظ„ط®ظٹظˆط·...")

    # طھظ‡ظٹط¦ط© WebSocket ط§ظ„ظ„ط­ط¸ظٹ
    if REALTIME_AVAILABLE and ENABLE_REALTIME_DATA:
        try:
            all_symbols = core.get_all_futures_symbols()

            if not all_symbols:
                logger.warning("âڑ ï¸ڈ ظ‚ط§ط¦ظ…ط© ط§ظ„ط±ظ…ظˆط² ظپط§ط±ط؛ط© - ط§ط³طھط®ط¯ط§ظ… ط§ظ„ظ‚ط§ط¦ظ…ط© ط§ظ„ط§ط­طھظٹط§ط·ظٹط©")
                all_symbols = FALLBACK_SYMBOLS

            top_symbols = all_symbols[:min(REALTIME_MAX_SUBSCRIPTIONS, TOP_SYMBOLS_TO_SCAN)]

            if realtime_data.init_realtime(top_symbols):
                logger.info(f"âœ… WebSocket ط§ظ„ظ„ط­ط¸ظٹ ظ…ظپط¹ظ„ ({len(top_symbols)} ط¹ظ…ظ„ط©)")
                logger.info("âڈ³ ط§ظ†طھط¸ط§ط± 8 ط«ظˆط§ظ†ظٹ ظ„طھط¬ظ…ظٹط¹ ط§ظ„ط¨ظٹط§ظ†ط§طھ ط§ظ„ط£ظˆظ„ظٹط©...")
                time.sleep(8)

                rt_status = realtime_data.get_realtime_status()
                logger.info(f"ًں“ٹ ط­ط§ظ„ط© WebSocket: {rt_status}")
            else:
                logger.warning("âڑ ï¸ڈ ظپط´ظ„ طھط´ط؛ظٹظ„ WebSocket ط§ظ„ظ„ط­ط¸ظٹ")
        except Exception as e:
            logger.error(f"â‌Œ ط®ط·ط£ ظپظٹ طھظ‡ظٹط¦ط© WebSocket: {e}")
            import traceback
            traceback.print_exc()

    # طھط´ط؛ظٹظ„ ط®ظٹظˆط· ط§ظ„ظ…ط±ط§ظ‚ط¨ط©
    scanner = threading.Thread(target=auto_sniper_scanner, daemon=True)
    scanner.start()

    monitor = threading.Thread(target=monitor_positions_loop, daemon=True)
    monitor.start()

    tp_sl_monitor = threading.Thread(target=monitor_tp_sl_loop, daemon=True)
    tp_sl_monitor.start()

    logger.info("âœ… طھظ… طھط´ط؛ظٹظ„ 3 ط®ظٹظˆط· ظ…ط±ط§ظ‚ط¨ط©")


def main():
    """ط§ظ„ط¯ط§ظ„ط© ط§ظ„ط±ط¦ظٹط³ظٹط©"""
    try:
        send_startup()
        time.sleep(3)

        logger.info("ًں§¹ ظ…ط²ط§ظ…ظ†ط© ظ…ظ„ظپ ط§ظ„طµظپظ‚ط§طھ ظ…ط¹ Binance...")
        tgbot.cleanup_state_file()

        if MEMORY_AVAILABLE:
            try:
                logger.info("ًں”„ ظ…ط²ط§ظ…ظ†ط© profit_history.json...")
                memory.sync_profit_history()
                logger.info("âœ… طھظ… ظ…ط²ط§ظ…ظ†ط© profit_history.json")
            except Exception as e:
                logger.warning(f"âڑ ï¸ڈ ظپط´ظ„ ظ…ط²ط§ظ…ظ†ط© profit_history: {e}")

        logger.info("ًںژ¯ ظ†ط¸ط§ظ… ط§ظ„ظ‚ظ†ط§طµ v4.1.4 ظ…ظپط¹ظ„")
        logger.info(f"âڈ° ط§ظ„ظ…ط³ط­ ظƒظ„ {AUTO_SCAN_INTERVAL // 60} ط¯ظ‚ظٹظ‚ط©")
        logger.info(f"ًں”’ Trailing SL: {'âœ…' if TRAILING_SL_ENABLED else 'â‌Œ'}")
        logger.info(f"ًں”’ Breakeven ط¨ط¹ط¯ TP1: âœ… ({TP_MULTIPLE_LEVELS[0]}%)")
        logger.info(f"ًں“ٹ ظپظ„طھط± ط§ظ„ط³ظٹظˆظ„ط©: {'âœ…' if ENABLE_VOLUME_FILTER else 'â‌Œ'}")
        logger.info(f"ًں›،ï¸ڈ ظ…ظ†ط¹ ط§ظ„طµظپظ‚ط§طھ ط§ظ„ظ…طھط¹ط§ظƒط³ط©: {'âœ…' if ENABLE_OPPOSITE_DIRECTION_FILTER else 'â‌Œ'}")
        logger.info(f"âڑ، ط¨ظٹط§ظ†ط§طھ ظ„ط­ط¸ظٹط©: {'âœ…' if (REALTIME_AVAILABLE and ENABLE_REALTIME_DATA) else 'â‌Œ'}")
        logger.info(f"ًں”¥ طھظ…ظٹظٹط² ط§ظ„طµظپظ‚ط§طھ ط§ظ„ظٹط¯ظˆظٹط©: âœ…")
        logger.info(f"ًںژ¯ MIN_SCORE: {MIN_SCORE_REQUIRED}")
        logger.info(f"ًں“ˆ MAX_POSITIONS: {MAX_OPEN_POSITIONS}")
        logger.info(f"ًں›‘ طھظˆظ‚ظپ ط¨ط¹ط¯ {MAX_CONSECUTIVE_LOSSES} ط®ط³ط§ط¦ط±")

        tgbot.run_bot()

    except Exception as e:
        logger.error(f"ط®ط·ط£: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
