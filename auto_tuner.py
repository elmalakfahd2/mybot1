# ==================================================
# 📁 ملف: auto_tuner.py - الإصدار v5.7
# ⚠️ v5.7: هذا الملف لم يعد جزءاً من حلقة التعلم. الأوزان في SCORE_WEIGHTS لا تُقرأ
#    في حساب النقاط، وconfig.py على Railway قرص مؤقت. التعلم الفعلي في adaptive_rules.py.
#    بقي الملف للتوافق (get_tuning_stats) وrestart_bot صار آمناً (لا يعيد تحميل الاستراتيجية).
# 🔧 التعديلات v5.6:
#    - 🔥 إصلاح regex (يتعامل مع الأعداد الصحيحة والعشرية)
#    - 🔥 إصلاح تحديث الأوزان في config.py
#    - 🔥 إصلاح تحديث الأوزان في الذاكرة
# 📅 التاريخ: 2026-09-26
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


# ==================== تعديل config.py ====================

def read_config():
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return f.read()
    except Exception as e:
        logger.error(f"خطأ في قراءة config.py: {e}")
        return None


def write_config(content):
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            f.write(content)
        logger.info("✅ تم تحديث config.py")
        return True
    except Exception as e:
        logger.error(f"خطأ في كتابة config.py: {e}")
        return False


def update_weight_in_config(content, weight_name, new_value):
    """
    🔥 v5.6: regex يعمل مع الأعداد الصحيحة والعشرية
    """
    try:
        # 🔥 النمط: يتعامل مع 20 أو 20.5 أو 20.55
        # يبحث عن: 'weight_name': <number>
        pattern = rf"('{weight_name}'\s*:\s*)(-?\d+(?:\.\d+)?)"

        match = re.search(pattern, content)
        if not match:
            logger.warning(f"⚠️ لم يتم العثور على الوزن: {weight_name}")
            return content

        old_value = match.group(2)

        # 🔥 استبدال
        def replace(m):
            return f"{m.group(1)}{new_value:.1f}"

        new_content = re.sub(pattern, replace, content, count=1)

        if new_content == content:
            logger.warning(f"⚠️ لم يتم تعديل: {weight_name}")
            return content

        logger.info(f"   ✅ {weight_name}: {old_value} → {new_value:.1f}")
        return new_content

    except Exception as e:
        logger.error(f"خطأ في تحديث الوزن {weight_name}: {e}")
        return content


def apply_weight_changes(weight_changes):
    """تطبيق التغييرات على config.py"""
    try:
        content = read_config()
        if not content:
            return False

        logger.info(f"🔧 تطبيق {len(weight_changes)} تغيير...")

        for weight_name, new_value in weight_changes.items():
            content = update_weight_in_config(content, weight_name, new_value)

        # إضافة تعليق
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        comment = f"\n# 🔥 تم التحديث تلقائياً: {timestamp}\n"

        if "# 🔥 تم التحديث تلقائياً" not in content:
            content = content.rstrip() + "\n" + comment

        return write_config(content)

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
        msg += f"   • Profit Factor: {analysis.get('profit_factor', 0):.2f}\n"
        msg += f"   • متوسط الربح: {analysis.get('avg_win', 0):+.4f}\n"
        msg += f"   • متوسط الخسارة: {analysis.get('avg_loss', 0):+.4f}\n\n"

        msg += f"🔧 <b>الأوزان الجديدة:</b>\n"
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

        suggestions = analysis.get('recommendations', {}).get('suggestions', [])
        warnings = analysis.get('recommendations', {}).get('warnings', [])

        if suggestions:
            msg += f"\n💡 <b>ملاحظات:</b>\n"
            for s in suggestions[:3]:
                msg += f"   {s}\n"

        if warnings:
            msg += f"\n⚠️ <b>تحذيرات:</b>\n"
            for w in warnings[:3]:
                msg += f"   {w}\n"

        msg += f"\n⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        return msg
    except Exception as e:
        logger.error(f"خطأ: {e}")
        return f"🧠 تم تحديث الأوزان\n{datetime.now()}"


# ==================== تحديث في الذاكرة ====================

def restart_bot():
    """v5.7: آمن - لا يعيد تحميل bot_strategies_enhanced (كان يمسح التبريد ولا يفيد)"""
    try:
        import importlib
        import config
        importlib.reload(config)
        logger.info("✅ تم إعادة تحميل config فقط")
    except Exception as e:
        logger.error(f"❌ فشل التحديث: {e}")


# ==================== الدالة الرئيسية ====================

def run_tuning():
    try:
        logger.info("=" * 60)
        logger.info("🧠 بدء التعديل التلقائي...")
        logger.info("=" * 60)

        from config import (
            ENABLE_AUTO_LEARNING, AUTO_LEARN_MIN_TRADES,
            AUTO_TUNE_WEIGHTS, AUTO_RESTART_AFTER_TUNE,
            AUTO_LEARN_BACKUP_ENABLED, SCORE_WEIGHTS,
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

        old_weights = {k: v for k, v in SCORE_WEIGHTS.items() if k != 'max_score'}

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

        logger.info("✅ تم التعديل بنجاح")

        if AUTO_RESTART_AFTER_TUNE:
            restart_bot()

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
    print("🧪 اختبار auto_tuner v5.6...")
    result = run_tuning()
    print(f"النتيجة: {result}")