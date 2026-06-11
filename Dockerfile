FROM python:3.11-slim
RUN apt-get update && apt-get install -y ffmpeg ghostscript && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
# Pre-download the background-removal model so the first request is fast
RUN python -c "from rembg import new_session; new_session('u2net')" || true
COPY . .
CMD ["python", "main.py"]
