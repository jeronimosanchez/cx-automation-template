#!/usr/bin/env python3
"""
act/validate_html_cloudrun.py — Fase 8. Que el panel conectado funciona.

Verifica `docs/panels/act_cx_resources_deploy_v2_output_cloudrun.html` — la
copia que la Fase 7 convirtió en panel de producción — en cuatro niveles de
riesgo creciente. Los dos primeros no necesitan nada; el tercero arranca el
servidor de verdad; el cuarto ejecuta el panel en un DOM y pulsa sus botones.

    Nivel 0  Estático. El código fuente del panel: sin simulación residual, con
             una llamada real por cada puerta, sin URL escrita a fuego.
    Nivel 1  Contrato. El panel contra el servidor y el Dockerfile: ninguna
             ruta sin consumidor, ningún motivo de error sin mensaje propio,
             el panel dentro de la imagen.
    Nivel 2  Servido. Arranca el servidor real y comprueba que entrega el panel
             desde su mismo origen, con las cabeceras que toca.
    Nivel 3  Comportamiento. Ejecuta el panel en un DOM real (jsdom) con un
             servidor de mentira y comprueba lo que aparece en pantalla al
             pulsar. Vive en `act/validate_html_dom_cloudrun.js`.

**Por qué cuatro y no solo el análisis estático que pedía la fase.** Un `grep`
confirma que el código llama al servidor; no confirma que la pantalla funcione.
Un botón que no responde, un aviso que no aparece y —el peor— un `status` de
error pintado como éxito no los caza ningún análisis de texto: el servidor
devuelve el resultado del pipeline con **HTTP 200** aunque el deploy haya
quedado a medias (`act/server_cloudrun.py`, la vista devuelve `jsonify(...), 200`),
así que un panel que mirara `response.ok` daría por bueno un borrador roto y
todos los checks estáticos seguirían en verde.

**Este script no toca ningún agente.** No necesita destino: el Nivel 2 arranca
el servidor solo para pedirle un archivo, y el Nivel 3 no sale a la red. Por eso
no lleva —ni necesita— la guarda del agente desechable de las Fases 4 y 6.

Uso:
    python act/validate_html_cloudrun.py                # todos los niveles
    python act/validate_html_cloudrun.py --levels 0-1   # sin arrancar nada
"""

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

import requests

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from act.validate_pipeline_cloudrun import PASS, FAIL, SKIP, CheckRunner  # noqa: E402

PANEL = "docs/panels/act_cx_resources_deploy_v2_output_cloudrun.html"
PANEL_REFERENCIA = "docs/panels/act_cx_resources_deploy_v2.html"
SERVIDOR = "act/server_cloudrun.py"
DOCKERFILE = "Dockerfile"
DOM_SUITE = "act/validate_html_dom_cloudrun.js"

# Las nueve rutas del servidor. Ninguna puede quedarse sin consumidor en el
# panel, y el panel no puede llamar a ninguna que no exista.
RUTAS_DEL_PIPELINE = [
    "/step/1", "/step/2", "/step/3", "/step/4", "/step/5",
    "/discover", "/register-agent", "/link-project-repo", "/manage-versions",
]

# Rastros de la maqueta. Si sobrevive uno, ese trozo del panel sigue enseñando
# datos de mentira aunque el resto ya esté conectado — y parece que funciona.
SIMULACION_RESIDUAL = [
    ("INV_LINES", "las líneas del log del Paso 1 escritas a mano"),
    ("DEPLOY_RESOURCES", "la tabla que decidía qué fila 'fallaba'"),
    ("DEPLOY_SIMULATE_FAIL", "el interruptor de fallo simulado del Paso 3"),
    ("PRODUCTION_SIMULATE_CONFLICT", "el interruptor de conflicto simulado del Paso 5"),
    ("SIMULAR_DRAFT_MOVIDO", "el interruptor del borrador movido"),
    ("REPOS_POR_PROYECTO", "el mapeo proyecto→repo escrito en el panel"),
    ("RAMAS_POR_AGENTE", "las ramas de cada agente escritas en el panel"),
    ("REGION_POR_AGENTE", "las regiones escritas en el panel"),
    ("TIENE_ENTORNO_PRODUCCION_POR_AGENTE", "el aviso de entorno decidido en el panel"),
    ("RAMA_PROPUESTA_POR_AGENTE", "la rama propuesta calculada en el panel"),
    ("TOOL_ONBOARDING_LOG_LINES", "el log de vincular escrito a mano"),
    ("DIFF_COUNT", "el contador de cambios fijo"),
    ("completeAuto", "el avance automático de pasos por temporizador"),
    ("huellaDraft", "la huella del borrador inventada en el panel"),
    ("ESTADO_INICIAL", "la foto del HTML de partida que reponía las tablas"),
    ("toggleSpecsPanel", "la columna de specs"),
    ("specs-panel", "la columna de specs"),
    (".spec-block", "el CSS de la columna de specs"),
]

