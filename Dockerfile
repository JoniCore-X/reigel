# Imagen de la aplicación R.E.I.G.E.L. Guía: docs/DESPLIEGUE.md.
# No contiene base de datos, claves ni .env (ver .dockerignore): todo eso vive
# en el volumen /app/data y en el archivo .env del servidor.
FROM python:3.14-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    REIGEL_DB_PATH=/app/data/reigel.db \
    FORWARDED_ALLOW_IPS=127.0.0.1
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt \
    && useradd --uid 10001 --user-group --no-create-home --home-dir /tmp --shell /usr/sbin/nologin solar \
    && mkdir -m 0700 /app/data \
    && chown solar:solar /app/data
# El código queda propiedad de root y en solo lectura para el usuario de la
# aplicación: un fallo en la aplicación no puede reescribir su propio código.
COPY reigel ./reigel
COPY frontend ./frontend
COPY scripts ./scripts
COPY main.py ./
USER solar
EXPOSE 8765
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8765/health', timeout=4)"]
# Un solo proceso: los límites de solicitudes y la coordinación viven en memoria.
# Las cabeceras X-Forwarded-* solo se aceptan de las direcciones indicadas en
# FORWARDED_ALLOW_IPS (aquí, ninguna externa; compose.yaml fija la del proxy).
# Nunca usar "*": cualquier cliente podría falsificar su dirección.
CMD ["python", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8765", "--workers", "1", "--no-access-log", "--proxy-headers"]
