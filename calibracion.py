"""Modo calibración: guarda un cuadro de la cámara con una grilla de coordenadas."""

import logging

import cv2

from camara import Camara

log = logging.getLogger(__name__)

PASO_GRILLA = 50     # separación de las líneas de la grilla (px)
PASO_NUMEROS = 100   # cada cuántos px se escribe la coordenada
ESPERA_CUADRO = 30   # segundos máximos esperando un cuadro de la cámara

COLOR_MENOR = (0, 200, 255)   # naranja (BGR)
COLOR_MAYOR = (0, 255, 255)   # amarillo
COLOR_LINEA = (0, 0, 255)     # rojo: línea de conteo configurada


def _texto(imagen, texto, posicion):
    """Texto blanco con borde negro para que se lea sobre cualquier fondo."""
    fuente = cv2.FONT_HERSHEY_SIMPLEX
    cv2.putText(imagen, texto, posicion, fuente, 0.45, (0, 0, 0), 3, cv2.LINE_AA)
    cv2.putText(imagen, texto, posicion, fuente, 0.45, (255, 255, 255), 1, cv2.LINE_AA)


def dibujar_grilla(cuadro, linea=None):
    imagen = cuadro.copy()
    alto, ancho = imagen.shape[:2]

    for x in range(0, ancho, PASO_GRILLA):
        mayor = x % PASO_NUMEROS == 0
        cv2.line(imagen, (x, 0), (x, alto - 1), COLOR_MAYOR if mayor else COLOR_MENOR, 1)
        if mayor and x > 0:
            _texto(imagen, str(x), (x + 3, 15))

    for y in range(0, alto, PASO_GRILLA):
        mayor = y % PASO_NUMEROS == 0
        cv2.line(imagen, (0, y), (ancho - 1, y), COLOR_MAYOR if mayor else COLOR_MENOR, 1)
        if mayor and y > 0:
            _texto(imagen, str(y), (3, y - 4))

    if linea is not None:
        inicio, fin = tuple(linea["punto_inicio"]), tuple(linea["punto_fin"])
        cv2.line(imagen, inicio, fin, COLOR_LINEA, 2)
        _texto(imagen, f"inicio {inicio}", (inicio[0] + 5, inicio[1] + 18))
        _texto(imagen, f"fin {fin}", (fin[0] + 5, fin[1] + 18))

    return imagen


def generar_calibracion(camara: Camara, linea=None, ruta: str = "calibracion.jpg") -> bool:
    """Toma un cuadro, le dibuja la grilla y lo guarda. Devuelve True si tuvo éxito."""
    camara.iniciar()
    try:
        cuadro = camara.leer(timeout=ESPERA_CUADRO)
    finally:
        camara.detener()

    if cuadro is None:
        log.error("No se recibió ningún cuadro de la cámara en %d s", ESPERA_CUADRO)
        return False

    alto, ancho = cuadro.shape[:2]
    if not cv2.imwrite(ruta, dibujar_grilla(cuadro, linea)):
        log.error("No se pudo guardar %s", ruta)
        return False

    log.info("Imagen de calibración guardada en %s", ruta)
    log.info("Resolución del stream: %dx%d (x de 0 a %d, y de 0 a %d)", ancho, alto, ancho - 1, alto - 1)
    log.info("La línea roja es la configurada actualmente. Editar punto_inicio y punto_fin en config.yaml")
    return True
