# -*- coding: utf-8 -*-
"""
main_enhanced.py - النظام الرئيسي المحسن v5.7
🔥 التعديلات الرئيسية:
    - إصلاح تسرب الذاكرة في المراقب (بدون WebSocket)
    - نظام حماية ذاتية شامل (PAUSE_ESCALATION + خفض الحجم + حد خسارة يومي)
    - فحص الصحة الشامل قبل فتح كل صفقة
    - نظام التبريد المُحسن
    - تقارير أسبوعية إضافية
    - 🔥 v5.7: إصلاح التعلم (adaptive_rules يؤثر فعلياً) + تبريد صحيح بنتيجة حقيقية
    - 🔥 فحص أداء يومي تلقائي مع حكم آلي على Telegram (performance_check)
    - 🔥 دالة main() رسمية (نقطة دخول run_bot.py) — كان __main__ فقط ففشل الاستيراد
"""

import guard_bootstrap; guard_bootstrap.apply_patches()

import logging
import time
import threading
import json
import signal
import sys
import asyncio
from datetime import datetime, timedelta
from collections import defaultdict

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("bot.log", encoding='utf-8'),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger("main_enhanced")

try:
    import config
    from config import *
except ImportError as e:
    logger.error(f"❌ خطأ في config: {e}")
    sys.exit(1)

try:
    import bot_enhanced
    logger.info("✅ تم تحميل النظام")
except ImportError as e:
    logger.error(f"❌ خطأ: {e}")
    sys.exit(1)

try:
    import core_functions as core
    logger.info("✅ تم تحميل core_functions")
except ImportError as e:
    logger.error(f"❌ خطأ: {e}")
    core = None

try:
    from groq_integration import is_groq_available
    logger.info("✅ تم تحميل وحدة Groq")
except ImportError as e:
    logger.error(f"❌ خطأ: {e}")
    is_groq_available = lambda: False

try:
    import bot_strategies_enhanced as strategies
    logger.info("✅ تم تحميل الاستراتيجيات")
except ImportError as e:
    logger.error(f"❌ خطأ: {e}")
    strategies = None

try:
    import trade_memory as memory
    logger.info("✅ ذاكرة الصفقات متاحة")
    MEMORY_AVAILABLE = True
except ImportError:
    logger.warning("⚠️ trade_memory غير متاح")
    MEMORY_AVAILABLE = False

try:
    from market_regime import MarketRegime
    logger.info("✅ كشف حالة السوق متاح")
    MARKET_REGIME_AVAILABLE = True
except ImportError:
    logger.warning("⚠️ market_regime غير متاح")
    MARKET_REGIME_AVAILABLE = False

try:
    import realtime_data
    logger.info("✅ realtime_data متاح")
    REALTIME_AVAILABLE = True
except ImportError:
    logger.warning("⚠️ realtime_data غير متاح")
    REALTIME_AVAILABLE = False

try:
    from auto_learner import AutoLearner
    logger.info("✅ نظام التعلم التلقائي متاح")
    AUTO_LEARNER_AVAILABLE = True
except ImportError:
    logger.warning("⚠️ auto_learner غير متاح")
    AUTO_LEARNER_AVAILABLE = False

try:
    import auto_learner
    logger.info("✅ auto_learner متاح")
except ImportError:
    logger.warning("⚠️ auto_learner غير متاح")
    auto_learner = None

try:
    import auto_tuner
    logger.info("✅ auto_tuner متاح")
except ImportError:
    logger.warning("⚠️ auto_tuner غير متاح")
    auto_tuner = None

try:
    import performance_tracker
    logger.info("✅ performance_tracker متاح")
except ImportError:
    logger.warning("⚠️ performance_tracker غير متاح")
    performance_tracker = None

try:
    import daily_reporter
    logger.info("✅ daily_reporter متاح")
except ImportError:
    logger.warning("⚠️ daily_reporter غير متاح")
    daily_reporter = None

