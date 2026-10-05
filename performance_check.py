# -*- coding: utf-8 -*-
"""
performance_check.py - الإصدار v1.0 (2026-10-05)
فحص أداء يومي تلقائي مع حكم آلي + إرسال تقرير Telegram

🔥 ماذا يفقد كل يوم في PERFORMANCE_CHECK_HOUR:
   1. يلخص صفقات آخر 7/30 يوم (موثقة من trade_memory)
   2. يحسب: النجاح، PF، الصافي، الترند (هذا الأسبوع vs السابق)
   3. يفحص حالة الحماية (خسائر متتالية، رفع الحد، ساعات محظورة)
   4. يعطي "حكماً آلياً" (ممتاز/جيد/مقبول/يحتاج مراجعة/خطير) بدرجة 0-100
   5. يقارن مع حكم الأمس (تحسّن/تدهور/ثبات)
   6. يقترح إجراءات آلية (لا يعدّل شيئاً بنفسه — للمراجعة فقط)
   7. يرسل التقرير إلى Telegram ويحفظه في performance_check_history.json

🔧 التشغيل:
   - تلقائياً: من main_enhanced (انظر INSTALL أسفل الملف)
   - يدوياً:  python performance_check.py
"""

import json
import os
import time
import logging
import threading
from datetime import datetime, timedelta

import requests

logger = logging.getLogger("performance_check")

HISTORY_FILE = "performance_check_history.json"

try:
    from config import *
except ImportError:
    TELEGRAM_TOKEN = ""
    TELEGRAM_CHAT_ID = ""

# إعدادات افتراضية إذا غابت من config.py
try:
    ENABLE_PERFORMANCE_CHECK
except NameError:
    ENABLE_PERFORMANCE_CHECK = True
try:
    PERFORMANCE_CHECK_HOUR
except NameError:
    PERFORMANCE_CHECK_HOUR = 10


# ==================== أدوات مساعدة ====================

def _load_history():
    try:
        if os.path.exists(HISTORY_FILE):
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception as e:
        logger.error(f"تعذر قراءة سجل الفحوص: {e}")
    return {"checks": []}


def _save_history(h):
    try:
        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(h, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"تعذر حفظ سجل الفحوص: {e}")


def _get_trades(days=30):
    """صفقات موثقة من trade_memory، وإلا من profit_history.json"""
    try:
        import trade_memory
        trades = trade_memory.get_verified_trades(days=days)
        if trades:
            return trades
    except Exception as e:
        logger.debug(f"trade_memory: {e}")
    try:
        if os.path.exists("profit_history.json"):
            with open("profit_history.json", "r", encoding="utf-8") as f:
                data = json.load(f)
            cutoff = datetime.now() - timedelta(days=days)
            out = []
            for t in (data if isinstance(data, list) else data.get("trades", [])):
                try:
                    ts = t.get("entry_time") or t.get("time") or ""
                    if ts and datetime.fromisoformat(ts) < cutoff:
                        continue
                    out.append(t)
                except Exception:
                    out.append(t)
            return out
    except Exception as e:
        logger.debug(f"profit_history: {e}")
    return []


def _summarize(trades):
    if not trades:
        return {'n': 0, 'wins': 0, 'losses': 0, 'win_rate': 0.0, 'pnl': 0.0,
                'profit_factor': 0.0, 'avg_win': 0.0, 'avg_loss': 0.0}
    wins = [t for t in trades if t.get('is_win')]
    losses = [t for t in trades
              if t.get('is_loss') or (t.get('pnl', 0) < -float(globals().get('LOSS_EPSILON', 0.10)))]
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


def _daily_breakdown(trades, days=7):
    """صافي كل يوم لآخر N أيام"""
    out = {}
    cutoff = (datetime.now() - timedelta(days=days)).date()
    for t in trades:
        try:
            d = datetime.fromisoformat(t.get('entry_time')).date()
        except Exception:
            continue
        if d < cutoff:
            continue
        day = d.isoformat()
        out.setdefault(day, {'n': 0, 'pnl': 0.0, 'wins': 0})
        out[day]['n'] += 1
        out[day]['pnl'] = round(out[day]['pnl'] + t.get('pnl', 0), 3)
        if t.get('is_win'):
            out[day]['wins'] += 1
    return dict(sorted(out.items()))


