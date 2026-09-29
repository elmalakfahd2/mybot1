# ==================================================
# 📁 ملف: adaptive_rules.py - التعلم التكيفي v1.0
# 🔧 الوصف:
#    - يتعلم من الصفقات الموثقة فقط (PnL حقيقي من Binance)
#    - قواعده تؤثر فعلياً على قرار الدخول:
#        1) رفع الحد الأدنى للنقاط بعد أداء ضعيف (ويرجع تلقائياً عند التحسن)
#        2) عقوبة نقاط لاتجاه (BUY/SELL) أثبت ضعفه
#        3) حظر ساعات الدخول الخاسرة
#    - يبني سياقاً للذكاء الاصطناعي (حالة السوق + سجل العملة + أداء البوت)
#    - القواعد تُحفظ محلياً وفي Firebase ولا تضيع عند إعادة التشغيل
# 📅 التاريخ: 2026-09-29
# ==================================================

import json
import os
import time
import logging
import threading
from datetime import datetime

logger = logging.getLogger("adaptive_rules")

RULES_FILE = "learned_rules.json"
FIREBASE_DOC = "learned_rules"

_lock = threading.Lock()
_cache = {'rules': None, 'ts': 0}
_CACHE_SECONDS = 60


def _c(name, default):
    try:
        import config
        return getattr(config, name, default)
    except Exception:
        return default


def _default_rules():
    return {
        'min_score_boost': 0,
        'direction_penalty': {'BUY': 0, 'SELL': 0},
        'blocked_hours': [],
        'trades_used': 0,
        'stats': {},
        'notes': ['لا توجد بيانات كافية بعد - القواعد الافتراضية'],
        'updated': None,
    }


# ==================== التخزين ====================

def _save_rules(rules):
    try:
        with open(RULES_FILE, "w", encoding="utf-8") as f:
            json.dump(rules, f, indent=2, ensure_ascii=False)
    except Exception as e:
        logger.error(f"خطأ حفظ القواعد محلياً: {e}")

    try:
        import firebase_backup
        if firebase_backup.is_available():
            firebase_backup.save_doc(FIREBASE_DOC, rules)
    except Exception as e:
        logger.debug(f"تعذر حفظ القواعد في Firebase: {e}")


def load_rules(force=False):
    """تحميل القواعد (مع تخزين مؤقت 60 ثانية)"""
    now = time.time()
    with _lock:
        if not force and _cache['rules'] is not None and now - _cache['ts'] < _CACHE_SECONDS:
            return _cache['rules']

    rules = None
    try:
        if os.path.exists(RULES_FILE):
            with open(RULES_FILE, "r", encoding="utf-8") as f:
                rules = json.load(f)
    except Exception:
        rules = None

    if rules is None:
        try:
            import firebase_backup
            if firebase_backup.is_available():
                doc = firebase_backup.load_doc(FIREBASE_DOC)
                if doc:
                    doc.pop('_saved_at', None)
                    rules = doc
                    _save_rules_local_only(rules)
        except Exception:
            rules = None

    if rules is None:
        rules = _default_rules()

    with _lock:
        _cache['rules'] = rules
        _cache['ts'] = now
    return rules


def _save_rules_local_only(rules):
    try:
        with open(RULES_FILE, "w", encoding="utf-8") as f:
            json.dump(rules, f, indent=2, ensure_ascii=False)
    except Exception:
        pass


def restore_from_firebase():
    """يُستدعى عند الإقلاع بعد تهيئة Firebase"""
    try:
        import firebase_backup
        if not firebase_backup.is_available():
            return False
        doc = firebase_backup.load_doc(FIREBASE_DOC)
        if doc:
            doc.pop('_saved_at', None)
            _save_rules_local_only(doc)
            load_rules(force=True)
            logger.info("✅ تم استرجاع قواعد التعلم من Firebase")
            return True
    except Exception as e:
        logger.debug(f"restore_from_firebase: {e}")
    return False


# ==================== أدوات التحليل ====================

