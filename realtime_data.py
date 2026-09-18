# ==================================================
# 📁 ملف: realtime_data.py - الإصدار 1.0
# 🔧 الوصف:
#    - WebSocket لحظي من Binance USDⓈ-M Futures
#    - حساب Order Book Imbalance (OBI)
#    - حساب Buy/Sell Pressure من aggTrade
#    - حساب Trade Velocity (سرعة التداول)
#    - كشف Liquidation Events (forceOrder)
#    - بدون أي مفاتيح API (تدفق عام)
# 📅 التاريخ: 2026-09-18
# ==================================================

import logging
import json
import time
import threading
from collections import deque
from datetime import datetime

logger = logging.getLogger("realtime_data")

try:
    import websocket  # websocket-client
    WEBSOCKET_AVAILABLE = True
except ImportError:
    WEBSOCKET_AVAILABLE = False
    logger.warning("⚠️ websocket-client غير مثبت. شغّل: pip install websocket-client")


# ==================== إعدادات ====================

# نقطة النهاية الجديدة (القديمة ستُوقف في 23 أبريل 2026)
WS_BASE_URL = "wss://fstream.binance.com/stream"

# نافذة زمنية لحساب الضغط (بالثواني)
PRESSURE_WINDOW_SECONDS = 30

# عدد المستويات في دفتر الأوامر
DEPTH_LEVELS = 20

# الحد الأدنى لقيمة التصفية لاعتبارها "حدث مهم" (USDT)
LIQUIDATION_THRESHOLD_USDT = 50000


# ==================== هيكل البيانات لكل عملة ====================

class SymbolData:
    """يخزّن البيانات اللحظية لعملة واحدة"""

    def __init__(self, symbol):
        self.symbol = symbol

        # aggTrade - نافذة متحركة
        self.trades = deque(maxlen=500)  # (timestamp, price, qty, is_buyer_maker)

        # depth - أفضل 20 مستوى
        self.bids = {}  # price -> qty
        self.asks = {}  # price -> qty
        self.last_depth_update = 0

        # forceOrder (تصفيات)
        self.liquidations = deque(maxlen=50)  # (timestamp, side, qty, price)

        # قيم محسوبة
        self.obi = 0.0                # Order Book Imbalance (-1 إلى +1)
        self.buy_pressure = 0.0       # ضغط الشراء (0 إلى 1)
        self.sell_pressure = 0.0      # ضغط البيع (0 إلى 1)
        self.trade_velocity = 0.0     # صفقات/ثانية
        self.liquidation_bias = 0.0   # انحياز التصفيات (-1 إلى +1)

        self.last_update = 0
        self.connected = False


# ==================== المخزن العام ====================

_symbols_data = {}
_data_lock = threading.Lock()
_ws_thread = None
_ws_running = False
_subscribed_symbols = set()


# ==================== الحسابات ====================

def _recalculate_obi(sym_data):
    """
    Order Book Imbalance
    OBI = (bid_volume - ask_volume) / (bid_volume + ask_volume)
    النطاق: -1 (بيع قوي) إلى +1 (شراء قوي)
    """
    try:
        bid_vol = sum(sym_data.bids.values())
        ask_vol = sum(sym_data.asks.values())
        total = bid_vol + ask_vol

        if total <= 0:
            sym_data.obi = 0.0
            return

        sym_data.obi = round((bid_vol - ask_vol) / total, 4)
    except Exception as e:
        logger.error(f"خطأ OBI لـ {sym_data.symbol}: {e}")
        sym_data.obi = 0.0


