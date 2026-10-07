"""Conexión RTSP con la cámara Vivotek y reconexión automática."""

import logging
import os
import threading
from urllib.parse import quote

# RTSP sobre TCP es más estable que UDP en redes con pérdida de paquetes.
# Debe definirse antes de importar cv2.
os.environ.setdefault("OPENCV_FFMPEG_CAPTURE_OPTIONS", "rtsp_transport;tcp")

import cv2  # noqa: E402

log = logging.getLogger(__name__)

TIMEOUT_MS = 10000  # tiempo máximo para abrir el stream o leer un cuadro


class Camara:
    """Lee el stream en un hilo aparte y conserva solo el último cuadro.

    Así el procesamiento siempre trabaja sobre la imagen más reciente (sin acumular
    retraso si YOLO es más lento que la cámara) y los cortes se resuelven reintentando
    cada `reintento_segundos` sin detener el programa.
    """

    def __init__(self, cfg: dict):
        usuario = str(cfg["usuario"])
        clave = str(cfg["clave"])
        destino = f"{cfg['ip']}:{cfg.get('puerto', 554)}/{cfg['stream']}"
        self._url = f"rtsp://{quote(usuario, safe='')}:{quote(clave, safe='')}@{destino}"
        # Versión de la URL apta para logs: nunca incluye la clave.
        self.url_segura = f"rtsp://{usuario}:***@{destino}"
        self.reintento = float(cfg.get("reintento_segundos", 5))

        self._cuadro = None
        self._hay_nuevo = threading.Event()
        self._lock = threading.Lock()
        self._detener = threading.Event()
        self._hilo = None

    def abrir(self):
        """Abre una captura de OpenCV. Devuelve None si la cámara no responde."""
        cap = cv2.VideoCapture(
            self._url,
            cv2.CAP_FFMPEG,
            [cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, TIMEOUT_MS, cv2.CAP_PROP_READ_TIMEOUT_MSEC, TIMEOUT_MS],
        )
        if cap.isOpened():
            return cap
        cap.release()
        return None

    def iniciar(self):
        """Arranca el hilo de lectura."""
        self._detener.clear()
        self._hilo = threading.Thread(target=self._bucle, name="lector-rtsp", daemon=True)
        self._hilo.start()

    def detener(self):
        self._detener.set()
        if self._hilo is not None:
            self._hilo.join(timeout=TIMEOUT_MS / 1000 + 2)

    def leer(self, timeout: float = 1.0):
        """Devuelve el cuadro más reciente aún no leído, o None si no llegó ninguno a tiempo."""
        if not self._hay_nuevo.wait(timeout):
            return None
        with self._lock:
            cuadro = self._cuadro
            self._hay_nuevo.clear()
        return cuadro

    def _bucle(self):
        while not self._detener.is_set():
            log.info("Conectando a %s", self.url_segura)
            cap = self.abrir()
            if cap is None:
                log.warning("La cámara no responde. Reintentando en %.0f s", self.reintento)
                self._detener.wait(self.reintento)
                continue

            ancho = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            alto = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            log.info("Conectado a la cámara (%dx%d)", ancho, alto)

            while not self._detener.is_set():
                ok, cuadro = cap.read()
                if not ok or cuadro is None:
                    log.warning("Se cortó el stream. Reintentando en %.0f s", self.reintento)
                    break
                with self._lock:
                    self._cuadro = cuadro
                    self._hay_nuevo.set()

            cap.release()
            if not self._detener.is_set():
                self._detener.wait(self.reintento)
