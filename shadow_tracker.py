# ==================================================
# 📁 ملف: shadow_tracker.py - v5.9 (صفقات الظل)
# 🔧 الوصف:
#    - يسجّل الإشارات التي رُفضت (نقاط أقل من الحد / فيتو الذكاء الاصطناعي) كصفقات "ظل"
#    - يتتبعها على شموع 5m ويحاكي نفس منطق البوت الفعلي (SL، Breakeven، TP1/2/3، العمولة)
#      دون أي مال حقيقي، ثم يحسب: هل الرفض كان صحيحاً؟
#    - يغذي التعلم: إن أثبتت الإشارات المرفوضة ربحيتها، يخفف رفع الحد تلقائياً (adaptive_rules)
#    - الحفظ: ملف محلي + Firebase (يبقى بعد إعادة النشر)
# ⚠️ محاكاة تقريبية: لا تنزلق الأسعار، وإن لمست الشمعة الوقف والهدف معاً يُحتسب الوقف (متحفظ)
# ==================================================

import os
import json
import time
import logging
import threading
from datetime import datetime, timedelta

logger = logging.getLogger("shadow_tracker")

SHADOW_FILE = "shadow_trades.json"
FIREBASE_DOC = "shadow_trades"

_lock = threading.RLock()
_state = None          # {'open': [...], 'closed': [...]}
_dirty = False
_last_flush = 0


def _c(name, default):
    try:
        import config
        return getattr(config, name, default)
    except Exception:
        return default


def enabled():
    return bool(_c('ENABLE_SHADOW_TRACKING', True))


# ==================== التخزين ====================

