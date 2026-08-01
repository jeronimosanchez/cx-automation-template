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
