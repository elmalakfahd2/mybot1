# ==================================================
# 📁 ملف: auto_tuner.py - v6.0
# 🔧 التعديلات v6.0:
#    - 🔥 كتابة الأوزان في learned_weights.json (بدل config.py)
#    - 🔥 إزالة restart_bot (لا يمسح التبريدات)
#    - 🔥 config.py يبقى نظيفاً
# ==================================================

import os
import re
import json
import shutil
import logging
import threading
import asyncio
from datetime import datetime

logger = logging.getLogger("auto_tuner")

CONFIG_FILE = "config.py"
BACKUP_DIR = "config_backups"
TUNING_HISTORY_FILE = "tuning_history.json"
LEARNED_WEIGHTS_FILE = "learned_weights.json"


# ==================== النسخ الاحتياطي ====================

def ensure_backup_dir():
    if not os.path.exists(BACKUP_DIR):
        os.makedirs(BACKUP_DIR)


def create_backup():
    try:
        ensure_backup_dir()
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = os.path.join(BACKUP_DIR, f"config_{timestamp}.py")
        shutil.copy2(CONFIG_FILE, backup_path)
        logger.info(f"✅ نسخة احتياطية: {backup_path}")
        cleanup_old_backups(max_keep=10)
        return backup_path
    except Exception as e:
        logger.error(f"❌ فشل النسخ الاحتياطي: {e}")
        return None


def cleanup_old_backups(max_keep=10):
    try:
        ensure_backup_dir()
        backups = sorted([f for f in os.listdir(BACKUP_DIR)
                         if f.startswith("config_") and f.endswith(".py")])
        if len(backups) > max_keep:
            for old in backups[:-max_keep]:
                os.remove(os.path.join(BACKUP_DIR, old))
    except Exception as e:
        logger.error(f"خطأ: {e}")


# ==================== 🔥 كتابة الأوزان في JSON (جديد v6.0) ====================

def load_learned_weights():
    """قراءة الأوزان المتعلَّمة من JSON"""
    try:
        if not os.path.exists(LEARNED_WEIGHTS_FILE):
            return {}
        with open(LEARNED_WEIGHTS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"خطأ قراءة learned_weights: {e}")
        return {}


def save_learned_weights(weights_data):
    """حفظ الأوزان المتعلَّمة في JSON"""
    try:
        with open(LEARNED_WEIGHTS_FILE, "w", encoding="utf-8") as f:
            json.dump(weights_data, f, indent=2, ensure_ascii=False)
        logger.info(f"✅ تم حفظ الأوزان في {LEARNED_WEIGHTS_FILE}")
        return True
    except Exception as e:
        logger.error(f"❌ فشل حفظ الأوزان: {e}")
        return False


def apply_weight_changes(weight_changes):
    """
    🔥 v6.0: حفظ الأوزان في learned_weights.json
    (بدل تعديل config.py الذي يضيع عند إعادة النشر)
    """
    try:
        current = load_learned_weights()
        
        # تحديث الأوزان
        for name, value in weight_changes.items():
            current[name] = round(value, 2)
        
        current["last_updated"] = datetime.now().isoformat()
        current["updated_by"] = "auto_tuner_v6.0"
        
        success = save_learned_weights(current)
        
        if success:
            logger.info(f"🔧 تم تحديث {len(weight_changes)} وزن في JSON")
        
        return success

    except Exception as e:
        logger.error(f"خطأ في تطبيق التغييرات: {e}")
        return False


# ==================== سجل التعديلات ====================

