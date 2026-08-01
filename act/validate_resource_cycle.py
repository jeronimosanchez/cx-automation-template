#!/usr/bin/env python3
"""
act/validate_resource_cycle.py — Ciclo crear → modificar → rollback → borrar
por cada tipo de recurso, contra un agente desechable.

Automatiza lo que el recorrido manual de la Fase 6 hace a mano, y da la
primera cobertura real del Paso 4: hoy solo el Full Update de Playbooks
está ejercitado, y la Regla 15 dice que el `updateMask` hay que comprobarlo
recurso a recurso. Cada tipo que pasa aquí es un `code:3` menos esperando
en un deploy real.

El ciclo pasa por las funciones `deploy_*` del pipeline, nunca por
`cx_client` directamente: si llamara a la API en crudo verificaría que
Google funciona, no que nuestro código está bien.

Seguridad:
  · Solo opera sobre un agente que crea él mismo en esta ejecución. Un
    agente preexistente nunca puede ser destino, ni Petal ni ningún otro.
  · El ID del agente se registra en disco antes de cualquier otra llamada,
    para que un corte no deje un huérfano sin rastro (--limpiar-huerfanos).
  · Limpieza en finally: borra el agente entero pase lo que pase.
  · Inventario de Petal antes y después; si cambia algo, se reporta.
  · Cero operaciones de git.

Uso:
    python act/validate_resource_cycle.py
    python act/validate_resource_cycle.py --limpiar-huerfanos
"""

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from act import act_cx_resources_deploy as pipeline
from act.utils import cx_client
from act.validate_pipeline import FAIL, PASS, SKIP, CheckRunner

PREFIX = "TEST_FASE6_"
AGENT_PREFIX = "zz-ciclo-"
ORPHAN_FILE = pipeline.LOGS_DIR / ".agente_desechable_en_curso"

# Agentes reales del proyecto. La protección de verdad es la lista blanca
# (solo el agente creado en esta ejecución), pero se comprueban también por
# nombre: si algún día alguien añade un flag --agent, esto sigue en pie.
AGENTES_PROTEGIDOS = {
    "745375ba-ac7e-4eb8-b8a0-d742891f2aa4",  # Floristeria-Petal (Petal 1.0)
    "cea66b60-192d-4b5a-af10-28f8661032e0",  # Petal-RESERVA-jun26
}

OPENAPI_MINIMO = (
    "openapi: 3.0.0\n"
    "info:\n  title: TestTool\n  version: 1.0.0\n"
    "servers:\n  - url: https://ejemplo.invalid\n"
    "paths:\n  /ping:\n    get:\n      operationId: ping\n"
    "      responses:\n        '200':\n          description: ok\n"
)


PADRE = f"{PREFIX}padre"


def crear_playbook_padre(project, agent_id):
    """El ciclo de examples necesita un playbook que no se borre a mitad.

    El de `playbooks` elimina el suyo al terminar — reutilizarlo dejaba al
    example sin padre y el pipeline lo rechazaba, con razón.
    """
    pipeline.deploy_playbooks(project, agent_id, {
        "type": "playbooks", "resource": PADRE, "operation": "POST",
        "local": {"displayName": PADRE, "goal": "padre de los examples de prueba",
                  "playbookType": "ROUTINE",
                  "instruction": {"steps": [{"text": "sin uso"}]}}})


