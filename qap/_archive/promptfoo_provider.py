"""
qa/promptfoo_provider.py — Custom Python provider para Promptfoo.

Llama a Dialogflow CX (REST v3beta1, detectIntent) con el `prompt` recibido
y devuelve la respuesta del agente. Lee la config del agente de
`definitions/agent.yaml` (project, location, agent_id) y autentica via
`gcloud auth print-access-token` (decision tecnica no negociable).

Promptfoo invoca:
    call_api(prompt: str, options: dict, context: dict) -> dict
y espera un retorno con clave `output: str` (o `error: str`).

Cada llamada usa una `session_id` aleatoria por defecto. Si necesitas
mantener contexto entre turnos (multi-turno), pasa `session_id` en
`config.session_id` del provider en `promptfooconfig.yaml`.
"""
from __future__ import annotations

import os
import subprocess
import sys
import uuid
from pathlib import Path

import requests
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
AGENT_YAML = REPO_ROOT / "definitions" / "agent.yaml"


def _load_agent_config() -> dict:
    with open(AGENT_YAML) as f:
        return yaml.safe_load(f)


def _get_token() -> str:
    """Token via gcloud — decision tecnica no negociable."""
    r = subprocess.run(
        ["gcloud", "auth", "print-access-token"],
        capture_output=True, text=True, check=True,
    )
    return r.stdout.strip()


def _build_headers(cfg: dict, token: str) -> dict:
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    extra = (cfg.get("api") or {}).get("required_headers") or {}
    headers.update(extra)
    return headers


def _detect_intent_url(cfg: dict, session_id: str) -> str:
    base = cfg["api"]["base_v3beta1"]
    return (
        f"{base}/projects/{cfg['project']}/locations/{cfg['location']}"
        f"/agents/{cfg['agent_id']}/sessions/{session_id}:detectIntent"
    )


def _extract_text(query_result: dict) -> str:
    chunks = []
    for msg in query_result.get("responseMessages", []) or []:
        if "text" in msg:
            for t in msg["text"].get("text", []) or []:
                if t:
                    chunks.append(t)
    return "\n".join(chunks)


def call_api(prompt: str, options: dict | None = None, context: dict | None = None) -> dict:
    options = options or {}
    config = options.get("config") or {}
    cfg = _load_agent_config()
    session_id = (
        config.get("session_id")
        or os.environ.get("CX_SESSION_ID")
        or f"qa-{uuid.uuid4()}"
    )
    language = config.get("language_code", "es")

    try:
        token = _get_token()
    except subprocess.CalledProcessError as e:
        return {"error": f"gcloud auth print-access-token fallo: {e.stderr}"}

    headers = _build_headers(cfg, token)
    url = _detect_intent_url(cfg, session_id)
    payload = {
        "queryInput": {
            "text": {"text": prompt},
            "languageCode": language,
        }
    }

    r = requests.post(url, headers=headers, json=payload, timeout=30)
    if r.status_code != 200:
        return {"error": f"CX detectIntent {r.status_code}: {r.text[:500]}"}

    body = r.json()
    text = _extract_text(body.get("queryResult", {}))
    return {
        "output": text,
        "metadata": {
            "session_id": session_id,
            "match_type": body.get("queryResult", {}).get("match", {}).get("matchType"),
        },
    }


if __name__ == "__main__":
    prompt = sys.argv[1] if len(sys.argv) > 1 else "hola"
    result = call_api(prompt)
    print(result)