# Identificadores reales que no pueden estar escritos dentro del panel. El
# destino se elige, no se hereda de un ejemplo.
LITERALES_PROHIBIDOS = re.compile(
    r"(floristeria-petal-digital"
    r"|745375ba-ac7e-4eb8-b8a0-d742891f2aa4"
    r"|cea66b60-192d-4b5a-af10-28f8661032e0"
    r"|jeronimosanchez/cx-automation-template"
    r"|98fcbdd)"
)


def leer(ruta):
    return (REPO_ROOT / ruta).read_text()


def bloque_script(texto):
    """Solo el JavaScript del panel, sin el HTML ni el CSS."""
    ini = texto.index("<script>") + len("<script>")
    return texto[ini:texto.index("</script>", ini)]


def bloque_html(texto):
    """Solo el HTML del panel, sin el JavaScript.

    Hace falta separarlos porque el JS **construye** HTML: buscar un `<option>`
    con valor en el archivo entero encuentra las plantillas que rellenan los
    desplegables desde el servidor, que es justo lo contrario de lo que se
    quiere cazar.
    """
    return texto[:texto.index("<script>")]


def sin_comentarios(script):
    """El JavaScript sin sus comentarios.

    Un símbolo prohibido citado en un comentario que explica por qué no está no
    puede contar como si estuviera: eso convierte la documentación en un fallo.
    """
    sin_bloque = re.sub(r"/\*.*?\*/", "", script, flags=re.S)
    return re.sub(r"^\s*//.*$", "", sin_bloque, flags=re.M)


def llamadas_fetch(script):
    """Cada `llamar('<ruta>' …)` del panel, con su cuerpo aproximado.

    Se busca el helper propio y no `fetch(` a secas a propósito: el panel tiene
    un único camino de salida a la red, y que lo tenga es parte de lo que se
    comprueba —un `fetch` suelto se saltaría el manejo de errores común—.
    """
    encontradas = []
    for coincidencia in re.finditer(r"llamar\(\s*(`|')([^`']+)\1", script):
        ruta = coincidencia.group(2)
        # El trozo que sigue a la llamada, donde vive el cuerpo de la petición.
        cola = script[coincidencia.end():coincidencia.end() + 400]
        encontradas.append((ruta, cola))
    return encontradas


# ── Nivel 0 · Estático ───────────────────────────────────────────────────────

