"""Contador de personas que entran y salen, usando una cámara RTSP y YOLO.

Uso:
    python main.py               # modo conteo (por defecto)
    python main.py --calibrar    # genera calibracion.jpg con una grilla de coordenadas
    python main.py --sin-video   # sin la ventana de OpenCV (el panel web sigue activo)
    python main.py --sin-panel   # sin el panel web
"""

import argparse
import logging
import os
import signal
import sys
import threading
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path

import yaml

from camara import Camara

log = logging.getLogger("main")

VENTANA = "Contador de personas (q para salir)"


def configurar_logging(ruta_log: str):
    formato = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s", "%Y-%m-%d %H:%M:%S")
    consola = logging.StreamHandler()
    consola.setFormatter(formato)
    archivo = RotatingFileHandler(ruta_log, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8")
    archivo.setFormatter(formato)
    logging.basicConfig(level=logging.INFO, handlers=[consola, archivo])


# Variables de entorno que pisan valores del YAML (pensadas para Docker/Coolify, donde la
# clave no debe quedar en el repositorio).
VARIABLES_ENTORNO = {
    "CAMARA_IP": ("camara", "ip", str),
    "CAMARA_PUERTO": ("camara", "puerto", int),
    "CAMARA_USUARIO": ("camara", "usuario", str),
    "CAMARA_CLAVE": ("camara", "clave", str),
    "CAMARA_STREAM": ("camara", "stream", str),
    "INVERTIR_SENTIDO": ("linea", "invertir_sentido", lambda v: v.lower() in ("1", "true", "si", "sí")),
    "CONFIANZA": ("deteccion", "confianza", float),
    "PANEL_PUERTO": ("panel", "puerto", int),
    "VIDEO_FPS": ("panel", "video_fps", float),
    "MAX_FPS": ("deteccion", "max_fps", float),
    "HILOS_CPU": ("deteccion", "hilos_cpu", int),
}


def _aplicar_entorno(cfg: dict):
    for variable, (seccion, clave, convertir) in VARIABLES_ENTORNO.items():
        valor = os.environ.get(variable)
        if valor:
            cfg.setdefault(seccion, {})[clave] = convertir(valor)
    linea = os.environ.get("LINEA")  # formato "x1,y1,x2,y2"
    if linea:
        x1, y1, x2, y2 = (int(v) for v in linea.split(","))
        cfg["linea"]["punto_inicio"], cfg["linea"]["punto_fin"] = [x1, y1], [x2, y2]
    datos = os.environ.get("DATOS_DIR")  # carpeta persistente para CSV, base y log
    if datos:
        Path(datos).mkdir(parents=True, exist_ok=True)
        for clave in ("csv", "base_datos", "log"):
            if clave in cfg["salida"]:
                cfg["salida"][clave] = str(Path(datos) / Path(cfg["salida"][clave]).name)


def cargar_config(ruta: Path) -> dict:
    if not ruta.exists():
        sys.exit(f"No existe {ruta}. Copiar config.example.yaml como config.yaml y completarlo.")
    with ruta.open(encoding="utf-8-sig") as archivo:
        cfg = yaml.safe_load(archivo)
    for seccion in ("camara", "linea", "deteccion", "salida"):
        if seccion not in cfg:
            sys.exit(f"Falta la sección '{seccion}' en {ruta}")
    _aplicar_entorno(cfg)
    if str(cfg["camara"].get("clave", "")) in ("", "CAMBIAR"):
        sys.exit(f"Completar la clave de la cámara en {ruta} o en la variable CAMARA_CLAVE")
    return cfg


def _terminar(signum, frame):
    # SIGTERM (p. ej. systemctl stop) se trata igual que Ctrl+C para guardar la hora en curso.
    raise KeyboardInterrupt


class Deteccion(threading.Thread):
    """Corre YOLO en un hilo aparte sobre el cuadro más reciente, a lo sumo `max_fps` veces por
    segundo. Así el video del panel no queda atado a la velocidad de la detección."""

    def __init__(self, contador, max_fps: float):
        super().__init__(name="deteccion", daemon=True)
        self.contador = contador
        self.intervalo = 1.0 / max_fps if max_fps > 0 else 0.0
        self._cuadro = None
        self._lock = threading.Lock()
        self._hay_cuadro = threading.Event()
        self.detener = threading.Event()
        self.procesados = 0

    def entregar(self, cuadro):
        with self._lock:
            self._cuadro = cuadro
        self._hay_cuadro.set()

    def run(self):
        while not self.detener.is_set():
            if not self._hay_cuadro.wait(timeout=1.0):
                self.contador.verificar_hora()  # cámara caída: igual se controla el cambio de hora
                continue
            with self._lock:
                cuadro, self._cuadro = self._cuadro, None
                self._hay_cuadro.clear()
            inicio = time.monotonic()
            try:
                self.contador.procesar(cuadro)
                self.procesados += 1
            except Exception:
                log.exception("Error al procesar un cuadro")
            espera = self.intervalo - (time.monotonic() - inicio)
            if espera > 0:
                self.detener.wait(espera)


def contar(cfg: dict, mostrar: bool, con_panel: bool):
    import cv2
    from contador import Contador, limitar_hilos
    from db import BaseDatos

    det_cfg = cfg["deteccion"]
    limitar_hilos(det_cfg.get("hilos_cpu"))
    base = BaseDatos(cfg["salida"].get("base_datos", "conteos.db"))
    contador = Contador(cfg["linea"], det_cfg, cfg["salida"]["csv"], base)
    deteccion = Deteccion(contador, float(det_cfg.get("max_fps") or 0))
    deteccion.start()
    log.info("Detección: %s", f"máximo {det_cfg['max_fps']} cuadros/s" if det_cfg.get("max_fps") else "sin límite de cuadros/s")

    panel = None
    if con_panel:
        from panel import Panel
        cfg_panel = cfg.get("panel", {})
        panel = Panel(contador, base, cfg_panel.get("host", "127.0.0.1"), int(cfg_panel.get("puerto", 8000)))
        panel.iniciar()

    camara = Camara(cfg["camara"])
    camara.iniciar()
    log.info("Conteo iniciado (%s). Detener con %s", "con ventana" if mostrar else "sin ventana",
             "q o Ctrl+C" if mostrar else "Ctrl+C")
    video_fps = float(cfg.get("panel", {}).get("video_fps", 15))
    intervalo_video = 1.0 / video_fps if video_fps > 0 else 0.0
    ultimo_video = 0.0
    ultimo_reporte, cuadros_video = time.monotonic(), 0
    try:
        while True:
            cuadro = camara.leer(timeout=1.0)
            if cuadro is None:
                if mostrar and cv2.waitKey(1) & 0xFF == ord("q"):
                    break
                continue

            deteccion.entregar(cuadro)
            if panel is not None:
                panel.latido()

            ahora = time.monotonic()
            if ahora - ultimo_reporte >= 60:
                transcurrido = ahora - ultimo_reporte
                log.info("Rendimiento: detección %.1f cuadros/s, video %.1f cuadros/s",
                         deteccion.procesados / transcurrido, cuadros_video / transcurrido)
                deteccion.procesados, cuadros_video, ultimo_reporte = 0, 0, ahora

            # El video se arma con el cuadro nuevo y los últimos recuadros detectados.
            if ahora - ultimo_video < intervalo_video:
                continue
            quiere_video = mostrar or (panel is not None and panel.hay_espectadores())
            if not quiere_video:
                continue
            ultimo_video = ahora
            cuadros_video += 1
            imagen = contador.anotar(cuadro)
            if panel is not None:
                panel.publicar(imagen)
            if mostrar:
                cv2.imshow(VENTANA, imagen)
                if cv2.waitKey(1) & 0xFF == ord("q"):
                    log.info("Se presionó q")
                    break
    except KeyboardInterrupt:
        log.info("Interrupción recibida")
    finally:
        deteccion.detener.set()
        deteccion.join(timeout=5)
        contador.guardar_hora()
        camara.detener()
        if panel is not None:
            panel.detener()
        if mostrar:
            cv2.destroyAllWindows()
        log.info("Programa finalizado")


def main():
    parser = argparse.ArgumentParser(description="Contador de personas por cámara RTSP")
    parser.add_argument("--calibrar", action="store_true",
                        help="guardar calibracion.jpg con una grilla de coordenadas y salir")
    parser.add_argument("--sin-video", action="store_true",
                        help="no mostrar ventana de video (modo servidor)")
    parser.add_argument("--sin-panel", action="store_true", help="no levantar el panel web")
    parser.add_argument("--config", default="config.yaml", help="ruta del archivo de configuración")
    args = parser.parse_args()

    cfg = cargar_config(Path(args.config))
    configurar_logging(cfg["salida"].get("log", "contador.log"))
    signal.signal(signal.SIGTERM, _terminar)

    if args.calibrar:
        from calibracion import generar_calibracion
        ok = generar_calibracion(Camara(cfg["camara"]), cfg["linea"])
        sys.exit(0 if ok else 1)

    mostrar = bool(cfg["salida"].get("mostrar_video", False)) and not args.sin_video
    con_panel = bool(cfg.get("panel", {}).get("habilitado", True)) and not args.sin_panel
    contar(cfg, mostrar, con_panel)


if __name__ == "__main__":
    main()
