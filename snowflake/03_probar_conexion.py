"""Prueba de conexión por clave; no crea tablas ni carga datos.

Ejecutar en Windows: .venv/Scripts/python.exe snowflake/03_probar_conexion.py
Requiere snowflake-connector-python y python-dotenv.
"""

import os
import base64
import hashlib
from getpass import getpass
from pathlib import Path

import snowflake.connector
from dotenv import load_dotenv
from cryptography.hazmat.primitives import serialization


def crear_conexion(query_tag='PSET2_PRUEBA_CONEXION'):
    raiz = Path(__file__).resolve().parents[1]
    # Las variables del entorno tienen prioridad sobre el archivo local.
    load_dotenv(raiz / '.env', override=False)
    nombres = ['ACCOUNT', 'USER', 'ROLE', 'WAREHOUSE', 'DATABASE', 'SCHEMA', 'PRIVATE_KEY_FILE']
    config = {}
    for nombre in nombres:
        valor = os.environ.get(f'SNOWFLAKE_{nombre}', '').strip()
        if not valor or valor.startswith('tu_'):
            raise SystemExit(f'Completa SNOWFLAKE_{nombre} en el archivo .env.')
        config[nombre] = valor

    clave_path = Path(config['PRIVATE_KEY_FILE'])
    if not clave_path.is_absolute():
        clave_path = raiz / clave_path
    if not clave_path.is_file():
        raise SystemExit('No se encontró el archivo de clave privada configurado.')
    frase = os.environ.get('SNOWFLAKE_PRIVATE_KEY_PASSPHRASE')
    if not frase:
        # Docker podrá montar este archivo como secret. No quitar espacios:
        # pueden formar parte de la frase elegida.
        ruta_frase = Path(os.environ.get(
            'SNOWFLAKE_PRIVATE_KEY_PASSPHRASE_FILE',
            str(raiz / '.secrets' / 'snowflake_passphrase.txt'),
        ))
        if not ruta_frase.is_absolute():
            ruta_frase = raiz / ruta_frase
        if ruta_frase.is_file():
            frase = ruta_frase.read_text(encoding='utf-8')
    if not frase:
        if os.environ.get('PSET2_NON_INTERACTIVE') == '1':
            raise SystemExit('Falta configurar la frase de la clave para ejecución automática.')
        frase = getpass('Frase de la clave privada (no se muestra): ')

    # Descifrar localmente permite distinguir una frase incorrecta de un
    # rechazo del servidor. Solo mostramos la huella pública, nunca la clave.
    clave = serialization.load_pem_private_key(
        clave_path.read_bytes(), password=frase.encode('utf-8')
    )
    publica_der = clave.public_key().public_bytes(
        serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    huella = base64.b64encode(hashlib.sha256(publica_der).digest()).decode('ascii')
    print('Cuenta utilizada:', config['ACCOUNT'])
    print('Login utilizado:', config['USER'])
    print('Huella pública local: SHA256:' + huella)
    privada_der = clave.private_bytes(
        serialization.Encoding.DER, serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )

    return snowflake.connector.connect(
        account=config['ACCOUNT'],
        user=config['USER'],
        role=config['ROLE'],
        warehouse=config['WAREHOUSE'],
        database=config['DATABASE'],
        schema=config['SCHEMA'],
        authenticator='SNOWFLAKE_JWT',
        private_key=privada_der,
        login_timeout=30,
        # Esta prueba no lanza consultas asíncronas; cerrar sesión al terminar.
        enable_server_session_keep_alive_auto_detection=False,
        session_parameters={'QUERY_TAG': query_tag},
    )


def main():
    with crear_conexion() as conexion:
        with conexion.cursor() as cursor:
            cursor.execute('''
                SELECT CURRENT_USER(), CURRENT_ROLE(), CURRENT_WAREHOUSE(),
                       CURRENT_DATABASE(), CURRENT_SCHEMA()
            ''')
            resultado = cursor.fetchone()
            print('Conexión correcta.')
            for nombre, valor in zip(['Usuario', 'Rol', 'Warehouse', 'Base de datos', 'Esquema'], resultado):
                print(f'{nombre}: {valor}')


if __name__ == '__main__':
    main()