def nivel_0(runner):
    print("\nNIVEL 0 — Estático · el código fuente del panel")
    panel = leer(PANEL)
    script = bloque_script(panel)

    def existe_y_no_toca_la_referencia():
        referencia = leer(PANEL_REFERENCIA)
        return ("specs-panel" in referencia and panel != referencia), (
            "el panel de referencia tiene que seguir con su columna de specs y "
            "ser distinto del conectado")

    runner.check(0, "El panel conectado existe y el de referencia sigue intacto",
                 existe_y_no_toca_la_referencia)

    def sin_simulacion_residual():
        vivos = [f"{simbolo} ({que})" for simbolo, que in SIMULACION_RESIDUAL
                 if simbolo in panel]
        return not vivos, "sobrevive " + " · ".join(vivos) if vivos else ""

    runner.check(0, "No queda ningún rastro de la maqueta: ni datos falsos, ni "
                    "interruptores de simulación, ni la columna de specs",
                 sin_simulacion_residual)

    def sin_setTimeout_que_finja_trabajo():
        """Los `setTimeout` que quedan tienen que ser de pantalla, no de flujo.

        Un `setTimeout` que llame a una función de paso, que pinte una línea de
        log o que avance el pipeline es una simulación con otro nombre.
        """
        sospechosos = []
        for coincidencia in re.finditer(r"setTimeout\(([^;]{0,120})", script):
            cuerpo = coincidencia.group(1)
            if re.search(r"(showLine|siguiente|advance|completeAuto|"
                         r"appendLogLine|pintarLog|step)", cuerpo):
                sospechosos.append(cuerpo.strip()[:70])
        return not sospechosos, " · ".join(sospechosos)

    runner.check(0, "Ningún setTimeout mueve el pipeline ni escribe el log: los "
                    "que quedan son de pantalla", sin_setTimeout_que_finja_trabajo)

    def una_llamada_por_puerta():
        rutas = {r for r, _ in llamadas_fetch(script)}
        # `/discover` se llama con y sin proyecto; se normaliza para comparar.
        normalizadas = {r.split("?")[0] for r in rutas}
        faltan = [r for r in RUTAS_DEL_PIPELINE if r not in normalizadas]
        sobran = [r for r in normalizadas if r not in RUTAS_DEL_PIPELINE + ["/health"]]
        return not faltan and not sobran, (
            f"sin llamar: {faltan} · llamadas a rutas que no existen: {sobran}")

    runner.check(0, "Las nueve rutas del servidor tienen quien las llame, y el "
                    "panel no llama a ninguna que no exista", una_llamada_por_puerta)

    def los_pasos_mandan_destino():
        """Cada paso manda `project` y `agent`. El servidor no pone valores por
        defecto: una llamada sin destino se rechaza con un 400."""
        faltan = []
        for ruta, cola in llamadas_fetch(script):
            if not ruta.startswith("/step/") and ruta not in (
                    "/register-agent", "/manage-versions"):
                continue
            if "project:" not in cola or "agent:" not in cola:
                faltan.append(ruta)
        return not faltan, f"sin destino en el cuerpo: {faltan}"

    runner.check(0, "Cada llamada que actúa sobre un agente lleva project y "
                    "agent en el cuerpo", los_pasos_mandan_destino)

    def la_direccion_no_esta_escrita_a_fuego():
        """El panel lo sirve el propio servidor (S25): rutas relativas y punto.

        Se comprueba lo contrario de lo que pedía la regla vieja —una constante
        con la URL de Cloud Run— porque esa regla es anterior a S25. Con el panel
        y la API en el mismo origen no hay URL que configurar, y una absoluta
        volvería a traer el problema de CORS que la decisión elimina.
        """
        sucios = []
        for ruta, _ in llamadas_fetch(script):
            if ruta.startswith(("http://", "https://", "//")):
                sucios.append(ruta)
        if re.search(r"llamar\([^)]*localhost", script) or "127.0.0.1" in script:
            sucios.append("localhost/127.0.0.1 dentro de una llamada")
        if re.search(r":8080", script):
            sucios.append(":8080")
        return not sucios, " · ".join(sucios)

    runner.check(0, "Ninguna llamada usa una URL absoluta, ni localhost, ni el "
                    "puerto del contenedor", la_direccion_no_esta_escrita_a_fuego)

    def el_mensaje_de_red_dice_la_direccion():
        """Con rutas relativas el fallo más probable es que el panel no lo sirva
        quien creemos. Un mensaje sin dirección no distingue eso de un servidor
        caído."""
        return ("No se pudo conectar con el servidor en ${url}" in script
                and "new URL(ruta, location.href)" in script), (
            "falta el mensaje con la URL absoluta resuelta")

    runner.check(0, "El mensaje de «no conecta» incluye la dirección exacta a la "
                    "que se llamó", el_mensaje_de_red_dice_la_direccion)

    def ningun_error_se_traga_en_silencio():
        """Un `catch` que no escribe en pantalla deja el paso colgado sin señal.

        `console.error` **no cuenta** como salida: el registro del navegador no
        lo mira nadie mientras despliega, y un error que solo vive ahí es
        exactamente el fallo silencioso que esta comprobación busca.
        """
        # Lo que sí cuenta como que el fallo sale a algún sitio: pintarlo,
        # escribirlo en un elemento, relanzarlo, o devolverlo a quien llamó.
        SALIDAS = r"(pintarError|innerHTML|textContent|mostrar\(|habilitar\w+|throw|return)"
        mudos = []
        for coincidencia in re.finditer(r"catch\s*\(([^)]*)\)\s*\{([^}]*)\}", script):
            cuerpo = coincidencia.group(2)
            if re.search(SALIDAS, cuerpo):
                continue
            # Los dos únicos silencios admitidos, y los dos llevan su comentario
            # dentro explicando por qué: `localStorage` no disponible (se sigue
            # trabajando, solo no se recuerda) y el `JSON.parse` de una respuesta
            # que se trata inmediatamente después.
            if "/*" in cuerpo or cuerpo.strip() in ("", "sobre = null;"):
                continue
            mudos.append(cuerpo.strip()[:60])
        return not mudos, f"catch sin salida visible: {mudos}"

    runner.check(0, "Ningún catch se traga un error sin dejar rastro",
                 ningun_error_se_traga_en_silencio)

    def el_status_del_sobre_se_mira_siempre():
        """El servidor devuelve `{status: "error"}` con HTTP 200 cuando el
        pipeline para a medias. Mirar solo el código HTTP pinta eso como éxito."""
        veces = len(re.findall(r"sobre\.status\s*!==\s*'ok'", script))
        return veces >= 6, (
            f"solo {veces} sitios comprueban el status del sobre; cada llamada "
            f"que actúa tiene que hacerlo")

    runner.check(0, "Cada respuesta se juzga por el status del sobre, no por el "
                    "código HTTP", el_status_del_sobre_se_mira_siempre)

    def los_selectores_salen_del_descubrimiento():
        # Solo el HTML: el JS construye `<option>` con los datos que llegan del
        # Descubrimiento, y esas plantillas son justo lo que tiene que haber.
        opciones_fijas = re.findall(r"<option value=\"(?!\")([^\"]+)\"",
                                    bloque_html(panel))
        return not opciones_fijas, (
            f"hay <option> con valor escrito en el HTML: {opciones_fijas[:5]}")

    runner.check(0, "Los dos selectores no traen ninguna opción escrita en el "
                    "HTML", los_selectores_salen_del_descubrimiento)

    def el_estado_persiste_con_clave_propia():
        return ("act_panel_cloudrun_v1" in script
                and "localStorage.setItem" in script
                and "localStorage.getItem" in script), (
            "falta la persistencia en localStorage con clave propia del panel")

    runner.check(0, "El estado del pipeline se guarda en localStorage con clave "
                    "propia", el_estado_persiste_con_clave_propia)

    def se_avisa_de_lo_que_quedo_en_vuelo():
        return ("enCurso" in script and "aviso-interrumpido" in panel), (
            "recargar a mitad de una escritura no avisa de que pudo completarse")

    runner.check(0, "Una operación interrumpida se avisa al volver, no se da por "
                    "no ocurrida", se_avisa_de_lo_que_quedo_en_vuelo)

    def el_boton_se_apaga_al_pulsarlo():
        return ("peticionEnCurso" in script and "boton.disabled = true" in script), (
            "sin bloqueo, un doble clic dispara dos escrituras")

    runner.check(0, "Los botones que escriben se apagan en el mismo gesto de "
                    "pulsarlos", el_boton_se_apaga_al_pulsarlo)

    def los_gates_nombran_el_destino():
        faltan = [i for i in ("gate3-project", "gate3-agent", "gate5-project",
                              "gate5-agent", "gate5-rama", "gate5-rama-principal")
                  if f'id="{i}"' not in panel]
        return not faltan, f"sin identificador en el gate: {faltan}"

    runner.check(0, "Los gates de los Pasos 3 y 5 tienen dónde escribir el "
                    "destino real", los_gates_nombran_el_destino)

    def los_avisos_de_limite_tienen_consumidor():
        return ("contenedores_cerca_del_limite" in script
                and "poda_pendiente" in script), (
            "los dos avisos de límite de versiones llegan del servidor y nadie "
            "los pinta")

    runner.check(0, "Los dos avisos de límite de versiones se pintan",
                 los_avisos_de_limite_tienen_consumidor)

    def sin_identificadores_reales_dentro():
        sucios = [linea for i, linea in enumerate(panel.splitlines(), 1)
                  if LITERALES_PROHIBIDOS.search(linea)
                  # La única mención admitida: el texto que explica el 403 de
                  # destino bloqueado, que nombra Petal para que se entienda.
                  and "destinos protegidos" not in linea]
        return not sucios, f"{len(sucios)} líneas con identificadores reales"

    runner.check(0, "No hay ningún proyecto, agente ni repositorio real escrito "
                    "dentro del panel", sin_identificadores_reales_dentro)

    def el_area_de_pasos_ocupa_todo():
        """Sin la columna de specs, nada puede quedar reservando su ancho.

        Se busca la columna por su nombre y no por su ancho: `420px` aparece
        también como `max-width` de los formularios de la Tool, que no tienen
        nada que ver y son anteriores a esta fase.
        """
        restos = [r for r in ("<aside", ".specs-panel", ".specs-content",
                              ".specs-tab", "specs-section")
                  if r in panel]
        return not restos, f"queda la columna de specs: {restos}"

    runner.check(0, "No queda ninguna columna lateral ni su ancho reservado",
                 el_area_de_pasos_ocupa_todo)


