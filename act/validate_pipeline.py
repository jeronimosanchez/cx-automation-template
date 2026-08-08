#!/usr/bin/env python3
"""
act/validate_pipeline.py — Smoke test de act_cx_resources_deploy.py.

Tres niveles, de menos a más consecuencia:

    Nivel 1  Read-only   Auth, conectividad, LIST, integridad, idempotencia.
    Nivel 2  Dry-run     Plan de los 8 pasos sin escribir en CX.
    Nivel 3  Write real  Checklist impreso para que lo recorra una persona.

Los Niveles 1 y 2 se ejecutan solos y reportan PASS/FAIL por check. El
Nivel 3 no se automatiza: provoca fallos parciales, rollbacks y conflictos
de merge sobre un agente real, y esa decisión es de una persona.

Uso:
    python act/validate_pipeline.py --project <id> --agent <id>
    python act/validate_pipeline.py --project <id> --agent <id> --level 1
    python act/validate_pipeline.py --project <id> --agent <id> --allow-push
"""

import argparse
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

PASS = "PASS"
FAIL = "FAIL"
SKIP = "SKIP"


class CheckRunner:
    """Acumula el resultado de cada check sin abortar el resto.

    Una excepción inesperada cuenta como FAIL de ese check, no como caída
    del validador: si el primer check revienta, los otros veinte siguen
    dando información sobre dónde está el problema.
    """

    def __init__(self):
        self.results = []

    def check(self, level, name, function):
        try:
            passed, detail = function()
            status = PASS if passed else FAIL
        except Exception as error:
            status, detail = FAIL, f"{type(error).__name__}: {error}"
        self._record(level, name, status, detail)

    def skip(self, level, name, reason):
        self._record(level, name, SKIP, reason)

    def _record(self, level, name, status, detail):
        self.results.append((level, name, status, detail))
        marker = {PASS: "✓", FAIL: "✗", SKIP: "–"}[status]
        print(f"  {marker} [{status}] {name}")
        if detail and status != PASS:
            print(f"        {detail}")

    @property
    def failed(self):
        return [item for item in self.results if item[2] == FAIL]

    def summary(self):
        counts = {PASS: 0, FAIL: 0, SKIP: 0}
        for _, _, status, _ in self.results:
            counts[status] += 1
        return counts


# ── Nivel 1 — Read-only ──────────────────────────────────────────────────────

