# ==================================================
# 📁 ملف: trade_memory.py - v6.0
# 🔧 التعديلات v6.0:
#    - 🔥 حظر مؤقت 48 ساعة (بدل دائم)
#    - 🔥 إعادة حساب الإحصائيات من آخر 100 صفقة
#    - 🔥 إعادة حساب من Firebase عند الإقلاع
# ==================================================

import json
import os
import logging
import threading
import time
from datetime import datetime, timedelta
from threading import Lock

logger = logging.getLogger("trade_memory")

MEMORY_FILE = "trade_memory.json"
MAX_TRADES_TO_KEEP = 100
BLOCK_DURATION_HOURS = 48    # 🔥 حظر مؤقت
_lock = Lock()

try:
    from config import COMMISSION_RATE
except ImportError:
    COMMISSION_RATE = 0.0004

try:
    import firebase_backup
    FIREBASE_AVAILABLE = True
except ImportError:
    FIREBASE_AVAILABLE = False
    firebase_backup = None

try:
    from config import (
        ENABLE_FIREBASE_BACKUP,
        FIREBASE_BACKUP_INTERVAL
    )
except ImportError:
    ENABLE_FIREBASE_BACKUP = False
    FIREBASE_BACKUP_INTERVAL = 30


# ==================== التحميل والحفظ ====================

