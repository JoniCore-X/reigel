FROM python:3.14-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 REIGEL_DB_PATH=/app/data/reigel.db
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt && useradd --create-home --uid 10001 solar && mkdir /app/data && chown solar:solar /app/data
COPY --chown=solar:solar reigel ./reigel
COPY --chown=solar:solar frontend ./frontend
COPY --chown=solar:solar scripts ./scripts
COPY --chown=solar:solar main.py ./
USER solar
EXPOSE 8765
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8765/health', timeout=4)"
CMD ["python", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8765", "--workers", "1", "--no-access-log", "--proxy-headers", "--forwarded-allow-ips", "*"]