def run_level_1(runner, project, agent_id):
    print("\nNIVEL 1 — Read-only")
    print(f"  proyecto: {project} · agente: {agent_id}\n")

    inventory_holder = {}

    def auth_valido():
        token = cx_client.get_token()
        response = cx_client.api_get(project, cx_client.build_parent(project, agent_id))
        if response.status_code in (401, 403):
            return False, f"La API respondió {response.status_code}"
        return bool(token), f"Token obtenido, la API respondió {response.status_code}"

    def conectividad():
        agent = pipeline.preflight_check(project, agent_id)
        return bool(agent.get("name")), f"Agente '{agent.get('displayName')}' accesible"

    def list_de_los_12_tipos():
        faltan = []
        for resource_type, fetch in pipeline.INVENTORY_FUNCTIONS.items():
            try:
                fetch(project, agent_id)
            except Exception as error:
                faltan.append(f"{resource_type}: {error}")
        return not faltan, "; ".join(faltan) or "12/12 tipos listados"

    def inventario_integro():
        result = pipeline.step_1_inventory(project, agent_id)
        inventory_holder["data"] = pipeline.load_inventory(project, agent_id)
        totals = inventory_holder["data"]["totals"]
        resources = inventory_holder["data"]["resources"]
        incoherentes = [
            resource_type for resource_type in totals
            if totals[resource_type] != len(resources[resource_type])
        ]
        return (
            not incoherentes and result["status"] == "ok",
            f"totals == len en {len(totals)} tipos" if not incoherentes
            else f"incoherentes: {incoherentes}",
        )

    def diff_idempotente():
        primero = pipeline.step_3_diff(project, agent_id)["data"]["operations"]
        segundo = pipeline.step_3_diff(project, agent_id)["data"]["operations"]
        estable = primero == segundo
        return estable, (
            f"{len(primero)} operaciones, estables entre ejecuciones" if estable
            else "el diff cambia entre dos ejecuciones seguidas sobre el mismo estado"
        )

    def aborta_ante_list_parcial():
        """Un LIST caído no puede producir un inventario a medias.

        Datos parciales dan un diff corrupto: los recursos que no se
        listaron aparecerían como nuevos y se duplicarían en el Paso 4.
        """
        original = pipeline.INVENTORY_FUNCTIONS["tools"]

        def revienta(*_args, **_kwargs):
            raise pipeline.PipelineError("LIST tools simulado como caído")

        pipeline.INVENTORY_FUNCTIONS["tools"] = revienta
        try:
            pipeline.step_1_inventory(project, agent_id)
            return False, "el Paso 1 continuó pese al fallo de un LIST"
        except pipeline.PipelineError:
            return True, "el Paso 1 aborta y no escribe inventario parcial"
        finally:
            pipeline.INVENTORY_FUNCTIONS["tools"] = original

    def backoff_ante_429():
        intentos, esperas = [], []
        original_request, original_sleep = requests.request, time.sleep

        def siempre_429(*_args, **_kwargs):
            intentos.append(1)
            return _FakeResponse(429)

        requests.request = siempre_429
        time.sleep = lambda seconds: esperas.append(seconds)
        try:
            response = cx_client.api_request("GET", project, "cualquier/ruta")
        finally:
            requests.request, time.sleep = original_request, original_sleep

        creciente = esperas == sorted(esperas) and len(set(esperas)) == len(esperas)
        return (
            len(intentos) == 3 and response.status_code == 429 and creciente,
            f"{len(intentos)} intentos, esperas {esperas}s — devuelve el 429 sin colgarse",
        )

    def refresca_token_ante_401():
        respuestas = [_FakeResponse(401), _FakeResponse(200)]
        tokens_pedidos = []
        original_request = requests.request
        original_fetch = cx_client._fetch_token

        def responde(*_args, **kwargs):
            tokens_pedidos.append(kwargs["headers"]["Authorization"])
            return respuestas.pop(0)

        requests.request = responde
        cx_client._fetch_token = lambda: f"token-{len(tokens_pedidos)}"
        cx_client._cached_token = "token-viejo"
        try:
            response = cx_client.api_request("GET", project, "cualquier/ruta")
        finally:
            requests.request = original_request
            cx_client._fetch_token = original_fetch
            cx_client._cached_token = None

        refrescado = len(tokens_pedidos) == 2 and tokens_pedidos[0] != tokens_pedidos[1]
        return (
            refrescado and response.status_code == 200,
            "401 → token nuevo → reintento con éxito" if refrescado
            else f"no reintentó con token nuevo: {tokens_pedidos}",
        )

    def cli_exige_project_y_agent():
        fallos = []
        for argumentos in ([], ["--project", project], ["--agent", agent_id]):
            resultado = subprocess.run(
                [sys.executable, "act/act_cx_resources_deploy.py", *argumentos],
                cwd=REPO_ROOT, capture_output=True, text=True,
            )
            if resultado.returncode == 0:
                fallos.append(f"arrancó con {argumentos or 'ningún flag'}")
        return not fallos, "; ".join(fallos) or "rechaza las 3 invocaciones incompletas"

    runner.check(1, "Auth válido — sin 401/403", auth_valido)
    runner.check(1, "Conectividad con CX — GET al agente responde", conectividad)
    runner.check(1, "LIST completa para los 12 tipos", list_de_los_12_tipos)
    runner.check(1, "Inventario JSON íntegro — totals == len por tipo", inventario_integro)
    runner.check(1, "Idempotencia del diff", diff_idempotente)
    runner.check(1, "LIST fallido → aborta sin datos parciales", aborta_ante_list_parcial)
    runner.check(1, "429 → backoff exponencial, máx. 3 intentos", backoff_ante_429)
    runner.check(1, "401 → refresca token y reintenta una vez", refresca_token_ante_401)
    runner.check(1, "CLI sin --project o sin --agent → no ejecuta", cli_exige_project_y_agent)

    return inventory_holder.get("data")


