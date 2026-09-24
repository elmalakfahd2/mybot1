# ==================================================
# 📁 ملف: smart_scheduler.py - الإصدار v5.2.2
# 🔧 التعديلات v5.2.2:
#    - 🔥 إزالة os._exit (لا إعادة تشغيل)
#    - 🔥 تحديث الأوزان في الذاكرة
#    - 🔥 إصلاح توقف البوت بعد التعلم
# 🔧 التعديلات v5.0:
#    - جدولة المهام التلقائية
# 📅 التاريخ: 2026-09-24
# ==================================================

import threading
import time
import logging
from datetime import datetime, timedelta

logger = logging.getLogger("smart_scheduler")

_last_learning_run = 0
_last_report_run = 0
_last_weekly_report = 0
_scheduler_running = False


# ==================== فحص الحماية الذاتية ====================

def check_auto_protection():
    try:
        from config import (
            AUTO_PROTECTION_ENABLED,
            AUTO_PAUSE_ON_LOSS_STREAK,
            MAX_CONSECUTIVE_LOSSES,
        )

        if not AUTO_PROTECTION_ENABLED:
            return

        import core_functions as core

        consecutive_losses = core.get_consecutive_losses()

        if consecutive_losses >= AUTO_PAUSE_ON_LOSS_STREAK:
            logger.warning(f"🛑 {consecutive_losses} خسائر متتالية — الحماية الذاتية نشطة")

        elif consecutive_losses >= MAX_CONSECUTIVE_LOSSES:
            logger.warning(f"🛑 {consecutive_losses} خسائر — البوت سيُوقف مؤقتاً")

    except Exception as e:
        logger.error(f"خطأ في الحماية الذاتية: {e}")


# ==================== تشغيل التعلم التلقائي ====================

def run_learning_session():
    """تشغيل جلسة تعلم كاملة"""
    try:
        logger.info("=" * 60)
        logger.info("🧠 [SCHEDULER] بدء جلسة التعلم التلقائي...")
        logger.info("=" * 60)

        # 1. التحليل
        import auto_learner
        analysis = auto_learner.run_analysis()

        if not analysis:
            logger.info("⏳ [SCHEDULER] لا توجد بيانات كافية")
            return False

        # 2. التعديل
        from config import AUTO_TUNE_WEIGHTS

        if AUTO_TUNE_WEIGHTS:
            import auto_tuner

            try:
                from config import (
                    ENABLE_AUTO_LEARNING,
                    AUTO_LEARN_MIN_TRADES,
                    AUTO_LEARN_BACKUP_ENABLED,
                    SCORE_WEIGHTS,
                )

                weight_changes = analysis.get('recommendations', {}).get('weight_changes', {})

                if weight_changes:
                    # نسخة احتياطية
                    if AUTO_LEARN_BACKUP_ENABLED:
                        auto_tuner.create_backup()

                    # تطبيق التغييرات
                    auto_tuner.apply_weight_changes(weight_changes)

                    # تسجيل
                    auto_tuner.record_tuning(analysis, weight_changes)

                    # إشعار
                    old_weights = {k: v for k, v in SCORE_WEIGHTS.items() if k != 'max_score'}
                    report = auto_tuner.format_tuning_report(analysis, weight_changes, old_weights)
                    auto_tuner.send_telegram_message(report)

                    logger.info("✅ [SCHEDULER] تم تحديث الأوزان")

                    # 🔥 v5.2.2: تحديث في الذاكرة (بدون إعادة تشغيل)
                    logger.info("🔄 [SCHEDULER] تحديث الأوزان في الذاكرة...")
                    auto_tuner.restart_bot()

                    logger.info("✅ [SCHEDULER] تم التحديث - البوت مستمر في العمل")
                    return True

            except Exception as e:
                logger.error(f"خطأ في التعديل: {e}")
                import traceback
                traceback.print_exc()

        return True

    except Exception as e:
        logger.error(f"❌ [SCHEDULER] فشل جلسة التعلم: {e}")
        import traceback
        traceback.print_exc()
        return False


# ==================== تقرير يومي ====================

def run_daily_report():
    try:
        logger.info("📊 [SCHEDULER] بدء التقرير اليومي...")

        import daily_reporter
        daily_reporter.send_daily_report()

        return True

    except Exception as e:
        logger.error(f"❌ [SCHEDULER] فشل التقرير اليومي: {e}")
        return False


