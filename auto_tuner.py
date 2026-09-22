# ==================================================
# 📁 ملف: auto_tuner.py - الإصدار v5.0
# 🔧 الوصف:
#    - يستلم الأوزان من auto_learner
#    - يعدّل config.py تلقائياً
#    - يعمل نسخة احتياطية قبل التعديل
#    - يعيد تشغيل البوت تلقائياً
#    - يرسل تقرير على Telegram
# 📅 التاريخ: 2026-09-22
# ==================================================

import os
import re
import json
import shutil
import logging
import threading
import asyncio
import subprocess
import sys
from datetime import datetime

logger = logging.getLogger("auto_tuner")

CONFIG_FILE = "config.py"
BACKUP_DIR = "config_backups"
TUNING_HISTORY_FILE = "tuning_history.json"


# ==================== النسخ الاحتياطي ====================

def ensure_backup_dir():
    """التأكد من وجود مجلد النسخ الاحتياطية"""
    if not os.path.exists(BACKUP_DIR):
        os.makedirs(BACKUP_DIR)


def create_backup():
    """إنشاء نسخة احتياطية من config.py"""
    try:
        ensure_backup_dir()
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = os.path.join(BACKUP_DIR, f"config_{timestamp}.py")

        shutil.copy2(CONFIG_FILE, backup_path)
        logger.info(f"✅ نسخة احتياطية: {backup_path}")

        # حذف النسخ القديمة (نحتفظ بآخر 10 فقط)
        cleanup_old_backups(max_keep=10)

        return backup_path

    except Exception as e:
        logger.error(f"❌ فشل النسخ الاحتياطي: {e}")
        return None


def cleanup_old_backups(max_keep=10):
    """حذف النسخ القديمة"""
    try:
        ensure_backup_dir()
        backups = sorted([
            f for f in os.listdir(BACKUP_DIR)
            if f.startswith("config_") and f.endswith(".py")
        ])

        if len(backups) > max_keep:
            for old in backups[:-max_keep]:
                os.remove(os.path.join(BACKUP_DIR, old))
                logger.info(f"🗑️ حذف نسخة قديمة: {old}")

    except Exception as e:
        logger.error(f"خطأ في حذف النسخ: {e}")


# ==================== تعديل config.py ====================

def read_config():
    """قراءة config.py"""
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return f.read()
    except Exception as e:
        logger.error(f"خطأ في قراءة config.py: {e}")
        return None


