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

import requests

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from act import act_cx_resources_deploy_cloudrun as pipeline
from act.utils import cx_client_cloudrun as cx
from act.utils import cx_payloads_cloudrun as payloads
from act.utils import firestore_client_cloudrun as store

PASS, FAIL, SKIP = "PASS", "FAIL", "SKIP"


def _lleva_la_marca(tipo, item):
    """Si un resource lo creó una corrida de este validador.

    Las **versiones** llevan la marca en `description` cuando cuelgan de un
    playbook, porque ese endpoint no acepta `displayName`. El resto de tipos
    solo en `displayName`: buscar en la descripción de cualquier resource caza
    también los que una prueba se limitó a *modificar* — y así el barrido
    intentaba borrar el flow de arranque del agente, que CX no deja borrar.
    """
    if tipo == "version":
        return PREFIJO in f"{item.get('displayName','')} {item.get('description','')}"
    return str(item.get("displayName", "")).startswith(PREFIJO)


def pathlib_stem(ruta):
    """El nombre del archivo sin carpeta ni extensión."""
    return ruta.rsplit("/", 1)[-1].rsplit(".", 1)[0]

# Marca que un agente tiene que llevar en su nombre para que este script acepte
# escribir en él. No es una lista de agentes prohibidos —una lista se queda
# desactualizada— sino lo contrario: solo se admite lo que se declara
# desechable, así que un agente real nunca pasa por olvido.
MARCA_DESECHABLE = "desechable"

# Prefijo de todo lo que crea una corrida. Permite saber qué borrar y de qué
# ejecución es, incluso si dos corridas se solapan.
PREFIJO = "actval"

# Cuerpo mínimo válido de cada tipo desplegable, para fabricar resources de
# prueba. No es un fixture guardado: se construye en el momento, y solo lleva
# los campos que la API exige para que el POST no se caiga por otra razón.
CUERPO_MINIMO = {
    "intent": {"trainingPhrases": [{"parts": [{"text": "hola"}], "repeatCount": 1}]},
    "entity_type": {"kind": "KIND_MAP",
                    "entities": [{"value": "a", "synonyms": ["a"]}]},
    "webhook": {"genericWebService": {"uri": "https://example.invalid/x"},
                "timeout": "5s"},
    "generator": {"promptText": {"text": "resume"}},
    "playbook": {"goal": "objetivo de prueba", "playbookType": "ROUTINE",
                 "instruction": {"steps": [{"text": "haz algo"}]}},
    "example": {"actions": [{"userUtterance": {"text": "hola"}},
                            {"agentUtterance": {"text": "hola"}}],
                "conversationState": "OUTPUT_STATE_OK"},
    "flow": {},
    "page": {},
    "transition_route_group": {"transitionRoutes": []},
    "tool": {"description": "herramienta de prueba", "openApiSpec": {
        "textSchema": "openapi: 3.0.0\ninfo:\n  title: x\n  version: '1'\npaths: {}\n"}},
}

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

# Ramas que este script no puede tocar bajo ningún concepto. El Paso 5 fusiona
# la rama de trabajo en la principal, así que si la principal de un proyecto es
# `main`, probar la publicación escribe en ella. Ocurrió: una tanda de checks
# dejó cinco commits de merge en `main` con nombres como "Publicar
# corte_inyectado en producción".
RAMAS_INTOCABLES = ("main", "master", "produccion", "production")


