#!/usr/bin/env python3
"""
act/utils/cx_client_cloudrun.py — Cliente HTTP de la API v3beta1 de Dialogflow
CX para el pipeline que corre en Cloud Run.

Clon de act/utils/cx_client.py. No lo importa ni depende de él en tiempo de
ejecución: la regla de nomenclatura de la Fase 1 obliga a clonar en vez de
reutilizar, para que el pipeline cloud no quede atado a un archivo del local.

Tres diferencias de fondo con el original:

1. La región nunca es constante de módulo. En el local `LOCATION` estaba
   cableada a europe-west1 y `BASE` se construía con ella. Aquí proyecto,
   agente y región entran siempre por parámetro — el servidor atiende a
   cualquier agente de cualquier proyecto (S4).

2. La autenticación es ADC, no `gcloud auth print-access-token`. En Cloud Run
   no hay sesión humana ni binario de gcloud. Verificado contra la API que ADC
   se comporta igual que la sesión local siempre que viaje la cabecera
   `x-goog-user-project`; sin ella, 403.

3. Nunca acepta una URL completa como destino. En el local,
   `url = path if path.startswith("http") else ...` permitía que quien llamara
   dirigiera el token del servicio a cualquier host. Aquí eso es un error
   explícito: todas las URLs se construyen desde project + region (C3).
"""

import base64
import concurrent.futures
import threading

import google.auth
import google.auth.transport.requests
import requests


GLOBAL_HOST = "https://dialogflow.googleapis.com"
RESOURCE_MANAGER_BASE = "https://cloudresourcemanager.googleapis.com/v1"
SECRET_MANAGER_BASE = "https://secretmanager.googleapis.com/v1"

API_VERSION = "v3beta1"
SCOPES = ["https://www.googleapis.com/auth/cloud-platform"]

OPERATION_MAX_ATTEMPTS = 60
OPERATION_DELAY_SECONDS = 5


class AuthError(RuntimeError):
    """No hay credenciales por defecto disponibles, o no se pueden refrescar."""


class ApiError(RuntimeError):
    """La API respondió con un estado inesperado."""

    def __init__(self, message, status_code=None):
        super().__init__(message)
        self.status_code = status_code


class ProjectListPermissionError(ApiError):
    """Faltan permisos de Resource Manager para listar proyectos.

    Se distingue del resto porque tiene una salida concreta: el panel ofrece
    escribir el ID del proyecto a mano.
    """


class RegionNotFound(RuntimeError):
    """Ninguna región de CX reconoce ese agente."""


class OperationTimeout(RuntimeError):
    """Una operación de larga duración no terminó dentro del límite."""


# ── Auth (ADC) ───────────────────────────────────────────────────────────────
#
# Las credenciales se cachean porque son siempre las mismas (la cuenta de
# servicio del propio Cloud Run). El proyecto NO se cachea con ellas: viaja en
# `x-goog-user-project`, que se construye en cada llamada. Un contenedor
# reutilizado entre peticiones de dos agentes distintos comparte credenciales
# pero nunca cabecera de cuota.

_credentials = None
_credentials_lock = threading.Lock()


def _load_credentials():
    global _credentials
    with _credentials_lock:
        if _credentials is None:
            try:
                _credentials, _ = google.auth.default(scopes=SCOPES)
            except google.auth.exceptions.DefaultCredentialsError as exc:
                raise AuthError(
                    "Sin credenciales por defecto (ADC). En Cloud Run las "
                    "inyecta la plataforma; en local, ejecuta "
                    "`gcloud auth application-default login`."
                ) from exc
        return _credentials


