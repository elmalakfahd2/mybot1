# ==================================================
# 📁 ملف: log_capture.py - حفظ سجل البوت في ملف + استخراج أجزاء منه
# 🔧 الوصف:
#    - يضيف RotatingFileHandler للـ root logger (آمن للاستدعاء المتكرر)
#    - يتيح إرسال آخر ساعة/3 ساعات/6 ساعات/الأخطاء فقط عبر Telegram
#    - يخفي المفاتيح السرية من النص قبل إرساله
# ⚠️ ملاحظة: قرص Railway مؤقت؛ السجل يُمسح عند إعادة النشر (يبقى سجل النسخة الحالية)
# 📅 التاريخ: 2026-10-01
# ==================================================

import io
import os
import re
import logging
from logging.handlers import RotatingFileHandler
from datetime import datetime, timedelta

LOG_FILE = "bot.log"
MAX_BYTES = 4 * 1024 * 1024     # 4MB لكل ملف
BACKUP_COUNT = 3                # الحد الأقصى ~16MB (أقل من حد Telegram 50MB)
FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"

_TS = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}),\d{3} - ")
_LEVEL = re.compile(r" - (WARNING|ERROR|CRITICAL) - ")
_installed = False


def setup():
    """إضافة معالج الملف (مرة واحدة)"""
    global _installed
    if _installed:
        return True
    try:
        root = logging.getLogger()
        for h in root.handlers:
            if isinstance(h, RotatingFileHandler) and getattr(h, "baseFilename", "").endswith(LOG_FILE):
                _installed = True
                return True

        handler = RotatingFileHandler(
            LOG_FILE, maxBytes=MAX_BYTES, backupCount=BACKUP_COUNT, encoding="utf-8"
        )
        handler.setFormatter(logging.Formatter(FORMAT))
        handler.setLevel(logging.INFO)
        root.addHandler(handler)
        if root.level == logging.NOTSET or root.level > logging.INFO:
            root.setLevel(logging.INFO)
        _installed = True
        return True
    except Exception as e:
        print(f"⚠️ تعذر تفعيل حفظ السجل: {e}")
        return False


def _all_log_files():
    """الملفات من الأقدم إلى الأحدث"""
    files = []
    for i in range(BACKUP_COUNT, 0, -1):
        f = f"{LOG_FILE}.{i}"
        if os.path.exists(f):
            files.append(f)
    if os.path.exists(LOG_FILE):
        files.append(LOG_FILE)
    return files


def _secrets():
    vals = []
    try:
        import config
        for name in ("BINANCE_API_KEY", "BINANCE_API_SECRET", "TELEGRAM_TOKEN",
                     "GROQ_API_KEY", "GEMINI_API_KEY", "HUGGINGFACE_API_KEY",
                     "OPENROUTER_API_KEY", "SAMBANOVA_API_KEY", "FIREBASE_KEY_JSON", "GITHUB_TOKEN"):
            v = getattr(config, name, "")
            if v and len(str(v)) >= 8:
                vals.append(str(v))
    except Exception:
        pass
    return vals


def _redact(text):
    for v in _secrets():
        text = text.replace(v, "***")
    return text


def get_excerpt(hours=None, errors_only=False, max_lines=None):
    """
    يرجع (bytes, عدد_الأسطر, أول_وقت, آخر_وقت)
    hours=None → كل المتاح. errors_only → WARNING وما فوق (مع سطور الـ traceback التابعة لها).
    """
    cutoff = None
    if hours:
        cutoff = datetime.now() - timedelta(hours=hours)

    out = []
    first_ts = last_ts = None

    for path in _all_log_files():
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                keep_block = cutoff is None   # هل الكتلة الحالية (سطر + تتمته) مقبولة
                level_ok = True
                for line in f:
                    m = _TS.match(line)
                    if m:
                        try:
                            ts = datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S")
                        except ValueError:
                            ts = None
                        keep_block = (cutoff is None) or (ts is not None and ts >= cutoff)
                        level_ok = (not errors_only) or bool(_LEVEL.search(line))
                        if keep_block and level_ok and ts:
                            first_ts = ts if first_ts is None else min(first_ts, ts)
                            last_ts = ts if last_ts is None else max(last_ts, ts)
                    if keep_block and level_ok:
                        out.append(line)
        except Exception:
            continue

    # إزالة التكرار المتتالي للسطر نفسه إن وجد
    cleaned = []
    prev_line = None
    for line in out:
        if line == prev_line:
            continue
        cleaned.append(line)
        prev_line = line
    out = cleaned

    if max_lines and len(out) > max_lines:
        out = out[-max_lines:]

    text = _redact("".join(out))
    return text.encode("utf-8"), len(out), first_ts, last_ts


def get_info():
    files = _all_log_files()
    size = sum(os.path.getsize(f) for f in files if os.path.exists(f))
    return {"files": len(files), "size_mb": round(size / 1024 / 1024, 2)}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    setup()
    logging.getLogger("test").info("hello")
    print(get_info())
