# ==================================================
# 📁 ملف: core_functions.py - الإصدار v4.2.0
# 🔧 التعديلات v4.2.0:
#    - 🔥 تنظيف الأوامر اليتيمة (cleanup_orphan_algo_orders)
#    - 🔥 تسجيل algo_ids لكل صفقة
#    - 🔥 close_position_safe يحذف أوامر الصفقة فقط
#    - 🔥 حماية الصفقات اليدوية
# 📅 التاريخ: 2026-09-26
# ==================================================

import logging
import threading
import time
import hmac
import hashlib
import requests
import json
import os
from urllib.parse import urlencode
from datetime import datetime, timedelta
from binance.client import Client
from binance.exceptions import BinanceAPIException, BinanceRequestException
from config import *

logger = logging.getLogger("core")
_client = None

# ==================== 🔥 Cache للرموز ====================
_symbols_cache = None
_symbols_cache_time = 0
_SYMBOLS_CACHE_DURATION = 600  # 10 دقائق

# ==================== 🔥 Algo Order API ====================
CONDITIONAL_ORDER_TYPES = {
    'STOP_MARKET', 'TAKE_PROFIT_MARKET', 'STOP', 'TAKE_PROFIT', 'TRAILING_STOP_MARKET'
}

_FUTURES_BASE_URL = "https://testnet.binancefuture.com" if 'USE_TESTNET' in globals() and USE_TESTNET \
    else "https://fapi.binance.com"


