# ==================================================
# 📁 ملف: performance_tracker.py - الإصدار v5.0
# 🔧 الوصف:
#    - حساب نسبة النجاح
#    - Profit Factor
#    - Max Drawdown
#    - Sharpe Ratio
#    - إحصائيات شاملة
# 📅 التاريخ: 2026-09-22
# ==================================================

import json
import os
import logging
from datetime import datetime, timedelta
from collections import defaultdict

logger = logging.getLogger("performance_tracker")

MEMORY_FILE = "trade_memory.json"
PERFORMANCE_FILE = "performance_history.json"


# ==================== تحميل البيانات ====================

def load_memory():
    """تحميل ذاكرة الصفقات"""
    try:
        if not os.path.exists(MEMORY_FILE):
            return {"trades": []}
        with open(MEMORY_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"خطأ في تحميل الذاكرة: {e}")
        return {"trades": []}


def load_performance_history():
    """تحميل سجل الأداء"""
    try:
        if not os.path.exists(PERFORMANCE_FILE):
            return []
        with open(PERFORMANCE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return []


def save_performance_history(history):
    """حفظ سجل الأداء"""
    try:
        with open(PERFORMANCE_FILE, "w", encoding="utf-8") as f:
            json.dump(history, f, indent=2, ensure_ascii=False)
        return True
    except Exception as e:
        logger.error(f"خطأ في الحفظ: {e}")
        return False


# ==================== الحسابات الأساسية ====================

def calculate_win_rate(trades):
    """حساب نسبة النجاح"""
    if not trades:
        return 0.0
    wins = sum(1 for t in trades if t.get('is_win', False))
    return round(wins / len(trades) * 100, 2)


def calculate_profit_factor(trades):
    """حساب Profit Factor"""
    try:
        gross_profit = sum(t.get('pnl', 0) for t in trades if t.get('pnl', 0) > 0)
        gross_loss = abs(sum(t.get('pnl', 0) for t in trades if t.get('pnl', 0) < 0))

        if gross_loss == 0:
            return 999.0 if gross_profit > 0 else 0.0

        return round(gross_profit / gross_loss, 2)
    except:
        return 0.0


def calculate_max_drawdown(trades):
    """حساب Max Drawdown"""
    try:
        if not trades:
            return 0.0

        equity = 0
        peak = 0
        max_dd = 0

        for trade in trades:
            equity += trade.get('pnl', 0)
            if equity > peak:
                peak = equity
            dd = peak - equity
            if dd > max_dd:
                max_dd = dd

        return round(max_dd, 4)
    except:
        return 0.0


def calculate_sharpe_ratio(trades, risk_free_rate=0.0):
    """حساب Sharpe Ratio (مبسط)"""
    try:
        if len(trades) < 2:
            return 0.0

        returns = [t.get('pnl_percent', 0) for t in trades]

        mean_return = sum(returns) / len(returns)
        variance = sum((r - mean_return) ** 2 for r in returns) / len(returns)
        std_dev = variance ** 0.5

        if std_dev == 0:
            return 0.0

        return round((mean_return - risk_free_rate) / std_dev, 2)
    except:
        return 0.0


def calculate_avg_win_loss(trades):
    """حساب متوسط الربح والخسارة"""
    try:
        wins = [t.get('pnl', 0) for t in trades if t.get('is_win', False)]
        losses = [t.get('pnl', 0) for t in trades if not t.get('is_win', False)]

        avg_win = sum(wins) / len(wins) if wins else 0
        avg_loss = sum(losses) / len(losses) if losses else 0

        return round(avg_win, 4), round(avg_loss, 4)
    except:
        return 0, 0


def calculate_rr_ratio(trades):
    """حساب R:R Ratio الفعلي"""
    try:
        avg_win, avg_loss = calculate_avg_win_loss(trades)

        if avg_loss == 0:
            return 999.0

        return round(abs(avg_win / avg_loss), 2)
    except:
        return 0.0


# ==================== التحليل الزمني ====================

def analyze_by_hour(trades):
    """تحليل حسب الساعة"""
    try:
        hourly = defaultdict(lambda: {'wins': 0, 'losses': 0, 'pnl': 0})

        for trade in trades:
            hour = trade.get('hour', -1)
            if hour < 0:
                continue

            if trade.get('is_win'):
                hourly[hour]['wins'] += 1
            else:
                hourly[hour]['losses'] += 1

            hourly[hour]['pnl'] += trade.get('pnl', 0)

        result = {}
        for hour, data in hourly.items():
            total = data['wins'] + data['losses']
            result[hour] = {
                'wins': data['wins'],
                'losses': data['losses'],
                'win_rate': round(data['wins'] / total * 100, 1) if total > 0 else 0,
                'pnl': round(data['pnl'], 4)
            }

        return result
    except:
        return {}


def analyze_by_symbol(trades):
    """تحليل حسب العملة"""
    try:
        symbol_stats = defaultdict(lambda: {'wins': 0, 'losses': 0, 'pnl': 0})

        for trade in trades:
            symbol = trade.get('symbol', 'UNKNOWN')
            if trade.get('is_win'):
                symbol_stats[symbol]['wins'] += 1
            else:
                symbol_stats[symbol]['losses'] += 1
            symbol_stats[symbol]['pnl'] += trade.get('pnl', 0)

        result = {}
        for symbol, data in symbol_stats.items():
            total = data['wins'] + data['losses']
            result[symbol] = {
                'wins': data['wins'],
                'losses': data['losses'],
                'total': total,
                'win_rate': round(data['wins'] / total * 100, 1) if total > 0 else 0,
                'pnl': round(data['pnl'], 4)
            }

        return result
    except:
        return {}


def analyze_by_direction(trades):
    """تحليل حسب الاتجاه"""
    try:
        stats = {
            'BUY': {'wins': 0, 'losses': 0, 'pnl': 0},
            'SELL': {'wins': 0, 'losses': 0, 'pnl': 0}
        }

        for trade in trades:
            direction = trade.get('direction', 'UNKNOWN')
            if direction not in stats:
                continue

            if trade.get('is_win'):
                stats[direction]['wins'] += 1
            else:
                stats[direction]['losses'] += 1
            stats[direction]['pnl'] += trade.get('pnl', 0)

        result = {}
        for direction, data in stats.items():
            total = data['wins'] + data['losses']
            result[direction] = {
                'wins': data['wins'],
                'losses': data['losses'],
                'total': total,
                'win_rate': round(data['wins'] / total * 100, 1) if total > 0 else 0,
                'pnl': round(data['pnl'], 4)
            }

        return result
    except:
        return {}


# ==================== التحليل الرئيسي ====================

def get_full_performance(days=30):
    """
    الحصول على تقرير الأداء الكامل
    """
    try:
        memory = load_memory()
        all_trades = memory.get('trades', [])

        if not all_trades:
            return None

        # آخر days يوم
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()
        trades = [t for t in all_trades if t.get('entry_time', '') >= cutoff]

        if not trades:
            trades = all_trades[-50:]  # آخر 50 صفقة

        # الحسابات الأساسية
        win_rate = calculate_win_rate(trades)
        profit_factor = calculate_profit_factor(trades)
        max_dd = calculate_max_drawdown(trades)
        sharpe = calculate_sharpe_ratio(trades)
        avg_win, avg_loss = calculate_avg_win_loss(trades)
        rr_ratio = calculate_rr_ratio(trades)

        total_pnl = sum(t.get('pnl', 0) for t in trades)

        # التحليلات الفرعية
        hourly = analyze_by_hour(trades)
        symbols = analyze_by_symbol(trades)
        directions = analyze_by_direction(trades)

        # أفضل/أسوأ
        best_hour = max(hourly.items(), key=lambda x: x[1]['win_rate']) if hourly else None
        worst_hour = min(hourly.items(), key=lambda x: x[1]['win_rate']) if hourly else None

        best_symbol = max(symbols.items(), key=lambda x: x[1]['pnl']) if symbols else None
        worst_symbol = min(symbols.items(), key=lambda x: x[1]['pnl']) if symbols else None

        return {
            'period_days': days,
            'total_trades': len(trades),
            'wins': sum(1 for t in trades if t.get('is_win')),
            'losses': sum(1 for t in trades if not t.get('is_win')),
            'win_rate': win_rate,
            'profit_factor': profit_factor,
            'max_drawdown': max_dd,
            'sharpe_ratio': sharpe,
            'avg_win': avg_win,
            'avg_loss': avg_loss,
            'rr_ratio': rr_ratio,
            'total_pnl': round(total_pnl, 4),
            'best_hour': best_hour,
            'worst_hour': worst_hour,
            'best_symbol': best_symbol,
            'worst_symbol': worst_symbol,
            'hourly_stats': hourly,
            'symbol_stats': symbols,
            'direction_stats': directions,
            'timestamp': datetime.now().isoformat()
        }

    except Exception as e:
        logger.error(f"خطأ في التحليل: {e}")
        import traceback
        traceback.print_exc()
        return None


# ==================== تقييم الأداء ====================

def evaluate_performance(performance):
    """تقييم الأداء وإعطاء درجة"""
    try:
        if not performance:
            return {'score': 0, 'rating': 'غير معروف'}

        score = 0
        details = {}

        # نسبة النجاح (30 نقطة)
        wr = performance.get('win_rate', 0)
        if wr >= 60:
            score += 30
            details['win_rate'] = 'ممتاز'
        elif wr >= 50:
            score += 22
            details['win_rate'] = 'جيد'
        elif wr >= 40:
            score += 15
            details['win_rate'] = 'متوسط'
        else:
            score += 5
            details['win_rate'] = 'ضعيف'

        # Profit Factor (25 نقطة)
        pf = performance.get('profit_factor', 0)
        if pf >= 1.5:
            score += 25
            details['profit_factor'] = 'ممتاز'
        elif pf >= 1.2:
            score += 20
            details['profit_factor'] = 'جيد'
        elif pf >= 1.0:
            score += 12
            details['profit_factor'] = 'متعادل'
        else:
            score += 3
            details['profit_factor'] = 'خاسر'

        # R:R Ratio (20 نقطة)
        rr = performance.get('rr_ratio', 0)
        if rr >= 1.5:
            score += 20
            details['rr_ratio'] = 'ممتاز'
        elif rr >= 1.2:
            score += 15
            details['rr_ratio'] = 'جيد'
        elif rr >= 1.0:
            score += 10
            details['rr_ratio'] = 'متعادل'
        else:
            score += 3
            details['rr_ratio'] = 'ضعيف'

        # Sharpe Ratio (15 نقطة)
        sr = performance.get('sharpe_ratio', 0)
        if sr >= 1.5:
            score += 15
            details['sharpe'] = 'ممتاز'
        elif sr >= 1.0:
            score += 10
            details['sharpe'] = 'جيد'
        elif sr >= 0.5:
            score += 6
            details['sharpe'] = 'متوسط'
        else:
            score += 2
            details['sharpe'] = 'ضعيف'

        # Max Drawdown (10 نقطة)
        dd = performance.get('max_drawdown', 0)
        if dd <= 5:
            score += 10
            details['max_dd'] = 'ممتاز'
        elif dd <= 10:
            score += 7
            details['max_dd'] = 'جيد'
        elif dd <= 20:
            score += 4
            details['max_dd'] = 'مقبول'
        else:
            score += 1
            details['max_dd'] = 'خطير'

        # التقييم النهائي
        if score >= 80:
            rating = 'ممتاز ⭐⭐⭐⭐⭐'
        elif score >= 65:
            rating = 'جيد ⭐⭐⭐⭐'
        elif score >= 50:
            rating = 'متوسط ⭐⭐⭐'
        elif score >= 35:
            rating = 'ضعيف ⭐⭐'
        else:
            rating = 'خطير ⭐'

        return {
            'score': score,
            'rating': rating,
            'details': details
        }

    except Exception as e:
        logger.error(f"خطأ في التقييم: {e}")
        return {'score': 0, 'rating': 'خطأ'}


# ==================== حفظ الأداء ====================

def save_performance_snapshot(performance):
    """حفظ لقطة أداء"""
    try:
        history = load_performance_history()
        history.append(performance)

        # احتفظ بآخر 100 فقط
        if len(history) > 100:
            history = history[-100:]

        save_performance_history(history)
        return True
    except Exception as e:
        logger.error(f"خطأ في الحفظ: {e}")
        return False


# ==================== API خارجي ====================

def get_performance_summary():
    """ملخص سريع للأداء"""
    try:
        performance = get_full_performance(days=30)
        if not performance:
            return None

        evaluation = evaluate_performance(performance)

        return {
            'performance': performance,
            'evaluation': evaluation
        }
    except Exception as e:
        logger.error(f"خطأ: {e}")
        return None


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print("🧪 اختبار performance_tracker...")
    result = get_performance_summary()

    if result:
        perf = result['performance']
        eval_ = result['evaluation']

        print(f"\n📊 التقرير:")
        print(f"   صفقات: {perf['total_trades']}")
        print(f"   نسبة النجاح: {perf['win_rate']}%")
        print(f"   Profit Factor: {perf['profit_factor']}")
        print(f"   R:R: {perf['rr_ratio']}")
        print(f"   Sharpe: {perf['sharpe_ratio']}")
        print(f"   Max DD: {perf['max_drawdown']}")
        print(f"   صافي: {perf['total_pnl']:+.4f}")

        print(f"\n🎯 التقييم: {eval_['rating']} ({eval_['score']}/100)")
    else:
        print("⏳ لا توجد بيانات كافية")