FROM python:3.11-slim

WORKDIR /app
COPY pyproject.toml .
COPY fs/ fs/
COPY bin/ bin/
COPY system/ system/

RUN pip install --no-cache-dir . 2>/dev/null; \
    pip install --no-cache-dir fastapi uvicorn python-multipart

EXPOSE 8000

CMD ["python", "bin/web.py", "--fsimage", "/app/vault.db", "--passwd", "/app/passwd.txt", "--host", "0.0.0.0"]
