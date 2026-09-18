# ==================================================
# 📁 ملف: core_functions.py - الإصدار النهائي
# 🔧 الإصلاحات:
#    - التحقق الإجباري من TP/SL
#    - إعادة المحاولة 3 مرات
#    - إغلاق تلقائي عند الفشل
#    - فلتر السيولة
#    - Trailing SL
#    - ✅ إصلاح check_daily_drawdown (availableBalance)
# 📅 التاريخ: 2024-01-15
# ==================================================

import logging
import time
import hmac
import hashlib
import requests
from urllib.parse import urlencode
from datetime import datetime, timedelta
from binance.client import Client
from binance.exceptions import BinanceAPIException, BinanceRequestException
from config import *

logger = logging.getLogger("core")
_client = None

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


def get_all_futures_symbols():
    """جميع الرموز مع فلتر السيولة"""
    try:
        client_obj = get_client()
        if not client_obj:
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
                volume_map = {t['symbol']: float(t.get('quoteVolume', 0)) for t in all_tickers}
            except Exception as e:
                logger.error(f"⚠️ فشل جلب التيكرز دفعة واحدة: {e}")
                volume_map = None

            if volume_map is not None:
                filtered_syms = [
                    sym for sym in syms
                    if volume_map.get(sym, 0) >= MIN_VOLUME_24H_USDT
                ]
            else:
                filtered_syms = []
                for sym in syms:
                    try:
                        ticker = client_obj.futures_ticker(symbol=sym)
                        volume_usdt = float(ticker.get('quoteVolume', 0))
                        if volume_usdt >= MIN_VOLUME_24H_USDT:
                            filtered_syms.append(sym)
                    except:
                        continue
            
            logger.info(f"📊 فلتر السيولة: {len(filtered_syms)}/{len(syms)} عملة (حد أدنى: {MIN_VOLUME_24H_USDT/1e6:.0f}M USDT)")
            return filtered_syms
        
        return syms
    except Exception as e:
        logger.error(f"خطأ: {e}")
        return []


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


# ==================== 🔥 تحليل دفتر الأوامر ====================

def get_order_book_analysis(symbol, depth_levels=20):
    """تحليل دفتر الأوامر: السبريد، العمق، والانحياز"""
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
    """فلتر تنفيذ صارم: يرفض الدخول لو السبريد واسع أو السيولة غير كافية"""
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
            return False, f"سيولة ضعيفة في الدفتر: {ob['total_depth_usdt']:.0f} USDT (المطلوب: {min_required_depth:.0f})"

        return True, "سيولة ومطابقة السبريد مقبولة"
    except Exception as e:
        logger.error(f"خطأ فحص السيولة: {e}")
        return True, "خطأ في الفحص - تم التجاوز"


# ==================== 🔥 Funding Rate + Open Interest ====================

def get_funding_rate(symbol):
    """معدل التمويل الحالي"""
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
    """اتجاه الـ Open Interest"""
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


# ==================== 🔥 الارتباط ====================

def get_price_correlation(symbol_a, symbol_b, interval='15m', limit=50):
    """معامل ارتباط بيرسون"""
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
    """يرفض فتح صفقة جديدة لو هي فعلياً نفس الرهان على صفقة مفتوحة"""
    try:
        if not ENABLE_CORRELATION_FILTER or not open_positions:
            return True, "فلتر الارتباط معطل أو لا توجد صفقات مفتوحة"

        for pos in open_positions:
            other_symbol = pos.get('symbol')
            other_side = "BUY" if float(pos.get('positionAmt', 0)) > 0 else "SELL"
            if other_symbol == symbol:
                continue
            if other_side != direction:
                continue

            corr = get_price_correlation(symbol, other_symbol)
            if abs(corr) >= MAX_CORRELATION:
                return False, f"ارتباط عالٍ ({corr:.2f}) مع صفقة مفتوحة على {other_symbol} بنفس الاتجاه"

        return True, "التعرض ضمن الحدود المقبولة"
    except Exception as e:
        logger.error(f"خطأ فحص الارتباط: {e}")
        return True, "خطأ في الفحص - تم التجاوز"


# ==================== 🔥 قاطع دائرة الخسارة اليومية ====================

def check_daily_drawdown():
    """
    ✅ إصلاح: استخدام availableBalance الصحيح
    """
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

        loss_percent = (abs(today_pnl) / balance) * 100

        if loss_percent >= DAILY_MAX_LOSS_PERCENT:
            return False, f"🛑 خسارة يومية {loss_percent:.2f}% (الحد: {DAILY_MAX_LOSS_PERCENT}%)"

        return True, f"خسارة اليوم: {loss_percent:.2f}%"

    except Exception as e:
        logger.error(f"خطأ فحص الخسارة اليومية: {e}")
        return True, "خطأ - تم التجاوز"


# ==================== 🔥 التحقق من TP/SL ====================

