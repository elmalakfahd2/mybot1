# ==================================================
# 📁 ملف: health_server.py - v5.4
# 🔧 الوصف:
#    - خادم HTTP بسيط لـ Railway Health Check
#    - يجعل Railway يعرف أن البوت يعمل
#    - يمنع إعادة التشغيل كل 10 دقائق
# 📅 التاريخ: 2026-09-25
# ==================================================

import http.server
import socketserver
import threading
import logging
import os

logger = logging.getLogger("health_server")


class HealthHandler(http.server.BaseHTTPRequestHandler):
    """معالج HTTP بسيط"""

    def do_GET(self):
        try:
            if self.path in ('/', '/health'):
                self.send_response(200)
                self.send_header('Content-Type', 'text/plain')
                self.send_header('Cache-Control', 'no-cache')
                self.end_headers()
                self.wfile.write(b'OK')

            elif self.path == '/status':
                import trade_memory
                try:
                    mem = trade_memory.get_memory_stats()
                    status = (
                        f"Trades: {mem.get('total_trades', 0)}\n"
                        f"Win Rate: {mem.get('win_rate', 0)}%\n"
                        f"Total PnL: {mem.get('total_pnl', 0)}\n"
                    )
                except:
                    status = "Running\n"

                self.send_response(200)
                self.send_header('Content-Type', 'text/plain')
                self.end_headers()
                self.wfile.write(status.encode())

            else:
                self.send_response(404)
                self.end_headers()

        except Exception as e:
            logger.error(f"خطأ في Health Handler: {e}")

    def log_message(self, format, *args):
        # لا نطبع logs لتوفير الموارد
        pass


def start_health_server():
    """بدء خادم Health Check"""
    try:
        port = int(os.environ.get("PORT", 8080))

        # السماح بإعادة استخدام المنفذ
        socketserver.TCPServer.allow_reuse_address = True

        with socketserver.TCPServer(("0.0.0.0", port), HealthHandler) as httpd:
            logger.info(f"✅ Health Check server on port {port}")
            httpd.serve_forever()

    except Exception as e:
        logger.error(f"❌ فشل بدء Health server: {e}")


def run_in_background():
    """تشغيل الخادم في خيط منفصل"""
    try:
        thread = threading.Thread(
            target=start_health_server,
            daemon=True,
            name="HealthServer"
        )
        thread.start()
        logger.info("✅ تم تشغيل Health Check في الخلفية")
        return True
    except Exception as e:
        logger.error(f"❌ فشل: {e}")
        return False


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    start_health_server()