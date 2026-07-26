FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY config ./config
COPY src ./src
COPY scripts ./scripts
# Seed scraped leads (optional — empty store still boots)
COPY outputs/hub ./outputs/hub

ENV PYTHONPATH=/app/src
ENV PORT=8787

EXPOSE 8787

RUN mkdir -p /app/outputs /app/data \
  && printf '#!/bin/sh\nset -e\nexec python -m uvicorn gem_agent.api:app --host 0.0.0.0 --port ${PORT:-8787}\n' > /app/entrypoint.sh \
  && chmod +x /app/entrypoint.sh

HEALTHCHECK --interval=30s --timeout=5s --start-period=25s --retries=3 \
  CMD curl -fsS http://127.0.0.1:${PORT:-8787}/health || exit 1

CMD ["/app/entrypoint.sh"]
