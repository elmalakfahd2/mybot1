"""
Market Structure + HTF Bias + Correlation Guard
يضيف سياقاً أقوى للدخول دون رفع التعقيد كثيراً.
"""
import time
import logging
from typing import Dict, Any, List

import core_functions as core

logger = logging.getLogger("market_structure")

_CACHE: Dict[str, Dict[str, Any]] = {}

GROUPS = {
    "ETH_ECO": {"ETH", "SOL", "AVAX", "NEAR", "ARB", "OP", "MATIC", "FTM", "APT", "SUI", "SEI", "INJ"},
    "BTC_ECO": {"BTC", "BCH", "LTC"},
    "MEME": {"DOGE", "SHIB", "1000SHIB", "1000PEPE", "PEPE", "FLOKI", "BONK", "WIF", "MEME"},
    "DEFI": {"UNI", "AAVE", "CRV", "MKR", "SNX", "COMP", "SUSHI", "1INCH"},
    "ORACLE": {"LINK", "API3", "TRB", "BAND"},
    "AI": {"FET", "RNDR", "AGIX", "OCEAN", "GRT", "ARKM", "NMR"},
    "GAMING": {"SAND", "MANA", "AXS", "ENJ", "GALA", "IMX", "BEAMX"},
    "DOT_ECO": {"DOT", "KSM", "GLMR", "MOVR"},
    "EXCHANGE": {"BNB", "OKB", "KCS", "CRO"},
}


def _cache_get(key, ttl=300):
    item = _CACHE.get(key)
    if not item:
        return None
    if time.time() - item.get("ts", 0) > ttl:
        return None
    return item.get("data")


def _cache_set(key, data, ttl=300):
    _CACHE[key] = {"ts": time.time(), "data": data}


def _closes(klines):
    try:
        return [float(k[4]) for k in klines if k and len(k) > 4]
    except Exception:
        return []


def _highs(klines):
    try:
        return [float(k[2]) for k in klines if k and len(k) > 2]
    except Exception:
        return []


def _lows(klines):
    try:
        return [float(k[3]) for k in klines if k and len(k) > 3]
    except Exception:
        return []


def _ema(values, period):
    if not values or len(values) < period:
        return None
    k = 2 / (period + 1)
    ema = sum(values[:period]) / period
    for v in values[period:]:
        ema = v * k + ema * (1 - k)
    return ema


def _rsi(values, period=14):
    if not values or len(values) < period + 1:
        return None
    gains, losses = [], []
    for i in range(1, len(values)):
        ch = values[i] - values[i - 1]
        gains.append(max(ch, 0))
        losses.append(max(-ch, 0))
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def get_htf_bias(symbol: str) -> Dict[str, Any]:
    cached = _cache_get(f"htf_{symbol}")
    if cached:
        return cached

    result = {"bias": "UNKNOWN", "score": 0, "details": {}}
    try:
        score = 0
        details = {}
        for interval in ("15m", "1h"):
            klines = core.get_klines(symbol, interval, 120) or []
            closes = _closes(klines)
            if len(closes) < 60:
                continue
            ema20 = _ema(closes, 20)
            ema50 = _ema(closes, 50)
            rsi = _rsi(closes, 14)
            close = closes[-1]
            if not ema20 or not ema50 or not rsi:
                continue
            bull = close > ema20 and ema20 > ema50 and rsi > 50
            bear = close < ema20 and ema20 < ema50 and rsi < 50
            if bull:
                score += 1
            elif bear:
                score -= 1
            details[interval] = {
                "close": round(close, 8),
                "ema20": round(ema20, 8),
                "ema50": round(ema50, 8),
                "rsi": round(rsi, 2),
                "bull": bull,
                "bear": bear,
            }
        if score >= 1:
            result["bias"] = "BULLISH"
        elif score <= -1:
            result["bias"] = "BEARISH"
        else:
            result["bias"] = "RANGE"
        result["score"] = score
        result["details"] = details
    except Exception as e:
        logger.debug(f"htf bias {symbol}: {e}")
    _cache_set(f"htf_{symbol}", result, ttl=300)
    return result


