FROM apache/spark:3.5.3-python3 AS spark_runtime
FROM kestra/kestra:v1.3.0
USER root
RUN apt-get update \
    && apt-get install -y --no-install-recommends python3 python3-venv \
    && rm -rf /var/lib/apt/lists/*
COPY kestra/requirements.txt /opt/pset2-requirements.txt
# La base trae Python 3.10; el conector 5.x necesita un Python más reciente.
ENV UV_PYTHON_INSTALL_DIR=/opt/pset2-python UV_NATIVE_TLS=true
RUN python3 -m venv /opt/bootstrap \
    && /opt/bootstrap/bin/pip install --no-cache-dir uv==0.9.7 \
    && /opt/bootstrap/bin/uv python install 3.12.12 \
    && /opt/bootstrap/bin/uv venv --python 3.12.12 /opt/pset2-venv \
    && /opt/bootstrap/bin/uv pip install --python /opt/pset2-venv/bin/python -r /opt/pset2-requirements.txt
COPY snowflake/ /workspace/snowflake/
COPY dbt/requirements.txt /opt/pset2-dbt-requirements.txt
RUN /opt/bootstrap/bin/uv venv --python 3.12.12 /opt/dbt-venv \
    && /opt/bootstrap/bin/uv pip install --python /opt/dbt-venv/bin/python -r /opt/pset2-dbt-requirements.txt
RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*
ENV PYTHONUNBUFFERED=1
# spark-submit usa su Java 11; Kestra conserva su propio Java 25.
COPY --from=spark_runtime /opt/spark /opt/spark
COPY --from=spark_runtime /opt/java/openjdk /opt/spark-java
COPY spark/descargar_conectores.py /opt/descargar_conectores.py
RUN /opt/pset2-venv/bin/python /opt/descargar_conectores.py