def ciclos(nombre_playbook):
    """Definición local de cada tipo, como la traería un YAML del repo."""
    return [
        {"tipo": "entity_types", "modificar": ("entities", [{"value": "b", "synonyms": ["b"]}]),
         "local": {"displayName": f"{PREFIX}entidad", "kind": "KIND_MAP",
                   "entities": [{"value": "a", "synonyms": ["a"]}]}},
        {"tipo": "intents", "modificar": ("description", "modificado"),
         "local": {"displayName": f"{PREFIX}intent", "description": "original",
                   "trainingPhrases": [{"parts": [{"text": "hola que tal"}], "repeatCount": 1}]}},
        {"tipo": "webhooks", "modificar": ("timeout", "8s"),
         "local": {"displayName": f"{PREFIX}webhook", "timeout": "5s",
                   "genericWebService": {"uri": "https://ejemplo.invalid/hook"}}},
        {"tipo": "tools", "modificar": ("description", "modificado"),
         "local": {"displayName": f"{PREFIX}tool", "description": "original",
                   "toolType": "CUSTOMIZED_TOOL",
                   "openApiSpec": {"textSchema": OPENAPI_MINIMO}}},
        {"tipo": "generators", "modificar": ("promptText", {"text": "prompt modificado"}),
         "local": {"displayName": f"{PREFIX}generator",
                   "promptText": {"text": "prompt original"}}},
        {"tipo": "playbooks", "modificar": ("goal", "objetivo modificado"),
         "local": {"displayName": nombre_playbook, "goal": "objetivo original",
                   "playbookType": "ROUTINE",
                   "instruction": {"steps": [{"text": "paso original"}]}}},
        {"tipo": "examples", "modificar": ("description", "modificado"),
         "local": {"displayName": f"{PREFIX}example", "description": "original",
                   "playbook": PADRE, "languageCode": "es",
                   "conversationState": "OUTPUT_STATE_OK",
                   "actions": [{"agentUtterance": {"text": "hola"}}]}},
        {"tipo": "flows", "modificar": ("description", "modificado"),
         "local": {"displayName": f"{PREFIX}flow", "description": "original"}},
    ]


# ── Agente desechable ────────────────────────────────────────────────────────

def crear_agente(project):
    marca = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    response = cx_client.api_post(
        project, f"projects/{project}/locations/{cx_client.LOCATION}/agents",
        {"displayName": f"{AGENT_PREFIX}{marca}", "defaultLanguageCode": "es",
         "timeZone": "Europe/Madrid",
         "description": "Desechable — validate_resource_cycle.py. Borrar si sobrevive."},
    )
    if response.status_code not in (200, 201):
        raise RuntimeError(f"No se pudo crear el agente: {response.status_code} {response.text[:200]}")
    agente = cx_client.resolve_operation(project, response)
    agent_id = agente["name"].rsplit("/", 1)[-1]

    # Antes de cualquier otra llamada: si esto se corta ahora, el ID queda.
    pipeline.LOGS_DIR.mkdir(parents=True, exist_ok=True)
    ORPHAN_FILE.write_text(f"{project}\n{agent_id}\n")
    return agent_id


def borrar_agente(project, agent_id):
    cx_client.api_delete(project, cx_client.build_parent(project, agent_id))
    sigue = cx_client.api_get(project, cx_client.build_parent(project, agent_id))
    ORPHAN_FILE.unlink(missing_ok=True)
    return sigue.status_code == 404


def limpiar_huerfanos(project):
    print("Buscando agentes desechables huérfanos…")
    encontrados = [a for a in cx_client.list_cx_agents(project)
                   if a["displayName"].startswith(AGENT_PREFIX)]
    if not encontrados:
        print("  ninguno")
        ORPHAN_FILE.unlink(missing_ok=True)
        return 0
    for agente in encontrados:
        borrado = borrar_agente(project, agente["agentId"])
        print(f"  {agente['displayName']} → {'borrado' if borrado else 'NO se pudo borrar'}")
    return 0


def proteger(agent_id, creado_en_esta_ejecucion):
    """Lista blanca: solo el agente creado aquí. Todo lo demás aborta."""
    if agent_id != creado_en_esta_ejecucion:
        raise RuntimeError(
            f"El destino {agent_id} no es el agente creado en esta ejecución "
            f"({creado_en_esta_ejecucion}). Abortado sin ejecutar nada."
        )
    if agent_id in AGENTES_PROTEGIDOS:
        raise RuntimeError(f"El destino {agent_id} es un agente real. Abortado.")


