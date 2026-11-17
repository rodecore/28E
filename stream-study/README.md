# Yaire · Noche de estudio para 28E

Escena procedural WebGL derivada del motor de `dclf.html`, sin inicializar el juego, partidas, Firebase ni audio. Cámara fija, habitación nueva con ventana izquierda, escritorio central y cama derecha. Conserva la paleta y geometría del avatar de Yaire y añade postura sentada, escritura, respiración, mirada, cambio de página, taza y lluvia.

## Producción

- `scene.html`: fuente editable y vista WebGL; `?capture=1` detiene el reloj para captura determinista. `window.__studyCinema.seek(segundos)` permite inspeccionar poses.
- `render.cjs`: captura 3600 fotogramas a tiempos exactos (render interno 1280 × 720, escalado Lanczos) y genera un bucle H.264 1920 × 1080, 30 fps, 120 segundos, sin audio. Necesita Node, Playwright, Chrome y FFmpeg. Configurar `PLAYWRIGHT_MODULE` y `CHROME_BIN` en otra máquina.
- `verify.cjs`: comprueba ocho poses, errores WebGL y coincidencia de píxeles entre t=0 y t=120.
- `player.html`: reproducción de `yaire-study-vps.mp4` (1280 × 720 a 30 fps) en el lienzo 1080p del stream; máster 1080p conservado aparte. Reproducción del MP4, sin WebGL ni construcción de geometría durante la emisión. El navegador mantiene solo un vídeo con `autoplay`, `muted`, `loop` y `playsinline`.

## VPS

Copiar `player.html`, `preview.png` y `yaire-study-vps.mp4` a `/opt/radio28e/repo/stream-study/`.

Integración: cambiar únicamente el `src` del iframe de fondo en `radio-stream.html` a `stream-study/player.html`. La música y sus metadatos continúan en el documento principal. Hacer copia del HTML antes del cambio. No ejecutar `scene.html` como fondo del servidor: es la fuente de autoría, no el modo de reproducción recomendado.

Abrir el reproductor por separado y medir los fotogramas descartados con `window.__studyPlayback()`; el coste de decodificación real depende del navegador y de la carga del VPS. Comprobar FFmpeg y la emisión después de integrar. El prerender evita el coste de WebGL, pero no garantiza por sí solo cero pérdidas en el directo.

El reloj, noticias, contador y tipografía de la interfaz son una capa independiente; no se hornean en el vídeo.

## Resultado de las comprobaciones

- WebGL: ocho poses sin errores; cero diferencias de píxeles entre t=0 y t=120.
- Máster H.264: 1920 × 1080, 30 fps, 120 s, 3600 cuadros.
- Copia VPS H.264: 1280 × 720, 30 fps, 3600 cuadros.
- Chrome local: 0 cuadros descartados; salto de final a inicio verificado.
- VPS con el directo activo, navegador aislado a 1920 × 1080: 20 segundos medidos, 601 cuadros procesados sin nuevos descartes; 7 descartes durante arranque antes de la medición. CPU del navegador de prueba: ~32.55 % de un núcleo. La prueba no equivale a una validación prolongada del nuevo fondo integrado en producción.
- La prueba comparativa del máster 1080p consumió ~37.2 % de un núcleo y añadió 24 descartes en 20 s. Por eso el reproductor usa la copia 720p.
- La copia temporal de vista previa se retiró del VPS tras aclarar el alcance. Los archivos finales se conservan localmente. No se ha sustituido el iframe de producción ni reiniciado el servicio.