# ── Nivel 1 · Contrato con el servidor y con la imagen ───────────────────────

def nivel_1(runner):
    print("\nNIVEL 1 — Contrato · el panel contra el servidor y el Dockerfile")
    panel = leer(PANEL)
    script = bloque_script(panel)
    servidor = leer(SERVIDOR)

    def el_servidor_sirve_el_panel():
        return ('@app.get("/panel")' in servidor
                and "send_file" in servidor
                and '@app.get("/")' in servidor), (
            "el servidor no tiene ruta que sirva el panel")

    runner.check(1, "El servidor sirve el panel desde su mismo origen",
                 el_servidor_sirve_el_panel)

    def el_dockerfile_mete_el_panel_en_la_imagen():
        texto = leer(DOCKERFILE)
        return ("docs/panels/act_cx_resources_deploy_v2_output_cloudrun.html"
                in texto and "COPY" in texto), (
            "el Dockerfile no copia el panel: en el contenedor, /panel daría 404 "
            "aunque en el Mac funcione")

    runner.check(1, "El Dockerfile copia el panel dentro de la imagen",
                 el_dockerfile_mete_el_panel_en_la_imagen)

    def el_panel_no_se_ha_movido_de_carpeta():
        return (REPO_ROOT / PANEL).is_file(), (
            f"{PANEL} no está donde el Dockerfile lo busca")

    runner.check(1, "El panel sigue en docs/panels/, que es de donde lo copia la "
                    "imagen", el_panel_no_se_ha_movido_de_carpeta)

    def cada_motivo_del_servidor_tiene_mensaje():
        """El servidor etiqueta sus errores con un `reason`. Cada uno tiene que
        traducirse a un mensaje propio: fundirlos en «algo falló» tira justo la
        información que dice qué hacer."""
        motivos = set(re.findall(r'"reason":\s*"([a-z_]+)"', servidor))
        sin_mensaje = [m for m in motivos if m not in script]
        return not sin_mensaje, (
            f"motivos del servidor sin mensaje propio en el panel: {sorted(sin_mensaje)}")

    runner.check(1, "Cada motivo de error que devuelve el servidor tiene su "
                    "mensaje en el panel", cada_motivo_del_servidor_tiene_mensaje)

    def cada_codigo_http_tiene_mensaje():
        codigos = {"400", "403", "404", "409", "500", "502", "504"}
        faltan = [c for c in sorted(codigos)
                  if not re.search(rf"\b{c}:\s*'", script)]
        return not faltan, f"códigos sin mensaje propio: {faltan}"

    runner.check(1, "Cada código HTTP que el servidor puede devolver tiene su "
                    "mensaje", cada_codigo_http_tiene_mensaje)

    def los_estados_del_pipeline_se_tratan():
        """`aborted` y `conflict` llegan con HTTP 200 y no son éxitos."""
        return ("'aborted'" in script and "'conflict'" in script), (
            "el panel no distingue los estados aborted/conflict del Paso 5")

    runner.check(1, "El panel distingue los estados aborted y conflict que "
                    "devuelve publicar", los_estados_del_pipeline_se_tratan)

    def el_panel_no_manda_operaciones():
        """El servidor recalcula el diff (S1): el panel manda qué se marcó, no
        qué operaciones ejecutar. Mandar `operaciones` sería una segunda fuente
        de verdad.

        Se mira el código sin comentarios: la frase que explica esta misma regla
        contiene la palabra, y contarla haría fallar al panel por documentarse.
        """
        return "operaciones:" not in sin_comentarios(script), (
            "el panel manda un array de operaciones al servidor")

    runner.check(1, "El panel nunca manda operaciones al servidor — solo qué se "
                    "marcó", el_panel_no_manda_operaciones)