def get_token(force_refresh=False):
    """Token de acceso vía ADC, refrescado cuando caduca.

    Nunca se registra en ningún log: los logs de Cloud Run se comparten entre
    invocaciones del mismo servicio.

    El refresco va bajo candado, y se vuelve a comprobar dentro. Desde que el
    descubrimiento pregunta a varias regiones **a la vez**
    (`list_cx_agents_everywhere`), varios hilos comparten este mismo objeto de
    credenciales: `google.auth` no lo protege por su cuenta, así que sin el
    candado dos hilos pueden escribirle el token al mismo tiempo, y sin la
    segunda comprobación los seis del pool pagan seis refrescos seguidos por un
    token que ya había renovado el primero.
    """
    credentials = _load_credentials()
    if force_refresh or not credentials.valid:
        with _credentials_lock:
            if force_refresh or not credentials.valid:
                try:
                    credentials.refresh(google.auth.transport.requests.Request())
                except Exception as exc:
                    raise AuthError(
                        f"No se pudo refrescar el token ADC: {exc}") from exc
    return credentials.token


def runtime_service_account():
    """El email de la cuenta que este proceso está usando de verdad.

    Es lo que va en el comando IAM que la herramienta de vincular muestra para
    ejecutar a mano: un placeholder como `$ACT_SERVICE_ACCOUNT` produce, al
    pegarlo en una terminal donde esa variable no existe, un `--member=` vacío
    y un error de sintaxis de gcloud que no dice nada del alta. Y es el único
    paso del onboarding que ocurre fuera del panel, así que tiene que poder
    seguirse copiando y pegando.

    Se pregunta en vez de deducirse: en Cloud Run la cuenta la pone la
    plataforma, y en local es la de quien haya hecho el login.
    """
    credentials = _load_credentials()
    email = getattr(credentials, "service_account_email", None)
    if email and email != "default":
        return email

    # En Cloud Run las credenciales llegan de la plataforma y `google.auth`
    # las expone con `service_account_email == "default"`: el nombre real no
    # viaja en ellas. Quien lo tiene es el servidor de metadatos, y es la vía
    # documentada para preguntárselo desde dentro de la instancia.
    #
    # Este caso se descubrió con el servicio ya desplegado: la función caía
    # hasta el `userinfo` de abajo, que **no devuelve email para el token de
    # una cuenta de servicio**, y acababa lanzando el error de más abajo. O
    # sea: el comando IAM que el panel enseña para ejecutar a mano no se podía
    # construir precisamente donde hace falta, en producción.
    try:
        respuesta = requests.get(
            "http://metadata.google.internal/computeMetadata/v1/instance/"
            "service-accounts/default/email",
            headers={"Metadata-Flavor": "Google"}, timeout=5,
        )
        if respuesta.status_code == 200 and "@" in respuesta.text:
            return respuesta.text.strip()
    except requests.exceptions.RequestException:
        # Fuera de GCP ese host no existe. No es un fallo: significa que se
        # está corriendo en local, y ahí sirve el `userinfo` de abajo.
        pass

    respuesta = requests.get(
        "https://www.googleapis.com/oauth2/v3/userinfo",
        headers={"Authorization": f"Bearer {get_token()}"}, timeout=30,
    )
    if respuesta.status_code == 200 and respuesta.json().get("email"):
        return respuesta.json()["email"]
    raise AuthError(
        "No se pudo averiguar con qué cuenta está corriendo este proceso, y "
        "sin ella el comando IAM que hay que ejecutar a mano no se puede "
        "construir completo."
    )


def get_headers(project, force_refresh=False):
    if not project:
        raise ValueError("get_headers exige un project — no hay valor por defecto.")
    return {
        "Authorization": f"Bearer {get_token(force_refresh)}",
        "Content-Type": "application/json",
        "x-goog-user-project": project,
    }


# ── Construcción de rutas ────────────────────────────────────────────────────

def build_base(region):
    """Host de la API para una región.

    `global` no lleva prefijo en el host; el resto de regiones sí. Es la única
    excepción, y va aquí para que ningún punto de llamada tenga que conocerla.
    """
    if not region:
        raise ValueError("build_base exige una región — no hay valor por defecto.")
    if region == "global":
        return f"{GLOBAL_HOST}/{API_VERSION}"
    return f"https://{region}-dialogflow.googleapis.com/{API_VERSION}"