def _ensure_memory_file():
    if not os.path.exists(MEMORY_FILE):
        initial_data = {
            "trades": [], "symbol_stats": {}, "hourly_stats": {},
            "condition_stats": {}, "last_updated": datetime.now().isoformat(),
            "total_trades": 0, "total_wins": 0,
            "total_losses": 0, "total_pnl": 0.0
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


# ==================== 🔥 إعادة حساب الإحصائيات (جديد v6.0) ====================

def recalculate_stats(memory=None):
    """
    🔥 إعادة بناء symbol_stats و hourly_stats من الصفقات الأخيرة فقط
    يصلح مشكلة تراكم الإحصائيات الخاطئة
    """
    try:
        if memory is None:
            memory = load_memory()
        
        trades = memory.get("trades", [])
        
        # إعادة تعيين
        symbol_stats = {}
        hourly_stats = {}
        
        for trade in trades:
            symbol = trade.get("symbol", "UNKNOWN")
            is_win = trade.get("is_win", False)
            pnl = trade.get("pnl", 0)
            hour = str(trade.get("hour", 0))
            
            # symbol_stats
            if symbol not in symbol_stats:
                symbol_stats[symbol] = {
                    "wins": 0, "losses": 0, "total_pnl": 0.0,
                    "last_trade": None, "consecutive_losses": 0,
                    "avg_confidence": 0, "avg_pnl": 0
                }
            
            stats = symbol_stats[symbol]
            if is_win:
                stats["wins"] += 1
                stats["consecutive_losses"] = 0
            else:
                stats["losses"] += 1
                stats["consecutive_losses"] += 1
            
            stats["total_pnl"] = round(stats["total_pnl"] + pnl, 4)
            stats["last_trade"] = trade.get("entry_time", "")
            
            total = stats["wins"] + stats["losses"]
            if total > 0:
                stats["avg_pnl"] = round(stats["total_pnl"] / total, 4)
            
            # hourly_stats
            if hour not in hourly_stats:
                hourly_stats[hour] = {"wins": 0, "losses": 0, "total_pnl": 0.0}
            
            hstats = hourly_stats[hour]
            if is_win:
                hstats["wins"] += 1
            else:
                hstats["losses"] += 1
            hstats["total_pnl"] = round(hstats["total_pnl"] + pnl, 4)
        
        # تحديث الإجماليات
        total_trades = len(trades)
        total_wins = sum(1 for t in trades if t.get("is_win", False))
        total_losses = total_trades - total_wins
        total_pnl = round(sum(t.get("pnl", 0) for t in trades), 4)
        
        memory["symbol_stats"] = symbol_stats
        memory["hourly_stats"] = hourly_stats
        memory["total_trades"] = total_trades
        memory["total_wins"] = total_wins
        memory["total_losses"] = total_losses
        memory["total_pnl"] = total_pnl
        
        save_memory(memory)
        
        logger.info(f"✅ إعادة حساب: {total_trades} صفقة, {len(symbol_stats)} عملة")
        return memory
    
    except Exception as e:
        logger.error(f"❌ فشل إعادة الحساب: {e}")
        return memory


# ==================== Firebase ====================

def backup_to_firebase(memory_data=None):
    try:
        if not FIREBASE_AVAILABLE:
            return False
        if not firebase_backup.is_available():
            return False
        if memory_data is None:
            memory_data = load_memory()
        return firebase_backup.save_to_firebase(memory_data)
    except Exception as e:
        logger.error(f"❌ فشل backup: {e}")
        return False


def sync_from_firebase():
    try:
        if not FIREBASE_AVAILABLE:
            return False
        if not firebase_backup.is_available():
            return False
        
        result = firebase_backup.sync_from_firebase_on_startup()
        
        # 🔥 إعادة حساب الإحصائيات بعد المزامنة
        if result:
            logger.info("🔄 إعادة حساب الإحصائيات بعد المزامنة...")
            recalculate_stats()
        
        return result
    except Exception as e:
        logger.error(f"❌ فشل sync: {e}")
        return False


def start_auto_backup():
    try:
        if not ENABLE_FIREBASE_BACKUP or not FIREBASE_AVAILABLE:
            return False
        return firebase_backup.start_auto_backup()
    except Exception as e:
        logger.error(f"❌ فشل auto_backup: {e}")
        return False


# ==================== 🔥 الحظر المؤقت (جديد v6.0) ====================

def is_symbol_permanently_blocked(symbol):
    """
    🔥 v6.0: حظر مؤقت 48 ساعة (بدل دائم)
    الشروط:
    - خسارتان متتاليتان + إجمالي سالب
    - 4+ خسائر مع ربحية سلبية
    - 4+ صفقات + نسبة نجاح أقل من 25%
    - خسارة كلية أكبر من 2$
    
    مع فحص آخر صفقة خاسرة - إن مرّت 48 ساعة → رفع الحظر
    """
    try:
        memory = load_memory()
        stats = memory.get("symbol_stats", {}).get(symbol, {})
        
        if not stats:
            return False, ""
        
        # 🔥 فحص الوقت: هل مرّت 48 ساعة منذ آخر خسارة؟
        last_trade_iso = stats.get("last_trade", "")
        if last_trade_iso:
            try:
                last_trade_time = datetime.fromisoformat(last_trade_iso)
                hours_since = (datetime.now() - last_trade_time).total_seconds() / 3600
                
                if hours_since >= BLOCK_DURATION_HOURS:
                    logger.info(f"✅ {symbol}: مرّت {hours_since:.1f} ساعة - رفع الحظر تلقائياً")
                    return False, ""
            except:
                pass
        
        wins = stats.get("wins", 0)
        losses = stats.get("losses", 0)
        total = wins + losses
        total_pnl = stats.get("total_pnl", 0)
        consecutive = stats.get("consecutive_losses", 0)
        
        # شرط 1: خسارتان متتاليتان
        if consecutive >= 2 and total_pnl < -0.5:
            return True, f"خسارتان متتاليتان (48 ساعة)"
        
        # شرط 2: 4+ خسائر
        if losses >= 4 and total_pnl < 0:
            return True, f"{losses} خسائر (48 ساعة)"
        
        # شرط 3: نسبة نجاح منخفضة
        if total >= 4 and (wins / total) < 0.25:
            return True, f"نسبة نجاح {wins/total*100:.0f}% (48 ساعة)"
        
        # شرط 4: خسارة كلية
        if total_pnl < -2.0:
            return True, f"خسارة كلية {total_pnl:.2f}$ (48 ساعة)"
        
        return False, ""
    except Exception as e:
        logger.error(f"خطأ: {e}")
        return False, ""


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
        logger.warning(f"⚠️ تعذر جلب exit_price: {e}")
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
        return round(gross_pnl - entry_commission - exit_commission, 6)
    except:
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

            entry_dt = datetime.now()
            if entry_time_iso:
                try:
                    entry_dt = datetime.fromisoformat(entry_time_iso)
                except:
                    pass

            trade_record = {
                "id": len(memory["trades"]) + 1,
                "symbol": symbol, "direction": direction,
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
                "hour": entry_dt.hour,
                "day_of_week": entry_dt.weekday(),
                "date": entry_dt.strftime("%Y-%m-%d")
            }

            memory["trades"].append(trade_record)
            
            # تقليم
            if len(memory["trades"]) > MAX_TRADES_TO_KEEP:
                memory["trades"] = memory["trades"][-MAX_TRADES_TO_KEEP:]
            
            # 🔥 إعادة حساب كامل بدل التحديث اليدوي
            memory = recalculate_stats(memory)
            
            # حفظ
            save_memory(memory)

            # Firebase
            if ENABLE_FIREBASE_BACKUP and FIREBASE_AVAILABLE:
                try:
                    threading.Thread(
                        target=backup_to_firebase,
                        args=(memory,),
                        daemon=True
                    ).start()
                except:
                    pass

            status = "✅" if is_win else "❌"
            logger.info(f"📝 {symbol} {status} صافي: {net_pnl:+.4f}$")

            return True

    except Exception as e:
        logger.error(f"خطأ: {e}")
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
        score = 50 + (win_rate - 0.5) * 100
        
        if stats["consecutive_losses"] >= 3:
            score -= 30
        elif stats["consecutive_losses"] >= 2:
            score -= 15
        
        if stats["total_pnl"] < -1.0:
            score -= 30
        elif stats["total_pnl"] < -0.5:
            score -= 15
        
        score = max(0, min(100, score))
        
        should_trade = True
        reason = f"نجاح {win_rate*100:.1f}% ({stats['wins']}/{total})"
        
        if score < 30:
            should_trade = False
            reason = "أداء ضعيف"
        
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
            return {'score': 20, 'should_trade': False, 'reason': "ساعة سيئة"}
        return {'score': round(win_rate * 100, 2), 'should_trade': True, 'reason': f"نجاح {win_rate*100:.0f}%"}
    except:
        return {'score': 50, 'should_trade': True, 'reason': 'خطأ'}


def get_memory_stats():
    try:
        memory = load_memory()
        total = memory["total_trades"]
        wins = memory["total_wins"]
        win_rate = (wins / total * 100) if total > 0 else 0
        
        yesterday = (datetime.now() - timedelta(days=1)).isoformat()
        recent = [t for t in memory["trades"] if t.get("entry_time", "") >= yesterday]
        
        return {
            'total_trades': total,
            'total_wins': wins,
            'total_losses': memory["total_losses"],
            'win_rate': round(win_rate, 2),
            'total_pnl': memory["total_pnl"],
            'recent_24h_trades': len(recent),
            'recent_24h_wins': len([t for t in recent if t["is_win"]]),
            'recent_24h_pnl': round(sum(t["pnl"] for t in recent), 4),
            'last_updated': memory.get("last_updated", "N/A")
        }
    except:
        return {}


def get_today_pnl():
    try:
        memory = load_memory()
        today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
        today_trades = [t for t in memory["trades"] if t.get("entry_time", "") >= today_start]
        return round(sum(t.get("pnl", 0) for t in today_trades), 4)
    except:
        return 0.0


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
            return True, f"نجاح منخفض: {win_rate*100:.1f}%"
        if stats["consecutive_losses"] >= max_consecutive_losses:
            return True, f"{stats['consecutive_losses']} خسائر"
        if stats["total_pnl"] < -1.0:
            return True, f"خسارة كلية"
        return False, ""
    except:
        return False, ""


def sync_profit_history():
    try:
        memory = load_memory()
        daily, weekly, monthly = {}, {}, {}
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
            daily[date_key] = round(daily.get(date_key, 0) + pnl, 4)
            weekly[week_key] = round(weekly.get(week_key, 0) + pnl, 4)
            monthly[month_key] = round(monthly.get(month_key, 0) + pnl, 4)
        
        with open("profit_history.json", "w", encoding="utf-8") as f:
            json.dump({
                "daily_profits": daily, "weekly_profits": weekly,
                "monthly_profits": monthly,
                "last_sync": datetime.now().isoformat(),
                "total_profit": memory.get("total_pnl", 0),
                "total_trades": memory.get("total_trades", 0)
            }, f, indent=2, ensure_ascii=False)
        
        logger.info("✅ تم مزامنة profit_history.json")
        return True
    except Exception as e:
        logger.error(f"خطأ: {e}")
        return False


# ==================== سكريبت تنظيف ====================

def cleanup_and_recalculate():
    """
    🔥 تشغيل يدوي: إعادة حساب كل الإحصائيات من الصفر
    """
    logger.info("🧹 بدء تنظيف الذاكرة...")
    memory = load_memory()
    old_count = len(memory.get("trades", []))
    memory = recalculate_stats(memory)
    logger.info(f"✅ تم إعادة حساب {old_count} صفقة")
    return memory


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print("🧪 trade_memory v6.0 - تنظيف...")
    cleanup_and_recalculate()
    stats = get_memory_stats()
    print(f"إحصائيات جديدة: {stats}")