def _ai_stats(trades):
    groups = {}
    for t in trades:
        key = t.get('groq_recommendation') or 'بدون AI'
        groups.setdefault(key, []).append(t)
    return {k: _summarize(v) for k, v in groups.items() if v}


def _score_bands(trades):
    bands = {'<55': [], '55-64': [], '65-74': [], '75+': []}
    for t in trades:
        sc = (t.get('score_details') or {}).get('total')
        if sc is None:
            continue
        if sc < 55:
            bands['<55'].append(t)
        elif sc < 65:
            bands['55-64'].append(t)
        elif sc < 75:
            bands['65-74'].append(t)
        else:
            bands['75+'].append(t)
    return {k: _summarize(v) for k, v in bands.items() if v}


def _protection_status():
    status = {}
    try:
        import adaptive_rules
        rules = adaptive_rules.load_rules()
        status['boost'] = rules.get('min_score_boost', 0)
        status['blocked_hours'] = rules.get('blocked_hours', [])
        status['trades_used'] = rules.get('trades_used', 0)
    except Exception:
        status['boost'] = 0
        status['blocked_hours'] = []
    try:
        import core_functions as core
        status['consecutive_losses'] = core.get_consecutive_losses()
    except Exception:
        status['consecutive_losses'] = -1
    return status


# ==================== الحكم الآلي ====================

def _interp(x, points):
    """استيفاء خطي بين نقاط [(x0,y0), (x1,y1), ...] مرتبة"""
    if x <= points[0][0]:
        return points[0][1]
    if x >= points[-1][0]:
        return points[-1][1]
    for (x0, y0), (x1, y1) in zip(points, points[1:]):
        if x0 <= x <= x1:
            return y0 + (y1 - y0) * (x - x0) / (x1 - x0)
    return points[-1][1]


def compute_verdict(s7, trend, protection):
    """درجة 0-100 + حكم + أسباب + توصيات"""
    reasons, recs = [], []

    pf_score = _interp(s7['profit_factor'] if s7['profit_factor'] < 90 else 2.5,
                       [(0.5, 0), (0.8, 25), (1.0, 50), (1.3, 70), (1.8, 90), (2.5, 100)])
    wr_score = _interp(s7['win_rate'] * 100, [(30, 0), (40, 35), (50, 60), (58, 80), (65, 100)])
    tr_score = 50 if trend is None else _interp(trend, [(-10, 0), (-2, 30), (0, 55), (2, 80), (10, 100)])
    dd_score = _interp(protection.get('consecutive_losses', 0), [(0, 100), (2, 70), (3, 45), (5, 10), (7, 0)])
    n_score = _interp(s7['n'], [(0, 20), (5, 40), (10, 55), (20, 75), (30, 90), (50, 100)])

    score = round(pf_score * 0.30 + wr_score * 0.20 + tr_score * 0.20
                  + dd_score * 0.15 + n_score * 0.15)

    if score >= 85:
        emoji, label = "🟢", "ممتاز"
    elif score >= 70:
        emoji, label = "🟢", "جيد"
    elif score >= 55:
        emoji, label = "🟡", "مقبول"
    elif score >= 40:
        emoji, label = "🟠", "يحتاج مراجعة"
    else:
        emoji, label = "🔴", "خطير"

    if s7['n'] < 15:
        label += " (عينة صغيرة)"

    # الأسباب
    if s7['profit_factor'] >= 1.3:
        reasons.append(f"PF ممتاز ({s7['profit_factor']})")
    elif s7['profit_factor'] < 1.0 and s7['n'] >= 5:
        reasons.append(f"PF تحت التعادل ({s7['profit_factor']})")
    if s7['win_rate'] >= 0.58:
        reasons.append(f"نسبة نجاح قوية {s7['win_rate']*100:.0f}%")
    elif s7['win_rate'] < 0.45 and s7['n'] >= 5:
        reasons.append(f"نسبة نجاح ضعيفة {s7['win_rate']*100:.0f}%")
    if trend is not None:
        reasons.append("الترند صاعد 📈" if trend > 1 else ("الترند هابط 📉" if trend < -1 else "الترند مستقر ➡️"))
    if protection.get('consecutive_losses', 0) >= 3:
        reasons.append(f"{protection['consecutive_losses']} خسائر متتالية - الحماية نشطة")

    # التوصيات
    if s7['profit_factor'] < 1.0 and s7['n'] >= 10:
        recs.append("الربحية سالبة: لا تخفض أي حد يدوياً؛ دع التعلم يرفع الحد حتى يتحسن PF")
    if protection.get('boost', 0) > 0:
        recs.append(f"التعلم رفع الحد +{protection['boost']} — هذا صحيح، لا تتدخل")
    if protection.get('consecutive_losses', 0) >= 3:
        recs.append("خسائر متتالية: التبريد والإيقاف المتصاعد يعملان — راقب فقط")
    if s7['n'] >= 15 and s7['profit_factor'] >= 1.4 and trend is not None and trend > 1:
        recs.append("الأداء قوي وثابت: يمكنك رفع TRADE_USDT تدريجياً (بحد أقصى 15$)")
    if not recs:
        recs.append("لا إجراء مطلوب — النظام يعمل ضمن المسار الطبيعي")

    return score, emoji, label, reasons, recs


