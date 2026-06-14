FROM python:3.11-slim
RUN apt-get update && apt-get install -y ffmpeg ghostscript && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
# Pre-download the background-removal model so the first request is fast
RUN python -c "from rembg import new_session; new_session('u2netp')" || true
COPY . .
# Servidor de produção: 2 workers, timeout 300s, reinicia worker que travar
CMD gunicorn main:app --bind 0.0.0.0:$PORT --workers 2 --timeout 300 --max-requests 50 --max-requests-jitter 10
