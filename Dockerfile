FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src \
    UV_LINK_MODE=copy \
    DATABASE_PATH=/data/swapmeet_astana.sqlite3 \
    FSM_STORAGE=redis \
    REDIS_URL=redis://127.0.0.1:6379/0

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends redis-server \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir uv

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

COPY src ./src

VOLUME ["/data"]

CMD ["sh", "-c", "export DATABASE_PATH=/data/swapmeet_astana.sqlite3 FSM_STORAGE=redis REDIS_URL=redis://127.0.0.1:6379/0 && redis-server --appendonly yes --dir /data --daemonize yes && exec uv run python -m bot"]