def _recalculate_pressure(sym_data):
    """
    Buy/Sell Pressure من aggTrade
    نقيس حجم الشراء مقابل البيع في نافذة زمنية
    """
    try:
        now = time.time()
        cutoff = now - PRESSURE_WINDOW_SECONDS

        buy_vol = 0.0
        sell_vol = 0.0
        count = 0

        for ts, price, qty, is_buyer_maker in sym_data.trades:
            if ts < cutoff:
                continue
            count += 1

            # is_buyer_maker = True تعني أن المشتري هو صاحب الأمر المحدد
            # أي أن البائع هو من "ضرب" السوق => بيع عدواني
            if is_buyer_maker:
                sell_vol += qty * price
            else:
                buy_vol += qty * price

        total = buy_vol + sell_vol
        if total <= 0:
            sym_data.buy_pressure = 0.5
            sym_data.sell_pressure = 0.5
            sym_data.trade_velocity = 0.0
            return

        sym_data.buy_pressure = round(buy_vol / total, 4)
        sym_data.sell_pressure = round(sell_vol / total, 4)
        sym_data.trade_velocity = round(count / PRESSURE_WINDOW_SECONDS, 2)

    except Exception as e:
        logger.error(f"خطأ Pressure لـ {sym_data.symbol}: {e}")


def _recalculate_liquidation_bias(sym_data):
    """
    انحياز التصفيات
    موجب = تصفيات شورت (bullish)
    سالب = تصفيات لونج (bearish)
    """
    try:
        now = time.time()
        cutoff = now - 300  # آخر 5 دقائق

        long_liq = 0.0   # تصفيات مراكز شراء
        short_liq = 0.0  # تصفيات مراكز بيع

        for ts, side, qty, price in sym_data.liquidations:
            if ts < cutoff:
                continue

            value = qty * price
            if side == "SELL":
                # SELL في forceOrder = تصفية مركز LONG
                long_liq += value
            else:
                short_liq += value

        total = long_liq + short_liq
        if total <= 0:
            sym_data.liquidation_bias = 0.0
            return

        sym_data.liquidation_bias = round((short_liq - long_liq) / total, 4)

    except Exception as e:
        logger.error(f"خطأ Liquidations لـ {sym_data.symbol}: {e}")


# ==================== معالجات الرسائل ====================

def _handle_agg_trade(symbol, data):
    """معالجة صفقة فردية"""
    try:
        with _data_lock:
            if symbol not in _symbols_data:
                return

            sym_data = _symbols_data[symbol]
            trade = data.get('data', data)

            price = float(trade['p'])
            qty = float(trade['q'])
            is_buyer_maker = trade['m']
            ts = trade['T'] / 1000.0

            sym_data.trades.append((ts, price, qty, is_buyer_maker))
            sym_data.last_update = time.time()
            sym_data.connected = True

            _recalculate_pressure(sym_data)

    except Exception as e:
        logger.error(f"خطأ aggTrade {symbol}: {e}")


def _handle_depth(symbol, data):
    """معالجة تحديث دفتر الأوامر"""
    try:
        with _data_lock:
            if symbol not in _symbols_data:
                return

            sym_data = _symbols_data[symbol]
            depth = data.get('data', data)

            bids = depth.get('b', [])
            asks = depth.get('a', [])

            # تحديث كامل (snapshot)
            sym_data.bids.clear()
            sym_data.asks.clear()

            for price, qty in bids[:DEPTH_LEVELS]:
                p = float(price)
                q = float(qty)
                if q > 0:
                    sym_data.bids[p] = q

            for price, qty in asks[:DEPTH_LEVELS]:
                p = float(price)
                q = float(qty)
                if q > 0:
                    sym_data.asks[p] = q

            sym_data.last_depth_update = time.time()
            sym_data.last_update = time.time()

            _recalculate_obi(sym_data)

    except Exception as e:
        logger.error(f"خطأ depth {symbol}: {e}")


def _handle_force_order(symbol, data):
    """معالجة أمر تصفية إجباري"""
    try:
        with _data_lock:
            if symbol not in _symbols_data:
                return

            sym_data = _symbols_data[symbol]
            fo = data.get('data', data).get('o', {})

            side = fo.get('S', '')
            qty = float(fo.get('q', 0))
            price = float(fo.get('p', 0))
            ts = fo.get('T', int(time.time() * 1000)) / 1000.0

            value = qty * price
            if value < LIQUIDATION_THRESHOLD_USDT:
                return

            sym_data.liquidations.append((ts, side, qty, price))
            _recalculate_liquidation_bias(sym_data)

            logger.info(
                f"💥 تصفية {symbol} | {side} | "
                f"{qty} @ {price} = {value:,.0f} USDT"
            )

    except Exception as e:
        logger.error(f"خطأ forceOrder {symbol}: {e}")


