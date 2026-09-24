# ==================================================
# 📁 ملف: trade_memory.py - ذاكرة الصفقات الذكية v5.3
# 🔧 التعديلات v5.3:
#    - 🔥 إضافة backup_to_github (حفظ تلقائي)
#    - 🔥 إضافة auto_backup_thread (حفظ دوري)
#    - 🔥 إضافة get_all_trades_for_analysis
#    - حساب العمولات (v4.0)
#    - جلب exit_price الحقيقي (v4.0)
# 📅 التاريخ: 2026-09-24
# ==================================================

import json
import os
import logging
import base64
import requests
import threading
import time
from datetime import datetime, timedelta
from threading import Lock

logger = logging.getLogger("trade_memory")

MEMORY_FILE = "trade_memory.json"
_lock = Lock()

# 🔥 معدل العمولة
try:
    from config import COMMISSION_RATE
except ImportError:
    COMMISSION_RATE = 0.0004

# 🔥 GitHub Backup
try:
    from config import (
        GITHUB_TOKEN, GITHUB_REPO, GITHUB_BRANCH,
        ENABLE_AUTO_BACKUP, BACKUP_INTERVAL_MINUTES
    )
except ImportError:
    GITHUB_TOKEN = ""
    GITHUB_REPO = ""
    GITHUB_BRANCH = "main"
    ENABLE_AUTO_BACKUP = False
    BACKUP_INTERVAL_MINUTES = 10

_backup_thread_running = False


def _ensure_memory_file():
    if not os.path.exists(MEMORY_FILE):
        initial_data = {
            "trades": [],
            "symbol_stats": {},
            "hourly_stats": {},
            "condition_stats": {},
            "last_updated": datetime.now().isoformat(),
            "total_trades": 0,
            "total_wins": 0,
            "total_losses": 0,
            "total_pnl": 0.0
        }
        with open(MEMORY_FILE, "w", encoding="utf-8") as f:
            json.dump(initial_data, f, indent=2, ensure_ascii=False)


def load_memory():
    try:
        _ensure_memory_file()
        with open(MEMORY_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"خطأ في تحميل الذاكرة: {e}")
        return {
            "trades": [], "symbol_stats": {}, "hourly_stats": {},
            "condition_stats": {}, "total_trades": 0, "total_wins": 0,
            "total_losses": 0, "total_pnl": 0.0
        }


