# ==================================================
# 📁 ملف: smart_scheduler.py - الإصدار v5.7
# 🔧 التعديلات v5.7:
#    - 🔥 جلسة التعلم تحدّث قواعد التعلم التكيفي (adaptive_rules) التي تؤثر فعلياً على القرار
#    - 🔥 لا تعديل لملف config.py ولا إعادة تحميل الوحدات (كان يمسح التبريد ويضيع عند إعادة النشر)
#    - 🔥 تصحيح الصفقات القديمة من سجل Binance ضمن الجلسة
#    - 🔥 لا يتوقف أبداً: كل مهمة في خيط منفصل ومحمية بـ try/except
# 📅 التاريخ: 2026-09-29
# ==================================================

import threading
import time
import logging
from datetime import datetime

logger = logging.getLogger("smart_scheduler")

_last_learning_run = 0
_last_report_run = 0
_last_weekly_report = 0
_last_shadow_run = 0
_scheduler_running = False
_learning_lock = threading.Lock()


# ==================== الحماية الذاتية ====================

def check_auto_protection():
    """الحماية الفعلية (إيقاف متصاعد + حد يومي) تتم في core_functions.
    هنا فقط تسجيل حالة للمتابعة."""
    try:
        from config import AUTO_PROTECTION_ENABLED
        if not AUTO_PROTECTION_ENABLED:
            return
        import core_functions as core
        paused, remaining = core.is_trading_paused()
        if paused:
            logger.info(f"🛑 [PROTECTION] التداول موقوف ({remaining} د) - {core.get_pause_reason()}")
    except Exception as e:
        logger.debug(f"خطأ في الحماية الذاتية: {e}")


# ==================== جلسة التعلم ====================

def run_learning_session():
    """
    جلسة تعلم:
      1) تصحيح أي صفقات قديمة ما زالت غير موثقة من سجل Binance
      2) تحديث قواعد التعلم التكيفي من الصفقات الموثقة
      3) إرسال ملخص على Telegram
    يرجع True إذا اكتملت (حتى لو لم تتغير القواعد)، False عند غياب بيانات موثقة.
    """
    if not _learning_lock.acquire(blocking=False):
        logger.info("⏳ [SCHEDULER] جلسة تعلم جارية بالفعل")
        return True

    try:
        logger.info("=" * 60)
        logger.info("🧠 [SCHEDULER] بدء جلسة التعلم التكيفي...")
        logger.info("=" * 60)

        try:
            import trade_memory
            fixed = trade_memory.reconcile_legacy_trades()
            if fixed:
                logger.info(f"✅ [SCHEDULER] تم تصحيح {fixed} صفقة من سجل Binance")
        except Exception as e:
            logger.warning(f"⚠️ [SCHEDULER] تصحيح الصفقات: {e}")

        import adaptive_rules
        rules = adaptive_rules.update_rules()

        if not rules or rules.get('trades_used', 0) == 0:
            logger.info("⏳ [SCHEDULER] لا توجد صفقات موثقة بعد")
            return False

        try:
            import daily_reporter
            text = adaptive_rules.get_status_text()
            try:
                import shadow_tracker
                text += "\n\n" + shadow_tracker.summary_text()
            except Exception:
                pass
            daily_reporter.send_telegram_message(text)
        except Exception as e:
            logger.debug(f"تعذر إرسال ملخص التعلم: {e}")

        logger.info("✅ [SCHEDULER] اكتملت جلسة التعلم")
        return True

    except Exception as e:
        logger.error(f"❌ [SCHEDULER] فشل جلسة التعلم: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        _learning_lock.release()


# ==================== التقارير ====================

def run_daily_report():
    try:
        logger.info("📊 [SCHEDULER] بدء التقرير اليومي...")
        import daily_reporter
        daily_reporter.send_daily_report()
        return True
    except Exception as e:
        logger.error(f"❌ [SCHEDULER] فشل التقرير اليومي: {e}")
        return False


def run_weekly_report():
    try:
        logger.info("📊 [SCHEDULER] بدء التقرير الأسبوعي...")
        import daily_reporter
        daily_reporter.send_weekly_report()
        return True
    except Exception as e:
        logger.error(f"❌ [SCHEDULER] فشل التقرير الأسبوعي: {e}")
        return False


# ==================== الحلقة الرئيسية ====================

def scheduler_loop():
    global _last_learning_run, _last_report_run, _last_weekly_report, _last_shadow_run, _scheduler_running

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

            if ENABLE_AUTO_LEARNING:
                if now - _last_learning_run >= AUTO_LEARN_INTERVAL_HOURS * 3600:
                    _last_learning_run = now
                    logger.info("🧠 [SCHEDULER] موعد التعلم التلقائي")
                    threading.Thread(target=run_learning_session, daemon=True).start()

            # 👻 v5.9: متابعة صفقات الظل كل 10 دقائق
            if now - _last_shadow_run >= 600:
                _last_shadow_run = now
                try:
                    import shadow_tracker
                    threading.Thread(target=shadow_tracker.resolve_open, daemon=True).start()
                except Exception as e:
                    logger.debug(f"shadow: {e}")

            if ENABLE_DAILY_REPORT:
                if now_dt.hour == DAILY_REPORT_HOUR and (now - _last_report_run) >= 3600:
                    _last_report_run = now
                    logger.info("📊 [SCHEDULER] موعد التقرير اليومي")
                    threading.Thread(target=run_daily_report, daemon=True).start()

            if ENABLE_WEEKLY_REPORT:
                if now_dt.weekday() == 6 and now_dt.hour == DAILY_REPORT_HOUR:
                    if (now - _last_weekly_report) >= 86400:
                        _last_weekly_report = now
                        logger.info("📊 [SCHEDULER] موعد التقرير الأسبوعي")
                        threading.Thread(target=run_weekly_report, daemon=True).start()

            if AUTO_PROTECTION_ENABLED:
                check_auto_protection()

        except Exception as e:
            logger.error(f"❌ [SCHEDULER] خطأ في الحلقة: {e}")

        time.sleep(60)

    logger.info("🛑 [SCHEDULER] توقف خيط الجدولة")


# ==================== API خارجي ====================

def start_scheduler():
    global _scheduler_running
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
    """تشغيل التعلم فوراً (من زر Telegram)"""
    global _last_learning_run
    _last_learning_run = time.time()
    logger.info("🔥 [SCHEDULER] تشغيل التعلم فوراً")
    return run_learning_session()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print("🧪 اختبار smart_scheduler...")
    force_learning_now()
