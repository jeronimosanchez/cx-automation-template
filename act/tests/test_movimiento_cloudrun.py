"""
act/tests/test_movimiento_cloudrun.py — De qué lado vino el cambio.

El diff solo ve dos estados, repositorio y CX, y con dos no se puede saber
**quién se movió**: una diferencia se lee igual venga de donde venga. Por eso
todo acababa en el Paso 3, incluido lo editado a mano en la consola, que no
tenía camino de vuelta.

El tercer punto es cómo quedaron los dos lados la última vez que escribió el
pipeline. Cada lado se compara contra su propio pasado — nunca uno contra el
otro, porque `differs` compara solo los campos que el YAML declara y el payload
local es un subconjunto del remoto.

Ninguno toca la red: son funciones puras.
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from act import act_cx_resources_deploy_cloudrun as pipeline
from act.utils import cx_payloads_cloudrun as payloads


REMOTO_ENTONCES = {"name": "p/playbooks/x", "displayName": "Compra",
                   "goal": "vender"}
LOCAL_ENTONCES = {"displayName": "Compra", "goal": "vender"}


def _operacion(local):
    return {"tipo": "playbook", "cx_id": "abc", "local": local}


def _auditoria(huella_cx=None, huella_repo=None, **extra):
    registro = {"huella_cx": huella_cx, "huella_repo": huella_repo}
    registro.update(extra)
    return {("playbook", "abc"): registro}


def _huellas_de_partida():
    return (pipeline.huella_resource(REMOTO_ENTONCES),
            pipeline.huella_local(LOCAL_ENTONCES))


# ── Las cuatro combinaciones ─────────────────────────────────────────────────

def test_si_solo_se_movio_el_repositorio_es_repo():
    cx, repo = _huellas_de_partida()
    movimiento = pipeline._quien_se_movio(
        _operacion({"displayName": "Compra", "goal": "vender MÁS"}),
        REMOTO_ENTONCES, _auditoria(cx, repo),
    )
    assert movimiento == "repo"


def test_si_solo_se_movio_cx_es_cx():
    """El caso que no existía: editar en la consola y poder traerlo."""
    cx, repo = _huellas_de_partida()
    movimiento = pipeline._quien_se_movio(
        _operacion(LOCAL_ENTONCES),
        {**REMOTO_ENTONCES, "goal": "otra cosa"}, _auditoria(cx, repo),
    )
    assert movimiento == "cx"


def test_si_se_movieron_los_dos_es_ambos():
    cx, repo = _huellas_de_partida()
    movimiento = pipeline._quien_se_movio(
        _operacion({"displayName": "Compra", "goal": "lo del repo"}),
        {**REMOTO_ENTONCES, "goal": "lo de CX"}, _auditoria(cx, repo),
    )
    assert movimiento == "ambos"


def test_si_no_se_movio_ninguno_no_dice_nada():
    """Difieren pero ninguno avanzó: el pipeline los dejó ya distintos.

    No es ninguno de los tres casos, y mandarlo a un paso sería inventar.
    """
    cx, repo = _huellas_de_partida()
    movimiento = pipeline._quien_se_movio(
        _operacion(LOCAL_ENTONCES), REMOTO_ENTONCES, _auditoria(cx, repo),
    )
    assert movimiento is None


# ── Cuando no se sabe ────────────────────────────────────────────────────────

def test_un_registro_viejo_sin_huella_del_repo_no_se_enruta():
    """Los resources escritos antes de que existiera `huella_repo`.

    Sin ese dato no se puede saber si el repositorio se movió. Devolver "cx"
    por descarte mandaría a sobrescribir un archivo sin motivo — la dirección
    cara, la que se lleva por delante lo que hubiera dentro.
    """
    cx, _ = _huellas_de_partida()
    movimiento = pipeline._quien_se_movio(
        _operacion({"displayName": "Compra", "goal": "otra"}),
        {**REMOTO_ENTONCES, "goal": "y otra"}, _auditoria(cx, None),
    )
    assert movimiento is None


def test_un_resource_que_el_pipeline_nunca_escribio_no_se_enruta():
    movimiento = pipeline._quien_se_movio(
        _operacion(LOCAL_ENTONCES), REMOTO_ENTONCES, {},
    )
    assert movimiento is None


# ── La ida y la vuelta ───────────────────────────────────────────────────────

def test_traer_un_resource_no_lo_deja_pareciendo_movido():
    """La invariante que sostiene todo lo demás.

    El Paso 2 guarda la huella del archivo que acaba de escribir; el diff
    siguiente la recalcula leyendo ese archivo. Si el volcado a YAML
    normalizara cualquier cosa, las dos no coincidirían y el resource saldría
    como «movido en el repositorio» nada más traerlo — un cambio fantasma en
    cada ejecución.
    """
    item = {"name": "p/playbooks/x", "createTime": "2026-01-01T00:00:00Z",
            "displayName": "Compra", "goal": "vender",
            "instruction": {"steps": [{"text": "saludar"}]},
            "inputParameterDefinitions": []}
    texto = pipeline._yaml_para_repo("playbook", item, None, agente="ag1")
    guardada = pipeline._huella_del_archivo("playbook", texto)

    # Lo que hará el diff siguiente: leer el archivo del repositorio.
    import yaml
    documento = yaml.safe_load(texto)
    recalculada = pipeline.huella_local(
        payloads.comparable_local("playbook", documento))

    assert guardada == recalculada
    assert guardada is not None


def test_dos_huellas_distintas_no_significan_que_esten_en_desacuerdo():
    """Por qué cada lado se compara solo contra su propio pasado.

    `differs` mira **solo los campos que el YAML declara**: los que no menciona
    se preservan del remoto y no son una diferencia. Así que un remoto con
    campos de más está de acuerdo con el archivo y aun así su huella es otra.

    Si alguien decidiera «se movió» comparando una huella con la otra, este
    resource saldría como cambiado en cada ejecución sin que nadie lo tocara.
    """
    remoto = {**REMOTO_ENTONCES, "referenceId": "lo-pone-el-servidor"}
    assert payloads.differs(remoto, LOCAL_ENTONCES) is False
    assert (pipeline.huella_resource(remoto)
            != pipeline.huella_local(LOCAL_ENTONCES))


def test_el_mismo_contenido_da_la_misma_huella_en_otro_orden():
    """Sin esto, reordenar claves del YAML se leería como un cambio."""
    assert (pipeline.huella_local({"a": 1, "b": 2})
            == pipeline.huella_local({"b": 2, "a": 1}))