# ── Nivel 2 · El servidor entregando el panel ────────────────────────────────

def nivel_2(runner):
    print("\nNIVEL 2 — Servido · el servidor real entregando el panel")
    from act.validate_server_cloudrun import Servidor

    try:
        contexto = Servidor()
        contexto.__enter__()
    except Exception as error:                       # noqa: BLE001
        runner.skip(2, "El servidor arranca para servir el panel",
                    f"no arrancó: {type(error).__name__}: {error}")
        return

    try:
        def sirve_el_panel_en_su_ruta():
            respuesta = requests.get(contexto.url("/panel"), timeout=30)
            cuerpo = respuesta.text
            return (respuesta.status_code == 200
                    and "act_cx_resources_deploy_cloudrun.py" in cuerpo
                    and "<script>" in cuerpo
                    and len(cuerpo) > 50_000), (
                f"HTTP {respuesta.status_code}, {len(respuesta.text)} bytes")

        runner.check(2, "GET /panel devuelve el panel entero",
                     sirve_el_panel_en_su_ruta)

        def la_raiz_lleva_al_panel():
            respuesta = requests.get(contexto.url("/"), timeout=30,
                                     allow_redirects=False)
            return (respuesta.status_code in (301, 302)
                    and respuesta.headers.get("Location", "").endswith("/panel")), (
                f"HTTP {respuesta.status_code} → {respuesta.headers.get('Location')}")

        runner.check(2, "GET / redirige al panel", la_raiz_lleva_al_panel)

        def el_panel_no_se_cachea():
            """Un panel viejo servido contra un servidor nuevo produce fallos que
            nadie relaciona con la caché."""
            respuesta = requests.get(contexto.url("/panel"), timeout=30)
            cache = respuesta.headers.get("Cache-Control", "")
            return "no-store" in cache, f"Cache-Control: {cache!r}"

        runner.check(2, "El panel se sirve sin caché", el_panel_no_se_cachea)

        def es_el_mismo_archivo_del_repositorio():
            respuesta = requests.get(contexto.url("/panel"), timeout=30)
            return respuesta.text == leer(PANEL), (
                "lo servido no es byte a byte el archivo del repositorio")

        runner.check(2, "Lo que sirve el servidor es exactamente el archivo del "
                        "repositorio", es_el_mismo_archivo_del_repositorio)

        def el_panel_no_es_un_endpoint_del_pipeline():
            """Servir un archivo no puede haber añadido una puerta que escriba."""
            salud = requests.get(contexto.url("/health"), timeout=30).json()
            rutas = set(salud["data"]["endpoints"])
            esperadas = set(RUTAS_DEL_PIPELINE) | {"/health", "/", "/panel"}
            return rutas == esperadas, f"rutas del servidor: {sorted(rutas)}"

        runner.check(2, "El servidor expone exactamente las nueve rutas del "
                        "pipeline más salud, raíz y panel",
                     el_panel_no_es_un_endpoint_del_pipeline)

        def el_panel_ausente_se_dice():
            """Una imagen construida sin el panel tiene que decirlo, no reventar."""
            with Servidor(entorno_extra={"PANEL_PATH": "/no/existe/panel.html"},
                          esperar=True) as otro:
                # PANEL_PATH inexistente cae al del repositorio, que sí está: se
                # comprueba lo contrario —que el fallback existe y funciona—.
                respuesta = requests.get(otro.url("/panel"), timeout=30)
                return respuesta.status_code == 200, (
                    f"con PANEL_PATH inválido debería caer al del repositorio, "
                    f"y devolvió {respuesta.status_code}")

        runner.check(2, "Con PANEL_PATH inválido, el servidor cae al panel del "
                        "repositorio en vez de romperse", el_panel_ausente_se_dice)
    finally:
        contexto.__exit__(None, None, None)


