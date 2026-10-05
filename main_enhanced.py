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
    - 🔥 دالة main() رسمية (نقطة دخول run_bot.py)
🔧 إصلاحات v5.7.1 (بنية التوافق الكاملة مع bot_enhanced):
    - bot_enhanced.run_bot() (كان start_bot غير موجود)
    - دوال على مستوى الوحدة يتوقعها bot_enhanced:
      start_scanner_threads() / toggle_auto_trading() / get_system_status()
      + _auto_scan_enabled / _auto_trading_enabled
    - initialize() منفصلة عن الحلقة الطويلة (run_bot يحظر في polling
      والخيوط تبدأ من post_init → start_scanner_threads)
    - memory.get_memory_stats() و sync_from_firebase() (أسماء API الصحيحة)
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

# 🔔 v5.8: وحدة الإشعارات (بدء التشغيل / فتح / إغلاق)
try:
    import notifier
    logger.info("✅ notifier متاح")
except Exception as _e:
    logger.error(f"❌ notifier غير متاح: {_e}")
    notifier = None

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


def _cfg(name, default=None):
    """قراءة آمنة من config"""
    try:
        return getattr(config, name, default)
    except Exception:
        return default


# 🔥 حالة عامة على مستوى الوحدة — يتوقعها bot_enhanced (أزرار التلغرام)
_auto_scan_enabled = True
_auto_trading_enabled = True
main_system = None

def _risk_status():
    """🔥 حالة المخاطر — يكتشف اسم الدالة المتاح في core_functions عبر الإصدارات"""
    if not core:
        return {'paused': False, 'remaining_minutes': 0, 'consecutive_losses': 0}
    # 1) دوال مجمعة محتملة
    for name in ('get_risk_status', 'get_risk_state', 'risk_status',
                 'get_protection_status', 'get_risk_info'):
        fn = getattr(core, name, None)
        if callable(fn):
            try:
                r = fn() or {}
                if isinstance(r, (tuple, list)):
                    r = {'paused': bool(r[0]) if len(r) > 0 else False,
                         'remaining_minutes': r[1] if len(r) > 1 else 0}
                return {
                    'paused': bool(r.get('paused', r.get('is_paused', False))),
                    'remaining_minutes': int(r.get('remaining_minutes',
                                                   r.get('pause_remaining', r.get('minutes', 0)))),
                    'consecutive_losses': int(r.get('consecutive_losses', r.get('losses', 0))),
                }
            except Exception:
                pass
    # 2) تركيب يدوي من الدوال المؤكدة (is_trading_paused / get_pause_reason ...)
    paused, remaining, losses = False, 0, 0
    try:
        fn = getattr(core, 'is_trading_paused', None)
        if callable(fn):
            res = fn()
            # 🔥 is_trading_paused ترجع (paused, remaining_minutes) — bool(tuple) كانت دائماً True
            if isinstance(res, (tuple, list)):
                paused = bool(res[0]) if len(res) > 0 else False
                if len(res) > 1:
                    try:
                        remaining = int(res[1])
                    except Exception:
                        remaining = 0
            else:
                paused = bool(res)
    except Exception:
        pass
    for name in ('get_pause_remaining_minutes', 'get_pause_remaining',
                 'get_pause_minutes', 'get_pause_time_remaining'):
        fn = getattr(core, name, None)
        if callable(fn):
            try:
                remaining = int(fn())
                break
            except Exception:
                pass
    try:
        fn = getattr(core, 'get_consecutive_losses', None)
        losses = int(fn()) if callable(fn) else 0
    except Exception:
        pass
    return {'paused': paused, 'remaining_minutes': remaining, 'consecutive_losses': losses}


def _daily_pnl():
    """صافي اليوم — بأسماء متعددة محتملة"""
    if not core:
        return {'pnl': 0.0}
    for name in ('get_daily_pnl', 'get_accurate_daily_pnl', 'get_today_pnl'):
        fn = getattr(core, name, None)
        if callable(fn):
            try:
                r = fn() or {}
                pnl = r.get('pnl', r.get('daily_pnl', 0))
                return {'pnl': float(pnl)}
            except Exception:
                pass
    return {'pnl': 0.0}


