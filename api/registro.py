"""Registro local de predicciones y solicitudes (SQLite en un volumen de Docker).

La API escribe aquí cada predicción (id, timestamp, entradas, salida, versión del
modelo, run_id, latencia) y cada solicitud HTTP (ruta, estado, latencia). Un
flujo de Kestra carga las filas pendientes a la tabla PREDICCIONES de Snowflake
y las marca como enviadas. Así, si Snowflake no responde, la API sigue sirviendo y
ninguna predicción se pierde.
"""

import json
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path

ESQUEMA = """
CREATE TABLE IF NOT EXISTS predicciones (
    id_prediccion   TEXT PRIMARY KEY,
    ts_utc          TEXT NOT NULL,
    lote            TEXT,
    store_nbr       INTEGER,
    item_nbr        INTEGER,
    fecha           TEXT,
    entradas        TEXT NOT NULL,
    pedido_sugerido REAL NOT NULL,
    decision        TEXT NOT NULL,
    modelo_nombre   TEXT,
    modelo_version  TEXT,
    modelo_alias    TEXT,
    run_id          TEXT,
    respaldo        INTEGER NOT NULL,
    motivo_respaldo TEXT,
    latencia_ms     REAL NOT NULL,
    enviado         INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS predicciones_pendientes ON predicciones(enviado);
CREATE TABLE IF NOT EXISTS solicitudes (
    ts_utc      TEXT NOT NULL,
    metodo      TEXT NOT NULL,
    ruta        TEXT NOT NULL,
    estado      INTEGER NOT NULL,
    latencia_ms REAL NOT NULL,
    filas       INTEGER,
    lote        TEXT
);
"""

COLUMNAS = ['id_prediccion', 'ts_utc', 'lote', 'store_nbr', 'item_nbr', 'fecha', 'entradas', 'pedido_sugerido',
            'decision', 'modelo_nombre', 'modelo_version', 'modelo_alias', 'run_id', 'respaldo',
            'motivo_respaldo', 'latencia_ms']


class Registro:
    def __init__(self, ruta):
        self.ruta = Path(ruta)
        self.ruta.parent.mkdir(parents=True, exist_ok=True)
        self._candado = threading.Lock()
        with self._conexion() as c:
            c.execute('PRAGMA journal_mode=WAL')
            c.executescript(ESQUEMA)

    @contextmanager
    def _conexion(self):
        c = sqlite3.connect(self.ruta, timeout=30)
        try:
            yield c
            c.commit()
        finally:
            c.close()

    def predicciones(self, filas):
        """filas: lista de dicts con las COLUMNAS; 'entradas' puede venir como dict."""
        valores = [tuple(json.dumps(f[k], default=str) if k == 'entradas' and not isinstance(f[k], str)
                         else f.get(k) for k in COLUMNAS) for f in filas]
        with self._candado, self._conexion() as c:
            c.executemany(f'INSERT INTO predicciones ({", ".join(COLUMNAS)}) '
                          f'VALUES ({", ".join("?" * len(COLUMNAS))})', valores)

    def solicitud(self, ts_utc, metodo, ruta, estado, latencia_ms, filas=None, lote=None):
        with self._candado, self._conexion() as c:
            c.execute('INSERT INTO solicitudes VALUES (?, ?, ?, ?, ?, ?, ?)',
                      (ts_utc, metodo, ruta, estado, latencia_ms, filas, lote))