def _algo_signed_request(method, path, params=None):
    """طلب موقّع مباشرة لـ Algo Order API"""
    params = dict(params or {})
    params['timestamp'] = int(time.time() * 1000)
    params.setdefault('recvWindow', 10000)

    query_string = urlencode(params)
    signature = hmac.new(
        BINANCE_API_SECRET.encode('utf-8'),
        query_string.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()
    params['signature'] = signature

    headers = {'X-MBX-APIKEY': BINANCE_API_KEY}
    url = f"{_FUTURES_BASE_URL}{path}"

    resp = requests.request(method, url, params=params, headers=headers, timeout=REQUEST_TIMEOUT)
    try:
        data = resp.json()
    except Exception:
        data = {'code': resp.status_code, 'msg': resp.text}

    return resp.status_code, data


def create_algo_order(order_params, max_retries=None):
    """إنشاء أمر شرطي عبر Algo Order API"""
    if max_retries is None:
        max_retries = TP_SL_MAX_RETRIES

    params = dict(order_params)
    params['algoType'] = 'CONDITIONAL'

    if 'stopPrice' in params:
        params['triggerPrice'] = params.pop('stopPrice')

    if params.get('closePosition') in ('true', True):
        params.pop('quantity', None)

    for attempt in range(max_retries):
        try:
            status_code, data = _algo_signed_request('post', '/fapi/v1/algoOrder', params)

            if status_code == 200 and 'algoId' in data:
                logger.info(f"✅ أمر Algo ناجح (محاولة {attempt+1}) - algoId={data['algoId']}")
                data['orderId'] = data['algoId']
                return data

            code = data.get('code')
            msg = data.get('msg', str(data))
            logger.warning(f"⚠️ Algo محاولة {attempt+1}/{max_retries} فشلت: {code} - {msg}")

            if code in [-1111, -1102, -2019]:
                logger.error("❌ خطأ دائم - إيقاف المحاولات")
                return None

            # -2021: السعر تجاوز مستوى الـ STOP قبل إنشاء الأمر
            # نحرك الـ trigger قليلاً بعيداً عن السعر الحالي حتى لا ينفذ فوراً.
            if code == -2021 and params.get('type') == 'STOP_MARKET' and 'triggerPrice' in params:
                try:
                    old_trigger = float(params['triggerPrice'])
                    if params.get('side') == 'BUY':      # إغلاق SHORT: الوقف فوق السعر
                        new_trigger = old_trigger * 1.002
                    else:                                # إغلاق LONG: الوقف تحت السعر
                        new_trigger = old_trigger * 0.998
                    params['triggerPrice'] = round(new_trigger, 8)
                    logger.info(f"🔧 تعديل SL بعد -2021: {old_trigger} → {params['triggerPrice']}")
                except Exception as adjust_err:
                    logger.debug(f"تعذر تعديل SL بعد -2021: {adjust_err}")

        except Exception as e:
            logger.warning(f"⚠️ Algo محاولة {attempt+1}/{max_retries} فشلت: {e}")

        if attempt < max_retries - 1:
            time.sleep(TP_SL_RETRY_DELAY_SECONDS)

    logger.error(f"❌ فشل جميع محاولات Algo Order ({max_retries})")
    return None


def cancel_algo_order(symbol, algo_id):
    """إلغاء أمر شرطي"""
    try:
        status_code, data = _algo_signed_request(
            'delete', '/fapi/v1/algoOrder', {'algoId': algo_id}
        )
        return status_code == 200
    except Exception as e:
        logger.warning(f"⚠️ فشل إلغاء Algo Order {algo_id}: {e}")
        return False


def get_open_algo_orders(symbol=None):
    """الأوامر الشرطية المفتوحة"""
    try:
        params = {'symbol': symbol} if symbol else {}
        status_code, data = _algo_signed_request('get', '/fapi/v1/openAlgoOrders', params)
        if status_code == 200 and isinstance(data, list):
            for o in data:
                o['orderId'] = o.get('algoId')
                o['type'] = o.get('orderType', o.get('algoType'))
            return data
        return []
    except Exception as e:
        logger.error(f"خطأ في جلب Algo Orders المفتوحة: {e}")
        return []


_connection_retries = 0
_MAX_RETRIES = 3

try:
    USE_TESTNET
except NameError:
    USE_TESTNET = False

try:
    ENABLE_SL
except NameError:
    ENABLE_SL = True

try:
    ENABLE_ORDER_BOOK_FILTER
except NameError:
    ENABLE_ORDER_BOOK_FILTER = True
try:
    MAX_SPREAD_PERCENT
except NameError:
    MAX_SPREAD_PERCENT = 0.20
try:
    MIN_DEPTH_MULTIPLIER
except NameError:
    MIN_DEPTH_MULTIPLIER = 5
try:
    ENABLE_CORRELATION_FILTER
except NameError:
    ENABLE_CORRELATION_FILTER = True
try:
    MAX_CORRELATION
except NameError:
    MAX_CORRELATION = 0.75
try:
    ENABLE_DAILY_DRAWDOWN_LIMIT
except NameError:
    ENABLE_DAILY_DRAWDOWN_LIMIT = True
try:
    DAILY_MAX_LOSS_PERCENT
except NameError:
    DAILY_MAX_LOSS_PERCENT = 8.0
try:
    BREAKEVEN_OFFSET_PERCENT
except NameError:
    BREAKEVEN_OFFSET_PERCENT = 0.1
try:
    ENABLE_ORPHAN_CLEANUP
except NameError:
    ENABLE_ORPHAN_CLEANUP = True


# ==================== تهيئة Binance ====================

def create_binance_client():
    global _client, _connection_retries

    try:
        print("🚀 محاولة الاتصال بـ Binance Futures...")

        if USE_TESTNET:
            client_obj = Client(
                BINANCE_API_KEY, BINANCE_API_SECRET,
                testnet=True,
                requests_params={'timeout': 15, 'verify': True}
            )
        else:
            client_obj = Client(
                BINANCE_API_KEY, BINANCE_API_SECRET,
                requests_params={'timeout': 15, 'verify': True}
            )

        try:
            client_obj.futures_ping()
            server_time = client_obj.futures_time()
            if server_time:
                print(f"✅ اتصال ناجح - {server_time['serverTime']}")
                _client = client_obj
                _connection_retries = 0
                return client_obj
        except Exception as e:
            print(f"❌ خطأ اختبار: {e}")
            raise

    except BinanceAPIException as e:
        _connection_retries += 1
        print(f"❌ خطأ API ({_connection_retries}/{_MAX_RETRIES}): {e}")

        if e.code == -1003:
            print("🛑 حظر بسبب الوزن - انتظار 60 ثانية...")
            time.sleep(60)
    except Exception as e:
        _connection_retries += 1
        print(f"❌ خطأ ({_connection_retries}/{_MAX_RETRIES}): {e}")

    if _connection_retries < _MAX_RETRIES:
        print("🔄 إعادة المحاولة...")
        time.sleep(5)
        return create_binance_client()

    return None


def ensure_client_connection():
    global _client
    if _client is not None:
        try:
            _client.futures_ping()
            return True
        except:
            _client = None
    if _client is None:
        _client = create_binance_client()
    return _client is not None


def get_client():
    if not ensure_client_connection():
        return None
    return _client


client = get_client()


# ==================== الحساب ====================

def get_account_mode():
    try:
        client_obj = get_client()
        if not client_obj:
            return "HEDGE"
        account = client_obj.futures_account()
        return "HEDGE" if account.get('multiAssetsMode', False) else "ONE_WAY"
    except:
        return "HEDGE"


def get_open_positions():
    try:
        client_obj = get_client()
        if not client_obj:
            return []
        acct = client_obj.futures_account()
        positions = []
        for p in acct["positions"]:
            try:
                amt = float(p["positionAmt"])
                if abs(amt) > 0:
                    position_side = p.get("positionSide", "BOTH")
                    if position_side == "BOTH":
                        position_side = "LONG" if amt > 0 else "SHORT"
                    positions.append({
                        "symbol": p["symbol"],
                        "positionAmt": p["positionAmt"],
                        "entryPrice": p["entryPrice"],
                        "unrealizedProfit": p["unrealizedProfit"],
                        "positionSide": position_side,
                        "leverage": p["leverage"],
                        "isolated": p["isolated"]
                    })
            except:
                continue
        return positions
    except Exception as e:
        logger.error(f"خطأ: {e}")
        return []


def get_open_positions_strict():
    """
    🔥 v5.7: مثل get_open_positions لكن يرجع None عند فشل الاتصال
    (حتى لا يُعتبر فشل الـ API إغلاقاً لكل الصفقات).
    """
    try:
        client_obj = get_client()
        if not client_obj:
            return None
        acct = client_obj.futures_account()
        if not acct or "positions" not in acct:
            return None
        positions = []
        for p in acct["positions"]:
            try:
                amt = float(p["positionAmt"])
                if abs(amt) > 0:
                    position_side = p.get("positionSide", "BOTH")
                    if position_side == "BOTH":
                        position_side = "LONG" if amt > 0 else "SHORT"
                    positions.append({
                        "symbol": p["symbol"],
                        "positionAmt": p["positionAmt"],
                        "entryPrice": p["entryPrice"],
                        "unrealizedProfit": p["unrealizedProfit"],
                        "positionSide": position_side,
                        "leverage": p["leverage"],
                        "isolated": p["isolated"]
                    })
            except Exception:
                continue
        return positions
    except Exception as e:
        logger.error(f"خطأ get_open_positions_strict: {e}")
        return None


def get_open_orders(symbol=None):
    try:
        client_obj = get_client()
        if not client_obj:
            return []
        if symbol:
            return client_obj.futures_get_open_orders(symbol=symbol)
        return client_obj.futures_get_open_orders()
    except Exception as e:
        logger.error(f"خطأ: {e}")
        return []


# ==================== 🔥 قراءة صفقات البوت ====================

def _get_bot_owned_symbols_and_algo_ids():
    """
    🔥 v4.2: قراءة صفقات البوت + قائمة algoIds
    Returns: (set of "SYMBOL_SIDE", set of algoIds)
    """
    try:
        state_file = "open_positions.json"
        if not os.path.exists(state_file):
            return set(), set()

        with open(state_file, "r", encoding="utf-8") as f:
            data = json.load(f)

        bot_keys = set()
        bot_algo_ids = set()

        for p in data:
            sym = p.get('symbol')
            side = p.get('positionSide')
            if sym and side:
                bot_keys.add(f"{sym}_{side}")

            # 🔥 جمع algo_ids إن وُجدت
            algo_orders = p.get('algo_orders', {})
            for key, algo_id in algo_orders.items():
                if algo_id:
                    bot_algo_ids.add(int(algo_id))

        return bot_keys, bot_algo_ids
    except Exception as e:
        logger.error(f"خطأ في قراءة open_positions: {e}")
        return set(), set()


# ==================== get_all_futures_symbols ====================

def get_all_futures_symbols():
    """Cache لمدة 10 دقائق"""
    global _symbols_cache, _symbols_cache_time

    try:
        current_time = time.time()

        if _symbols_cache is not None and (current_time - _symbols_cache_time) < _SYMBOLS_CACHE_DURATION:
            logger.info(f"📊 فلتر السيولة (Cache): {len(_symbols_cache)} عملة")
            return _symbols_cache

        client_obj = get_client()
        if not client_obj:
            if _symbols_cache:
                logger.warning("⚠️ فشل الاتصال - استخدام Cache قديم")
                return _symbols_cache
            return []

        info = client_obj.futures_exchange_info()

        syms = [
            s["symbol"] for s in info["symbols"]
            if s["status"] == "TRADING"
            and s["quoteAsset"] == "USDT"
            and s["contractType"] == "PERPETUAL"
        ]

        if ENABLE_VOLUME_FILTER:
            try:
                all_tickers = client_obj.futures_ticker()
                volume_map = {
                    t['symbol']: float(t.get('quoteVolume', 0))
                    for t in all_tickers
                }
                filtered_syms = [
                    sym for sym in syms
                    if volume_map.get(sym, 0) >= MIN_VOLUME_24H_USDT
                ]
            except Exception as e:
                logger.error(f"⚠️ فشل فلتر الحجم: {e}")
                filtered_syms = syms
        else:
            filtered_syms = syms

        logger.info(f"📊 فلتر السيولة: {len(filtered_syms)}/{len(syms)} عملة")

        _symbols_cache = filtered_syms
        _symbols_cache_time = current_time

        return filtered_syms

    except BinanceAPIException as e:
        if e.code == -1003:
            logger.error("🛑 حظر بسبب الوزن - استخدام Cache إن وُجد")
            if _symbols_cache:
                return _symbols_cache
        logger.error(f"خطأ: {e}")
        return _symbols_cache if _symbols_cache else []
    except Exception as e:
        logger.error(f"خطأ: {e}")
        return _symbols_cache if _symbols_cache else []


def get_price(symbol):
    try:
        client_obj = get_client()
        if not client_obj:
            return None
        ticker = client_obj.futures_symbol_ticker(symbol=symbol)
        return float(ticker["price"])
    except:
        return None


def get_klines(symbol, interval, limit=200):
    try:
        client_obj = get_client()
        if not client_obj:
            return []
        return client_obj.futures_klines(symbol=symbol, interval=interval, limit=limit)
    except:
        return []


def get_futures_balance(asset="USDT"):
    try:
        client_obj = get_client()
        if not client_obj:
            return 0.0
        bal = client_obj.futures_account_balance()
        for b in bal:
            if b["asset"] == asset:
                return float(b["balance"])
        return 0.0
    except:
        return 0.0


def get_symbol_info(symbol):
    try:
        client_obj = get_client()
        if not client_obj:
            return None
        info = client_obj.futures_exchange_info()
        for s in info["symbols"]:
            if s["symbol"] == symbol:
                return s
        return None
    except:
        return None


def get_price_precision(symbol):
    try:
        symbol_info = get_symbol_info(symbol)
        if symbol_info:
            for f in symbol_info["filters"]:
                if f["filterType"] == "PRICE_FILTER":
                    tick = f["tickSize"].rstrip('0')
                    if '.' in tick:
                        return len(tick.split('.')[-1])
                    return 0
        return 2
    except:
        return 2


def _round_quantity(symbol, qty):
    try:
        symbol_info = get_symbol_info(symbol)
        if symbol_info:
            for f in symbol_info["filters"]:
                if f["filterType"] == "LOT_SIZE":
                    step_size = float(f["stepSize"])
                    precision = len(f["stepSize"].rstrip('0').split('.')[-1])
                    qty = float(int(qty / step_size) * step_size)
                    return round(qty, precision)
        return round(qty, 3)
    except:
        return round(qty, 3)


def format_price_for_binance(symbol, price):
    try:
        if price is None:
            return None
        precision = get_price_precision(symbol)
        return round(price, precision)
    except:
        return round(price, 2) if price else None


# ==================== تحليل دفتر الأوامر ====================

def get_order_book_analysis(symbol, depth_levels=20):
    try:
        client_obj = get_client()
        if not client_obj:
            return None

        ob = client_obj.futures_order_book(symbol=symbol, limit=depth_levels)
        bids = ob.get('bids', [])
        asks = ob.get('asks', [])

        if not bids or not asks:
            return None

        best_bid = float(bids[0][0])
        best_ask = float(asks[0][0])
        mid_price = (best_bid + best_ask) / 2

        spread_percent = ((best_ask - best_bid) / mid_price) * 100 if mid_price > 0 else 999

        bid_depth_usdt = sum(float(p) * float(q) for p, q in bids)
        ask_depth_usdt = sum(float(p) * float(q) for p, q in asks)
        total_depth = bid_depth_usdt + ask_depth_usdt

        imbalance = ((bid_depth_usdt - ask_depth_usdt) / total_depth) if total_depth > 0 else 0

        return {
            'spread_percent': round(spread_percent, 4),
            'bid_depth_usdt': round(bid_depth_usdt, 2),
            'ask_depth_usdt': round(ask_depth_usdt, 2),
            'total_depth_usdt': round(total_depth, 2),
            'imbalance': round(imbalance, 3),
            'best_bid': best_bid,
            'best_ask': best_ask
        }
    except Exception as e:
        logger.error(f"خطأ في تحليل دفتر الأوامر لـ {symbol}: {e}")
        return None


def check_spread_and_liquidity(symbol, trade_usdt):
    try:
        if not ENABLE_ORDER_BOOK_FILTER:
            return True, "فلتر دفتر الأوامر معطل"

        ob = get_order_book_analysis(symbol)
        if not ob:
            return False, "تعذر جلب دفتر الأوامر"

        if ob['spread_percent'] > MAX_SPREAD_PERCENT:
            return False, f"سبريد واسع: {ob['spread_percent']:.3f}% (الحد: {MAX_SPREAD_PERCENT}%)"

        min_required_depth = trade_usdt * LEVERAGE * MIN_DEPTH_MULTIPLIER
        if ob['total_depth_usdt'] < min_required_depth:
            return False, f"سيولة ضعيفة: {ob['total_depth_usdt']:.0f} USDT"

        return True, "سيولة مقبولة"
    except Exception as e:
        logger.error(f"خطأ فحص السيولة: {e}")
        return True, "خطأ - تم التجاوز"


# ==================== Funding Rate + Open Interest ====================

def get_funding_rate(symbol):
    try:
        client_obj = get_client()
        if not client_obj:
            return None
        data = client_obj.futures_mark_price(symbol=symbol)
        return float(data.get('lastFundingRate', 0)) * 100
    except Exception as e:
        logger.error(f"خطأ funding rate لـ {symbol}: {e}")
        return None


def get_open_interest_trend(symbol, period='5m', limit=6):
    try:
        client_obj = get_client()
        if not client_obj:
            return None
        hist = client_obj.futures_open_interest_hist(symbol=symbol, period=period, limit=limit)
        if not hist or len(hist) < 2:
            return None
        oldest = float(hist[0]['sumOpenInterest'])
        newest = float(hist[-1]['sumOpenInterest'])
        if oldest == 0:
            return None
        return round(((newest - oldest) / oldest) * 100, 3)
    except Exception as e:
        logger.error(f"خطأ Open Interest لـ {symbol}: {e}")
        return None


# ==================== الارتباط ====================

def get_price_correlation(symbol_a, symbol_b, interval='15m', limit=50):
    try:
        klines_a = get_klines(symbol_a, interval, limit=limit)
        klines_b = get_klines(symbol_b, interval, limit=limit)
        if len(klines_a) < 10 or len(klines_b) < 10:
            return 0.0

        closes_a = [float(k[4]) for k in klines_a]
        closes_b = [float(k[4]) for k in klines_b]
        n = min(len(closes_a), len(closes_b))
        closes_a, closes_b = closes_a[-n:], closes_b[-n:]

        returns_a = [(closes_a[i] - closes_a[i-1]) / closes_a[i-1] for i in range(1, n) if closes_a[i-1] != 0]
        returns_b = [(closes_b[i] - closes_b[i-1]) / closes_b[i-1] for i in range(1, n) if closes_b[i-1] != 0]
        m = min(len(returns_a), len(returns_b))
        if m < 5:
            return 0.0
        returns_a, returns_b = returns_a[-m:], returns_b[-m:]

        mean_a = sum(returns_a) / m
        mean_b = sum(returns_b) / m
        cov = sum((returns_a[i] - mean_a) * (returns_b[i] - mean_b) for i in range(m))
        std_a = sum((x - mean_a) ** 2 for x in returns_a) ** 0.5
        std_b = sum((x - mean_b) ** 2 for x in returns_b) ** 0.5

        if std_a == 0 or std_b == 0:
            return 0.0
        return round(cov / (std_a * std_b), 3)
    except Exception as e:
        logger.error(f"خطأ حساب الارتباط: {e}")
        return 0.0


def check_correlation_exposure(symbol, direction, open_positions):
    try:
        if not ENABLE_CORRELATION_FILTER or not open_positions:
            return True, "فلتر الارتباط معطل"

        for pos in open_positions:
            other_symbol = pos.get('symbol')
            other_side = "BUY" if float(pos.get('positionAmt', 0)) > 0 else "SELL"
            if other_symbol == symbol:
                continue
            if other_side != direction:
                continue

            corr = get_price_correlation(symbol, other_symbol)
            if abs(corr) >= MAX_CORRELATION:
                return False, f"ارتباط عالٍ ({corr:.2f}) مع {other_symbol}"

        return True, "التعرض ضمن الحدود"
    except Exception as e:
        logger.error(f"خطأ فحص الارتباط: {e}")
        return True, "خطأ - تم التجاوز"


# ==================== قاطع دائرة الخسارة اليومية ====================

def check_daily_drawdown():
    """
    🔥 v5.7: حد الخسارة اليومية من دخل Binance الحقيقي (وليس من الذاكرة).
    عند تجاوزه يتوقف البوت حتى منتصف الليل.
    """
    global _pause_until, _pause_reason
    try:
        if not _cfg_val('ENABLE_DAILY_DRAWDOWN_LIMIT', False):
            return True, "معطل"

        today = get_today_net_income()
        if today is None:
            return True, "تعذر جلب البيانات"

        if today >= 0:
            return True, f"ربح اليوم: {today:.2f}"

        loss = abs(today)
        limit_usdt = float(_cfg_val('DAILY_MAX_LOSS_USDT', 0) or 0)
        limit_pct = float(_cfg_val('DAILY_MAX_LOSS_PERCENT', 0) or 0)

        breached = False
        reason = ""

        if limit_usdt > 0 and loss >= limit_usdt:
            breached = True
            reason = f"خسارة اليوم {loss:.2f}$ ≥ الحد {limit_usdt:.2f}$"

        if not breached and limit_pct > 0:
            try:
                client_obj = get_client()
                wallet = 0.0
                if client_obj:
                    for a in client_obj.futures_account_balance():
                        if a.get('asset') == 'USDT':
                            wallet = float(a.get('balance', 0))
                            break
                if wallet > 0 and (loss / wallet * 100) >= limit_pct:
                    breached = True
                    reason = f"خسارة اليوم {loss / wallet * 100:.1f}% ≥ الحد {limit_pct:.1f}%"
            except Exception:
                pass

        if breached:
            with _risk_lock:
                until = _midnight_after_now()
                if until > _pause_until:
                    _pause_until = until
                    _pause_reason = "حد الخسارة اليومية"
            _save_risk_state()
            logger.error(f"🛑 {reason} - إيقاف حتى منتصف الليل")
            return False, f"🛑 {reason}"

        return True, f"خسارة اليوم: {loss:.2f}$"

    except Exception as e:
        logger.error(f"خطأ فحص الخسارة اليومية: {e}")
        return True, "خطأ - تم التجاوز"


# ==================== التحقق من TP/SL ====================

def verify_tp_sl_created(symbol, position_side):
    try:
        open_orders = list(get_open_orders(symbol) or []) + list(get_open_algo_orders(symbol) or [])

        if not open_orders:
            return False, False, {
                'total_orders': 0,
                'tp_count': 0,
                'sl_count': 0
            }

        tp_orders = [o for o in open_orders if o.get('type') in ('TAKE_PROFIT_MARKET', 'TAKE_PROFIT')]
        sl_orders = [o for o in open_orders if o.get('type') in ('STOP_MARKET', 'STOP')]

        has_tp = len(tp_orders) > 0
        has_sl = len(sl_orders) > 0

        details = {
            'total_orders': len(open_orders),
            'tp_count': len(tp_orders),
            'sl_count': len(sl_orders),
            'tp_orders': tp_orders,
            'sl_orders': sl_orders
        }

        return has_tp, has_sl, details

    except Exception as e:
        logger.error(f"خطأ في التحقق من TP/SL: {e}")
        return False, False, {}


def create_order_with_retry(order_params, max_retries=None):
    if order_params.get('type') in CONDITIONAL_ORDER_TYPES:
        return create_algo_order(order_params, max_retries=max_retries)

    if max_retries is None:
        max_retries = TP_SL_MAX_RETRIES

    client_obj = get_client()
    if not client_obj:
        return None

    for attempt in range(max_retries):
        try:
            order = client_obj.futures_create_order(**order_params)
            logger.info(f"✅ أمر ناجح (محاولة {attempt+1})")
            return order
        except BinanceAPIException as e:
            logger.warning(f"⚠️ محاولة {attempt+1}/{max_retries} فشلت: {e.code} - {e.message}")

            if e.code in [-1111, -1102, -2019]:
                logger.error(f"❌ خطأ دائم")
                return None

            if attempt < max_retries - 1:
                time.sleep(TP_SL_RETRY_DELAY_SECONDS)
        except Exception as e:
            logger.warning(f"⚠️ محاولة {attempt+1}/{max_retries} فشلت: {e}")
            if attempt < max_retries - 1:
                time.sleep(TP_SL_RETRY_DELAY_SECONDS)

    logger.error(f"❌ فشل جميع المحاولات ({max_retries})")
    return None


# ==================== 🔥 إغلاق آمن ====================

def _cleanup_symbol_orders(symbol, algo_ids=None):
    """
    🔥 v4.2: حذف الأوامر
    لو algo_ids موجودة → يحذف فقط هذه الأوامر
    لو None → يحذف كل أوامر العملة (استخدام حذر!)
    """
    try:
        client_obj = get_client()
        if not client_obj:
            return 0

        cancelled = 0

        # 🔥 حالة 1: حذف algo_ids محددة فقط
        if algo_ids:
            for algo_id in algo_ids:
                if cancel_algo_order(symbol, algo_id):
                    cancelled += 1
                    logger.info(f"🗑️ إلغاء Algo محدد: {algo_id}")
            return cancelled

        # 🔥 حالة 2: حذف كل الأوامر (fallback)
        try:
            open_orders = client_obj.futures_get_open_orders(symbol=symbol)
            for order in open_orders:
                try:
                    client_obj.futures_cancel_order(symbol=symbol, orderId=order['orderId'])
                    cancelled += 1
                except:
                    pass
        except:
            pass

        try:
            algo_orders = get_open_algo_orders(symbol)
            for order in algo_orders:
                algo_id = order.get('algoId') or order.get('orderId')
                if algo_id and cancel_algo_order(symbol, algo_id):
                    cancelled += 1
        except:
            pass

        return cancelled

    except Exception as e:
        logger.error(f"خطأ تنظيف {symbol}: {e}")
        return 0


def close_position_safe(symbol, position_side, algo_ids=None, error_ref=None):
    """
    🔥 إغلاق آمن مع سبب فشل واضح.
    - إذا algo_ids محددة → يحذفها
    - ثم يحاول الإغلاق بعدة طرق: reduceOnly → عادي → closePosition
    """
    def _fail(msg):
        logger.error(f"❌ فشل إغلاق {symbol} {position_side}: {msg}")
        if error_ref is not None:
            try:
                error_ref.append(str(msg))
            except Exception:
                pass
        return False

    try:
        client_obj = get_client()
        if not client_obj:
            return _fail("لا يوجد اتصال بـ Binance")

        positions = get_open_positions_strict()
        if positions is None:
            return _fail("فشل جلب الصفقات من Binance")
        position = None
        for pos in positions:
            if pos["symbol"] == symbol and pos["positionSide"] == position_side:
                position = pos
                break

        if not position:
            if algo_ids:
                _cleanup_symbol_orders(symbol, algo_ids)
            return _fail("الصفقة غير موجودة الآن أو أُغلقت مسبقاً")

        quantity = abs(float(position["positionAmt"]))
        if quantity <= 0:
            if algo_ids:
                _cleanup_symbol_orders(symbol, algo_ids)
            return _fail("كمية الصفقة صفر")

        close_side = "SELL" if position_side == "LONG" else "BUY"

        # 1) تنظيف أوامر الصفقة
        try:
            if algo_ids:
                _cleanup_symbol_orders(symbol, algo_ids)
            else:
                _cleanup_symbol_orders(symbol)
        except Exception as cleanup_err:
            logger.warning(f"⚠️ تنظيف أوامر {symbol} قبل الإغلاق: {cleanup_err}")

        # 2) الإغلاق: محاولات متدرجة
        try:
            client_obj.futures_create_order(
                symbol=symbol,
                side=close_side,
                type="MARKET",
                quantity=quantity,
                positionSide=position_side,
                reduceOnly="true"
            )
            logger.info(f"✅ إغلاق reduceOnly: {symbol} {position_side}")
            remove_trailing_sl_tracking(symbol, position_side)
            return True
        except BinanceAPIException as e:
            logger.warning(f"⚠️ إغلاق reduceOnly فشل ({e.code}): {e.message}")

        # 3) بدون reduceOnly
        try:
            client_obj.futures_create_order(
                symbol=symbol,
                side=close_side,
                type="MARKET",
                quantity=quantity,
                positionSide=position_side
            )
            logger.info(f"✅ إغلاق عادي: {symbol} {position_side}")
            remove_trailing_sl_tracking(symbol, position_side)
            return True
        except BinanceAPIException as e:
            logger.warning(f"⚠️ الإغلاق العادي فشل ({e.code}): {e.message}")

        # 4) closePosition كحل أخير
        try:
            close_kwargs = {
                "symbol": symbol,
                "side": close_side,
                "type": "MARKET",
                "closePosition": "true"
            }
            if position_side in ("LONG", "SHORT"):
                close_kwargs["positionSide"] = position_side
            client_obj.futures_create_order(**close_kwargs)
            logger.info(f"✅ إغلاق closePosition: {symbol} {position_side}")
            remove_trailing_sl_tracking(symbol, position_side)
            return True
        except Exception as e:
            return _fail(f"فشلت كل محاولات الإغلاق: {e}")

    except Exception as e:
        return _fail(f"استثناء غير متوقع: {e}")


def close_all_positions():
    try:
        positions = get_open_positions()
        if not positions:
            return 0, 0.0

        closed = 0
        total_pnl = 0.0

        for position in positions:
            try:
                symbol = position.get("symbol")
                position_side = position.get("positionSide")
                pnl = float(position.get("unrealizedProfit", 0))

                if close_position_safe(symbol, position_side):
                    closed += 1
                    total_pnl += pnl
                    record_trade_result(pnl)
                    time.sleep(0.3)
            except:
                continue

        return closed, total_pnl
    except:
        return 0, 0.0


def close_profitable_positions():
    try:
        positions = get_open_positions()
        profitable = [p for p in positions if float(p.get("unrealizedProfit", 0)) > 0]

        if not profitable:
            return 0, 0.0

        closed = 0
        total_profit = 0.0

        for position in profitable:
            try:
                symbol = position.get("symbol")
                position_side = position.get("positionSide")
                profit = float(position.get("unrealizedProfit", 0))

                if close_position_safe(symbol, position_side):
                    closed += 1
                    total_profit += profit
                    time.sleep(0.3)
            except:
                continue

        return closed, total_profit
    except:
        return 0, 0.0


def close_losing_positions():
    try:
        positions = get_open_positions()
        losing = [p for p in positions if float(p.get("unrealizedProfit", 0)) < 0]

        if not losing:
            return 0, 0.0

        closed = 0
        total_loss = 0.0

        for position in losing:
            try:
                symbol = position.get("symbol")
                position_side = position.get("positionSide")
                loss = float(position.get("unrealizedProfit", 0))

                if close_position_safe(symbol, position_side):
                    closed += 1
                    total_loss += loss
                    record_trade_result(loss)
                    time.sleep(0.3)
            except:
                continue

        return closed, total_loss
    except:
        return 0, 0.0


# ==================== 🔥 تنظيف الأوامر اليتيمة ====================

def cleanup_orphan_algo_orders():
    """
    🔥 v4.2: حذف الأوامر اليتيمة
    - الأوامر لعملات مغلقة (لا صفقة مفتوحة)
    - يتجاهل أوامر الصفقات اليدوية (عبر bot_owned)
    """
    try:
        if not ENABLE_ORPHAN_CLEANUP:
            return 0

        client_obj = get_client()
        if not client_obj:
            return 0

        # 1. جلب الصفقات المفتوحة
        open_positions = get_open_positions()
        open_keys = {f"{p['symbol']}_{p['positionSide']}" for p in open_positions}
        open_symbols = {p['symbol'] for p in open_positions}

        # 2. قراءة صفقات البوت + algo_ids
        bot_keys, bot_algo_ids = _get_bot_owned_symbols_and_algo_ids()

        # 3. جلب كل الأوامر المشروطة
        all_algo_orders = get_open_algo_orders()
        if not all_algo_orders:
            return 0

        cancelled_count = 0

        # 4. حذف الأوامر اليتيمة
        for order in all_algo_orders:
            try:
                order_symbol = order.get('symbol', '')
                order_position_side = order.get('positionSide', '')
                algo_id = order.get('algoId') or order.get('orderId')

                if not algo_id:
                    continue

                # 🔥 حالة A: العملة ليس لها صفقة مفتوحة
                if order_symbol not in open_symbols:
                    if cancel_algo_order(order_symbol, algo_id):
                        cancelled_count += 1
                        logger.info(f"🗑️ يتيم (لا صفقة): {order_symbol} #{algo_id}")
                    continue

                # 🔥 حالة B: العملة لها صفقة، لكن الـ positionSide مختلف
                pos_key = f"{order_symbol}_{order_position_side}"
                if pos_key not in open_keys:
                    if cancel_algo_order(order_symbol, algo_id):
                        cancelled_count += 1
                        logger.info(f"🗑️ يتيم (side): {pos_key} #{algo_id}")
                    continue

                # 🔥 حالة C: العملة لها صفقة، لكن الأمر مش من صفقات البوت
                # (لمنع حذف أوامر الصفقات اليدوية)
                if bot_algo_ids and int(algo_id) not in bot_algo_ids:
                    if pos_key not in bot_keys:
                        # صفقة يدوية → لا نحذف
                        logger.info(f"🛡️ أمر صفقة يدوية (محفوظ): {pos_key} #{algo_id}")
                        continue

            except Exception as e:
                logger.warning(f"⚠️ خطأ في تنظيف أمر: {e}")
                continue

        if cancelled_count > 0:
            logger.info(f"✅ تم حذف {cancelled_count} أمر يتيم")

        return cancelled_count

    except Exception as e:
        logger.error(f"خطأ في cleanup_orphan_algo_orders: {e}")
        return 0


def cleanup_orphan_orders():
    """🔥 اسم بديل يستخدمه main_enhanced — يرجع عدد الأوامر المحذوفة"""
    try:
        return int(cleanup_orphan_algo_orders() or 0)
    except Exception as e:
        logger.error(f"خطأ في cleanup_orphan_orders: {e}")
        return 0


# ==================== Trailing SL ====================

_trailing_sl_positions = {}
_consecutive_losses = 0
_pause_until = 0
_last_loss_ts = 0
_pause_reason = ""
_risk_lock = threading.Lock()
RISK_STATE_FILE = "risk_state.json"
RISK_FIREBASE_DOC = "risk_state"


def setup_trailing_sl(symbol, position_side, entry_price, quantity, sl_price=None,
                      breakeven_trigger=None, trailing_trigger=None, trailing_distance=None):
    try:
        key = f"{symbol}_{position_side}"

        if sl_price is None:
            if position_side == "LONG":
                sl_price = entry_price * (1 - SL_PERCENT / 100)
            else:
                sl_price = entry_price * (1 + SL_PERCENT / 100)

        _trailing_sl_positions[key] = {
            'symbol': symbol,
            'position_side': position_side,
            'entry_price': entry_price,
            'quantity': quantity,
            'initial_sl': sl_price,
            'current_sl': sl_price,
            'highest_price': entry_price,
            'lowest_price': entry_price,
            'breakeven_set': False,
            'trailing_active': False,
            'breakeven_trigger': breakeven_trigger if breakeven_trigger is not None else BREAKEVEN_TRIGGER,
            'trailing_trigger': trailing_trigger if trailing_trigger is not None else TRAILING_SL_TRIGGER,
            'trailing_distance': trailing_distance if trailing_distance is not None else TRAILING_SL_DISTANCE,
            'created_at': time.time()
        }

        logger.info(f"✅ Trailing SL: {symbol} {position_side}")
        return True
    except:
        return False


def update_sl_order(symbol, position_side, old_sl, new_sl, quantity):
    try:
        client_obj = get_client()
        if not client_obj:
            return False

        algo_orders = get_open_algo_orders(symbol)
        for order in algo_orders:
            if order.get('type') == 'STOP_MARKET':
                cancel_algo_order(symbol, order.get('algoId', order.get('orderId')))

        close_side = "SELL" if position_side == "LONG" else "BUY"
        formatted_sl = format_price_for_binance(symbol, new_sl)

        if not formatted_sl:
            return False

        order_params = {
            'symbol': symbol,
            'side': close_side,
            'type': 'STOP_MARKET',
            'quantity': quantity,
            'stopPrice': formatted_sl,
            'positionSide': position_side,
            'timeInForce': 'GTC'
        }

        result = create_order_with_retry(order_params)

        if result:
            logger.info(f"✅ SL محدث: {formatted_sl}")
            return True

        logger.error(f"❌ فشل تحديث SL")
        return False

    except Exception as e:
        logger.error(f"خطأ: {e}")
        return False


def update_trailing_sl(symbol, position_side, current_price):
    try:
        if not TRAILING_SL_ENABLED:
            return False

        key = f"{symbol}_{position_side}"
        if key not in _trailing_sl_positions:
            return False

        data = _trailing_sl_positions[key]
        entry_price = data['entry_price']
        quantity = data['quantity']

        # بعد TP جزئي تتغير الكمية؛ نستخدم الكمية الحالية من Binance لتحديث الوقف
        try:
            positions_now = get_open_positions()
            for pos in positions_now or []:
                if pos.get("symbol") == symbol and pos.get("positionSide") == position_side:
                    live_qty = abs(float(pos.get("positionAmt", 0) or 0))
                    if live_qty > 0:
                        quantity = live_qty
                    break
        except Exception:
            pass

        if position_side == "LONG":
            profit_percent = ((current_price - entry_price) / entry_price) * 100
        else:
            profit_percent = ((entry_price - current_price) / entry_price) * 100

        updated = False

        if position_side == "LONG":
            if current_price > data['highest_price']:
                data['highest_price'] = current_price
        else:
            if current_price < data['lowest_price']:
                data['lowest_price'] = current_price

        tp1_level = TP_MULTIPLE_LEVELS[0]
        be_trigger = data.get('breakeven_trigger', BREAKEVEN_TRIGGER)
        trail_trigger = data.get('trailing_trigger', TRAILING_SL_TRIGGER)
        trail_distance = data.get('trailing_distance', TRAILING_SL_DISTANCE)

        if not data['breakeven_set'] and profit_percent >= be_trigger:
            if position_side == "LONG":
                breakeven_price = entry_price * (1 + BREAKEVEN_OFFSET_PERCENT / 100)
            else:
                breakeven_price = entry_price * (1 - BREAKEVEN_OFFSET_PERCENT / 100)

            if update_sl_order(symbol, position_side, data['current_sl'], breakeven_price, quantity):
                data['current_sl'] = breakeven_price
                data['breakeven_set'] = True
                updated = True
                logger.info(f"🔒 {symbol} - Breakeven")

        if data['breakeven_set'] and profit_percent >= trail_trigger:
            if position_side == "LONG":
                new_sl = data['highest_price'] * (1 - trail_distance / 100)
                if new_sl > data['current_sl']:
                    if update_sl_order(symbol, position_side, data['current_sl'], new_sl, quantity):
                        data['current_sl'] = new_sl
                        data['trailing_active'] = True
                        updated = True
            else:
                new_sl = data['lowest_price'] * (1 + trail_distance / 100)
                if new_sl < data['current_sl']:
                    if update_sl_order(symbol, position_side, data['current_sl'], new_sl, quantity):
                        data['current_sl'] = new_sl
                        data['trailing_active'] = True
                        updated = True

        return updated
    except:
        return False


def remove_trailing_sl_tracking(symbol, position_side=None):
    try:
        if position_side:
            key = f"{symbol}_{position_side}"
            if key in _trailing_sl_positions:
                del _trailing_sl_positions[key]
        else:
            keys = [k for k in _trailing_sl_positions if k.startswith(f"{symbol}_")]
            for key in keys:
                del _trailing_sl_positions[key]
        return True
    except:
        return False


def monitor_trailing_sl():
    try:
        if not TRAILING_SL_ENABLED:
            return 0

        positions = get_open_positions()
        updated = 0

        for position in positions:
            symbol = position['symbol']
            position_side = position['positionSide']
            current_price = get_price(symbol)

            if current_price:
                if update_trailing_sl(symbol, position_side, current_price):
                    updated += 1

        return updated
    except:
        return 0


def get_trailing_sl_status():
    try:
        return {
            'active_positions': len(_trailing_sl_positions),
            'positions': {
                key: {
                    'symbol': data['symbol'],
                    'position_side': data['position_side'],
                    'entry_price': data['entry_price'],
                    'current_sl': data['current_sl'],
                    'breakeven_set': data['breakeven_set'],
                    'trailing_active': data['trailing_active']
                }
                for key, data in _trailing_sl_positions.items()
            }
        }
    except:
        return {'active_positions': 0, 'positions': {}}


# ==================== الحماية ====================

def _cfg_val(name, default):
    return globals().get(name, default)


def _risk_state_dict():
    return {
        'consecutive_losses': _consecutive_losses,
        'pause_until': _pause_until,
        'last_loss_ts': _last_loss_ts,
        'pause_reason': _pause_reason,
        'updated_ts': time.time(),
    }


def _save_risk_state():
    """🔥 حفظ حالة المخاطر (محلياً + Firebase) حتى لا تُصفَّر عند إعادة التشغيل"""
    try:
        state = _risk_state_dict()
        try:
            with open(RISK_STATE_FILE, "w", encoding="utf-8") as f:
                json.dump(state, f)
        except Exception as e:
            logger.debug(f"تعذر حفظ risk_state محلياً: {e}")

        try:
            import firebase_backup
            if firebase_backup.is_available():
                threading.Thread(
                    target=firebase_backup.save_doc,
                    args=(RISK_FIREBASE_DOC, state),
                    daemon=True
                ).start()
        except Exception:
            pass
    except Exception as e:
        logger.debug(f"_save_risk_state: {e}")


def load_risk_state(from_firebase=True):
    """تحميل حالة المخاطر (الأحدث بين المحلي و Firebase)"""
    global _consecutive_losses, _pause_until, _last_loss_ts, _pause_reason
    try:
        candidates = []
        try:
            if os.path.exists(RISK_STATE_FILE):
                with open(RISK_STATE_FILE, "r", encoding="utf-8") as f:
                    candidates.append(json.load(f))
        except Exception:
            pass

        if from_firebase:
            try:
                import firebase_backup
                if firebase_backup.is_available():
                    doc = firebase_backup.load_doc(RISK_FIREBASE_DOC)
                    if doc:
                        candidates.append(doc)
            except Exception:
                pass

        if not candidates:
            return False

        best = max(candidates, key=lambda d: float(d.get('updated_ts', 0) or 0))
        with _risk_lock:
            _consecutive_losses = int(best.get('consecutive_losses', 0) or 0)
            _pause_until = float(best.get('pause_until', 0) or 0)
            _last_loss_ts = float(best.get('last_loss_ts', 0) or 0)
            _pause_reason = best.get('pause_reason', '') or ''

        logger.info(f"✅ حالة المخاطر: خسائر متتالية={_consecutive_losses}, "
                    f"توقف حتى={'لا' if _pause_until <= time.time() else datetime.fromtimestamp(_pause_until).strftime('%H:%M')}")
        return True
    except Exception as e:
        logger.warning(f"⚠️ تعذر تحميل حالة المخاطر: {e}")
        return False


def _pause_minutes_for(streak):
    """إيقاف متصاعد: يُقرأ من PAUSE_ESCALATION = [(عدد الخسائر, دقائق), ...]"""
    table = _cfg_val('PAUSE_ESCALATION', [(3, 60), (5, 240), (7, 720)])
    minutes = 0
    for threshold, mins in sorted(table):
        if streak >= threshold:
            minutes = mins
    return minutes


def record_trade_result(profit):
    """
    🔥 v5.7: إيقاف متصاعد + تجاهل التعادل + حفظ الحالة.
    profit هنا هو الصافي الحقيقي (بعد العمولة).
    """
    global _consecutive_losses, _pause_until, _last_loss_ts, _pause_reason

    try:
        eps = float(_cfg_val('LOSS_EPSILON', 0.10))
        paused_now = False

        with _risk_lock:
            if profit < -eps:
                _consecutive_losses += 1
                _last_loss_ts = time.time()
                logger.warning(f"⚠️ خسارة: {_consecutive_losses} متتالية")

                minutes = _pause_minutes_for(_consecutive_losses)
                if minutes:
                    until = time.time() + minutes * 60
                    if until > _pause_until:
                        _pause_until = until
                        _pause_reason = f"{_consecutive_losses} خسائر متتالية"
                    logger.warning(f"🛑 توقف {minutes} دقيقة ({_consecutive_losses} خسائر متتالية)")
                    paused_now = True

            elif profit > eps:
                if _consecutive_losses > 0:
                    logger.info("✅ ربح - إعادة تعيين عداد الخسائر")
                _consecutive_losses = 0
            # التعادل (|profit| <= eps) لا يغيّر العداد

        _save_risk_state()
        return paused_now
    except Exception as e:
        logger.error(f"خطأ record_trade_result: {e}")
        return False






def get_pause_reason():
    return _pause_reason


def get_risk_multiplier():
    """🔥 تقليل حجم الصفقة بعد خسائر متتالية (يرجع 1.0 في الحالة العادية)"""
    try:
        if not _cfg_val('AUTO_REDUCE_RISK_ON_LOSS', True):
            return 1.0
        losses = get_consecutive_losses()
        if losses >= int(_cfg_val('RISK_REDUCE_AFTER_LOSSES', 3)):
            return float(_cfg_val('AUTO_RISK_REDUCTION_FACTOR', 0.5))
        return 1.0
    except Exception:
        return 1.0


def _midnight_after_now():
    now = datetime.now()
    return (now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)).timestamp()


