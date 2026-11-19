"""Ejecuta dbt con la frase suministrada por entorno/archivo, sin imprimirla.

En Docker: python /workspace/snowflake/12_ejecutar_dbt.py debug
"""

import os
import subprocess
import sys
from pathlib import Path

from dotenv import load_dotenv


def main():
    raiz = Path(__file__).resolve().parents[1]
    load_dotenv(raiz / '.env', override=False)
    entorno = os.environ.copy()
    frase = entorno.get('SNOWFLAKE_PRIVATE_KEY_PASSPHRASE')
    if not frase:
        ruta = Path(entorno.get('SNOWFLAKE_PRIVATE_KEY_PASSPHRASE_FILE',
                                str(raiz / '.secrets' / 'snowflake_passphrase.txt')))
        if not ruta.is_absolute():
            ruta = raiz / ruta
        frase = ruta.read_text(encoding='utf-8')
    if not frase:
        raise SystemExit('Falta configurar la frase para dbt.')
    entorno['DBT_ENV_SECRET_KEY_PASSPHRASE'] = frase
    # El adaptador dbt también necesita una ruta absoluta a la clave.
    clave = Path(entorno['SNOWFLAKE_PRIVATE_KEY_FILE'])
    if not clave.is_absolute():
        clave = raiz / clave
    entorno['SNOWFLAKE_PRIVATE_KEY_FILE'] = str(clave)
    argumentos = sys.argv[1:] or ['debug']
    ejecutable = entorno.get('DBT_EXECUTABLE', '/opt/dbt-venv/bin/dbt')
    resultado = subprocess.run(
        [ejecutable, *argumentos, '--project-dir', str(raiz / 'dbt'),
         '--profiles-dir', str(raiz / 'dbt' / 'profiles')],
        env=entorno, cwd=raiz, check=False,
    )
    raise SystemExit(resultado.returncode)


if __name__ == '__main__':
    main()