# ── Ciclo por tipo ───────────────────────────────────────────────────────────

def _buscar(project, agent_id, tipo, display_name):
    return next(
        (r for r in pipeline.INVENTORY_FUNCTIONS[tipo](project, agent_id)
         if r.get("displayName") == display_name), None)


def ejecutar_ciclo(project, agent_id, caso):
    """crear → verificar → modificar → verificar → rollback → verificar → borrar."""
    tipo, local = caso["tipo"], caso["local"]
    nombre = local["displayName"]
    campo, valor_nuevo = caso["modificar"]
    deploy = pipeline.DEPLOY_FUNCTIONS[tipo]

    if _buscar(project, agent_id, tipo, nombre):
        raise RuntimeError(f"Ya existe un {tipo} llamado {nombre!r} — abortado, no se sobrescribe.")

    deploy(project, agent_id, {"type": tipo, "resource": nombre, "operation": "POST", "local": local})
    creado = _buscar(project, agent_id, tipo, nombre)
    if not creado:
        raise RuntimeError("POST no dejó el recurso en CX")

    def patch(valores):
        actual = _buscar(project, agent_id, tipo, nombre)
        deploy(project, agent_id, {"type": tipo, "resource": nombre, "operation": "PATCH",
                                   "local": {**local, **valores}, "remote_name": actual["name"]})
        return _buscar(project, agent_id, tipo, nombre)

    modificado = patch({campo: valor_nuevo})
    if modificado.get(campo) != valor_nuevo:
        raise RuntimeError(
            f"PATCH no aplicó {campo}: quedó {str(modificado.get(campo))[:60]!r} "
            f"— revisa el updateMask de este tipo (Regla 15)")

    revertido = patch({campo: local.get(campo)})
    if revertido.get(campo) != local.get(campo):
        raise RuntimeError(f"El rollback no restauró {campo}")

    deploy(project, agent_id, {"type": tipo, "resource": nombre, "operation": "DELETE",
                               "remote_name": revertido["name"]})
    if _buscar(project, agent_id, tipo, nombre):
        raise RuntimeError("DELETE no eliminó el recurso")
    return True, f"crear → modificar ({campo}) → rollback → borrar"


def ciclo_version_y_entorno(project, agent_id):
    """Patrón distinto: no se edita, se mueve el puntero del entorno.

    Se comprueba `versionConfigs` por GET, no el comportamiento servido: la
    propagación tarda minutos (Regla 18) y esperarla haría el test inusable.
    """
    primeras = pipeline.create_versions_for_snapshot(project, agent_id, "ciclo_v1")
    response = cx_client.api_post(
        project, f"{cx_client.build_parent(project, agent_id)}/environments",
        {"displayName": "ciclo", "versionConfigs": [{"version": v} for v in primeras]})
    if response.status_code not in (200, 201):
        raise RuntimeError(f"POST /environments falló: {response.status_code} {response.text[:200]}")
    entorno = cx_client.resolve_operation(project, response)

    entorno = cx_client.api_get(project, entorno["name"]).json()
    antes = [c["version"] for c in entorno.get("versionConfigs", [])]

    segundas = pipeline.create_versions_for_snapshot(project, agent_id, "ciclo_v2")
    pipeline.point_environment_at_versions(project, entorno, segundas)
    ahora = [c["version"] for c in cx_client.api_get(project, entorno["name"]).json()["versionConfigs"]]
    if sorted(ahora) != sorted(segundas):
        raise RuntimeError(f"El entorno no quedó en la versión nueva: {ahora}")

    # Rollback al ID exacto que tenía, no a "una versión anterior cualquiera".
    pipeline.point_environment_at_versions(project, entorno, antes)
    final = [c["version"] for c in cx_client.api_get(project, entorno["name"]).json()["versionConfigs"]]
    if sorted(final) != sorted(antes):
        raise RuntimeError(f"El rollback no restauró el ID exacto: {final} ≠ {antes}")
    return True, (f"v1 ({len(antes)}) → v2 ({len(segundas)}) → rollback al ID exacto de v1")