def _ensure_loaded():
    global _state
    if _state is not None:
        return
    data = None
    try:
        if os.path.exists(SHADOW_FILE):
            with open(SHADOW_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
    except Exception as e:
        logger.warning(f"⚠️ قراءة {SHADOW_FILE}: {e}")
    if not data:
        try:
            import firebase_backup
            data = firebase_backup.load_doc(FIREBASE_DOC)
            if data:
                logger.info("✅ استُرجعت صفقات الظل من Firebase")
        except Exception:
            data = None
    if not isinstance(data, dict):
        data = {}
    _state = {'open': list(data.get('open', [])), 'closed': list(data.get('closed', []))}


def _save_local():
    try:
        with open(SHADOW_FILE, "w", encoding="utf-8") as f:
            json.dump(_state, f, ensure_ascii=False)
    except Exception as e:
        logger.debug(f"حفظ محلي: {e}")


def flush(force=False):
    """حفظ في Firebase (على الأكثر مرة كل دقيقتين ما لم يُطلب بالقوة)"""
    global _dirty, _last_flush
    with _lock:
        if _state is None:
            return False
        _save_local()
        if not _dirty and not force:
            return True
        if not force and time.time() - _last_flush < 120:
            return True
        try:
            import firebase_backup
            payload = {'open': _state['open'][-80:], 'closed': _state['closed'][-400:]}
            if firebase_backup.save_doc(FIREBASE_DOC, payload):
                _dirty = False
                _last_flush = time.time()
                return True
        except Exception as e:
            logger.debug(f"Firebase: {e}")
        return False


# ==================== التسجيل ====================

def record(symbol, direction, entry_price, score, tier, ai_rec='', ai_conf=0, details=None):
    """
    تسجيل إشارة مرفوضة كصفقة ظل.
    tier: below_ai_gate | below_required | ai_veto
    """
    global _dirty
    if not enabled():
        return False
    try:
        if direction not in ("BUY", "SELL") or not entry_price:
            return False
        with _lock:
            _ensure_loaded()
            max_open = int(_c('SHADOW_MAX_OPEN', 60))
            if len(_state['open']) >= max_open:
                return False
            for s in _state['open']:
                if s['symbol'] == symbol and s['direction'] == direction:
                    return False  # واحدة مفتوحة لكل عملة/اتجاه
            slim = {}
            if isinstance(details, dict):
                slim = {k: v for k, v in details.items()
                        if isinstance(v, (int, float)) and not isinstance(v, bool)}
            _state['open'].append({
                'symbol': symbol,
                'direction': direction,
                'entry_price': float(entry_price),
                'score': int(score),
                'tier': tier,
                'ai_rec': ai_rec or '',
                'ai_conf': float(ai_conf or 0),
                'details': slim,
                'entry_ts': int(time.time() * 1000),
                'entry_time': datetime.now().isoformat(),
                'hour': datetime.now().hour,
            })
            _dirty = True
            _save_local()
        return True
    except Exception as e:
        logger.debug(f"record: {e}")
        return False


# ==================== المحاكاة ====================

def _simulate(direction, entry, candles, sl_pct, levels, ratios, be_trigger, be_offset):
    """
    يحاكي نفس منطق الصفقة الفعلية على الشموع (من الأقدم للأحدث).
    يرجع dict: done, gross_pct, mfe, mae, reason, last_profit
    كل القيم نسب مئوية من سعر الدخول (حركة السعر، قبل الرافعة).
    """
    sign = 1 if direction == "BUY" else -1
    sl = -abs(sl_pct)
    be_set = False
    remaining, realized = 1.0, 0.0
    tp_i = 0
    mfe = mae = 0.0
    last_profit = 0.0
    reason = None

    for c in candles:
        hi, lo, cl = float(c[2]), float(c[3]), float(c[4])
        if sign > 0:
            best = (hi - entry) / entry * 100
            worst = (lo - entry) / entry * 100
        else:
            best = (entry - lo) / entry * 100
            worst = (entry - hi) / entry * 100
        last_profit = (cl - entry) / entry * 100 * sign
        mae = min(mae, worst)

        # 1) الوقف أولاً (متحفظ)
        if worst <= sl:
            realized += remaining * sl
            remaining = 0.0
            reason = 'be_stop' if be_set else 'sl'
            break

        # 2) أقصى ربح، Breakeven، سلّم الأهداف
        mfe = max(mfe, best)
        if not be_set and best >= be_trigger:
            be_set = True
            sl = be_offset
        while tp_i < len(levels) and best >= levels[tp_i]:
            realized += ratios[tp_i] * levels[tp_i]
            remaining -= ratios[tp_i]
            tp_i += 1
        if remaining <= 1e-9:
            remaining = 0.0
            reason = 'tp_all'
            break

    done = reason is not None
    gross = realized + (0.0 if done else remaining * last_profit)
    return {'done': done, 'gross_pct': gross, 'mfe': mfe, 'mae': mae,
            'reason': reason, 'last_profit': last_profit}


def _fetch_candles(symbol, start_ms):
    try:
        import core_functions as core
        client = core.get_client()
        if not client:
            return []
        return client.futures_klines(symbol=symbol, interval='5m', startTime=start_ms, limit=500)
    except Exception as e:
        logger.debug(f"klines {symbol}: {e}")
        return []


def resolve_open(max_checks=40):
    """فحص صفقات الظل المفتوحة وإغلاق ما انتهى. يُستدعى من الجدولة كل ~10 دقائق."""
    global _dirty
    if not enabled():
        return 0
    try:
        sl_pct = float(_c('SL_PERCENT', 1.3))
        levels = list(_c('TP_MULTIPLE_LEVELS', [2.5, 3.5, 5.0]))
        ratios = list(_c('TP_QUANTITY_RATIOS', [0.4, 0.35, 0.25]))
        be_trigger = float(_c('BREAKEVEN_TRIGGER', 1.2))
        be_offset = float(_c('BREAKEVEN_OFFSET_PERCENT', 0.1))
        fee_pct = 2 * float(_c('COMMISSION_RATE', 0.0004)) * 100
        margin = float(_c('TRADE_USDT', 10))
        lev = float(_c('LEVERAGE', 15))
        max_ms = float(_c('SHADOW_MAX_HOURS', 8)) * 3600 * 1000
        now_ms = int(time.time() * 1000)

        with _lock:
            _ensure_loaded()
            pending = list(_state['open'])[:max_checks]

        closed_now = 0
        for s in pending:
            if now_ms - s['entry_ts'] < 5 * 60 * 1000:
                continue
            candles = _fetch_candles(s['symbol'], s['entry_ts'])
            if not candles:
                continue
            # استبعد الشمعة التي لم تُغلق بعد
            candles = [c for c in candles if int(c[6]) < now_ms] or []
            if not candles:
                continue
            r = _simulate(s['direction'], s['entry_price'], candles, sl_pct, levels,
                          ratios, be_trigger, be_offset)
            expired = (now_ms - s['entry_ts']) >= max_ms
            if not r['done'] and not expired:
                continue
            reason = r['reason'] or 'timeout'
            net_pct = r['gross_pct'] - fee_pct
            pnl = round(margin * lev * net_pct / 100, 3)
            s2 = dict(s)
            s2.update({
                'reason': reason,
                'pnl': pnl,
                'net_pct': round(net_pct, 3),
                'mfe_pct': round(r['mfe'], 3),
                'mae_pct': round(r['mae'], 3),
                'closed_time': datetime.now().isoformat(),
            })
            with _lock:
                try:
                    _state['open'].remove(s)
                except ValueError:
                    pass
                _state['closed'].append(s2)
                _state['closed'] = _state['closed'][-600:]
                _dirty = True
            closed_now += 1
            time.sleep(0.2)

        if closed_now:
            logger.info(f"👻 [SHADOW] أُغلقت {closed_now} صفقة ظل")
        flush()
        return closed_now
    except Exception as e:
        logger.error(f"❌ resolve_open: {e}")
        return 0


# ==================== الإحصاءات ====================

def _summ(items):
    eps = float(_c('LOSS_EPSILON', 0.10))
    wins = [t for t in items if t.get('pnl', 0) > eps]
    losses = [t for t in items if t.get('pnl', 0) < -eps]
    gw = sum(t['pnl'] for t in wins)
    gl = abs(sum(t['pnl'] for t in losses))
    dec = len(wins) + len(losses)
    n = len(items)
    return {
        'n': n,
        'wins': len(wins),
        'losses': len(losses),
        'win_rate': round(len(wins) / dec, 3) if dec else 0.0,
        'pnl': round(sum(t.get('pnl', 0) for t in items), 2),
        'profit_factor': round(gw / gl, 2) if gl > 0 else (99.0 if gw > 0 else 0.0),
        'avg_mfe': round(sum(t.get('mfe_pct', 0) for t in items) / n, 2) if n else 0.0,
        'avg_mae': round(sum(t.get('mae_pct', 0) for t in items) / n, 2) if n else 0.0,
    }


def _closed_since(days):
    with _lock:
        _ensure_loaded()
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()
        return [t for t in _state['closed'] if t.get('closed_time', '') >= cutoff]


def get_stats(days=None):
    days = days or int(_c('SHADOW_LOOKBACK_DAYS', 14))
    closed = _closed_since(days)
    out = {'days': days, 'by_tier': {}, 'overall': _summ(closed)}
    for tier in ('below_ai_gate', 'below_required', 'ai_veto'):
        items = [t for t in closed if t.get('tier') == tier]
        if items:
            out['by_tier'][tier] = _summ(items)
    with _lock:
        out['open'] = len(_state['open'])
    return out


def relief_info():
    """
    الإشارات التي مرّت على الذكاء الاصطناعي ولم تبلغ الحد (نقاطها قريبة من حد الدخول).
    هي المجموعة المقابلة للصفقات الحقيقية ذات النقاط 65-74.
    """
    items = [t for t in _closed_since(int(_c('SHADOW_LOOKBACK_DAYS', 14)))
             if t.get('tier') == 'below_required']
    s = _summ(items)
    s['min_needed'] = int(_c('SHADOW_RELIEF_MIN_TRADES', 15))
    return s


_TIER_AR = {
    'below_ai_gate': 'نقاط ضعيفة (لم تصل للذكاء الاصطناعي)',
    'below_required': 'نقاط قريبة من الحد (بعد الذكاء الاصطناعي)',
    'ai_veto': 'رفضها الذكاء الاصطناعي',
}


def summary_text():
    try:
        st = get_stats()
        msg = f"👻 <b>صفقات الظل</b> (آخر {st['days']} يوم)\n"
        msg += "<i>إشارات رُفضت وتم تتبعها افتراضياً دون مال</i>\n\n"
        if not st['overall']['n']:
            msg += f"⏳ لا توجد صفقات ظل مغلقة بعد (مفتوحة الآن: {st['open']})"
            return msg
        o = st['overall']
        msg += (f"📊 المغلقة: {o['n']} | نجاح {o['win_rate']*100:.0f}% | "
                f"PF {o['profit_factor']} | صافي {o['pnl']:+.2f}$\n")
        msg += f"🔄 مفتوحة الآن: {st['open']}\n"
        for tier, s in st['by_tier'].items():
            verdict = ""
            if s['n'] >= 10:
                verdict = " ✅ الرفض كان خسارة فرصة" if (s['profit_factor'] >= 1.3 and s['win_rate'] >= 0.5) \
                    else (" 🛡️ الرفض كان صحيحاً" if s['profit_factor'] < 0.9 else "")
            msg += (f"\n• {_TIER_AR.get(tier, tier)}:\n"
                    f"   {s['n']} صفقة | نجاح {s['win_rate']*100:.0f}% | PF {s['profit_factor']} | "
                    f"{s['pnl']:+.2f}$ | أقصى ربح/خسارة وسطي {s['avg_mfe']:+.2f}% / {s['avg_mae']:+.2f}%{verdict}")
        msg += "\n\n⚠️ محاكاة تقريبية (بدون انزلاق)، وتحتاج 15+ صفقة لكل فئة قبل الاعتماد عليها."
        return msg
    except Exception as e:
        return f"❌ خطأ: {e}"


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print(json.dumps(get_stats(), ensure_ascii=False, indent=2))