def build_parent(project, region, agent_id):
    if not (project and region and agent_id):
        raise ValueError(
            "build_parent exige project, region y agent_id — ninguno tiene "
            "valor por defecto."
        )
    return f"projects/{project}/locations/{region}/agents/{agent_id}"


# ── HTTP ─────────────────────────────────────────────────────────────────────

def api_request(method, project, region, path, body=None, params=None,
                max_retries=5, base_delay=2.0, timeout=60):
    """Llamada a la API con refresco de token ante 401 y backoff ante 429.

    El backoff espera hasta ~30s repartidos en cinco intentos (2+4+8+16), no
    los ~7s de tres intentos que había antes. La cuota de CX que dispara el 429
    es **por minuto**, así que rendirse a los siete segundos era rendirse
    dentro de la misma ventana que había que dejar pasar. Salió en una tanda de
    validación real: dos corridas seguidas del nivel de escritura tumbaron un
    check con un 429, y el paso siguiente lo leyó como un fallo del pipeline.
    Un agente grande puede llegar al límite por sí solo — el inventario lee los
    13 tipos y las versiones de cada contenedor.

    **Un corte de red se reintenta como un 429.** No es un código de estado
    sino una excepción, así que antes subía directa y abortaba el paso entero:
    un segundo de conexión caída a mitad del Paso 3 deja el borrador escrito a
    medias, y a mitad del Paso 5 deja versiones creadas sin entorno apuntado.
    El pipeline hace cientos de llamadas por corrida — un transitorio de red no
    es un caso raro. Solo se reintenta lo que es seguro reintentar por sí solo:
    si la conexión se cae **sin respuesta**, la petición no llegó a completarse
    y repetirla no duplica nada. Un timeout de lectura no entra aquí: ahí el
    servidor pudo haber procesado la escritura y repetirla sí podría duplicar.

    `path` es siempre un nombre de recurso relativo (`projects/…/playbooks/…`).
    Una URL absoluta es un error, no un atajo: el token de la cuenta de
    servicio no puede acabar apuntando a un host que decida quien llama (C3).
    """
    if path.startswith("http"):
        raise ValueError(
            "api_request no acepta URLs absolutas — pasa el nombre de recurso "
            f"relativo. Recibido: {path[:80]}"
        )

    url = f"{build_base(region)}/{path.lstrip('/')}"
    already_refreshed = False
    response = None
    ultimo_corte = None

    for attempt in range(max_retries):
        try:
            response = requests.request(
                method, url, headers=get_headers(project), json=body,
                params=params, timeout=timeout,
            )
            if response.status_code == 401 and not already_refreshed:
                already_refreshed = True
                response = requests.request(
                    method, url,
                    headers=get_headers(project, force_refresh=True),
                    json=body, params=params, timeout=timeout,
                )
        except requests.exceptions.ConnectionError as error:
            ultimo_corte = error
            if attempt < max_retries - 1:
                _sleep(base_delay * (2 ** attempt))
                continue
            raise ApiError(
                f"La conexión con la API se cayó {max_retries} veces seguidas "
                f"al llamar a {method} {path[:80]}. No se ha completado la "
                f"petición: {ultimo_corte}"
            ) from ultimo_corte
        if response.status_code != 429:
            _comprobar_region(response, region)
            return response
        if attempt < max_retries - 1:
            _sleep(base_delay * (2 ** attempt))

    _comprobar_region(response, region)
    return response


def _comprobar_region(response, region):
    """Convierte el 404 de un host inexistente en un error de región.

    Una región que no existe produce un host que tampoco existe, y Google
    responde con su página de error en HTML — no con un JSON de la API. Sin
    esta traducción, un valor equivocado en Firestore llega a quien lo depura
    como un 404 con una página web dentro, sin ninguna pista de que el
    problema era la región.

    Se distingue del 404 legítimo —la API responde JSON diciendo qué recurso
    no encontró— por el tipo de contenido, no por el código de estado.
    """
    if response.status_code != 404:
        return
    if "application/json" in response.headers.get("Content-Type", ""):
        return
    raise ApiError(
        f"La región '{region}' no corresponde a ningún endpoint de Dialogflow "
        f"CX: la petición no llegó a la API. Revisa la región guardada para "
        f"este agente.",
        status_code=404,
    )


