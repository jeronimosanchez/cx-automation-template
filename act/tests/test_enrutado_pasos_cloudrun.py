"""
act/tests/test_enrutado_pasos_cloudrun.py — Que cada cambio se ofrezca en su paso.

Los tests de `test_movimiento_cloudrun.py` prueban que se decide bien de qué
lado vino el cambio. Estos prueban lo que se hace con esa decisión, y lo prueban
**llamando a los pasos y mirando el efecto**, no leyendo el código: una
comprobación que busca un texto en la fuente aprueba cualquier cosa que se le
parezca, y eso ya nos dejó tres pruebas decorativas en este repositorio.

Nada toca la red: CX, GitHub y Firestore son dobles, y lo que se mira es qué
recibieron.
"""

import contextlib
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from act import act_cx_resources_deploy_cloudrun as pipeline


PROJECT, AGENT = "proyecto-de-prueba", "agente-de-prueba"

REMOTO = {"name": f"p/agents/{AGENT}/playbooks/p1", "displayName": "Compra",
          "goal": "lo que dice CX ahora"}
DOCUMENTO = {"metadata": {"tipo": "playbook", "padre": None, "cx_id": "p1",
                          "agente": AGENT},
             "displayName": "Compra", "goal": "lo que dice el archivo"}


class _GitHubDoble:
    def __init__(self):
        self.commits = []

    def commit_files(self, rama, archivos, mensaje):
        self.commits.append({"rama": rama, "archivos": archivos,
                             "mensaje": mensaje})
        return "cccccccdddddddd"

    def branch_head(self, rama):
        return "aaaaaaa"


class _ContextoDoble:
    def __init__(self, gh):
        self.project, self.agent_id = PROJECT, AGENT
        self.store = object()
        self.region, self.carpeta_raiz = "europe-west1", "definitions"
        self.repo, self.rama, self.rama_principal = "org/repo", "rama", "main"
        self.gh = gh
        self.agente_slug = "agente-de-prueba"
        self.parent = f"projects/{PROJECT}/locations/europe-west1/agents/{AGENT}"


@pytest.fixture
def banco(monkeypatch):
    """CX, GitHub y Firestore de mentira, y el registro de lo que reciben."""
    gh = _GitHubDoble()
    escrito_en_cx = []
    registrado = []

    inventario = {tipo: {} for tipo in pipeline.RESOURCE_TYPES}
    inventario["playbook"] = {"p1": REMOTO}
    repositorio = {
        "commit": "aaaaaaa", "total_archivos": 1, "sin_cx_id": [],
        "por_tipo": {"playbook": {"p1": {
            "ruta": "definitions/agente-de-prueba/playbooks/compra.yaml",
            "documento": DOCUMENTO, "display_name": "Compra", "padre": None}}},
    }

    monkeypatch.setattr(pipeline, "Contexto",
                        lambda *a, **k: _ContextoDoble(gh))
    monkeypatch.setattr(pipeline, "inventariar_cx",
                        lambda *a, **k: (inventario, None, None))
    monkeypatch.setattr(pipeline, "cargar_repositorio",
                        lambda *a, **k: (repositorio, None))
    monkeypatch.setattr(pipeline, "avisar_cambio_de_archivo", lambda *a, **k: [])
    monkeypatch.setattr(pipeline, "_commit_que_dejo_el_pipeline",
                        lambda *a, **k: None)
    monkeypatch.setattr(pipeline.store, "agent_lock",
                        lambda *a, **k: contextlib.nullcontext())
    monkeypatch.setattr(pipeline.store, "record_resource_write",
                        lambda *a, **k: registrado.append(k))

    def _aplicar(contexto, operacion, inv):
        escrito_en_cx.append(operacion["cx_id"])
        return dict(REMOTO)

    monkeypatch.setattr(pipeline, "_aplicar_operacion", _aplicar)

    def con_movimiento(cual):
        monkeypatch.setattr(pipeline, "_quien_se_movio",
                            lambda *a, **k: cual)

    return type("Banco", (), {
        "gh": gh, "escrito_en_cx": escrito_en_cx, "registrado": registrado,
        "con_movimiento": staticmethod(con_movimiento),
    })


# ── Paso 3: no se lleva a CX lo que vino de CX ───────────────────────────────

def test_el_paso_3_se_niega_a_aplicar_lo_que_se_movio_en_cx(banco):
    """Aplicarlo revertiría en silencio lo que alguien escribió en la consola.

    El panel ya no lo ofrece, pero el servidor no se fía de la lista que le
    manden: es lo último que queda entre una petición y una escritura en CX.
    """
    banco.con_movimiento("cx")
    with pytest.raises(pipeline.PipelineError) as error:
        pipeline.step_3_apply_to_cx(PROJECT, AGENT)
    assert "Paso 2" in str(error.value)
    assert banco.escrito_en_cx == [], "escribió en CX pese a rechazarlo"