class _FakeResponse:
    """Respuesta mínima para los checks que no deben tocar la red."""

    def __init__(self, status_code, payload=None):
        self.status_code = status_code
        self.text = ""
        self._payload = payload or {}

    def json(self):
        return self._payload


# ── Nivel 2 — Dry-run ────────────────────────────────────────────────────────

def run_level_2(runner, project, agent_id, inventory, allow_push):
    print("\nNIVEL 2 — Dry-run")
    print(f"  proyecto: {project} · agente: {agent_id}\n")

    def dry_run_de_los_8_pasos():
        fallos = []
        for numero, step in sorted(pipeline.STEP_FUNCTIONS.items()):
            try:
                resultado = (
                    step(project, agent_id, name=None, dry_run=True) if numero == 5
                    else step(project, agent_id, dry_run=True)
                )
                if resultado["status"] != "ok":
                    fallos.append(f"paso {numero}: {resultado['status']}")
            except Exception as error:
                fallos.append(f"paso {numero}: {error}")
        return not fallos, "; ".join(fallos) or "los 8 pasos completan en dry-run"

    def diff_detecta_los_cambios():
        """Sobre dicts sintéticos, nunca tocando definitions/.

        Introducir un cambio real en definitions/ para probar el diff
        significaría editar material del knowledgebase — el diff se prueba
        igual de bien con entradas construidas aquí.
        """
        remoto = [
            {"name": "n/1", "displayName": "SinCambios", "goal": "igual"},
            {"name": "n/2", "displayName": "Modificado", "goal": "viejo"},
            {"name": "n/3", "displayName": "Sobrante", "goal": "x"},
        ]
        local = {
            "SinCambios": {"displayName": "SinCambios", "goal": "igual"},
            "Modificado": {"displayName": "Modificado", "goal": "nuevo"},
            "Nuevo": {"displayName": "Nuevo", "goal": "y"},
        }
        operaciones = pipeline.diff_playbooks(remoto, local)
        por_recurso = {item["resource"]: item["operation"] for item in operaciones}
        esperado = {"Modificado": "PATCH", "Nuevo": "POST", "Sobrante": "DELETE"}
        return por_recurso == esperado, f"detectado {por_recurso}, esperado {esperado}"

    def diff_cubre_los_12_tipos():
        cubiertos = set(pipeline.DIFF_FUNCTIONS)
        declarados = set(pipeline.RESOURCE_TYPES)
        return cubiertos == declarados, f"{len(cubiertos)}/12 tipos con función de diff"

    def operaciones_mutuamente_excluyentes():
        resultado = pipeline.step_3_diff(project, agent_id)
        operaciones = resultado["data"]["operations"]
        vistos = {}
        duplicados = []
        for operacion in operaciones:
            clave = (operacion["type"], operacion["resource"])
            if clave in vistos:
                duplicados.append(f"{clave}: {vistos[clave]} y {operacion['operation']}")
            vistos[clave] = operacion["operation"]
        return not duplicados, "; ".join(duplicados) or (
            f"{len(operaciones)} operaciones, ninguna repetida por recurso"
        )

    def diff_coherente_con_inventario():
        # El Nivel 2 puede correr solo (--level 2): el inventario no llega del
        # Nivel 1 en memoria, pero el Paso 1 lo dejó escrito en disco.
        datos = inventory or pipeline.load_inventory(project, agent_id)
        operaciones = pipeline.step_3_diff(project, agent_id)["data"]["operations"]
        nombres_remotos = {
            item.get("name")
            for items in datos["resources"].values() for item in items
        }
        huerfanas = [
            operacion["resource"] for operacion in operaciones
            if operacion["operation"] in ("PATCH", "DELETE")
            and operacion.get("remote_name") not in nombres_remotos
        ]
        return not huerfanas, "; ".join(huerfanas) or (
            "toda PATCH/DELETE apunta a un recurso del inventario"
        )

    def sin_cambios_termina_limpiamente():
        resultado = pipeline.step_3_diff("proyecto-inexistente", "agente-inexistente")
        data = resultado["data"]
        return (
            resultado["status"] == "ok" and data["operations"] == []
            and data.get("no_local_definitions") is True,
            "sin definiciones locales → diff vacío, status ok, no continúa al Paso 4",
        )

    def orden_de_deploy_correcto():
        esperado = [
            "entity_types", "intents", "webhooks", "tools", "generators",
            "playbooks", "examples", "flows", "agent_config",
        ]
        plan = pipeline.step_4_deploy(
            project, agent_id,
            operations=[
                {"type": tipo, "resource": f"r-{tipo}", "operation": "POST", "local": {}}
                for tipo in reversed(esperado)
            ],
            dry_run=True,
        )
        orden_real = [operacion["type"] for operacion in plan["data"]["operations"]]
        return orden_real == esperado, f"orden generado: {orden_real}"

    def orden_de_los_8_pasos():
        return (
            sorted(pipeline.STEP_FUNCTIONS) == list(range(1, 9)),
            "los 8 pasos existen numerados del 1 al 8",
        )

    def exit_codes_coherentes():
        exito = subprocess.run(
            [sys.executable, "act/act_cx_resources_deploy.py",
             "--project", project, "--agent", agent_id, "--step", "3", "--dry-run"],
            cwd=REPO_ROOT, capture_output=True, text=True,
        )
        fallo = subprocess.run(
            [sys.executable, "act/act_cx_resources_deploy.py",
             "--project", "no-existe", "--agent", "no-existe", "--step", "1"],
            cwd=REPO_ROOT, capture_output=True, text=True,
        )
        return (
            exito.returncode == 0 and fallo.returncode == 1 and "ERROR" in fallo.stderr,
            f"éxito → {exito.returncode}, fallo → {fallo.returncode} con mensaje en stderr",
        )

    def push_a_staging():
        pendientes = pipeline.pending_commits()
        resultado = pipeline.step_2_push_staging(project, agent_id)
        return resultado["status"] == "ok", (
            f"{len(pendientes)} commits pendientes antes del push; "
            f"resultado: {resultado['log'][-1]}"
        )

    def origin_staging_al_dia():
        return not pipeline.pending_commits(), "origin/staging sin commits pendientes"

    runner.check(2, "--dry-run completa los 8 pasos", dry_run_de_los_8_pasos)
    runner.check(2, "Diff detecta POST/PATCH/DELETE exactos", diff_detecta_los_cambios)
    runner.check(2, "Diff cubre los 12 tipos", diff_cubre_los_12_tipos)
    runner.check(2, "POST/PATCH/DELETE excluyentes por recurso", operaciones_mutuamente_excluyentes)
    runner.check(2, "Diff coherente con el inventario del Paso 1", diff_coherente_con_inventario)
    runner.check(2, "Sin cambios → termina limpiamente", sin_cambios_termina_limpiamente)
    runner.check(2, "Orden de deploy correcto en el plan", orden_de_deploy_correcto)
    runner.check(2, "Los 8 pasos en el orden del HTML", orden_de_los_8_pasos)
    runner.check(2, "Exit 0 en éxito, exit 1 con mensaje en fallo", exit_codes_coherentes)

    if allow_push:
        runner.check(2, "Push a GitHub staging", push_a_staging)
        runner.check(2, "origin/staging al día tras el push", origin_staging_al_dia)
    else:
        motivo = (
            "El push escribe en un repositorio público y requiere OK explícito. "
            "Relanza con --allow-push para cubrir estos dos checks."
        )
        runner.skip(2, "Push a GitHub staging", motivo)
        runner.skip(2, "origin/staging al día tras el push", motivo)


