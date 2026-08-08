"""
act/tests/test_cx_payloads_cloudrun.py — Tests de la capa de adaptación del
pipeline Cloud Run.

Ninguno toca la red ni necesita credenciales: cubren funciones puras, así que
se pueden correr en cualquier momento para comprobar rápido que la lógica de
comparación sigue en pie. Si alguno necesitara conexión, dejaría de probar la
función y pasaría a probar la API.

Cada caso está escrito contra un fallo concreto que ya ocurrió o que rompería
una regla firmada del proyecto — no hay tests de "la función existe".
"""

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from act.utils import cx_payloads_cloudrun as payloads


# ── metadata ─────────────────────────────────────────────────────────────────

def test_metadata_se_lee_cuando_existe():
    documento = {"metadata": {"tipo": "playbook", "cx_id": "abc"},
                 "displayName": "Compra"}
    assert payloads.read_metadata(documento) == {"tipo": "playbook", "cx_id": "abc"}


def test_yaml_sin_metadata_no_es_un_resource():
    """Un YAML sin cabecera se ignora, no da error.

    En el repositorio hay YAML que nunca fueron resources —taxonomías,
    configuraciones de scoring, specs OpenAPI— y perseguirlos como resources
    incompletos convertiría el arranque en una lista de falsos errores.
    """
    assert payloads.read_metadata({"displayName": "Compra"}) is None
    assert payloads.read_metadata(None) is None
    assert payloads.read_metadata(["no", "es", "un", "mapa"]) is None


def test_metadata_nunca_viaja_a_cx():
    """Regla única de S18: lo de dentro de metadata se excluye, lo de fuera se envía."""
    documento = {"metadata": {"tipo": "playbook", "padre": None, "cx_id": "abc"},
                 "displayName": "Compra", "goal": "vender flores"}
    assert payloads.strip_metadata(documento) == {
        "displayName": "Compra", "goal": "vender flores",
    }


def test_campos_locales_no_entran_en_la_comparacion():
    """`id` y `playbook` de un example no existen en la API.

    Compararlos haría que cada example saliera siempre como PATCH; enviarlos
    haría que la API rechazara la llamada.
    """
    documento = {
        "metadata": {"tipo": "example", "cx_id": "abc"},
        "playbook": "Checkout", "id": "abc",
        "displayName": "Ex01",
    }
    assert payloads.comparable_local("example", documento) == {"displayName": "Ex01"}


# ── Comparación ──────────────────────────────────────────────────────────────

def test_campo_vacio_y_campo_ausente_son_lo_mismo():
    """CX omite los campos con valor por defecto en vez de devolverlos vacíos.

    Sin esta equivalencia, `inputParameterDefinitions: []` frente a un remoto
    que no trae el campo se lee como diferencia, el recurso sale como PATCH en
    cada ejecución y se rompe la idempotencia (CLAUDE.md §3.4).
    """
    remoto = {"displayName": "Compra"}
    local = {"displayName": "Compra", "inputParameterDefinitions": []}
    assert payloads.differs(remoto, local) is False


def test_un_cambio_real_si_es_diferencia():
    remoto = {"displayName": "Compra", "goal": "vender"}
    local = {"displayName": "Compra", "goal": "vender flores"}
    assert payloads.differs(remoto, local) is True


def test_campos_no_declarados_en_el_yaml_no_son_diferencia():
    """Lo que el YAML no menciona se preserva del remoto, así que no difiere."""
    remoto = {"displayName": "Compra", "tokenCount": 1234, "llmModelSettings": {}}
    local = {"displayName": "Compra"}
    assert payloads.differs(remoto, local) is False


def test_las_referencias_no_dependen_del_orden():
    """referencedTools declara a qué puede llamar, no en qué orden.

    CX las devuelve en un orden propio que no tiene por qué coincidir con el
    del YAML; compararlas como secuencia sacaría el playbook como PATCH cada
    vez sin que nada hubiera cambiado.
    """
    remoto = {"referencedTools": ["b", "a"]}
    local = {"referencedTools": ["a", "b"]}
    assert payloads.differs(remoto, local) is False


