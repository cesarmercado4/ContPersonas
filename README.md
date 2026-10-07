# Contador de personas – Ingreso

Cuenta las personas que **entran** por la puerta usando la cámara domo Vivotek del ingreso
(RTSP), el modelo YOLO `yolo11n.pt` y `ultralytics.solutions.ObjectCounter` con tracking. Las
salidas no se registran. Cada entrada se guarda con fecha y hora en una base SQLite
(`conteos.db`), cada hora se agrega un resumen a `conteos.csv`, y un panel web muestra la cámara
en vivo con las entradas del día.

## Archivos

| Archivo | Función |
|---|---|
| `main.py` | Punto de entrada (`--calibrar`, `--sin-video`, `--sin-panel`, `--config`) |
| `camara.py` | Conexión RTSP en un hilo aparte y reconexión automática |
| `contador.py` | Conteo de entradas, registro en la base y guardado horario en CSV |
| `db.py` | Base SQLite con cada entrada (fecha y hora) |
| `panel.py` y `web/panel.html` | Panel web: video en vivo, contadores e historial |
| `calibracion.py` | Genera `calibracion.jpg` con una grilla de coordenadas |
| `probar_rtsp.py` | Prueba rápida de que el stream abre con OpenCV |
| `config.yaml` | Configuración real (**con la clave**, no se sube a git) |
| `config.example.yaml` | Plantilla sin la clave |

## 1. Instalación

Requiere Python 3.10 o superior.

**Windows** (PowerShell, en la carpeta del proyecto):

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Para instalar Python, usar el instalador de python.org y marcar **"Add python.exe to PATH"**.

**Linux:**

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
sudo apt install libgl1        # dependencia de OpenCV en Debian/Ubuntu
```

La primera vez que se ejecuta el conteo se descarga automáticamente `yolo11n.pt` (hace falta
internet solo esa vez).

Si `config.yaml` no existe, copiar `config.example.yaml` como `config.yaml` y completar la clave.

## 2. Probar la conexión con la cámara

```
python probar_rtsp.py
```

Debe mostrar `OK: stream abierto, cuadro de ANCHOxALTO`. Si falla, revisar IP, usuario, clave y
nombre del stream (`live1s2.sdp` = secundario, liviano; `live1s1.sdp` = principal), y que la
cámara abra en el navegador en http://10.10.50.16/.

## 3. Calibrar la línea de conteo

```
python main.py --calibrar
```

Se guarda `calibracion.jpg` con una grilla cada 50 px (números cada 100 px) y en el log se
informa la resolución del stream. La línea roja es la configurada actualmente.

Elegir dos puntos que formen una línea que **cruce la puerta de lado a lado**, perpendicular al
sentido en que camina la gente, en una zona donde las personas se vean completas. Cargarlos en
`config.yaml`:

```yaml
linea:
  punto_inicio: [120, 260]
  punto_fin: [520, 260]
```

Volver a correr `--calibrar` para ver la línea dibujada. Las coordenadas dependen del stream:
si se cambia de `live1s2.sdp` a `live1s1.sdp` (u otra resolución), hay que recalibrar.

## 4. Contar

```
python main.py               # conteo + panel web (salir con Ctrl+C)
python main.py --sin-panel   # sin panel web
```

Con `mostrar_video: true` en `config.yaml` se abre además una ventana de OpenCV (se cierra con
q); `--sin-video` la desactiva aunque esté en `true`.

### Panel web

Con el programa corriendo, abrir en el navegador **http://localhost:8000**. Muestra:

- La cámara en vivo con la línea de conteo y las personas detectadas.
- Las entradas de hoy, las de la hora en curso y el total de ayer para comparar.
- Las últimas entradas, con su hora.
- Un gráfico de entradas por hora para cualquier fecha (◀ ▶, calendario o clic en un día de la
  tabla), con la hora pico y opción de verlo como tabla.
- Los totales de los últimos 30 días y un botón **Exportar CSV** (detalle por día y hora).

Para verlo desde otras PCs de la red, poner `host: 0.0.0.0` en la sección `panel` de
`config.yaml` y entrar con la IP de esta PC (por ejemplo `http://10.0.40.10:8000`). Puede hacer
falta permitir el puerto 8000 en el Firewall de Windows. El panel no tiene usuario ni clave:
cualquiera en la red que conozca la dirección puede ver la cámara.

### Datos guardados

