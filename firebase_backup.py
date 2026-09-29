# ==================================================
# 📁 ملف: firebase_backup.py - الإصدار v5.7
# 🔧 التعديلات v5.7:
#    - 🔥 save_doc / load_doc: حفظ أي حالة (المخاطر، الصفقات المفتوحة، قواعد التعلم)
#      حتى لا تضيع عند إعادة تشغيل Railway
# 🔧 التعديلات v5.5.1:
#    - 🔥 استخدام getattr (لا يفشل الاستيراد أبداً)
#    - 🔥 معالجة آمنة للمتغيرات المفقودة
# 📅 التاريخ: 2026-09-25
# ==================================================

import logging
import json
import os
import threading
import time
from datetime import datetime

logger = logging.getLogger("firebase_backup")

# 🔥 Firebase Admin SDK
try:
    import firebase_admin
    from firebase_admin import credentials, firestore
    FIREBASE_AVAILABLE = True
except ImportError:
    FIREBASE_AVAILABLE = False
    logger.warning("⚠️ firebase-admin غير مثبت")

# 🔥 إعدادات آمنة (getattr لا يفشل أبداً)
try:
    import config

    FIREBASE_KEY_JSON = getattr(config, 'FIREBASE_KEY_JSON', '')
    FIREBASE_PROJECT_ID = getattr(config, 'FIREBASE_PROJECT_ID', 'mybot1-backup-91f59')
    ENABLE_FIREBASE_BACKUP = getattr(config, 'ENABLE_FIREBASE_BACKUP', True)
    FIREBASE_BACKUP_INTERVAL = getattr(config, 'FIREBASE_BACKUP_INTERVAL', 30)
    MEMORY_FILE = getattr(config, 'MEMORY_FILE', 'trade_memory.json')

except ImportError as e:
    logger.error(f"❌ فشل استيراد config: {e}")
    FIREBASE_KEY_JSON = ""
    FIREBASE_PROJECT_ID = "mybot1-backup-91f59"
    ENABLE_FIREBASE_BACKUP = True
    FIREBASE_BACKUP_INTERVAL = 30
    MEMORY_FILE = "trade_memory.json"

# 🔥 المعاملات
COLLECTION_NAME = "bot_data"
DOCUMENT_NAME = "trade_memory"

# 🔥 حالة داخلية
_db = None
_initialized = False
_backup_thread_running = False


# ==================== التهيئة ====================

def initialize_firebase():
    """تهيئة Firebase"""
    global _db, _initialized

    if _initialized:
        return True

    if not FIREBASE_AVAILABLE:
        logger.error("❌ firebase-admin غير متاح")
        return False

    if not FIREBASE_KEY_JSON:
        logger.warning("⚠️ FIREBASE_KEY غير موجود")
        return False

    try:
        # تحليل JSON
        try:
            cred_dict = json.loads(FIREBASE_KEY_JSON)
        except json.JSONDecodeError as e:
            logger.error(f"❌ FIREBASE_KEY ليس JSON صالح: {e}")
            return False

        # إنشاء الاعتماد
        cred = credentials.Certificate(cred_dict)

        # تهيئة التطبيق
        if not firebase_admin._apps:
            firebase_admin.initialize_app(cred)
        else:
            logger.info("ℹ️ Firebase مهيأ مسبقاً")

        # إنشاء العميل
        _db = firestore.client()
        _initialized = True

        logger.info(f"✅ Firebase متصل: {FIREBASE_PROJECT_ID}")
        return True

    except Exception as e:
        logger.error(f"❌ فشل تهيئة Firebase: {e}")
        import traceback
        traceback.print_exc()
        return False


def is_available():
    """التحقق من توفر Firebase"""
    return _initialized and _db is not None


# ==================== الحفظ والتحميل ====================

def save_to_firebase(memory_data):
    """حفظ الذاكرة في Firebase"""
    try:
        if not is_available():
            return False

        # إضافة timestamp
        memory_data["last_sync_firebase"] = datetime.now().isoformat()

        # المرجع
        doc_ref = _db.collection(COLLECTION_NAME).document(DOCUMENT_NAME)

        # حفظ
        doc_ref.set(memory_data)

        logger.info("💾 تم الحفظ في Firebase")
        return True

    except Exception as e:
        logger.error(f"❌ فشل الحفظ في Firebase: {e}")
        return False


def load_from_firebase():
    """تحميل الذاكرة من Firebase"""
    try:
        if not is_available():
            return None

        doc_ref = _db.collection(COLLECTION_NAME).document(DOCUMENT_NAME)
        doc = doc_ref.get()

        if doc.exists:
            data = doc.to_dict()
            logger.info(f"✅ تم التحميل من Firebase")
            return data
        else:
            logger.info("ℹ️ لا توجد بيانات في Firebase")
            return None

    except Exception as e:
        logger.error(f"❌ فشل التحميل من Firebase: {e}")
        return None


# ==================== 🔥 مستندات عامة (v5.7) ====================