# ==================== خيط WebSocket ====================

def _on_message(ws, message):
    """موزّع الرسائل"""
    try:
        payload = json.loads(message)

        # تدفق مدمج: {"stream": "...", "data": {...}}
        stream = payload.get('stream', '')
        if not stream:
            return

        # استخراج الـ symbol
        if '@aggTrade' in stream:
            symbol = stream.split('@')[0].upper()
            _handle_agg_trade(symbol, payload)

        elif '@depth' in stream:
            symbol = stream.split('@')[0].upper()
            _handle_depth(symbol, payload)

        elif '@forceOrder' in stream:
            symbol = stream.split('@')[0].upper()
            _handle_force_order(symbol, payload)

    except Exception as e:
        logger.error(f"خطأ في معالجة رسالة WebSocket: {e}")


def _on_error(ws, error):
    logger.error(f"❌ خطأ WebSocket: {error}")


def _on_close(ws, close_status, close_msg):
    global _ws_running
    logger.warning(f"⚠️ WebSocket أُغلق: {close_status} - {close_msg}")
    _ws_running = False


def _on_open(ws):
    logger.info("✅ WebSocket متصل")


def _build_stream_url(symbols):
    """
    بناء URL للتدفق المدمج
    كل عملة: aggTrade + depth@100ms + forceOrder
    """
    streams = []

    for sym in symbols:
        s = sym.lower()
        streams.append(f"{s}@aggTrade")
        streams.append(f"{s}@depth{DEPTH_LEVELS}@100ms")
        streams.append(f"{s}@forceOrder")

    # Binance يدعم حتى 1024 stream في الاتصال الواحد
    # لكن عملياً نبقى تحت 200 stream
    if len(streams) > 200:
        streams = streams[:200]
        logger.warning(f"⚠️ تم قطع عدد التدفقات إلى 200")

    return f"{WS_BASE_URL}?streams={'/'.join(streams)}"


def _ws_worker():
    """خيط الاتصال المستمر"""
    global _ws_running

    while _ws_running:
        try:
            with _data_lock:
                symbols = list(_subscribed_symbols)

            if not symbols:
                time.sleep(2)
                continue

            url = _build_stream_url(symbols)
            logger.info(f"🔌 اتصال بـ WebSocket ({len(symbols)} عملة)...")

            ws = websocket.WebSocketApp(
                url,
                on_open=_on_open,
                on_message=_on_message,
                on_error=_on_error,
                on_close=_on_close,
            )

            ws.run_forever(ping_interval=20, ping_timeout=10)

        except Exception as e:
            logger.error(f"خطأ في خيط WebSocket: {e}")

        if _ws_running:
            logger.info("🔄 إعادة اتصال WebSocket بعد 5 ثواني...")
            time.sleep(5)


# ==================== الواجهة العامة ====================

def init_realtime(symbols):
    """
    تهيئة الاتصال اللحظي لعملات محددة
    يجب استدعاؤها مرة واحدة عند بدء البوت
    """
    global _ws_thread, _ws_running

    if not WEBSOCKET_AVAILABLE:
        logger.error("❌ websocket-client غير مثبت")
        return False

    if _ws_running:
        logger.info("ℹ️ WebSocket يعمل بالفعل")
        return True

    with _data_lock:
        for sym in symbols:
            if sym not in _symbols_data:
                _symbols_data[sym] = SymbolData(sym)
            _subscribed_symbols.add(sym)

    _ws_running = True
    _ws_thread = threading.Thread(target=_ws_worker, daemon=True)
    _ws_thread.start()

    logger.info(f"✅ تم تشغيل WebSocket لـ {len(symbols)} عملة")
    return True


