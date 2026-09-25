# ==================================================
# 📁 ملف: run_bot.py - v5.4
# 🔧 التعديلات v5.4:
#    - إزالة إعادة التشغيل التلقائي
#    - الاعتماد على Railway
#    - بسيط وآمن
# 📅 التاريخ: 2026-09-25
# ==================================================

import sys
import os
import time
import traceback

sys.path.append(os.path.dirname(os.path.abspath(__file__)))


def main():
    try:
        print("🚀 بدء تشغيل البوت...")
        print("⏳ جاري التحميل...")
        print("📁 النظام: الإصدار المحسن (Enhanced)")

        from main_enhanced import main as bot_main
        bot_main()

    except IndentationError as e:
        print(f"❌ خطأ في المسافات: {e}")
        traceback.print_exc()
        sys.exit(1)
    except SyntaxError as e:
        print(f"❌ خطأ في الصيغة: {e}")
        traceback.print_exc()
        sys.exit(1)
    except ImportError as e:
        print(f"❌ خطأ في الاستيراد: {e}")
        print("🔧 تأكد من تثبيت المكتبات: pip install -r requirements.txt")
        traceback.print_exc()
        sys.exit(1)
    except KeyboardInterrupt:
        print("\n⏹️ تم إيقاف البوت بواسطة المستخدم")
        sys.exit(0)
    except Exception as e:
        print(f"❌ خطأ غير متوقع: {e}")
        traceback.print_exc()
        # 🔥 لا إعادة تشغيل تلقائي — نترك Railway يديرها
        sys.exit(1)


if __name__ == "__main__":
    main()