"""Lógica de conteo de entradas, registro en SQLite y guardado horario en CSV."""

import csv
import logging
from datetime import datetime
from pathlib import Path

import cv2
from ultralytics import solutions

from db import BaseDatos

log = logging.getLogger(__name__)

# Ultralytics configura su logger al importarse y avisa "No tracks found" en cada cuadro
# sin personas; solo interesan sus errores.
logging.getLogger("ultralytics").setLevel(logging.ERROR)

CLASE_PERSONA = 0
COLUMNAS_CSV = ["fecha", "hora", "entradas"]
COLOR_LINEA = (238, 211, 34)  # cian (BGR), igual al del panel


def _inicio_de_hora(momento: datetime) -> datetime:
    return momento.replace(minute=0, second=0, microsecond=0)


def _texto(imagen, texto, posicion):
    """Texto blanco con borde negro, legible sobre cualquier fondo."""
    fuente = cv2.FONT_HERSHEY_SIMPLEX
    cv2.putText(imagen, texto, posicion, fuente, 0.8, (0, 0, 0), 4, cv2.LINE_AA)
    cv2.putText(imagen, texto, posicion, fuente, 0.8, (255, 255, 255), 2, cv2.LINE_AA)


def _migrar_csv(ruta: Path):
    """Quita la columna 'salidas' de un CSV de la versión anterior, conservando los datos."""
    if not ruta.exists() or ruta.stat().st_size == 0:
        return
    with ruta.open(newline="", encoding="utf-8") as archivo:
        filas = list(csv.DictReader(archivo))
        if not filas or "salidas" not in filas[0]:
            return
    with ruta.open("w", newline="", encoding="utf-8") as archivo:
        escritor = csv.DictWriter(archivo, fieldnames=COLUMNAS_CSV, extrasaction="ignore")
        escritor.writeheader()
        escritor.writerows(filas)
    log.info("%s convertido al formato nuevo (sin columna de salidas)", ruta)


class Contador:
    """Envuelve ObjectCounter de ultralytics y acumula las entradas de cada hora."""

    def __init__(self, cfg_linea: dict, cfg_deteccion: dict, ruta_csv: str, base: BaseDatos):
        region = [tuple(cfg_linea["punto_inicio"]), tuple(cfg_linea["punto_fin"])]
        self.region = region
        self.invertir = bool(cfg_linea.get("invertir_sentido", False))
        self.ruta_csv = Path(ruta_csv)
        self.base = base
        try:
            _migrar_csv(self.ruta_csv)
        except OSError:
            log.exception("No se pudo convertir %s al formato nuevo", self.ruta_csv)

        log.info("Cargando modelo %s", cfg_deteccion["modelo"])
        self._contador = solutions.ObjectCounter(
            model=cfg_deteccion["modelo"],
            region=region,
            classes=[CLASE_PERSONA],
            conf=float(cfg_deteccion.get("confianza", 0.4)),
            tracker=cfg_deteccion.get("tracker", "bytetrack.yaml"),
            show=False,  # la ventana la maneja main.py
            # Los IN/OUT propios de ultralytics no respetan invertir_sentido: se dibuja el nuestro.
            show_in=False,
            show_out=False,
            verbose=False,
        )
        log.info("Línea de conteo: %s -> %s (invertir_sentido=%s)", region[0], region[1], self.invertir)

        # ObjectCounter devuelve totales acumulados de cada sentido; guardamos el anterior
        # para obtener solo los cruces nuevos de cada cuadro.
        self._previo = 0

        self.hora_actual = _inicio_de_hora(datetime.now())
        self.entradas_hora = 0
        self._pendientes = []  # filas que no se pudieron escribir todavía

        # Total del día: parte de lo ya guardado, así sobrevive a un reinicio.
        self.entradas_hoy = self.base.entradas_dia(self.hora_actual.date())

    def procesar(self, cuadro):
        """Procesa un cuadro, actualiza el conteo y devuelve la imagen anotada."""
        self.verificar_hora()
        resultado = self._contador(cuadro)

        # Solo interesa un sentido: el "in" de ultralytics, o el "out" si invertir_sentido.
        total = resultado.out_count if self.invertir else resultado.in_count
        nuevas = total - self._previo
        self._previo = total
        if nuevas > 0:
            self._registrar(nuevas)

        imagen = resultado.plot_im
        # Ultralytics dibuja la línea en violeta fijo; se repinta en cian para el panel.
        cv2.line(imagen, self.region[0], self.region[1], COLOR_LINEA, 3, cv2.LINE_AA)
        for punto in self.region:
            cv2.circle(imagen, punto, 6, COLOR_LINEA, -1, cv2.LINE_AA)
        _texto(imagen, f"Entradas hoy: {self.entradas_hoy}", (10, imagen.shape[0] - 15))
        return imagen

    def _registrar(self, cantidad: int):
        self.entradas_hora += cantidad
        self.entradas_hoy += cantidad
        log.info("Entrada (+%d). Hoy: %d entradas", cantidad, self.entradas_hoy)
        try:
            self.base.registrar(cantidad)
        except Exception:
            # Un fallo de la base no debe cortar el conteo; queda al menos en el CSV horario.
            log.exception("No se pudo registrar la entrada en la base de datos")

    def verificar_hora(self):
        """Si cambió la hora, guarda la anterior en el CSV y reinicia el parcial."""
        ahora = _inicio_de_hora(datetime.now())
        if ahora != self.hora_actual:
            self.guardar_hora()
            if ahora.date() != self.hora_actual.date():
                self.entradas_hoy = 0
            self.hora_actual = ahora
            self.entradas_hora = 0

    def guardar_hora(self):
        """Agrega al CSV una fila con lo contado en la hora actual."""
        self._pendientes.append({
            "fecha": self.hora_actual.strftime("%Y-%m-%d"),
            "hora": self.hora_actual.strftime("%H:00"),
            "entradas": self.entradas_hora,
        })
        try:
            nuevo = not self.ruta_csv.exists() or self.ruta_csv.stat().st_size == 0
            with self.ruta_csv.open("a", newline="", encoding="utf-8") as archivo:
                escritor = csv.DictWriter(archivo, fieldnames=COLUMNAS_CSV)
                if nuevo:
                    escritor.writeheader()
                escritor.writerows(self._pendientes)
        except OSError:
            # Por ejemplo, si el CSV está abierto y bloqueado en Excel: las filas quedan
            # pendientes y se reintentan en el próximo guardado.
            log.exception("No se pudo escribir %s; %d fila(s) pendiente(s)",
                          self.ruta_csv, len(self._pendientes))
            return
        for fila in self._pendientes:
            log.info("Guardado en %s: %s %s -> %d entradas", self.ruta_csv,
                     fila["fecha"], fila["hora"], fila["entradas"])
        self._pendientes.clear()