class MainSystem:
    def __init__(self):
        self.running = True
        self.signals_sent = 0
        self.last_signal_time = time.time()
        self.last_scan_time = time.time()
        self.last_heartbeat = time.time()   # 🔥 v5.8: نبض الماسح (للـ StallChecker)
        self.tracker = None                 # 🔔 كاشف إغلاق الصفقات
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

    # ==================== الإقلاع (بدون حلقة طويلة) ====================

    def initialize(self):
        """تهيئة ما قبل polling: فحص صحة + مزامنة + سجل الإعدادات"""
        try:
            self.health_check()

            if core:
                try:
                    core.sync_trade_files()
                except Exception as e:
                    logger.debug(f"sync_trade_files: {e}")

            if _cfg('ENABLE_ORPHAN_CLEANUP', True) and core:
                try:
                    deleted = core.cleanup_orphan_orders()
                    if deleted:
                        logger.info(f"🧹 [MAIN] تم حذف {deleted} أمر يتيم")
                except Exception as e:
                    logger.debug(f"cleanup: {e}")

            if MEMORY_AVAILABLE:
                for sync_name in ('sync_from_binance', 'sync_from_firebase', 'sync_from_file'):
                    fn = getattr(memory, sync_name, None)
                    if callable(fn):
                        try:
                            fn()
                            break
                        except Exception as e:
                            logger.debug(f"{sync_name}: {e}")

            stats = {}
            if MEMORY_AVAILABLE:
                try:
                    stats = memory.get_memory_stats()
                except AttributeError:
                    try:
                        stats = memory.get_trading_stats()
                    except Exception:
                        pass
                except Exception:
                    pass
            logger.info(f"📊 [MAIN] عدد الصفقات: {stats.get('total_trades', 0)}")
            logger.info(f"📊 [MAIN] نسبة النجاح: {stats.get('win_rate', 0)}%")

            logger.info("=" * 60)
            logger.info("🎯 [MAIN] نظام القناص مفعل")
            logger.info("=" * 60)

            logger.info(f"⏰ [MAIN] المسح كل {_cfg('AUTO_SCAN_INTERVAL', 420) // 60} دقيقة")
            logger.info(f"🎯 [MAIN] MIN_SCORE: {_cfg('MIN_SCORE_REQUIRED', 55)}")
            logger.info(f"📈 [MAIN] MAX_POSITIONS: {_cfg('MAX_OPEN_POSITIONS', 6)}")
            logger.info(f"💰 [MAIN] TRADE_USDT: {_cfg('TRADE_USDT', 10)}")
            logger.info(f"⚡ [MAIN] LEVERAGE: {_cfg('LEVERAGE', 15)}x")
            logger.info(f"🔔 [MAIN] إشعار إغلاق: {'✅' if _cfg('ENABLE_CLOSE_NOTIFICATIONS', True) else '❌'}")
            logger.info(f"🧠 [MAIN] التعلم التلقائي: {'✅' if _cfg('ENABLE_AUTO_LEARNING', True) else '❌'}")
            logger.info(f"📊 [MAIN] التقارير اليومية: {'✅' if _cfg('ENABLE_DAILY_REPORT', True) else '❌'}")
            logger.info(f"🔥 [MAIN] Firebase Backup: {'✅' if _cfg('ENABLE_FIREBASE_BACKUP', True) else '❌'}")
            logger.info("=" * 60)

        except Exception as e:
            logger.error(f"❌ خطأ في التهيئة: {e}")
            import traceback
            logger.error(traceback.format_exc())

    def run(self):
        """تشغيل مستقل (بديل عن مسار run_bot)"""
        self.initialize()
        self.start_scanner_threads()
        try:
            while self.running:
                time.sleep(1)
        except KeyboardInterrupt:
            logger.info("⏹️ إيقاف...")
            self.running = False

    # ==================== أدوات ====================

    def get_open_positions(self):
        try:
            if core:
                positions = core.get_open_positions()
                return positions if positions else []
        except:
            pass
        return []

    def health_check(self):
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
        try:
            if not core:
                return True, "Core متاح"

            balance = core.get_futures_balance()
            if balance is None:
                return False, "فشل قراءة الرصيد"
            if balance < 5:
                return False, f"رصيد منخفض ({balance:.2f}$)"

            risk = _risk_status()
            if risk.get('paused', False):
                return False, f"التداول موقوف ({risk.get('remaining_minutes', 0)} دقيقة)"

            max_pos = _cfg('MAX_OPEN_POSITIONS', 6)
            open_pos = self.get_open_positions()
            if len(open_pos) >= max_pos:
                return False, f"أقصى عدد صفقات ({len(open_pos)}/{max_pos})"

            if _cfg('ENABLE_DAILY_DRAWDOWN_LIMIT', True):
                daily_pnl = _daily_pnl().get('pnl', 0)
                loss_limit = -float(_cfg('DAILY_MAX_LOSS_USDT', 7.0))
                if daily_pnl <= loss_limit:
                    return False, f"حد الخسارة اليومية ({daily_pnl:.2f}$)"

            return True, "جميع الفحوصات سليمة"
        except Exception as e:
            logger.error(f"خطأ في فحص ما قبل التداول: {e}")
            return True, "فحص جزئي"

    def cleanup_orphan_orders(self):
        try:
            if _cfg('ENABLE_ORPHAN_CLEANUP', True) and core:
                current_time = time.time()
                if current_time - self.orphan_cleanup_last >= _cfg('ORPHAN_CLEANUP_INTERVAL', 300):
                    self.orphan_cleanup_last = current_time
                    deleted = core.cleanup_orphan_orders()
                    if deleted > 0:
                        logger.info(f"🧹 [CLEANUP] تم حذف {deleted} أمر يتيم")
        except Exception as e:
            logger.error(f"خطأ في التنظيف: {e}")

    def send_daily_report(self):
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
        try:
            if not daily_reporter:
                return
            today = datetime.now()
            week_start = (today - timedelta(days=today.weekday())).strftime('%Y-%m-%d')
            if self.last_weekly_report_date == week_start:
                return
            if daily_reporter.send_weekly_report():
                self.last_weekly_report_date = week_start
                logger.info("✅ [REPORT] التقرير الأسبوعي")
        except Exception as e:
            logger.error(f"❌ خطأ في التقرير الأسبوعي: {e}")

    # ==================== الخيوط ====================

    def sniper_scanner_loop(self):
        try:
            scan_interval = _cfg('AUTO_SCAN_INTERVAL', 420)
            logger.info("🎯 [THREAD] بدء مسح القناص...")

            while self.running:
                try:
                    self.last_heartbeat = time.time()
                    global _auto_scan_enabled
                    if not _auto_scan_enabled:
                        time.sleep(30)
                        continue

                    if not self.health_check():
                        time.sleep(60)
                        continue

                    risk = _risk_status()
                    if risk.get('paused', False):
                        logger.warning(f"⏸️ توقف - {risk.get('remaining_minutes', 0)} د")
                        time.sleep(60)
                        continue

                    logger.info("🎯 [SCAN] بدء مسح القناص...")
                    signals = strategies.scan_sniper_signals() if strategies else []
                    self.last_scan_time = time.time()
                    self.last_heartbeat = time.time()

                    if signals:
                        logger.info(f"🎯 {len(signals)} إشارة")
                        for signal in signals[:_cfg('MAX_OPEN_POSITIONS', 6)]:
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
        global _auto_trading_enabled
        if not _auto_trading_enabled:
            logger.info("⏸️ التنفيذ التلقائي متوقف — تُركت الإشارة")
            return

        try:
            symbol = signal['symbol']
            direction = signal['direction']

            logger.info(f"🚀 فحص {symbol} {direction}")

            ok, reason = self.pre_trade_health_check(symbol, direction)
            if not ok:
                logger.warning(f"🛑 {symbol}: {reason}")
                return

            # فحص عدد الصفقات بنفس الاتجاه
            try:
                positions = self.get_open_positions()
                same_dir = 0
                for p in positions:
                    pside = p.get('positionSide', '')
                    pdir = "BUY" if pside == "LONG" else "SELL"
                    if pdir == direction:
                        same_dir += 1
                if same_dir >= _cfg('MAX_SAME_DIRECTION_POSITIONS', 3):
                    logger.warning(f"🛑 {symbol}: {same_dir} صفقة {direction} مفتوحة (الحد {_cfg('MAX_SAME_DIRECTION_POSITIONS', 3)})")
                    return
            except Exception as e:
                logger.debug(f"فحص الاتجاه: {e}")

            # خفض الحجم بعد خسائر متتالية
            amount = _cfg('TRADE_USDT', 10)
            try:
                risk = _risk_status()
                if risk.get('consecutive_losses', 0) >= _cfg('RISK_REDUCE_AFTER_LOSSES', 3):
                    amount = amount * _cfg('AUTO_RISK_REDUCTION_FACTOR', 0.5)
                    logger.warning(f"⚠️ {symbol}: تقليل الحجم إلى {amount}$ بسبب خسائر متتالية")
            except Exception:
                pass

            sl_percent = _cfg('SL_PERCENT', 1.3)
            pside = "LONG" if str(direction).upper() == "BUY" else "SHORT"
            if _cfg('DYNAMIC_SL_ENABLED', True):
                try:
                    # calculate_dynamic_sl ترجع (sl_price, sl_percent)
                    _dyn = core.calculate_dynamic_sl(symbol, float(signal['entry_price']), pside)
                    _dyn_pct = _dyn[1] if isinstance(_dyn, (tuple, list)) else _dyn
                    sl_percent = max(_cfg('SL_MIN_PERCENT', 1.0), min(_cfg('SL_MAX_PERCENT', 1.6), float(_dyn_pct)))
                except Exception:
                    pass

            leverage = _cfg('LEVERAGE', 15)
            logger.info(f"✅ {symbol}: اجتاز كل الفحوص - جاري التنفيذ ({amount}$ | SL {sl_percent:.2f}%)")

            # 🔥 v5.8: التوقيع الصحيح (كان يُمرَّر 6 وسائط لدالة تقبل 4 → TypeError ولا تُفتح صفقة)
            result = core.place_market_order_with_multiple_tp(
                symbol, direction, amount, leverage, sl_percent=sl_percent
            )

            if result and result.get('closed_due_to_failure'):
                logger.error(f"❌ {symbol}: أُغلقت فوراً (فشل SL)")
                if notifier:
                    notifier.notify_trade_opened(result, signal, amount, leverage)
            elif result:
                logger.info(f"✅ {symbol}: تم فتح الصفقة بنجاح")
                self.last_signal_time = time.time()
                self.signals_sent += 1
                self._update_daily_stats(symbol, direction, 'OPEN', 0)
                # سجّل الصفقة كصفقة بوت (لحماية TP/SL وفصلها عن الصفقات اليدوية)
                try:
                    bot_enhanced.add_open_position(result)
                except Exception as e:
                    logger.debug(f"add_open_position: {e}")
                if notifier:
                    notifier.notify_trade_opened(result, signal, amount, leverage)
            else:
                logger.error(f"❌ {symbol}: فشل فتح الصفقة")

        except Exception as e:
            logger.error(f"خطأ في معالجة الإشارة: {e}")

    def _update_daily_stats(self, symbol, direction, action, pnl):
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

    def monitor_positions(self):
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
                    pnl = float(pos.get('unrealizedProfit', pos.get('unRealizedProfit', 0)))
                    entry_price = float(pos.get('entryPrice', 0))
                    amount = abs(float(pos.get('positionAmt', 0)))

                    if not symbol or amount == 0:
                        continue

                    # get_open_positions ترجع LONG/SHORT
                    if position_side not in ("LONG", "SHORT"):
                        position_side = "LONG" if float(pos.get('positionAmt', 0)) > 0 else "SHORT"
                    mark_price = core.get_price(symbol) or entry_price

                    # 🔥 v5.8: التحقق من TP/SL بالدوال الموجودة فعلاً (get_position_tp_sl/close_position غير موجودتين)
                    if _cfg('VERIFY_TP_SL_AFTER_CREATION', True):
                        try:
                            has_tp, has_sl, _details = core.verify_tp_sl_created(symbol, position_side)
                            if not has_sl:
                                logger.warning(f"⚠️ {symbol}: لا SL! محاولة الإصلاح...")
                                core.check_and_add_tp_sl_to_existing_positions()
                        except Exception as e:
                            logger.debug(f"verify TP/SL {symbol}: {e}")

                    if _cfg('TRAILING_SL_ENABLED', True):
                        try:
                            core.update_trailing_sl(symbol, position_side, mark_price)
                        except Exception as e:
                            logger.debug(f"trailing {symbol}: {e}")

                    if pnl <= -abs(entry_price * amount) * (_cfg('SL_PERCENT', 1.3) / 100) * 1.5:
                        logger.warning(f"🛑 {symbol}: خسارة حرجة {pnl:.2f}$ - إغلاق طارئ")
                        core.close_position_safe(symbol, position_side)

                except Exception as e:
                    logger.error(f"خطأ في مراقبة {pos.get('symbol', '?')}: {e}")
                    continue
        except Exception as e:
            logger.error(f"خطأ في المراقبة: {e}")

    def monitor_loop(self):
        try:
            while self.running:
                try:
                    if notifier and core:
                        try:
                            if self.tracker is None:
                                self.tracker = notifier.PositionTracker(core)
                            self.tracker.check()      # 🔔 إشعارات الإغلاق
                        except Exception as e:
                            logger.error(f"خطأ في كاشف الإغلاق: {e}")
                    self.monitor_positions()
                    self.cleanup_orphan_orders()
                    time.sleep(_cfg('MONITOR_TP_SL_INTERVAL', 60))
                except Exception as e:
                    logger.error(f"خطأ في المراقبة: {e}")
                    time.sleep(30)
        except Exception as e:
            logger.error(f"خطأ في خيط المراقبة: {e}")

    def performance_loop(self):
        try:
            while self.running:
                time.sleep(300)
                if not core:
                    continue
                try:
                    balance = core.get_futures_balance()
                    daily = _daily_pnl()
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
        try:
            while self.running:
                now = datetime.now()
                if now.hour == _cfg('DAILY_REPORT_HOUR', 10) and now.minute < 5:
                    self.send_daily_report()
                if now.weekday() == 0 and now.hour == 9 and now.minute < 5:
                    self.send_weekly_report()
                time.sleep(60)
        except Exception as e:
            logger.error(f"خطأ في الجدولة: {e}")

    def stall_check_loop(self):
        try:
            stall_minutes = _cfg('STALL_RESTART_MINUTES', 30)
            while self.running:
                try:
                    current_time = time.time()
                    if current_time - self.last_heartbeat > stall_minutes * 60:
                        logger.warning("⚠️ [STALL] لا إشارات - إعادة تشغيل...")
                        self.running = False
                        time.sleep(2)
                        import os
                        os.execv(sys.executable, [sys.executable] + sys.argv)
                    time.sleep(60)
                except Exception as e:
                    logger.error(f"خطأ في فحص التوقف: {e}")
                    time.sleep(60)
        except Exception as e:
            logger.error(f"خطأ في StallChecker: {e}")

    def start_scanner_threads(self):
        """بدء جميع الخيوط"""
        try:
            logger.info("🔧 [START] بدء تشغيل الخيوط...")
            logger.info("=" * 60)

            threads = [
                ("SniperScanner", self.sniper_scanner_loop),
                ("Monitor", self.monitor_loop),
                ("Scheduler", self.scheduler_loop),
                ("PerformanceTracker", self.performance_loop),
                ("StallChecker", self.stall_check_loop),
                ("Supervisor", supervisor_loop),
            ]

            for name, target in threads:
                try:
                    threading.Thread(target=target, daemon=True, name=name).start()
                    logger.info(f"✅ [START] {name}")
                except Exception as e:
                    logger.error(f"❌ [START] فشل {name}: {e}")

            # 🔥 فحص الأداء اليومي — حكم آلي على Telegram
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