_income_cache = {'ts': 0, 'value': None}


def get_today_net_income(max_age=45):
    """صافي دخل اليوم من Binance (REALIZED_PNL + COMMISSION + FUNDING_FEE)"""
    try:
        if _income_cache['value'] is not None and time.time() - _income_cache['ts'] < max_age:
            return _income_cache['value']

        # 🔥 v6.2: حد الخسارة اليومية لصفقات البوت فقط (من trade_memory) - لا يحسب صفقاتك اليدوية
        if _cfg_val('BOT_ONLY_DAILY_LOSS', True):
            try:
                import trade_memory as _tm
                _start_iso = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
                _tot = 0.0
                for _t in (_tm.load_memory().get("trades", []) or []):
                    _when = _t.get("closed_at") or _t.get("entry_time") or ""
                    if _when >= _start_iso:
                        _tot += float(_t.get("pnl", 0) or 0)
                _income_cache['ts'] = time.time()
                _income_cache['value'] = round(_tot, 4)
                return _income_cache['value']
            except Exception as _e:
                logger.warning(f"⚠️ تعذر حساب خسارة البوت من الذاكرة، استخدام Binance: {_e}")

        client_obj = get_client()
        if not client_obj:
            return None

        start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        rows = client_obj.futures_income_history(
            startTime=int(start.timestamp() * 1000), limit=1000
        )
        total = 0.0
        for r in rows or []:
            if r.get('incomeType') in ('REALIZED_PNL', 'COMMISSION', 'FUNDING_FEE'):
                total += float(r.get('income', 0) or 0)

        _income_cache['ts'] = time.time()
        _income_cache['value'] = round(total, 4)
        return _income_cache['value']
    except Exception as e:
        logger.warning(f"⚠️ تعذر جلب دخل اليوم: {e}")
        return None


