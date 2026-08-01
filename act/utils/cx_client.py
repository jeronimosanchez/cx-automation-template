#!/usr/bin/env python3
"""
act/utils/cx_client.py — Cliente HTTP para la API REST v3beta1 de Dialogflow CX.

Primitivas de conexión reutilizables por el pipeline: auth, helpers HTTP,
paginación, polling de operaciones largas y descubrimiento de proyectos y
agentes.

El proyecto y el agente nunca son constantes de módulo: cada función los
recibe como parámetro, porque el pipeline opera sobre más de un agente.
La región sí es fija — europe-west1 es la única validada en producción.
"""

import subprocess
import time

import requests


LOCATION = "europe-west1"
BASE = f"https://{LOCATION}-dialogflow.googleapis.com/v3beta1"
RESOURCE_MANAGER_BASE = "https://cloudresourcemanager.googleapis.com/v1"

OPERATION_MAX_ATTEMPTS = 60
OPERATION_DELAY_SECONDS = 5


class AuthError(RuntimeError):
    """gcloud no disponible o sin sesión iniciada."""


class ApiError(RuntimeError):
    """La API respondió con un estado inesperado."""

    def __init__(self, message, status_code=None):
        super().__init__(message)
        self.status_code = status_code


class ProjectListPermissionError(ApiError):
    """Faltan permisos de Resource Manager para listar proyectos.

    Se distingue del resto de errores porque tiene una salida concreta:
    el panel ofrece escribir el ID del proyecto a mano.
    """


class OperationTimeout(RuntimeError):
    """Una operación de larga duración no terminó dentro del límite."""


# ── Auth ─────────────────────────────────────────────────────────────────────

_cached_token = None


def _fetch_token():
    try:
        return subprocess.check_output(
            ["gcloud", "auth", "print-access-token"],
            text=True,
        ).strip()
    except FileNotFoundError as exc:
        raise AuthError(
            "gcloud no encontrado en PATH. Instala Google Cloud SDK."
        ) from exc
    except subprocess.CalledProcessError as exc:
        raise AuthError(
            "gcloud no autenticado. Ejecuta `gcloud auth login` y reintenta."
        ) from exc


def get_token(force_refresh=False):
    """Token de acceso, cacheado para todo el run.

    Decisión validada: nunca google.auth.default() — ADC con quota project
    causó problemas en Sprint 1. gcloud directo es la única vía validada.
    """
    global _cached_token
    if _cached_token is None or force_refresh:
        _cached_token = _fetch_token()
    return _cached_token


def get_headers(project, force_refresh=False):
    return {
        "Authorization": f"Bearer {get_token(force_refresh)}",
        "Content-Type": "application/json",
        "x-goog-user-project": project,
    }


def build_parent(project, agent_id):
    return f"projects/{project}/locations/{LOCATION}/agents/{agent_id}"


# ── HTTP helpers ─────────────────────────────────────────────────────────────

def api_request(method, project, path, body=None, params=None,
                max_retries=3, base_delay=1.0):
    """Llamada a la API con refresco de token ante 401 y backoff ante 429.

    El token se obtiene una vez por run, pero los Pasos 6 y 7 son gates
    manuales que pueden durar horas — tiempo de sobra para que expire a
    mitad del pipeline. Por eso el 401 se reintenta con token fresco en
    lugar de abortar.
    """
    url = path if path.startswith("http") else f"{BASE}/{path}"
    already_refreshed = False
    response = None

    for attempt in range(max_retries):
        response = requests.request(
            method, url, headers=get_headers(project), json=body, params=params
        )
        if response.status_code == 401 and not already_refreshed:
            already_refreshed = True
            response = requests.request(
                method, url,
                headers=get_headers(project, force_refresh=True),
                json=body, params=params,
            )
        if response.status_code != 429:
            return response
        if attempt < max_retries - 1:
            time.sleep(base_delay * (2 ** attempt))

    return response


def api_get(project, path, params=None):
    return api_request("GET", project, path, params=params)


def api_post(project, path, body):
    return api_request("POST", project, path, body=body)


def api_patch(project, path, body, params=None):
    return api_request("PATCH", project, path, body=body, params=params)


