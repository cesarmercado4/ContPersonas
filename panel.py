"""Panel web: video en vivo, entradas del día e historial guardado en SQLite."""

import csv
import io
import logging
import threading
import time
from datetime import date, datetime, timedelta
from pathlib import Path

import cv2
from flask import Flask, Response, abort, jsonify, request, send_file
from werkzeug.serving import make_server

log = logging.getLogger(__name__)

PAGINA = Path(__file__).parent / "web" / "panel.html"
SIN_SENAL_SEGUNDOS = 5   # sin cuadros durante este tiempo = cámara caída
CALIDAD_JPEG = 80


class Panel:
    def __init__(self, contador, base, host: str, puerto: int):
        self.contador = contador
        self.base = base
        self.host, self.puerto = host, puerto

        self._jpeg = None
        self._version = 0
        self._ultimo_cuadro = 0.0
        self._espectadores = 0
        self._condicion = threading.Condition()
        self._servidor = None

        self.app = Flask(__name__)
        self._rutas()

    # --- lado del conteo -------------------------------------------------------

    def latido(self):
        """Avisa que llegó un cuadro de la cámara (para el indicador de cámara en línea)."""
        self._ultimo_cuadro = time.monotonic()

    def hay_espectadores(self) -> bool:
        """Si nadie mira el video, no vale la pena comprimir cuadros en JPEG."""
        return self._espectadores > 0

    def publicar(self, imagen):
        """Recibe la imagen anotada para el video en vivo."""
        ok, jpeg = cv2.imencode(".jpg", imagen, [cv2.IMWRITE_JPEG_QUALITY, CALIDAD_JPEG])
        if not ok:
            return
        with self._condicion:
            self._jpeg = jpeg.tobytes()
            self._version += 1
            self._condicion.notify_all()

    def iniciar(self):
        logging.getLogger("werkzeug").setLevel(logging.WARNING)  # sin un log por cada consulta
        self._servidor = make_server(self.host, self.puerto, self.app, threaded=True)
        threading.Thread(target=self._servidor.serve_forever, name="panel-web", daemon=True).start()
        visible = "localhost" if self.host in ("0.0.0.0", "127.0.0.1") else self.host
        log.info("Panel web en http://%s:%d", visible, self.puerto)

    def detener(self):
        if self._servidor is not None:
            self._servidor.shutdown()

    # --- lado web --------------------------------------------------------------

    def _camara_ok(self):
        return time.monotonic() - self._ultimo_cuadro < SIN_SENAL_SEGUNDOS

    def _cuadros_mjpeg(self):
        version = -1
        with self._condicion:
            self._espectadores += 1
        try:
            while True:
                with self._condicion:
                    self._condicion.wait_for(lambda: self._version != version, timeout=SIN_SENAL_SEGUNDOS)
                    if self._version == version or self._jpeg is None:
                        continue
                    version, jpeg = self._version, self._jpeg
                yield b"--cuadro\r\nContent-Type: image/jpeg\r\n\r\n" + jpeg + b"\r\n"
        finally:
            # Se ejecuta cuando el navegador cierra la conexión.
            with self._condicion:
                self._espectadores -= 1

    def _rutas(self):
        app = self.app

        @app.get("/")
        def inicio():
            return send_file(PAGINA)

        @app.get("/video")
        def video():
            return Response(self._cuadros_mjpeg(), mimetype="multipart/x-mixed-replace; boundary=cuadro")

        @app.get("/api/estado")
        def estado():
            c = self.contador
            return jsonify({
                "ahora": datetime.now().isoformat(timespec="seconds"),
                "camara_ok": self._camara_ok(),
                "entradas_hoy": c.entradas_hoy,
                "entradas_ayer": self.base.entradas_dia(date.today() - timedelta(days=1)),
                "hora_actual": c.hora_actual.strftime("%H:00"),
                # De la base y no del contador: así incluye lo registrado antes de un reinicio.
                "entradas_hora": self.base.entradas_entre(c.hora_actual, c.hora_actual + timedelta(hours=1)),
                "ultimas": self.base.ultimas(10),
            })

        @app.get("/api/dia")
        def dia():
            fecha = _fecha(request.args.get("fecha"), date.today())
            return jsonify({"fecha": fecha.isoformat(), "entradas": self.base.entradas_dia(fecha),
                            "horas": self.base.por_hora(fecha)})

        @app.get("/api/historial")
        def historial():
            hasta = _fecha(request.args.get("hasta"), date.today())
            desde = _fecha(request.args.get("desde"), hasta - timedelta(days=29))
            return jsonify(self.base.por_dia(desde, hasta))

        @app.get("/api/exportar.csv")
        def exportar():
            hasta = _fecha(request.args.get("hasta"), date.today())
            desde = _fecha(request.args.get("desde"), hasta - timedelta(days=29))
            salida = io.StringIO()
            escritor = csv.DictWriter(salida, fieldnames=["fecha", "hora", "entradas"])
            escritor.writeheader()
            escritor.writerows(self.base.por_dia_hora(desde, hasta))
            nombre = f"conteos_{desde.isoformat()}_{hasta.isoformat()}.csv"
            return Response(salida.getvalue(), mimetype="text/csv",
                            headers={"Content-Disposition": f"attachment; filename={nombre}"})


def _fecha(texto, por_defecto: date) -> date:
    if not texto:
        return por_defecto
    try:
        return date.fromisoformat(texto)
    except ValueError:
        abort(400, "Fecha inválida, usar AAAA-MM-DD")