# ==================== تقرير أسبوعي ====================

def run_weekly_report():
    try:
        logger.info("📊 [SCHEDULER] بدء التقرير الأسبوعي...")

        import daily_reporter
        daily_reporter.send_weekly_report()

        return True

    except Exception as e:
        logger.error(f"❌ [SCHEDULER] فشل التقرير الأسبوعي: {e}")
        return False


# ==================== الخيط الرئيسي ====================

def scheduler_loop():
    """الحلقة الرئيسية للجدولة"""
    global _last_learning_run, _last_report_run, _last_weekly_report, _scheduler_running

    _scheduler_running = True
    logger.info("⏰ [SCHEDULER] بدء خيط الجدولة التلقائية...")

    while _scheduler_running:
        try:
            from config import (
                ENABLE_AUTO_LEARNING,
                AUTO_LEARN_INTERVAL_HOURS,
                ENABLE_DAILY_REPORT,
                DAILY_REPORT_HOUR,
                ENABLE_WEEKLY_REPORT,
                AUTO_PROTECTION_ENABLED,
            )

            now = time.time()
            now_dt = datetime.now()

            # 1. التعلم التلقائي
            if ENABLE_AUTO_LEARNING:
                interval_seconds = AUTO_LEARN_INTERVAL_HOURS * 3600

                if now - _last_learning_run >= interval_seconds:
                    _last_learning_run = now
                    logger.info("🧠 [SCHEDULER] موعد التعلم التلقائي")
                    threading.Thread(target=run_learning_session, daemon=True).start()

            # 2. التقرير اليومي
            if ENABLE_DAILY_REPORT:
                target_hour = DAILY_REPORT_HOUR
                if now_dt.hour == target_hour and (now - _last_report_run) >= 3600:
                    _last_report_run = now
                    logger.info("📊 [SCHEDULER] موعد التقرير اليومي")
                    threading.Thread(target=run_daily_report, daemon=True).start()

            # 3. التقرير الأسبوعي
            if ENABLE_WEEKLY_REPORT:
                if now_dt.weekday() == 6 and now_dt.hour == DAILY_REPORT_HOUR:
                    if (now - _last_weekly_report) >= 86400:
                        _last_weekly_report = now
                        logger.info("📊 [SCHEDULER] موعد التقرير الأسبوعي")
                        threading.Thread(target=run_weekly_report, daemon=True).start()

            # 4. الحماية الذاتية
            if AUTO_PROTECTION_ENABLED:
                check_auto_protection()

            time.sleep(60)

        except Exception as e:
            logger.error(f"❌ [SCHEDULER] خطأ في الحلقة: {e}")
            time.sleep(60)

    logger.info("🛑 [SCHEDULER] توقف خيط الجدولة")


# ==================== API خارجي ====================

def start_scheduler():
    """بدء الجدولة (تُستدعى من main)"""
    try:
        thread = threading.Thread(target=scheduler_loop, daemon=True, name="SmartScheduler")
        thread.start()
        logger.info("✅ [SCHEDULER] تم تشغيل الجدولة في الخلفية")
        return True
    except Exception as e:
        logger.error(f"❌ [SCHEDULER] فشل البدء: {e}")
        return False


def stop_scheduler():
    global _scheduler_running
    _scheduler_running = False
    logger.info("🛑 [SCHEDULER] إيقاف الجدولة")


def get_scheduler_status():
    return {
        'running': _scheduler_running,
        'last_learning': datetime.fromtimestamp(_last_learning_run).isoformat() if _last_learning_run > 0 else None,
        'last_report': datetime.fromtimestamp(_last_report_run).isoformat() if _last_report_run > 0 else None,
        'last_weekly': datetime.fromtimestamp(_last_weekly_report).isoformat() if _last_weekly_report > 0 else None,
    }


def force_learning_now():
    """تشغيل التعلم فوراً"""
    global _last_learning_run
    _last_learning_run = 0
    logger.info("🔥 [SCHEDULER] تشغيل التعلم فوراً")
    return run_learning_session()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print("🧪 اختبار smart_scheduler...")
    print("تشغيل التعلم الآن...")
    force_learning_now()