def _is_loss(t):
    if 'is_loss' in t:
        return bool(t['is_loss'])
    return t.get('pnl', 0) < -float(_c('LOSS_EPSILON', 0.10))


def _summarize(trades):
    """ملخص أداء لقائمة صفقات"""
    if not trades:
        return {'n': 0, 'wins': 0, 'losses': 0, 'win_rate': 0.0, 'pnl': 0.0,
                'profit_factor': 0.0, 'avg_win': 0.0, 'avg_loss': 0.0}
    wins = [t for t in trades if t.get('is_win')]
    losses = [t for t in trades if _is_loss(t)]
    gross_win = sum(t.get('pnl', 0) for t in wins)
    gross_loss = abs(sum(t.get('pnl', 0) for t in losses))
    decided = len(wins) + len(losses)
    return {
        'n': len(trades),
        'wins': len(wins),
        'losses': len(losses),
        'win_rate': round(len(wins) / decided, 3) if decided else 0.0,
        'pnl': round(sum(t.get('pnl', 0) for t in trades), 3),
        'profit_factor': round(gross_win / gross_loss, 2) if gross_loss > 0 else (99.0 if gross_win > 0 else 0.0),
        'avg_win': round(gross_win / len(wins), 3) if wins else 0.0,
        'avg_loss': round(-gross_loss / len(losses), 3) if losses else 0.0,
    }


def _entry_hour(t):
    try:
        return datetime.fromisoformat(t.get('entry_time')).hour
    except Exception:
        return t.get('hour', -1)


def _verified_trades(days=None):
    try:
        import trade_memory
        return trade_memory.get_verified_trades(days=days)
    except Exception as e:
        logger.error(f"تعذر جلب الصفقات الموثقة: {e}")
        return []


# ==================== التعلم ====================