# ── Nivel 3 — Checklist manual ───────────────────────────────────────────────

NIVEL_3_CHECKLIST = [
    ("Smoke test base", [
        "POST /versions con el campo de nombre vacío en el panel → el LRO termina en "
        "done:true y la versión tiene un displayName autogenerado, nunca un error code:3.",
        "PATCH /environments/staging apuntando a una versión real → GET /environments/staging "
        "confirma que el entorno quedó en esa versión.",
        "Cronometra el POST /versions de punta a punta y anota los segundos: el timeout de "
        "5 min (60 intentos × 5 s) es provisional y no está medido contra un caso real.",
    ]),
    ("Paso 4 — Confirmar deploy", [
        "Deploy con todo sincronizado → banner verde y 'Continuar →' habilitado.",
        "Provoca el fallo de un recurso (referencia rota en un YAML) → resumen "
        "OK/ERROR/no-intentado por recurso y las dos opciones de recuperación.",
        "'Reintentar fallidos' → solo se reintentan el fallido y los 'no intentado'; "
        "los que ya estaban OK no cambian de timestamp ni de log.",
        "'Revertir draft' → el draft vuelve al estado del inventario del Paso 1.",
    ]),
    ("Paso 5 — Snapshot del agente", [
        "Observa el log: el panel no reporta éxito hasta que el LRO devuelve done:true.",
        "Con el entorno en su límite de 5 versiones, lanza un snapshot nuevo → la más "
        "antigua desaparece y el snapshot se crea sin error de límite.",
        "Avanza hasta el Paso 8 → el nombre del snapshot aparece correcto en 6, 7 y 8.",
    ]),
    ("Paso 6 — Validación de tests", [
        "'Tests superados' → cero llamadas nuevas a la API de CX al avanzar al Paso 7.",
        "'Rollback' confirmado → staging en la versión anterior y draft igual a esa versión.",
        "Abre el diálogo de rollback y cancélalo → ni staging ni draft cambian.",
        "Repite las tres observando producción → producción no cambia en ninguna.",
    ]),
    ("Paso 7 — Gate QA staging", [
        "'Validado' → cero llamadas nuevas a la API al avanzar al Paso 8.",
        "'Rollback' → PATCH a la versión anterior y draft restaurado, igual que el Paso 6.",
        "Repite el rollback observando producción → producción no cambia.",
        "Tras confirmar un rollback, intenta continuar → no hay camino, el pipeline "
        "queda cerrado, solo se puede iniciar un deploy nuevo.",
    ]),
    ("Paso 8 — Aprobar producción", [
        "Aprueba y observa el orden en el log → el merge a main completa antes del "
        "PATCH /environments/production, nunca en paralelo ni al revés.",
        "Provoca un conflicto de merge (edita main antes de aprobar) → el PATCH a "
        "producción nunca se dispara.",
        "Con el conflicto activo, pulsa 'Abortar' → vuelves al gate inicial sin cambios "
        "y sin ningún rollback.",
        "Tras aprobar con éxito, compara GET production con GET staging → ambos en la "
        "misma versión, sin crear ninguna nueva.",
    ]),
]