def supervisor_loop():
    """مراقب يعيد تشغيل الخيوط المتوقفة"""
    try:
        logger.info("🛡️ [SUPERVISOR] بدء المراقبة")
        tracked = {"Monitor", "SniperScanner", "Scheduler",
                   "PerformanceTracker", "StallChecker", "PerformanceCheck"}

        def _restart(name):
            global main_system
            if main_system is None:
                return
            mapping = {
                "Monitor": main_system.monitor_loop,
                "SniperScanner": main_system.sniper_scanner_loop,
                "Scheduler": main_system.scheduler_loop,
                "PerformanceTracker": main_system.performance_loop,
                "StallChecker": main_system.stall_check_loop,
            }
            if name in mapping:
                threading.Thread(target=mapping[name], daemon=True, name=name).start()
            elif name == "PerformanceCheck":
                try:
                    import performance_check
                    performance_check.start_daily_check()
                except Exception:
                    pass

        while True:
            time.sleep(30)
            try:
                threads = {t.name: t for t in threading.enumerate()}
                for name in tracked:
                    t = threads.get(name)
                    if t is None or not t.is_alive():
                        logger.warning(f"⚠️ [SUPERVISOR] خيط {name} متوقف - إعادة تشغيله")
                        _restart(name)
                        logger.info(f"✅ [SUPERVISOR] أُعيد تشغيل {name}")
            except Exception as e:
                logger.error(f"خطأ في المراقب: {e}")
    except Exception as e:
        logger.error(f"خطأ في المراقب الرئيسي: {e}")


