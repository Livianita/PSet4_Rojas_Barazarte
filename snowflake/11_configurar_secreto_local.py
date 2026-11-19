"""Guarda la frase validada en un archivo local excluido de Git.

Ejecutar en terminal interactiva. No conecta ni cambia claves en Snowflake.
"""

import os
from getpass import getpass
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from dotenv import load_dotenv


def main():
    raiz = Path(__file__).resolve().parents[1]
    load_dotenv(raiz / '.env', override=False)
    clave = Path(os.environ.get('SNOWFLAKE_PRIVATE_KEY_FILE', '.secrets/snowflake_key.p8'))
    if not clave.is_absolute():
        clave = raiz / clave
    destino = Path(os.environ.get(
        'SNOWFLAKE_PRIVATE_KEY_PASSPHRASE_FILE', '.secrets/snowflake_passphrase.txt'
    ))
    if not destino.is_absolute():
        destino = raiz / destino
    # Guardar solo dentro de la carpeta de secretos del proyecto.
    if destino.resolve().parent != (raiz / '.secrets').resolve():
        raise SystemExit('Para este paso utiliza .secrets/snowflake_passphrase.txt como destino.')
    frase = getpass('Frase ACTUAL de la clave privada (no se muestra): ')
    if not frase:
        raise SystemExit('La frase no puede estar vacía.')
    try:
        serialization.load_pem_private_key(clave.read_bytes(), password=frase.encode('utf-8'))
    except ValueError:
        raise SystemExit('La frase no abrió la clave. No se guardó el secreto.') from None
    # No añadir un salto de línea ni mostrar la frase.
    destino.write_text(frase, encoding='utf-8')
    print('Secreto local guardado y validado. No subir .secrets/ a Git.')
    print('Prueba siguiente: ejecutar 03_probar_conexion.py; ya no debería pedir la frase.')


if __name__ == '__main__':
    main()