def update_rules():
    """
    تحليل الصفقات الموثقة وتحديث القواعد. آمن للتشغيل المتكرر.
    القواعد تُعاد حسابها من الصفر كل مرة، فتنتهي القواعد القديمة تلقائياً.
    """
    try:
        min_trades = int(_c('ADAPTIVE_MIN_TRADES', 12))
        lookback_days = int(_c('ADAPTIVE_LOOKBACK_DAYS', 14))
        max_boost = int(_c('ADAPTIVE_MAX_SCORE_BOOST', 10))

        trades = _verified_trades(days=lookback_days)
        rules = _default_rules()
        rules['trades_used'] = len(trades)
        rules['updated'] = datetime.now().isoformat()

        overall = _summarize(trades)
        rules['stats'] = {'overall': overall}

        if len(trades) < min_trades:
            rules['notes'] = [f"بيانات موثقة غير كافية ({len(trades)}/{min_trades}) - القواعد الافتراضية"]
            _save_rules(rules)
            with _lock:
                _cache['rules'] = rules
                _cache['ts'] = time.time()
            return rules

        notes = []

        # ---------- 1) رفع الحد الأدنى للنقاط حسب الأداء الأخير ----------
        recent_n = int(_c('ADAPTIVE_RECENT_WINDOW', 15))
        recent = _summarize(trades[-recent_n:])
        rules['stats']['recent'] = recent

        boost = 0
        if recent['n'] >= 8:
            if recent['win_rate'] < 0.35 or recent['profit_factor'] < 0.6:
                boost = max_boost
            elif recent['win_rate'] < 0.45 or recent['profit_factor'] < 0.9:
                boost = max(1, max_boost // 2)
        rules['min_score_boost'] = min(boost, max_boost)
        if boost:
            notes.append(
                f"⚠️ أداء آخر {recent['n']} صفقة ضعيف (نجاح {recent['win_rate']*100:.0f}% / PF {recent['profit_factor']}) "
                f"← رفع حد الدخول +{rules['min_score_boost']} نقطة"
            )
        else:
            notes.append(f"✅ أداء آخر {recent['n']} صفقة مقبول - لا رفع للحد")

        # ---------- 2) عقوبة الاتجاه ----------
        min_dir = int(_c('ADAPTIVE_MIN_TRADES_PER_DIRECTION', 6))
        for d in ('BUY', 'SELL'):
            dt = [t for t in trades if t.get('direction') == d]
            s = _summarize(dt)
            rules['stats'][d] = s
            if s['n'] >= min_dir and s['win_rate'] < 0.35 and s['pnl'] < 0:
                rules['direction_penalty'][d] = 5
                notes.append(f"📉 اتجاه {d} ضعيف ({s['wins']}/{s['n']} ، {s['pnl']:+.2f}$) ← +5 نقاط مطلوبة")

        # ---------- 3) الساعات الخاسرة (ساعة الدخول) ----------
        min_hour = int(_c('ADAPTIVE_MIN_TRADES_PER_HOUR', 4))
        hours = {}
        for t in trades:
            h = _entry_hour(t)
            if h >= 0:
                hours.setdefault(h, []).append(t)
        blocked = []
        for h, ht in sorted(hours.items()):
            s = _summarize(ht)
            if s['n'] >= min_hour and s['win_rate'] <= 0.20 and s['pnl'] < -2.0:
                blocked.append(h)
                notes.append(f"🕐 الساعة {h}:00 خاسرة ({s['wins']}/{s['n']} ، {s['pnl']:+.2f}$) ← حظر")
        rules['blocked_hours'] = blocked

        # ---------- 4) تقارير للمعلومات (لا تغيّر القرار) ----------
        bands = {'<65': [], '65-74': [], '75+': []}
        for t in trades:
            sc = (t.get('score_details') or {}).get('total')
            if sc is None:
                continue
            if sc < 65:
                bands['<65'].append(t)
            elif sc < 75:
                bands['65-74'].append(t)
            else:
                bands['75+'].append(t)
        rules['stats']['score_bands'] = {k: _summarize(v) for k, v in bands.items() if v}

        ai_groups = {}
        for t in trades:
            rec = t.get('groq_recommendation') or 'بدون AI'
            ai_groups.setdefault(rec, []).append(t)
        rules['stats']['by_ai'] = {k: _summarize(v) for k, v in ai_groups.items()}

        rules['notes'] = notes
        _save_rules(rules)
        with _lock:
            _cache['rules'] = rules
            _cache['ts'] = time.time()

        logger.info(f"🧠 تم تحديث قواعد التعلم من {len(trades)} صفقة موثقة")
        for n in notes:
            logger.info(f"   {n}")
        return rules

    except Exception as e:
        logger.error(f"❌ فشل تحديث القواعد: {e}")
        import traceback
        traceback.print_exc()
        return load_rules()


# ==================== الاستعلام (تستخدمه الاستراتيجية) ====================

def get_required_score(direction):
    """الحد الأدنى الفعلي للنقاط لهذا الاتجاه (الأساس + تعلم)"""
    base = int(_c('MIN_SCORE_REQUIRED', 65))
    try:
        if not _c('ENABLE_ADAPTIVE_RULES', True):
            return base
        rules = load_rules()
        extra = int(rules.get('min_score_boost', 0))
        extra += int(rules.get('direction_penalty', {}).get(direction, 0))
        cap = int(_c('ADAPTIVE_MAX_TOTAL_BOOST', 12))
        return base + min(extra, cap)
    except Exception:
        return base


def is_hour_blocked(hour=None):
    try:
        if not _c('ENABLE_ADAPTIVE_RULES', True):
            return False
        if hour is None:
            hour = datetime.now().hour
        return hour in load_rules().get('blocked_hours', [])
    except Exception:
        return False


# ==================== سياق الذكاء الاصطناعي ====================

def build_ai_context(symbol, direction):
    """
    نص قصير يُرسل للذكاء الاصطناعي حتى يقرر بمعرفة السوق والسجل،
    لا بمؤشرات الإشارة وحدها.
    """
    lines = []
    try:
        # 1) حالة السوق
        try:
            from market_regime import MarketRegime
            reg = MarketRegime.get_regime()
            lines.append(
                f"- حالة السوق (BTC): {reg.get('regime_ar', '؟')} | 1س {reg.get('change_1h', 0):+.2f}% | "
                f"4س {reg.get('change_4h', 0):+.2f}% | 24س {reg.get('change_24h', 0):+.2f}% | "
                f"التقلب: {reg.get('volatility', '؟')}"
            )
            rtype = reg.get('regime', '')
            if direction == 'SELL' and rtype in ('bullish', 'strong_bullish'):
                lines.append("- ⚠️ الإشارة SELL عكس اتجاه السوق الصاعد")
            elif direction == 'BUY' and rtype in ('bearish', 'strong_bearish'):
                lines.append("- ⚠️ الإشارة BUY عكس اتجاه السوق الهابط")
        except Exception:
            pass

        trades = _verified_trades(days=14)

        # 2) أداء البوت الأخير
        if trades:
            recent = trades[-20:]
            s = _summarize(recent)
            streak = 0
            for t in reversed(recent):
                if _is_loss(t):
                    streak += 1
                elif t.get('is_win'):
                    break
            lines.append(
                f"- أداء البوت (آخر {s['n']} صفقة موثقة): نجاح {s['win_rate']*100:.0f}% | "
                f"صافي {s['pnl']:+.2f}$ | خسائر متتالية حالياً: {streak}"
            )

            # 3) سجل العملة
            sym = [t for t in trades if t.get('symbol') == symbol][-5:]
            if sym:
                items = []
                for t in sym:
                    r = 'ربح' if t.get('is_win') else ('خسارة' if _is_loss(t) else 'تعادل')
                    items.append(f"{t.get('direction')}:{r}({t.get('pnl', 0):+.2f}$)")
                lines.append(f"- آخر صفقات {symbol}: " + " ، ".join(items))

            # 4) سجل الاتجاه
            dirs = [t for t in trades if t.get('direction') == direction][-10:]
            if len(dirs) >= 4:
                ds = _summarize(dirs)
                lines.append(
                    f"- سجل صفقات {direction} (آخر {ds['n']}): نجاح {ds['win_rate']*100:.0f}% | صافي {ds['pnl']:+.2f}$"
                )
        else:
            lines.append("- لا يوجد سجل صفقات موثق بعد")

        # 5) حالة الحماية
        try:
            import core_functions as core
            losses = core.get_consecutive_losses()
            if losses >= 2:
                lines.append(f"- تنبيه: {losses} خسائر متتالية للبوت الآن")
        except Exception:
            pass

    except Exception as e:
        logger.debug(f"build_ai_context: {e}")

    return "\n".join(lines)


# ==================== تقرير نصي ====================

def get_status_text():
    """ملخص للتلغرام"""
    try:
        r = load_rules()
        st = r.get('stats', {}).get('overall', {})
        msg = "🧠 <b>قواعد التعلم الحالية</b>\n\n"
        msg += f"📊 صفقات موثقة: {r.get('trades_used', 0)}\n"
        if st.get('n'):
            msg += f"   • نجاح: {st.get('win_rate', 0)*100:.0f}% | PF: {st.get('profit_factor', 0)} | صافي: {st.get('pnl', 0):+.2f}$\n"
        msg += f"\n🎯 رفع حد النقاط: +{r.get('min_score_boost', 0)}\n"
        dp = r.get('direction_penalty', {})
        msg += f"↕️ عقوبة الاتجاه: BUY +{dp.get('BUY', 0)} | SELL +{dp.get('SELL', 0)}\n"
        bh = r.get('blocked_hours', [])
        msg += f"🕐 ساعات محظورة: {', '.join(str(h) for h in bh) if bh else 'لا يوجد'}\n"
        for n in r.get('notes', [])[:6]:
            msg += f"\n{n}"
        return msg
    except Exception as e:
        return f"❌ خطأ: {e}"


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print(json.dumps(update_rules(), indent=2, ensure_ascii=False))
