"""Dependencias JVM fijadas; se descargan al construir la imagen, no en cada flujo."""
import hashlib
from pathlib import Path
from urllib.request import urlopen

DESTINO = Path('/opt/snowflake-jars')
DESTINO.mkdir(parents=True, exist_ok=True)
for grupo, artefacto, version in [
    ('net/snowflake', 'spark-snowflake_2.12', '3.1.1'),
    ('net/snowflake', 'snowflake-jdbc', '3.19.0'),
    ('org/apache/parquet', 'parquet-avro', '1.13.1'),
]:
    nombre = f'{artefacto}-{version}.jar'
    url = f'https://repo.maven.apache.org/maven2/{grupo}/{artefacto}/{version}/{nombre}'
    with urlopen(url, timeout=120) as respuesta:
        contenido = respuesta.read()
    with urlopen(url + '.sha1', timeout=30) as respuesta:
        esperado = respuesta.read().decode().split()[0].lower()
    if hashlib.sha1(contenido).hexdigest() != esperado:
        raise RuntimeError(f'Checksum incorrecto: {nombre}')
    (DESTINO / nombre).write_bytes(contenido)
    print('Dependencia verificada:', nombre)