def verify_tp_sl_created(symbol, position_side):
    """التحقق من وجود TP/SL فعلياً"""
    try:
        open_orders = list(get_open_orders(symbol) or []) + list(get_open_algo_orders(symbol) or [])
        
        if not open_orders:
            return False, False, {
                'total_orders': 0,
                'tp_count': 0,
                'sl_count': 0
            }
        
        tp_orders = [o for o in open_orders if o.get('type') == 'TAKE_PROFIT_MARKET']
        sl_orders = [o for o in open_orders if o.get('type') == 'STOP_MARKET']
        
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
    """إنشاء أمر مع إعادة المحاولة"""
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
                logger.error(f"❌ خطأ دائم - إيقاف المحاولات")
                return None
            
            if attempt < max_retries - 1:
                time.sleep(TP_SL_RETRY_DELAY_SECONDS)
        except Exception as e:
            logger.warning(f"⚠️ محاولة {attempt+1}/{max_retries} فشلت: {e}")
            if attempt < max_retries - 1:
                time.sleep(TP_SL_RETRY_DELAY_SECONDS)
    
    logger.error(f"❌ فشل جميع المحاولات ({max_retries})")
    return None


# ==================== إغلاق الصفقات ====================

def close_position_safe(symbol, position_side):
    try:
        client_obj = get_client()
        if not client_obj:
            return False

        positions = get_open_positions()
        position = None
        for pos in positions:
            if pos["symbol"] == symbol and pos["positionSide"] == position_side:
                position = pos
                break

        if not position:
            logger.error(f"لا صفقة: {symbol} {position_side}")
            return False

        quantity = abs(float(position["positionAmt"]))
        if quantity <= 0:
            return False

        close_side = "SELL" if position_side == "LONG" else "BUY"

        try:
            open_orders = get_open_orders(symbol)
            for order in open_orders:
                try:
                    client_obj.futures_cancel_order(symbol=symbol, orderId=order['orderId'])
                except:
                    pass
        except:
            pass

        try:
            algo_orders = get_open_algo_orders(symbol)
            for order in algo_orders:
                cancel_algo_order(symbol, order.get('algoId', order.get('orderId')))
        except:
            pass

        try:
            client_obj.futures_create_order(
                symbol=symbol,
                side=close_side,
                type="MARKET",
                quantity=quantity,
                positionSide=position_side,
                reduceOnly="true"
            )
            logger.info(f"✅ إغلاق: {symbol} {position_side}")
            remove_trailing_sl_tracking(symbol, position_side)
            return True
        except BinanceAPIException as e:
            if e.code == -4061:
                try:
                    client_obj.futures_create_order(
                        symbol=symbol,
                        side=close_side,
                        type="MARKET",
                        quantity=quantity,
                        positionSide=position_side
                    )
                    remove_trailing_sl_tracking(symbol, position_side)
                    return True
                except:
                    return False
            return False

    except Exception as e:
        logger.error(f"خطأ إغلاق: {e}")
        return False


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


# ==================== Trailing SL ====================

_trailing_sl_positions = {}
_consecutive_losses = 0
_pause_until = 0


def setup_trailing_sl(symbol, position_side, entry_price, quantity, sl_price=None):
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

        if not data['breakeven_set'] and profit_percent >= BREAKEVEN_TRIGGER:
            if update_sl_order(symbol, position_side, data['current_sl'], entry_price, quantity):
                data['current_sl'] = entry_price
                data['breakeven_set'] = True
                updated = True
                logger.info(f"🔒 {symbol} - Breakeven")

        if data['breakeven_set'] and profit_percent >= TRAILING_SL_TRIGGER:
            if position_side == "LONG":
                new_sl = data['highest_price'] * (1 - TRAILING_SL_DISTANCE / 100)
                if new_sl > data['current_sl']:
                    if update_sl_order(symbol, position_side, data['current_sl'], new_sl, quantity):
                        data['current_sl'] = new_sl
                        data['trailing_active'] = True
                        updated = True
            else:
                new_sl = data['lowest_price'] * (1 + TRAILING_SL_DISTANCE / 100)
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

def record_trade_result(profit):
    global _consecutive_losses, _pause_until

    try:
        if profit < 0:
            _consecutive_losses += 1
            logger.warning(f"⚠️ خسارة: {_consecutive_losses}/{MAX_CONSECUTIVE_LOSSES}")

            if _consecutive_losses >= MAX_CONSECUTIVE_LOSSES:
                _pause_until = time.time() + (PAUSE_DURATION_MINUTES * 60)
                logger.warning(f"🛑 توقف {PAUSE_DURATION_MINUTES} دقيقة")
                return True
        else:
            if _consecutive_losses > 0:
                logger.info("✅ ربح - إعادة تعيين")
            _consecutive_losses = 0

        return False
    except:
        return False


