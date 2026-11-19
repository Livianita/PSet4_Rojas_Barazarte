# Imagen de la API. Se construye desde la raíz del proyecto:
#   docker build -f api/Dockerfile -t favorita-api .
# El modelo NO va dentro de la imagen: se descarga de MLflow (alias champion) al
# arrancar, y cambiar de versión no requiere reconstruirla.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 \
    RUTA_REGISTRO=/registros/predicciones.jsonl RUTA_SOLICITUDES=/registros/solicitudes.jsonl

WORKDIR /app
COPY api/requirements.txt /app/api/requirements.txt
RUN pip install -r /app/api/requirements.txt

# Solo lo que la API necesita: src (preparación y regla de negocio), monitoreo (deriva) y api.
COPY src/__init__.py src/pipeline.py src/negocio.py /app/src/
COPY monitoreo/__init__.py monitoreo/deriva.py /app/monitoreo/
COPY api/ /app/api/

RUN useradd --create-home --uid 10001 api && mkdir -p /registros && chown api /registros
USER api

EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=5s --start-period=60s --retries=5 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/salud')"
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