def _release_daily_pause_if_ok():
    """🔥 v6.2: إيقاف 'حد الخسارة اليومية' القديم يُرفع فوراً إن كانت خسارة البوت الآن أقل من الحد الحالي."""
    global _pause_until, _pause_reason
    try:
        if _pause_reason != "حد الخسارة اليومية" or _pause_until <= time.time():
            return
        today = get_today_net_income()
        if today is None:
            return
        limit = float(_cfg_val('DAILY_MAX_LOSS_USDT', 0) or 0)
        loss = abs(today) if today < 0 else 0.0
        if limit > 0 and loss < limit:
            with _risk_lock:
                _pause_until = 0
                _pause_reason = ""
            _save_risk_state()
            logger.info(f"✅ رُفع إيقاف الخسارة اليومية: خسارة البوت {loss:.2f}$ < الحد {limit:.2f}$")
    except Exception as e:
        logger.debug(f"_release_daily_pause_if_ok: {e}")


def is_trading_paused():
    global _pause_until

    try:
        _release_daily_pause_if_ok()
        if _pause_until == 0:
            return False, 0

        current_time = time.time()
        if current_time >= _pause_until:
            _pause_until = 0
            logger.info("✅ انتهى التوقف")
            return False, 0
        else:
            remaining = int((_pause_until - current_time) / 60)
            return True, remaining
    except:
        return False, 0