def is_trading_paused():
    global _pause_until

    try:
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
                              tp_levels, tp_ratios, sl_percent=None):
    """إنشاء أوامر TP متعددة"""
    try:
        client_obj = get_client()
        if not client_obj:
            return {'sl_success': False, 'tp_orders': [], 'total_tp_quantity': 0}

        # 🔥 التحقق من مجموع النسب
        ratios_sum = sum(tp_ratios)
        if abs(ratios_sum - 1.0) > 0.01:
            logger.error(f"❌ مجموع نسب TP = {ratios_sum} يجب أن يكون 1.0")
            return {'sl_success': False, 'tp_orders': [], 'total_tp_quantity': 0}

        results = {'sl_success': False, 'tp_orders': [], 'total_tp_quantity': 0}
        
        close_side = "SELL" if position_side == "LONG" else "BUY"

        # ==================== SL ====================
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
                    logger.info(f"✅ SL: {formatted_sl} ({actual_sl_percent:.2f}%)")
                else:
                    logger.error(f"❌ فشل إنشاء SL بعد {TP_SL_MAX_RETRIES} محاولات!")

        # ==================== TP متعدد ====================
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
                    logger.info(f"✅ TP{i+1}: {tp_percent}% @ {formatted_tp}")
                else:
                    logger.error(f"❌ فشل TP{i+1} بعد {TP_SL_MAX_RETRIES} محاولات")
                    results['tp_orders'].append({
                        'level': i + 1,
                        'tp_percent': tp_percent,
                        'success': False
                    })

        return results

    except Exception as e:
        logger.error(f"خطأ: {e}")
        return {'sl_success': False, 'tp_orders': [], 'total_tp_quantity': 0}


def place_market_order_with_multiple_tp(symbol, side, amount_usdt, leverage,
                                        tp_levels=None, tp_ratios=None, sl_percent=None):
    """وضع أمر مع TP متعدد + التحقق الإجباري"""
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

        notional = float(amount_usdt) * float(leverage)
        total_qty = _round_quantity(symbol, notional / price)

        if total_qty <= 0:
            logger.error(f"كمية غير صالحة: {total_qty}")
            return None

        client_obj.futures_change_leverage(symbol=symbol, leverage=int(leverage))

        # ==================== فتح الصفقة ====================
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

        # ==================== إنشاء TP/SL ====================
        logger.info(f"📊 إنشاء TP/SL...")
        
        tp_results = create_multiple_tp_orders(
            symbol=symbol,
            position_side=positionSide,
            total_quantity=actual_qty,
            entry_price=entry_price,
            tp_levels=tp_levels,
            tp_ratios=tp_ratios,
            sl_percent=sl_percent
        )

        # ==================== 🔥 التحقق الإجباري ====================
        time.sleep(2)
        
        has_tp, has_sl, details = verify_tp_sl_created(symbol, positionSide)
        
        logger.info(f"🔍 التحقق: TP={has_tp} ({details.get('tp_count', 0)}), SL={has_sl} ({details.get('sl_count', 0)})")
        
        if VERIFY_TP_SL_AFTER_CREATION and not has_sl:
            logger.error(f"🚨 فشل SL - إغلاق الصفقة فوراً!")
            
            close_position_safe(symbol, positionSide)
            
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
    """إعادة إنشاء أوامر TP لصفقة مفتوحة"""
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
    """التحقق من TP/SL وإعادة الإنشاء إذا لزم"""
    try:
        positions = get_open_positions()
        fixed = 0

        for position in positions:
            symbol = position["symbol"]
            position_side = position["positionSide"]
            
            has_tp, has_sl, details = verify_tp_sl_created(symbol, position_side)
            
            if not has_sl:
                logger.warning(f"⚠️ {symbol} بدون SL - محاولة إعادة الإنشاء")
                
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
                    logger.error(f"🛑 {symbol} تخطى مستوى SL فعلياً ({current_price} vs {formatted_sl}) - إغلاق فوري")
                    if close_position_safe(symbol, position_side):
                        fixed += 1
                        logger.info(f"✅ تم إغلاق {symbol} وقائياً (كان بدون حماية)")
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
                    logger.error(f"❌ فشل إنشاء SL لـ {symbol} نهائياً - إغلاق وقائي")
                    if close_position_safe(symbol, position_side):
                        logger.info(f"✅ تم إغلاق {symbol} وقائياً بعد فشل SL")

            elif not has_tp:
                logger.warning(f"⚠️ {symbol} بدون TP - محاولة إعادة الإنشاء")

                entry_price = float(position["entryPrice"])
                quantity = abs(float(position["positionAmt"]))

                if recreate_missing_tp(symbol, position_side, entry_price, quantity):
                    fixed += 1
                    logger.info(f"✅ تم إعادة إنشاء TP لـ {symbol}")
                else:
                    logger.error(f"❌ فشل إعادة إنشاء TP لـ {symbol}")

        return fixed
    except Exception as e:
        logger.error(f"خطأ: {e}")
        return 0


if __name__ == "__main__":
    print("🚀 core_functions.py - النسخة النهائية")
    print(f"✅ الاتصال: {'ناجح' if client else 'فشل'}")
    print(f"🔍 التحقق من TP/SL: {'مفعل' if VERIFY_TP_SL_AFTER_CREATION else 'معطل'}")
    print(f"🔒 إغلاق عند فشل SL: {'مفعل' if CLOSE_ON_TP_SL_FAIL else 'معطل'}")
    print(f"📊 فلتر السيولة: {'مفعل' if ENABLE_VOLUME_FILTER else 'معطل'} ({MIN_VOLUME_24H_USDT/1e6:.0f}M USDT)")