def api_delete(project, path):
    return api_request("DELETE", project, path)


# ── Retry genérico ───────────────────────────────────────────────────────────

def retry_with_backoff(func, max_retries=3, base_delay=1.0):
    """Reintenta func() con backoff exponencial.

    Para trabajo que no es una llamada HTTP directa — las llamadas a la API
    ya reintentan por su cuenta dentro de api_request().
    """
    last_error = None
    for attempt in range(max_retries):
        try:
            return func()
        except Exception as error:
            last_error = error
            if attempt < max_retries - 1:
                time.sleep(base_delay * (2 ** attempt))
    raise last_error


# ── Paginación ───────────────────────────────────────────────────────────────

def list_all_pages(project, path, resource_key, page_size=100):
    """Recorre todas las páginas de un endpoint LIST y devuelve la lista completa.

    resource_key es el campo del JSON que contiene los ítems
    (e.g. 'playbooks', 'examples', 'tools').
    """
    items = []
    next_token = None
    while True:
        params = {"pageSize": page_size}
        if next_token:
            params["pageToken"] = next_token
        response = api_get(project, path, params=params)
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

def poll_operation(project, operation_name,
                   max_attempts=OPERATION_MAX_ATTEMPTS,
                   delay=OPERATION_DELAY_SECONDS):
    """Consulta una LRO hasta done:true y devuelve la operación terminada.

    POST /versions responde 200 OK al instante pero sigue procesando en
    segundo plano. Sin este polling, el paso siguiente trabajaría sobre una
    versión a medio crear.
    """
    for _ in range(max_attempts):
        response = api_get(project, operation_name)
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
        time.sleep(delay)

    raise OperationTimeout(
        f"La operación {operation_name} no terminó tras "
        f"{max_attempts} intentos ({max_attempts * delay}s). "
        f"Último estado: {operation}"
    )


def resolve_operation(project, response, max_attempts=OPERATION_MAX_ATTEMPTS,
                      delay=OPERATION_DELAY_SECONDS):
    """Devuelve el recurso, poleando antes si la respuesta era una operación.

    Varios endpoints (POST /versions, PATCH /environments) responden 200 OK
    con {"name": ".../operations/..."} en lugar del recurso pedido, y el
    fallo real llega después dentro de la operación. Sin polear, un code:3
    queda invisible y el paso se reporta como correcto.

    Centralizado aquí a propósito: si cada punto de llamada tuviera que
    acordarse de polear, bastaría olvidarlo en uno para reabrir el agujero.
    """
    payload = response.json() if response.text else {}
    operation_name = payload.get("name", "")
    if "/operations/" not in operation_name:
        return payload
    operation = poll_operation(project, operation_name, max_attempts, delay)
    return operation.get("response", operation)


# ── Descubrimiento de proyectos y agentes ────────────────────────────────────

def list_gcp_projects():
    """Proyectos GCP activos visibles con las credenciales actuales.

    Va contra Cloud Resource Manager, no contra Dialogflow CX: es otra API,
    con su propio permiso IAM (resourcemanager.projects.list). Una cuenta
    puede tener acceso a CX sin tenerlo, de ahí el error diferenciado.

    Tampoco manda x-goog-user-project: el proyecto es justamente lo que
    todavía no se ha elegido cuando se llama a esta función.
    """
    headers = {
        "Authorization": f"Bearer {get_token()}",
        "Content-Type": "application/json",
    }
    projects = []
    next_token = None

    while True:
        params = {"pageSize": 200}
        if next_token:
            params["pageToken"] = next_token
        response = requests.get(
            f"{RESOURCE_MANAGER_BASE}/projects", headers=headers, params=params
        )
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


def list_cx_agents(project):
    """Agentes CX de un proyecto en la región fija europe-west1."""
    agents = list_all_pages(
        project, f"projects/{project}/locations/{LOCATION}/agents", "agents"
    )
    return [
        {
            "agentId": agent["name"].rsplit("/", 1)[-1],
            "displayName": agent.get("displayName", ""),
            "name": agent["name"],
        }
        for agent in agents
    ]