def get_consecutive_losses():
    return _consecutive_losses


# ==================== SL ديناميكي ====================

def calculate_dynamic_sl(symbol, entry_price, position_side):
    try:
        if not DYNAMIC_SL_ENABLED:
            if position_side == "LONG":
                sl_price = entry_price * (1 - SL_PERCENT / 100)
            else:
                sl_price = entry_price * (1 + SL_PERCENT / 100)
            return sl_price, SL_PERCENT

        klines = get_klines(symbol, "5m", limit=20)
        if not klines or len(klines) < 15:
            if position_side == "LONG":
                sl_price = entry_price * (1 - SL_PERCENT / 100)
            else:
                sl_price = entry_price * (1 + SL_PERCENT / 100)
            return sl_price, SL_PERCENT

        highs = [float(k[2]) for k in klines]
        lows = [float(k[3]) for k in klines]
        closes = [float(k[4]) for k in klines]

        true_ranges = []
        for i in range(1, len(highs)):
            tr1 = highs[i] - lows[i]
            tr2 = abs(highs[i] - closes[i - 1])
            tr3 = abs(lows[i] - closes[i - 1])
            true_ranges.append(max(tr1, tr2, tr3))

        if not true_ranges:
            if position_side == "LONG":
                sl_price = entry_price * (1 - SL_PERCENT / 100)
            else:
                sl_price = entry_price * (1 + SL_PERCENT / 100)
            return sl_price, SL_PERCENT

        atr = sum(true_ranges[-14:]) / 14
        atr_percent = (atr / entry_price) * 100 * SL_ATR_MULTIPLIER
        sl_percent = max(SL_MIN_PERCENT, min(SL_MAX_PERCENT, atr_percent))

        # سقف خسارة الصفقة الواحدة: لا نسمح للوقف أن يتجاوز حد الخسارة المطلوب
        try:
            max_loss_usdt = float(getattr(cfg, 'MAX_TRADE_LOSS_USDT', 0) or 0)
            notional = float(getattr(cfg, 'TRADE_USDT', 10)) * float(getattr(cfg, 'LEVERAGE', 10))
            if max_loss_usdt > 0 and notional > 0:
                loss_cap_percent = (max_loss_usdt / notional) * 100
                sl_percent = min(sl_percent, loss_cap_percent)
        except Exception:
            pass

        if position_side == "LONG":
            sl_price = entry_price * (1 - sl_percent / 100)
        else:
            sl_price = entry_price * (1 + sl_percent / 100)

        return sl_price, sl_percent
    except:
        if position_side == "LONG":
            sl_price = entry_price * (1 - SL_PERCENT / 100)
        else:
            sl_price = entry_price * (1 + SL_PERCENT / 100)
        return sl_price, SL_PERCENT