def _sleep(seconds):
    """Aislado para que los tests puedan sustituirlo sin esperar de verdad."""
    import time
    time.sleep(seconds)


def api_get(project, region, path, params=None):
    return api_request("GET", project, region, path, params=params)


def api_post(project, region, path, body):
    return api_request("POST", project, region, path, body=body)


def api_patch(project, region, path, body, params=None):
    return api_request("PATCH", project, region, path, body=body, params=params)


def api_delete(project, region, path):
    return api_request("DELETE", project, region, path)


# ── Paginación ───────────────────────────────────────────────────────────────

def list_all_pages(project, region, path, resource_key, page_size=100):
    """Recorre todas las páginas de un LIST y devuelve la lista completa."""
    items = []
    next_token = None
    while True:
        params = {"pageSize": page_size}
        if next_token:
            params["pageToken"] = next_token
        response = api_get(project, region, path, params=params)
        if response.status_code != 200:
            raise ApiError(
                f"LIST {path} falló: {response.status_code} {response.text[:300]}",
                status_code=response.status_code,
            )
        payload = response.json()
        items.extend(payload.get(resource_key, []))
        next_token = payload.get("nextPageToken")
        if not next_token:
            break
    return items


# ── Operaciones de larga duración ────────────────────────────────────────────

def poll_operation(project, region, operation_name,
                   max_attempts=OPERATION_MAX_ATTEMPTS,
                   delay=OPERATION_DELAY_SECONDS):
    """Consulta una LRO hasta done:true y devuelve la operación terminada.

    POST /versions responde 200 OK al instante pero sigue procesando por
    detrás, y el fallo real (code:3 por displayName ausente) llega dentro de
    la operación. Sin este polling el paso se reportaría como correcto.
    """
    operation = None
    for _ in range(max_attempts):
        response = api_get(project, region, operation_name)
        if response.status_code != 200:
            raise ApiError(
                f"GET {operation_name} falló: "
                f"{response.status_code} {response.text[:300]}",
                status_code=response.status_code,
            )
        operation = response.json()
        if operation.get("done"):
            if "error" in operation:
                raise ApiError(
                    f"La operación {operation_name} terminó con error: "
                    f"{operation['error']}"
                )
            return operation
        _sleep(delay)

    raise OperationTimeout(
        f"La operación {operation_name} no terminó tras {max_attempts} "
        f"intentos ({max_attempts * delay}s). Último estado: {operation}"
    )


def resolve_operation(project, region, response,
                      max_attempts=OPERATION_MAX_ATTEMPTS,
                      delay=OPERATION_DELAY_SECONDS):
    """Devuelve el recurso, poleando antes si la respuesta era una operación.

    Centralizado a propósito: si cada punto de llamada tuviera que acordarse
    de polear, bastaría olvidarlo en uno para reabrir el agujero.
    """
    payload = response.json() if response.text else {}
    operation_name = payload.get("name", "")
    if "/operations/" not in operation_name:
        return payload
    operation = poll_operation(project, region, operation_name, max_attempts, delay)
    return operation.get("response", operation)


# ── Descubrimiento de proyectos, regiones y agentes ──────────────────────────

