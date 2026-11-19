"""Genera claves locales cifradas y SQL para registrar solo la pública.

Requiere cryptography. Ejecutar desde una terminal interactiva.
No conecta con Snowflake ni imprime la clave privada o su frase.
"""

from getpass import getpass
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa


def main():
    carpeta = Path(__file__).resolve().parents[1] / '.secrets'
    carpeta.mkdir(exist_ok=True)
    privada_path = carpeta / 'snowflake_key.p8'
    publica_path = carpeta / 'snowflake_key.pub'
    sql_path = carpeta / 'registrar_clave_publica.sql'
    if any(p.exists() for p in [privada_path, publica_path, sql_path]):
        raise SystemExit('Ya existen archivos de claves. No se reemplazará ninguno.')

    frase = getpass('Elige una frase para cifrar la clave privada (no se muestra): ')
    confirmacion = getpass('Repite la frase: ')
    if not frase or frase != confirmacion:
        raise SystemExit('Las frases deben coincidir y no estar vacías. No se generaron claves.')

    privada = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    privada_bytes = privada.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.BestAvailableEncryption(frase.encode('utf-8')),
    )
    publica_bytes = privada.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    # x / xb impide sobrescribir un archivo existente.
    with privada_path.open('xb') as archivo:
        archivo.write(privada_bytes)
    with publica_path.open('xb') as archivo:
        archivo.write(publica_bytes)
    publica_snowflake = ''.join(publica_bytes.decode('ascii').splitlines()[1:-1])
    sql = (
        '-- Registrar únicamente esta clave pública en tu usuario actual.\n'
        '-- Antes, comprueba si ya hay una clave configurada; no reemplazarla sin revisión.\n'
        'USE ROLE ACCOUNTADMIN;\n'
        'SET usuario_actual = (SELECT \'"\' || REPLACE(CURRENT_USER(), \'"\', \'""\') || \'"\');\n'
        'DESCRIBE USER IDENTIFIER($usuario_actual);\n'
        '-- Si RSA_PUBLIC_KEY_FP ya tiene valor, detenerse y revisar.\n'
        f"ALTER USER IDENTIFIER($usuario_actual) SET RSA_PUBLIC_KEY = '{publica_snowflake}';\n"
    )
    with sql_path.open('x', encoding='utf-8') as archivo:
        archivo.write(sql)
    print('Claves generadas en .secrets/. No compartas la clave privada ni la frase.')
    print('Siguiente paso: revisar .secrets/registrar_clave_publica.sql antes de ejecutarlo.')


if __name__ == '__main__':
    main()
