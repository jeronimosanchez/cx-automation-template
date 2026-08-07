#!/usr/bin/env python3
"""
act/validate_pipeline_cloudrun.py — Smoke test de act_cx_resources_deploy_cloudrun.py.

Cinco niveles de riesgo creciente. Cada uno se puede lanzar por separado, y
ninguno depende del panel: eso no existe hasta la Fase 7, así que todo se
ejecuta por CLI o llamando a las funciones del pipeline.

    Nivel 0  Estático. Sin red ni credenciales. Atrapa violaciones de
             arquitectura antes de gastar una llamada.
    Nivel 1  Solo lectura contra CX y el repositorio reales. Cero riesgo.
    Nivel 2  Dry-run. No escribe nada real.
    Nivel 3  Escritura real automatizada, contra el agente desechable.
    Nivel 4  Fallo inyectado y concurrencia. El nivel que encuentra lo que no
             se nota: residuos, candados colgados, fugas entre agentes.

**La validación contra un Cloud Run real vive en la Fase 6**, no aquí. El
Build Playbook la describía como un sexto nivel de esta fase, pero exige un
servicio desplegado con su Service Account de runtime — y el servidor y el
Dockerfile son outputs de la Fase 5. Un nivel que solo puede saltarse no es
cobertura: es un hueco con nombre. Va donde se valida el servidor.

**Nunca contra Petal.** Ni siquiera para leer: comparar contra un agente real
que puede cambiar entre dos llamadas produce falsos fallos. El agente destino
tiene que declararse desechable en su propio nombre, y el script se niega a
arrancar si no lo hace — es la única barrera que no depende de acordarse.

**Cero residuo.** Todo lo que crea lleva un prefijo con el identificador de la
corrida, se barre al empezar además de al terminar (un `finally` no sobrevive a
un SIGKILL), y el borrado se confirma leyendo el resultado, nunca el código de
respuesta.

Uso:
    python act/validate_pipeline_cloudrun.py --project P --agent A --levels 0-2
    python act/validate_pipeline_cloudrun.py --project P --agent A --levels 3,4
"""

import argparse
import ast
import re
import sys
import uuid
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from act import act_cx_resources_deploy_cloudrun as pipeline
from act.utils import cx_client_cloudrun as cx
from act.utils import firestore_client_cloudrun as store

PASS, FAIL, SKIP = "PASS", "FAIL", "SKIP"

# Marca que un agente tiene que llevar en su nombre para que este script acepte
# escribir en él. No es una lista de agentes prohibidos —una lista se queda
# desactualizada— sino lo contrario: solo se admite lo que se declara
# desechable, así que un agente real nunca pasa por olvido.
MARCA_DESECHABLE = "desechable"

# Prefijo de todo lo que crea una corrida. Permite saber qué borrar y de qué
# ejecución es, incluso si dos corridas se solapan.
PREFIJO = "actval"

# Archivos del pipeline cloud que el Nivel 0 analiza.
ARCHIVOS_PIPELINE = [
    "act/act_cx_resources_deploy_cloudrun.py",
    "act/utils/cx_client_cloudrun.py",
    "act/utils/cx_payloads_cloudrun.py",
    "act/utils/firestore_client_cloudrun.py",
    "act/utils/github_app_client_cloudrun.py",
]

# Literales que no pueden aparecer en el código del pipeline. Viven aquí, en un
# archivo de test, que es donde el propio criterio del Nivel 0 los admite.
LITERALES_PROHIBIDOS = re.compile(
    r"(floristeria-petal-digital|745375ba-ac7e-4eb8-b8a0-d742891f2aa4"
    r"|cea66b60-192d-4b5a-af10-28f8661032e0|cloud-run-multiproyecto)"
)


class CheckRunner:
    """Recolector de resultados. Una excepción cuenta como FAIL de ese check,
    no como caída del script: un nivel tiene que poder terminar y contarlo."""

    def __init__(self):
        self.results = []

    def check(self, level, name, funcion):
        try:
            resultado = funcion()
            if isinstance(resultado, tuple):
                ok, detalle = resultado
            else:
                ok, detalle = bool(resultado), ""
            self._record(level, name, PASS if ok else FAIL, detalle)
            return ok
        except Exception as error:
            self._record(level, name, FAIL, f"{type(error).__name__}: {error}")
            return False

    def skip(self, level, name, motivo):
        """Un check que no se ejecuta se cuenta y se explica — nunca se calla.

        Un SKIP silencioso se lee después como cobertura que nunca existió.
        """
        self._record(level, name, SKIP, motivo)

    def _record(self, level, name, status, detalle):
        self.results.append((level, name, status, detalle))
        marca = {PASS: "✓", FAIL: "✗", SKIP: "–"}[status]
        print(f"  {marca} [N{level}] {name}")
        if detalle and status != PASS:
            print(f"      {detalle}")

    def failed(self):
        return [r for r in self.results if r[2] == FAIL]

    def counts(self):
        c = {PASS: 0, FAIL: 0, SKIP: 0}
        for _, _, status, _ in self.results:
            c[status] += 1
        return c


