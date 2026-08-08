"""Tests unitarios del comparador del Paso 3.

Sin red: _differs y _comparable_local son funciones puras sobre dicts.
Los inputs imitan la forma real de la API (que omite los campos vacíos en
vez de devolverlos vacíos) y la de los YAML del repo (que sí los declaran).
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from act.act_cx_resources_deploy import (
    LOCAL_ONLY_FIELDS,
    UNORDERED_FIELDS,
    _comparable_local,
    _differs,
    _is_empty,
    diff_playbooks,
)


@pytest.mark.parametrize("valor", [None, [], {}, ""])
def test_valores_vacios_equivalentes(valor):
    assert _is_empty(valor)


@pytest.mark.parametrize("valor", [0, False, "algo", [1], {"a": 1}])
def test_valores_con_contenido_no_son_vacios(valor):
    assert not _is_empty(valor)


def test_lista_vacia_local_y_campo_ausente_remoto_no_es_diferencia():
    remote = {"displayName": "Compra"}
    local = {"displayName": "Compra", "inputParameterDefinitions": []}

    assert not _differs(remote, local)


def test_lista_con_contenido_frente_a_campo_ausente_si_es_diferencia():
    remote = {"displayName": "Compra"}
    local = {"displayName": "Compra", "inputParameterDefinitions": [{"name": "x"}]}

    assert _differs(remote, local)


def test_campo_declarado_con_valor_distinto_es_diferencia():
    assert _differs({"goal": "viejo"}, {"goal": "nuevo"})


def test_campo_no_declarado_en_local_no_es_diferencia():
    remote = {"goal": "vender", "tokenCount": 1500}
    local = {"goal": "vender"}

    assert not _differs(remote, local)


def test_cero_y_false_no_se_confunden_con_vacio():
    assert _differs({}, {"repeatCount": 0}) is True
    assert _differs({}, {"enabled": False}) is True


def test_comparable_local_descarta_los_campos_solo_del_repo():
    local = {"displayName": "ex1", "id": "abc-123", "playbook": "Checkout",
             "actions": [{"agentUtterance": {"text": "hola"}}]}

    comparable = _comparable_local("examples", local)

    assert set(comparable) == {"displayName", "actions"}


def test_comparable_local_no_toca_tipos_sin_campos_propios_del_repo():
    local = {"displayName": "Compra", "goal": "vender"}

    assert _comparable_local("playbooks", local) == local


@pytest.mark.parametrize("resource_type,field", [
    (tipo, campo)
    for tipo, campos in LOCAL_ONLY_FIELDS.items() for campo in campos
])
def test_cada_campo_solo_del_repo_se_descarta(resource_type, field):
    assert field not in _comparable_local(resource_type, {field: "valor"})


def test_idempotencia_sin_cambios_no_genera_operaciones():
    remote = [{"name": "n/1", "displayName": "Compra", "goal": "vender",
               "referencedTools": ["t/1"]}]
    local = {"Compra": {"displayName": "Compra", "goal": "vender",
                        "referencedTools": ["t/1"], "inputParameterDefinitions": []}}

    assert diff_playbooks(remote, local) == []


def test_las_tres_operaciones_son_excluyentes_por_recurso():
    remote = [{"name": "n/1", "displayName": "Igual", "goal": "x"},
              {"name": "n/2", "displayName": "Cambiado", "goal": "viejo"},
              {"name": "n/3", "displayName": "Sobrante", "goal": "z"}]
    local = {"Igual": {"displayName": "Igual", "goal": "x"},
             "Cambiado": {"displayName": "Cambiado", "goal": "nuevo"},
             "Nuevo": {"displayName": "Nuevo", "goal": "y"}}

    operaciones = diff_playbooks(remote, local)
    por_recurso = {o["resource"]: o["operation"] for o in operaciones}

    assert por_recurso == {"Cambiado": "PATCH", "Nuevo": "POST", "Sobrante": "DELETE"}
    assert len(operaciones) == len(por_recurso)


def test_los_tools_integrados_no_entran_en_el_diff():
    """code-interpreter lo provee la plataforma: no está ni puede estar en
    el repo, y proponerlo como DELETE haría que el Paso 4 intentara borrar
    un recurso de CX."""
    remote = [{"name": "t/1", "displayName": "PetalDataTool", "toolType": "CUSTOMIZED_TOOL"},
              {"name": "t/2", "displayName": "code-interpreter", "toolType": "BUILTIN_TOOL"}]
    local = {"PetalDataTool": {"displayName": "PetalDataTool"}}

    from act.act_cx_resources_deploy import diff_tools
    assert diff_tools(remote, local) == []


def test_un_tool_propio_ausente_del_repo_si_sale_como_delete():
    remote = [{"name": "t/1", "displayName": "OtroTool", "toolType": "CUSTOMIZED_TOOL"}]

    from act.act_cx_resources_deploy import diff_tools
    operaciones = diff_tools(remote, {})

    assert [(o["resource"], o["operation"]) for o in operaciones] == [("OtroTool", "DELETE")]


def test_referencias_en_distinto_orden_no_son_diferencia():
    """referencedPlaybooks declara a quién puede llamar este playbook: es un
    conjunto de permisos, y CX lo devuelve en su propio orden."""
    remote = {"referencedPlaybooks": ["pb/b", "pb/a", "pb/c"]}
    local = {"referencedPlaybooks": ["pb/a", "pb/b", "pb/c"]}

    assert not _differs(remote, local)


def test_una_referencia_de_mas_o_de_menos_si_es_diferencia():
    remote = {"referencedPlaybooks": ["pb/a", "pb/b"]}

    assert _differs(remote, {"referencedPlaybooks": ["pb/a", "pb/b", "pb/c"]})
    assert _differs(remote, {"referencedPlaybooks": ["pb/a"]})


@pytest.mark.parametrize("field", UNORDERED_FIELDS)
def test_los_tres_campos_de_referencias_ignoran_el_orden(field):
    assert not _differs({field: ["y", "x"]}, {field: ["x", "y"]})


def test_las_secuencias_reales_siguen_siendo_sensibles_al_orden():
    """instruction.steps y actions son secuencias: reordenarlas cambia el
    comportamiento, así que tratarlas como conjunto ocultaría un cambio real."""
    remote = {"instruction": {"steps": [{"text": "uno"}, {"text": "dos"}]}}
    local = {"instruction": {"steps": [{"text": "dos"}, {"text": "uno"}]}}

    assert _differs(remote, local)

    remote_ex = {"actions": [{"a": 1}, {"b": 2}]}
    assert _differs(remote_ex, {"actions": [{"b": 2}, {"a": 1}]})


def test_subclave_no_declarada_en_local_no_es_diferencia():
    """El YAML de un tool declara openApiSpec.textSchema pero no
    openApiSpec.authentication, que CX sí tiene. Comparar el dict entero
    haría salir el tool como PATCH en cada ejecución."""
    remote = {"openApiSpec": {"textSchema": "openapi: 3.0.0", "authentication": {"apiKey": "x"}}}
    local = {"openApiSpec": {"textSchema": "openapi: 3.0.0"}}

    assert not _differs(remote, local)


def test_subclave_con_valor_distinto_si_es_diferencia():
    remote = {"openApiSpec": {"textSchema": "viejo", "authentication": {"apiKey": "x"}}}
    local = {"openApiSpec": {"textSchema": "nuevo"}}

    assert _differs(remote, local)


def test_anidamiento_de_mas_de_un_nivel():
    remote = {"advancedSettings": {"speechSettings": {"noSpeechTimeout": "5s", "extra": 1}}}
    local = {"advancedSettings": {"speechSettings": {"noSpeechTimeout": "5s"}}}

    assert not _differs(remote, local)
    assert _differs(remote, {"advancedSettings": {"speechSettings": {"noSpeechTimeout": "9s"}}})
