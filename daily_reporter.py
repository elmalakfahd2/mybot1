# ==================================================
# 📁 ملف: daily_reporter.py - الإصدار v5.0
# 🔧 الوصف:
#    - تقارير يومية تلقائية
#    - تقارير أسبوعية
#    - تقارير أداء شاملة
#    - إرسال تلقائي على Telegram
# 📅 التاريخ: 2026-09-22
# ==================================================

import logging
import asyncio
from datetime import datetime, timedelta

logger = logging.getLogger("daily_reporter")


# ==================== إرسال رسالة Telegram ====================

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
                parse_mode="HTML",
                disable_web_page_preview=True
            )

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(send_async())
        finally:
            loop.close()

        logger.info("✅ تم إرسال التقرير")
        return True

    except Exception as e:
        logger.error(f"❌ فشل الإرسال: {e}")
        return False


# ==================== التقرير اليومي ====================

def build_daily_report():
    """بناء التقرير اليومي"""
    try:
        import core_functions as core
        import trade_memory as memory
        import performance_tracker as tracker
        import auto_tuner

        # ==================== البيانات الأساسية ====================
        daily_pnl = core.get_accurate_daily_pnl()
        weekly_pnl = core.get_accurate_weekly_pnl()
        monthly_pnl = core.get_accurate_monthly_pnl()

        # ==================== الرصيد ====================
        balance_info = {}
        try:
            client_obj = core.get_client()
            if client_obj:
                account = client_obj.futures_account()
                for asset in account.get('assets', []):
                    if asset.get('asset') == 'USDT':
                        balance_info = {
                            'available': float(asset.get('availableBalance', 0)),
                            'wallet': float(asset.get('walletBalance', 0)),
                            'unrealized': float(asset.get('unrealizedProfit', 0)),
                        }
                        break
        except:
            pass

        # ==================== الصفقات ====================
        all_positions = core.get_open_positions()

        # صفقات البوت
        import main_enhanced
        bot_positions = main_enhanced.get_bot_owned_positions()
        manual_positions = main_enhanced.get_manual_positions()

        # ==================== الأداء ====================
        perf = tracker.get_full_performance(days=7)

        # ==================== رسالة ====================
        msg = f"📊 <b>التقرير اليومي</b>\n"
        msg += f"📅 {datetime.now().strftime('%Y-%m-%d')}\n\n"

        # الرصيد
        msg += f"💰 <b>الرصيد:</b>\n"
        msg += f"   • المتاح: {balance_info.get('available', 0):.2f} USDT\n"
        msg += f"   • الإجمالي: {balance_info.get('wallet', 0):.2f} USDT\n"
        msg += f"   • غير محقق: {balance_info.get('unrealized', 0):+.2f} USDT\n\n"

        # الأرباح
        msg += f"📈 <b>الأرباح:</b>\n"
        msg += f"   • اليوم: {daily_pnl.get('daily_pnl', 0):+.2f} USDT\n"
        msg += f"   • الأسبوع: {weekly_pnl.get('weekly_pnl', 0):+.2f} USDT\n"
        msg += f"   • الشهر: {monthly_pnl.get('monthly_pnl', 0):+.2f} USDT\n\n"

        # الصفقات
        msg += f"🎯 <b>الصفقات:</b>\n"
        msg += f"   • البوت: {len(bot_positions)}/{__import__('config').MAX_OPEN_POSITIONS}\n"
        msg += f"   • اليدوية: {len(manual_positions)}\n"
        msg += f"   • الإجمالي: {len(all_positions)}\n\n"

        # أداء الأسبوع
        if perf:
            eval_result = tracker.evaluate_performance(perf)
            msg += f"📊 <b>أداء (7 أيام):</b>\n"
            msg += f"   • صفقات: {perf['total_trades']}\n"
            msg += f"   • نسبة النجاح: {perf['win_rate']}%\n"
            msg += f"   • Profit Factor: {perf['profit_factor']}\n"
            msg += f"   • R:R: {perf['rr_ratio']}\n"
            msg += f"   • Sharpe: {perf['sharpe_ratio']}\n"
            msg += f"   • Max DD: {perf['max_drawdown']}\n"
            msg += f"   • التقييم: {eval_result['rating']}\n\n"

            # أفضل/أسوأ
            if perf.get('best_symbol'):
                best = perf['best_symbol']
                msg += f"✅ <b>أفضل عملة:</b> {best[0]} ({best[1]['pnl']:+.2f})\n"

            if perf.get('worst_symbol'):
                worst = perf['worst_symbol']
                msg += f"❌ <b>أسوأ عملة:</b> {worst[0]} ({worst[1]['pnl']:+.2f})\n"

            msg += "\n"

        # آخر التعديلات
        try:
            tuning_stats = auto_tuner.get_tuning_stats()
            if tuning_stats.get('total_tunings', 0) > 0:
                msg += f"🧠 <b>التعلم التلقائي:</b>\n"
                msg += f"   • جلسات: {tuning_stats['total_tunings']}\n"
                msg += f"   • آخر جلسة: {tuning_stats.get('last_tuning', 'N/A')[:19]}\n\n"
        except:
            pass

        # الحماية
        try:
            is_paused, remaining = core.is_trading_paused()
            if is_paused:
                msg += f"⏸️ <b>البوت متوقف مؤقتاً</b> ({remaining} دقيقة)\n\n"
        except:
            pass

        msg += f"⏰ {datetime.now().strftime('%H:%M:%S')}"

        return msg

    except Exception as e:
        logger.error(f"❌ خطأ في بناء التقرير: {e}")
        import traceback
        traceback.print_exc()
        return None