def load_tuning_history():
    try:
        if not os.path.exists(TUNING_HISTORY_FILE):
            return []
        with open(TUNING_HISTORY_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return []


def save_tuning_history(history):
    try:
        with open(TUNING_HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(history, f, indent=2, ensure_ascii=False)
        return True
    except:
        return False


def record_tuning(analysis, weight_changes):
    try:
        history = load_tuning_history()
        history.append({
            'timestamp': datetime.now().isoformat(),
            'analysis': analysis,
            'weight_changes': weight_changes
        })
        save_tuning_history(history)
        return True
    except:
        return False


# ==================== Telegram ====================

def send_telegram_message(text):
    try:
        from telegram import Bot
        from config import TELEGRAM_TOKEN, TELEGRAM_CHAT_ID
        bot = Bot(token=TELEGRAM_TOKEN)

        async def send_async():
            await bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=text, parse_mode="HTML")

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(send_async())
        finally:
            loop.close()

        logger.info("✅ تم إرسال الإشعار")
        return True
    except Exception as e:
        logger.error(f"❌ فشل الإشعار: {e}")
        return False


def format_tuning_report(analysis, weight_changes, old_weights):
    try:
        msg = "🧠 <b>تم تحديث الأوزان تلقائياً</b>\n\n"
        msg += f"📊 <b>التحليل:</b>\n"
        msg += f"   • صفقات: {analysis.get('trades_analyzed', 0)}\n"
        msg += f"   • نسبة النجاح: {analysis.get('win_rate', 0):.1f}%\n"
        msg += f"   • Profit Factor: {analysis.get('profit_factor', 0):.2f}\n\n"

        msg += f"🔧 <b>الأوزان الجديدة (JSON):</b>\n"
        for name, new_val in weight_changes.items():
            old_val = old_weights.get(name, 10)
            change = new_val - old_val

            if change > 0.1:
                arrow = "🔼"
            elif change < -0.1:
                arrow = "🔽"
            else:
                arrow = "➡️"

            msg += f"   {arrow} {name}: {old_val:.1f} → {new_val:.1f}\n"

        msg += f"\n📁 محفوظة في: learned_weights.json"
        msg += f"\n⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        return msg
    except Exception as e:
        logger.error(f"خطأ: {e}")
        return f"🧠 تم تحديث الأوزان\n{datetime.now()}"


# ==================== 🔥 إزالة restart_bot (v6.0) ====================

def restart_bot():
    """
    🔥 v6.0: تم إلغاء هذه الدالة
    السبب: importlib.reload كان يصفّر _symbol_cooldown
    الآن: لا حاجة لإعادة التحميل - bot_strategies يقرأ JSON كل مرة
    """
    logger.info("ℹ️ restart_bot معطل في v6.0 - لا حاجة لإعادة تحميل")
    return True


# ==================== الدالة الرئيسية ====================

def run_tuning():
    try:
        logger.info("=" * 60)
        logger.info("🧠 بدء التعديل التلقائي v6.0...")
        logger.info("=" * 60)

        from config import (
            ENABLE_AUTO_LEARNING, AUTO_LEARN_MIN_TRADES,
            AUTO_TUNE_WEIGHTS, SCORE_WEIGHTS,
        )

        if not ENABLE_AUTO_LEARNING or not AUTO_TUNE_WEIGHTS:
            logger.info("ℹ️ التعلم معطل")
            return False

        import auto_learner
        analysis = auto_learner.analyze_performance(min_trades=AUTO_LEARN_MIN_TRADES)
        if not analysis:
            return False

        weight_changes = analysis.get('recommendations', {}).get('weight_changes', {})
        if not weight_changes:
            logger.info("ℹ️ لا توجد تغييرات")
            return False

        old_weights = load_learned_weights() or {k: v for k, v in SCORE_WEIGHTS.items() if k != 'max_score'}

        if AUTO_LEARN_BACKUP_ENABLED:
            create_backup()

        success = apply_weight_changes(weight_changes)
        if not success:
            logger.error("❌ فشل التطبيق")
            return False

        record_tuning(analysis, weight_changes)

        try:
            report = format_tuning_report(analysis, weight_changes, old_weights)
            send_telegram_message(report)
        except Exception as e:
            logger.error(f"فشل الإشعار: {e}")

        logger.info("✅ تم التعديل بنجاح (JSON)")
        return True

    except Exception as e:
        logger.error(f"❌ فشل: {e}")
        import traceback
        traceback.print_exc()
        return False


def get_tuning_stats():
    try:
        history = load_tuning_history()
        if not history:
            return {'total_tunings': 0, 'last_tuning': None, 'recent_changes': []}

        return {
            'total_tunings': len(history),
            'last_tuning': history[-1].get('timestamp'),
            'recent_changes': [
                {'time': h.get('timestamp'), 'changes': h.get('weight_changes', {})}
                for h in history[-5:]
            ]
        }
    except:
        return {'total_tunings': 0, 'last_tuning': None, 'recent_changes': []}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print("🧪 اختبار auto_tuner v6.0...")
    result = run_tuning()
    print(f"النتيجة: {result}")