#!/usr/bin/env python3
"""
act/server.py — Servidor HTTP local que expone el pipeline al panel.

Un endpoint por paso (POST /step/1 .. /step/8) más dos de descubrimiento
(GET /projects, GET /projects/<project>/agents), que el panel usa para
rellenar sus dos selectores.

Es un adaptador, no un segundo pipeline: cada endpoint delega en la función
correspondiente de act_cx_resources_deploy.py y devuelve su resultado tal
cual. Toda la lógica vive allí, y por eso el pipeline sigue funcionando por
CLI sin este servidor.

Arranque:
    python act/server.py            # puerto 5000
    PORT=8080 python act/server.py
"""

import os
import socket
import sys
import threading
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from flask import Flask, jsonify, request
from flask_cors import CORS

from act import act_cx_resources_deploy as pipeline
from act.utils import cx_client

app = Flask(__name__)

# El panel se abre desde file://, cuyo origen el navegador manda como "null".
# Sin CORS, cada llamada se bloquea antes de salir y el fallo solo se ve en la
# consola del navegador, nunca en el log del servidor.
CORS(app)

DEFAULT_PORT = 5000

# Un solo candado global, no uno por agente: dos deploys simultáneos sobre
# agentes distintos tampoco aportan nada aquí y sí abren la puerta a
# escrituras concurrentes. El pipeline es de un solo operador.
_operation_lock = threading.Lock()


def _optional_kwargs(step_number, body):
    """Parámetros que solo aceptan algunos pasos, tomados del body."""
    if step_number == 4:
        return {"operations": body.get("operations"),
                "only_pending": bool(body.get("only_pending", False))}
    if step_number == 5:
        return {"name": body.get("name")}
    if step_number in (6, 7):
        kwargs = {"previous_versions": body.get("previous_versions")}
        if body.get("decision"):
            kwargs["decision"] = body["decision"]
        return kwargs
    if step_number == 8:
        return {"version_names": body.get("version_names")}
    return {}


@app.post("/step/<int:step_number>")
def run_step(step_number):
    if step_number not in pipeline.STEP_FUNCTIONS:
        return jsonify(status="error", log=[f"El paso {step_number} no existe"],
                       data={}), 404

    body = request.get_json(silent=True) or {}
    project, agent = body.get("project"), body.get("agent")
    if not project or not agent:
        # Sin destino explícito no se ejecuta: el servidor no guarda la
        # selección entre peticiones y adivinarla sería operar sobre el
        # agente equivocado sin que nadie lo note.
        return jsonify(
            status="error",
            log=["Faltan 'project' y/o 'agent' en el body — el servidor no "
                 "aplica ningún valor por defecto."],
            data={"missing": [k for k, v in (("project", project), ("agent", agent))
                              if not v]},
        ), 400

    if not _operation_lock.acquire(blocking=False):
        return jsonify(
            status="busy",
            log=["Ya hay una operación en curso. Espera a que termine."],
            data={},
        ), 409

    try:
        step = pipeline.STEP_FUNCTIONS[step_number]
        result = step(project, agent,
                      dry_run=bool(body.get("dry_run", False)),
                      **_optional_kwargs(step_number, body))
        return jsonify(result), 200
    except (pipeline.PipelineError, cx_client.AuthError, cx_client.ApiError,
            cx_client.OperationTimeout) as error:
        return jsonify(status="error", log=[str(error)], data={}), 200
    finally:
        _operation_lock.release()


@app.get("/projects")
def list_projects():
    try:
        return jsonify(status="ok", log=[], data={"projects": cx_client.list_gcp_projects()}), 200
    except cx_client.ProjectListPermissionError as error:
        # Una cuenta puede tener acceso a Dialogflow CX sin permiso de
        # Resource Manager. El panel ofrece escribir el ID a mano, así que
        # necesita distinguir este caso de un error cualquiera.
        return jsonify(
            status="error",
            log=[str(error)],
            data={"reason": "missing_permission", "manual_entry": True},
        ), 200
    except (cx_client.AuthError, cx_client.ApiError) as error:
        return jsonify(status="error", log=[str(error)], data={}), 200


@app.get("/projects/<project>/agents")
def list_agents(project):
    try:
        return jsonify(status="ok", log=[],
                       data={"agents": cx_client.list_cx_agents(project)}), 200
    except (cx_client.AuthError, cx_client.ApiError) as error:
        return jsonify(status="error", log=[str(error)], data={}), 200


@app.get("/health")
def health():
    return jsonify(status="ok", log=["servidor en marcha"],
                   data={"steps": sorted(pipeline.STEP_FUNCTIONS)}), 200


def _avisar_si_el_puerto_esta_ocupado(port):
    """En macOS el receptor de AirPlay escucha en el 5000 sobre IPv6.

    Como este servidor solo se ata a IPv4, ambos conviven sin error — pero
    un navegador que resuelva `localhost` a ::1 acaba hablando con AirPlay,
    que devuelve 403 sin CORS. El panel usa 127.0.0.1 por eso; el aviso está
    aquí para quien lo abra a mano.
    """
    with socket.socket(socket.AF_INET6, socket.SOCK_STREAM) as probe:
        probe.settimeout(0.4)
        if probe.connect_ex(("::1", port)) == 0:
            print(f"AVISO: algo ocupa el puerto {port} sobre IPv6 (en macOS suele ser "
                  f"AirPlay Receiver). Usa http://127.0.0.1:{port}, no localhost, o "
                  f"desactiva AirPlay en Ajustes › General › AirDrop y Handoff.")


def main():
    port = int(os.environ.get("PORT", DEFAULT_PORT))
    _avisar_si_el_puerto_esta_ocupado(port)
    app.run(host="127.0.0.1", port=port, debug=False, threaded=True)


if __name__ == "__main__":
    main()