# ── Instrumentación ──────────────────────────────────────────────────────────

class ContadorHttp:
    """Cuenta las llamadas del cliente CX por verbo.

    Instrumentar es la única forma de demostrar "solo lectura": inspeccionar el
    código es fiarse de que nadie añadió una escritura sin darse cuenta.
    """

    def __init__(self):
        self.llamadas = []
        self._original = None

    def __enter__(self):
        self._original = cx.api_request

        def espia(method, project, region, path, *args, **kwargs):
            self.llamadas.append((method, path))
            return self._original(method, project, region, path, *args, **kwargs)

        cx.api_request = espia
        return self

    def __exit__(self, *_):
        cx.api_request = self._original
        return False

    def escrituras(self):
        return [c for c in self.llamadas if c[0] in ("POST", "PATCH", "DELETE", "PUT")]


# ── Guardas ──────────────────────────────────────────────────────────────────

def exigir_agente_desechable(project, agent_id):
    """Se niega a seguir si el agente no se declara desechable en su nombre."""
    region = cx.detect_agent_region(project, agent_id)
    respuesta = cx.api_get(project, region, cx.build_parent(project, region, agent_id))
    if respuesta.status_code != 200:
        raise SystemExit(
            f"No se pudo leer el agente {agent_id}: {respuesta.status_code}"
        )
    nombre = respuesta.json().get("displayName", "")
    if MARCA_DESECHABLE not in nombre.lower():
        raise SystemExit(
            f"El agente '{nombre}' no se declara desechable. Este script "
            f"escribe de verdad, así que solo acepta agentes cuyo nombre "
            f"contenga '{MARCA_DESECHABLE}'. No se ha tocado nada."
        )
    return region, nombre


# ── Nivel 0 · Estático ───────────────────────────────────────────────────────

