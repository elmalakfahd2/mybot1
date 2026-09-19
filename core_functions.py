# ==================================================
# 📁 ملف: core_functions.py - الإصدار v4.1.4
# 🔧 التعديلات v4.1.4:
#    - 🔥 check_and_add_tp_sl_to_existing_positions يتجاهل الصفقات اليدوية
#    - 🔥 Cache الرموز (10 دقائق)
# 🔧 التعديلات v4.0:
#    - Breakeven بعد TP1 + هامش 0.1%
# 📅 التاريخ: 2026-09-19
# ==================================================

import logging
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
    """إنشاء أمر شرطي عبر Algo Order API الجديد"""
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

        except Exception as e:
            logger.warning(f"⚠️ Algo محاولة {attempt+1}/{max_retries} فشلت: {e}")

        if attempt < max_retries - 1:
            time.sleep(TP_SL_RETRY_DELAY_SECONDS)

    logger.error(f"❌ فشل جميع محاولات Algo Order ({max_retries})")
    return None


def cancel_algo_order(symbol, algo_id):
    """إلغاء أمر شرطي عبر DELETE /fapi/v1/algoOrder"""
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
    MAX_SPREAD_PERCENT = 0.15
try:
    MIN_DEPTH_MULTIPLIER
except NameError:
    MIN_DEPTH_MULTIPLIER = 10
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


# ==================== get_all_futures_symbols محسّن ====================

def get_all_futures_symbols():
    """
    🔥 Cache لمدة 10 دقائق
    طلب واحد لكل التيكرز (بدل 528 طلب)
    """
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

        logger.info(f"📊 فلتر السيولة: {len(filtered_syms)}/{len(syms)} عملة (حد أدنى: {MIN_VOLUME_24H_USDT/1e6:.0f}M USDT)")

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
            return False, f"سيولة ضعيفة: {ob['total_depth_usdt']:.0f} USDT (المطلوب: {min_required_depth:.0f})"

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
        logger.error(f"خطأ حساب الارتباط {symbol_a}/{symbol_b}: {e}")
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
    try:
        if not ENABLE_DAILY_DRAWDOWN_LIMIT:
            return True, "معطل"

        client_obj = get_client()
        if not client_obj:
            return True, "لا يوجد اتصال"

        account = client_obj.futures_account()
        balance = 0.0
        for asset in account.get('assets', []):
            if asset.get('asset') == 'USDT':
                balance = float(asset.get('availableBalance', 0))
                break

        if balance <= 0:
            return True, "رصيد غير متاح"

        try:
            import trade_memory
            today_pnl = trade_memory.get_today_pnl()
        except Exception as e:
            logger.warning(f"⚠️ تعذر جلب PnL اليوم: {e}")
            return True, "تعذر جلب البيانات"

        if today_pnl >= 0:
            return True, f"ربح اليوم: {today_pnl:.2f}"

        loss_percent = (abs
