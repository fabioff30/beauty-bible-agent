FROM python:3.12-slim

# Minimal OS deps. sqlcipher3-wheels, Pillow and sklearn ship statically-linked
# binaries in their Python wheels — no system libs needed beyond TLS + init.
RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates \
        tini \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Python deps (cached layer)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# App source
COPY . .

# Persistent data lives here — mount a volume to this path in EasyPanel
ENV DATA_DIR=/data
RUN mkdir -p /data

# Container-level metadata
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    LOG_LEVEL=INFO

# tini = proper PID 1 (handles SIGTERM cleanly for Telegram polling)
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["python", "bot.py"]
