FROM python:3.11-slim AS builder

# psycopg2-binary menyediakan wheel manylinux, jadi tidak perlu compiler
# di image final.
ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /build
COPY requirements.txt .
RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install --no-cache-dir -r requirements.txt


FROM python:3.11-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/opt/venv/bin:$PATH" \
    PORT=8080 \
    HOST=0.0.0.0

WORKDIR /app

RUN groupadd --system --gid 1001 rofi \
    && useradd --system --uid 1001 --gid rofi --create-home rofi \
    && mkdir -p /app/data \
    && chown -R rofi:rofi /app

COPY --from=builder /opt/venv /opt/venv
COPY --chown=rofi:rofi app.py ./

USER rofi

EXPOSE 8080

# healthz mengembalikan 503 bila database tidak bisa dijangkau.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/api/healthz', timeout=4)"]

CMD ["python", "app.py"]
