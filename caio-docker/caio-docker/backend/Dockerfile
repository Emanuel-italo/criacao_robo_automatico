FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PASTA_SAIDA=/app/arquivos

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN mkdir -p /app/arquivos /app/uploads /app/dados && \
    useradd -m -u 1000 caio && chown -R caio:caio /app
USER caio

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD curl -fsS http://localhost:8000/api/health || exit 1

# 1 worker + threads: os jobs assíncronos ficam em memória do processo.
# Se migrar para Redis/Celery, pode aumentar --workers.
CMD ["gunicorn", "--bind", "0.0.0.0:8000", "--workers", "1", "--threads", "8", \
     "--worker-class", "gthread", "--timeout", "600", "--access-logfile", "-", "app:app"]
