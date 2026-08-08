"""Tests unitarios de act/utils/cx_payloads.py.

Sin red: build_full_update_body es una función pura sobre dicts. Los inputs
se construyen a mano aquí — si un test necesitara una llamada a CX para
armar el objeto de entrada, estaría probando la API, no la función.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from act.utils.cx_payloads import PLAYBOOK_IGNORE_FIELDS, build_full_update_body


def test_preserva_campos_remotos_no_declarados_en_local():
    remote = {"displayName": "Compra", "goal": "vender flores", "llmModelSettings": {"model": "gemini"}}
    local = {"displayName": "Compra"}

    merged = build_full_update_body(remote, local)

    assert merged["goal"] == "vender flores"
    assert merged["llmModelSettings"] == {"model": "gemini"}


def test_local_sobreescribe_remoto():
    remote = {"displayName": "Compra", "goal": "antiguo"}
    local = {"goal": "nuevo"}

    merged = build_full_update_body(remote, local)

    assert merged["goal"] == "nuevo"


def test_elimina_campos_read_only_del_remoto():
    remote = {
        "name": "projects/p/locations/l/agents/a/playbooks/123",
        "tokenCount": 1500,
        "createTime": "2026-01-01T00:00:00Z",
        "updateTime": "2026-02-01T00:00:00Z",
        "displayName": "Compra",
    }

    merged = build_full_update_body(remote, {})

    for field in PLAYBOOK_IGNORE_FIELDS:
        assert field not in merged
    assert merged["displayName"] == "Compra"


def test_elimina_campos_read_only_que_llegan_desde_el_local():
    remote = {"displayName": "Compra"}
    local = {"displayName": "Compra", "name": "playbooks/123", "tokenCount": 99}

    merged = build_full_update_body(remote, local)

    assert "name" not in merged
    assert "tokenCount" not in merged


def test_no_muta_los_dicts_de_entrada():
    remote = {"name": "playbooks/123", "displayName": "Compra", "goal": "antiguo"}
    local = {"goal": "nuevo"}
    remote_original = dict(remote)
    local_original = dict(local)

    build_full_update_body(remote, local)

    assert remote == remote_original
    assert local == local_original


def test_local_vacio_devuelve_remoto_sin_read_only():
    remote = {"name": "playbooks/123", "displayName": "Compra", "goal": "vender"}

    merged = build_full_update_body(remote, {})

    assert merged == {"displayName": "Compra", "goal": "vender"}


def test_remoto_vacio_devuelve_local_sin_read_only():
    local = {"name": "playbooks/123", "displayName": "Compra"}

    merged = build_full_update_body({}, local)

    assert merged == {"displayName": "Compra"}


def test_caso_realista_edicion_de_instruction_steps():
    remote = {
        "name": "projects/p/locations/l/agents/a/playbooks/123",
        "displayName": "Compra",
        "goal": "Gestionar la compra de flores",
        "tokenCount": 13200,
        "instruction": {"steps": [{"text": "paso antiguo"}]},
    }
    local = {"instruction": {"steps": [{"text": "paso nuevo"}]}}

    merged = build_full_update_body(remote, local)

    assert merged["instruction"] == {"steps": [{"text": "paso nuevo"}]}
    assert merged["goal"] == "Gestionar la compra de flores"
    assert "tokenCount" not in merged


@pytest.mark.parametrize("field", PLAYBOOK_IGNORE_FIELDS)
def test_cada_campo_read_only_se_elimina(field):
    merged = build_full_update_body({field: "valor"}, {})

    assert field not in merged