def run_level_3(project, agent_id):
    print("\nNIVEL 3 — Write real · checklist manual")
    print(f"  proyecto: {project} · agente: {agent_id}")
    print("  Este nivel NO se automatiza: escribe en un agente real.\n")
    for titulo, items in NIVEL_3_CHECKLIST:
        print(f"  {titulo}")
        for numero, item in enumerate(items, 1):
            print(f"    [ ] {numero}. {item}")
        print()


# ── CLI ──────────────────────────────────────────────────────────────────────

def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Smoke test del pipeline de deploy.")
    parser.add_argument("--project", required=True, help="ID del proyecto GCP")
    parser.add_argument("--agent", required=True, help="ID del agente de Dialogflow CX")
    parser.add_argument(
        "--level", type=int, choices=(1, 2, 3),
        help="Ejecuta un solo nivel. Sin este flag, los tres.",
    )
    parser.add_argument(
        "--allow-push", action="store_true",
        help="Autoriza el único push real del Nivel 2 (repositorio público).",
    )
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    niveles = [args.level] if args.level else [1, 2, 3]
    runner = CheckRunner()
    inventory = None

    if 1 in niveles:
        inventory = run_level_1(runner, args.project, args.agent)
    if 2 in niveles:
        run_level_2(runner, args.project, args.agent, inventory, args.allow_push)
    if 3 in niveles:
        run_level_3(args.project, args.agent)

    counts = runner.summary()
    print(f"\nRESUMEN: {counts[PASS]} PASS · {counts[FAIL]} FAIL · {counts[SKIP]} SKIP")
    if runner.failed:
        print("\nChecks fallidos:")
        for level, name, _, detail in runner.failed:
            print(f"  Nivel {level} · {name}\n        {detail}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
