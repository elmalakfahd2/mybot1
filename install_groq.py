# ==================================================
# 📁 ملف: install_dependencies.py - تثبيت التبعيات المطلوبة تلقائياً
# 📅 التاريخ: 2024-01-15
# ==================================================

import subprocess
import sys
import os

def install_package(package):
    """تثبيت حزمة باستخدام pip"""
    try:
        subprocess.check_call([sys.executable, "-m", "pip", "install", package])
        print(f"✅ تم تثبيت {package} بنجاح")
        return True
    except subprocess.CalledProcessError as e:
        print(f"❌ فشل تثبيت {package}: {e}")
        return False

def main():
    """الدالة الرئيسية لتثبيت التبعيات"""
    print("🚀 بدء تثبيت التبعيات المطلوبة...")
    
    # قائمة الحزم المطلوبة - محدثة للإصدارات الجديدة
    packages = [
        "groq==0.3.0",
        "python-telegram-bot==20.7",  # 🔥 تحديث الإصدار
        "python-binance==1.0.19",
        "requests>=2.31.0",
        "pandas>=2.0.3", 
        "numpy>=1.24.3",
        "schedule>=1.2.0",
        "python-dotenv>=1.0.0"
    ]
    
    success_count = 0
    failed_count = 0
    
    for package in packages:
        if install_package(package):
            success_count += 1
        else:
            failed_count += 1
    
    print(f"\n📊 نتائج التثبيت:")
    print(f"✅ نجح: {success_count} حزمة")
    print(f"❌ فشل: {failed_count} حزمة")
    
    if failed_count == 0:
        print("🎉 تم تثبيت جميع التبعيات بنجاح!")
        print("🔧 يمكنك الآن تشغيل البوت باستخدام: python main_enhanced.py")
    else:
        print("⚠️ هناك بعض الحزم التي فشل تثبيتها. يرجى تثبيتها يدوياً.")
        print("🔧 استخدم: pip install package_name")

if __name__ == "__main__":
    main()