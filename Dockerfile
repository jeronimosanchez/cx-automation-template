# Contenedor del servidor del pipeline ACT para Cloud Run.
#
# Es el único archivo de la Fase 5 sin el sufijo `_cloudrun`: Docker exige este
# nombre exacto por convención, y renombrarlo obligaría a pasar `-f` en cada
# build y en cada despliegue.
#
# **Sin credenciales dentro.** Ni la clave de la GitHub App —que se lee de
# Secret Manager en el momento de usarla— ni ningún token de Google: la
# identidad la inyecta Cloud Run en tiempo de ejecución a través de la cuenta
# de servicio del servicio. Una imagen con secretos dentro los reparte a todo
# el que pueda descargarla, y las imágenes viven en el registro mucho más que
# la sesión que las construyó.

FROM python:3.11-slim

# La salida sin buffer es lo que hace que el registro de un paso largo aparezca
# en los logs de Cloud Run según ocurre, en vez de aparecer entero al terminar
# —o de perderse del todo si el contenedor muere a mitad—.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# Las dependencias antes que el código: cambiar una línea de Python no obliga a
# reinstalarlas, que es la parte lenta del build.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY act/ ./act/

# El panel, dentro de la imagen y servido por el propio servidor (S25). Se copia
# a `panel/` en vez de arrastrar `docs/` entero: lo que se despliega es un
# archivo, no la documentación del repositorio. El original se queda donde vive
# —`docs/panels/`— y esta línea es lo único que sabe de él.
#
# Sin esto, `GET /panel` contesta 404 en el contenedor aunque funcione en el Mac,
# porque en local encuentra el del repositorio y aquí no hay repositorio.
COPY docs/panels/act_cx_resources_deploy_v2_output_cloudrun.html ./panel/

# El caché de bytecode que venga del Mac no sirve aquí y solo puede confundir:
# se compila de nuevo dentro, desde las fuentes que acaban de copiarse.
RUN find /app -name __pycache__ -type d -prune -exec rm -rf {} +

# Documental: Cloud Run enruta al valor de PORT, no a lo que declare EXPOSE. Se
# deja escrito porque es el puerto que espera quien arranque la imagen a mano.
EXPOSE 8080

CMD ["python", "act/server_cloudrun.py"]
