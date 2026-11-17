FROM python:3.11-slim

# Instalar FFmpeg y dependencias básicas del sistema
RUN apt-get update && \
    apt-get install -y --no-install-recommends ffmpeg procps ca-certificates && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copiar video 1080p, scripts y listas de canciones
COPY videos/16-9_1080p.mp4 /app/videos/16-9_1080p.mp4
COPY scripts/ /app/scripts/
COPY radio/ /app/radio/
COPY sounds/ /app/sounds/
COPY app_render.py /app/app.py

ENV PORT=10000
ENV PYTHONUNBUFFERED=1

EXPOSE 10000

CMD ["python3", "/app/app.py"]