def save_memory(data):
    try:
        data["last_updated"] = datetime.now().isoformat()
        with open(MEMORY_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        return True
    except Exception as e:
        logger.error(f"خطأ في حفظ الذاكرة: {e}")
        return False


# ==================== 🔥 GitHub Backup ====================

def backup_to_github(force=False):
    """
    🔥 رفع trade_memory.json إلى GitHub
    """
    try:
        if not GITHUB_TOKEN:
            if force:
                logger.warning("⚠️ GITHUB_TOKEN غير موجود - تخطي الرفع")
            return False

        if not os.path.exists(MEMORY_FILE):
            logger.warning("⚠️ trade_memory.json غير موجود")
            return False

        # قراءة الملف
        with open(MEMORY_FILE, "r", encoding="utf-8") as f:
            content = f.read()

        # Base64
        content_b64 = base64.b64encode(content.encode('utf-8')).decode('utf-8')

        # API URL
        url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/trade_memory.json"
        headers = {
            "Authorization": f"token {GITHUB_TOKEN}",
            "Accept": "application/vnd.github.v3+json"
        }

        # جلب SHA الحالي
        sha = None
        try:
            response = requests.get(url, headers=headers, timeout=15)
            if response.status_code == 200:
                sha = response.json().get("sha")
        except:
            pass

        # رفع
        data = {
            "message": f"Auto-save: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            "content": content_b64,
            "branch": GITHUB_BRANCH
        }
        if sha:
            data["sha"] = sha

        response = requests.put(url, headers=headers, json=data, timeout=30)

        if response.status_code in [200, 201]:
            logger.info(f"💾 تم حفظ trade_memory.json في GitHub")
            return True
        else:
            logger.warning(f"⚠️ فشل الحفظ في GitHub: {response.status_code}")
            return False

    except Exception as e:
        logger.error(f"خطأ في backup_to_github: {e}")
        return False


def auto_backup_loop():
    """
    🔥 خيط الحفظ الدوري في GitHub
    """
    global _backup_thread_running

    if not ENABLE_AUTO_BACKUP:
        logger.info("ℹ️ الحفظ التلقائي معطل")
        return

    if not GITHUB_TOKEN:
        logger.warning("⚠️ GITHUB_TOKEN غير موجود - الحفظ التلقائي معطل")
        return

    _backup_thread_running = True
    logger.info(f"💾 بدء الحفظ الدوري (كل {BACKUP_INTERVAL_MINUTES} دقيقة)")

    while _backup_thread_running:
        try:
            time.sleep(BACKUP_INTERVAL_MINUTES * 60)

            if _backup_thread_running:
                logger.info("💾 حفظ دوري في GitHub...")
                backup_to_github()

        except Exception as e:
            logger.error(f"خطأ في الحفظ الدوري: {e}")
            time.sleep(60)


def start_auto_backup():
    """بدء الحفظ التلقائي في خيط منفصل"""
    try:
        if not ENABLE_AUTO_BACKUP:
            logger.info("ℹ️ الحفظ التلقائي معطل")
            return False

        thread = threading.Thread(target=auto_backup_loop, daemon=True, name="GitHubBackup")
        thread.start()
        logger.info("✅ تم تشغيل الحفظ التلقائي في GitHub")
        return True
    except Exception as e:
        logger.error(f"❌ فشل تشغيل الحفظ التلقائي: {e}")
        return False


# ==================== جلب سعر الخروج ====================

def get_exit_price(symbol, entry_time_iso):
    try:
        import core_functions as core
        client_obj = core.get_client()
        if not client_obj:
            return 0.0

        try:
            entry_dt = datetime.fromisoformat(entry_time_iso)
            entry_ts = int(entry_dt.timestamp() * 1000)
        except:
            entry_ts = int((datetime.now() - timedelta(hours=2)).timestamp() * 1000)

        trades = client_obj.futures_account_trades(
            symbol=symbol, startTime=entry_ts, limit=20
        )

        if not trades:
            return 0.0

        return float(trades[-1].get('price', 0))

    except Exception as e:
        logger.warning(f"⚠️ تعذر جلب exit_price لـ {symbol}: {e}")
        return 0.0


def calculate_net_pnl(entry_price, exit_price, quantity, direction):
    try:
        if not entry_price or not quantity:
            return 0.0

        if direction == "BUY":
            gross_pnl = (exit_price - entry_price) * quantity
        else:
            gross_pnl = (entry_price - exit_price) * quantity

        entry_commission = entry_price * quantity * COMMISSION_RATE
        exit_commission = exit_price * quantity * COMMISSION_RATE
        total_commission = entry_commission + exit_commission

        net_pnl = gross_pnl - total_commission

        return round(net_pnl, 6)

    except Exception as e:
        logger.error(f"خطأ في حساب الربح الصافي: {e}")
        return 0.0


# ==================== تسجيل الصفقة ====================

def record_trade(symbol, direction, entry_price, exit_price,
                 quantity, pnl, confidence, timeframe_alignment,
                 volume_ratio, groq_recommendation, groq_confidence,
                 score_details=None, exit_reason="unknown",
                 entry_time_iso=None):
    try:
        with _lock:
            memory = load_memory()

            if not exit_price or exit_price == 0:
                if entry_time_iso:
                    exit_price = get_exit_price(symbol, entry_time_iso)

            if exit_price and exit_price > 0:
                net_pnl = calculate_net_pnl(entry_price, exit_price, quantity, direction)
            else:
                commission = entry_price * quantity * COMMISSION_RATE * 2
                net_pnl = pnl - commission

            is_win = net_pnl > 0.01

            position_value = entry_price * quantity
            pnl_percent = (net_pnl / position_value * 100) if position_value > 0 else 0

            trade_record = {
                "id": len(memory["trades"]) + 1,
                "symbol": symbol,
                "direction": direction,
                "entry_price": entry_price,
                "exit_price": round(exit_price, 8) if exit_price else 0,
                "quantity": quantity,
                "pnl_gross": round(pnl, 4),
                "pnl": round(net_pnl, 4),
                "pnl_percent": round(pnl_percent, 4),
                "is_win": is_win,
                "confidence": confidence,
                "timeframe_alignment": timeframe_alignment,
                "volume_ratio": volume_ratio,
                "groq_recommendation": groq_recommendation,
                "groq_confidence": groq_confidence,
                "score_details": score_details or {},
                "exit_reason": exit_reason,
                "entry_time": entry_time_iso or datetime.now().isoformat(),
                "hour": datetime.now().hour,
                "day_of_week": datetime.now().weekday(),
                "date": datetime.now().strftime("%Y-%m-%d")
            }

            memory["trades"].append(trade_record)
            memory["total_trades"] += 1
            if is_win:
                memory["total_wins"] += 1
            else:
                memory["total_losses"] += 1
            memory["total_pnl"] = round(memory["total_pnl"] + net_pnl, 4)

            if symbol not in memory["symbol_stats"]:
                memory["symbol_stats"][symbol] = {
                    "wins": 0, "losses": 0, "total_pnl": 0.0,
                    "last_trade": None, "consecutive_losses": 0,
                    "avg_confidence": 0, "avg_pnl": 0
                }

            stats = memory["symbol_stats"][symbol]
            stats["wins" if is_win else "losses"] += 1
            stats["total_pnl"] = round(stats["total_pnl"] + net_pnl, 4)
            stats["last_trade"] = datetime.now().isoformat()

            if net_pnl < 0:
                stats["consecutive_losses"] += 1
            else:
                stats["consecutive_losses"] = 0

            total = stats["wins"] + stats["losses"]
            if total > 0:
                stats["avg_confidence"] = round(
                    (stats["avg_confidence"] * (total - 1) + confidence) / total, 2
                )
                stats["avg_pnl"] = round(stats["total_pnl"] / total, 4)

            hour_key = str(datetime.now().hour)
            if hour_key not in memory["hourly_stats"]:
                memory["hourly_stats"][hour_key] = {
                    "wins": 0, "losses": 0, "total_pnl": 0.0
                }

            hour_stats = memory["hourly_stats"][hour_key]
            hour_stats["wins" if is_win else "losses"] += 1
            hour_stats["total_pnl"] = round(hour_stats["total_pnl"] + net_pnl, 4)

            save_memory(memory)

            # 🔥 حفظ فوري في GitHub (بعد كل صفقة)
            if ENABLE_AUTO_BACKUP:
                try:
                    backup_to_github()
                except:
                    pass

            status = "✅" if is_win else "❌"
            logger.info(f"📝 تسجيل: {symbol} {status} صافي: {net_pnl:+.4f}$")

            return True

    except Exception as e:
        logger.error(f"خطأ في تسجيل الصفقة: {e}")
        return False


# ==================== نقاط العملة ====================

def get_symbol_score(symbol):
    try:
        memory = load_memory()

        if symbol not in memory["symbol_stats"]:
            return {'score': 50, 'should_trade': True, 'reason': 'عملة جديدة', 'stats': {}}

        stats = memory["symbol_stats"][symbol]
        total = stats["wins"] + stats["losses"]

        if total == 0:
            return {'score': 50, 'should_trade': True, 'reason': 'لا يوجد تاريخ', 'stats': stats}

        win_rate = stats["wins"] / total
        score = 50
        score += (win_rate - 0.5) * 100

        if stats["consecutive_losses"] >= 3:
            score -= 30
        elif stats["consecutive_losses"] >= 2:
            score -= 15

        if stats["total_pnl"] < -1.0:
            score -= 30
        elif stats["total_pnl"] < -0.5:
            score -= 15

        if win_rate >= 0.7 and total >= 5:
            score += 20
        elif win_rate >= 0.6 and total >= 3:
            score += 10

        score = max(0, min(100, score))

        should_trade = True
        reason = f"نسبة نجاح: {win_rate*100:.1f}% ({stats['wins']}/{total}) | PnL: {stats['total_pnl']:+.2f}$"

        if score < 30:
            should_trade = False
            reason = f"⚠️ أداء ضعيف"
        elif stats["consecutive_losses"] >= 3:
            should_trade = False
            reason = f"⚠️ {stats['consecutive_losses']} خسائر متتالية"
        elif stats["total_pnl"] < -1.0:
            should_trade = False
            reason = f"⚠️ خسارة كلية: {stats['total_pnl']:.2f}$"

        return {
            'score': round(score, 2),
            'should_trade': should_trade,
            'reason': reason,
            'win_rate': round(win_rate * 100, 2),
            'total_trades': total,
            'total_pnl': stats['total_pnl'],
            'consecutive_losses': stats["consecutive_losses"],
            'stats': stats
        }

    except Exception as e:
        logger.error(f"خطأ: {e}")
        return {'score': 50, 'should_trade': True, 'reason': 'خطأ', 'stats': {}}


def get_hour_score(hour=None):
    try:
        if hour is None:
            hour = datetime.now().hour

        memory = load_memory()
        hour_key = str(hour)

        if hour_key not in memory["hourly_stats"]:
            return {'score': 50, 'should_trade': True, 'reason': 'ساعة جديدة'}

        stats = memory["hourly_stats"][hour_key]
        total = stats["wins"] + stats["losses"]

        if total < 3:
            return {'score': 50, 'should_trade': True, 'reason': 'بيانات غير كافية'}

        win_rate = stats["wins"] / total

        if win_rate < 0.3:
            return {'score': 20, 'should_trade': False, 'reason': f"⚠️ ساعة سيئة", 'win_rate': round(win_rate * 100, 2)}

        return {'score': round(win_rate * 100, 2), 'should_trade': True, 'reason': f"نسبة نجاح: {win_rate*100:.0f}%", 'win_rate': round(win_rate * 100, 2)}

    except Exception as e:
        logger.error(f"خطأ: {e}")
        return {'score': 50, 'should_trade': True, 'reason': 'خطأ'}


def get_memory_stats():
    try:
        memory = load_memory()
        total = memory["total_trades"]
        wins = memory["total_wins"]
        losses = memory["total_losses"]
        win_rate = (wins / total * 100) if total > 0 else 0

        yesterday = (datetime.now() - timedelta(days=1)).isoformat()
        recent_trades = [t for t in memory["trades"] if t.get("entry_time", "") >= yesterday]
        recent_wins = len([t for t in recent_trades if t["is_win"]])
        recent_pnl = sum(t["pnl"] for t in recent_trades)

        return {
            'total_trades': total,
            'total_wins': wins,
            'total_losses': losses,
            'win_rate': round(win_rate, 2),
            'total_pnl': memory["total_pnl"],
            'recent_24h_trades': len(recent_trades),
            'recent_24h_wins': recent_wins,
            'recent_24h_pnl': round(recent_pnl, 4),
            'last_updated': memory.get("last_updated", "N/A")
        }

    except Exception as e:
        logger.error(f"خطأ: {e}")
        return {}


def get_today_pnl():
    try:
        memory = load_memory()
        today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
        today_trades = [t for t in memory["trades"] if t.get("entry_time", "") >= today_start]
        total_pnl = sum(t.get("pnl", 0) for t in today_trades)
        return round(total_pnl, 4)
    except Exception as e:
        logger.error(f"خطأ: {e}")
        return 0.0


def get_all_trades_for_analysis(min_trades=10):
    """🔥 جلب كل الصفقات للتحليل"""
    try:
        memory = load_memory()
        trades = memory.get("trades", [])
        return trades[-min_trades:] if len(trades) >= min_trades else trades
    except:
        return []


def get_symbol_history(symbol, limit=10):
    try:
        memory = load_memory()
        trades = [t for t in memory["trades"] if t["symbol"] == symbol]
        return trades[-limit:]
    except:
        return []


def is_symbol_blacklisted(symbol, min_trades=5, max_win_rate=0.25, max_consecutive_losses=3):
    try:
        memory = load_memory()
        if symbol not in memory["symbol_stats"]:
            return False, ""

        stats = memory["symbol_stats"][symbol]
        total = stats["wins"] + stats["losses"]

        if total < min_trades:
            return False, ""

        win_rate = stats["wins"] / total

        if win_rate < max_win_rate:
            return True, f"نسبة نجاح منخفضة: {win_rate*100:.1f}%"

        if stats["consecutive_losses"] >= max_consecutive_losses:
            return True, f"{stats['consecutive_losses']} خسائر متتالية"

        if stats["total_pnl"] < -1.0:
            return True, f"خسارة كلية: {stats['total_pnl']:.2f}$"

        avg_pnl = stats["total_pnl"] / total if total > 0 else 0
        if avg_pnl < -0.5:
            return True, f"متوسط خسارة: {avg_pnl:.2f}$"

        return False, ""

    except Exception as e:
        logger.error(f"خطأ: {e}")
        return False, ""


# ==================== مزامنة profit_history ====================

def sync_profit_history():
    try:
        memory = load_memory()
        daily_profits = {}
        weekly_profits = {}
        monthly_profits = {}

        for trade in memory.get("trades", []):
            entry_time = trade.get("entry_time", "")
            if not entry_time:
                continue
            try:
                dt = datetime.fromisoformat(entry_time)
            except:
                continue

            date_key = dt.strftime("%Y-%m-%d")
            week_key = f"{dt.year}-W{dt.isocalendar()[1]:02d}"
            month_key = dt.strftime("%Y-%m")
            pnl = trade.get("pnl", 0)

            daily_profits[date_key] = round(daily_profits.get(date_key, 0) + pnl, 4)
            weekly_profits[week_key] = round(weekly_profits.get(week_key, 0) + pnl, 4)
            monthly_profits[month_key] = round(monthly_profits.get(month_key, 0) + pnl, 4)

        profit_history = {
            "daily_profits": daily_profits,
            "weekly_profits": weekly_profits,
            "monthly_profits": monthly_profits,
            "last_sync": datetime.now().isoformat(),
            "total_profit": memory.get("total_pnl", 0),
            "total_trades": memory.get("total_trades", 0)
        }

        with open("profit_history.json", "w", encoding="utf-8") as f:
            json.dump(profit_history, f, indent=2, ensure_ascii=False)

        logger.info(f"✅ تم مزامنة profit_history.json")
        return True

    except Exception as e:
        logger.error(f"خطأ: {e}")
        return False


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print("🧪 اختبار ذاكرة الصفقات v5.3...")
    net = calculate_net_pnl(entry_price=100, exit_price=101, quantity=1, direction="BUY")
    print(f"صافي الربح: {net}$")
    stats = get_memory_stats()
    print(f"إحصائيات: {stats}")
    print("\n🧪 اختبار GitHub backup:")
    backup_to_github(force=True)