def subscribe_symbol(symbol):
    """إضافة عملة جديدة للاشتراك (سيُعاد الاتصال)"""
    global _ws_running

    with _data_lock:
        if symbol in _subscribed_symbols:
            return

        _subscribed_symbols.add(symbol)
        if symbol not in _symbols_data:
            _symbols_data[symbol] = SymbolData(symbol)

    logger.info(f"➕ إضافة {symbol} للاشتراك (سيُعاد الاتصال)")

    # إعادة تشغيل الاتصال لضم العملة الجديدة
    _ws_running = False
    time.sleep(1)
    _ws_running = True
    threading.Thread(target=_ws_worker, daemon=True).start()


def stop_realtime():
    """إيقاف الاتصال"""
    global _ws_running
    _ws_running = False
    logger.info("🛑 إيقاف WebSocket")


# ==================== قراءة البيانات ====================

def get_realtime_metrics(symbol):
    """
    الحصول على المقاييس اللحظية لعملة

    Returns:
        dict أو None إذا لا توجد بيانات
    """
    try:
        with _data_lock:
            if symbol not in _symbols_data:
                return None

            sd = _symbols_data[symbol]

            # نتحقق من حداثة البيانات (أقل من 30 ثانية)
            age = time.time() - sd.last_update if sd.last_update > 0 else 999

            if age > 30:
                return {
                    'symbol': symbol,
                    'stale': True,
                    'age_seconds': round(age, 1),
                    'obi': 0.0,
                    'buy_pressure': 0.5,
                    'sell_pressure': 0.5,
                    'trade_velocity': 0.0,
                    'liquidation_bias': 0.0,
                }

            return {
                'symbol': symbol,
                'stale': False,
                'age_seconds': round(age, 1),
                'obi': sd.obi,
                'buy_pressure': sd.buy_pressure,
                'sell_pressure': sd.sell_pressure,
                'trade_velocity': sd.trade_velocity,
                'liquidation_bias': sd.liquidation_bias,
                'connected': sd.connected,
                'bids_count': len(sd.bids),
                'asks_count': len(sd.asks),
            }
    except Exception as e:
        logger.error(f"خطأ في قراءة بيانات {symbol}: {e}")
        return None


