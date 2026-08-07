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
    """
    credentials = _load_credentials()
    if force_refresh or not credentials.valid:
        try:
            credentials.refresh(google.auth.transport.requests.Request())
        except Exception as exc:
            raise AuthError(f"No se pudo refrescar el token ADC: {exc}") from exc
    return credentials.token


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
                max_retries=3, base_delay=1.0, timeout=60):
    """Llamada a la API con refresco de token ante 401 y backoff ante 429.

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

    for attempt in range(max_retries):
        response = requests.request(
            method, url, headers=get_headers(project), json=body, params=params,
            timeout=timeout,
        )
        if response.status_code == 401 and not already_refreshed:
            already_refreshed = True
            response = requests.request(
                method, url,
                headers=get_headers(project, force_refresh=True),
                json=body, params=params, timeout=timeout,
            )
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


def list_cx_agents_everywhere(project):
    """Agentes de un proyecto en todas las regiones, con la región de cada uno.

    El panel ofrece un desplegable de agentes por proyecto, y un agente puede
    vivir en cualquier región. Recorrer solo una dejaría fuera agentes reales
    sin decirlo.
    """
    found = []
    for region in list_cx_locations(project):
        try:
            for agent in list_cx_agents(project, region):
                found.append({**agent, "region": region})
        except ApiError:
            # Una región que rechaza el LIST no invalida el resto: puede ser
            # una región donde el proyecto no tiene la API habilitada.
            continue
    return sorted(found, key=lambda item: item["displayName"].lower())


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
