# ==================================================
# 📁 ملف: trade_memory.py - ذاكرة الصفقات الذكية
# 🔧 الوصف:
#    - حفظ كل صفقة ونتيجتها
#    - تحليل أداء العملات
#    - منع تكرار الأخطاء
#    - إحصائيات شاملة
# 📅 التاريخ: 2024-01-15
# ==================================================

import json
import os
import logging
from datetime import datetime, timedelta
from threading import Lock

logger = logging.getLogger("trade_memory")

MEMORY_FILE = "trade_memory.json"
_lock = Lock()


def _ensure_memory_file():
    """التأكد من وجود الملف"""
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
    """تحميل الذاكرة"""
    try:
        _ensure_memory_file()
        with open(MEMORY_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"خطأ في تحميل الذاكرة: {e}")
        return {
            "trades": [],
            "symbol_stats": {},
            "hourly_stats": {},
            "condition_stats": {},
            "total_trades": 0,
            "total_wins": 0,
            "total_losses": 0,
            "total_pnl": 0.0
        }


def save_memory(data):
    """حفظ الذاكرة"""
    try:
        data["last_updated"] = datetime.now().isoformat()
        with open(MEMORY_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        return True
    except Exception as e:
        logger.error(f"خطأ في حفظ الذاكرة: {e}")
        return False


def record_trade(symbol, direction, entry_price, exit_price, 
                 quantity, pnl, confidence, timeframe_alignment,
                 volume_ratio, groq_recommendation, groq_confidence,
                 score_details=None, exit_reason="unknown"):
    """
    تسجيل صفقة مكتملة
    
    Args:
        symbol: العملة
        direction: BUY/SELL
        entry_price: سعر الدخول
        exit_price: سعر الخروج
        quantity: الكمية
        pnl: الربح/الخسارة
        confidence: ثقة النظام
        timeframe_alignment: ترابط الفريمات
        volume_ratio: نسبة الحجم
        groq_recommendation: توصية Groq
        groq_confidence: ثقة Groq
        score_details: تفاصيل النقاط
        exit_reason: TP/SL/Manual/Trailing
    """
    try:
        with _lock:
            memory = load_memory()
            
            trade_record = {
                "id": len(memory["trades"]) + 1,
                "symbol": symbol,
                "direction": direction,
                "entry_price": entry_price,
                "exit_price": exit_price,
                "quantity": quantity,
                "pnl": round(pnl, 4),
                "pnl_percent": round((pnl / (entry_price * quantity)) * 100, 4) if entry_price * quantity > 0 else 0,
                "is_win": pnl > 0,
                "confidence": confidence,
                "timeframe_alignment": timeframe_alignment,
                "volume_ratio": volume_ratio,
                "groq_recommendation": groq_recommendation,
                "groq_confidence": groq_confidence,
                "score_details": score_details or {},
                "exit_reason": exit_reason,
                "entry_time": datetime.now().isoformat(),
                "hour": datetime.now().hour,
                "day_of_week": datetime.now().weekday(),
                "date": datetime.now().strftime("%Y-%m-%d")
            }
            
            memory["trades"].append(trade_record)
            
            # تحديث الإحصائيات
            memory["total_trades"] += 1
            if pnl > 0:
                memory["total_wins"] += 1
            else:
                memory["total_losses"] += 1
            memory["total_pnl"] = round(memory["total_pnl"] + pnl, 4)
            
            # تحديث إحصائيات العملة
            if symbol not in memory["symbol_stats"]:
                memory["symbol_stats"][symbol] = {
                    "wins": 0,
                    "losses": 0,
                    "total_pnl": 0.0,
                    "last_trade": None,
                    "consecutive_losses": 0,
                    "avg_confidence": 0,
                    "avg_pnl": 0
                }
            
            stats = memory["symbol_stats"][symbol]
            stats["wins" if pnl > 0 else "losses"] += 1
            stats["total_pnl"] = round(stats["total_pnl"] + pnl, 4)
            stats["last_trade"] = datetime.now().isoformat()
            
            if pnl < 0:
                stats["consecutive_losses"] += 1
            else:
                stats["consecutive_losses"] = 0
            
            total = stats["wins"] + stats["losses"]
            if total > 0:
                stats["avg_confidence"] = round(
                    (stats["avg_confidence"] * (total - 1) + confidence) / total, 2
                )
                stats["avg_pnl"] = round(stats["total_pnl"] / total, 4)
            
            # تحديث إحصائيات الساعة
            hour_key = str(datetime.now().hour)
            if hour_key not in memory["hourly_stats"]:
                memory["hourly_stats"][hour_key] = {
                    "wins": 0,
                    "losses": 0,
                    "total_pnl": 0.0
                }
            
            hour_stats = memory["hourly_stats"][hour_key]
            hour_stats["wins" if pnl > 0 else "losses"] += 1
            hour_stats["total_pnl"] = round(hour_stats["total_pnl"] + pnl, 4)
            
            save_memory(memory)
            
            logger.info(f"📝 تم تسجيل صفقة: {symbol} {'✅' if pnl > 0 else '❌'} {pnl:+.4f}")
            
            return True
            
    except Exception as e:
        logger.error(f"خطأ في تسجيل الصفقة: {e}")
        return False


def get_symbol_score(symbol):
    """
    حساب نقاط الثقة للعملة بناءً على تاريخها
    
    Returns:
        {
            'score': 0-100,
            'should_trade': bool,
            'reason': str,
            'stats': dict
        }
    """
    try:
        memory = load_memory()
        
        if symbol not in memory["symbol_stats"]:
            return {
                'score': 50,
                'should_trade': True,
                'reason': 'عملة جديدة - لا يوجد تاريخ',
                'stats': {}
            }
        
        stats = memory["symbol_stats"][symbol]
        total = stats["wins"] + stats["losses"]
        
        if total == 0:
            return {
                'score': 50,
                'should_trade': True,
                'reason': 'لا يوجد تاريخ كافٍ',
                'stats': stats
            }
        
        win_rate = stats["wins"] / total
        
        # حساب النقاط
        score = 50
        score += (win_rate - 0.5) * 100  # -50 إلى +50
        
        # عقوبة الخسائر المتتالية
        if stats["consecutive_losses"] >= 3:
            score -= 30
        elif stats["consecutive_losses"] >= 2:
            score -= 15
        
        # مكافأة الخسائر المتتالية المنخفضة
        if win_rate >= 0.7 and total >= 5:
            score += 20
        elif win_rate >= 0.6 and total >= 3:
            score += 10
        
        score = max(0, min(100, score))
        
        # قرار التداول
        should_trade = True
        reason = f"نسبة نجاح: {win_rate*100:.1f}% ({stats['wins']}/{total})"
        
        if score < 30:
            should_trade = False
            reason = f"⚠️ أداء ضعيف - نسبة نجاح: {win_rate*100:.1f}%"
        elif stats["consecutive_losses"] >= 3:
            should_trade = False
            reason = f"⚠️ {stats['consecutive_losses']} خسائر متتالية"
        
        return {
            'score': round(score, 2),
            'should_trade': should_trade,
            'reason': reason,
            'win_rate': round(win_rate * 100, 2),
            'total_trades': total,
            'consecutive_losses': stats["consecutive_losses"],
            'stats': stats
        }
        
    except Exception as e:
        logger.error(f"خطأ في حساب نقاط العملة: {e}")
        return {'score': 50, 'should_trade': True, 'reason': 'خطأ', 'stats': {}}


def get_hour_score(hour=None):
    """حساب نقاط الساعة الحالية"""
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
            return {
                'score': 20,
                'should_trade': False,
                'reason': f"⚠️ ساعة سيئة: {win_rate*100:.0f}% نجاح",
                'win_rate': round(win_rate * 100, 2)
            }
        
        return {
            'score': round(win_rate * 100, 2),
            'should_trade': True,
            'reason': f"نسبة نجاح الساعة: {win_rate*100:.0f}%",
            'win_rate': round(win_rate * 100, 2)
        }
        
    except Exception as e:
        logger.error(f"خطأ: {e}")
        return {'score': 50, 'should_trade': True, 'reason': 'خطأ'}


def get_best_symbols(min_trades=3, top_n=10):
    """الحصول على أفضل العملات"""
    try:
        memory = load_memory()
        
        symbols_with_stats = []
        for symbol, stats in memory["symbol_stats"].items():
            total = stats["wins"] + stats["losses"]
            if total >= min_trades:
                win_rate = stats["wins"] / total
                symbols_with_stats.append({
                    'symbol': symbol,
                    'win_rate': round(win_rate * 100, 2),
                    'total_pnl': stats["total_pnl"],
                    'total_trades': total
                })
        
        symbols_with_stats.sort(key=lambda x: (x['win_rate'], x['total_pnl']), reverse=True)
        return symbols_with_stats[:top_n]
        
    except Exception as e:
        logger.error(f"خطأ: {e}")
        return []


def get_worst_symbols(min_trades=3, bottom_n=10):
    """الحصول على أسوأ العملات"""
    try:
        memory = load_memory()
        
        symbols_with_stats = []
        for symbol, stats in memory["symbol_stats"].items():
            total = stats["wins"] + stats["losses"]
            if total >= min_trades:
                win_rate = stats["wins"] / total
                symbols_with_stats.append({
                    'symbol': symbol,
                    'win_rate': round(win_rate * 100, 2),
                    'total_pnl': stats["total_pnl"],
                    'total_trades': total
                })
        
        symbols_with_stats.sort(key=lambda x: (x['win_rate'], x['total_pnl']))
        return symbols_with_stats[:bottom_n]
        
    except Exception as e:
        logger.error(f"خطأ: {e}")
        return []


def get_memory_stats():
    """إحصائيات شاملة"""
    try:
        memory = load_memory()
        
        total = memory["total_trades"]
        wins = memory["total_wins"]
        losses = memory["total_losses"]
        
        win_rate = (wins / total * 100) if total > 0 else 0
        
        # آخر 24 ساعة
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
    """🔥 صافي الربح/الخسارة لليوم الحالي (منذ منتصف الليل) - لقاطع دائرة الخسارة اليومية"""
    try:
        memory = load_memory()
        today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
        today_trades = [t for t in memory["trades"] if t.get("entry_time", "") >= today_start]
        return sum(t.get("pnl", 0) for t in today_trades)
    except Exception as e:
        logger.error(f"خطأ في حساب أرباح اليوم: {e}")
        return 0.0


def clear_old_trades(days=30):
    """حذف الصفقات القديمة"""
    try:
        with _lock:
            memory = load_memory()
            cutoff = (datetime.now() - timedelta(days=days)).isoformat()
            
            old_count = len(memory["trades"])
            memory["trades"] = [t for t in memory["trades"] if t.get("entry_time", "") >= cutoff]
            new_count = len(memory["trades"])
            
            save_memory(memory)
            
            logger.info(f"🧹 تم حذف {old_count - new_count} صفقة قديمة")
            return old_count - new_count
            
    except Exception as e:
        logger.error(f"خطأ: {e}")
        return 0


def get_symbol_history(symbol, limit=10):
    """تاريخ صفقات عملة معينة"""
    try:
        memory = load_memory()
        trades = [t for t in memory["trades"] if t["symbol"] == symbol]
        return trades[-limit:]
    except:
        return []


def is_symbol_blacklisted(symbol, min_trades=5, max_win_rate=0.25, max_consecutive_losses=3):
    """التحقق من أن العملة محظورة"""
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
        
        return False, ""
        
    except Exception as e:
        logger.error(f"خطأ: {e}")
        return False, ""


if __name__ == "__main__":
    print("🧪 اختبار ذاكرة الصفقات...")
    
    # اختبار
    record_trade(
        symbol="BTCUSDT",
        direction="BUY",
        entry_price=45000,
        exit_price=45225,
        quantity=0.001,
        pnl=0.225,
        confidence=75,
        timeframe_alignment=7.5,
        volume_ratio=1.8,
        groq_recommendation="تأكيد",
        groq_confidence=75,
        exit_reason="TP1"
    )
    
    print("\n📊 إحصائيات:")
    stats = get_memory_stats()
    for k, v in stats.items():
        print(f"  {k}: {v}")
    
    print("\n🎯 نقاط BTCUSDT:")
    score = get_symbol_score("BTCUSDT")
    print(f"  {score}")