# ==================== TP المتعدد ====================

def calculate_tp_price(position_side, entry_price, tp_percent):
    if position_side == "LONG":
        return entry_price * (1 + tp_percent / 100)
    return entry_price * (1 - tp_percent / 100)


def create_multiple_tp_orders(symbol, position_side, total_quantity, entry_price,
                              tp_levels, tp_ratios, sl_percent=None, exit_mode=None):
    try:
        client_obj = get_client()
        if not client_obj:
            return {'sl_success': False, 'tp_orders': [], 'total_tp_quantity': 0, 'algo_ids': {}}

        # وضع الخروج الواسع: أهداف أكبر وتوزيع مختلف للصفقات القوية فقط
        if exit_mode == 'wide':
            tp_levels = list(getattr(cfg, 'WIDE_TP_R_MULTIPLES', tp_levels))
            tp_ratios = list(getattr(cfg, 'WIDE_TP_RATIOS', tp_ratios))

        ratios_sum = sum(tp_ratios)
        if abs(ratios_sum - 1.0) > 0.01:
            logger.error(f"❌ مجموع نسب TP = {ratios_sum} يجب أن يكون 1.0")
            return {'sl_success': False, 'tp_orders': [], 'total_tp_quantity': 0, 'algo_ids': {}}

        results = {'sl_success': False, 'tp_orders': [], 'total_tp_quantity': 0, 'algo_ids': {}}

        close_side = "SELL" if position_side == "LONG" else "BUY"

        # SL
        if ENABLE_SL:
            sl_price, actual_sl_percent = calculate_dynamic_sl(symbol, entry_price, position_side)
            formatted_sl = format_price_for_binance(symbol, sl_price)

            if formatted_sl:
                logger.info(f"📊 محاولة إنشاء SL @ {formatted_sl}")

                sl_params = {
                    'symbol': symbol,
                    'side': close_side,
                    'type': 'STOP_MARKET',
                    'quantity': total_quantity,
                    'stopPrice': formatted_sl,
                    'positionSide': position_side,
                    'timeInForce': 'GTC'
                }

                sl_order = create_order_with_retry(sl_params)

                if sl_order:
                    results['sl_success'] = True
                    results['sl_order_id'] = sl_order['orderId']
                    results['sl_price'] = formatted_sl
                    results['sl_percent'] = actual_sl_percent
                    results['algo_ids']['sl'] = sl_order['orderId']
                    logger.info(f"✅ SL: {formatted_sl} ({actual_sl_percent:.2f}%)")
                else:
                    logger.error(f"❌ فشل إنشاء SL")

        # Hybrid RR: بناء TP من الوقف الفعلي حتى لا تقل جودة الصفقة عن 1.2R
        try:
            if 'actual_sl_percent' not in locals() or actual_sl_percent is None:
                actual_sl_percent = float(sl_percent or SL_PERCENT)
            r_multipliers = list(getattr(cfg, 'WIDE_TP_R_MULTIPLES' if exit_mode == 'wide' else 'TP_R_MULTIPLES',
                                         getattr(cfg, 'TP_R_MULTIPLES', [1.2, 2.0, 3.2])))
            tp_min = float(getattr(cfg, 'TP_PERCENT', 1.2))
            tp_max = float(getattr(cfg, 'TP_MAX_PERCENT', 5.0))
            dynamic_tp_levels = []
            for idx, r in enumerate(r_multipliers[:len(tp_levels)]):
                pct = max(tp_min, float(actual_sl_percent) * float(r))
                pct = min(tp_max, pct)
                dynamic_tp_levels.append(round(pct, 2))
            if len(dynamic_tp_levels) == len(tp_levels):
                tp_levels = dynamic_tp_levels
                logger.info(f"🎯 TP RR levels: {tp_levels} بناءً على SL {actual_sl_percent:.2f}%")
        except Exception as rr_err:
            logger.debug(f"dynamic TP RR skipped: {rr_err}")

        # TP متعدد
        for i, (tp_percent, ratio) in enumerate(zip(tp_levels, tp_ratios)):
            level_quantity = total_quantity * ratio
            level_quantity = _round_quantity(symbol, level_quantity)

            if level_quantity <= 0:
                logger.warning(f"⚠️ TP{i+1}: كمية صفرية")
                continue

            tp_price = calculate_tp_price(position_side, entry_price, tp_percent)
            formatted_tp = format_price_for_binance(symbol, tp_price)

            if formatted_tp:
                logger.info(f"📊 محاولة إنشاء TP{i+1} @ {formatted_tp}")

                tp_params = {
                    'symbol': symbol,
                    'side': close_side,
                    'type': 'TAKE_PROFIT_MARKET',
                    'quantity': level_quantity,
                    'stopPrice': formatted_tp,
                    'positionSide': position_side,
                    'timeInForce': 'GTC'
                }

                tp_order = create_order_with_retry(tp_params)

                if tp_order:
                    results['tp_orders'].append({
                        'order_id': tp_order['orderId'],
                        'level': i + 1,
                        'tp_percent': tp_percent,
                        'tp_price': formatted_tp,
                        'quantity': level_quantity,
                        'ratio': ratio,
                        'success': True
                    })
                    results['total_tp_quantity'] += level_quantity
                    results['algo_ids'][f'tp{i+1}'] = tp_order['orderId']
                    logger.info(f"✅ TP{i+1}: {tp_percent}% @ {formatted_tp}")
                else:
                    logger.error(f"❌ فشل TP{i+1}")
                    results['tp_orders'].append({
                        'level': i + 1,
                        'tp_percent': tp_percent,
                        'success': False
                    })

        return results

    except Exception as e:
        logger.error(f"خطأ: {e}")
        return {'sl_success': False, 'tp_orders': [], 'total_tp_quantity': 0, 'algo_ids': {}}



# ==================== 🔥 v6.2: رافعة آمنة لكل عملة (خطأ -4028) ====================
# بعض العملات لا تقبل الرافعة المطلوبة (مثل 15x). بدل فشل الصفقة:
#   LEVERAGE_FALLBACK_MODE = "max"  → استخدم أعلى رافعة تقبلها العملة (الهامش يبقى كما هو)
#   LEVERAGE_FALLBACK_MODE = "skip" → تجاهل الصفقة (لا تفتح)
_LEV_CAP = {}  # symbol -> أعلى رافعة مقبولة


