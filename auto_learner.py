# ==================================================
# 📁 ملف: auto_learner.py - الإصدار v5.0
# 🔧 الوصف:
#    - قراءة trade_memory.json
#    - تحليل كل صفقة
#    - حساب correlation لكل ميزة
#    - إرجاع الأوزان الموصى بها
#    - لا يحتاج تدخل يدوي
# 📅 التاريخ: 2026-09-22
# ==================================================

import json
import os
import logging
from datetime import datetime, timedelta
from collections import defaultdict

logger = logging.getLogger("auto_learner")

MEMORY_FILE = "trade_memory.json"
LEARNING_HISTORY_FILE = "learning_history.json"


def _ensure_memory_file():
    """التأكد من وجود ملف الذاكرة"""
    if not os.path.exists(MEMORY_FILE):
        with open(MEMORY_FILE, "w", encoding="utf-8") as f:
            json.dump({
                "trades": [],
                "symbol_stats": {},
                "hourly_stats": {},
                "last_updated": datetime.now().isoformat(),
                "total_trades": 0,
                "total_wins": 0,
                "total_losses": 0,
                "total_pnl": 0.0
            }, f, indent=2, ensure_ascii=False)


def load_memory():
    """تحميل الذاكرة"""
    try:
        _ensure_memory_file()
        with open(MEMORY_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"خطأ في تحميل الذاكرة: {e}")
        return {"trades": []}