def exigir_rama_principal_desechable(project, client=None):
    """Se niega a arrancar si publicar acabaría escribiendo en la rama real.

    Nada impedía que un check de publicar fusionara en `main`: el agente estaba
    marcado como desechable, pero la rama principal no la miraba nadie.
    """
    from act.utils import firestore_client_cloudrun as _store
    try:
        proyecto = _store.get_project_mapping(client or _store.get_client(), project)
    except Exception:
        return None
    principal = proyecto.get("rama_principal", "")
    if principal in RAMAS_INTOCABLES:
        raise SystemExit(
            f"La rama principal del proyecto {project} es '{principal}'. Este "
            f"script prueba la publicación, y publicar fusiona la rama de "
            f"trabajo en la principal: correría un merge real sobre '{principal}'. "
            f"Apunta el proyecto a una rama principal desechable antes de "
            f"lanzarlo. No se ha tocado nada."
        )
    return principal


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
        """El repositorio es del proyecto y la región del agente: son dos
        documentos con dos esquemas, y ninguno puede quedarse sin sus campos."""
        agente = set(store.CAMPOS_OBLIGATORIOS_AGENTE)
        proyecto = set(store.CAMPOS_OBLIGATORIOS_PROYECTO)
        problemas = []
        if agente != {"project", "agent_id", "region", "rama"}:
            problemas.append(f"agente: {sorted(agente)}")
        if proyecto != {"project", "repo", "rama_principal"}:
            problemas.append(f"proyecto: {sorted(proyecto)}")
        if "repo" in agente:
            problemas.append("el agente exige repositorio, y el repositorio es del proyecto")
        if "rama" in proyecto:
            problemas.append("el proyecto fija la rama de trabajo, y esa es de cada agente: "
                             "compartirla haría que publicar uno arrastrara a sus hermanos")
        return not problemas, " · ".join(problemas)

    runner.check(0, "Los documentos de proyecto y de agente declaran sus campos "
                    "obligatorios, y el repositorio vive en el del proyecto",
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
        # `open(` a secas cazaba `tarfile.open(fileobj=...)`, que lee de
        # memoria y no toca el disco. Lo que importa es escribir en una ruta.
        sucios = []
        for ruta in ARCHIVOS_PIPELINE:
            for i, linea in enumerate((REPO_ROOT / ruta).read_text().splitlines(), 1):
                if linea.strip().startswith("#"):
                    continue
                for patron in ("/tmp/", "tempfile.", "NamedTemporary",
                               ".write_text(", ".write_bytes(", "open(\"w"):
                    if patron in linea:
                        sucios.append(f"{ruta}:{i} {patron}")
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

def nivel_1(runner, project, agent_id, region, run_id, hermano=None):
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
        """Se renombra de verdad un resource en CX y se comprueba que sigue
        emparejando con su archivo.

        Mirar el estado tal cual está no prueba nada: justo después de un pull
        no hay ningún nombre distinto entre los dos lados, así que el escenario
        no llega a existir y el check pasaría siempre.
        """
        inventario, _, _ = pipeline.inventariar_cx(contexto)
        repositorio, _ = pipeline.cargar_repositorio(contexto)
        emparejados = pipeline.emparejar(inventario, repositorio)["emparejados"]
        objetivo = next((e for e in emparejados if e["tipo"] == "intent"),
                        None) or (emparejados[0] if emparejados else None)
        if objetivo is None:
            return False, "no hay ningún resource emparejado que renombrar"

        remoto = inventario[objetivo["tipo"]][objetivo["cx_id"]]
        original = remoto.get("displayName")
        cuerpo = {k: v for k, v in remoto.items()
                  if k not in pipeline.CAMPOS_LEIDOS_NO_ENVIADOS}
        cuerpo["displayName"] = f"{PREFIJO}_{run_id}_renombrado"
        respuesta = cx.api_patch(project, contexto.region, remoto["name"], cuerpo)
        if respuesta.status_code not in (200, 201):
            return False, f"no se pudo renombrar: {respuesta.status_code}"
        try:
            inv2, _, _ = pipeline.inventariar_cx(contexto)
            grupos = pipeline.emparejar(inv2, repositorio)
            sigue = any(e["cx_id"] == objetivo["cx_id"]
                        for e in grupos["emparejados"])
            fantasma = any(s.get("cx_id") == objetivo["cx_id"]
                           for s in grupos["solo_repo"])
            return sigue and not fantasma, (
                f"tras renombrar: emparejado={sigue} · fantasma={fantasma}. "
                f"Si el emparejamiento cayera al nombre, el renombrado "
                f"produciría un duplicado en el repositorio"
            )
        finally:
            cuerpo["displayName"] = original
            cx.api_patch(project, contexto.region, remoto["name"], cuerpo)

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

    def la_cabecera_nace_completa_tipo_por_tipo():
        """La cabecera que escribe el pull, comprobada en los 13 tipos.

        Es la función real del pull la que se ejercita, sobre los resources
        reales del agente: se comprueba que `tipo` es el correcto, que el
        `cx_id` es el que CX asigna, y que `padre` está relleno **solo** si el
        tipo cuelga de otro — y que ese padre existe de verdad en el agente.

        Un tipo con la cabecera a medias produce un archivo que el pipeline no
        sabrá emparejar después, y eso no se ve hasta el deploy siguiente.
        """
        inventario, _, _ = pipeline.inventariar_cx(contexto)
        fallos, revisados = [], []
        for tipo, items in inventario.items():
            if tipo in pipeline.TIPOS_FUERA_DEL_REPARTO:
                continue
            item = next((i for i in items.values()
                         if not pipeline.es_nativo(tipo, i)), None)
            if item is None:
                continue
            spec = pipeline.RESOURCE_TYPES[tipo]
            padre_id = pipeline._padre_id_de(tipo, item) if spec.get("padre") else None
            documento = __import__("yaml").safe_load(
                pipeline._yaml_para_repo(tipo, item, padre_id))
            meta = documento.get("metadata") or {}
            revisados.append(tipo)

            if meta.get("tipo") != tipo:
                fallos.append(f"{tipo}: metadata.tipo = {meta.get('tipo')!r}")
            if meta.get("cx_id") != pipeline._cx_id_de(item):
                fallos.append(f"{tipo}: cx_id {meta.get('cx_id')!r} != "
                              f"{pipeline._cx_id_de(item)!r}")
            if "metadata" in {k for k in documento if k != "metadata"}:
                fallos.append(f"{tipo}: metadata duplicada en el cuerpo")
            if spec.get("padre"):
                if not meta.get("padre"):
                    fallos.append(f"{tipo}: cuelga de {spec['padre']} y padre "
                                  f"viene vacío")
                elif meta["padre"] == pipeline.PADRE_AGENTE:
                    # Los tipos que existen en los dos niveles lo declaran así
                    # cuando cuelgan del agente. Es lo correcto, no un hueco.
                    if not spec.get("tambien_en_agente"):
                        fallos.append(f"{tipo}: dice colgar del agente y no puede")
                elif meta["padre"] not in inventario.get(spec["padre"], {}):
                    fallos.append(f"{tipo}: declara padre {meta['padre']}, que "
                                  f"no existe como {spec['padre']}")
            elif meta.get("padre") is not None:
                fallos.append(f"{tipo}: no cuelga de nada y trae padre "
                              f"{meta['padre']!r}")

        return not fallos, f"revisados {len(revisados)} tipos · " + " | ".join(fallos)

    runner.check(1, "El pull construye la cabecera completa y correcta en cada "
                    "tipo: tipo, cx_id y padre solo cuando corresponde",
                 la_cabecera_nace_completa_tipo_por_tipo)

    def un_archivo_sin_cabecera_no_es_un_resource():
        """Lo que convierte un archivo en resource es tener cabecera.

        Un YAML sin ella no es un resource del pipeline y no puede aparecer en
        ningún grupo del reparto ni en el diff — el repositorio tiene YAML que
        nunca fueron resources: taxonomías, configuraciones, specs OpenAPI.
        """
        original = contexto.gh.read_repo_files
        archivos = dict(original(contexto.gh.branch_head(contexto.rama)))
        intruso = {"path": "definitions/intents/sin_cabecera.yaml"}
        archivos[intruso["path"]] = (
            b"displayName: sin_cabecera\ndescription: no soy un resource\n")
        contexto.gh.read_repo_files = lambda *_a, **_k: archivos
        try:
            repositorio, _ = pipeline.cargar_repositorio(contexto)
            inventario, _, _ = pipeline.inventariar_cx(contexto)
            grupos = pipeline.emparejar(inventario, repositorio)
            operaciones = pipeline.calcular_diff(contexto, inventario, repositorio)
            aparece = (
                any(x.get("ruta") == intruso["path"] for x in grupos["solo_repo"])
                or any(o.get("ruta") == intruso["path"] for o in operaciones)
            )
            return not aparece, "el archivo sin cabecera entró en el reparto o en el diff"
        finally:
            contexto.gh.read_repo_files = original

    runner.check(1, "Un YAML sin cabecera no es un resource: ni entra en el "
                    "reparto ni genera operación",
                 un_archivo_sin_cabecera_no_es_un_resource)

    def un_padre_inexistente_se_rechaza_con_su_nombre():
        """Resolver dónde cuelga un resource es el único punto donde el padre
        declarado se usa. Un padre que no existe tiene que decirlo, no fallar
        con un error que apunte a otro sitio."""
        operacion = pipeline._operacion(
            "POST", "example", None,
            {"ruta": "definitions/examples/huerfano.yaml",
             "display_name": "huerfano", "padre": "padre-que-no-existe"},
            {"displayName": "huerfano"},
        )
        try:
            pipeline._ruta_padre(contexto, operacion, {"playbook": {}})
            return False, "aceptó un padre que no existe"
        except pipeline.PipelineError as error:
            texto = str(error)
            return ("padre-que-no-existe" in texto and "playbook" in texto), \
                f"el error no nombra el padre ni su tipo: {texto[:90]}"

    runner.check(1, "Un padre declarado que no existe se rechaza nombrándolo, "
                    "junto al tipo que se esperaba",
                 un_padre_inexistente_se_rechaza_con_su_nombre)

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

    def descubrimiento_lista_proyectos():
        datos = pipeline.discover()["data"]
        proyectos = datos["proyectos"]
        return bool(proyectos) and all("projectId" in p for p in proyectos), \
            f"{len(proyectos)} proyectos, sin projectId en alguno"

    runner.check(1, "Descubrimiento sin proyecto devuelve la lista de proyectos GCP",
                 descubrimiento_lista_proyectos)

    def descubrimiento_lista_agentes_con_su_repositorio():
        datos = pipeline.discover(project)["data"]
        agentes = datos["agentes"]
        nuestro = next((a for a in agentes if a["agentId"] == agent_id), None)
        if nuestro is None:
            return False, "el agente desechable no aparece en el descubrimiento"
        campos = {"agentId", "displayName", "region", "repo", "rama", "vinculado"}
        return campos <= set(nuestro) and nuestro["vinculado"] and nuestro["repo"], \
            f"faltan campos o no viene vinculado: {nuestro}"

    runner.check(1, "Descubrimiento devuelve cada agente con el repositorio que "
                    "le corresponde — es lo que rellena los desplegables del panel",
                 descubrimiento_lista_agentes_con_su_repositorio)

    def agentes_sin_repositorio_no_se_omiten():
        datos = pipeline.discover(project)["data"]
        sin_vincular = [a for a in datos["agentes"] if not a["vinculado"]]
        # Lo que importa no es que existan, sino que si existen vengan marcados
        # en vez de desaparecer: omitirlos los haría invisibles justo cuando
        # hace falta vincularlos.
        return all(a["repo"] is None for a in sin_vincular), \
            "un agente sin vincular trae repositorio"

    runner.check(1, "Un agente sin repositorio se incluye marcado, nunca se omite "
                    "en silencio",
                 agentes_sin_repositorio_no_se_omiten)

    def los_trece_tipos_traen_contenido():
        inventario, _, _ = pipeline.inventariar_cx(contexto)
        vacios = [t for t, items in inventario.items() if not items]
        return not vacios, f"sin contenido: {sorted(vacios)}"

    runner.check(1, "Los 13 tipos devuelven contenido real, no solo responden",
                 los_trece_tipos_traen_contenido)

    if hermano:
        def cada_agente_ve_solo_lo_suyo():
            """Un repositorio compartido no puede filtrar los archivos de un
            agente en la vista de otro.

            Sin el filtro por agente, los archivos del hermano aparecerían
            como "solo en el repositorio" del nuestro — pendientes de crear en
            CX, cuando ya existen en su propio agente.
            """
            resultados = {}
            for quien in (agent_id, hermano):
                ctx = pipeline.Contexto(project, quien)
                inv, _, _ = pipeline.inventariar_cx(ctx)
                repo, _ = pipeline.cargar_repositorio(ctx)
                grupos = pipeline.emparejar(inv, repo)
                resultados[quien] = {
                    "mios": {e["cx_id"] for e in grupos["emparejados"]},
                    "rutas": {e["ruta"] for e in grupos["emparejados"]},
                    "solo_repo": len(grupos["solo_repo"]),
                    "otros": len(repo["otros_agentes"]),
                }
            a, b = resultados[agent_id], resultados[hermano]
            comunes = a["rutas"] & b["rutas"]
            if comunes:
                return False, f"{len(comunes)} archivos aparecen en los dos agentes"
            if not a["otros"] or not b["otros"]:
                return False, ("ninguno de los dos ve archivos del otro: no "
                               "están compartiendo repositorio de verdad")
            return True, (f"{a['otros']} y {b['otros']} archivos ajenos, "
                          f"contados aparte y fuera del reparto")

        runner.check(1, "Dos agentes comparten repositorio sin mezclarse: "
                        "ningún archivo aparece en los dos, y los ajenos se "
                        "cuentan aparte en vez de salir como pendientes",
                     cada_agente_ve_solo_lo_suyo)

        def el_mismo_cx_id_en_dos_agentes_no_colisiona():
            """CX reutiliza identificadores entre agentes.

            Verificado con agentes reales: sus "Default Start Flow" y "Default
            Welcome Intent" comparten cx_id. Con la clave sin el agente, la
            defensa de duplicados saltaría el primer día y nada arrancaría.
            """
            ids = {}
            for quien in (agent_id, hermano):
                ctx = pipeline.Contexto(project, quien)
                inv, _, _ = pipeline.inventariar_cx(ctx)
                for tipo, items in inv.items():
                    for cx_id in items:
                        ids.setdefault((tipo, cx_id), set()).add(quien)
            compartidos = {k: v for k, v in ids.items() if len(v) > 1}
            if not compartidos:
                return False, ("los dos agentes no comparten ningún cx_id, así "
                               "que el caso no se llega a probar")
            # Y aun compartiéndolos, cargar el repositorio no protesta.
            pipeline.cargar_repositorio(pipeline.Contexto(project, agent_id))
            return True, (f"{len(compartidos)} identificadores compartidos entre "
                          f"los dos agentes, sin colisión")

        runner.check(1, "Dos agentes con el mismo cx_id no disparan la defensa "
                        "de duplicados: la clave lleva el agente",
                     el_mismo_cx_id_en_dos_agentes_no_colisiona)

        def un_resource_ajeno_no_entra_en_el_diff():
            datos = pipeline.step_3_apply_to_cx(project, agent_id, dry_run=True)["data"]
            ctx = pipeline.Contexto(project, hermano)
            repo_hermano, _ = pipeline.cargar_repositorio(ctx)
            suyas = {e["ruta"] for por_tipo in repo_hermano["por_tipo"].values()
                     for e in por_tipo.values()}
            intrusas = [o["ruta"] for o in datos["operaciones"] if o.get("ruta") in suyas]
            return not intrusas, f"el diff propone tocar archivos del hermano: {intrusas[:3]}"

        runner.check(1, "El diff de un agente no propone nada sobre los archivos "
                        "de su hermano",
                     un_resource_ajeno_no_entra_en_el_diff)
    else:
        runner.skip(1, "Dos agentes comparten repositorio sin mezclarse",
                    "hace falta --agente-hermano: un segundo agente desechable "
                    "del mismo proyecto")

    def un_archivo_sin_agente_se_cuenta_aparte():
        """Un archivo con cabecera pero sin `agente` no es de nadie.

        Filtrando por agente desaparecería de todas las vistas sin dejar
        rastro: no se puede aplicar en ninguno y nadie sabría por qué. El
        Paso 1 es el único momento que lee el repositorio entero antes de
        repartirlo, así que es el único sitio donde se puede contar.
        """
        original = contexto.gh.read_repo_files
        archivos = dict(original(contexto.gh.branch_head(contexto.rama)))
        huerfano = {"path": "definitions/intents/sin_dueno.yaml"}
        archivos[huerfano["path"]] = (
            b"metadata:\n  tipo: intent\n  padre: null\n"
            b"  cx_id: null\ndisplayName: sin_dueno\n")
        contexto.gh.read_repo_files = lambda *_a, **_k: archivos
        try:
            repositorio, _ = pipeline.cargar_repositorio(contexto)
            sin_agente = [e["ruta"] for e in repositorio["sin_agente"]]
            en_el_reparto = any(
                e["ruta"] == huerfano["path"]
                for por_tipo in repositorio["por_tipo"].values()
                for e in por_tipo.values()
            ) or any(e["ruta"] == huerfano["path"] for e in repositorio["sin_cx_id"])
            return (huerfano["path"] in sin_agente and not en_el_reparto), (
                f"sin_agente={sin_agente[:2]} · entró en el reparto={en_el_reparto}"
            )
        finally:
            contexto.gh.read_repo_files = original

    runner.check(1, "Un archivo con cabecera pero sin agente se cuenta aparte y "
                    "no entra en el reparto de ningún agente",
                 un_archivo_sin_agente_se_cuenta_aparte)

    runner.skip(1, "Dos pares proyecto+agente en el mismo proceso no se contaminan",
                "exige un segundo agente desechable; la propiedad que probaría "
                "—que la cabecera de cuota no se cachea— sí está cubierta en el "
                "Nivel 4 sin necesitarlo")


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

    # ── Defensas que solo se disparan cuando algo va mal ─────────────────────
    #
    # Ninguna se había ejecutado nunca. Una defensa que no se ha probado es una
    # suposición: el día que haga falta es el día que se descubre si funciona.

    def cx_id_duplicado_para():
        contexto = pipeline.Contexto(project, agent_id)
        original = contexto.gh.read_repo_files
        archivos = original(contexto.gh.branch_head(contexto.rama))
        # Tiene que ser un archivo que de verdad sea un resource de este
        # agente: copiar uno sin cabecera no dispara nada, y copiar uno de otro
        # agente tampoco tiene por que — su clave lleva otro agente.
        repositorio, _ = pipeline.cargar_repositorio(contexto)
        propias = [e["ruta"] for por_tipo in repositorio["por_tipo"].values()
                   for e in por_tipo.values()]
        origen = next((r for r in propias if r in archivos), None)
        if origen is None:
            return True, "(el agente no tiene ningun resource en el repositorio)"

        copia = dict(archivos)
        copia[origen.replace(".yaml", "_copia.yaml")] = archivos[origen]
        contexto.gh.read_repo_files = lambda *_a, **_k: copia
        try:
            pipeline.cargar_repositorio(contexto)
            return False, "acepto dos archivos con el mismo tipo y cx_id"
        except pipeline.PipelineError as error:
            return "cx_id" in str(error), str(error)[:90]
        finally:
            contexto.gh.read_repo_files = original

    runner.check(2, "Dos archivos con el mismo tipo y cx_id paran el pipeline — "
                    "duplicar un YAML y olvidar vaciar el id deja dos "
                    "reclamando el mismo resource",
                 cx_id_duplicado_para)

    def tipo_desconocido_da_error_explicito():
        contexto = pipeline.Contexto(project, agent_id)
        original = contexto.gh.read_repo_files
        contexto.gh.read_repo_files = lambda *_a, **_k: {
            "definitions/raro/x.yaml":
                b"metadata:\n  tipo: tipo_inventado\n  cx_id: abc\n"
                b"  agente: x\ndisplayName: x\n"}
        try:
            pipeline.cargar_repositorio(contexto)
            return False, "aceptó un tipo que no existe"
        except pipeline.PipelineError as error:
            return "tipo_inventado" in str(error), str(error)[:90]
        finally:
            contexto.gh.read_repo_files = original

    runner.check(2, "Un YAML con un tipo que no existe da error nombrándolo, "
                    "no se vuelve invisible",
                 tipo_desconocido_da_error_explicito)

    def yaml_mal_formado_dice_que_archivo():
        contexto = pipeline.Contexto(project, agent_id)
        original = contexto.gh.read_repo_files
        contexto.gh.read_repo_files = lambda *_a, **_k: {
            "definitions/roto.yaml": b"metadata:\n  tipo: [sin cerrar\n"}
        try:
            pipeline.cargar_repositorio(contexto)
            return False, "aceptó un YAML mal formado"
        except pipeline.PipelineError as error:
            return "definitions/roto.yaml" in str(error), str(error)[:90]
        finally:
            contexto.gh.read_repo_files = original

    runner.check(2, "Un YAML mal formado dice qué archivo lo provocó",
                 yaml_mal_formado_dice_que_archivo)

    def rama_inexistente_falla_claro():
        cliente = store.get_client()
        mapeo = store.get_agent_mapping(cliente, project, agent_id)
        store.save_agent_mapping(cliente, project, agent_id, mapeo["region"],
                                 "rama-que-no-existe",
                                 mapeo.get("carpeta_raiz", "definitions"))
        try:
            pipeline.step_1_inventory(project, agent_id)
            return False, "no falló con una rama inexistente"
        except Exception as error:
            return "404" in str(error) or "not found" in str(error).lower(), \
                str(error)[:90]
        finally:
            store.save_agent_mapping(cliente, project, agent_id, mapeo["region"],
                                     mapeo["rama"],
                                     mapeo.get("carpeta_raiz", "definitions"))

    runner.check(2, "Una rama que no existe en el mapeo falla, no devuelve un "
                    "repositorio vacío",
                 rama_inexistente_falla_claro)

    def etiqueta_de_version_validada():
        malas = ["", "con espacios", "con/barra", "acentué", None]
        for mala in malas:
            try:
                pipeline.step_5_publish(project, agent_id, mala)
                return False, f"aceptó el nombre de versión {mala!r}"
            except ValueError:
                continue
            except Exception as error:
                return False, f"{mala!r} falló por otra razón: {type(error).__name__}"
        return True, ""

    runner.check(2, "Un nombre de versión inválido se rechaza antes de tocar nada",
                 etiqueta_de_version_validada)

    def url_de_repositorio_validada():
        for mala in ["", "no-es-una-url", "https://github.com/solo-usuario",
                     "https://gitlab.com/a/b/c/d"]:
            try:
                pipeline._repo_desde_url(mala)
                return False, f"aceptó {mala!r} como repositorio"
            except ValueError:
                continue
        buena = pipeline._repo_desde_url("https://github.com/usuario/repo.git")
        return buena == "usuario/repo", buena

    runner.check(2, "Una URL de repositorio que no lo es se rechaza",
                 url_de_repositorio_validada)

    def resource_suelto_rechaza_lo_que_no_despliega():
        for tipo in ("environment", "version", "tipo_que_no_existe"):
            try:
                pipeline.deploy_single_resource(project, agent_id, tipo, "x")
                return False, f"aceptó desplegar un {tipo}"
            except ValueError:
                continue
        return True, ""

    runner.check(2, "Desplegar un resource suelto rechaza los tipos que no "
                    "despliega, incluidos los entornos",
                 resource_suelto_rechaza_lo_que_no_despliega)

    def resource_suelto_exige_que_el_repo_lo_declare():
        try:
            pipeline.deploy_single_resource(project, agent_id, "intent",
                                            "cx-id-que-nadie-declara")
            return False, "aceptó un cx_id que ningún archivo declara"
        except pipeline.PipelineError as error:
            return "repositorio" in str(error), str(error)[:90]

    runner.check(2, "Desplegar un resource suelto exige que algún archivo lo declare",
                 resource_suelto_exige_que_el_repo_lo_declare)

    def tests_solo_admite_dos_respuestas():
        for valor in ("ok", "", None, "SUPERADOS"):
            try:
                pipeline.step_4_validate_tests(project, agent_id, valor)
                return False, f"aceptó {valor!r} como resultado de los tests"
            except ValueError:
                continue
        return True, ""

    runner.check(2, "Declarar los tests solo admite 'superados' o 'fallidos'",
                 tests_solo_admite_dos_respuestas)



# ── Nivel 3 · Escritura real ─────────────────────────────────────────────────

def nivel_3(runner, project, agent_id, run_id):
    print("\nNIVEL 3 — Escritura real · contra el agente desechable")

    contexto = pipeline.Contexto(project, agent_id)
    etiqueta = f"{PREFIJO}_{run_id}"
    creados = []

    # Punto al que se devuelve la rama al terminar. Sin esto, un resource que
    # el nivel crea en CX y trae al repositorio sobrevive al borrado —
    # desaparece de CX pero su archivo se queda, y el inventario siguiente lo
    # reporta como cx_id fantasma para siempre. Encontrado ejecutando: el
    # Nivel 1 falló por el residuo que había dejado el Nivel 3.
    rama_al_empezar = contexto.gh.branch_head(contexto.rama)

    def _desanclar_lo_de_las_pruebas(inventario):
        """Quita del entorno de producción las versiones de resources de prueba.

        Es el primer eslabón de la cadena de residuo, y sin él los otros dos no
        se pueden romper: publicar crea una versión del flow o playbook de
        prueba, esa versión queda fijada en producción, y entonces CX se niega
        a borrar el resource — *"cannot be deleted because it is still
        referenced in the following environments"*. El resource se queda, su
        versión se queda, y a la corrida siguiente hay dos.

        Devuelve cuántas desancló.
        """
        entornos = list(inventario.get("environment", {}).values())
        desancladas = 0
        for entorno in entornos:
            fijadas = [c["version"] for c in entorno.get("versionConfigs", [])]
            sobreviven = []
            for version in fijadas:
                padre = version.rsplit("/versions/", 1)[0]
                respuesta = cx.api_get(project, contexto.region, padre)
                nombre = (respuesta.json().get("displayName", "")
                          if respuesta.status_code == 200 else "")
                if str(nombre).startswith(PREFIJO):
                    desancladas += 1
                else:
                    sobreviven.append(version)
            if len(sobreviven) != len(fijadas):
                pipeline._apuntar_entorno(contexto, entorno, sobreviven)
        return desancladas

    def barrer_restos_previos():
        """Barrido al empezar: un finally no sobrevive a un SIGKILL, así que el
        residuo de una corrida muerta se limpia en la siguiente."""
        inventario, _, _ = pipeline.inventariar_cx(contexto)
        desancladas = _desanclar_lo_de_las_pruebas(inventario)
        inventario, _, _ = pipeline.inventariar_cx(contexto)
        # Las versiones primero: mientras exista una version de un resource de
        # prueba, CX se niega a borrar el resource.
        restos = [item for item in inventario.get("version", {}).values()
                  if _lleva_la_marca("version", item)]
        restos += [
            item for tipo, items in inventario.items() if tipo != "version"
            for item in items.values() if _lleva_la_marca(tipo, item)
        ]
        for resto in restos:
            cx.api_delete(project, contexto.region, resto["name"])
        return True, (f"{desancladas} versiones desancladas de un entorno · "
                      f"{len(restos)} restos borrados")

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

    def los_trece_tipos_ciclo_completo():
        """Create, update y delete real de cada tipo desplegable.

        Los tipos poco comunes pueden tener comportamiento propio que no se
        descubre nunca si solo se prueban los cuatro conocidos.
        """
        inventario, _, _ = pipeline.inventariar_cx(contexto)
        fallos, probados = [], []
        for tipo, spec in pipeline.TIPOS_DESPLEGABLES.items():
            if spec.get("singular"):
                continue  # el agente no se crea ni se borra desde aquí
            padre = contexto.parent
            if spec.get("padre"):
                candidatos = list(inventario.get(spec["padre"], {}).values())
                if not candidatos:
                    fallos.append(f"{tipo}: sin padre donde colgarlo")
                    continue
                padre = candidatos[0]["name"]

            # Sufijo propio: sin él choca con el resource que este mismo nivel
            # crea al empezar, y la API responde 409 AlreadyExists.
            cuerpo = {"displayName": f"{etiqueta}_ciclo_{tipo}"}
            if tipo == "entity_type":
                cuerpo.update({"kind": "KIND_MAP",
                               "entities": [{"value": "a", "synonyms": ["a"]}]})
            elif tipo == "webhook":
                cuerpo.update({"genericWebService": {"uri": "https://example.invalid/x"},
                               "timeout": "5s"})
            elif tipo == "generator":
                cuerpo.update({"promptText": {"text": "resume"}})
            elif tipo == "playbook":
                cuerpo.update({"goal": "objetivo de prueba",
                               "playbookType": "ROUTINE",
                               "instruction": {"steps": [{"text": "haz algo"}]}})
            elif tipo == "example":
                cuerpo.update({"actions": [{"userUtterance": {"text": "hola"}},
                                           {"agentUtterance": {"text": "hola"}}],
                               "conversationState": "OUTPUT_STATE_OK"})
            elif tipo == "tool":
                cuerpo.update({"description": "herramienta de prueba",
                               "openApiSpec": {"textSchema":
                                   "openapi: 3.0.0\ninfo:\n  title: x\n  version: '1'\npaths: {}\n"}})

            creado = cx.api_post(project, contexto.region,
                                 f"{padre}/{spec['api']}", cuerpo)
            if creado.status_code not in (200, 201):
                fallos.append(f"{tipo} CREATE {creado.status_code}: "
                              f"{creado.text[:90]}")
                continue
            nombre = cx.resolve_operation(project, contexto.region, creado)["name"]

            actual = cx.api_get(project, contexto.region, nombre).json()
            actual["displayName"] = f"{etiqueta}_ciclo_{tipo}_mod"
            for campo in payloads.ignore_fields_for(tipo):
                actual.pop(campo, None)
            modificado = cx.api_patch(project, contexto.region, nombre, actual)
            if modificado.status_code not in (200, 201):
                fallos.append(f"{tipo} UPDATE {modificado.status_code}: "
                              f"{modificado.text[:90]}")

            cx.api_delete(project, contexto.region, nombre)
            if cx.api_get(project, contexto.region, nombre).status_code != 404:
                fallos.append(f"{tipo} DELETE no surtió efecto")
            probados.append(tipo)

        return not fallos, (f"probados {len(probados)} · " + " | ".join(fallos))

    runner.check(3, "Create, update y delete real de cada tipo desplegable, "
                    "confirmando el borrado leyendo el resultado",
                 los_trece_tipos_ciclo_completo)

    def el_ciclo_del_cx_id_se_cierra():
        """Un resource que nace en el repositorio recibe su id de CX y ese id
        vuelve al archivo.

        Es el ciclo completo de la cabecera: el archivo nace sin `cx_id`
        —no puede tenerlo, no existe en ningún sitio y el id lo asigna CX—, se
        sube, y el id que devuelve CX se escribe de vuelta en su `metadata`.

        Si el id no vuelve, la cabecera queda incompleta para siempre y cada
        deploy vuelve a tratar el archivo como inexistente en CX: un duplicado
        por pasada, contra la idempotencia de CLAUDE.md §3.4.
        """
        ruta = f"definitions/intents/{etiqueta}_ciclo.yaml"
        documento = {
            "metadata": {"tipo": "intent", "padre": None, "cx_id": None,
                         "agente": agent_id},
            "displayName": f"{etiqueta}_ciclo",
            "trainingPhrases": [{"parts": [{"text": "ciclo"}], "repeatCount": 1}],
        }
        contexto.gh.commit_files(
            contexto.rama,
            {ruta: __import__("yaml").safe_dump(documento, allow_unicode=True,
                                               sort_keys=False)},
            f"test: resource nuevo sin cx_id ({etiqueta})",
        )

        resultado = pipeline.step_3_apply_to_cx(project, agent_id)
        if resultado["status"] != "ok":
            return False, f"el Paso 3 falló: {resultado['status']}"

        archivos = contexto.gh.read_repo_files(contexto.gh.branch_head(contexto.rama))
        if ruta not in archivos:
            return False, "el archivo desapareció del repositorio"
        guardado = (__import__("yaml").safe_load(archivos[ruta])
                    .get("metadata", {}).get("cx_id"))
        if not guardado:
            return False, ("el cx_id no volvió al archivo: la cabecera sigue "
                           "incompleta y el próximo deploy lo creará otra vez")

        inventario, _, _ = pipeline.inventariar_cx(contexto, tipos=["intent"])
        real = next((pipeline._cx_id_de(i) for i in inventario["intent"].values()
                     if i.get("displayName") == f"{etiqueta}_ciclo"), None)
        if guardado != real:
            return False, f"el archivo guarda {guardado} y CX dice {real}"

        # La prueba de verdad: el deploy siguiente no propone nada sobre él.
        pendientes = [o for o in pipeline.step_3_apply_to_cx(
            project, agent_id, dry_run=True)["data"]["operaciones"]
            if o["ruta"] == ruta]
        if pendientes:
            # El mensaje se construye solo cuando hay algo que contar: armarlo
            # siempre indexaría una lista vacía en el camino bueno.
            return False, (f"el segundo deploy propone "
                           f"{pendientes[0]['operacion']} sobre el mismo "
                           f"archivo: el ciclo no se cerró")
        return True, ""

    runner.check(3, "El cx_id que asigna CX vuelve al archivo, y el deploy "
                    "siguiente no vuelve a crear el resource",
                 el_ciclo_del_cx_id_se_cierra)

    def el_ciclo_se_cierra_en_todos_los_tipos():
        """El ciclo completo de la cabecera, barriendo todos los tipos.

        Se escribe un YAML nuevo de cada tipo desplegable —con `tipo`, con
        `padre` si cuelga de otro, y sin `cx_id`— en un solo commit. Se aplica
        una vez. Y se comprueba, tipo por tipo, que CX lo creó donde tocaba,
        que el id volvió al archivo, y que el deploy siguiente no propone nada
        sobre ninguno.

        Un tipo puede tener su propio comportamiento y no se descubre nunca si
        solo se prueba con el fácil, que es el que cuelga del agente.
        """
        inventario, _, _ = pipeline.inventariar_cx(contexto)
        archivos, esperados = {}, {}

        for tipo, spec in pipeline.TIPOS_DESPLEGABLES.items():
            if spec.get("singular") or tipo not in CUERPO_MINIMO:
                continue
            padre_id = None
            if spec.get("padre"):
                padres = list(inventario.get(spec["padre"], {}))
                if not padres:
                    continue  # sin padre donde colgarlo, no aplica
                padre_id = padres[0]
            nombre = f"{etiqueta}_ciclo_{tipo}"
            ruta = f"definitions/{tipo}s/{nombre}.yaml"
            archivos[ruta] = __import__("yaml").safe_dump(
                {"metadata": {"tipo": tipo, "padre": padre_id, "cx_id": None,
                              "agente": agent_id},
                 "displayName": nombre, **CUERPO_MINIMO[tipo]},
                allow_unicode=True, sort_keys=False)
            esperados[tipo] = {"ruta": ruta, "nombre": nombre, "padre": padre_id}

        if not archivos:
            return False, "no se pudo fabricar ningún resource de prueba"

        contexto.gh.commit_files(
            contexto.rama, archivos,
            f"test: un resource nuevo de cada tipo, sin cx_id ({etiqueta})")

        resultado = pipeline.step_3_apply_to_cx(project, agent_id)
        if resultado["status"] != "ok":
            fallidas = [f"{o['tipo']}: {o.get('error', '')[:60]}"
                        for o in resultado["data"]["operaciones"]
                        if o.get("result") == "ERROR"]
            return False, f"el Paso 3 falló · {' | '.join(fallidas)}"

        arbol = contexto.gh.read_repo_files(contexto.gh.branch_head(contexto.rama))
        inventario, _, _ = pipeline.inventariar_cx(contexto)
        fallos = []
        for tipo, esperado in esperados.items():
            creado = next((i for i in inventario.get(tipo, {}).values()
                           if i.get("displayName") == esperado["nombre"]), None)
            if creado is None:
                fallos.append(f"{tipo}: no se creó en CX")
                continue
            crudo = arbol.get(esperado["ruta"])
            if crudo is None:
                fallos.append(f"{tipo}: su archivo desapareció del repositorio")
                continue
            meta = (__import__("yaml").safe_load(crudo).get("metadata") or {})
            if meta.get("cx_id") != pipeline._cx_id_de(creado):
                fallos.append(f"{tipo}: el archivo guarda {meta.get('cx_id')!r} "
                              f"y CX dice {pipeline._cx_id_de(creado)!r}")
            if esperado["padre"] and esperado["padre"] not in creado.get("name", ""):
                fallos.append(f"{tipo}: colgó de otro padre")

        pendientes = [o["tipo"] for o in pipeline.step_3_apply_to_cx(
            project, agent_id, dry_run=True)["data"]["operaciones"]
            if o.get("ruta") in {e["ruta"] for e in esperados.values()}]
        if pendientes:
            fallos.append(f"el 2º deploy vuelve a proponer: {sorted(set(pendientes))}")

        return not fallos, f"probados {len(esperados)} tipos · " + " | ".join(fallos)

    runner.check(3, "El ciclo de la cabecera se cierra en todos los tipos: nacen "
                    "sin cx_id, CX se lo da, vuelve al archivo, y el deploy "
                    "siguiente no propone nada",
                 el_ciclo_se_cierra_en_todos_los_tipos)

    def la_cabecera_nunca_viaja_a_cx():
        """El bloque `metadata` es del repositorio, no del agente.

        Se comprueba sobre el cuerpo que sale de verdad y sobre el resource
        leído de vuelta desde CX — no inspeccionando el código, que pasaría
        aunque la línea que lo quita fuera inalcanzable.
        """
        enviados = []
        original = cx.api_request

        def espia(method, project_, region, path, body=None, **kw):
            if method in ("POST", "PATCH") and isinstance(body, dict):
                enviados.append((path, body))
            return original(method, project_, region, path, body=body, **kw)

        cx.api_request = espia
        try:
            pipeline.step_3_apply_to_cx(project, agent_id)
        finally:
            cx.api_request = original

        con_cabecera = [p for p, b in enviados if "metadata" in b]
        if con_cabecera:
            return False, f"la cabecera viajó a la API en: {con_cabecera[:2]}"

        inventario, _, _ = pipeline.inventariar_cx(contexto)
        en_borrador = [
            item.get("displayName") for items in inventario.values()
            for item in items.values() if "metadata" in item
        ]
        return not en_borrador, (
            f"hay resources con metadata en el borrador: {en_borrador[:3]}"
        )

    runner.check(3, "La cabecera metadata no viaja a CX ni aparece en el "
                    "borrador — comprobado sobre el cuerpo enviado y sobre el "
                    "resource leído de vuelta",
                 la_cabecera_nunca_viaja_a_cx)

    def full_update_no_borra_los_handlers_del_flow():
        """El bug ya documentado: un PATCH parcial intenta borrar los
        eventHandlers que ningún YAML declara, y la API responde 400."""
        inventario, _, _ = pipeline.inventariar_cx(contexto, tipos=["flow"])
        flows = list(inventario.get("flow", {}).values())
        if not flows:
            return True, "(el agente no tiene flows)"
        flow = flows[0]
        antes = len(cx.api_get(project, contexto.region, flow["name"])
                    .json().get("eventHandlers", []))
        if antes == 0:
            return True, "(el flow no tiene eventHandlers que preservar)"

        operacion = pipeline._operacion(
            "PATCH", "flow", pipeline._cx_id_de(flow),
            {"ruta": "sintetico", "display_name": flow["displayName"]},
            {"description": f"tocado por {etiqueta}"},
            remote_name=flow["name"],
        )
        pipeline._patch_full_update(contexto, operacion)
        despues = len(cx.api_get(project, contexto.region, flow["name"])
                      .json().get("eventHandlers", []))
        return antes == despues, (
            f"el Full Update pasó de {antes} a {despues} eventHandlers"
        )

    runner.check(3, "Full Update en un flow con eventHandlers implícitos no los "
                    "borra — es la reproducción del bug ya documentado",
                 full_update_no_borra_los_handlers_del_flow)

    def full_update_en_playbook_aplica_de_verdad():
        """El bug de §3.8: en europe-west1 el PATCH con updateMask devuelve 200
        y no aplica nada. Lo que se comprueba es que el Full Update sí aplica —
        leyendo el resultado, no el código de respuesta."""
        inventario, _, _ = pipeline.inventariar_cx(contexto, tipos=["playbook"])
        playbooks = list(inventario.get("playbook", {}).values())
        if not playbooks:
            return True, "(el agente no tiene playbooks)"
        playbook = playbooks[0]
        nuevo = f"objetivo cambiado por {etiqueta}"
        operacion = pipeline._operacion(
            "PATCH", "playbook", pipeline._cx_id_de(playbook),
            {"ruta": "sintetico", "display_name": playbook["displayName"]},
            {"goal": nuevo}, remote_name=playbook["name"],
        )
        pipeline._patch_full_update(contexto, operacion)
        leido = cx.api_get(project, contexto.region, playbook["name"]).json()
        return leido.get("goal") == nuevo, (
            f"el cambio no llegó: goal = {leido.get('goal')!r}"
        )

    runner.check(3, "Full Update en un playbook aplica de verdad, confirmado "
                    "leyendo el objeto y no el código de respuesta",
                 full_update_en_playbook_aplica_de_verdad)

    def desplegar_un_resource_suelto():
        repositorio, _ = pipeline.cargar_repositorio(contexto)
        candidato = None
        for tipo in ("intent", "entity_type", "generator", "webhook"):
            for cx_id in repositorio["por_tipo"].get(tipo, {}):
                candidato = (tipo, cx_id)
                break
            if candidato:
                break
        if not candidato:
            return True, "(el repositorio no tiene un resource desplegable suelto)"
        tipo, cx_id = candidato
        # Ya coincide, así que tiene que reportar que no hay nada que aplicar.
        resultado = pipeline.deploy_single_resource(project, agent_id, tipo, cx_id)
        return resultado["data"]["aplicado"] is False, (
            "aplicó algo cuando repo y CX ya coincidían"
        )

    runner.check(3, "Desplegar un resource suelto no escribe si repo y CX ya "
                    "coinciden",
                 desplegar_un_resource_suelto)

    def declarar_tests_da_una_huella_que_cambia():
        """Si la huella no cambiara al cambiar el borrador, el aviso de 'draft
        movido' del Paso 5 no avisaría de nada."""
        antes = pipeline.step_4_validate_tests(
            project, agent_id, "superados")["data"]["huella_borrador"]
        creado = cx.api_post(project, contexto.region, f"{contexto.parent}/intents",
                             {"displayName": f"{etiqueta}_huella"})
        if creado.status_code not in (200, 201):
            return False, f"no se pudo mover el borrador: {creado.status_code}"
        nombre = creado.json()["name"]
        try:
            despues = pipeline.step_4_validate_tests(
                project, agent_id, "superados")["data"]["huella_borrador"]
            return antes != despues, "la huella no cambió al mover el borrador"
        finally:
            cx.api_delete(project, contexto.region, nombre)

    runner.check(3, "La huella del borrador cambia cuando el borrador cambia — "
                    "sin eso, el aviso de 'draft movido' no avisa de nada",
                 declarar_tests_da_una_huella_que_cambia)

    def borrar_versiones_respeta_las_que_sirve_un_entorno():
        listado = pipeline.manage_versions(project, agent_id, "list")["data"]
        en_uso = [v["name"] for v in listado["versiones"] if v["en_uso"]]
        if not en_uso:
            return True, "(ninguna versión está en uso)"
        resultado = pipeline.manage_versions(project, agent_id, "delete",
                                             version_names=en_uso)["data"]
        sigue = pipeline.manage_versions(project, agent_id, "list")["data"]
        nombres = {v["name"] for v in sigue["versiones"]}
        return (not resultado["borradas"] and set(en_uso) <= nombres), (
            f"borró {resultado['borradas']} de las que sirve un entorno"
        )

    runner.check(3, "Borrar versiones se niega con las que un entorno está "
                    "sirviendo, y las deja intactas",
                 borrar_versiones_respeta_las_que_sirve_un_entorno)

    def borrar_una_version_libre_funciona():
        inventario, _, _ = pipeline.inventariar_cx(contexto, tipos=["flow"])
        flows = list(inventario.get("flow", {}).values())
        if not flows:
            return True, "(sin flows)"
        creada = cx.api_post(project, contexto.region, f"{flows[0]['name']}/versions",
                             {"displayName": f"{etiqueta}_v"})
        if creada.status_code not in (200, 201):
            return False, f"no se pudo crear la versión: {creada.status_code}"
        nombre = cx.resolve_operation(project, contexto.region, creada)["name"]
        resultado = pipeline.manage_versions(project, agent_id, "delete",
                                             version_names=[nombre])["data"]
        desaparecio = cx.api_get(project, contexto.region, nombre).status_code == 404
        return nombre in resultado["borradas"] and desaparecio, (
            "la versión no se borró de verdad"
        )

    runner.check(3, "Borrar una versión libre funciona, y el borrado se confirma "
                    "leyendo",
                 borrar_una_version_libre_funciona)

    def publicar_hace_tres_cosas_en_orden():
        """Fusionar, crear la versión y apuntar producción — en ese orden.

        Si se promoviera antes de fusionar y el merge fallara, producción
        estaría sirviendo algo cuyo código no está en la rama principal.
        """
        inventario, _, _ = pipeline.inventariar_cx(contexto, tipos=["environment"])
        produccion = [e for e in inventario.get("environment", {}).values()
                      if e.get("displayName") == "production"]
        if not produccion:
            return False, "el agente desechable no tiene entorno production"
        antes = [c["version"] for c in produccion[0].get("versionConfigs", [])]

        resultado = pipeline.step_5_publish(project, agent_id, f"{etiqueta}_pub")
        if resultado["status"] != "ok":
            return False, f"{resultado['status']}: {resultado['log'][-1:]}"

        registro = " | ".join(resultado["log"])
        orden_correcto = (registro.index("1/3") < registro.index("2/3")
                          < registro.index("3/3"))
        inventario, _, _ = pipeline.inventariar_cx(contexto, tipos=["environment"])
        despues = [c["version"] for c in
                   [e for e in inventario["environment"].values()
                    if e.get("displayName") == "production"][0]
                   .get("versionConfigs", [])]
        return orden_correcto and resultado["data"]["publicado"], (
            f"orden={orden_correcto} antes={len(antes)} después={len(despues)}"
        )

    runner.check(3, "Publicar hace tres cosas y en orden: fusionar, versionar y "
                    "apuntar producción",
                 publicar_hace_tres_cosas_en_orden)

    def publicar_solo_versiona_lo_tocado():
        """H4: el tiempo del paso tiene que ser proporcional al cambio, no al
        tamaño del agente — y cada deploy no puede quemar un hueco de versión
        en todos los playbooks contra un límite de 20."""
        cliente = store.get_client()
        pendientes = store.list_pending_publication(cliente, project, agent_id)
        resultado = pipeline.step_5_publish(project, agent_id, f"{etiqueta}_h4")
        if resultado["status"] != "ok":
            return False, resultado["status"]
        creadas = resultado["data"]["versiones_creadas"]
        inventario, _, _ = pipeline.inventariar_cx(
            contexto, tipos=["playbook", "flow"])
        versionables = len(inventario.get("playbook", {})) + len(inventario.get("flow", {}))
        return len(creadas) <= max(1, len(pendientes)) and len(creadas) < versionables + 1, (
            f"{len(creadas)} versiones creadas con {len(pendientes)} resources "
            f"tocados y {versionables} versionables en total"
        )

    runner.check(3, "Publicar versiona solo lo que el diff tocó, no el agente "
                    "entero (H4)",
                 publicar_solo_versiona_lo_tocado)

    def publicar_dos_veces_es_no_op():
        """Un reintento accidental del Paso 5 sobre un commit ya publicado no
        debe fusionar dos veces ni crear una versión duplicada."""
        primera = pipeline.step_5_publish(project, agent_id, f"{etiqueta}_dos_a")
        segunda = pipeline.step_5_publish(project, agent_id, f"{etiqueta}_dos_b")
        if primera["status"] != "ok" or segunda["status"] != "ok":
            return False, f"{primera['status']} / {segunda['status']}"
        return len(segunda["data"]["versiones_creadas"]) == 0, (
            f"la segunda publicación creó {len(segunda['data']['versiones_creadas'])} "
            f"versiones sin nada que publicar"
        )

    runner.check(3, "Publicar dos veces seguidas sin cambios no crea una segunda "
                    "versión",
                 publicar_dos_veces_es_no_op)

    def el_rollback_queda_registrado():
        cliente = store.get_client()
        previas = store.get_previous_versions(cliente, project, agent_id)
        return previas is not None and "version_names" in previas, (
            "no quedó registrado a qué apuntaba producción antes"
        )

    runner.check(3, "Publicar registra a qué versiones apuntaba producción antes "
                    "— es lo único que hace posible el rollback",
                 el_rollback_queda_registrado)

    runner.skip(3, "Repetir los checks de Full Update en una región distinta de "
                   "europe-west1",
                "exige un segundo agente desechable en otra región. El bug de "
                "CLAUDE.md §3.8 solo está verificado en europe-west1 y sigue sin "
                "verificar fuera: con la región autodetectada, el pipeline puede "
                "acabar operando en otra sin que nadie lo haya comprobado")

    # ── Limpieza · va al final, y pase lo que pase antes ─────────────────────

    def limpiar_cx():
        """Borra todo lo que lleva el prefijo, y confirma leyendo.

        Una excepción declarada: la versión que el entorno de producción está
        sirviendo no se puede borrar mientras la sirva — la API se niega, y con
        razón. Deja de estar en uso en cuanto la corrida siguiente publique
        otra, y entonces la barre el barrido inicial. Se cuenta aquí en vez de
        callarla, porque un residuo silencioso se lee luego como limpieza que
        sí ocurrió.
        """
        inventario, _, _ = pipeline.inventariar_cx(contexto)
        desancladas = _desanclar_lo_de_las_pruebas(inventario)
        inventario, _, _ = pipeline.inventariar_cx(contexto)
        en_uso = {
            config["version"]
            for entorno in inventario.get("environment", {}).values()
            for config in entorno.get("versionConfigs", [])
        }
        # Las versiones de playbook llevan la marca en `description` y no en
        # `displayName`, porque el endpoint de versiones de playbook no acepta
        # displayName. Buscar solo por displayName las dejaba fuera del barrido
        # para siempre, y se acumulaban contra el limite de 20 por playbook.
        objetivos = set(creados) | {
            item["name"]
            for tipo, items in inventario.items() for item in items.values()
            if _lleva_la_marca(tipo, item)
        }

        pendientes, servidos = [], []
        for nombre in objetivos:
            if nombre in en_uso:
                servidos.append(nombre.rsplit("/", 1)[-1])
                continue
            cx.api_delete(project, contexto.region, nombre)
            # El borrado se confirma leyendo, no por el código de respuesta.
            if cx.api_get(project, contexto.region, nombre).status_code != 404:
                pendientes.append(nombre)

        detalle = f"no se borraron: {pendientes}" if pendientes else (
            f"{desancladas} desancladas · {len(servidos)} siguen en uso"
            if (desancladas or servidos) else ""
        )
        return not pendientes, detalle

    runner.check(3, "Cero residuo en CX: lo creado se borra y el borrado se "
                    "confirma leyendo el resultado",
                 limpiar_cx)

    def limpiar_repositorio():
        """Devuelve la rama al commit en el que estaba antes del nivel.

        Es un force update, y por eso solo se hace contra el repositorio
        desechable. Revertir archivo por archivo dejaría fuera cualquiera que
        el nivel creara sin que este código lo supiera — que es justo lo que
        pasó: el nivel traía al repositorio un resource que luego borraba de
        CX, y el archivo se quedaba reclamando un cx_id que ya no existe.
        """
        actual = contexto.gh.branch_head(contexto.rama)
        if actual == rama_al_empezar:
            return True, "la rama no se movió"
        respuesta = requests.patch(
            f"https://api.github.com/repos/{contexto.repo}/git/refs/heads/"
            f"{contexto.rama}",
            headers=contexto.gh._headers(),
            json={"sha": rama_al_empezar, "force": True}, timeout=30,
        )
        if respuesta.status_code != 200:
            return False, f"{respuesta.status_code} {respuesta.text[:120]}"
        vuelto = contexto.gh.branch_head(contexto.rama)
        return vuelto == rama_al_empezar, (
            f"la rama quedó en {vuelto[:7]}, no en {rama_al_empezar[:7]}"
        )

    runner.check(3, "Cero residuo en el repositorio: la rama vuelve al commit en "
                    "el que estaba antes del nivel",
                 limpiar_repositorio)


# ── Nivel 4 · Caos ───────────────────────────────────────────────────────────

def nivel_4(runner, project, agent_id, run_id, hermano=None):
    print("\nNIVEL 4 — Fallo inyectado y concurrencia")

    cliente = store.get_client()
    # El check de conflicto escribe en el repositorio para provocar el caso.
    rama_al_empezar = pipeline.Contexto(project, agent_id).gh.branch_head(
        store.get_agent_mapping(cliente, project, agent_id)["rama"])

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

    if hermano:
        def el_candado_cubre_a_los_agentes_hermanos():
            """El candado es del proyecto, no del agente.

            Lo que protege no es solo el agente: es también el repositorio, y
            ese lo comparten todos los agentes de un proyecto. Con un candado
            por agente, dos deploys hermanos escribirían en la misma rama de
            git sin verse.
            """
            primero = store.acquire_lock(cliente, project, agent_id, "deploy A")
            try:
                store.acquire_lock(cliente, project, hermano, "deploy B")
                return False, ("el hermano tomó el candado mientras el otro "
                               "escribía: los dos irían a la misma rama")
            except store.LockBusy:
                return True, ""
            finally:
                store.release_lock(cliente, project, agent_id, primero)

        runner.check(4, "Un deploy sobre un agente bloquea a sus hermanos del "
                        "mismo proyecto: comparten repositorio",
                     el_candado_cubre_a_los_agentes_hermanos)

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
        """Se anota un progreso y se lee con un cliente nuevo, como haría un
        contenedor recién arrancado.

        Comprobar que una función devuelve una lista no prueba nada: devolvería
        una lista vacía igual si el progreso se estuviera guardando en memoria
        del proceso, que es justo el fallo que este check existe para detectar.
        """
        marca = f"{PREFIJO}_{run_id}_progreso"
        store.record_resource_write(
            cliente, project, agent_id, "intent", marca,
            "sintetico/progreso.yaml", display_name=marca, operacion="PATCH",
        )
        try:
            otro_cliente = store.get_client()   # como un contenedor nuevo
            leidos = store.list_pending_publication(otro_cliente, project, agent_id)
            encontrado = any(r.get("cx_id") == marca for r in leidos)
            registro = store.get_resource_record(otro_cliente, project, agent_id,
                                                 "intent", marca)
            return (encontrado and registro is not None
                    and registro.get("archivo") == "sintetico/progreso.yaml"), (
                "el progreso anotado no se ve desde un cliente nuevo: no está "
                "sobreviviendo fuera del proceso"
            )
        finally:
            store.mark_published(cliente, project, agent_id,
                                 [{"tipo": "intent", "cx_id": marca}])

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
        """Reintentar tras un fallo parcial reenvía lo fallido y lo no
        intentado, nunca lo que ya salió bien: repetirlo lo escribiría dos
        veces.

        Se fabrican tres resources nuevos, se reintenta declarando solo uno
        como pendiente, y se cuentan las escrituras HTTP reales. Confirmarlo
        por el resultado final no valdría: como las operaciones son
        idempotentes, reenviar las tres daría el mismo estado y ocultaría el
        fallo de seguimiento.
        """
        contexto = pipeline.Contexto(project, agent_id)
        rama0 = contexto.gh.branch_head(contexto.rama)
        rutas = {}
        for sufijo in ("uno", "dos", "tres"):
            nombre = f"{PREFIJO}_{run_id}_reint_{sufijo}"
            rutas[sufijo] = f"definitions/intents/{nombre}.yaml"
        contexto.gh.commit_files(contexto.rama, {
            ruta: __import__("yaml").safe_dump(
                {"metadata": {"tipo": "intent", "padre": None, "cx_id": None,
                              "agente": agent_id},
                 "displayName": pathlib_stem(ruta),
                 "trainingPhrases": [{"parts": [{"text": "hola"}],
                                      "repeatCount": 1}]},
                allow_unicode=True, sort_keys=False)
            for ruta in rutas.values()
        }, f"test: tres resources para el reintento ({run_id})")

        try:
            elegido = rutas["dos"]
            with ContadorHttp() as contador:
                pipeline.step_3_apply_to_cx(
                    project, agent_id,
                    aplicar=[{"tipo": "intent", "ruta": elegido}],
                    only_pending=[{"tipo": "intent", "ruta": elegido}],
                )
            creaciones = [c for c in contador.escrituras()
                          if c[0] == "POST" and c[1].endswith("/intents")]
            return len(creaciones) == 1, (
                f"{len(creaciones)} altas de intent en el reintento; se declaró "
                f"pendiente solo una. Reenviar las tres significa que el "
                f"seguimiento de lo ya aplicado no funciona"
            )
        finally:
            inventario, _, _ = pipeline.inventariar_cx(contexto, tipos=["intent"])
            for item in inventario.get("intent", {}).values():
                if str(item.get("displayName", "")).startswith(f"{PREFIJO}_{run_id}_reint"):
                    cx.api_delete(project, contexto.region, item["name"])
            requests.patch(
                f"https://api.github.com/repos/{contexto.repo}/git/refs/heads/"
                f"{contexto.rama}", headers=contexto.gh._headers(),
                json={"sha": rama0, "force": True}, timeout=30)

    runner.check(4, "El reintento solo reenvía lo pendiente", reintento_solo_lo_pendiente)

    runner.skip(4, "SIGKILL a mitad de una escritura real del Paso 3",
                "exige lanzar el pipeline como subproceso y matarlo en el momento "
                "exacto de una escritura. La garantía que probaría —el candado se "
                "libera por caducidad— sí está cubierta arriba, sin depender del "
                "momento del disparo")

    def limpiar_repositorio_del_nivel_4():
        """El check de conflicto escribió en el repositorio para provocar el caso."""
        contexto = pipeline.Contexto(project, agent_id)
        actual = contexto.gh.branch_head(contexto.rama)
        if actual == rama_al_empezar:
            return True, "la rama no se movió"
        respuesta = requests.patch(
            f"https://api.github.com/repos/{contexto.repo}/git/refs/heads/"
            f"{contexto.rama}",
            headers=contexto.gh._headers(),
            json={"sha": rama_al_empezar, "force": True}, timeout=30,
        )
        if respuesta.status_code != 200:
            return False, f"{respuesta.status_code} {respuesta.text[:120]}"
        return contexto.gh.branch_head(contexto.rama) == rama_al_empezar, ""

    runner.check(4, "Cero residuo: la rama vuelve al commit en el que estaba "
                    "antes del nivel",
                 limpiar_repositorio_del_nivel_4)

    def fallo_entre_crear_version_y_apuntar_entorno():
        """Se corta el Paso 5 justo después de crear la versión.

        Lo que se comprueba es si el reintento apunta el entorno a la versión
        que ya existe, o si crea otra — que dejaría la primera huérfana y el
        estado de CX ambiguo.
        """
        cliente = store.get_client()
        contexto = pipeline.Contexto(project, agent_id)

        # Sin algo pendiente de publicar no se crea ninguna versión, y el
        # escenario —una versión huérfana tras el corte— no llega a existir:
        # el check pasaría sin haber probado nada. Se siembra la marca sobre un
        # playbook real para que el Paso 5 tenga de verdad qué versionar.
        inventario, _, _ = pipeline.inventariar_cx(contexto, tipos=["playbook"])
        playbooks = list(inventario.get("playbook", {}).values())
        if not playbooks:
            return False, "sin playbooks no se puede provocar el escenario"
        store.record_resource_write(
            cliente, project, agent_id, "playbook",
            pipeline._cx_id_de(playbooks[0]), "sintetico/corte.yaml",
            display_name=playbooks[0].get("displayName"), operacion="PATCH",
        )
        pendientes_antes = store.list_pending_publication(cliente, project, agent_id)
        if not pendientes_antes:
            return False, "no se pudo dejar nada pendiente de publicar"

        original = pipeline._apuntar_entorno
        pipeline._apuntar_entorno = lambda *_a, **_k: (_ for _ in ()).throw(
            pipeline.PipelineError("corte inyectado antes de apuntar el entorno")
        )
        try:
            pipeline.step_5_publish(project, agent_id, "corte_inyectado")
            interrumpido = False
        except pipeline.PipelineError:
            interrumpido = True
        finally:
            pipeline._apuntar_entorno = original

        if not interrumpido:
            return False, "el corte no llegó a interrumpir el paso"

        # Lo que el corte dejó creado y sin fijar. Es contra esto contra lo que
        # se compara: el reintento tiene que usar exactamente estas, no otras.
        en_vuelo = store.get_inflight_versions(cliente, project, agent_id)
        if not en_vuelo or not en_vuelo.get("version_names"):
            return False, ("el corte no dejó anotada ninguna versión creada, "
                           "así que nada puede reutilizarla después")
        huerfanas = set(en_vuelo["version_names"])

        reintento = pipeline.step_5_publish(project, agent_id, "reintento_tras_corte")
        if reintento["status"] != "ok":
            return False, f"el reintento falló: {reintento['status']}"
        usadas = set(reintento["data"]["versiones_creadas"])
        return usadas == huerfanas, (
            f"con {len(pendientes_antes)} resources pendientes, el corte dejó "
            f"{len(huerfanas)} versiones creadas y el reintento usó "
            f"{len(usadas)}, de las que {len(usadas - huerfanas)} son nuevas. "
            f"Las que no se reutilizan quedan huérfanas."
        )

    runner.check(4, "Tras un corte entre crear la versión y apuntar el entorno, "
                    "el reintento reutiliza la versión ya creada",
                 fallo_entre_crear_version_y_apuntar_entorno)

    def el_gate_del_paso_4_aborta_si_el_borrador_se_movio():
        """La huella se toma al declarar los tests y se compara al publicar.

        Aborta, no avisa: publicar subiría a usuarios reales algo que nadie
        validó. Y aborta antes del merge, así que no deja nada a medias.
        """
        contexto = pipeline.Contexto(project, agent_id)

        def foto():
            inventario, _, _ = pipeline.inventariar_cx(contexto)
            produccion = next(
                e for e in inventario["environment"].values()
                if e.get("displayName") == "production"
            )
            return {
                "produccion": [c["version"] for c in
                               produccion.get("versionConfigs", [])],
                "borrador": pipeline._huella_borrador(inventario),
                "rama": contexto.gh.branch_head(contexto.rama),
                "principal": contexto.gh.branch_head(contexto.rama_principal),
            }

        antes = foto()
        resultado = pipeline.step_5_publish(
            project, agent_id, "huella_vieja",
            huella_al_validar="huella_que_no_corresponde",
        )
        despues = foto()

        # Abortar no es revertir: lo que el Paso 3 aplicó sigue en el borrador,
        # y ni el repositorio ni producción se mueven. Simplemente no avanza.
        cambiado = [k for k in antes if antes[k] != despues[k]]
        return (resultado["status"] == "aborted"
                and not resultado["data"]["fusionado"]
                and not resultado["data"]["publicado"]
                and not cambiado), (
            f"status={resultado['status']} · cambió: {cambiado or 'nada'}"
        )

    runner.check(4, "Abortar por borrador movido no revierte nada: el borrador "
                    "conserva lo aplicado, y producción, la rama de trabajo y la "
                    "principal quedan intactas. Simplemente no avanza",
                 el_gate_del_paso_4_aborta_si_el_borrador_se_movio)

    def se_detecta_el_conflicto_de_los_dos_lados():
        """El repositorio cambió y CX también, por separado.

        Con dos estados no se puede distinguir de un cambio normal: hace falta
        saber cómo quedó CX la última vez que escribió el pipeline. Se provoca
        el caso tocando un resource directamente en CX, como haría alguien
        editando en la consola.
        """
        contexto = pipeline.Contexto(project, agent_id)
        inventario, _, _ = pipeline.inventariar_cx(contexto)
        repositorio, _ = pipeline.cargar_repositorio(contexto)

        # Un resource emparejado y ya escrito por el pipeline alguna vez.
        auditados = store.list_resource_records(cliente, project, agent_id)
        candidato = next(
            ((t, c) for (t, c), reg in auditados.items()
             if reg.get("huella_cx") and c in inventario.get(t, {})
             and c in repositorio["por_tipo"].get(t, {})),
            None,
        )
        if candidato is None:
            return False, ("ningún resource tiene huella guardada de la última "
                           "escritura: sin ese tercer punto el conflicto no se "
                           "puede detectar para ninguno")
        tipo, cx_id = candidato
        remoto = inventario[tipo][cx_id]

        # Se toca CX por fuera del pipeline, como en la consola.
        cuerpo = {k: v for k, v in remoto.items()
                  if k not in pipeline.CAMPOS_LEIDOS_NO_ENVIADOS}
        cuerpo["description"] = f"tocado por fuera {run_id}"
        externo = cx.api_patch(project, contexto.region, remoto["name"], cuerpo)
        if externo.status_code not in (200, 201):
            return False, f"no se pudo tocar CX por fuera: {externo.status_code}"

        # Y se cambia también el repositorio, para que el diff proponga algo.
        entrada = repositorio["por_tipo"][tipo][cx_id]
        documento = dict(entrada["documento"])
        documento["description"] = f"tocado en el repo {run_id}"
        contexto.gh.commit_files(
            contexto.rama,
            {entrada["ruta"]: __import__("yaml").safe_dump(
                documento, allow_unicode=True, sort_keys=False)},
            f"test: provocar un conflicto en {tipo}/{cx_id}",
        )

        datos = pipeline.step_3_apply_to_cx(project, agent_id, dry_run=True)["data"]
        conflictos = datos.get("conflictos", [])
        return any(c["cx_id"] == cx_id for c in conflictos), (
            f"{len(conflictos)} conflictos detectados, ninguno de {tipo}/{cx_id}"
        )

    runner.check(4, "Un resource cambiado a la vez en el repositorio y en CX se "
                    "señala como conflicto, no se resuelve en silencio a favor "
                    "del repositorio",
                 se_detecta_el_conflicto_de_los_dos_lados)


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
    parser.add_argument("--agente-hermano", dest="hermano",
                        help="Segundo agente desechable del mismo proyecto, "
                             "para probar que comparten repositorio sin mezclarse")
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
        if 3 in niveles:
            # El Nivel 3 publica de verdad, y publicar fusiona en la principal.
            exigir_rama_principal_desechable(args.project)
        print(f"Destino: {nombre} · {args.project} · {region} · corrida {run_id}")

    if 0 in niveles:
        nivel_0(runner)
    if 1 in niveles:
        nivel_1(runner, args.project, args.agent, region, run_id, args.hermano)
    if 2 in niveles:
        nivel_2(runner, args.project, args.agent)
    if 3 in niveles:
        nivel_3(runner, args.project, args.agent, run_id)
    if 4 in niveles:
        nivel_4(runner, args.project, args.agent, run_id, args.hermano)

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