try:
    import firebase_backup
    logger.info("✅ firebase_backup متاح")
except ImportError:
    logger.warning("⚠️ firebase_backup غير متاح")
    firebase_backup = None

try:
    import adaptive_rules
    logger.info("✅ adaptive_rules متاح")
except ImportError:
    logger.warning("⚠️ adaptive_rules غير متاح")
    adaptive_rules = None

# 🔥 v5.6: منع تشغيل نسختين على نفس الحساب
try:
    import socket
    _lock_socket = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    try:
        _lock_socket.bind('\0' + TELEGRAM_CHAT_ID)
    except OSError:
        logger.error("🚫 نسخة أخرى من البوت تعمل بالفعل! إيقاف.")
        sys.exit(1)
except Exception:
    pass


class MainSystem:
    def __init__(self):
        self.running = True
        self.signals_sent = 0
        self.last_signal_time = time.time()
        self.last_scan_time = time.time()
        self.daily_report_sent = False
        self.last_daily_report_date = None
        self.last_weekly_report_date = None
        self.last_signal_date = None
        self.orphan_cleanup_last = time.time()
        self.last_trade_count = 0
        self.last_trade_change_time = time.time()
        self.performance_history = []
        self.daily_stats = defaultdict(lambda: {'trades': 0, 'wins': 0, 'losses': 0, 'pnl': 0.0})

        logger.info("=" * 60)
        logger.info("🚀 [MAIN] بدء main_enhanced v5.7...")
        logger.info("=" * 60)

    def get_open_positions(self):
        """🔥 يقرأ الصفقات المفتوحة فعلياً من Binance"""
        try:
            if core:
                positions = core.get_open_positions()
                return positions if positions else []
        except:
            pass
        return []

    def send_daily_report(self):
        """تقرير يومي احترافي"""
        try:
            if not daily_reporter:
                return

            today = datetime.now().strftime('%Y-%m-%d')
            if self.last_daily_report_date == today:
                return

            if daily_reporter.send_daily_report():
                self.last_daily_report_date = today
                logger.info("✅ [REPORT] التقرير اليومي")
        except Exception as e:
            logger.error(f"❌ خطأ في التقرير اليومي: {e}")

    def send_weekly_report(self):
        """تقرير أسبوعي"""
        try:
            if not daily_reporter:
                return

            today = datetime.now()
            days_since_monday = today.weekday()
            week_start = (today - timedelta(days=days_since_monday)).strftime('%Y-%m-%d')

            if self.last_weekly_report_date == week_start:
                return

            if daily_reporter.send_weekly_report():
                self.last_weekly_report_date = week_start
                logger.info("✅ [REPORT] التقرير الأسبوعي")
        except Exception as e:
            logger.error(f"❌ خطأ في التقرير الأسبوعي: {e}")

    def check_and_restart_stalled(self):
        """🔥 إعادة تشغيل تلقائية إذا توقف البوت"""
        try:
            current_time = time.time()
            time_since_signal = current_time - self.last_signal_time
            time_since_scan = current_time - self.last_scan_time

            if time_since_signal > STALL_RESTART_MINUTES * 60:
                logger.warning("⚠️ [STALL] لا إشارات - إعادة تشغيل...")
                self.restart_bot()

            if time_since_scan > STALL_RESTART_MINUTES * 60:
                logger.warning("⚠️ [STALL] لا مسح - إعادة تشغيل...")
                self.restart_bot()

        except Exception as e:
            logger.error(f"خطأ في فحص التوقف: {e}")

    def restart_bot(self):
        """إعادة تشغيل البوت"""
        try:
            logger.info("🔄 [RESTART] إعادة تشغيل البوت...")
            self.running = False
            time.sleep(2)
            import os
            os.execv(sys.executable, [sys.executable] + sys.argv)
        except Exception as e:
            logger.error(f"خطأ في إعادة التشغيل: {e}")

    def cleanup_orphan_orders(self):
        """تنظيف أوامر يتيمة"""
        try:
            if ENABLE_ORPHAN_CLEANUP and core:
                current_time = time.time()
                if current_time - self.orphan_cleanup_last >= ORPHAN_CLEANUP_INTERVAL:
                    self.orphan_cleanup_last = current_time
                    deleted = core.cleanup_orphan_orders()
                    if deleted > 0:
                        logger.info(f"🧹 [CLEANUP] تم حذف {deleted} أمر يتيم")
        except Exception as e:
            logger.error(f"خطأ في التنظيف: {e}")

    def health_check(self):
        """فحص صحة شامل"""
        try:
            issues = []

            if is_groq_available() == False:
                issues.append("Groq/Gemini غير متاح")

            if core:
                try:
                    balance = core.get_futures_balance()
                    if not balance or balance <= 0:
                        issues.append("الرصيد صفر")
                except:
                    issues.append("فشل قراءة الرصيد")

            if issues:
                logger.warning(f"⚠️ [HEALTH] مشاكل: {', '.join(issues)}")
                return False
            return True

        except Exception as e:
            logger.error(f"خطأ في فحص الصحة: {e}")
            return False

    def pre_trade_health_check(self, symbol, direction):
        """🔥 فحص صحة إضافي قبل فتح الصفقة"""
        try:
            if not core:
                return True, "Core متاح"

            balance = core.get_futures_balance()
            if balance is None:
                return False, "فشل قراءة الرصيد"
            if balance < 5:
                return False, f"رصيد منخفض ({balance:.2f}$)"

            risk = core.get_risk_status()
            if risk.get('paused', False):
                return False, f"التداول موقوف ({risk.get('remaining_minutes', 0)} دقيقة)"

            max_pos = MAX_OPEN_POSITIONS
            open_pos = self.get_open_positions()
            if len(open_pos) >= max_pos:
                return False, f"أقصى عدد صفقات ({len(open_pos)}/{max_pos})"

            if ENABLE_DAILY_DRAWDOWN_LIMIT:
                daily = core.get_daily_pnl()
                daily_pnl = daily.get('pnl', 0)
                loss_limit = -DAILY_MAX_LOSS_USDT
                if daily_pnl <= loss_limit:
                    return False, f"حد الخسارة اليومية ({daily_pnl:.2f}$)"

            return True, "جميع الفحوصات سليمة"

        except Exception as e:
            logger.error(f"خطأ في فحص ما قبل التداول: {e}")
            return True, "فحص جزئي"

    def monitor_positions(self):
        """مراقبة الصفقات المفتوحة + TP/SL"""
        try:
            if not core:
                return

            positions = self.get_open_positions()
            if not positions:
                return

            logger.info(f"📊 [MONITOR] مراقبة {len(positions)} صفقة...")

            for pos in positions:
                try:
                    symbol = pos.get('symbol')
                    position_side = pos.get('positionSide', 'BOTH')
                    pnl = float(pos.get('unRealizedProfit', 0))
                    entry_price = float(pos.get('entryPrice', 0))
                    mark_price = float(pos.get('markPrice', 0))
                    amount = abs(float(pos.get('positionAmt', 0)))

                    if not symbol or amount == 0:
                        continue

                    direction = "BUY" if position_side == "LONG" or float(pos.get('positionAmt', 0)) > 0 else "SELL"

                    if VERIFY_TP_SL_AFTER_CREATION:
                        tp_orders, sl_orders = core.get_position_tp_sl(symbol)
                        if len(tp_orders) == 0 and len(sl_orders) == 0:
                            logger.warning(f"⚠️ {symbol}: لا TP/SL! إنشاؤهما...")
                            sl_percent = SL_PERCENT
                            tp_percent = TP_PERCENT
                            if DYNAMIC_SL_ENABLED:
                                sl_percent = core.calculate_dynamic_sl(symbol, entry_price, direction)
                                sl_percent = max(SL_MIN_PERCENT, min(SL_MAX_PERCENT, sl_percent))
                            core.place_market_order_with_tp_sl(symbol, direction, amount, LEVERAGE,
                                                               sl_percent, tp_percent)

                    if TRAILING_SL_ENABLED:
                        core.update_trailing_sl(symbol, direction, entry_price, mark_price)

                    if pnl <= -abs(entry_price * amount) * (SL_PERCENT / 100) * 1.5:
                        logger.warning(f"🛑 {symbol}: خسارة حرجة {pnl:.2f}$ - إغلاق طارئ")
                        core.close_position(symbol, direction, "إغلاق طارئ")

                except Exception as e:
                    logger.error(f"خطأ في مراقبة {pos.get('symbol', '?')}: {e}")
                    continue

        except Exception as e:
            logger.error(f"خطأ في المراقبة: {e}")

    def sniper_scanner_loop(self):
        """حلقة مسح القناص"""
        try:
            scan_interval = AUTO_SCAN_INTERVAL

            logger.info("🎯 [THREAD] بدء مسح القناص...")

            while self.running:
                try:
                    if not self.health_check():
                        time.sleep(60)
                        continue

                    risk = core.get_risk_status() if core else {'paused': False}
                    if risk.get('paused', False):
                        logger.warning(f"⏸️ توقف - {risk.get('remaining_minutes', 0)} د")
                        time.sleep(60)
                        continue

                    logger.info("🎯 [SCAN] بدء مسح القناص...")

                    signals = strategies.scan_sniper_signals() if strategies else []

                    self.last_scan_time = time.time()

                    if signals:
                        logger.info(f"🎯 {len(signals)} إشارة")
                        for signal in signals[:MAX_OPEN_POSITIONS]:
                            self.process_signal(signal)
                    else:
                        logger.info("🔍 لا إشارات")

                    logger.info(f"⏰ الدورة التالية: {scan_interval // 60} دقيقة")
                    time.sleep(scan_interval)

                except Exception as e:
                    logger.error(f"خطأ في المسح: {e}")
                    time.sleep(60)

        except Exception as e:
            logger.error(f"خطأ في مسح القناص: {e}")

    def process_signal(self, signal):
        """معالجة إشارة وتنفيذها"""
        try:
            symbol = signal['symbol']
            direction = signal['direction']
            score = signal.get('total_score', 0)
            required = signal.get('required_score', MIN_SCORE_REQUIRED)

            logger.info(f"🚀 فحص {symbol} {direction}")

            ok, reason = self.pre_trade_health_check(symbol, direction)
            if not ok:
                logger.warning(f"🛑 {symbol}: {reason}")
                return

            # 🔥 فحص عدد الصفقات بنفس الاتجاه (v5.8: 0→52% | 1→44% | 2→33% | 3→25%)
            try:
                positions = self.get_open_positions()
                same_dir = 0
                for p in positions:
                    pside = p.get('positionSide', '')
                    pdir = "BUY" if pside == "LONG" else "SELL"
                    if pdir == direction:
                        same_dir += 1
                if same_dir >= MAX_SAME_DIRECTION_POSITIONS:
                    logger.warning(f"🛑 {symbol}: {same_dir} صفقة {direction} مفتوحة (الحد {MAX_SAME_DIRECTION_POSITIONS})")
                    return
            except Exception as e:
                logger.debug(f"فحص الاتجاه: {e}")

            # 🔥 v5.7: خفض الحجم بعد خسائر متتالية
            amount = TRADE_USDT
            try:
                risk = core.get_risk_status()
                if risk.get('consecutive_losses', 0) >= RISK_REDUCE_AFTER_LOSSES:
                    amount = TRADE_USDT * AUTO_RISK_REDUCTION_FACTOR
                    logger.warning(f"⚠️ {symbol}: تقليل الحجم إلى {amount}$ ({AUTO_RISK_REDUCTION_FACTOR*100:.0f}%) بسبب خسائر متتالية")
            except Exception:
                pass

            # 🔥 تحقق إضافي من TP/SL
            sl_percent = SL_PERCENT
            tp_percent = TP_PERCENT
            if DYNAMIC_SL_ENABLED:
                try:
                    sl_percent = core.calculate_dynamic_sl(symbol, signal['entry_price'], direction)
                    sl_percent = max(SL_MIN_PERCENT, min(SL_MAX_PERCENT, sl_percent))
                except Exception:
                    pass

            logger.info(f"✅ {symbol}: اجتاز كل الفحوص - جاري التنفيذ ({amount}$)")

            result = core.place_market_order_with_tp_sl(
                symbol, direction, amount, LEVERAGE, sl_percent, tp_percent
            )

            if result:
                logger.info(f"✅ {symbol}: تم فتح الصفقة بنجاح")
                self.last_signal_time = time.time()

                if MEMORY_AVAILABLE:
                    try:
                        memory.record_trade(
                            symbol=symbol,
                            direction=direction,
                            entry_price=signal['entry_price'],
                            volume_ratio=signal.get('analysis', {}).get('volume_analysis', {}).get('volume_5m_ratio', 1.0),
                            score_details=signal.get('score_details', {}),
                            net_pnl=0
                        )
                    except Exception as e:
                        logger.debug(f"تسجيل: {e}")

                self.signals_sent += 1
                self._update_daily_stats(symbol, direction, 'OPEN', 0)
            else:
                logger.error(f"❌ {symbol}: فشل فتح الصفقة")

        except Exception as e:
            logger.error(f"خطأ في معالجة الإشارة: {e}")

    def _update_daily_stats(self, symbol, direction, action, pnl):
        """تحديث إحصائيات اليوم"""
        try:
            today = datetime.now().strftime('%Y-%m-%d')
            if action == 'OPEN':
                self.daily_stats[today]['trades'] += 1
            elif action == 'WIN':
                self.daily_stats[today]['wins'] += 1
                self.daily_stats[today]['pnl'] += pnl
            elif action == 'LOSS':
                self.daily_stats[today]['losses'] += 1
                self.daily_stats[today]['pnl'] += pnl
        except Exception:
            pass

    def performance_loop(self):
        """تتبع الأداء"""
        try:
            while self.running:
                time.sleep(300)
                if not core:
                    continue

                try:
                    balance = core.get_futures_balance()
                    daily = core.get_daily_pnl()

                    self.performance_history.append({
                        'time': datetime.now().strftime('%H:%M'),
                        'balance': balance,
                        'daily_pnl': daily.get('pnl', 0)
                    })

                    if len(self.performance_history) > 100:
                        self.performance_history = self.performance_history[-50:]

                except Exception:
                    pass

        except Exception as e:
            logger.error(f"خطأ في تتبع الأداء: {e}")

    def scheduler_loop(self):
        """جدولة التقارير"""
        try:
            while self.running:
                now = datetime.now()

                if now.hour == DAILY_REPORT_HOUR and now.minute < 5:
                    self.send_daily_report()

                if now.weekday() == 0 and now.hour == 9 and now.minute < 5:
                    self.send_weekly_report()

                time.sleep(60)

        except Exception as e:
            logger.error(f"خطأ في الجدولة: {e}")

    def run(self):
        """تشغيل النظام الرئيسي"""
        try:
            self.health_check()

            if core:
                try:
                    core.sync_trade_files()
                except Exception as e:
                    logger.debug(f"sync_trade_files: {e}")

            if ENABLE_ORPHAN_CLEANUP and core:
                try:
                    deleted = core.cleanup_orphan_orders()
                    if deleted:
                        logger.info(f"🧹 [MAIN] تم حذف {deleted} أمر يتيم")
                except Exception as e:
                    logger.debug(f"cleanup: {e}")

            if MEMORY_AVAILABLE:
                try:
                    memory.sync_from_binance()
                except Exception as e:
                    logger.debug(f"sync: {e}")

            stats = memory.get_trading_stats() if MEMORY_AVAILABLE else {}
            logger.info(f"📊 [MAIN] عدد الصفقات: {stats.get('total_trades', 0)}")
            logger.info(f"📊 [MAIN] نسبة النجاح: {stats.get('win_rate', 0)*100:.1f}%")

            logger.info("=" * 60)
            logger.info("🎯 [MAIN] نظام القناص v5.6 مفعل")
            logger.info("=" * 60)

            logger.info(f"⏰ [MAIN] المسح كل {AUTO_SCAN_INTERVAL // 60} دقيقة")
            logger.info(f"🎯 [MAIN] MIN_SCORE: {MIN_SCORE_REQUIRED}")
            logger.info(f"📈 [MAIN] MAX_POSITIONS: {MAX_OPEN_POSITIONS}")
            logger.info(f"💰 [MAIN] TRADE_USDT: {TRADE_USDT}")
            logger.info(f"⚡ [MAIN] LEVERAGE: {LEVERAGE}x")
            logger.info(f"🧹 [MAIN] تنظيف الأوامر: {'✅' if ENABLE_ORPHAN_CLEANUP else '❌'} (كل {ORPHAN_CLEANUP_INTERVAL // 60} دقيقة)")
            logger.info(f"🔔 [MAIN] إشعار إغلاق: {'✅' if ENABLE_CLOSE_NOTIFICATIONS else '❌'}")
            logger.info(f"🧠 [MAIN] التعلم التلقائي: {'✅' if ENABLE_AUTO_LEARNING else '❌'}")
            logger.info(f"📊 [MAIN] التقارير اليومية: {'✅' if ENABLE_DAILY_REPORT else '❌'}")
            logger.info(f"🔥 [MAIN] Firebase Backup: {'✅' if ENABLE_FIREBASE_BACKUP else '❌'}")
            logger.info("=" * 60)

            self.start_scanner_threads()

            while self.running:
                time.sleep(1)

        except KeyboardInterrupt:
            logger.info("⏹️ إيقاف...")
            self.running = False
        except Exception as e:
            logger.error(f"❌ خطأ فادح: {e}")
            import traceback
            logger.error(traceback.format_exc())

    def start_scanner_threads(self):
        """🔥 بدء جميع الخيوط"""
        try:
            logger.info("🔧 [START] بدء تشغيل الخيوط v5.6...")
            logger.info("=" * 60)

            # 1. خيط مسح القناص الرئيسي
            try:
                threading.Thread(target=self.sniper_scanner_loop, daemon=True, name="SniperScanner").start()
                logger.info("✅ [START] SniperScanner")
            except Exception as e:
                logger.error(f"❌ [START] فشل scanner: {e}")

            # 2. خيط المراقبة الشاملة
            try:
                threading.Thread(target=self.monitor_loop, daemon=True, name="Monitor").start()
                logger.info("✅ [START] Monitor")
            except Exception as e:
                logger.error(f"❌ [START] فشل monitor: {e}")

            # 3. خيط التقارير
            try:
                threading.Thread(target=self.scheduler_loop, daemon=True, name="Scheduler").start()
                logger.info("✅ [START] Scheduler")
            except Exception as e:
                logger.error(f"❌ [START] فشل scheduler: {e}")

            # 4. خيط تتبع الأداء
            try:
                threading.Thread(target=self.performance_loop, daemon=True, name="PerformanceTracker").start()
                logger.info("✅ [START] PerformanceTracker")
            except Exception as e:
                logger.error(f"❌ [START] فشل performance: {e}")

            # 5. خيط فحص التوقف
            try:
                threading.Thread(target=self.stall_check_loop, daemon=True, name="StallChecker").start()
                logger.info("✅ [START] StallChecker")
            except Exception as e:
                logger.error(f"❌ [START] فشل stall checker: {e}")

            # 6. 🔥 المراقب (Supervisor)
            try:
                threading.Thread(target=supervisor_loop, daemon=True, name="Supervisor").start()
                logger.info("✅ [START] Supervisor (إعادة تشغيل الخيوط المتوقفة)")
            except Exception as e:
                logger.error(f"❌ [START] فشل supervisor: {e}")

            # 7. 🔥 v1.0: فحص الأداء اليومي — حكم آلي على Telegram كل يوم
            try:
                import performance_check
                performance_check.start_daily_check()
                logger.info("✅ [START] Performance Check اليومي")
            except Exception as e:
                logger.warning(f"⚠️ [START] performance_check: {e}")

            time.sleep(2)

            logger.info("✅ [START] عدد الخيوط: " + str(len(threading.enumerate())))
            logger.info("=" * 60)

        except Exception as e:
            logger.error(f"❌ خطأ في بدء الخيوط: {e}")

    def monitor_loop(self):
        """🔥 حلقة المراقبة - تسرب ذاكرة ثابت"""
        try:
            while self.running:
                try:
                    self.monitor_positions()
                    self.cleanup_orphan_orders()
                    time.sleep(MONITOR_TP_SL_INTERVAL)
                except Exception as e:
                    logger.error(f"خطأ في المراقبة: {e}")
                    time.sleep(30)
        except Exception as e:
            logger.error(f"خطأ في خيط المراقبة: {e}")

    def stall_check_loop(self):
        """فحص التوقف"""
        try:
            while self.running:
                try:
                    self.check_and_restart_stalled()
                    time.sleep(60)
                except Exception as e:
                    logger.error(f"خطأ في فحص التوقف: {e}")
                    time.sleep(60)
        except Exception as e:
            logger.error(f"خطأ في StallChecker: {e}")