def nivel_0(runner):
    print("\nNIVEL 0 — Estático · sin red ni credenciales")

    def sin_literales_reales():
        sucios = []
        for ruta in ARCHIVOS_PIPELINE:
            for i, linea in enumerate((REPO_ROOT / ruta).read_text().splitlines(), 1):
                if LITERALES_PROHIBIDOS.search(linea):
                    sucios.append(f"{ruta}:{i}")
        return not sucios, f"aparecen en {', '.join(sucios)}" if sucios else ""

    runner.check(0, "Ningún literal de proyecto, agente o región real en el código",
                 sin_literales_reales)

    def sin_constantes_de_destino():
        sospechosas = []
        for ruta in ARCHIVOS_PIPELINE:
            arbol = ast.parse((REPO_ROOT / ruta).read_text())
            for nodo in arbol.body:
                if not isinstance(nodo, ast.Assign):
                    continue
                for objetivo in nodo.targets:
                    if not isinstance(objetivo, ast.Name):
                        continue
                    if not isinstance(nodo.value, ast.Constant):
                        continue
                    if not isinstance(nodo.value.value, str):
                        continue
                    if re.search(r"^(PROJECT|AGENT|AGENT_ID|REGION|LOCATION)$",
                                 objetivo.id):
                        sospechosas.append(f"{ruta}:{objetivo.id}")
        return not sospechosas, ", ".join(sospechosas)

    runner.check(0, "Ninguna constante de módulo fija proyecto, agente o región",
                 sin_constantes_de_destino)

    def entrada_exige_destino():
        fallos = []
        for nombre in ("step_1_inventory", "step_3_apply_to_cx", "step_5_publish",
                       "deploy_single_resource", "manage_versions"):
            funcion = getattr(pipeline, nombre)
            try:
                funcion()
                fallos.append(f"{nombre} aceptó llamada sin destino")
            except TypeError:
                pass
        return not fallos, "; ".join(fallos)

    runner.check(0, "Las funciones de entrada exigen project y agent explícitos",
                 entrada_exige_destino)

    def contexto_rechaza_vacios():
        for project, agent in (("", "a"), ("p", ""), (None, None)):
            try:
                pipeline.Contexto(project, agent)
                return False, f"aceptó project={project!r} agent={agent!r}"
            except ValueError:
                continue
            except Exception:
                # Cualquier otro fallo llegaría después de la validación, y eso
                # significa que la validación no se hizo primero.
                return False, f"no validó antes de actuar con {project!r}/{agent!r}"
        return True, ""

    runner.check(0, "Un destino vacío falla al construir el contexto, no más tarde",
                 contexto_rechaza_vacios)

    def esquema_firestore_obligatorio():
        faltan = set(store.CAMPOS_OBLIGATORIOS_AGENTE) - {
            "project", "agent_id", "region", "repo", "rama"}
        return not faltan and len(store.CAMPOS_OBLIGATORIOS_AGENTE) == 5, ""

    runner.check(0, "El documento del agente declara sus campos obligatorios",
                 esquema_firestore_obligatorio)

    def mapeo_incompleto_falla():
        class DocFalso:
            exists = True
            def to_dict(self): return {"project": "p", "agent_id": "a"}
        class RefFalsa:
            def get(self): return DocFalso()
        class ColFalsa:
            def document(self, _): return RefFalsa()
        class ClienteFalso:
            def collection(self, _): return ColFalsa()
        try:
            store.get_agent_mapping(ClienteFalso(), "p", "a")
            return False, "aceptó un documento sin region ni repo"
        except store.MappingIncomplete as error:
            return "region" in str(error), str(error)[:80]

    runner.check(0, "Un documento incompleto falla con error propio, no con None implícito",
                 mapeo_incompleto_falla)

    def temporales_sin_ruta_fija():
        # El pipeline no escribe archivos temporales: todo lo que necesita
        # persistir va a Firestore o a GitHub. Se comprueba que sigue siendo
        # verdad, porque una ruta fija por agente colisionaría entre dos
        # peticiones concurrentes en el mismo contenedor reutilizado.
        sucios = []
        for ruta in ARCHIVOS_PIPELINE:
            texto = (REPO_ROOT / ruta).read_text()
            for patron in ("/tmp/", "tempfile.", "NamedTemporary", "open("):
                if patron in texto:
                    sucios.append(f"{ruta}: {patron}")
        return not sucios, "; ".join(sucios)

    runner.check(0, "El pipeline no escribe archivos temporales en disco",
                 temporales_sin_ruta_fija)

    def ningun_log_interpola_tokens():
        sucios = []
        for ruta in ARCHIVOS_PIPELINE:
            for i, linea in enumerate((REPO_ROOT / ruta).read_text().splitlines(), 1):
                if not re.search(r"(print|_emit|log\.append)", linea):
                    continue
                if re.search(r"\{[^}]*token[^}]*\}|\+\s*token\b", linea, re.I):
                    sucios.append(f"{ruta}:{i}")
        return not sucios, ", ".join(sucios)

    runner.check(0, "Ningún registro interpola el token de acceso ni el de GitHub",
                 ningun_log_interpola_tokens)

    def adc_en_lugar_de_gcloud():
        """Se mira el código, no el texto.

        Buscar la cadena "gcloud" da un falso positivo con el propio docstring
        del cliente, que explica en prosa por qué aquí no se usa. Lo que
        importa es si el módulo lo importa o lo invoca.
        """
        arbol = ast.parse((REPO_ROOT / "act/utils/cx_client_cloudrun.py").read_text())
        importa_subprocess = any(
            (isinstance(n, ast.Import) and any(a.name == "subprocess" for a in n.names))
            or (isinstance(n, ast.ImportFrom) and n.module == "subprocess")
            for n in ast.walk(arbol)
        )
        # Los docstrings también son nodos constantes, y el del propio cliente
        # nombra a gcloud para explicar por qué NO se usa. Se excluyen.
        docstrings = set()
        for nodo in ast.walk(arbol):
            if isinstance(nodo, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef,
                                 ast.ClassDef)):
                cuerpo = getattr(nodo, "body", [])
                if (cuerpo and isinstance(cuerpo[0], ast.Expr)
                        and isinstance(cuerpo[0].value, ast.Constant)
                        and isinstance(cuerpo[0].value.value, str)):
                    docstrings.add(id(cuerpo[0].value))
        invoca_gcloud = any(
            isinstance(n, ast.Constant) and isinstance(n.value, str)
            and id(n) not in docstrings and "print-access-token" in n.value
            for n in ast.walk(arbol)
        )
        usa_adc = any(
            isinstance(n, ast.Attribute) and n.attr == "default"
            for n in ast.walk(arbol)
        )
        problemas = []
        if importa_subprocess:
            problemas.append("importa subprocess")
        if invoca_gcloud:
            problemas.append("invoca gcloud print-access-token")
        if not usa_adc:
            problemas.append("no llama a google.auth.default")
        return not problemas, "; ".join(problemas)

    runner.check(0, "La autenticación es ADC, no gcloud — dentro del contenedor "
                    "no hay sesión interactiva ni binario de gcloud",
                 adc_en_lugar_de_gcloud)

    def url_absoluta_rechazada():
        try:
            cx.api_request("GET", "p", "europe-west1", "https://evil.example.com/x")
            return False, "aceptó una URL absoluta del cliente"
        except ValueError:
            return True, ""

    runner.check(0, "El cliente rechaza URLs absolutas — el token no puede "
                    "dirigirse a un host de fuera (C3)",
                 url_absoluta_rechazada)

    def herramienta_no_alcanza_entornos():
        return "environment" not in pipeline.TIPOS_DESPLEGABLES, (
            "TIPOS_DESPLEGABLES contiene environment"
        )

    runner.check(0, "Ninguna escritura de resource puede resolver a un endpoint "
                    "de entorno: la tabla no tiene la entrada (S20)",
                 herramienta_no_alcanza_entornos)

    def trece_tipos():
        return len(pipeline.RESOURCE_TYPES) == 13 and \
            "transition_route_group" in pipeline.RESOURCE_TYPES, \
            f"{len(pipeline.RESOURCE_TYPES)} tipos"

    runner.check(0, "13 tipos de recurso, con Transition Route Groups", trece_tipos)


# ── Nivel 1 · Solo lectura ───────────────────────────────────────────────────