def list_gcp_projects():
    """Proyectos GCP activos visibles con las credenciales actuales.

    Va contra Cloud Resource Manager, no contra Dialogflow CX: es otra API,
    con su propio permiso (resourcemanager.projects.list). Una cuenta puede
    tener acceso a CX sin tenerlo, de ahí el error diferenciado.

    No manda x-goog-user-project: el proyecto es justamente lo que todavía no
    se ha elegido cuando se llama a esta función.
    """
    def pedir(params, force_refresh=False):
        return requests.get(
            f"{RESOURCE_MANAGER_BASE}/projects",
            headers={"Authorization": f"Bearer {get_token(force_refresh)}",
                     "Content-Type": "application/json"},
            params=params, timeout=60,
        )

    projects = []
    next_token = None

    while True:
        params = {"pageSize": 200}
        if next_token:
            params["pageToken"] = next_token
        response = pedir(params)
        if response.status_code == 401:
            response = pedir(params, force_refresh=True)
        if response.status_code == 403:
            raise ProjectListPermissionError(
                "Sin permiso para listar proyectos GCP: falta "
                "resourcemanager.projects.list en Cloud Resource Manager. "
                "Escribe el ID del proyecto a mano.",
                status_code=403,
            )
        if response.status_code != 200:
            raise ApiError(
                f"LIST de proyectos falló: "
                f"{response.status_code} {response.text[:300]}",
                status_code=response.status_code,
            )
        payload = response.json()
        projects.extend(
            {"projectId": item["projectId"], "name": item.get("name", "")}
            for item in payload.get("projects", [])
            if item.get("lifecycleState") == "ACTIVE"
        )
        next_token = payload.get("nextPageToken")
        if not next_token:
            break

    return sorted(projects, key=lambda item: item["projectId"])


def list_cx_locations(project):
    """Regiones donde la API de CX admite agentes, preguntadas a la propia API.

    Se pregunta en lugar de mantener una lista fija: el número de regiones de
    CX ha crecido varias veces, y una lista cableada convierte una región
    nueva en un agente indetectable sin que nada lo avise.

    Sin paginar, a diferencia del resto de LIST de la API: este endpoint la
    rechaza explícitamente con 400 ("Pagination for ListLocations is not
    supported") si se le manda `pageSize`. Verificado contra la API real.
    """
    response = api_get(project, "global", f"projects/{project}/locations")
    if response.status_code != 200:
        raise ApiError(
            f"No se pudieron listar las regiones de CX de {project}: "
            f"{response.status_code} {response.text[:300]}",
            status_code=response.status_code,
        )
    return [
        item["locationId"]
        for item in response.json().get("locations", [])
        if item.get("locationId")
    ]


def detect_agent_region(project, agent_id):
    """Región en la que vive un agente, probando las que admite la API.

    Se ejecuta una sola vez, al vincular el agente con su repositorio, y el
    resultado queda guardado (S4). Preguntarle la región a quien lo usa es
    más frágil que detectarla: un valor erróneo produce un 404 sin contexto.
    """
    for region in list_cx_locations(project):
        response = api_get(
            project, region, build_parent(project, region, agent_id)
        )
        if response.status_code == 200:
            return region
    raise RegionNotFound(
        f"El agente {agent_id} no aparece en ninguna región de CX del "
        f"proyecto {project}. Comprueba el ID del agente y el proyecto."
    )


def list_cx_agents(project, region):
    agents = list_all_pages(
        project, region, f"projects/{project}/locations/{region}/agents", "agents"
    )
    return [
        {
            "agentId": agent["name"].rsplit("/", 1)[-1],
            "displayName": agent.get("displayName", ""),
            "name": agent["name"],
        }
        for agent in agents
    ]


# Cuántas regiones se preguntan a la vez. Ni una (que es lo que había) ni las
# diecisiete: la cuota de CX que dispara el 429 es **por minuto**, y lanzar las
# diecisiete de golpe convierte en un pico lo que antes era un goteo. Con seis
# el descubrimiento cabe en unas tres tandas y el pico se queda muy por debajo
# de la cuota. `api_request` reintenta ante un 429, pero un reintento cuesta
# segundos: acotar es más barato que recuperarse.
REGIONES_A_LA_VEZ = 6