def test_una_referencia_de_menos_si_es_diferencia():
    remoto = {"referencedTools": ["a", "b"]}
    local = {"referencedTools": ["a"]}
    assert payloads.differs(remoto, local) is True


def test_las_listas_normales_si_dependen_del_orden():
    """Los pasos de una instrucción son una secuencia, no un conjunto.

    Compararlos sin orden ocultaría una reordenación real, que en un playbook
    cambia el comportamiento.
    """
    remoto = {"instruction": {"steps": ["uno", "dos"]}}
    local = {"instruction": {"steps": ["dos", "uno"]}}
    assert payloads.differs(remoto, local) is True


def test_una_subclave_no_declarada_no_es_diferencia():
    """Si el YAML solo declara openApiSpec.textSchema, el resto se preserva."""
    remoto = {"openApiSpec": {"textSchema": "x", "authentication": {"k": "v"}}}
    local = {"openApiSpec": {"textSchema": "x"}}
    assert payloads.differs(remoto, local) is False


def test_una_subclave_declarada_y_distinta_si_es_diferencia():
    remoto = {"openApiSpec": {"textSchema": "x", "authentication": {"k": "v"}}}
    local = {"openApiSpec": {"textSchema": "y"}}
    assert payloads.differs(remoto, local) is True


def test_same_references_exige_dos_listas():
    assert payloads.same_references("a", ["a"]) is False
    assert payloads.same_references(["a"], None) is False


# ── Full Update ──────────────────────────────────────────────────────────────

def test_full_update_preserva_lo_que_el_yaml_no_declara():
    """Sin updateMask la API interpreta el body como el objeto entero.

    Mandar solo los campos del YAML equivale a pedir que borre los demás:
    verificado con Flows, que devuelven 400 por intentar eliminar el
    eventHandler 'sys.no-match-default' que ningún YAML declara.
    """
    remoto = {"name": "projects/x/playbooks/y", "displayName": "Compra",
              "llmModelSettings": {"model": "gemini"}, "tokenCount": 900}
    local = {"displayName": "Compra v2"}
    cuerpo = payloads.build_full_update_body(remoto, local)
    assert cuerpo["displayName"] == "Compra v2"
    assert cuerpo["llmModelSettings"] == {"model": "gemini"}


def test_full_update_quita_los_campos_de_solo_lectura():
    """La API devuelve estos campos en GET pero los rechaza en PATCH."""
    remoto = {"name": "n", "tokenCount": 1, "createTime": "t",
              "updateTime": "t", "displayName": "Compra"}
    cuerpo = payloads.build_full_update_body(remoto, {"displayName": "Compra"})
    for campo in ("name", "tokenCount", "createTime", "updateTime"):
        assert campo not in cuerpo


def test_version_excluye_state():
    """`state` es de solo lectura y no estaba en la lista conocida.

    Hay que leerlo para confirmar que una versión terminó bien, pero enviarlo
    de vuelta haría fallar la escritura.
    """
    assert "state" in payloads.ignore_fields_for("version")


def test_agent_config_excluye_los_campos_que_añade_google():
    campos = payloads.ignore_fields_for("agent_config")
    assert "satisfiesPzi" in campos and "satisfiesPzs" in campos


def test_tipo_desconocido_cae_en_la_lista_por_defecto():
    assert payloads.ignore_fields_for("transition_route_group") == ["name"]


# ── Cuerpo de creación ───────────────────────────────────────────────────────

def test_build_create_body_no_lleva_metadata_ni_campos_locales():
    documento = {
        "metadata": {"tipo": "example", "padre": "p", "cx_id": ""},
        "playbook": "Checkout", "id": "abc",
        "displayName": "Ex01", "actions": [{"agentUtterance": "hola"}],
    }
    cuerpo = payloads.build_create_body("example", documento)
    assert cuerpo == {"displayName": "Ex01",
                      "actions": [{"agentUtterance": "hola"}]}


def test_build_create_body_no_manda_name():
    """`name` lo asigna la API; enviarlo en un POST la hace rechazar la llamada."""
    documento = {"metadata": {"tipo": "intent"}, "name": "no-deberia-viajar",
                 "displayName": "Saludo"}
    assert "name" not in payloads.build_create_body("intent", documento)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
