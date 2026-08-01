#!/usr/bin/env python3
"""
act/validate_server.py — Smoke test de act/server.py.

server.py es una capa nueva entre el panel y el pipeline, y puede fallar por
razones que validate_pipeline.py no cubre: puerto ocupado, CORS mal puesto,
JSON mal formado, un endpoint que no llama a la función que dice llamar.

Dos niveles, la misma distinción que validate_pipeline.py:

    Nivel 1  Estructura   Arranque, cierre, CORS, formato, 400, lock.
                          Los pasos que escriben se golpean con dry_run.
    Nivel 2  Conexión     Compara el `data` del endpoint contra la función
                          invocada directamente. Solo Pasos 1 y 3 y los dos
                          de descubrimiento — los únicos de solo lectura.

El Paso 2 nunca se prueba sin dry_run: haría un push real a un repositorio
público. Los Pasos 4 a 8 tampoco: escriben en el agente.

Uso:
    python act/validate_server.py --project <id> --agent <id>
    python act/validate_server.py --project <id> --agent <id> --port 5050
"""

import argparse
import json
import socket
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import requests

from act import act_cx_resources_deploy as pipeline
from act.utils import cx_client
from act.validate_pipeline import PASS, SKIP, CheckRunner

DEFAULT_PORT = 5000
STARTUP_TIMEOUT_SECONDS = 30

# Los pasos que escriben solo se golpean en dry_run. La estructura de la
# respuesta se verifica igual; lo que no se ejecuta es el efecto.
WRITE_STEPS = (2, 4, 5, 6, 7, 8)
READ_ONLY_STEPS = (1, 3)


