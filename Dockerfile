FROM python:3.11-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app
COPY pyproject.toml .
COPY README.md .
COPY uv.lock .
COPY lib/ lib/
COPY fs/ fs/
COPY bin/ bin/
COPY system/ system/

RUN uv sync --no-dev

EXPOSE 8000

CMD ["uv", "run", "bin/web.py", "--fsimage", "/app/vault.db", "--passwd", "/app/passwd.txt", "--host", "0.0.0.0"]