def get_structure(symbol: str, direction: str) -> Dict[str, Any]:
    cached = _cache_get(f"struct_{symbol}_{direction}")
    if cached:
        return cached

    result = {
        "setup": "NONE",
        "bos_bull": False,
        "bos_bear": False,
        "pullback_long": False,
        "pullback_short": False,
        "range_reversal": False,
    }
    try:
        klines = core.get_klines(symbol, "5m", 120) or []
        closes = _closes(klines)
        highs = _highs(klines)
        lows = _lows(klines)
        if len(closes) < 60 or len(highs) < 60 or len(lows) < 60:
            _cache_set(f"struct_{symbol}_{direction}", result, ttl=180)
            return result

        close = closes[-1]
        ema20 = _ema(closes, 20)
        ema20_prev = _ema(closes[:-1], 20)
        rsi = _rsi(closes, 14) or 50

        # منطقة الهيكل الأخيرة بدون آخر 3 شموع لتجنب إعادة الرسم
        look = min(18, len(highs) - 4)
        recent_high = max(highs[-look:-3])
        recent_low = min(lows[-look:-3])

        bos_bull = close > recent_high
        bos_bear = close < recent_low

        touch_long = min(lows[-4:-1]) <= (ema20 or close) * 1.002
        touch_short = max(highs[-4:-1]) >= (ema20 or close) * 0.998
        pullback_long = bool(ema20 and ema20_prev and ema20 >= ema20_prev and close > ema20 and touch_long)
        pullback_short = bool(ema20 and ema20_prev and ema20 <= ema20_prev and close < ema20 and touch_short)

        range_reversal = (not bos_bull and not bos_bear and abs((close / ema20) - 1) < 0.004) if ema20 else False

        result.update({
            "bos_bull": bos_bull,
            "bos_bear": bos_bear,
            "pullback_long": pullback_long,
            "pullback_short": pullback_short,
            "range_reversal": range_reversal,
            "recent_high": recent_high,
            "recent_low": recent_low,
            "ema20": ema20,
            "rsi": rsi,
        })

        if direction == "BUY":
            if bos_bull:
                result["setup"] = "BREAKOUT"
            elif pullback_long:
                result["setup"] = "PULLBACK"
            elif range_reversal and rsi <= 38:
                result["setup"] = "RANGE_REVERSAL"
        else:
            if bos_bear:
                result["setup"] = "BREAKOUT"
            elif pullback_short:
                result["setup"] = "PULLBACK"
            elif range_reversal and rsi >= 62:
                result["setup"] = "RANGE_REVERSAL"
    except Exception as e:
        logger.debug(f"structure {symbol}: {e}")
    _cache_set(f"struct_{symbol}_{direction}", result, ttl=180)
    return result


def _symbol_group(symbol: str):
    for g, members in GROUPS.items():
        if symbol in members:
            return g
    return None


def correlation_conflict(symbol: str, direction: str) -> Dict[str, Any]:
    result = {"conflict": False, "reason": "", "group": _symbol_group(symbol)}
    try:
        group = result["group"]
        if not group:
            return result
        positions = core.get_open_positions() or []
        for pos in positions:
            sym = pos.get("symbol")
            side = pos.get("positionSide")
            if not sym or sym == symbol:
                continue
            if _symbol_group(sym) == group and side == direction:
                result["conflict"] = True
                result["reason"] = f"مركز مفتوح مترابط: {sym} {direction}"
                break
    except Exception as e:
        logger.debug(f"correlation {symbol}: {e}")
    return result


def get_market_context(symbol: str, direction: str) -> Dict[str, Any]:
    htf = get_htf_bias(symbol)
    structure = get_structure(symbol, direction)
    correlation = correlation_conflict(symbol, direction)
    return {"htf": htf, "structure": structure, "correlation": correlation}
