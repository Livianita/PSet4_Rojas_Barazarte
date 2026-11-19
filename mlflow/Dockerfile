# Servidor de tracking de MLflow. La versión coincide con la del cliente
# (requirements.txt) para evitar incompatibilidades del API REST.
FROM python:3.12-slim

RUN pip install --no-cache-dir mlflow==3.18.0 psycopg2-binary==2.9.11

EXPOSE 5000