- `conteos.db` (SQLite): una fila por cada entrada, con `fecha_hora`. Es la fuente del panel y
  conserva los conteos del día aunque se reinicie el programa. (La columna `tipo` quedó de una
  versión anterior que también contaba salidas; esas filas viejas se ignoran.)
  Se puede abrir con [DB Browser for SQLite](https://sqlitebrowser.org/).

- Si la cámara no responde o se corta el stream, reintenta cada 5 segundos
  (`reintento_segundos`) sin cerrar el programa ni perder lo contado.
- Al cambiar la hora se agrega una fila a `conteos.csv`:

  ```
  fecha,hora,entradas
  2026-09-28,08:00,37
  ```

- Al cerrar con q, Ctrl+C o `systemctl stop` se guarda también la hora en curso. Si el programa
  se reinicia dentro de la misma hora, puede haber dos filas para esa hora: hay que sumarlas.
- Si `conteos.csv` está abierto en Excel y no se puede escribir, la fila queda pendiente y se
  guarda en el próximo intento. Conviene abrir una copia del archivo.
- Los mensajes quedan en consola y en `contador.log`. La clave nunca se escribe en los logs.

## 5. Verificar que se cuenten las entradas (y no las salidas)

Solo se cuenta un sentido de cruce. Ultralytics lo decide **por la geometría de la línea, no por
el orden de los puntos**:

| Tipo de línea | Se cuenta a quien se mueve… |
|---|---|
| Más horizontal que vertical | hacia **abajo** en la imagen |
| Más vertical que horizontal | hacia la **derecha** en la imagen |

Por eso, invertir el orden de los puntos **no** cambia el resultado. Para verificarlo:

1. Ejecutar `python main.py` y abrir el panel en http://localhost:8000.
2. Una persona **entra** a la empresa cruzando la línea. En el panel debe sumar **Entradas hoy**
   (y en el log aparece `Entrada (+1)`).
3. La misma persona **sale**. El contador **no** debe cambiar.

Si pasa al revés (suma al salir y no al entrar), poner en `config.yaml`:

```yaml
linea:
  invertir_sentido: true
```

El panel, el video, el log, la base y el CSV ya tienen en cuenta `invertir_sentido`. Las
entradas ya registradas en la base no se corrigen solas.

## 6. Dejarlo corriendo al iniciar la computadora

Usar siempre `--sin-video`, porque el servicio no tiene pantalla. El panel web queda disponible
igual en http://localhost:8000.

### Windows (Programador de tareas)

En PowerShell **como administrador**, ajustando la ruta si el proyecto está en otra carpeta:

```powershell
$carpeta = "C:\Proyectos Corpico\ContPersona"
$accion = New-ScheduledTaskAction -Execute "$carpeta\.venv\Scripts\python.exe" `
    -Argument "main.py --sin-video" -WorkingDirectory $carpeta
$disparador = New-ScheduledTaskTrigger -AtStartup
$ajustes = New-ScheduledTaskSettingsSet -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -StartWhenAvailable
$cuenta = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest
Register-ScheduledTask -TaskName "ContadorPersonas" -Action $accion -Trigger $disparador `
    -Settings $ajustes -Principal $cuenta
```

- `-ExecutionTimeLimit 0` es importante: por defecto Windows corta las tareas a los 3 días.
- Probar sin reiniciar: `Start-ScheduledTask ContadorPersonas`. Revisar `contador.log`.
- Detener: `Stop-ScheduledTask ContadorPersonas`. Esto mata el proceso, así que **no** guarda la
  hora en curso (se pierde el parcial de esa hora).
- Eliminar: `Unregister-ScheduledTask ContadorPersonas`.

### Linux (systemd)

Crear `/etc/systemd/system/contador-personas.service`, ajustando usuario y rutas:

```ini
[Unit]
Description=Contador de personas del ingreso
After=network-online.target
Wants=network-online.target

[Service]
User=contador
WorkingDirectory=/opt/contpersona
ExecStart=/opt/contpersona/.venv/bin/python main.py --sin-video
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now contador-personas
sudo systemctl status contador-personas
journalctl -u contador-personas -f     # ver los mensajes
```

`systemctl stop` envía SIGTERM, y el programa lo trata como Ctrl+C: guarda la hora en curso
antes de salir.

## Seguridad

`config.yaml` contiene la clave de la cámara y está en `.gitignore`. Al compartir el proyecto,
usar solo `config.example.yaml`.