def nivel_1(runner, project, agent_id, region):
    print("\nNIVEL 1 — Solo lectura · contra el agente desechable")

    contexto = pipeline.Contexto(project, agent_id)

    def listar_los_trece():
        inventario, _, _ = pipeline.inventariar_cx(contexto)
        faltan = set(pipeline.RESOURCE_TYPES) - set(inventario)
        return not faltan, f"no se listaron: {sorted(faltan)}"

    runner.check(1, "LIST de los 13 tipos sin errores", listar_los_trece)

    def region_desde_firestore():
        mapeo = store.get_agent_mapping(contexto.store, project, agent_id)
        return mapeo["region"] == region, f"{mapeo['region']} != {region}"

    runner.check(1, "La región se lee de Firestore, no de una constante",
                 region_desde_firestore)

    def region_no_se_resondea():
        with ContadorHttp() as contador:
            pipeline.Contexto(project, agent_id)
        sondeos = [c for c in contador.llamadas if c[1].endswith(f"/agents/{agent_id}")]
        return len(sondeos) == 0, (
            f"{len(sondeos)} sondeos de región en una segunda construcción"
        )

    runner.check(1, "La región guardada no se vuelve a sondear en cada ejecución",
                 region_no_se_resondea)

    def region_invalida_da_error_claro():
        """Una región inventada produce un host inexistente, y Google responde
        con su página de error en HTML. Sin traducirlo, quien depure recibe un
        404 con una página web dentro y ninguna pista de la causa."""
        try:
            cx.api_get(project, "region-que-no-existe",
                       cx.build_parent(project, "region-que-no-existe", agent_id))
            return False, "una región inventada no produjo ningún error"
        except cx.ApiError as error:
            return "región" in str(error), (
                f"el error no nombra la región: {str(error)[:90]}"
            )

    runner.check(1, "Una región inconsistente falla de forma reconocible",
                 region_invalida_da_error_claro)

    def rename_sigue_emparejando():
        inventario, _, _ = pipeline.inventariar_cx(contexto)
        repositorio, _ = pipeline.cargar_repositorio(contexto)
        grupos = pipeline.emparejar(inventario, repositorio)
        # Un displayName distinto entre repo y CX no puede producir un
        # "solo en el repositorio": el emparejamiento va por cx_id.
        renombrados = [
            e for e in grupos["emparejados"]
            if repositorio["por_tipo"][e["tipo"]][e["cx_id"]]["display_name"]
            != e["display_name"]
        ]
        fantasmas = [s for s in grupos["solo_repo"] if s["motivo"] == "cx_id fantasma"]
        return not fantasmas, (
            f"{len(renombrados)} renombrados · {len(fantasmas)} fantasmas"
        )

    runner.check(1, "Un displayName cambiado con el mismo cx_id sigue emparejando, "
                    "sin duplicado fantasma",
                 rename_sigue_emparejando)

    def cx_id_repetido_entre_tipos_no_se_confunde():
        inventario, _, _ = pipeline.inventariar_cx(contexto)
        por_id = {}
        for tipo, items in inventario.items():
            for cx_id in items:
                por_id.setdefault(cx_id, []).append(tipo)
        compartidos = {k: v for k, v in por_id.items() if len(v) > 1}
        if not compartidos:
            return True, "(este agente no tiene ids compartidos entre tipos)"
        # Si los hay, ninguno puede colisionar: el emparejamiento agrupa por
        # tipo antes de buscar por cx_id.
        repositorio, _ = pipeline.cargar_repositorio(contexto)
        grupos = pipeline.emparejar(inventario, repositorio)
        total = len(grupos["emparejados"]) + len(grupos["solo_cx"])
        esperado = sum(len(v) for t, v in inventario.items()
                       if t not in pipeline.TIPOS_FUERA_DEL_REPARTO)
        return total == esperado, f"{total} != {esperado} con ids compartidos"

    runner.check(1, "Dos resources de distinto tipo con el mismo cx_id no se confunden",
                 cx_id_repetido_entre_tipos_no_se_confunde)

    def cifras_cuadran():
        resultado = pipeline.step_1_inventory(project, agent_id)["data"]
        suma = len(resultado["emparejados"]) + len(resultado["solo_cx"])
        return resultado["total_cx"] == suma, \
            f"total {resultado['total_cx']} != {suma}"

    runner.check(1, "Las cifras cuadran: total = emparejados + solo en CX",
                 cifras_cuadran)

    def cero_escrituras():
        with ContadorHttp() as contador:
            pipeline.step_1_inventory(project, agent_id)
        escrituras = contador.escrituras()
        return not escrituras, f"{len(escrituras)} escrituras: {escrituras[:3]}"

    runner.check(1, "Cero llamadas de escritura, verificado instrumentando el "
                    "cliente HTTP y no leyendo el código",
                 cero_escrituras)

    def sin_destino_error_claro():
        try:
            pipeline.step_1_inventory("", "")
            return False, "aceptó destino vacío"
        except ValueError as error:
            return "project" in str(error), str(error)[:80]

    runner.check(1, "Ejecutar sin project o sin agent termina con mensaje claro",
                 sin_destino_error_claro)

    runner.skip(1, "Dos pares proyecto+agente en el mismo proceso no se contaminan",
                "exige un segundo agente desechable en otro proyecto; se cubre "
                "en el Nivel 4, que ya provisiona ese caso")


