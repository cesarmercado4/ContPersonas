"""Base SQLite con cada entrada registrada (fecha y hora)."""

import sqlite3
from datetime import date, datetime, timedelta

# La columna 'tipo' se conserva por compatibilidad con los datos de la versión que también
# contaba salidas; hoy solo se guardan entradas y las consultas ignoran cualquier otra fila.
ESQUEMA = """
CREATE TABLE IF NOT EXISTS eventos (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    fecha_hora TEXT NOT NULL,   -- hora local, 'YYYY-MM-DD HH:MM:SS'
    tipo       TEXT NOT NULL CHECK (tipo IN ('entrada', 'salida'))
);
CREATE INDEX IF NOT EXISTS idx_eventos_fecha ON eventos (fecha_hora);
"""

ENTRADAS = "tipo = 'entrada'"


class BaseDatos:
    """Cada operación abre su propia conexión: la usan el hilo de conteo y los del panel."""

    def __init__(self, ruta: str):
        self.ruta = ruta
        with self._conectar() as con:
            con.execute("PRAGMA journal_mode=WAL")  # lecturas del panel sin bloquear escrituras
            con.executescript(ESQUEMA)

    def _conectar(self):
        con = sqlite3.connect(self.ruta, timeout=10)
        con.row_factory = sqlite3.Row
        return con

    def registrar(self, cantidad: int = 1, momento: datetime | None = None):
        marca = (momento or datetime.now()).strftime("%Y-%m-%d %H:%M:%S")
        with self._conectar() as con:
            con.executemany("INSERT INTO eventos (fecha_hora, tipo) VALUES (?, 'entrada')", [(marca,)] * cantidad)

    def entradas_entre(self, desde: datetime, hasta: datetime) -> int:
        with self._conectar() as con:
            return con.execute(f"SELECT COUNT(*) FROM eventos WHERE {ENTRADAS} AND fecha_hora >= ? AND fecha_hora < ?",
                               (desde.strftime("%Y-%m-%d %H:%M:%S"), hasta.strftime("%Y-%m-%d %H:%M:%S"))).fetchone()[0]

    def entradas_dia(self, dia: date) -> int:
        inicio = datetime(dia.year, dia.month, dia.day)
        return self.entradas_entre(inicio, inicio + timedelta(days=1))

    def por_hora(self, dia: date) -> list[dict]:
        """Las 24 horas del día, con ceros donde no hubo entradas."""
        desde, hasta = dia.isoformat(), (dia + timedelta(days=1)).isoformat()
        with self._conectar() as con:
            filas = con.execute(
                "SELECT CAST(substr(fecha_hora, 12, 2) AS INTEGER) AS hora, COUNT(*) AS entradas FROM eventos "
                f"WHERE {ENTRADAS} AND fecha_hora >= ? AND fecha_hora < ? GROUP BY hora", (desde, hasta)).fetchall()
        horas = {f["hora"]: f["entradas"] for f in filas}
        return [{"hora": h, "entradas": horas.get(h, 0)} for h in range(24)]

    def por_dia(self, desde: date, hasta: date) -> list[dict]:
        """Entradas por día entre dos fechas inclusive, del más reciente al más antiguo."""
        with self._conectar() as con:
            filas = con.execute(
                "SELECT substr(fecha_hora, 1, 10) AS fecha, COUNT(*) AS entradas FROM eventos "
                f"WHERE {ENTRADAS} AND fecha_hora >= ? AND fecha_hora < ? GROUP BY fecha ORDER BY fecha DESC",
                (desde.isoformat(), (hasta + timedelta(days=1)).isoformat())).fetchall()
        return [dict(f) for f in filas]

    def por_dia_hora(self, desde: date, hasta: date) -> list[dict]:
        """Entradas por día y hora entre dos fechas inclusive (solo horas con movimiento)."""
        with self._conectar() as con:
            filas = con.execute(
                "SELECT substr(fecha_hora, 1, 10) AS fecha, substr(fecha_hora, 12, 2) || ':00' AS hora, "
                f"COUNT(*) AS entradas FROM eventos WHERE {ENTRADAS} AND fecha_hora >= ? AND fecha_hora < ? "
                "GROUP BY fecha, hora ORDER BY fecha, hora",
                (desde.isoformat(), (hasta + timedelta(days=1)).isoformat())).fetchall()
        return [dict(f) for f in filas]

    def ultimas(self, cantidad: int = 10) -> list[str]:
        """Fecha y hora de las últimas entradas, de la más reciente a la más antigua."""
        with self._conectar() as con:
            filas = con.execute(f"SELECT fecha_hora FROM eventos WHERE {ENTRADAS} "
                                "ORDER BY fecha_hora DESC, id DESC LIMIT ?", (cantidad,)).fetchall()
        return [f["fecha_hora"] for f in filas]
