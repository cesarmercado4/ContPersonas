# Contador de personas: conteo + panel web en el puerto 8000.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    DATOS_DIR=/datos \
    YOLO_CONFIG_DIR=/tmp/ultralytics \
    TZ=America/Argentina/Buenos_Aires

WORKDIR /app

# Zona horaria: los conteos se guardan con la hora local.
RUN apt-get update && apt-get install -y --no-install-recommends tzdata && rm -rf /var/lib/apt/lists/*

# PyTorch solo CPU (mucho más liviano que la versión con CUDA) y OpenCV sin interfaz gráfica.
RUN pip install --index-url https://download.pytorch.org/whl/cpu torch torchvision
COPY requirements.txt .
RUN pip install -r requirements.txt \
 && pip uninstall -y opencv-python \
 && pip install opencv-python-headless

COPY . .
# La configuración base es la plantilla; la clave y lo específico se pasan por variables de entorno.
RUN cp config.example.yaml config.yaml \
 && python -c "from ultralytics import YOLO; YOLO('yolo11n.pt')"

VOLUME /datos
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/estado', timeout=4)"

CMD ["python", "main.py", "--sin-video"]