def get_realtime_score_adjustment(symbol, direction):
    """
    🔥 حساب تعديل النقاط بناءً على البيانات اللحظية

    Returns:
        (adjustment, details)
        adjustment: -5 إلى +10 نقاط تُضاف/تُخصم من النتيجة النهائية
    """
    try:
        m = get_realtime_metrics(symbol)
        if not m or m.get('stale'):
            return 0, {'reason': 'بيانات لحظية غير متوفرة'}

        adjustment = 0
        reasons = []

        obi = m['obi']
        buy_p = m['buy_pressure']
        liq_bias = m['liquidation_bias']
        velocity = m['trade_velocity']

        # ==================== OBI ====================
        if direction == "BUY":
            if obi >= 0.3:
                adjustment += 4
                reasons.append(f"OBI قوي للشراء ({obi:+.2f})")
            elif obi >= 0.15:
                adjustment += 2
                reasons.append(f"OBI إيجابي ({obi:+.2f})")
            elif obi <= -0.3:
                adjustment -= 4
                reasons.append(f"OBI ضد الشراء ({obi:+.2f})")
            elif obi <= -0.15:
                adjustment -= 2
                reasons.append(f"OBI سلبي ({obi:+.2f})")
        else:  # SELL
            if obi <= -0.3:
                adjustment += 4
                reasons.append(f"OBI قوي للبيع ({obi:+.2f})")
            elif obi <= -0.15:
                adjustment += 2
                reasons.append(f"OBI سلبي ({obi:+.2f})")
            elif obi >= 0.3:
                adjustment -= 4
                reasons.append(f"OBI ضد البيع ({obi:+.2f})")
            elif obi >= 0.15:
                adjustment -= 2
                reasons.append(f"OBI إيجابي ({obi:+.2f})")

        # ==================== Buy/Sell Pressure ====================
        if direction == "BUY":
            if buy_p >= 0.65:
                adjustment += 3
                reasons.append(f"ضغط شراء قوي ({buy_p:.0%})")
            elif buy_p <= 0.35:
                adjustment -= 3
                reasons.append(f"ضغط بيع مسيطر ({m['sell_pressure']:.0%})")
        else:
            if m['sell_pressure'] >= 0.65:
                adjustment += 3
                reasons.append(f"ضغط بيع قوي ({m['sell_pressure']:.0%})")
            elif m['sell_pressure'] <= 0.35:
                adjustment -= 3
                reasons.append(f"ضغط شراء مسيطر ({buy_p:.0%})")

        # ==================== Liquidation Bias ====================
        if direction == "BUY":
            if liq_bias >= 0.4:
                adjustment += 2
                reasons.append(f"تصفيات شورت قوية ({liq_bias:+.2f})")
            elif liq_bias <= -0.4:
                adjustment -= 2
                reasons.append(f"تصفيات لونج قوية ({liq_bias:+.2f})")
        else:
            if liq_bias <= -0.4:
                adjustment += 2
                reasons.append(f"تصفيات لونج قوية ({liq_bias:+.2f})")
            elif liq_bias >= 0.4:
                adjustment -= 2
                reasons.append(f"تصفيات شورت قوية ({liq_bias:+.2f})")

        # ==================== Trade Velocity ====================
        # سرعة عالية جداً = نشاط غير عادي، قد يدل على حركة وشيكة
        if velocity >= 15:
            adjustment += 1
            reasons.append(f"نشاط تداول مرتفع ({velocity:.1f} صفقة/ث)")
        elif velocity <= 0.5:
            adjustment -= 1
            reasons.append(f"نشاط ضعيف ({velocity:.1f} صفقة/ث)")

        # تحديد السقف
        adjustment = max(-5, min(10, adjustment))

        return adjustment, {
            'obi': obi,
            'buy_pressure': buy_p,
            'sell_pressure': m['sell_pressure'],
            'liquidation_bias': liq_bias,
            'trade_velocity': velocity,
            'reasons': reasons,
        }

    except Exception as e:
        logger.error(f"خطأ في حساب تعديل {symbol}: {e}")
        return 0, {'reason': f'خطأ: {e}'}


def is_realtime_ready(symbol):
    """التحقق من جاهزية بيانات عملة"""
    m = get_realtime_metrics(symbol)
    if not m or m.get('stale'):
        return False
    return m.get('bids_count', 0) > 0 and m.get('asks_count', 0) > 0


def get_realtime_status():
    """حالة النظام اللحظي"""
    with _data_lock:
        ready = 0
        stale = 0
        for sym in _subscribed_symbols:
            if is_realtime_ready(sym):
                ready += 1
            else:
                stale += 1

        return {
            'running': _ws_running,
            'subscribed': len(_subscribed_symbols),
            'ready': ready,
            'stale': stale,
        }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    print("🧪 اختبار WebSocket اللحظي...")
    print("سيتم الاشتراك في BTCUSDT و ETHUSDT لمدة 30 ثانية\n")

    init_realtime(["BTCUSDT", "ETHUSDT"])
    time.sleep(10)

    for i in range(6):
        print(f"\n--- {datetime.now().strftime('%H:%M:%S')} ---")
        for sym in ["BTCUSDT", "ETHUSDT"]:
            m = get_realtime_metrics(sym)
            if m:
                print(f"{sym}: OBI={m['obi']:+.3f} | "
                      f"Buy={m['buy_pressure']:.0%} | "
                      f"Vel={m['trade_velocity']:.1f} | "
                      f"Liq={m['liquidation_bias']:+.2f}")
        time.sleep(5)

    print("\n📊 الحالة النهائية:", get_realtime_status())
    stop_realtime()