def _apply_leverage(client_obj, symbol, leverage):
    """يضبط الرافعة ويرجع الرافعة الفعلية، أو None إن تعذّر/منع الوضع skip."""
    wanted = int(leverage)
    lev = min(wanted, _LEV_CAP.get(symbol, wanted))
    mode = str(globals().get('LEVERAGE_FALLBACK_MODE', 'max')).lower()
    if lev < 1:
        return None   # عملة سبق تخطّيها (وضع skip)
    for _ in range(5):
        try:
            client_obj.futures_change_leverage(symbol=symbol, leverage=lev)
            if lev != wanted:
                logger.warning(f"⚠️ {symbol}: الرافعة {wanted}x غير مقبولة - استخدام {lev}x (أعلى مسموح)")
            return lev
        except Exception as e:
            code = getattr(e, 'code', None)
            if code != -4028 and 'not valid' not in str(e):
                raise
            if mode == 'skip':
                _LEV_CAP[symbol] = 0
                logger.warning(f"⏭️ {symbol}: الرافعة {lev}x غير مقبولة - تخطّي (LEVERAGE_FALLBACK_MODE=skip)")
                return None
            mx = None
            try:
                br = client_obj.futures_leverage_bracket(symbol=symbol)
                mx = int(br[0]['brackets'][0]['initialLeverage'])
            except Exception:
                pass
            new = mx if (mx and mx < lev) else lev - 1
            if new < 1:
                return None
            lev = new
            _LEV_CAP[symbol] = lev
    return None


def place_market_order_with_multiple_tp(symbol, side, amount_usdt, leverage,
                                        tp_levels=None, tp_ratios=None, sl_percent=None, exit_mode=None):
    try:
        if tp_levels is None:
            tp_levels = TP_MULTIPLE_LEVELS
        if tp_ratios is None:
            tp_ratios = TP_QUANTITY_RATIOS

        client_obj = get_client()
        if not client_obj:
            return None

        positionSide = "LONG" if side.upper() == "BUY" else "SHORT"

        price = get_price(symbol)
        if not price:
            logger.error(f"لا يمكن الحصول على سعر {symbol}")
            return None

        # 🔥 v6.2: اضبط الرافعة أولاً (قد تُخفَّض لعملة لا تقبل 15x) ثم احسب الكمية
        eff_leverage = _apply_leverage(client_obj, symbol, leverage)
        if not eff_leverage:
            return None

        notional = float(amount_usdt) * float(eff_leverage)
        total_qty = _round_quantity(symbol, notional / price)

        if total_qty <= 0:
            logger.error(f"كمية غير صالحة: {total_qty}")
            return None

        logger.info(f"🚀 فتح صفقة: {symbol} {side} {total_qty}")

        main_order = client_obj.futures_create_order(
            symbol=symbol,
            side=side.upper(),
            type="MARKET",
            quantity=total_qty,
            positionSide=positionSide
        )

        if not main_order:
            logger.error("❌ فشل فتح الصفقة")
            return None

        logger.info(f"✅ تم فتح الصفقة: {main_order['orderId']}")

        time.sleep(5)

        positions = get_open_positions()
        entry_price = price
        actual_qty = total_qty

        for pos in positions:
            if pos["symbol"] == symbol and pos["positionSide"] == positionSide:
                entry_price = float(pos["entryPrice"])
                actual_qty = abs(float(pos["positionAmt"]))
                break

        logger.info(f"📊 إنشاء TP/SL...")

        tp_results = create_multiple_tp_orders(
            symbol=symbol,
            position_side=positionSide,
            total_quantity=actual_qty,
            entry_price=entry_price,
            tp_levels=tp_levels,
            tp_ratios=tp_ratios,
            sl_percent=sl_percent,
            exit_mode=exit_mode
        )

        time.sleep(2)

        has_tp, has_sl, details = verify_tp_sl_created(symbol, positionSide)

        logger.info(f"🔍 التحقق: TP={has_tp} ({details.get('tp_count', 0)}), SL={has_sl} ({details.get('sl_count', 0)})")

        if VERIFY_TP_SL_AFTER_CREATION and not has_sl:
            logger.error(f"🚨 فشل SL - إغلاق الصفقة فوراً!")

            # إغلاق الصفقة + حذف الأوامر التي أُنشئت
            algo_ids_to_cancel = [v for v in tp_results.get('algo_ids', {}).values() if v]
            close_position_safe(symbol, positionSide, algo_ids=algo_ids_to_cancel)

            return {
                'symbol': symbol,
                'side': side,
                'entry_price': entry_price,
                'quantity': actual_qty,
                'positionSide': positionSide,
                'order_id': main_order['orderId'],
                'multiple_tp': True,
                'tp_results': tp_results,
                'verification': {
                    'has_tp': has_tp,
                    'has_sl': has_sl,
                    'details': details
                },
                'closed_due_to_failure': True,
                'failure_reason': 'SL not created'
            }

        return {
            "symbol": symbol,
            "side": side,
            "entry_price": entry_price,
            "quantity": actual_qty,
            "positionSide": positionSide,
            "order_id": main_order["orderId"],
            "multiple_tp": True,
            "tp_results": tp_results,
            "tp_levels": tp_levels,
            "tp_ratios": tp_ratios,
            "algo_orders": tp_results.get('algo_ids', {}),  # 🔥 حفظ algo_ids
            "verification": {
                "has_tp": has_tp,
                "has_sl": has_sl,
                "details": details
            }
        }

    except Exception as e:
        logger.error(f"خطأ: {e}")
        return None


def place_market_order_with_tp_sl(symbol, side, amount_usdt, leverage):
    return place_market_order_with_multiple_tp(symbol, side, amount_usdt, leverage)


# ==================== الأرباح ====================

def get_accurate_daily_pnl():
    try:
        client_obj = get_client()
        if not client_obj:
            return {'daily_pnl': 0.0, 'today_trades': [], 'trade_count': 0, 'data_quality': 'خطأ'}

        today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        tomorrow = today + timedelta(days=1)

        income = client_obj.futures_income_history(incomeType="REALIZED_PNL", limit=1000)

        daily_pnl = 0.0
        today_trades = []
        unique = set()

        for item in income:
            if item['incomeType'] == 'REALIZED_PNL':
                trade_time = datetime.fromtimestamp(int(item['time']) / 1000)
                if today <= trade_time < tomorrow:
                    amount = float(item['income'])
                    key = f"{item.get('symbol')}_{item['time']}_{amount:.6f}"

                    if key not in unique:
                        unique.add(key)
                        daily_pnl += amount
                        if abs(amount) >= 0.05:
                            today_trades.append({
                                'symbol': item.get('symbol', 'N/A'),
                                'income': amount,
                                'time': item['time']
                            })

        return {
            'daily_pnl': daily_pnl,
            'today_trades': today_trades,
            'trade_count': len(today_trades),
            'data_quality': 'مصحح'
        }
    except:
        return {'daily_pnl': 0.0, 'today_trades': [], 'trade_count': 0, 'data_quality': 'خطأ'}


def get_accurate_weekly_pnl():
    try:
        client_obj = get_client()
        if not client_obj:
            return {'weekly_pnl': 0.0, 'weekly_trades': [], 'trade_count': 0,
                    'week_start': 'N/A', 'week_end': 'N/A', 'week_number': 0, 'data_quality': 'خطأ'}

        today = datetime.now()
        start = today - timedelta(days=today.weekday())
        start = start.replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + timedelta(days=6, hours=23, minutes=59, seconds=59)

        income = client_obj.futures_income_history(incomeType="REALIZED_PNL", limit=1000)

        weekly_pnl = 0.0
        weekly_trades = []
        unique = set()

        for item in income:
            if item['incomeType'] == 'REALIZED_PNL':
                trade_time = datetime.fromtimestamp(int(item['time']) / 1000)
                if start <= trade_time <= end:
                    amount = float(item['income'])
                    key = f"{item.get('symbol')}_{item['time']}_{amount:.6f}"

                    if key not in unique:
                        unique.add(key)
                        weekly_pnl += amount
                        if abs(amount) >= 0.05:
                            weekly_trades.append({
                                'symbol': item.get('symbol', 'N/A'),
                                'income': amount,
                                'time': item['time']
                            })

        return {
            'weekly_pnl': weekly_pnl,
            'weekly_trades': weekly_trades,
            'trade_count': len(weekly_trades),
            'week_start': start.strftime("%Y-%m-%d"),
            'week_end': end.strftime("%Y-%m-%d"),
            'week_number': today.isocalendar()[1],
            'data_quality': 'مصحح'
        }
    except:
        return {'weekly_pnl': 0.0, 'weekly_trades': [], 'trade_count': 0,
                'week_start': 'N/A', 'week_end': 'N/A', 'week_number': 0, 'data_quality': 'خطأ'}