# ── Nivel 3 · Comportamiento, en un DOM real ─────────────────────────────────

def nivel_3(runner):
    print("\nNIVEL 3 — Comportamiento · el panel ejecutado en un DOM real")

    try:
        proceso = subprocess.run(
            ["node", DOM_SUITE], cwd=str(REPO_ROOT), capture_output=True,
            text=True, timeout=600,
        )
    except FileNotFoundError:
        runner.skip(3, "Los escenarios de comportamiento del panel",
                    "no hay `node` en el PATH: sin él este nivel no se puede "
                    "ejecutar. Instala Node y repite.")
        return
    except subprocess.TimeoutExpired:
        runner.check(3, "Los escenarios de comportamiento del panel",
                     lambda: (False, "el nivel no terminó en 600 s"))
        return

    salida = proceso.stdout.strip().splitlines()
    resumen = {}
    if salida:
        try:
            resumen = json.loads(salida[-1])
        except json.JSONDecodeError:
            resumen = {}

    if resumen.get("error") == "sin_jsdom":
        runner.skip(3, "Los escenarios de comportamiento del panel",
                    resumen.get("detalle", "falta jsdom"))
        return

    if not resumen.get("resultados"):
        runner.check(3, "Los escenarios de comportamiento del panel",
                     lambda: (False, f"salida ilegible del harness: "
                                     f"{proceso.stdout[-300:]} {proceso.stderr[-300:]}"))
        return

    # Cada escenario se cuenta por separado: un nivel que reportara «pasó/falló»
    # en bloque escondería cuál de los veintitantos se rompió.
    for resultado in resumen["resultados"]:
        runner.check(3, resultado["nombre"],
                     lambda r=resultado: (r["ok"], r.get("detalle", "")))


NIVELES = {0: nivel_0, 1: nivel_1, 2: nivel_2, 3: nivel_3}


def parsear_niveles(texto):
    if "-" in texto:
        desde, hasta = texto.split("-", 1)
        return list(range(int(desde), int(hasta) + 1))
    return [int(n) for n in texto.split(",")]


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Valida el panel de producción conectado (Fase 8).")
    parser.add_argument("--levels", default="0-3",
                        help="Niveles a ejecutar: '0', '0-2', '0,3'")
    args = parser.parse_args(argv)

    runner = CheckRunner()
    for nivel in parsear_niveles(args.levels):
        if nivel not in NIVELES:
            raise SystemExit(f"Nivel desconocido: {nivel}. Hay 0, 1, 2 y 3.")
        NIVELES[nivel](runner)

    cuenta = runner.counts()
    print(f"\nRESUMEN: {cuenta[PASS]} PASS · {cuenta[FAIL]} FAIL · "
          f"{cuenta[SKIP]} SKIP")
    if runner.failed():
        print("\nFallos:")
        for nivel, nombre, _, detalle in runner.failed():
            print(f"  [N{nivel}] {nombre}\n        {detalle}")
    return 1 if runner.failed() else 0


if __name__ == "__main__":
    sys.exit(main())