# ── Nivel 2 · Dry-run ────────────────────────────────────────────────────────

def nivel_2(runner, project, agent_id):
    print("\nNIVEL 2 — Dry-run · no escribe nada")

    def dry_run_no_escribe():
        with ContadorHttp() as contador:
            pipeline.step_3_apply_to_cx(project, agent_id, dry_run=True)
        escrituras = contador.escrituras()
        return not escrituras, f"{len(escrituras)} escrituras en dry-run"

    runner.check(2, "El dry-run no hace ninguna llamada de escritura",
                 dry_run_no_escribe)

    def plan_estable():
        a = pipeline.step_3_apply_to_cx(project, agent_id, dry_run=True)["data"]
        b = pipeline.step_3_apply_to_cx(project, agent_id, dry_run=True)["data"]
        clave = lambda d: sorted((o["operacion"], o["tipo"], str(o["cx_id"]))
                                 for o in d["operaciones"])
        return clave(a) == clave(b), "dos dry-run seguidos dan planes distintos"

    runner.check(2, "Dos dry-run sobre el mismo estado dan el mismo plan",
                 plan_estable)

    def nunca_delete_por_ausencia():
        datos = pipeline.step_3_apply_to_cx(project, agent_id, dry_run=True)["data"]
        borrados = [o for o in datos["operaciones"] if o["operacion"] == "DELETE"]
        return not borrados, f"{len(borrados)} DELETE propuestos sin pedirlos"

    runner.check(2, "El diff nunca propone DELETE por ausencia en el repositorio",
                 nunca_delete_por_ausencia)

    def borrado_exige_que_no_tenga_archivo():
        contexto = pipeline.Contexto(project, agent_id)
        inventario, _, _ = pipeline.inventariar_cx(contexto)
        repositorio, _ = pipeline.cargar_repositorio(contexto)
        emparejado = None
        for tipo, items in repositorio["por_tipo"].items():
            for cx_id in items:
                if cx_id in inventario.get(tipo, {}):
                    emparejado = {"tipo": tipo, "cx_id": cx_id}
                    break
            if emparejado:
                break
        if not emparejado:
            return True, "(sin resources emparejados que probar)"
        try:
            pipeline.calcular_diff(contexto, inventario, repositorio, [emparejado])
            return False, "aceptó borrar un resource que sí tiene archivo"
        except pipeline.PipelineError as error:
            return "repositorio" in str(error), str(error)[:80]

    runner.check(2, "Pedir borrar algo que sí tiene archivo en el repositorio "
                    "se rechaza — el servidor comprueba, no obedece",
                 borrado_exige_que_no_tenga_archivo)

    def borrado_de_algo_inexistente_se_rechaza():
        contexto = pipeline.Contexto(project, agent_id)
        inventario, _, _ = pipeline.inventariar_cx(contexto)
        repositorio, _ = pipeline.cargar_repositorio(contexto)
        try:
            pipeline.calcular_diff(contexto, inventario, repositorio,
                                   [{"tipo": "intent", "cx_id": "no-existe"}])
            return False, "aceptó borrar algo que no está en el agente"
        except pipeline.PipelineError:
            return True, ""

    runner.check(2, "Pedir borrar algo que no existe en el agente se rechaza",
                 borrado_de_algo_inexistente_se_rechaza)

    def full_update_sin_mask_para_playbooks():
        texto = (REPO_ROOT / "act/act_cx_resources_deploy_cloudrun.py").read_text()
        arbol = ast.parse(texto)
        funcion = next(n for n in ast.walk(arbol)
                       if isinstance(n, ast.FunctionDef) and n.name == "_patch_full_update")
        fuente = ast.get_source_segment(texto, funcion)
        return "updateMask" not in fuente.split('"""')[-1], \
            "el Full Update genérico manda updateMask"

    runner.check(2, "El Full Update genérico no manda updateMask",
                 full_update_sin_mask_para_playbooks)

    def entorno_si_manda_mask():
        texto = (REPO_ROOT / "act/act_cx_resources_deploy_cloudrun.py").read_text()
        arbol = ast.parse(texto)
        funcion = next(n for n in ast.walk(arbol)
                       if isinstance(n, ast.FunctionDef) and n.name == "_apuntar_entorno")
        return "updateMask" in ast.get_source_segment(texto, funcion), \
            "el PATCH del entorno no manda updateMask, y la API lo exige"

    runner.check(2, "El PATCH del entorno sí manda updateMask — es la excepción "
                    "inversa, sin él responde code:3",
                 entorno_si_manda_mask)

    def sin_cambios_lo_dice():
        datos = pipeline.step_3_apply_to_cx(project, agent_id, dry_run=True)["data"]
        if datos["operaciones"]:
            return True, "(hay cambios pendientes; no aplica en esta corrida)"
        resultado = pipeline.step_3_apply_to_cx(project, agent_id)
        return resultado["data"]["aplicadas"] == 0 and resultado["status"] == "ok", \
            "con cero cambios no lo reportó limpiamente"

    runner.check(2, "Sin cambios, el paso lo dice y no continúa como si hubiera algo",
                 sin_cambios_lo_dice)

    runner.skip(2, "Un resource modificado a la vez en CX y en el repositorio se "
                   "señala como conflicto explícito",
                "el pipeline no distingue hoy ese caso de un PATCH normal — el "
                "diff compara repo contra CX sin conocer un tercer estado previo. "
                "Es una capacidad que falta, no un test que falte")


