# Tablero de monitoreo: Streamlit sobre las tablas PRODUCCION de Snowflake.
#   docker compose up -d tablero      → http://localhost:8501
FROM python:3.12-slim

WORKDIR /app
COPY tablero/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

# src/ (conexión a Snowflake), tablero/ y docs/ (CSV de respaldo) se montan desde el repositorio.
ENV PYTHONUNBUFFERED=1
EXPOSE 8501
CMD ["streamlit", "run", "tablero/app.py", "--server.address=0.0.0.0", "--server.port=8501", "--server.headless=true", "--browser.gatherUsageStats=false"]
