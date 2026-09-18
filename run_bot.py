# ==================================================
# 📁 ملف: run_bot.py
# 🔧 التعديلات:
# 1. تشغيل main_enhanced.py مباشرة
# 2. معالجة أفضل للأخطاء
# 3. إزالة input() في النهاية (كان بيعلّق التشغيل على سيرفر بدون طرفية تفاعلية مثل Railway)
# ==================================================

import sys
import os
import time

sys.path.append(os.path.dirname(os.path.abspath(__file__)))


def main():
    try:
        print("🚀 بدء تشغيل البوت...")
        print("⏳ جاري التحميل...")
        print("📁 النظام: الإصدار المحسن (Enhanced)")

        from main_enhanced import main as bot_main
        bot_main()

    except IndentationError as e:
        print(f"❌ خطأ في المسافات في الملف: {e}")
    except SyntaxError as e:
        print(f"❌ خطأ في الصيغة: {e}")
    except ImportError as e:
        print(f"❌ خطأ في الاستيراد: {e}")
        print("🔧 تأكد من تثبيت جميع المكتبات المطلوبة: pip install -r requirements.txt")
    except KeyboardInterrupt:
        print("\n⏹️ تم إيقاف البوت بواسطة المستخدم")
    except Exception as e:
        print(f"❌ خطأ غير متوقع: {e}")
        print("🔧 جاري إعادة التشغيل تلقائياً خلال 10 ثواني...")
        time.sleep(10)
        main()


if __name__ == "__main__":
    main()
    # ملاحظة: تم إزالة input() المتبقي من النسخة القديمة عمدًا،
    # لأن السيرفر (زي Railway) بيشغّل الملف بدون طرفية تفاعلية،
    # وأي استدعاء لـ input() هيفضل عالق للأبد.