def list_cx_agents_everywhere(project, a_la_vez=REGIONES_A_LA_VEZ):
    """Agentes de un proyecto en todas las regiones, con la región de cada uno.

    Devuelve `(agentes, regiones_sin_contestar)`.

    El panel ofrece un desplegable de agentes por proyecto, y un agente puede
    vivir en cualquier región. Recorrer solo una dejaría fuera agentes reales
    sin decirlo, y la API de CX no tiene ningún listado que cruce regiones: su
    llamada es siempre proyecto + región.

    **En paralelo, y no en serie.** Son diecisiete llamadas independientes
    entre sí y ninguna necesita el resultado de la anterior. En serie sumaban
    13-14 s medidos contra un proyecto real, con el desplegable en «cargando…»
    todo ese rato. La concurrencia va acotada — ver `REGIONES_A_LA_VEZ`.

    **El orden no depende de quién conteste antes.** Lo fija entera la clave de
    ordenación: nombre, y los empates los rompen la región y el identificador.
    Sin ese desempate, dos agentes con el mismo `displayName` quedan a merced
    de en qué orden liste las regiones la API —que no promete ninguno— y el
    desplegable baila entre recargas. Dos lecturas del mismo estado tienen que
    poder compararse.

    **Una región que falla se nombra, no se calla.** Antes se hacía `continue`
    y el agente que vivía ahí desaparecía del desplegable como si no existiera
    — y lo que se hace entonces es crear otro. Se devuelve lo encontrado, con
    la lista de las que no contestaron, porque un proyecto normalmente tiene
    regiones donde la API ni siquiera está habilitada: tumbar el descubrimiento
    entero por eso lo dejaría inservible para todo el mundo.

    **Salvo que fallen todas**, que entonces sí sube el error. Si ninguna
    contesta, el problema no es una región: son las credenciales, el permiso o
    la red. Devolver «cero agentes» con la lista de fallos al lado se lee como
    un proyecto vacío, y un proyecto vacío no tiene nada que arreglar.
    """
    regiones = list_cx_locations(project)
    if not regiones:
        return [], []

    # Una casilla por región. Cada hilo escribe solo en la suya, así que juntar
    # los resultados no necesita candado ni depende del orden de llegada — lo
    # que la lista de `caidas` sí necesita, y por eso se toca desde el hilo
    # principal, dentro del bucle de `as_completed`.
    por_region = [[] for _ in regiones]
    caidas = []
    primer_error = None

    with concurrent.futures.ThreadPoolExecutor(
            max_workers=min(a_la_vez, len(regiones)),
            thread_name_prefix="cx-descubrimiento") as pool:
        futuros = {pool.submit(list_cx_agents, project, region): (indice, region)
                   for indice, region in enumerate(regiones)}
        for futuro in concurrent.futures.as_completed(futuros):
            indice, region = futuros[futuro]
            try:
                por_region[indice] = [{**agente, "region": region}
                                      for agente in futuro.result()]
            except Exception as error:      # noqa: BLE001 — se reporta, no se traga
                # Amplio a propósito: dentro de un hilo, la excepción que no se
                # recoge aquí no sube a ningún sitio — se queda en el futuro y
                # el descubrimiento devuelve una lista corta sin decir por qué.
                if primer_error is None:
                    primer_error = error
                caidas.append({"region": region,
                               "error": f"{type(error).__name__}: {error}"})

    if len(caidas) == len(regiones):
        raise primer_error

    encontrados = [agente for bloque in por_region for agente in bloque]
    encontrados.sort(key=lambda item: (item["displayName"].lower(),
                                       item["region"], item["agentId"]))
    return encontrados, sorted(caidas, key=lambda item: item["region"])


# ── Secret Manager ───────────────────────────────────────────────────────────

def access_secret(project, secret_id, version="latest"):
    """Contenido de un secreto, por REST con el mismo token ADC.

    Por REST y no con la librería cliente porque es una sola llamada sin
    semántica especial — no compensa una dependencia más.
    """
    url = (f"{SECRET_MANAGER_BASE}/projects/{project}/secrets/{secret_id}"
           f"/versions/{version}:access")
    response = requests.get(
        url,
        headers={"Authorization": f"Bearer {get_token()}",
                 "x-goog-user-project": project},
        timeout=60,
    )
    if response.status_code != 200:
        raise ApiError(
            f"No se pudo leer el secreto {secret_id} de {project}: "
            f"{response.status_code} {response.text[:200]}",
            status_code=response.status_code,
        )
    return base64.b64decode(response.json()["payload"]["data"])
