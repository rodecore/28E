#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STATE_DIR=/opt/radio28e/state
: "${STREAM_KEY:?Configura STREAM_KEY en el entorno del servicio}"
mkdir -p "$STATE_DIR/chrome-hud"
chmod 700 "$STATE_DIR/chrome-hud"
cd "$ROOT_DIR"

children=()
encoder_pid=
cleanup() {
    if [[ -n "$encoder_pid" ]]; then kill "$encoder_pid" 2>/dev/null || true; fi
    for pid in "${children[@]}"; do
        kill "$pid" 2>/dev/null || true
    done
}
trap cleanup EXIT
trap 'exit 0' TERM INT

python3 -m http.server 5500 --bind 127.0.0.1 --directory "$ROOT_DIR" &
http_pid="$!"
children+=("$http_pid")
pulseaudio --start --exit-idle-time=-1
for attempt in {1..20}; do
    if pactl info >/dev/null 2>&1; then break; fi
    sleep 0.5
done
if ! pactl list short sinks | awk '{print $2}' | grep -qx 'Radio28ELive'; then
    pactl load-module module-null-sink sink_name=Radio28ELive rate=44100 channels=2 >/dev/null
fi
pactl set-sink-mute Radio28ELive 0
pactl set-sink-volume Radio28ELive 100%

Xvfb :99 -screen 0 1920x1080x24 -ac -nolisten tcp +extension GLX +render -noreset &
display_pid="$!"
children+=("$display_pid")
sleep 1
DISPLAY=:99 openbox &
children+=("$!")
sleep 1
PULSE_SINK=Radio28ELive PULSE_LATENCY_MSEC=400 DISPLAY=:99 \
LP_NUM_THREADS=2 OMP_NUM_THREADS=2 google-chrome \
    --kiosk --window-size=1920,1080 --window-position=0,0 --force-device-scale-factor=1 \
    --no-first-run --no-default-browser-check --noerrdialogs --no-sandbox \
    --disable-dev-shm-usage --disable-gpu --disable-software-rasterizer \
    --disable-background-timer-throttling --disable-renderer-backgrounding \
    --disable-backgrounding-occluded-windows --autoplay-policy=no-user-gesture-required \
    --disable-features=Translate,TranslateUI,IntensiveWakeUpThrottling \
    --lang=es --user-data-dir="$STATE_DIR/chrome-hud" \
    --remote-debugging-address=127.0.0.1 --remote-debugging-port=19222 \
    'http://127.0.0.1:5500/stream-study/embarcadero/hud.html?stream&emit&auth=optional' &
chrome_pid="$!"
children+=("$chrome_pid")
launcher_pid="$$"
(
    while kill -0 "$chrome_pid" 2>/dev/null &&
          kill -0 "$http_pid" 2>/dev/null &&
          kill -0 "$display_pid" 2>/dev/null; do
        sleep 5
    done
    kill -TERM "$launcher_pid"
) &
children+=("$!")

node scripts/radio-stream-health.cjs
echo '[RADIO] HUD preparado. Calentando la reproducción durante 30 segundos.'
sleep 30
echo '[RADIO] Iniciando la emisión a 1920x1080, 30 fps.'

while kill -0 "$chrome_pid" 2>/dev/null; do
    ffmpeg -hide_banner -loglevel warning -nostdin -nostats \
        -thread_queue_size 1024 -f x11grab -draw_mouse 0 -video_size 1920x1080 -framerate 30 -i :99.0 \
        -thread_queue_size 1024 -f pulse -fragment_size 2048 -i Radio28ELive.monitor \
        -c:v libx264 -preset ultrafast -tune zerolatency -threads 2 \
        -pix_fmt yuv420p -profile:v high -level 4.1 -r 30 -g 60 -keyint_min 60 -sc_threshold 0 \
        -b:v 4500k -minrate 4500k -maxrate 4500k -bufsize 4500k \
        -af 'aresample=async=1000' -c:a aac -b:a 192k -ar 44100 \
        -progress pipe:1 -flvflags no_duration_filesize \
        -f flv "rtmp://a.rtmp.youtube.com/live2/$STREAM_KEY" &
    encoder_pid="$!"
    wait "$encoder_pid" || true
    encoder_pid=
    echo '[RADIO] Reconectando la salida de YouTube en tres segundos.'
    sleep 3
done
exit 1
