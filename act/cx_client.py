#!/usr/bin/env python3
"""
act/cx_client.py — Cliente HTTP para la API REST v3beta1 de Dialogflow CX.

Contiene las primitivas de conexión reutilizables por cualquier script
del pipeline: auth, helpers HTTP, constantes de conexión, backoff y
paginación.
"""

import subprocess
import time
from pathlib import Path
import requests
import yaml


# ── Constantes de conexión (fuente única: definitions/agent.yaml) ────────────

_REPO_ROOT = Path(__file__).parent.parent
_agent_cfg = yaml.safe_load((_REPO_ROOT / "definitions" / "agent.yaml").read_text())

PROJECT  = _agent_cfg["project"]
LOCATION = _agent_cfg["location"]
AGENT_ID = _agent_cfg["agent_id"]
BASE     = f"https://{LOCATION}-dialogflow.googleapis.com/v3beta1"
PARENT   = f"projects/{PROJECT}/locations/{LOCATION}/agents/{AGENT_ID}"


# ── Auth ─────────────────────────────────────────────────────────────────────

def get_headers():
    """Token vía gcloud auth print-access-token + 3 headers obligatorios.

    Decisión validada: nunca usar google.auth.default() — ADC con quota
    project causó problemas en Sprint 1. gcloud directo es la única
    forma validada en producción.
    """
    try:
        token = subprocess.check_output(
            ["gcloud", "auth", "print-access-token"],
            text=True,
        ).strip()
    except FileNotFoundError as exc:
        raise RuntimeError(
            "gcloud no encontrado en PATH. Instala Google Cloud SDK."
        ) from exc
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(
            "gcloud no autenticado. Ejecuta `gcloud auth login` y reintenta."
        ) from exc
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "x-goog-user-project": PROJECT,
    }


# ── HTTP helpers ─────────────────────────────────────────────────────────────

def api_get(headers, path, params=None):
    url = path if path.startswith("http") else f"{BASE}/{path}"
    return requests.get(url, headers=headers, params=params)


def api_post(headers, path, body):
    url = path if path.startswith("http") else f"{BASE}/{path}"
    return requests.post(url, headers=headers, json=body)


def api_patch(headers, path, body, params=None):
    url = path if path.startswith("http") else f"{BASE}/{path}"
    return requests.patch(url, headers=headers, json=body, params=params)


def api_delete(headers, path):
    url = path if path.startswith("http") else f"{BASE}/{path}"
    return requests.delete(url, headers=headers)


# ── Retry con backoff exponencial ────────────────────────────────────────────

def retry_with_backoff(func, max_retries=3, base_delay=1.0):
    """Reintenta func() hasta max_retries veces con backoff exponencial.

    Pensado para absorber 429 y errores transitorios de la API.
    Levanta la última excepción si todos los reintentos fallan.
    """
    last_err = None
    for attempt in range(max_retries):
        try:
            return func()
        except Exception as e:
            last_err = e
            if attempt < max_retries - 1:
                time.sleep(base_delay * (2 ** attempt))
    raise last_err


# ── Paginación ───────────────────────────────────────────────────────────────

def list_all_pages(headers, path, resource_key, page_size=100):
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
        r = api_get(headers, path, params=params)
        if r.status_code != 200:
            raise RuntimeError(
                f"LIST {path} falló: {r.status_code} {r.text[:300]}"
            )
        data = r.json()
        items.extend(data.get(resource_key, []))
        next_token = data.get("nextPageToken")
        if not next_token:
            break
    return items