# ==================== دوال مستوى الوحدة (يتوقعها bot_enhanced) ====================

def start_scanner_threads():
    """🔥 يستدعيها bot_enhanced.run_bot عبر post_init"""
    global main_system
    if main_system is None:
        main_system = MainSystem()
        main_system.initialize()
    main_system.start_scanner_threads()
    if notifier:
        notifier.notify_startup(core)   # 🔔 "بدأ البوت العمل"


def toggle_auto_trading():
    """🔥 زر '🤖 تشغيل/إوقف التلقائي' في التلغرام"""
    global _auto_scan_enabled, _auto_trading_enabled
    _auto_scan_enabled = not _auto_scan_enabled
    _auto_trading_enabled = _auto_scan_enabled
    status = "🟢 مفعل" if _auto_scan_enabled else "🔴 متوقف"
    logger.info(f"🤖 التداول التلقائي: {status}")
    return f"🤖 <b>التداول التلقائي: {status}</b>\n\n⏰ {datetime.now().strftime('%H:%M:%S')}"


def get_system_status():
    """🔥 زر '📊 حالة النظام' في التلغرام"""
    status = {
        'auto_scan': _auto_scan_enabled,
        'auto_trading': _auto_trading_enabled,
        'open_positions': 0,
        'max_positions': _cfg('MAX_OPEN_POSITIONS', 6),
        'manual_positions': 0,
        'daily_pnl': 0.0, 'weekly_pnl': 0.0, 'monthly_pnl': 0.0,
        'cooldown_symbols': 0,
        'consecutive_losses': 0,
        'is_paused': False, 'pause_remaining': 0,
    }
    try:
        positions = core.get_open_positions() if core else []
        try:
            import bot_enhanced
            bot_keys = {f"{s.get('symbol')}_{s.get('positionSide')}" for s in bot_enhanced.load_state()}
            status['open_positions'] = sum(1 for p in positions
                                           if f"{p.get('symbol')}_{p.get('positionSide')}" in bot_keys)
            status['manual_positions'] = len(positions) - status['open_positions']
        except Exception:
            status['open_positions'] = len(positions)
    except Exception:
        pass
    try:
        status['daily_pnl'] = core.get_accurate_daily_pnl().get('daily_pnl', 0)
        status['weekly_pnl'] = core.get_accurate_weekly_pnl().get('weekly_pnl', 0)
        status['monthly_pnl'] = core.get_accurate_monthly_pnl().get('monthly_pnl', 0)
    except Exception:
        pass
    try:
        status['cooldown_symbols'] = strategies.get_cooldown_status().get('total_active', 0) if strategies else 0
    except Exception:
        pass
    try:
        status['consecutive_losses'] = core.get_consecutive_losses()
        risk = _risk_status()
        status['is_paused'] = risk.get('paused', False)
        status['pause_remaining'] = risk.get('remaining_minutes', 0)
    except Exception:
        pass
    return status


# ==================== نقطة الدخول ====================

def main():
    """🔥 نقطة الدخول الرسمية — يستدعيها run_bot.py"""
    global main_system
    main_system = MainSystem()
    main_system.initialize()

    # run_bot() يحظر في polling؛ الخيوط تبدأ عبر post_init → start_scanner_threads()
    try:
        bot_enhanced.run_bot()
    except Exception as e:
        logger.error(f"❌ خطأ في run_bot: {e}")
        import traceback
        logger.error(traceback.format_exc())

    # إذا انتهى polling (نادر) — أبقِ العملية حية بالخيوط
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("⏹️ إيقاف...")
        if main_system:
            main_system.running = False


if __name__ == "__main__":
    main()
