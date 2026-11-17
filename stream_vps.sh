#!/usr/bin/env bash

DIR="/opt/radio28e/repo"
cd "$DIR"

: "${STREAM_KEY:?Configura STREAM_KEY en el entorno antes de emitir}"

echo "[INFO] Limpiando procesos previos..."
pkill -9 -f 'chrome|google-chrome|Xvfb|openbox|ffmpeg|http.server' 2>/dev/null || true
rm -f /tmp/.X99-lock /tmp/.X11-unix/X99 2>/dev/null || true
rm -rf /tmp/stream_profile
mkdir -p /tmp/stream_profile /root/.config/google-chrome
touch /tmp/stream_profile/'First Run' /root/.config/google-chrome/'First Run'
sleep 1

echo "[INFO] Iniciando servidor web interno..."
python3 -m http.server 5500 --bind 127.0.0.1 --directory "$DIR" &
sleep 2

echo "[INFO] Configurando audio con PulseAudio (VirtualSink)..."
pulseaudio --kill 2>/dev/null || true
pulseaudio --start --exit-idle-time=-1 2>/dev/null || true
sleep 1
pactl load-module module-null-sink sink_name=VirtualSink rate=44100 channels=2 sink_properties=device.description=VirtualSink || true
pactl set-default-sink VirtualSink || true

echo "[INFO] Iniciando Xvfb display :99 a Full HD 1080p 30Hz..."
Xvfb :99 -screen 0 1920x1080x24 -ac -nolisten tcp +extension GLX +render -noreset &
sleep 1

echo "[INFO] Iniciando gestor de ventanas Openbox..."
DISPLAY=:99 openbox &
sleep 1

echo "[INFO] Iniciando Google Chrome en 1080p con Mesa LLVMpipe..."
LP_NUM_THREADS=2 OMP_NUM_THREADS=2 PULSE_LATENCY_MSEC=400 PULSE_SINK=VirtualSink DISPLAY=:99 google-chrome   --kiosk   --window-size=1920,1080   --window-position=0,0   --disable-infobars   --noerrdialogs   --disable-fre   --no-first-run   --no-default-browser-check   --suppress-message-center-popups   --disable-session-crashed-bubble   --disable-features=Translate,TranslateUI,CalculateNativeWinOcclusion,IntensiveWakeUpThrottling,ThrottleDisplayNoneAndVisibilityHiddenCrossOriginIframes   --disable-background-timer-throttling   --disable-renderer-backgrounding   --disable-backgrounding-occluded-windows   --use-gl=angle   --use-angle=gl   --enable-webgl   --ignore-gpu-blocklist   --autoplay-policy=no-user-gesture-required   --lang=es   --no-sandbox   --user-data-dir=/tmp/stream_profile   http://127.0.0.1:5500/radio-stream.html &

sleep 6
DISPLAY=:99 xdotool mousemove 960 540 click 1; DISPLAY=:99 xdotool mousemove 9999 9999 2>/dev/null || true

# Watchdog en segundo plano para cerrar cualquier popup y mantener el foco activo en 28E
(
  while true; do
    sleep 5
    WID=$(DISPLAY=:99 xdotool search --name 'Terms of Service' 2>/dev/null | head -n 1 || true)
    if [ -n "$WID" ]; then
      DISPLAY=:99 xdotool windowclose "$WID" 2>/dev/null || true
    fi
    WID_28E=$(DISPLAY=:99 xdotool search --name '28E' 2>/dev/null | head -n 1 || true)
    if [ -n "$WID_28E" ]; then
      DISPLAY=:99 xdotool windowactivate "$WID_28E" 2>/dev/null || true
    fi
  done
) &

echo "[INFO] Iniciando transmisión continua a YouTube Live (Full HD 1080p a 30 FPS CBR)..."
while true; do
    ffmpeg -thread_queue_size 1024 -f x11grab -draw_mouse 0 -video_size 1920x1080 -framerate 30 -i :99.0            -thread_queue_size 1024 -f pulse -fragment_size 2048 -i VirtualSink.monitor            -c:v libx264 -preset superfast -tune zerolatency -threads 2 -pix_fmt yuv420p -profile:v high -level 4.1            -r 30 -g 60 -keyint_min 60 -sc_threshold 0            -b:v 4500k -minrate 4500k -maxrate 4500k -bufsize 4500k            -af "aresample=async=1000"            -c:a aac -b:a 192k -ar 44100            -flvflags no_duration_filesize            -f flv "rtmp://a.rtmp.youtube.com/live2/$STREAM_KEY" || true

    echo "[ALERTA] Conexión con YouTube interrumpida. Reconectando en 3 segundos..."
    sleep 3
done
