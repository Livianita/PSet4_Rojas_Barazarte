"""Lanza Spark local desde Kestra; no cambia el Java utilizado por Kestra."""
import os
from pathlib import Path
import subprocess
import sys


def main():
    raiz = Path(__file__).resolve().parents[1]
    entorno = os.environ.copy()
    entorno.update(JAVA_HOME='/opt/spark-java', SPARK_HOME='/opt/spark',
                   PYSPARK_PYTHON=sys.executable, PYSPARK_DRIVER_PYTHON=sys.executable,
                   SPARK_LOCAL_IP='127.0.0.1')
    jars = ','.join(str(p) for p in sorted(Path('/opt/snowflake-jars').glob('*.jar')))
    if not jars:
        raise SystemExit('Faltan los conectores. Reconstruye la imagen de Kestra.')
    comando = ['/opt/spark/bin/spark-submit', '--master', 'local[2]',
               '--driver-memory', '1g', '--jars', jars,
               '--conf', 'spark.sql.shuffle.partitions=8',
               # Spark escribe su log en stderr y Kestra marca stderr como ERROR:
               # se limita a WARN para no llenar el log de líneas INFO de arranque.
               '--conf', 'spark.log.level=WARN',
               '--conf', 'spark.sql.session.timeZone=UTC',
               '--conf', 'spark.ui.enabled=false',
               '--conf', 'spark.eventLog.enabled=false',
               '--conf', 'spark.redaction.regex=(?i)secret|password|token|private.?key|passphrase',
               str(raiz / 'spark' / '02_construir_obt.py'), *sys.argv[1:]]
    raise SystemExit(subprocess.run(comando, env=entorno, cwd=raiz, check=False).returncode)


if __name__ == '__main__':
    main()