def write_config(content):
    """كتابة config.py"""
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
    تحديث وزن واحد في SCORE_WEIGHTS
    """
    try:
        # البحث عن SCORE_WEIGHTS
        pattern = rf"(SCORE_WEIGHTS\s*=\s*\{{[^}}]*?'{weight_name}'\s*:\s*)([\d.]+)"

        def replace(match):
            return f"{match.group(1)}{new_value:.1f}"

        new_content = re.sub(pattern, replace, content, flags=re.DOTALL)

        if new_content == content:
            logger.warning(f"⚠️ لم يتم العثور على الوزن: {weight_name}")
            return content

        return new_content

    except Exception as e:
        logger.error(f"خطأ في تحديث الوزن {weight_name}: {e}")
        return content


def apply_weight_changes(weight_changes):
    """
    تطبيق كل التغييرات في الأوزان
    weight_changes: {'timeframe_alignment': 26.0, 'volume': 22.0, ...}
    """
    try:
        content = read_config()
        if not content:
            return False

        logger.info(f"🔧 تطبيق {len(weight_changes)} تغيير...")

        for weight_name, new_value in weight_changes.items():
            content = update_weight_in_config(content, weight_name, new_value)
            logger.info(f"   • {weight_name} → {new_value:.1f}")

        # إضافة تعليق بالتحديث
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
    """تحميل سجل التعديلات"""
    try:
        if not os.path.exists(TUNING_HISTORY_FILE):
            return []
        with open(TUNING_HISTORY_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return []


def save_tuning_history(history):
    """حفظ سجل التعديلات"""
    try:
        with open(TUNING_HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(history, f, indent=2, ensure_ascii=False)
        return True
    except Exception as e:
        logger.error(f"خطأ في حفظ السجل: {e}")
        return False


def record_tuning(analysis, weight_changes):
    """تسجيل عملية تعديل"""
    try:
        history = load_tuning_history()
        history.append({
            'timestamp': datetime.now().isoformat(),
            'analysis': analysis,
            'weight_changes': weight_changes
        })
        save_tuning_history(history)
        return True
    except Exception as e:
        logger.error(f"خطأ في التسجيل: {e}")
        return False


# ==================== إشعارات Telegram ====================

def send_telegram_message(text):
    """إرسال رسالة Telegram"""
    try:
        from telegram import Bot
        from config import TELEGRAM_TOKEN, TELEGRAM_CHAT_ID

        bot = Bot(token=TELEGRAM_TOKEN)

        async def send_async():
            await bot.send_message(
                chat_id=TELEGRAM_CHAT_ID,
                text=text,
                parse_mode="HTML"
            )

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
    """تنسيق تقرير التعديل"""
    try:
        msg = "🧠 <b>تم تحديث الأوزان تلقائياً</b>\n\n"

        # ==================== ملخص التحليل ====================
        msg += f"📊 <b>التحليل:</b>\n"
        msg += f"   • صفقات: {analysis.get('trades_analyzed', 0)}\n"
        msg += f"   • نسبة النجاح: {analysis.get('win_rate', 0):.1f}%\n"
        msg += f"   • Profit Factor: {analysis.get('profit_factor', 0):.2f}\n"
        msg += f"   • متوسط الربح: {analysis.get('avg_win', 0):+.4f}\n"
        msg += f"   • متوسط الخسارة: {analysis.get('avg_loss', 0):+.4f}\n\n"

        # ==================== الأوزان الجديدة ====================
        msg += f"🔧 <b>الأوزان الجديدة:</b>\n"

        for name, new_val in weight_changes.items():
            old_val = old_weights.get(name, 10)
            change = new_val - old_val

            if change > 0:
                arrow = "🔼"
            elif change < 0:
                arrow = "🔽"
            else:
                arrow = "➡️"

            msg += f"   {arrow} {name}: {old_val:.1f} → {new_val:.1f}\n"

        # ==================== التوصيات ====================
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
        logger.error(f"خطأ في تنسيق التقرير: {e}")
        return f"🧠 تم تحديث الأوزان\n{datetime.now()}"


# ==================== إعادة تشغيل البوت ====================

def restart_bot():
    """إعادة تشغيل البوت (من داخل العملية)"""
    try:
        logger.info("🔄 إعادة تشغيل البوت...")

        # في Railway، يمكن استخدام إعادة التشغيل عبر os._exit
        # Railway سيعيد تشغيل الحاوية تلقائياً

        # حفظ الحالة أولاً
        try:
            import trade_memory
            trade_memory.sync_profit_history()
        except:
            pass

        logger.info("✅ تم طلب إعادة التشغيل")
        # ملاحظة: os._exit سيُوقف كل الخيوط

        # انتظر ثانيتين لإرسال الإشعار
        import time
        time.sleep(2)

        os._exit(0)

    except Exception as e:
        logger.error(f"❌ فشل إعادة التشغيل: {e}")


# ==================== الدالة الرئيسية ====================

def run_tuning():
    """
    تشغيل التعديل التلقائي
    """
    try:
        logger.info("=" * 60)
        logger.info("🧠 بدء التعديل التلقائي للأوزان...")
        logger.info("=" * 60)

        # ==================== 1. قراءة الإعدادات ====================
        from config import (
            ENABLE_AUTO_LEARNING,
            AUTO_LEARN_MIN_TRADES,
            AUTO_TUNE_WEIGHTS,
            AUTO_RESTART_AFTER_TUNE,
            AUTO_LEARN_MAX_ADJUSTMENT,
            AUTO_LEARN_BACKUP_ENABLED,
            SCORE_WEIGHTS,
        )

        if not ENABLE_AUTO_LEARNING:
            logger.info("ℹ️ التعلم التلقائي معطل")
            return False

        if not AUTO_TUNE_WEIGHTS:
            logger.info("ℹ️ تعديل الأوزان معطل")
            return False

        # ==================== 2. تحليل الأداء ====================
        import auto_learner

        analysis = auto_learner.analyze_performance(min_trades=AUTO_LEARN_MIN_TRADES)
        if not analysis:
            logger.info("⏳ لا يوجد ما يكفي من البيانات")
            return False

        # ==================== 3. الأوزان الجديدة ====================
        weight_changes = analysis.get('recommendations', {}).get('weight_changes', {})
        if not weight_changes:
            logger.info("ℹ️ لا توجد تغييرات مقترحة")
            return False

        # ==================== 4. النسخة الاحتياطية ====================
        old_weights = {k: v for k, v in SCORE_WEIGHTS.items() if k != 'max_score'}

        if AUTO_LEARN_BACKUP_ENABLED:
            backup_path = create_backup()
            if not backup_path:
                logger.warning("⚠️ فشل النسخ الاحتياطي - استمرار")

        # ==================== 5. تطبيق التغييرات ====================
        success = apply_weight_changes(weight_changes)
        if not success:
            logger.error("❌ فشل تطبيق التغييرات")
            return False

        # ==================== 6. تسجيل التعديل ====================
        record_tuning(analysis, weight_changes)

        # ==================== 7. إرسال إشعار ====================
        try:
            report = format_tuning_report(analysis, weight_changes, old_weights)
            send_telegram_message(report)
        except Exception as e:
            logger.error(f"فشل إرسال الإشعار: {e}")

        logger.info("✅ تم التعديل بنجاح")

        # ==================== 8. إعادة التشغيل ====================
        if AUTO_RESTART_AFTER_TUNE:
            logger.info("🔄 إعادة تشغيل البوت بعد 5 ثواني...")
            import time
            time.sleep(5)
            restart_bot()

        return True

    except Exception as e:
        logger.error(f"❌ فشل التعديل: {e}")
        import traceback
        traceback.print_exc()
        return False


# ==================== API للاستخدام الخارجي ====================

def get_tuning_stats():
    """إحصائيات التعديلات"""
    try:
        history = load_tuning_history()
        if not history:
            return {
                'total_tunings': 0,
                'last_tuning': None,
                'recent_changes': []
            }

        return {
            'total_tunings': len(history),
            'last_tuning': history[-1].get('timestamp'),
            'recent_changes': [
                {
                    'time': h.get('timestamp'),
                    'changes': h.get('weight_changes', {})
                }
                for h in history[-5:]
            ]
        }
    except:
        return {'total_tunings': 0, 'last_tuning': None, 'recent_changes': []}


def rollback_to_backup(backup_filename):
    """استرجاع نسخة احتياطية"""
    try:
        backup_path = os.path.join(BACKUP_DIR, backup_filename)
        if not os.path.exists(backup_path):
            logger.error(f"❌ النسخة غير موجودة: {backup_filename}")
            return False

        shutil.copy2(backup_path, CONFIG_FILE)
        logger.info(f"✅ تم الاسترجاع من: {backup_filename}")
        return True

    except Exception as e:
        logger.error(f"خطأ في الاسترجاع: {e}")
        return False


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print("🧪 اختبار auto_tuner...")
    result = run_tuning()
    if result:
        print("✅ تم التعديل")
    else:
        print("ℹ️ لا توجد تعديلات")