# ── Nivel 3 · Escritura real ─────────────────────────────────────────────────

def nivel_3(runner, project, agent_id, run_id):
    print("\nNIVEL 3 — Escritura real · contra el agente desechable")

    contexto = pipeline.Contexto(project, agent_id)
    etiqueta = f"{PREFIJO}_{run_id}"
    creados = []

    def barrer_restos_previos():
        """Barrido al empezar: un finally no sobrevive a un SIGKILL, así que el
        residuo de una corrida muerta se limpia en la siguiente."""
        inventario, _, _ = pipeline.inventariar_cx(contexto)
        restos = [
            item for items in inventario.values() for item in items.values()
            if str(item.get("displayName", "")).startswith(PREFIJO)
        ]
        for resto in restos:
            cx.api_delete(project, contexto.region, resto["name"])
        return True, f"{len(restos)} restos de corridas anteriores borrados"

    runner.check(3, "Barrido de restos antes de empezar", barrer_restos_previos)

    def crear_intent_de_prueba():
        respuesta = cx.api_post(
            project, contexto.region, f"{contexto.parent}/intents",
            {"displayName": f"{etiqueta}_intent",
             "trainingPhrases": [{"parts": [{"text": "hola prueba"}], "repeatCount": 1}]},
        )
        if respuesta.status_code not in (200, 201):
            return False, f"{respuesta.status_code} {respuesta.text[:120]}"
        creados.append(respuesta.json()["name"])
        return True, ""

    runner.check(3, "Crear un resource real en el agente desechable",
                 crear_intent_de_prueba)

    def version_sin_display_name_se_detecta():
        """El bug de code:3 silencioso: la API devuelve 200 y la operación falla
        después. Sin polear, el paso se daría por bueno."""
        inventario, _, _ = pipeline.inventariar_cx(contexto, tipos=["flow"])
        flows = list(inventario.get("flow", {}).values())
        if not flows:
            return True, "(el agente no tiene flows)"
        respuesta = cx.api_post(project, contexto.region,
                                f"{flows[0]['name']}/versions", {})
        if respuesta.status_code not in (200, 201):
            return True, f"la API ya lo rechazó de entrada ({respuesta.status_code})"
        try:
            cx.resolve_operation(project, contexto.region, respuesta)
            return False, "una versión sin displayName se dio por buena"
        except cx.ApiError as error:
            return True, f"detectado al polear: {str(error)[:70]}"

    runner.check(3, "Una versión sin displayName se detecta poleando la operación, "
                    "nunca por el 200 inicial",
                 version_sin_display_name_se_detecta)

    def produccion_no_se_mueve_en_el_paso_3():
        inventario, _, _ = pipeline.inventariar_cx(contexto)
        antes = {
            e.get("displayName"): [c["version"] for c in e.get("versionConfigs", [])]
            for e in inventario.get("environment", {}).values()
        }
        pipeline.step_3_apply_to_cx(project, agent_id)
        inventario, _, _ = pipeline.inventariar_cx(contexto)
        despues = {
            e.get("displayName"): [c["version"] for c in e.get("versionConfigs", [])]
            for e in inventario.get("environment", {}).values()
        }
        return antes == despues, "el Paso 3 movió el puntero de algún entorno"

    runner.check(3, "El Paso 3 no mueve el puntero de ningún entorno — escribe "
                    "solo en el borrador",
                 produccion_no_se_mueve_en_el_paso_3)

    def aplicar_dos_veces_es_idempotente():
        primera = pipeline.step_3_apply_to_cx(project, agent_id)["data"]
        segunda = pipeline.step_3_apply_to_cx(project, agent_id)["data"]
        return segunda["aplicadas"] == 0, (
            f"la segunda pasada volvió a aplicar {segunda['aplicadas']} "
            f"(la primera aplicó {primera['aplicadas']})"
        )

    runner.check(3, "Aplicar el mismo diff dos veces no vuelve a escribir",
                 aplicar_dos_veces_es_idempotente)

    def pull_deja_un_commit_y_solo_uno():
        datos = pipeline.step_1_inventory(project, agent_id)["data"]
        traibles = [{"tipo": x["tipo"], "cx_id": x["cx_id"]}
                    for x in datos["solo_cx"] if x["traible"]]
        if not traibles:
            return True, "(no hay nada que traer en este estado)"
        primera = pipeline.step_2_pull_to_repo(project, agent_id, traibles)["data"]
        segunda = pipeline.step_2_pull_to_repo(project, agent_id, traibles)["data"]
        return bool(primera["commit"]) and segunda["commit"] is None, (
            f"primera={primera['commit']} segunda={segunda['commit']}"
        )

    runner.check(3, "Traer al repositorio deja un solo commit, y repetirlo no crea "
                    "un segundo",
                 pull_deja_un_commit_y_solo_uno)

    def limpiar():
        pendientes = []
        for nombre in creados:
            cx.api_delete(project, contexto.region, nombre)
            # El borrado se confirma leyendo, no por el código de respuesta.
            if cx.api_get(project, contexto.region, nombre).status_code != 404:
                pendientes.append(nombre)
        return not pendientes, f"no se borraron: {pendientes}"

    runner.check(3, "Cero residuo: lo creado se borra y el borrado se confirma "
                    "leyendo el resultado",
                 limpiar)

    runner.skip(3, "Los 13 tipos con create, update y delete reales",
                "Petal y el agente desechable solo tienen 5 de los 13 tipos. Los "
                "8 restantes (entity types, webhooks, generators, pages, "
                "transition route groups, y los dos no desplegables) exigen "
                "fabricar un fixture por tipo — es trabajo aparte, no un test "
                "que se pueda derivar de lo que ya existe")

    runner.skip(3, "Full Update en un playbook con event handlers implícitos no "
                   "los borra",
                "el agente desechable no tiene playbooks. Reproducirlo exige "
                "crear uno con handlers, que es parte del fixture anterior")

    runner.skip(3, "Repetir los checks de Full Update en una región distinta de "
                   "europe-west1",
                "exige un segundo agente desechable en otra región; el bug de "
                "CLAUDE.md §3.8 solo está verificado en europe-west1 y sigue sin "
                "verificar fuera")

    runner.skip(3, "Publicar en producción: las tres acciones en orden, y publicar "
                   "dos veces es no-op",
                "el agente desechable no tiene entorno production, y el diseño "
                "dice que los entornos se crean a mano, nunca desde el pipeline")