def load_learning_history():
    """تحميل سجل التعلم"""
    try:
        if not os.path.exists(LEARNING_HISTORY_FILE):
            return []
        with open(LEARNING_HISTORY_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return []


def save_learning_history(history):
    """حفظ سجل التعلم"""
    try:
        with open(LEARNING_HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(history, f, indent=2, ensure_ascii=False)
        return True
    except Exception as e:
        logger.error(f"خطأ في حفظ سجل التعلم: {e}")
        return False


# ==================== حساب الارتباط ====================

def calculate_correlation(feature_values, outcomes):
    """
    حساب ارتباط بيرسون بين ميزة والنتيجة
    feature_values: قائمة قيم الميزة
    outcomes: قائمة النتائج (1 = ربح، 0 = خسارة)
    """
    try:
        n = len(feature_values)
        if n < 5:
            return 0.0

        mean_x = sum(feature_values) / n
        mean_y = sum(outcomes) / n

        numerator = sum(
            (feature_values[i] - mean_x) * (outcomes[i] - mean_y)
            for i in range(n)
        )

        std_x = (sum((x - mean_x) ** 2 for x in feature_values) / n) ** 0.5
        std_y = (sum((y - mean_y) ** 2 for y in outcomes) / n) ** 0.5

        if std_x == 0 or std_y == 0:
            return 0.0

        return round(numerator / (n * std_x * std_y), 4)

    except Exception as e:
        logger.error(f"خطأ في حساب الارتباط: {e}")
        return 0.0


# ==================== التحليل الرئيسي ====================

def analyze_performance(min_trades=30):
    """
    تحليل أداء البوت وتحديد الأوزان المثالية
    """
    try:
        memory = load_memory()
        trades = memory.get("trades", [])

        if len(trades) < min_trades:
            logger.info(f"⏳ عدد الصفقات غير كافٍ ({len(trades)}/{min_trades})")
            return None

        # آخر min_trades صفقة
        recent_trades = trades[-min_trades:]

        logger.info(f"📊 تحليل {len(recent_trades)} صفقة...")

        # ==================== جمع الميزات ====================
        features = {
            'timeframe_alignment': [],
            'volume_ratio': [],
            'rsi': [],
            'momentum_strength': [],
            'confidence': [],
            'groq_confidence': [],
            'order_book_points': [],
            'funding_oi_points': [],
            'market_points': [],
        }
        outcomes = []

        for trade in recent_trades:
            score_details = trade.get('score_details', {})
            is_win = 1 if trade.get('is_win', False) else 0
            outcomes.append(is_win)

            # استخراج الميزات
            features['timeframe_alignment'].append(
                float(trade.get('timeframe_alignment', 0))
            )
            features['volume_ratio'].append(
                float(trade.get('volume_ratio', 0))
            )
            features['rsi'].append(
                float(trade.get('rsi', 50)) if 'rsi' in trade else 50.0
            )
            features['momentum_strength'].append(
                float(score_details.get('momentum_points', 0))
            )
            features['confidence'].append(
                float(trade.get('confidence', 0))
            )
            features['groq_confidence'].append(
                float(trade.get('groq_confidence', 0))
            )
            features['order_book_points'].append(
                float(score_details.get('order_book_points', 0))
            )
            features['funding_oi_points'].append(
                float(score_details.get('funding_oi_points', 0))
            )
            features['market_points'].append(
                float(score_details.get('market_points', 0))
            )

        # ==================== حساب الارتباطات ====================
        correlations = {}
        for feature_name, values in features.items():
            if len(values) == len(outcomes) and len(values) >= 5:
                corr = calculate_correlation(values, outcomes)
                correlations[feature_name] = corr
                logger.info(f"   • {feature_name}: {corr:+.3f}")

        # ==================== إحصاءات إضافية ====================
        wins = [t for t in recent_trades if t.get('is_win')]
        losses = [t for t in recent_trades if not t.get('is_win')]

        win_count = len(wins)
        loss_count = len(losses)
        win_rate = win_count / len(recent_trades) if recent_trades else 0

        avg_win = sum(t.get('pnl', 0) for t in wins) / win_count if win_count > 0 else 0
        avg_loss = sum(t.get('pnl', 0) for t in losses) / loss_count if loss_count > 0 else 0

        # ==================== التوصيات ====================
        recommendations = generate_recommendations(
            correlations, win_rate, avg_win, avg_loss
        )

        # ==================== بناء النتيجة ====================
        result = {
            'timestamp': datetime.now().isoformat(),
            'trades_analyzed': len(recent_trades),
            'win_rate': round(win_rate * 100, 2),
            'win_count': win_count,
            'loss_count': loss_count,
            'avg_win': round(avg_win, 4),
            'avg_loss': round(avg_loss, 4),
            'profit_factor': round(abs(avg_win * win_count) / abs(avg_loss * loss_count), 2) if loss_count > 0 and avg_loss != 0 else 0,
            'correlations': correlations,
            'recommendations': recommendations
        }

        return result

    except Exception as e:
        logger.error(f"خطأ في التحليل: {e}")
        import traceback
        traceback.print_exc()
        return None


def generate_recommendations(correlations, win_rate, avg_win, avg_loss):
    """توليد التوصيات بناءً على الارتباطات"""
    try:
        recommendations = {
            'weight_changes': {},
            'suggestions': [],
            'warnings': []
        }

        # ==================== تعديلات الأوزان ====================
        # الميزات ذات الارتباط القوي (> 0.3) → وزن أعلى
        # الميزات ذات الارتباط الضعيف (< 0.1) → وزن أقل

        current_weights = {
            'timeframe_alignment': 20,
            'volume': 17,
            'groq': 20,
            'rsi_ideal': 12,
            'momentum': 8,
            'price_action': 3,
            'market_regime': 5,
            'order_book': 10,
            'funding_oi': 5,
        }

        # ربط أسماء الميزات بأسماء الأوزان
        mapping = {
            'timeframe_alignment': 'timeframe_alignment',
            'volume_ratio': 'volume',
            'rsi': 'rsi_ideal',
            'momentum_strength': 'momentum',
            'confidence': 'groq',  # تقريبي
            'groq_confidence': 'groq',
            'order_book_points': 'order_book',
            'funding_oi_points': 'funding_oi',
            'market_points': 'market_regime',
        }

        for feature_name, corr in correlations.items():
            if feature_name not in mapping:
                continue

            weight_name = mapping[feature_name]
            current = current_weights.get(weight_name, 10)

            # تعديل بنسبة الارتباط (مع حد أقصى 30%)
            if corr > 0.3:
                # ميزة قوية
                change = min(0.30, corr * 0.5)
                new_weight = current * (1 + change)
                recommendations['weight_changes'][weight_name] = round(new_weight, 1)

            elif corr < 0.05:
                # ميزة ضعيفة
                change = min(0.30, (0.1 - corr) * 2)
                new_weight = current * (1 - change)
                recommendations['weight_changes'][weight_name] = round(new_weight, 1)

        # ==================== التوصيات ====================
        if win_rate < 0.40:
            recommendations['warnings'].append(
                f"⚠️ نسبة النجاح منخفضة: {win_rate*100:.1f}%"
            )

        if win_rate > 0.60:
            recommendations['suggestions'].append(
                f"✅ نسبة النجاح ممتازة: {win_rate*100:.1f}%"
            )

        if avg_loss != 0 and abs(avg_win / avg_loss) < 1.0:
            recommendations['warnings'].append(
                f"⚠️ R:R سيئة: متوسط الربح {avg_win:.2f} vs الخسارة {avg_loss:.2f}"
            )

        # أفضل/أسوأ الميزات
        sorted_corr = sorted(correlations.items(), key=lambda x: x[1], reverse=True)
        if sorted_corr:
            best = sorted_corr[0]
            worst = sorted_corr[-1]
            recommendations['suggestions'].append(
                f"📈 أفضل ميزة: {best[0]} ({best[1]:+.3f})"
            )
            recommendations['warnings'].append(
                f"📉 أسوأ ميزة: {worst[0]} ({worst[1]:+.3f})"
            )

        return recommendations

    except Exception as e:
        logger.error(f"خطأ في التوصيات: {e}")
        return {'weight_changes': {}, 'suggestions': [], 'warnings': []}


# ==================== اقتراح الأوزان الجديدة ====================

def suggest_new_weights(min_trades=30):
    """
    اقتراح أوزان جديدة بناءً على التحليل
    """
    try:
        result = analyze_performance(min_trades)
        if not result:
            return None

        weight_changes = result.get('recommendations', {}).get('weight_changes', {})
        if not weight_changes:
            logger.info("ℹ️ لا توجد تغييرات مقترحة")
            return None

        return {
            'new_weights': weight_changes,
            'analysis': result,
            'confidence': min(1.0, len(result.get('correlations', {})) / 10)
        }

    except Exception as e:
        logger.error(f"خطأ في اقتراح الأوزان: {e}")
        return None


# ==================== التوافق ====================

def get_learning_stats():
    """إحصائيات التعلم"""
    try:
        history = load_learning_history()
        return {
            'total_sessions': len(history),
            'last_session': history[-1] if history else None,
            'first_session': history[0] if history else None
        }
    except:
        return {'total_sessions': 0, 'last_session': None}


def run_analysis():
    """تشغيل التحليل الكامل (للاستخدام الخارجي)"""
    try:
        logger.info("🧠 بدء التحليل التلقائي...")

        result = analyze_performance()
        if not result:
            logger.info("⏳ لا يوجد ما يكفي من البيانات")
            return None

        # حفظ في السجل
        history = load_learning_history()
        history.append(result)
        save_learning_history(history)

        # طباعة التقرير
        logger.info("=" * 60)
        logger.info(f"📊 تقرير التحليل ({result['trades_analyzed']} صفقة)")
        logger.info(f"   نسبة النجاح: {result['win_rate']}%")
        logger.info(f"   Profit Factor: {result['profit_factor']}")
        logger.info(f"   متوسط الربح: {result['avg_win']:+.4f}")
        logger.info(f"   متوسط الخسارة: {result['avg_loss']:+.4f}")

        for suggestion in result['recommendations'].get('suggestions', []):
            logger.info(f"   {suggestion}")

        for warning in result['recommendations'].get('warnings', []):
            logger.info(f"   {warning}")

        logger.info("=" * 60)

        return result

    except Exception as e:
        logger.error(f"خطأ في التشغيل: {e}")
        return None


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print("🧪 اختبار auto_learner...")
    result = run_analysis()
    if result:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print("⏳ لا توجد بيانات كافية")