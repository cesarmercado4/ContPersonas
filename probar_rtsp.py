"""Prueba rápida: verifica que la URL RTSP de config.yaml abre con OpenCV."""

import sys

import yaml

from camara import Camara

with open("config.yaml", encoding="utf-8") as archivo:
    camara = Camara(yaml.safe_load(archivo)["camara"])

print(f"Abriendo {camara.url_segura} ...")
cap = camara.abrir()
if cap is None:
    sys.exit("ERROR: OpenCV no pudo abrir el stream (revisar IP, usuario, clave y nombre del stream)")

ok, cuadro = cap.read()
cap.release()
if not ok:
    sys.exit("ERROR: el stream abrió pero no entregó ningún cuadro")

alto, ancho = cuadro.shape[:2]
print(f"OK: stream abierto, cuadro de {ancho}x{alto}")