def get_accurate_monthly_pnl():
    try:
        client_obj = get_client()
        if not client_obj:
            return {'monthly_pnl': 0.0, 'monthly_trades': [], 'trade_count': 0,
                    'month_start': 'N/A', 'month_end': 'N/A', 'month_name': 'Unknown',
                    'data_quality': 'خطأ', 'avg_trade_pnl': 0}

        today = datetime.now()
        start = today.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

        if today.month == 12:
            end = today.replace(year=today.year + 1, month=1, day=1) - timedelta(seconds=1)
        else:
            end = today.replace(month=today.month + 1, day=1) - timedelta(seconds=1)

        income = client_obj.futures_income_history(incomeType="REALIZED_PNL", limit=1000)

        monthly_pnl = 0.0
        monthly_trades = []
        unique = set()

        for item in income:
            if item['incomeType'] == 'REALIZED_PNL':
                trade_time = datetime.fromtimestamp(int(item['time']) / 1000)
                if start <= trade_time <= end:
                    amount = float(item['income'])
                    key = f"{item.get('symbol')}_{item['time']}_{amount:.6f}"

                    if key not in unique:
                        unique.add(key)
                        monthly_pnl += amount
                        if abs(amount) >= 0.05:
                            monthly_trades.append({
                                'symbol': item.get('symbol', 'N/A'),
                                'income': amount,
                                'time': item['time']
                            })

        avg = monthly_pnl / len(monthly_trades) if monthly_trades else 0

        return {
            'monthly_pnl': monthly_pnl,
            'monthly_trades': monthly_trades,
            'trade_count': len(monthly_trades),
            'month_start': start.strftime("%Y-%m-%d"),
            'month_end': end.strftime("%Y-%m-%d"),
            'month_name': today.strftime("%B"),
            'data_quality': 'مصحح',
            'avg_trade_pnl': avg
        }
    except:
        return {'monthly_pnl': 0.0, 'monthly_trades': [], 'trade_count': 0,
                'month_start': 'N/A', 'month_end': 'N/A', 'month_name': 'Unknown',
                'data_quality': 'خطأ', 'avg_trade_pnl': 0}


def format_pnl_report(pnl_data, period_type="يومي"):
    try:
        if period_type == "يومي":
            pnl = pnl_data.get('daily_pnl', 0)
            count = pnl_data.get('trade_count', 0)
            title = f"📅 اليوم - {datetime.now().strftime('%Y-%m-%d')}"
        elif period_type == "أسبوعي":
            pnl = pnl_data.get('weekly_pnl', 0)
            count = pnl_data.get('trade_count', 0)
            title = f"📊 الأسبوع {pnl_data.get('week_number', 0)}"
        else:
            pnl = pnl_data.get('monthly_pnl', 0)
            count = pnl_data.get('trade_count', 0)
            title = f"📈 {pnl_data.get('month_name', 'Unknown')}"

        emoji = "🟢" if pnl > 0 else "🔴" if pnl < 0 else "⚪"
        status = "ربح" if pnl > 0 else "خسارة" if pnl < 0 else "تعادل"

        return (f"{title}\n\n"
                f"{emoji} <b>الأرباح:</b> {pnl:.2f} USDT\n"
                f"📊 <b>الصفقات:</b> {count}\n"
                f"💹 <b>الحالة:</b> {status}")
    except:
        return "❌ خطأ"


def recreate_missing_tp(symbol, position_side, entry_price, quantity):
    try:
        close_side = "SELL" if position_side == "LONG" else "BUY"
        created_any = False

        if ENABLE_MULTIPLE_TP:
            tp_levels = TP_MULTIPLE_LEVELS
            tp_ratios = TP_QUANTITY_RATIOS
        else:
            tp_levels = [TP_PERCENT]
            tp_ratios = [1.0]

        for i, (tp_percent, ratio) in enumerate(zip(tp_levels, tp_ratios)):
            level_quantity = _round_quantity(symbol, quantity * ratio)
            if level_quantity <= 0:
                continue

            tp_price = calculate_tp_price(position_side, entry_price, tp_percent)
            formatted_tp = format_price_for_binance(symbol, tp_price)
            if not formatted_tp:
                continue

            tp_params = {
                'symbol': symbol,
                'side': close_side,
                'type': 'TAKE_PROFIT_MARKET',
                'quantity': level_quantity,
                'stopPrice': formatted_tp,
                'positionSide': position_side,
                'timeInForce': 'GTC'
            }

            tp_order = create_order_with_retry(tp_params)
            if tp_order:
                created_any = True
                logger.info(f"✅ TP{i+1} لـ {symbol} @ {formatted_tp}")
            else:
                logger.error(f"❌ فشل TP{i+1} لـ {symbol}")

        return created_any
    except Exception as e:
        logger.error(f"خطأ في إعادة إنشاء TP لـ {symbol}: {e}")
        return False


def check_and_add_tp_sl_to_existing_positions():
    """
    🔥 v4.2.0: إصلاح TP/SL لصفقات البوت فقط
    """
    try:
        state_file = "open_positions.json"

        if not os.path.exists(state_file):
            logger.info("ℹ️ لا توجد صفقات بوت مسجلة")
            return 0

        with open(state_file, "r", encoding="utf-8") as f:
            bot_positions_raw = json.load(f)

        bot_owned_keys = {
            f"{p.get('symbol')}_{p.get('positionSide')}"
            for p in bot_positions_raw
            if p.get('symbol') and p.get('positionSide')
        }

        if not bot_owned_keys:
            logger.info("ℹ️ لا توجد صفقات بوت")
            return 0

        all_positions = get_open_positions()
        bot_positions = [
            p for p in all_positions
            if f"{p['symbol']}_{p['positionSide']}" in bot_owned_keys
        ]

        if not bot_positions:
            logger.info("ℹ️ لا توجد صفقات بوت مفتوحة")
            return 0

        logger.info(f"🔧 فحص {len(bot_positions)} صفقة بوت (تجاهل {len(all_positions) - len(bot_positions)} صفقة يدوية)")

        fixed = 0

        for position in bot_positions:
            symbol = position["symbol"]
            position_side = position["positionSide"]

            # 🧹 إغلاق بقايا الصفقات بعد TP الجزئي حتى لا تبقى كميات صغيرة بلا هدف
            try:
                entry_price_dust = float(position.get("entryPrice", 0) or 0)
                quantity_dust = abs(float(position.get("positionAmt", 0) or 0))
                notional_dust = entry_price_dust * quantity_dust
                dust_limit = float(getattr(cfg, 'DUST_POSITION_NOTIONAL_USDT', 0.5))
                if quantity_dust > 0 and notional_dust < dust_limit:
                    logger.warning(f"🧹 {symbol} بقايا صفقة غبار {notional_dust:.4f}$ — إغلاقها")
                    if close_position_safe(symbol, position_side):
                        fixed += 1
                    continue
            except Exception as dust_err:
                logger.debug(f"dust check skipped: {dust_err}")

            has_tp, has_sl, details = verify_tp_sl_created(symbol, position_side)

            if not has_sl:
                logger.warning(f"⚠️ {symbol} بدون SL (صفقة بوت) - محاولة إعادة الإنشاء")

                entry_price = float(position["entryPrice"])
                quantity = abs(float(position["positionAmt"]))
                current_price = get_price(symbol)

                sl_price, sl_percent = calculate_dynamic_sl(symbol, entry_price, position_side)
                formatted_sl = format_price_for_binance(symbol, sl_price)

                if not formatted_sl:
                    continue

                already_past_sl = (
                    (position_side == "LONG" and current_price is not None and current_price <= formatted_sl) or
                    (position_side == "SHORT" and current_price is not None and current_price >= formatted_sl)
                )

                if already_past_sl:
                    logger.error(f"🛑 {symbol} تخطى SL - إغلاق فوري")
                    if close_position_safe(symbol, position_side):
                        fixed += 1
                    continue

                close_side = "SELL" if position_side == "LONG" else "BUY"

                sl_params = {
                    'symbol': symbol,
                    'side': close_side,
                    'type': 'STOP_MARKET',
                    'quantity': quantity,
                    'stopPrice': formatted_sl,
                    'positionSide': position_side,
                    'timeInForce': 'GTC'
                }

                sl_order = create_order_with_retry(sl_params)

                if sl_order:
                    fixed += 1
                    logger.info(f"✅ تم إعادة إنشاء SL لـ {symbol}")
                elif CLOSE_ON_TP_SL_FAIL:
                    logger.error(f"❌ فشل SL لـ {symbol} - إغلاق وقائي")
                    if close_position_safe(symbol, position_side):
                        logger.info(f"✅ تم إغلاق {symbol} وقائياً")

            elif not has_tp:
                logger.warning(f"⚠️ {symbol} بدون TP (صفقة بوت) - محاولة إعادة الإنشاء")

                entry_price = float(position["entryPrice"])
                quantity = abs(float(position["positionAmt"]))

                if recreate_missing_tp(symbol, position_side, entry_price, quantity):
                    fixed += 1
                    logger.info(f"✅ تم إعادة إنشاء TP لـ {symbol}")
                else:
                    # إذا كان السعر تجاوز TP بالفعل والمنصة ترفض إعادة الأمر، نغلق لحماية الربح بدل الاستمرار بلا TP
                    try:
                        current_price = get_price(symbol)
                        nearest_tp = calculate_tp_price(position_side, entry_price, TP_PERCENT)
                        passed_tp = (
                            (position_side == "LONG" and current_price is not None and current_price >= nearest_tp) or
                            (position_side == "SHORT" and current_price is not None and current_price <= nearest_tp)
                        )
                        if passed_tp:
                            logger.warning(f"⚠️ {symbol} تجاوز TP وإعادة الإنشاء فشلت — إغلاق لحماية الربح")
                            if close_position_safe(symbol, position_side):
                                fixed += 1
                                logger.info(f"✅ تم إغلاق {symbol} بعد تجاوز TP")
                        else:
                            logger.error(f"❌ فشل إعادة TP لـ {symbol} والسعر لم يصل للهدف بعد")
                    except Exception as close_err:
                        logger.error(f"خطأ معالجة فشل TP لـ {symbol}: {close_err}")

        return fixed
    except Exception as e:
        logger.error(f"خطأ: {e}")
        return 0


if __name__ == "__main__":
    print("🚀 core_functions.py v4.2.0")
    print(f"✅ الاتصال: {'ناجح' if client else 'فشل'}")
    print(f"🔍 التحقق من TP/SL: {'مفعل' if VERIFY_TP_SL_AFTER_CREATION else 'معطل'}")
    print(f"📊 فلتر السيولة: {'مفعل' if ENABLE_VOLUME_FILTER else 'معطل'}")
    print(f"🧹 تنظيف الأوامر اليتيمة: {'مفعل' if ENABLE_ORPHAN_CLEANUP else 'معطل'}")


# 🔥 استرجاع حالة المخاطر المحلية عند الاستيراد
try:
    load_risk_state(from_firebase=False)
except Exception:
    pass