def send_daily_report():
    """إرسال التقرير اليومي"""
    try:
        logger.info("📊 بناء التقرير اليومي...")

        msg = build_daily_report()
        if not msg:
            return False

        return send_telegram_message(msg)

    except Exception as e:
        logger.error(f"❌ خطأ: {e}")
        return False


# ==================== التقرير الأسبوعي ====================

def build_weekly_report():
    """بناء التقرير الأسبوعي"""
    try:
        import core_functions as core
        import performance_tracker as tracker

        # ==================== الأداء ====================
        perf = tracker.get_full_performance(days=7)

        if not perf:
            return "📊 لا توجد بيانات كافية للتقرير الأسبوعي"

        eval_result = tracker.evaluate_performance(perf)

        # ==================== الأرباح ====================
        weekly_pnl = core.get_accurate_weekly_pnl()
        monthly_pnl = core.get_accurate_monthly_pnl()

        msg = f"📊 <b>التقرير الأسبوعي</b>\n"
        msg += f"📅 {datetime.now().strftime('%Y-%m-%d')}\n\n"

        msg += f"💰 <b>الأرباح:</b>\n"
        msg += f"   • الأسبوع: {weekly_pnl.get('weekly_pnl', 0):+.2f} USDT\n"
        msg += f"   • الشهر: {monthly_pnl.get('monthly_pnl', 0):+.2f} USDT\n\n"

        msg += f"📊 <b>الأداء:</b>\n"
        msg += f"   • الصفقات: {perf['total_trades']}\n"
        msg += f"   • الرابحة: {perf['wins']}\n"
        msg += f"   • الخاسرة: {perf['losses']}\n"
        msg += f"   • نسبة النجاح: {perf['win_rate']}%\n"
        msg += f"   • Profit Factor: {perf['profit_factor']}\n"
        msg += f"   • R:R: {perf['rr_ratio']}\n"
        msg += f"   • Sharpe: {perf['sharpe_ratio']}\n"
        msg += f"   • Max Drawdown: {perf['max_drawdown']}\n\n"

        msg += f"🎯 <b>التقييم العام: {eval_result['rating']}</b>\n"
        msg += f"   النقاط: {eval_result['score']}/100\n\n"

        # تفاصيل التقييم
        details = eval_result.get('details', {})
        if details:
            msg += f"📋 <b>التفاصيل:</b>\n"
            for key, value in details.items():
                msg += f"   • {key}: {value}\n"
            msg += "\n"

        # أفضل/أسوأ
        if perf.get('best_symbol'):
            best = perf['best_symbol']
            msg += f"✅ <b>أفضل عملة:</b> {best[0]}\n"
            msg += f"   ({best[1]['wins']}/{best[1]['total']} = {best[1]['win_rate']}%)\n"

        if perf.get('worst_symbol'):
            worst = perf['worst_symbol']
            msg += f"❌ <b>أسوأ عملة:</b> {worst[0]}\n"
            msg += f"   ({worst[1]['wins']}/{worst[1]['total']} = {worst[1]['win_rate']}%)\n"

        msg += "\n"

        # أفضل/أسوأ ساعة
        if perf.get('best_hour'):
            bh = perf['best_hour']
            msg += f"✅ <b>أفضل ساعة:</b> {bh[0]}:00 ({bh[1]['win_rate']}%)\n"

        if perf.get('worst_hour'):
            wh = perf['worst_hour']
            msg += f"❌ <b>أسوأ ساعة:</b> {wh[0]}:00 ({wh[1]['win_rate']}%)\n"

        msg += f"\n⏰ {datetime.now().strftime('%H:%M:%S')}"

        return msg

    except Exception as e:
        logger.error(f"❌ خطأ في التقرير الأسبوعي: {e}")
        return None


def send_weekly_report():
    """إرسال التقرير الأسبوعي"""
    try:
        logger.info("📊 بناء التقرير الأسبوعي...")

        msg = build_weekly_report()
        if not msg:
            return False

        return send_telegram_message(msg)

    except Exception as e:
        logger.error(f"❌ خطأ: {e}")
        return False


# ==================== تقرير عند الطلب ====================

def send_custom_report():
    """إرسال تقرير مخصص (يُستدعى من Telegram)"""
    try:
        msg = build_daily_report()
        if not msg:
            return False
        return send_telegram_message(msg)
    except:
        return False


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print("🧪 اختبار daily_reporter...")

    print("\n📊 بناء التقرير اليومي:")
    daily = build_daily_report()
    if daily:
        print(daily[:500])
    else:
        print("❌ فشل")

    print("\n📊 بناء التقرير الأسبوعي:")
    weekly = build_weekly_report()
    if weekly:
        print(weekly[:500])
    else:
        print("❌ فشل")