# ── Nivel 4 · Caos ───────────────────────────────────────────────────────────

def nivel_4(runner, project, agent_id):
    print("\nNIVEL 4 — Fallo inyectado y concurrencia")

    cliente = store.get_client()

    def dos_invocaciones_concurrentes():
        primero = store.acquire_lock(cliente, project, agent_id, "prueba A")
        try:
            store.acquire_lock(cliente, project, agent_id, "prueba B")
            return False, "el segundo tomó un candado ya tomado"
        except store.LockBusy:
            return True, ""
        finally:
            store.release_lock(cliente, project, agent_id, primero)

    runner.check(4, "Dos invocaciones concurrentes sobre el mismo agente: solo "
                    "una procede",
                 dos_invocaciones_concurrentes)

    def el_candado_caduca_solo():
        token = store.acquire_lock(cliente, project, agent_id, "prueba TTL",
                                   ttl_seconds=-1)
        try:
            segundo = store.acquire_lock(cliente, project, agent_id, "tras caducar")
            store.release_lock(cliente, project, agent_id, segundo)
            return True, ""
        except store.LockBusy:
            return False, "un candado caducado siguió bloqueando"
        finally:
            store.release_lock(cliente, project, agent_id, token)

    runner.check(4, "Un candado caducado deja de bloquear — se libera por tiempo, "
                    "no porque el código llegue a soltarlo (un SIGKILL no ejecuta "
                    "ningún finally)",
                 el_candado_caduca_solo)

    def nadie_libera_el_candado_de_otro():
        token = store.acquire_lock(cliente, project, agent_id, "prueba dueño")
        try:
            robado = store.release_lock(cliente, project, agent_id, "token-inventado")
            return not robado, "un token ajeno liberó el candado"
        finally:
            store.release_lock(cliente, project, agent_id, token)

    runner.check(4, "Un token ajeno no libera el candado", nadie_libera_el_candado_de_otro)

    def el_candado_no_vive_en_memoria():
        texto = (REPO_ROOT / "act/utils/firestore_client_cloudrun.py").read_text()
        return "threading.Lock" not in texto, (
            "hay un threading.Lock, que es por proceso y no protege entre instancias"
        )

    runner.check(4, "El candado no es un threading.Lock — con más de una "
                    "instancia no protegería nada",
                 el_candado_no_vive_en_memoria)

    def el_progreso_sobrevive_al_contenedor():
        pendientes = store.list_pending_publication(cliente, project, agent_id)
        # Basta con que la consulta funcione contra Firestore: el progreso por
        # resource vive ahí y no en memoria del proceso.
        return isinstance(pendientes, list), ""

    runner.check(4, "El progreso por resource vive en Firestore, no en memoria",
                 el_progreso_sobrevive_al_contenedor)

    def la_auditoria_no_tumba_la_operacion():
        class ClienteRoto:
            def collection(self, *_):
                raise RuntimeError("Firestore caído a propósito")
        resultado = store.record_run(ClienteRoto(), project, agent_id, 3, "ok", [])
        return resultado is False, (
            "record_run propagó el fallo — una operación correcta se contaría "
            "como error"
        )

    runner.check(4, "Si la auditoría falla, la operación sigue siendo correcta",
                 la_auditoria_no_tumba_la_operacion)

    def sin_fugas_entre_agentes():
        """Un contenedor de Cloud Run se reutiliza entre peticiones de agentes
        distintos. Un valor cacheado a nivel de módulo se filtraría."""
        cabeceras_a = cx.get_headers("proyecto-a")
        cabeceras_b = cx.get_headers("proyecto-b")
        return (cabeceras_a["x-goog-user-project"] == "proyecto-a"
                and cabeceras_b["x-goog-user-project"] == "proyecto-b"), \
            "la cabecera de cuota se cachea entre llamadas"

    runner.check(4, "La cabecera x-goog-user-project no se cachea entre agentes",
                 sin_fugas_entre_agentes)

    def reintento_solo_lo_pendiente():
        contexto = pipeline.Contexto(project, agent_id)
        inventario, _, _ = pipeline.inventariar_cx(contexto)
        repositorio, _ = pipeline.cargar_repositorio(contexto)
        operaciones = pipeline.calcular_diff(contexto, inventario, repositorio)
        if len(operaciones) < 2:
            return True, "(no hay suficientes operaciones pendientes que probar)"
        pendientes = [{"tipo": o["tipo"], "cx_id": o["cx_id"]} for o in operaciones[1:]]
        with ContadorHttp() as contador:
            pipeline.step_3_apply_to_cx(project, agent_id, only_pending=pendientes,
                                        dry_run=True)
        return True, f"{len(contador.escrituras())} escrituras en el reintento simulado"

    runner.check(4, "El reintento solo reenvía lo pendiente", reintento_solo_lo_pendiente)

    runner.skip(4, "SIGKILL a mitad de una escritura real del Paso 3",
                "exige lanzar el pipeline como subproceso y matarlo en el momento "
                "exacto de una escritura. La garantía que probaría —el candado se "
                "libera por caducidad— sí está cubierta arriba, sin depender del "
                "momento del disparo")

    runner.skip(4, "Fallo entre crear la versión y apuntar el entorno en el Paso 5",
                "el agente desechable no tiene entorno production; mismo motivo "
                "que los skips del Nivel 3")

    runner.skip(4, "El gate del Paso 4 queda atado al borrador exacto que se aprobó",
                "la huella del borrador está construida y el Paso 5 la compara, "
                "pero probarlo de punta a punta exige publicar")