def dry_run_no_escribe(project, agent_id):
    nombre = f"{PREFIX}dryrun"
    pipeline.step_4_deploy(
        project, agent_id, dry_run=True,
        operations=[{"type": "intents", "resource": nombre, "operation": "POST",
                     "local": {"displayName": nombre,
                               "trainingPhrases": [{"parts": [{"text": "x y z"}], "repeatCount": 1}]}}])
    existe = _buscar(project, agent_id, "intents", nombre)
    return not existe, "el plan se genera y no aparece nada en CX"


# ── Inventario de Petal, antes y después ─────────────────────────────────────

def foto_de_petal(project, agent_id):
    entornos = pipeline.inventory_environments(project, agent_id)
    return {
        "playbooks": len(pipeline.inventory_playbooks(project, agent_id)),
        "examples": len(pipeline.inventory_examples(project, agent_id)),
        "tools": len(pipeline.inventory_tools(project, agent_id)),
        "versiones_flow": len(pipeline.inventory_versions(project, agent_id)),
        "entornos": {e["displayName"]: len(e.get("versionConfigs", [])) for e in entornos},
    }


# ── CLI ──────────────────────────────────────────────────────────────────────

def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Ciclo completo por tipo de recurso contra un agente desechable.")
    parser.add_argument("--project", default="floristeria-petal-digital")
    parser.add_argument("--petal-agent", default="745375ba-ac7e-4eb8-b8a0-d742891f2aa4",
                        help="Agente real del que se toma la foto antes/después")
    parser.add_argument("--limpiar-huerfanos", action="store_true",
                        help="Borra agentes desechables que hayan sobrevivido a una ejecución previa")
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    if args.limpiar_huerfanos:
        return limpiar_huerfanos(args.project)

    runner = CheckRunner()
    print("Foto de Petal antes de empezar…")
    petal_antes = foto_de_petal(args.project, args.petal_agent)
    print(f"  {petal_antes}\n")

    agent_id = crear_agente(args.project)
    nombre_playbook = f"{PREFIX}playbook"
    print(f"Agente desechable: {agent_id}  (registrado en {ORPHAN_FILE.name})\n")

    try:
        proteger(agent_id, agent_id)
        crear_playbook_padre(args.project, agent_id)
        runner.check(1, "dry-run no escribe nada en CX",
                     lambda: dry_run_no_escribe(args.project, agent_id))
        for caso in ciclos(nombre_playbook):
            runner.check(1, f"Ciclo completo · {caso['tipo']}",
                         lambda c=caso: ejecutar_ciclo(args.project, agent_id, c))
        runner.check(2, "Versión + entorno · mover puntero y rollback exacto",
                     lambda: ciclo_version_y_entorno(args.project, agent_id))
        runner.skip(1, "Ciclo completo · pages",
                    "Fuera de alcance por la Regla 9 — no existe deploy_pages().")
        runner.skip(1, "Ciclo completo · agent_config",
                    "Recurso singular: no admite create/delete. Su Full Update ya se "
                    "verificó por separado.")
    finally:
        print("\nLimpieza…")
        borrado = borrar_agente(args.project, agent_id)
        print(f"  agente desechable borrado: {borrado}")
        petal_despues = foto_de_petal(args.project, args.petal_agent)
        igual = petal_antes == petal_despues
        print(f"  Petal intacto: {igual}")
        if not igual:
            print(f"    antes:   {petal_antes}")
            print(f"    después: {petal_despues}")

    counts = runner.summary()
    print(f"\nRESUMEN: {counts[PASS]} PASS · {counts[FAIL]} FAIL · {counts[SKIP]} SKIP")
    if runner.failed:
        print("\nFallos:")
        for level, name, _, detail in runner.failed:
            print(f"  {name}\n        {detail}")
    return 0 if not runner.failed and borrado and igual else 1


if __name__ == "__main__":
    sys.exit(main())