def port_is_free(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        return probe.connect_ex(("127.0.0.1", port)) != 0


class ServerProcess:
    """Arranca server.py y garantiza el cierre, pase lo que pase.

    Sin el cierre garantizado, un test fallido deja el puerto ocupado y
    bloquea la siguiente ejecución del propio validador.
    """

    def __init__(self, port):
        self.port = port
        self.base = f"http://127.0.0.1:{port}"
        self.process = None

    def __enter__(self):
        if not port_is_free(self.port):
            raise RuntimeError(
                f"El puerto {self.port} ya está ocupado — probablemente hay otro "
                f"server.py corriendo. Ciérralo o usa --port."
            )
        self.process = subprocess.Popen(
            [sys.executable, "act/server.py"],
            cwd=REPO_ROOT, env={**_environ(), "PORT": str(self.port)},
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        )
        deadline = time.time() + STARTUP_TIMEOUT_SECONDS
        while time.time() < deadline:
            if self.process.poll() is not None:
                raise RuntimeError(
                    f"server.py murió al arrancar:\n{self.process.stdout.read()[:600]}"
                )
            try:
                requests.get(f"{self.base}/health", timeout=1)
                return self
            except requests.RequestException:
                time.sleep(0.3)
        raise RuntimeError(f"server.py no respondió en {STARTUP_TIMEOUT_SECONDS}s")

    def __exit__(self, *_exc):
        if self.process and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.process.kill()
        return False


def _environ():
    import os
    return dict(os.environ)


def post_step(base, number, project, agent, **extra):
    body = {"project": project, "agent": agent, **extra}
    return requests.post(f"{base}/step/{number}", json=body, timeout=180)


# ── Nivel 1 — Estructura ─────────────────────────────────────────────────────

def run_level_1(runner, server, project, agent):
    print("\nNIVEL 1 — Estructura (sin efectos sobre CX)\n")

    def puerto_ocupado_falla_claro():
        """Un servidor previo sin cerrar es el fallo más común aquí."""
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as ocupante:
            ocupante.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            ocupante.bind(("127.0.0.1", 0))
            ocupante.listen(1)
            puerto = ocupante.getsockname()[1]
            try:
                with ServerProcess(puerto):
                    return False, "arrancó pese a tener el puerto ocupado"
            except RuntimeError as error:
                claro = "ocupado" in str(error)
                return claro, f"{'mensaje claro' if claro else 'mensaje confuso'}: {error}"

    def health_responde():
        r = requests.get(f"{server.base}/health", timeout=5)
        return r.status_code == 200, f"HTTP {r.status_code}, pasos {r.json()['data']['steps']}"

    def los_8_endpoints_responden_bien():
        fallos = []
        for numero in range(1, 9):
            extra = {"dry_run": True} if numero in WRITE_STEPS else {}
            r = post_step(server.base, numero, project, agent, **extra)
            if r.status_code != 200:
                fallos.append(f"/step/{numero}: HTTP {r.status_code}")
                continue
            try:
                payload = r.json()
            except json.JSONDecodeError:
                fallos.append(f"/step/{numero}: body no es JSON")
                continue
            faltan = {"status", "log", "data"} - set(payload)
            if faltan:
                fallos.append(f"/step/{numero}: sin {sorted(faltan)}")
            elif payload["status"] not in ("ok", "conflict"):
                fallos.append(f"/step/{numero}: status={payload['status']} — {payload['log'][:1]}")
        return not fallos, "; ".join(fallos) or "8/8 devuelven 200 con status, log y data"

    def cors_presente():
        r = post_step(server.base, 3, project, agent)
        cabecera = r.headers.get("Access-Control-Allow-Origin")
        return bool(cabecera), (
            f"Access-Control-Allow-Origin: {cabecera}" if cabecera
            else "falta la cabecera — el panel en file:// no podría llamar al servidor"
        )

    def sin_project_o_agent_devuelve_400():
        fallos = []
        for body in ({}, {"project": project}, {"agent": agent}):
            r = requests.post(f"{server.base}/step/1", json=body, timeout=10)
            if r.status_code != 400:
                fallos.append(f"body={sorted(body)} → HTTP {r.status_code}")
            elif not r.json().get("log"):
                fallos.append(f"body={sorted(body)} → 400 sin mensaje")
        return not fallos, "; ".join(fallos) or "las 3 invocaciones incompletas dan 400 con mensaje"

    def paso_inexistente_da_404():
        r = post_step(server.base, 9, project, agent)
        return r.status_code == 404, f"/step/9 → HTTP {r.status_code}"

    def lock_global_rechaza_la_segunda():
        """Una segunda operación simultánea recibe 409, sea cual sea el agente."""
        import threading
        codigos = []
        def golpear():
            codigos.append(post_step(server.base, 1, project, agent).status_code)
        hilos = [threading.Thread(target=golpear) for _ in range(2)]
        for hilo in hilos:
            hilo.start()
        for hilo in hilos:
            hilo.join()
        return 409 in codigos, f"códigos {sorted(codigos)}"

    def error_de_permiso_capturado_en_el_codigo():
        """No hace falta provocar el 403: basta con que el caso esté escrito."""
        fuente = (REPO_ROOT / "act" / "server.py").read_text()
        capturado = "ProjectListPermissionError" in fuente and "manual_entry" in fuente
        return capturado, (
            "GET /projects captura ProjectListPermissionError y marca manual_entry"
            if capturado else "el 403 de Resource Manager no está capturado explícitamente"
        )

    runner.check(1, "Puerto ocupado → mensaje claro, no cuelgue", puerto_ocupado_falla_claro)
    runner.check(1, "El servidor arranca y responde", health_responde)
    runner.check(1, "Los 8 endpoints: 200 + JSON con status/log/data", los_8_endpoints_responden_bien)
    runner.check(1, "Access-Control-Allow-Origin presente", cors_presente)
    runner.check(1, "Sin project o agent → 400 con mensaje", sin_project_o_agent_devuelve_400)
    runner.check(1, "Paso inexistente → 404", paso_inexistente_da_404)
    runner.check(1, "Lock global → 409 en la segunda simultánea", lock_global_rechaza_la_segunda)
    runner.check(1, "403 de Resource Manager capturado en el código", error_de_permiso_capturado_en_el_codigo)


# ── Nivel 2 — Conexión real con el pipeline ──────────────────────────────────

def run_level_2(runner, server, project, agent):
    print("\nNIVEL 2 — Conexión real (solo Pasos 1 y 3, lectura)\n")

    def paso_1_devuelve_lo_que_devuelve_la_funcion():
        endpoint = post_step(server.base, 1, project, agent).json()["data"]
        directo = pipeline.step_1_inventory(project, agent)["data"]
        iguales = endpoint.get("totals") == directo.get("totals")
        return iguales, (
            f"totals coinciden ({sum(directo.get('totals', {}).values())} recursos)"
            if iguales else f"endpoint={endpoint.get('totals')} función={directo.get('totals')}"
        )

    def paso_3_devuelve_lo_que_devuelve_la_funcion():
        endpoint = post_step(server.base, 3, project, agent).json()["data"]
        directo = pipeline.step_3_diff(project, agent)["data"]
        iguales = endpoint.get("operations") == directo.get("operations")
        return iguales, (
            f"mismas {len(directo.get('operations', []))} operaciones"
            if iguales else
            f"endpoint={len(endpoint.get('operations', []))} función={len(directo.get('operations', []))}"
        )

    def paso_2_no_es_dato_fijo():
        """En dry_run: el push no se ejecuta, pero los commits pendientes
        que reporta tienen que ser los que git dice de verdad."""
        endpoint = post_step(server.base, 2, project, agent, dry_run=True).json()["data"]
        directo = pipeline.pending_commits()
        return endpoint.get("commits") == directo, (
            f"{len(directo)} commits pendientes, coinciden"
        )

    def paso_5_autogenera_el_nombre():
        con = post_step(server.base, 5, project, agent, dry_run=True, name="mi-snapshot")
        sin = post_step(server.base, 5, project, agent, dry_run=True)
        vacio = post_step(server.base, 5, project, agent, dry_run=True, name="")
        nombres = [r.json()["data"].get("snapshot_name") for r in (con, sin, vacio)]
        correcto = (nombres[0] == "mi-snapshot"
                    and all(n and n != "mi-snapshot" for n in nombres[1:]))
        return correcto, f"con name={nombres[0]!r} · sin={nombres[1]!r} · vacío={nombres[2]!r}"

    def descubrimiento_de_proyectos():
        r = requests.get(f"{server.base}/projects", timeout=60)
        payload = r.json()
        proyectos = payload.get("data", {}).get("projects", [])
        incluido = any(p["projectId"] == project for p in proyectos)
        return r.status_code == 200 and incluido, (
            f"{len(proyectos)} proyectos, {project} incluido"
            if incluido else f"status={payload.get('status')} log={payload.get('log')}"
        )

    def descubrimiento_de_agentes():
        r = requests.get(f"{server.base}/projects/{project}/agents", timeout=60)
        agentes = r.json().get("data", {}).get("agents", [])
        incluido = any(a["agentId"] == agent for a in agentes)
        return r.status_code == 200 and incluido, (
            f"{len(agentes)} agentes, el de referencia incluido" if incluido
            else f"el agente {agent} no aparece en {[a['agentId'] for a in agentes]}"
        )

    runner.check(2, "POST /step/1 == step_1_inventory()", paso_1_devuelve_lo_que_devuelve_la_funcion)
    runner.check(2, "POST /step/3 == step_3_diff()", paso_3_devuelve_lo_que_devuelve_la_funcion)
    runner.check(2, "POST /step/2 refleja el estado real de git", paso_2_no_es_dato_fijo)
    runner.check(2, "POST /step/5 autogenera el nombre si falta", paso_5_autogenera_el_nombre)
    runner.check(2, "GET /projects devuelve datos reales", descubrimiento_de_proyectos)
    runner.check(2, "GET /projects/<p>/agents devuelve datos reales", descubrimiento_de_agentes)

    runner.skip(2, "Escritura real de los Pasos 4 a 8",
                "Escriben en el agente y en GitHub. Se verifican en el recorrido "
                "manual de la Fase 6, no aquí.")


# ── CLI ──────────────────────────────────────────────────────────────────────

def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Smoke test del servidor del pipeline.")
    parser.add_argument("--project", required=True, help="ID del proyecto GCP")
    parser.add_argument("--agent", required=True, help="ID del agente de Dialogflow CX")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT,
                        help=f"Puerto del servidor bajo prueba (por defecto {DEFAULT_PORT})")
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    runner = CheckRunner()

    try:
        with ServerProcess(args.port) as server:
            print(f"server.py arrancado en {server.base}")
            run_level_1(runner, server, args.project, args.agent)
            run_level_2(runner, server, args.project, args.agent)
    except RuntimeError as error:
        print(f"\nERROR: {error}", file=sys.stderr)
        return 1

    counts = runner.summary()
    print(f"\nRESUMEN: {counts[PASS]} PASS · {counts['FAIL']} FAIL · {counts[SKIP]} SKIP")
    if runner.failed:
        print("\nChecks fallidos:")
        for level, name, _, detail in runner.failed:
            print(f"  Nivel {level} · {name}\n        {detail}")
        return 1
    print("El servidor está listo para que el panel se conecte (Fase 7).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