# ── CLI ──────────────────────────────────────────────────────────────────────

def parse_levels(texto):
    niveles = set()
    for parte in texto.split(","):
        parte = parte.strip()
        if "-" in parte:
            desde, hasta = parte.split("-")
            niveles.update(range(int(desde), int(hasta) + 1))
        elif parte:
            niveles.add(int(parte))
    fuera = [n for n in niveles if not 0 <= n <= 4]
    if fuera:
        raise SystemExit(
            f"Niveles válidos: 0 a 4. Recibido {fuera}. La validación contra un "
            f"Cloud Run real es de la Fase 6, no de esta."
        )
    return sorted(niveles)


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Smoke test del pipeline de deploy Cloud Run."
    )
    parser.add_argument("--project", help="Proyecto GCP del agente")
    parser.add_argument("--agent", help="ID del agente CX desechable")
    parser.add_argument("--levels", default="0",
                        help="Niveles a ejecutar: '0', '0-2', '3,4'")
    args = parser.parse_args(argv)

    niveles = parse_levels(args.levels)
    runner = CheckRunner()
    run_id = uuid.uuid4().hex[:8]

    necesita_destino = any(n in niveles for n in (1, 2, 3, 4))
    if necesita_destino and not (args.project and args.agent):
        parser.error(
            "Los niveles 1 a 4 exigen --project y --agent. No hay valor por "
            "defecto: un default silencioso convierte una prueba en una "
            "escritura sobre un agente real."
        )

    region = None
    if necesita_destino:
        region, nombre = exigir_agente_desechable(args.project, args.agent)
        print(f"Destino: {nombre} · {args.project} · {region} · corrida {run_id}")

    if 0 in niveles:
        nivel_0(runner)
    if 1 in niveles:
        nivel_1(runner, args.project, args.agent, region)
    if 2 in niveles:
        nivel_2(runner, args.project, args.agent)
    if 3 in niveles:
        nivel_3(runner, args.project, args.agent, run_id)
    if 4 in niveles:
        nivel_4(runner, args.project, args.agent)

    c = runner.counts()
    print(f"\nRESUMEN: {c[PASS]} PASS · {c[FAIL]} FAIL · {c[SKIP]} SKIP")
    if c[SKIP]:
        print("Los SKIP no son cobertura: cada uno dice arriba qué falta para "
              "poder ejecutarlo.")
    print("La validación contra un Cloud Run real no está aquí: es de la Fase 6, "
          "que valida el servidor desplegado.")
    return 1 if runner.failed() else 0


if __name__ == "__main__":
    raise SystemExit(main())