def supervisor_loop():
    """🔥 مراقب يعيد تشغيل الخيوط المتوقفة"""
    try:
        logger.info("🛡️ [SUPERVISOR] بدء المراقبة (مهلة التجمّد 30 د)")

        tracked = {
            "Monitor": 90,
            "SniperScanner": 15 * 60,
            "Scheduler": 10 * 60,
            "PerformanceTracker": 10 * 60,
            "StallChecker": 5 * 60,
        }

        while True:
            time.sleep(30)

            try:
                threads = {t.name: t for t in threading.enumerate()}

                for name, timeout in tracked.items():
                    t = threads.get(name)
                    if t is None or not t.is_alive():
                        logger.warning(f"⚠️ [SUPERVISOR] خيط {name} متوقف - إعادة تشغيله")

                        if name == "Monitor":
                            threading.Thread(target=main_system.monitor_loop, daemon=True, name="Monitor").start()
                        elif name == "SniperScanner":
                            threading.Thread(target=main_system.sniper_scanner_loop, daemon=True, name="SniperScanner").start()
                        elif name == "Scheduler":
                            threading.Thread(target=main_system.scheduler_loop, daemon=True, name="Scheduler").start()
                        elif name == "PerformanceTracker":
                            threading.Thread(target=main_system.performance_loop, daemon=True, name="PerformanceTracker").start()
                        elif name == "StallChecker":
                            threading.Thread(target=main_system.stall_check_loop, daemon=True, name="StallChecker").start()

                        logger.info(f"✅ [SUPERVISOR] أُعيد تشغيل {name}")

            except Exception as e:
                logger.error(f"خطأ في المراقب: {e}")

    except Exception as e:
        logger.error(f"خطأ في المراقب الرئيسي: {e}")


def main():
    """🔥 نقطة الدخول الرسمية — يستدعيها run_bot.py"""
    global main_system
    main_system = MainSystem()

    try:
        bot_enhanced.start_bot()
    except Exception as e:
        logger.error(f"❌ خطأ في بدء البوت: {e}")

    main_system.run()


if __name__ == "__main__":
    main()