def test_el_paso_3_se_niega_a_aplicar_lo_que_se_movio_en_los_dos(banco):
    banco.con_movimiento("ambos")
    with pytest.raises(pipeline.PipelineError):
        pipeline.step_3_apply_to_cx(PROJECT, AGENT)
    assert banco.escrito_en_cx == []


def test_el_paso_3_sigue_aplicando_lo_que_se_movio_en_el_repositorio(banco):
    """La anti-regresión: el camino de siempre no puede haberse cerrado."""
    banco.con_movimiento("repo")
    resultado = pipeline.step_3_apply_to_cx(PROJECT, AGENT)
    assert resultado["status"] == "ok"
    assert banco.escrito_en_cx == ["p1"]


def test_sin_saber_de_que_lado_vino_el_paso_3_aplica_como_siempre(banco):
    """Los resources escritos antes de que existiera la huella del repositorio.

    Es la dirección barata: llevar a CX de más se ve y se corrige.
    """
    banco.con_movimiento(None)
    pipeline.step_3_apply_to_cx(PROJECT, AGENT)
    assert banco.escrito_en_cx == ["p1"]


def test_el_dry_run_enseña_lo_bloqueado_en_vez_de_esconderlo(banco):
    """Esconderlo haría que el plan mintiera sobre lo que difiere."""
    banco.con_movimiento("ambos")
    datos = pipeline.step_3_apply_to_cx(PROJECT, AGENT, dry_run=True)["data"]
    assert [o["cx_id"] for o in datos["operaciones"]] == ["p1"]
    assert [o["cx_id"] for o in datos["no_aplicables"]] == ["p1"]
    assert banco.escrito_en_cx == [], "un dry-run no escribe"


# ── Paso 2: lo editado en CX vuelve al repositorio ───────────────────────────

def test_el_paso_2_sobrescribe_el_archivo_cuando_el_que_se_movio_fue_cx(banco):
    """La dirección que no existía.

    El paso se negaba a tocar un archivo existente —«ya tiene archivo, se
    omite»— y lo editado en la consola se quedaba como diferencia eterna.
    """
    banco.con_movimiento("cx")
    datos = pipeline.step_2_pull_to_repo(
        PROJECT, AGENT, [{"tipo": "playbook", "cx_id": "p1"}])["data"]

    assert [t["cx_id"] for t in datos["traidos"]] == ["p1"]
    assert len(banco.gh.commits) == 1
    escrito = banco.gh.commits[0]["archivos"]
    ruta = "definitions/agente-de-prueba/playbooks/compra.yaml"
    assert ruta in escrito
    # Y lo que se escribe es lo que dice CX, no lo que decía el archivo.
    assert "lo que dice CX ahora" in escrito[ruta]


def test_el_paso_2_no_sobrescribe_si_el_repositorio_tambien_se_movio(banco):
    """Traerlo se llevaría por delante el cambio del repositorio.

    Esa decisión no es de un paso automático: sale de los dos pasos y la toma
    una persona mirando las dos versiones.
    """
    banco.con_movimiento("ambos")
    datos = pipeline.step_2_pull_to_repo(
        PROJECT, AGENT, [{"tipo": "playbook", "cx_id": "p1"}])["data"]

    assert datos["traidos"] == []
    assert banco.gh.commits == [], "escribió en GitHub sin dirección segura"


def test_el_paso_2_no_sobrescribe_cuando_no_se_sabe_de_que_lado_vino(banco):
    """La dirección cara: sobrescribir un archivo se lleva lo que hubiera dentro."""
    banco.con_movimiento(None)
    datos = pipeline.step_2_pull_to_repo(
        PROJECT, AGENT, [{"tipo": "playbook", "cx_id": "p1"}])["data"]

    assert datos["traidos"] == []
    assert banco.gh.commits == []


def test_al_sobrescribir_se_guardan_las_dos_huellas(banco):
    """Si no, el resource saldría como movido otra vez en la ejecución siguiente."""
    banco.con_movimiento("cx")
    pipeline.step_2_pull_to_repo(
        PROJECT, AGENT, [{"tipo": "playbook", "cx_id": "p1"}])

    assert len(banco.registrado) == 1
    assert banco.registrado[0]["huella_cx"]
    assert banco.registrado[0]["huella_repo"]
