#!/usr/bin/env python3
import os
import sys
import time
import threading
import subprocess
from http.server import HTTPServer, BaseHTTPRequestHandler

PORT = int(os.environ.get("PORT", 10000))
STREAM_KEY = os.environ.get("STREAM_KEY", "").strip()
START_TIME = time.time()

class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        uptime = int(time.time() - START_TIME)
        status_msg = "running" if STREAM_KEY else "waiting_for_stream_key"
        response = (
            f'{{"status":"{status_msg}",'
            f'"service":"28E Radio 24/7 Live Stream",'
            f'"uptime_seconds":{uptime},'
            f'"stream_key_configured":{str(bool(STREAM_KEY)).lower()}}}\n'
        )
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(response)))
        self.end_headers()
        self.wfile.write(response.encode("utf-8"))

    def log_message(self, format, *args):
        # Evitar inundar la consola con logs de pings de UptimeRobot
        pass

def stream_worker():
    if not STREAM_KEY:
        print("[28E_STREAM] ⚠️ ATENCIÓN: No has configurado 'STREAM_KEY' en las variables de entorno de Render.", flush=True)
        print("[28E_STREAM] ⚠️ Por favor ve a Render Dashboard > Environment > Add Environment Variable > STREAM_KEY", flush=True)
        return

    rtmp_url = f"rtmp://a.rtmp.youtube.com/live2/{STREAM_KEY}"
    print(f"[28E_STREAM] 🚀 Iniciando emisión continua 1080p hacia YouTube Live...", flush=True)

    cmd = [
        "ffmpeg",
        "-re",
        "-stream_loop", "-1",
        "-i", "videos/16-9_1080p.mp4",
        "-stream_loop", "-1",
        "-f", "concat",
        "-safe", "0",
        "-i", "scripts/radio_playlist.txt",
        "-map", "0:v:0",
        "-map", "1:a:0",
        "-c:v", "copy",
        "-c:a", "aac",
        "-b:a", "192k",
        "-ar", "44100",
        "-f", "flv",
        rtmp_url
    ]

    while True:
        try:
            print("[28E_STREAM] Conectando FFmpeg con servidor RTMP de YouTube...", flush=True)
            proc = subprocess.Popen(cmd)
            proc.wait()
            print(f"[28E_STREAM] Proceso FFmpeg finalizado con código: {proc.returncode}", flush=True)
        except Exception as e:
            print(f"[28E_STREAM] Excepción en stream worker: {e}", flush=True)

        print("[28E_STREAM] Reconectando en 5 segundos...", flush=True)
        time.sleep(5)

if __name__ == "__main__":
    t = threading.Thread(target=stream_worker, daemon=True)
    t.start()

    print(f"[28E_WEB] Servidor HTTP de monitoreo activo en puerto {PORT}", flush=True)
    server = HTTPServer(("0.0.0.0", PORT), HealthHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("[28E_WEB] Deteniendo servidor...", flush=True)
        sys.exit(0)