def save_doc(name, data):
    """حفظ مستند باسم مخصص (dict) في Firebase"""
    try:
        if not is_available():
            return False
        payload = dict(data)
        payload["_saved_at"] = datetime.now().isoformat()
        _db.collection(COLLECTION_NAME).document(name).set(payload)
        return True
    except Exception as e:
        logger.error(f"❌ فشل حفظ المستند {name}: {e}")
        return False


def load_doc(name):
    """تحميل مستند باسم مخصص من Firebase (أو None)"""
    try:
        if not is_available():
            return None
        doc = _db.collection(COLLECTION_NAME).document(name).get()
        if doc.exists:
            return doc.to_dict()
        return None
    except Exception as e:
        logger.error(f"❌ فشل تحميل المستند {name}: {e}")
        return None


# ==================== Backup محلي ====================

def load_local_memory():
    """تحميل الذاكرة المحلية"""
    try:
        if not os.path.exists(MEMORY_FILE):
            return None

        with open(MEMORY_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return None


def save_local_memory(memory_data):
    """حفظ الذاكرة محلياً"""
    try:
        with open(MEMORY_FILE, "w", encoding="utf-8") as f:
            json.dump(memory_data, f, indent=2, ensure_ascii=False)
        return True
    except:
        return False


def sync_from_firebase_on_startup():
    """مزامنة عند بدء البوت"""
    try:
        if not is_available():
            return False

        # 1. تحميل من Firebase
        firebase_data = load_from_firebase()

        # 2. تحميل محلي
        local_data = load_local_memory()

        # 3. قرار
        if firebase_data:
            fb_trades = len(firebase_data.get("trades", []))
            local_trades = len(local_data.get("trades", [])) if local_data else 0

            if fb_trades >= local_trades:
                save_local_memory(firebase_data)
                logger.info(f"✅ مزامنة من Firebase: {fb_trades} صفقة")
                return True
            else:
                logger.info(f"⚠️ محلي أحدث ({local_trades} vs {fb_trades})")
                save_to_firebase(local_data)
                return True

        elif local_data:
            logger.info("📤 رفع البيانات المحلية إلى Firebase")
            save_to_firebase(local_data)
            return True

        return False

    except Exception as e:
        logger.error(f"❌ فشل المزامنة: {e}")
        return False


# ==================== Backup الدوري ====================

def backup_loop():
    """حفظ دوري كل X دقيقة"""
    global _backup_thread_running

    if not ENABLE_FIREBASE_BACKUP:
        logger.info("ℹ️ Firebase Backup معطل")
        return

    if not is_available():
        logger.warning("⚠️ Firebase غير متاح - Backup معطل")
        return

    _backup_thread_running = True
    logger.info(f"💾 بدء الحفظ الدوري في Firebase (كل {FIREBASE_BACKUP_INTERVAL} دقيقة)")

    # انتظار أولي
    time.sleep(60)

    while _backup_thread_running:
        try:
            time.sleep(FIREBASE_BACKUP_INTERVAL * 60)

            if _backup_thread_running:
                local_data = load_local_memory()
                if local_data:
                    save_to_firebase(local_data)

        except Exception as e:
            logger.error(f"خطأ في الحفظ الدوري: {e}")
            time.sleep(120)


def start_auto_backup():
    """بدء الحفظ التلقائي"""
    try:
        if not ENABLE_FIREBASE_BACKUP:
            logger.info("ℹ️ Firebase Backup معطل")
            return False

        if not is_available():
            logger.warning("⚠️ Firebase غير متاح")
            return False

        thread = threading.Thread(
            target=backup_loop,
            daemon=True,
            name="FirebaseBackup"
        )
        thread.start()
        logger.info("✅ تم تشغيل Firebase Backup")
        return True

    except Exception as e:
        logger.error(f"❌ فشل: {e}")
        return False


def stop_auto_backup():
    """إيقاف الحفظ التلقائي"""
    global _backup_thread_running
    _backup_thread_running = False
    logger.info("🛑 إيقاف Firebase Backup")


# ==================== API للاستخدام الخارجي ====================

def quick_save(memory_data):
    """حفظ سريع (بدون خيط)"""
    try:
        if not is_available():
            return False
        return save_to_firebase(memory_data)
    except:
        return False


def get_status():
    """حالة Firebase Backup"""
    return {
        'available': FIREBASE_AVAILABLE,
        'initialized': _initialized,
        'enabled': ENABLE_FIREBASE_BACKUP,
        'project_id': FIREBASE_PROJECT_ID,
        'interval': FIREBASE_BACKUP_INTERVAL,
        'thread_running': _backup_thread_running,
        'key_length': len(FIREBASE_KEY_JSON) if FIREBASE_KEY_JSON else 0,
        'memory_file': MEMORY_FILE,
    }


# ==================== اختبار ====================

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print("🧪 اختبار Firebase Backup...")
    print(get_status())

    if initialize_firebase():
        print("✅ Firebase جاهز")

        test_data = {
            "trades": [],
            "total_trades": 0,
            "test": True,
            "timestamp": datetime.now().isoformat()
        }
        save_to_firebase(test_data)

        loaded = load_from_firebase()
        print(f"تم التحميل: {loaded}")
    else:
        print("❌ فشل التهيئة")