# ==================== بناء التقرير ====================

def build_report():
    trades30 = _get_trades(days=30)
    trades7 = [t for t in trades30
               if _day_of(t) >= (datetime.now() - timedelta(days=7)).date()]
    trades_prev = [t for t in trades30
                   if (datetime.now() - timedelta(days=14)).date()
                   <= _day_of(t) < (datetime.now() - timedelta(days=7)).date()]

    s7 = _summarize(trades7)
    s_prev = _summarize(trades_prev)
    s30 = _summarize(trades30)
    protection = _protection_status()

    trend = None
    if s7['n'] >= 3 and s_prev['n'] >= 3:
        trend = round(s7['pnl'] - s_prev['pnl'], 2)

    score, emoji, label, reasons, recs = compute_verdict(s7, trend, protection)

    # مقارنة مع فحص الأمس
    history = _load_history()
    prev_score = history['checks'][-1]['score'] if history['checks'] else None
    if prev_score is not None:
        if score >= prev_score + 5:
            change = f"تحسّن ⬆️ (أمس {prev_score} → اليوم {score})"
        elif score <= prev_score - 5:
            change = f"تدهور ⬇️ (أمس {prev_score} → اليوم {score})"
        else:
            change = "ثبات ➡️"
    else:
        change = "أول فحص"

    daily = _daily_breakdown(trades30, days=7)
    ai = _ai_stats(trades7)
    bands = _score_bands(trades30)

    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    L = []
    L.append("📋 <b>فحص الأداء اليومي</b>")
    L.append(f"🕐 {now}\n")
    L.append(f"<b>الحكم: {emoji} {label}</b> — الدرجة {score}/100 ({change})\n")

    L.append("📊 <b>آخر 7 أيام:</b>")
    if s7['n']:
        L.append(f"   الصفقات: {s7['n']} | نجاح {s7['win_rate']*100:.0f}% "
                 f"| PF {s7['profit_factor']} | صافي {s7['pnl']:+.2f}$")
        L.append(f"   متوسط ربح {s7['avg_win']:+.2f}$ / خسارة {s7['avg_loss']:+.2f}$")
    else:
        L.append("   لا صفقات")
    if s30['n']:
        L.append(f"\n📅 <b>آخر 30 يوم:</b> {s30['n']} صفقة | نجاح {s30['win_rate']*100:.0f}% "
                 f"| PF {s30['profit_factor']} | صافي {s30['pnl']:+.2f}$")

    if daily:
        L.append("\n📆 <b>اليومية (7 أيام):</b>")
        for day, d in daily.items():
            mark = "✅" if d['pnl'] > 0 else ("❌" if d['pnl'] < 0 else "➖")
            L.append(f"   {mark} {day}: {d['n']} صفقة | {d['pnl']:+.2f}$")

    if bands:
        L.append("\n🎯 <b>النقاط مقابل النتيجة (30 يوم):</b>")
        for k, v in bands.items():
            L.append(f"   {k}: {v['n']} صفقة | PF {v['profit_factor']} | {v['pnl']:+.2f}$")

    if ai:
        L.append("\n🧠 <b>قرارات AI (7 أيام):</b>")
        for k, v in list(ai.items())[:4]:
            L.append(f"   {k}: {v['n']} | نجاح {v['win_rate']*100:.0f}% | PF {v['profit_factor']}")

    L.append("\n🛡️ <b>الحماية الآن:</b>")
    L.append(f"   خسائر متتالية: {protection.get('consecutive_losses', '؟')} | "
             f"رفع الحد: +{protection.get('boost', 0)} | "
             f"ساعات محظورة: {protection.get('blocked_hours') or 'لا'}")

    if reasons:
        L.append("\n<b>لماذا هذا الحكم:</b>")
        for r in reasons[:5]:
            L.append(f"   • {r}")

    L.append("\n<b>التوصيات:</b>")
    for r in recs[:5]:
        L.append(f"   • {r}")

    return "\n".join(L), score, label, emoji


