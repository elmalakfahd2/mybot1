# ==================================================
# 📁 ملف: auto_learner.py - الإصدار v5.3
# 🔧 التعديلات v5.3:
#    - 🔥 تحليل مفصّل: لماذا خسرت؟
#    - 🔥 مقارنة الرابحة vs الخاسرة
#    - 🔥 تحديد الأنماط الشائعة
#    - 🔥 AUTO_LEARN_MIN_TRADES = 10
# 📅 التاريخ: 2026-09-24
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
    if not os.path.exists(MEMORY_FILE):
        with open(MEMORY_FILE, "w", encoding="utf-8") as f:
            json.dump({
                "trades": [], "symbol_stats": {}, "hourly_stats": {},
                "last_updated": datetime.now().isoformat(),
                "total_trades": 0, "total_wins": 0,
                "total_losses": 0, "total_pnl": 0.0
            }, f, indent=2, ensure_ascii=False)


def load_memory():
    try:
        _ensure_memory_file()
        with open(MEMORY_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"خطأ: {e}")
        return {"trades": []}


def load_learning_history():
    try:
        if not os.path.exists(LEARNING_HISTORY_FILE):
            return []
        with open(LEARNING_HISTORY_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return []


def save_learning_history(history):
    try:
        with open(LEARNING_HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(history, f, indent=2, ensure_ascii=False)
        return True
    except Exception as e:
        logger.error(f"خطأ: {e}")
        return False


# ==================== حساب الارتباط ====================

def calculate_correlation(feature_values, outcomes):
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
        logger.error(f"خطأ: {e}")
        return 0.0


# ==================== 🔥 تحليل مفصل: لماذا خسرت؟ ====================

def analyze_why_lost(trades):
    """
    🔥 تحليل مفصّل: لماذا خسرت الصفقات؟
    """
    try:
        wins = [t for t in trades if t.get('is_win', False)]
        losses = [t for t in trades if not t.get('is_win', False)]

        if not losses:
            return {
                'common_losses': [],
                'common_wins': [],
                'comparisons': []
            }

        # ==================== مقارنة الخصائص ====================
        features_to_compare = [
            ('rsi', 'RSI', lambda t: t.get('score_details', {}).get('rsi_points', 0)),
            ('volume', 'الحجم', lambda t: t.get('volume_ratio', 0)),
            ('timeframe', 'ترابط الفريمات', lambda t: t.get('timeframe_alignment', 0)),
            ('momentum', 'الزخم', lambda t: t.get('score_details', {}).get('momentum_points', 0)),
            ('order_book', 'دفتر الأوامر', lambda t: t.get('score_details', {}).get('order_book_points', 0)),
            ('confidence', 'الثقة', lambda t: t.get('confidence', 0)),
            ('groq_conf', 'ثقة Groq', lambda t: t.get('groq_confidence', 0)),
            ('market', 'السوق', lambda t: t.get('score_details', {}).get('market_points', 0)),
            ('funding', 'Funding/OI', lambda t: t.get('score_details', {}).get('funding_oi_points', 0)),
            ('price_action', 'Price Action', lambda t: t.get('score_details', {}).get('price_action_points', 0)),
        ]

        comparisons = []

        for key, name_ar, extractor in features_to_compare:
            try:
                win_values = [extractor(t) for t in wins if extractor(t) is not None]
                loss_values = [extractor(t) for t in losses if extractor(t) is not None]

                if not win_values or not loss_values:
                    continue

                win_avg = sum(win_values) / len(win_values)
                loss_avg = sum(loss_values) / len(loss_values)
                diff = win_avg - loss_avg

                comparisons.append({
                    'feature': key,
                    'name': name_ar,
                    'win_avg': round(win_avg, 2),
                    'loss_avg': round(loss_avg, 2),
                    'diff': round(diff, 2),
                    'significant': abs(diff) > (abs(win_avg) * 0.15 if win_avg != 0 else 1)
                })
            except:
                continue

        # ترتيب حسب الأهمية
        comparisons.sort(key=lambda x: abs(x['diff']), reverse=True)

        # ==================== أنماط الخسائر ====================
        common_losses = []

        # 1. RSI مرتفع جداً
        high_rsi_losses = [t for t in losses if t.get('score_details', {}).get('rsi_points', 0) == 0]
        if len(high_rsi_losses) >= 2:
            common_losses.append({
                'pattern': 'RSI غير مثالي',
                'count': len(high_rsi_losses),
                'total_losses': len(losses),
                'description': f"RSI كان خارج النطاق المثالي في {len(high_rsi_losses)}/{len(losses)} خسارة"
            })

        # 2. دفتر أوامر ضعيف
        weak_ob_losses = [t for t in losses if t.get('score_details', {}).get('order_book_points', 0) < 3]
        if len(weak_ob_losses) >= 2:
            common_losses.append({
                'pattern': 'دفتر أوامر ضعيف',
                'count': len(weak_ob_losses),
                'total_losses': len(losses),
                'description': f"دفتر الأوامر كان ضعيفاً في {len(weak_ob_losses)}/{len(losses)} خسارة"
            })

        # 3. حجم منخفض
        low_volume_losses = [t for t in losses if t.get('volume_ratio', 0) < 1.3]
        if len(low_volume_losses) >= 2:
            common_losses.append({
                'pattern': 'حجم منخفض',
                'count': len(low_volume_losses),
                'total_losses': len(losses),
                'description': f"الحجم كان منخفضاً في {len(low_volume_losses)}/{len(losses)} خسارة"
            })

        # 4. Momentum معاكس
        wrong_momentum_losses = [t for t in losses if t.get('score_details', {}).get('momentum_points', 0) == 0]
        if len(wrong_momentum_losses) >= 2:
            common_losses.append({
                'pattern': 'Momentum معاكس',
                'count': len(wrong_momentum_losses),
                'total_losses': len(losses),
                'description': f"Momentum كان معاكساً في {len(wrong_momentum_losses)}/{len(losses)} خسارة"
            })

        # 5. ثقة منخفضة
        low_conf_losses = [t for t in losses if t.get('confidence', 0) < 60]
        if len(low_conf_losses) >= 2:
            common_losses.append({
                'pattern': 'ثقة منخفضة',
                'count': len(low_conf_losses),
                'total_losses': len(losses),
                'description': f"الثقة كانت منخفضة في {len(low_conf_losses)}/{len(losses)} خسارة"
            })

        # 6. السوق معاكس
        bad_market_losses = [t for t in losses if t.get('score_details', {}).get('market_points', 0) < 3]
        if len(bad_market_losses) >= 2:
            common_losses.append({
                'pattern': 'سوق معاكس',
                'count': len(bad_market_losses),
                'total_losses': len(losses),
                'description': f"حالة السوق كانت سيئة في {len(bad_market_losses)}/{len(losses)} خسارة"
            })

        # ==================== أنماط الربح ====================
        common_wins = []

        good_volume_wins = [t for t in wins if t.get('volume_ratio', 0) >= 1.5]
        if len(good_volume_wins) >= 2:
            common_wins.append({
                'pattern': 'حجم قوي',
                'count': len(good_volume_wins),
                'total_wins': len(wins),
                'description': f"الحجم كان قوياً في {len(good_volume_wins)}/{len(wins)} ربح"
            })

        good_ob_wins = [t for t in wins if t.get('score_details', {}).get('order_book_points', 0) >= 7]
        if len(good_ob_wins) >= 2:
            common_wins.append({
                'pattern': 'دفتر أوامر قوي',
                'count': len(good_ob_wins),
                'total_wins': len(wins),
                'description': f"دفتر الأوامر كان قوياً في {len(good_ob_wins)}/{len(wins)} ربح"
            })

        good_conf_wins = [t for t in wins if t.get('confidence', 0) >= 70]
        if len(good_conf_wins) >= 2:
            common_wins.append({
                'pattern': 'ثقة عالية',
                'count': len(good_conf_wins),
                'total_wins': len(wins),
                'description': f"الثقة كانت عالية في {len(good_conf_wins)}/{len(wins)} ربح"
            })

        return {
            'common_losses': common_losses,
            'common_wins': common_wins,
            'comparisons': comparisons[:5]  # أفضل 5 مقارنات
        }

    except Exception as e:
        logger.error(f"خطأ في analyze_why_lost: {e}")
        import traceback
        traceback.print_exc()
        return {'common_losses': [], 'common_wins': [], 'comparisons': []}


# ==================== التحليل الرئيسي ====================

def analyze_performance(min_trades=20):
    """
    تحليل أداء البوت وتحديد الأوزان المثالية
    """
    try:
        memory = load_memory()
        # 🔥 v5.7: الصفقات الموثقة (PnL حقيقي) فقط - القديمة كانت أرقامها خاطئة
        trades = [t for t in memory.get("trades", []) if t.get("pnl_verified")]

        if len(trades) < min_trades:
            logger.info(f"⏳ عدد الصفقات الموثقة غير كافٍ ({len(trades)}/{min_trades})")
            return None

        recent_trades = trades[-max(min_trades, 40):]

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

            features['timeframe_alignment'].append(float(trade.get('timeframe_alignment', 0)))
            features['volume_ratio'].append(float(trade.get('volume_ratio', 0)))
            features['rsi'].append(float(trade.get('score_details', {}).get('rsi_points', 0)))
            features['momentum_strength'].append(float(score_details.get('momentum_points', 0)))
            features['confidence'].append(float(trade.get('confidence', 0)))
            features['groq_confidence'].append(float(trade.get('groq_confidence', 0)))
            features['order_book_points'].append(float(score_details.get('order_book_points', 0)))
            features['funding_oi_points'].append(float(score_details.get('funding_oi_points', 0)))
            features['market_points'].append(float(score_details.get('market_points', 0)))

        # ==================== حساب الارتباطات ====================
        correlations = {}
        for feature_name, values in features.items():
            if len(values) == len(outcomes) and len(values) >= 5:
                corr = calculate_correlation(values, outcomes)
                correlations[feature_name] = corr
                logger.info(f"   • {feature_name}: {corr:+.3f}")

        # ==================== إحصاءات ====================
        wins = [t for t in recent_trades if t.get('is_win')]
        losses = [t for t in recent_trades if not t.get('is_win')]

        win_count = len(wins)
        loss_count = len(losses)
        win_rate = win_count / len(recent_trades) if recent_trades else 0

        avg_win = sum(t.get('pnl', 0) for t in wins) / win_count if win_count > 0 else 0
        avg_loss = sum(t.get('pnl', 0) for t in losses) / loss_count if loss_count > 0 else 0

        # ==================== التحليل المفصل ====================
        detailed_analysis = analyze_why_lost(recent_trades)

        # ==================== التوصيات ====================
        recommendations = generate_recommendations(
            correlations, win_rate, avg_win, avg_loss
        )

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
            'recommendations': recommendations,
            'detailed_analysis': detailed_analysis
        }

        return result

    except Exception as e:
        logger.error(f"خطأ في التحليل: {e}")
        import traceback
        traceback.print_exc()
        return None


def generate_recommendations(correlations, win_rate, avg_win, avg_loss):
    """توليد التوصيات"""
    try:
        recommendations = {
            'weight_changes': {},
            'suggestions': [],
            'warnings': []
        }

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

        mapping = {
            'timeframe_alignment': 'timeframe_alignment',
            'volume_ratio': 'volume',
            'rsi': 'rsi_ideal',
            'momentum_strength': 'momentum',
            'confidence': 'groq',
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

            if corr > 0.3:
                change = min(0.30, corr * 0.5)
                new_weight = current * (1 + change)
                recommendations['weight_changes'][weight_name] = round(new_weight, 1)

            elif corr < 0.05:
                change = min(0.30, (0.1 - corr) * 2)
                new_weight = current * (1 - change)
                recommendations['weight_changes'][weight_name] = round(new_weight, 1)

        if win_rate < 0.40:
            recommendations['warnings'].append(f"⚠️ نسبة النجاح منخفضة: {win_rate*100:.1f}%")

        if win_rate > 0.60:
            recommendations['suggestions'].append(f"✅ نسبة النجاح ممتازة: {win_rate*100:.1f}%")

        if avg_loss != 0 and abs(avg_win / avg_loss) < 1.0:
            recommendations['warnings'].append(f"⚠️ R:R سيئة: {avg_win:.2f} vs {avg_loss:.2f}")

        sorted_corr = sorted(correlations.items(), key=lambda x: x[1], reverse=True)
        if sorted_corr:
            best = sorted_corr[0]
            worst = sorted_corr[-1]
            recommendations['suggestions'].append(f"📈 أفضل ميزة: {best[0]} ({best[1]:+.3f})")
            recommendations['warnings'].append(f"📉 أسوأ ميزة: {worst[0]} ({worst[1]:+.3f})")

        return recommendations

    except Exception as e:
        logger.error(f"خطأ: {e}")
        return {'weight_changes': {}, 'suggestions': [], 'warnings': []}


def suggest_new_weights(min_trades=10):
    try:
        result = analyze_performance(min_trades)
        if not result:
            return None

        weight_changes = result.get('recommendations', {}).get('weight_changes', {})
        if not weight_changes:
            return None

        return {
            'new_weights': weight_changes,
            'analysis': result,
            'confidence': min(1.0, len(result.get('correlations', {})) / 10)
        }

    except Exception as e:
        logger.error(f"خطأ: {e}")
        return None


def get_learning_stats():
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
    """تشغيل التحليل الكامل"""
    try:
        logger.info("🧠 بدء التحليل التلقائي...")

        result = analyze_performance()
        if not result:
            logger.info("⏳ لا يوجد ما يكفي من البيانات")
            return None

        history = load_learning_history()
        history.append(result)
        save_learning_history(history)

        logger.info("=" * 60)
        logger.info(f"📊 تقرير التحليل ({result['trades_analyzed']} صفقة)")
        logger.info(f"   نسبة النجاح: {result['win_rate']}%")
        logger.info(f"   Profit Factor: {result['profit_factor']}")
        logger.info(f"   متوسط الربح: {result['avg_win']:+.4f}")
        logger.info(f"   متوسط الخسارة: {result['avg_loss']:+.4f}")

        # 🔥 الأنماط
        detailed = result.get('detailed_analysis', {})
        if detailed.get('common_losses'):
            logger.info("   ❌ الخسائر الشائعة:")
            for item in detailed['common_losses'][:3]:
                logger.info(f"      • {item['description']}")

        if detailed.get('common_wins'):
            logger.info("   ✅ الأنماط الرابحة:")
            for item in detailed['common_wins'][:3]:
                logger.info(f"      • {item['description']}")

        for suggestion in result['recommendations'].get('suggestions', []):
            logger.info(f"   {suggestion}")

        for warning in result['recommendations'].get('warnings', []):
            logger.info(f"   {warning}")

        logger.info("=" * 60)

        return result

    except Exception as e:
        logger.error(f"خطأ في التشغيل: {e}")
        import traceback
        traceback.print_exc()
        return None


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print("🧪 اختبار auto_learner v5.3...")
    result = run_analysis()
    if result:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print("⏳ لا توجد بيانات كافية")