def _day_of(t):
    try:
        return datetime.fromisoformat(t.get('entry_time')).date()
    except Exception:
        return datetime.now().date()


# ==================== الإرسال ====================

def send_report(text):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        logger.error("⚠️ Telegram غير مهيأ - تعذر الإرسال")
        return False
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        r = requests.post(url, data={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }, timeout=20)
        if r.status_code == 200:
            logger.info("✅ تم إرسال فحص الأداء")
            return True
        logger.error(f"فشل الإرسال: {r.status_code} {r.text[:150]}")
    except Exception as e:
        logger.error(f"خطأ إرسال Telegram: {e}")
    return False


def run_check(send=True):
    """ينفذ الفحص الكامل، يرسل إن طُلب، ويحفظ في السجل"""
    try:
        text, score, label, emoji = build_report()
        history = _load_history()
        history['checks'].append({
            'date': datetime.now().isoformat(),
            'score': score, 'label': label,
        })
        history['checks'] = history['checks'][-60:]
        _save_history(history)
        if send and ENABLE_PERFORMANCE_CHECK:
            send_report(text)
        return text
    except Exception as e:
        logger.error(f"❌ فشل فحص الأداء: {e}")
        import traceback
        traceback.print_exc()
        return None


# ==================== الجدولة اليومية ====================

def start_daily_check():
    """خيط يفحص كل دقيقة: هل حان موعد الإرسال اليومي؟"""
    if not ENABLE_PERFORMANCE_CHECK:
        logger.info("ℹ️ فحص الأداء اليومي معطل (ENABLE_PERFORMANCE_CHECK=False)")
        return

    def _loop():
        last_sent = None
        logger.info(f"✅ فحص الأداء اليومي نشط — الإرسال يومياً الساعة {PERFORMANCE_CHECK_HOUR:02d}:00")
        while True:
            try:
                now = datetime.now()
                today = now.date().isoformat()
                if now.hour == PERFORMANCE_CHECK_HOUR and last_sent != today:
                    time.sleep(30)  # دقيقة أمان بعد بدء الساعة
                    if run_check(send=True):
                        last_sent = today
            except Exception as e:
                logger.error(f"خطأ في خيط الفحص: {e}")
            time.sleep(60)

    t = threading.Thread(target=_loop, name="PerformanceCheck", daemon=True)
    t.start()


# ==================== دمج في main_enhanced ====================
# أضف هذا المقطع في main_enhanced.py بعد تشغيل الخيوط (بجانب باقي ✅ [START]):
#
#     try:
#         import performance_check
#         performance_check.start_daily_check()
#         logger.info("✅ [START] Performance Check اليومي")
#     except Exception as e:
#         logger.warning(f"⚠️ performance_check: {e}")

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    out = run_check(send=True)
    if out:
        print(out)
