"""Tests unitarios para act/pull_examples.py.

Cubre cx_to_local (strip + id extraction + playbook injection + order),
slugify con colapsado de underscores, dumper con literal block, y
round-trip end-to-end usando push_examples.load_example_yaml +
split_local_fields + find_existing_example + diff_resource.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from act.diff import diff_resource
from act.pull_examples import (
    PULL_STRIP_FIELDS,
    cx_to_local,
    dump_yaml,
    slugify,
)
from act.push_examples import (
    EXAMPLE_IGNORE_FIELDS,
    find_existing_example,
    load_example_yaml,
    split_local_fields,
)


AGENT_PATH = "projects/test-project/locations/europe-west1/agents/agent-uuid"
PB_PATH = f"{AGENT_PATH}/playbooks/pb-uuid"
EX_PATH = f"{PB_PATH}/examples/ex-uuid-abc"


# ============================================================
# cx_to_local — strip + id extraction + playbook injection
# ============================================================
def test_cx_to_local_strips_readonly_and_extracts_id():
    remote = {
        "name": EX_PATH,
        "displayName": "Ex_Reg_01",
        "actions": [{"agentUtterance": {"text": "Hola"}}],
        "tokenCount": "42",
        "createTime": "2026-05-01T00:00:00Z",
        "updateTime": "2026-05-02T00:00:00Z",
    }
    local = cx_to_local(remote, parent_playbook_display_name="Registro_Task")
    # Read-only strippeados (excepto name, que se transforma a id)
    for f in PULL_STRIP_FIELDS:
        assert f not in local, f"{f} debio ser strippeado"
    # id extraido del path completo
    assert local["id"] == "ex-uuid-abc"
    # playbook inyectado
    assert local["playbook"] == "Registro_Task"
    # Body conservado
    assert local["displayName"] == "Ex_Reg_01"
    assert local["actions"][0]["agentUtterance"]["text"] == "Hola"


def test_cx_to_local_canonical_order():
    """playbook + id van primero; despues body; desconocidos al final."""
    remote = {
        "playbookOutput": {"actionParameters": {}},
        "actions": [],
        "displayName": "Ex",
        "name": EX_PATH,
        "playbookInput": {"actionParameters": {}},
        "newFutureField": 99,
    }
    keys = list(cx_to_local(remote, parent_playbook_display_name="P").keys())
    assert keys[0] == "playbook"
    assert keys[1] == "id"
    assert keys[2] == "displayName"
    assert keys.index("actions") < keys.index("playbookInput")
    assert keys.index("playbookInput") < keys.index("playbookOutput")
    assert keys[-1] == "newFutureField"


def test_cx_to_local_without_name_omits_id():
    """Edge case: remote sin `name` -> sin id (caso defensivo, no debe pasar en CX real)."""
    remote = {"displayName": "Ex", "actions": []}
    local = cx_to_local(remote, parent_playbook_display_name="P")
    assert "id" not in local
    assert local["playbook"] == "P"


def test_cx_to_local_preserves_unknown_fields():
    remote = {"name": EX_PATH, "displayName": "Ex", "newFutureField": {"k": 1}}
    local = cx_to_local(remote, parent_playbook_display_name="P")
    assert local["newFutureField"] == {"k": 1}


# ============================================================
# slugify — incluye casos de Petal reales
# ============================================================
@pytest.mark.parametrize("display_name,expected", [
    ("Ex_Reg_01", "ex_reg_01"),
    ("Ex09 —solicitud agente", "ex09_solicitud_agente"),
    ("Compra/Ex01", "compra_ex01"),
    ("  trim me  ", "trim_me"),
    ("UPPER_case.with.dots", "upper_case.with.dots"),
])
def test_slugify_variations(display_name, expected):
    assert slugify(display_name) == expected


def test_slugify_collapses_multiple_underscores_from_stripped_chars():
    """'Ex06 — G2→G5' tiene em-dash y flecha que se eliminan;
    el slug NO debe tener __ doble."""
    s = slugify("Ex06 — G2→G5 con re-deteccion")
    assert "__" not in s, f"underscores duplicados: {s}"
    # Verificacion adicional: comienza con ex06, termina con deteccion
    assert s.startswith("ex06")
    assert s.endswith("deteccion")


def test_slugify_fallback():
    assert slugify("") == "unnamed"
    assert slugify("→→→") == "unnamed"


# ============================================================
# Dumper — literal block + spanish chars + no folding
# ============================================================
def test_dump_yaml_uses_literal_block_for_multiline():
    body = {
        "playbook": "P",
        "id": "uuid",
        "displayName": "Ex",
        "actions": [{"agentUtterance": {"text": "linea 1\nlinea 2"}}],
    }
    text = dump_yaml(body)
    assert "|" in text or "|-" in text
    assert "\\n" not in text  # nada de escapes
    reloaded = yaml.safe_load(text)
    assert reloaded == body


def test_dump_yaml_preserves_spanish_chars():
    body = {
        "playbook": "P", "id": "u", "displayName": "Ex",
        "actions": [{"agentUtterance": {"text": "¡Hola! ¿Cómo estás?"}}],
    }
    text = dump_yaml(body)
    assert "¡Hola!" in text
    assert "¿Cómo estás?" in text
    assert "\\u" not in text


# ============================================================
# Round-trip end-to-end usando push_examples real
# ============================================================
def test_round_trip_pull_to_push_reports_unchanged():
    """cx_to_local(remote, parent) -> dump -> push.load_example_yaml ->
    split_local_fields -> find_existing_example -> diff -> unchanged.

    Es la cadena real que push_examples.py ejecuta en --all --dry-run."""
    remote = {
        "name": EX_PATH,
        "displayName": "Ex_Reg_01",
        "actions": [
            {"agentUtterance": {"text": "Hola, ¿en qué puedo ayudarte?"}},
            {"userUtterance": {"text": "Quiero registrarme"}},
        ],
        "playbookInput": {"actionParameters": {"email": "test@example.com"}},
        "playbookOutput": {"actionParameters": {"id_cliente": "C123"}},
        "tokenCount": "150",
        "createTime": "2026-05-01T00:00:00Z",
    }
    local = cx_to_local(remote, parent_playbook_display_name="Registro_Task")

    # Simular ciclo push:
    # 1) load_example_yaml leeria el YAML; nosotros le pasamos `local` directo
    #    via split_local_fields (es lo que load_example_yaml hace al final).
    api_body, playbook_name, example_id = split_local_fields(local)
    assert playbook_name == "Registro_Task"
    assert example_id == "ex-uuid-abc"
    assert "playbook" not in api_body
    assert "id" not in api_body

    # 2) push usa find_existing_example(remote_list, id, displayName)
    remote_list = [remote]
    found = find_existing_example(remote_list, example_id, api_body["displayName"])
    assert found is remote, "find_existing_example debio encontrar el remote por id"

    # 3) diff api_body vs remote (con ignore_fields del push)
    result = diff_resource(api_body, found, ignore_fields=EXAMPLE_IGNORE_FIELDS)
    assert result.needs_update is False, (
        f"Round-trip dirty: mask={result.update_mask}, payload={result.patch_payload}"
    )


def test_round_trip_via_real_file_load(tmp_path: Path):
    """Mismo round-trip pero pasando por escritura + lectura de fichero
    real con push_examples.load_example_yaml."""
    remote = {
        "name": EX_PATH,
        "displayName": "Ex01",
        "actions": [{"agentUtterance": {"text": "Hi"}}],
    }
    local = cx_to_local(remote, parent_playbook_display_name="MyPlaybook")

    fp = tmp_path / "ex.yaml"
    fp.write_text(dump_yaml(local))

    playbook, example_id, api_body = load_example_yaml(fp)
    assert playbook == "MyPlaybook"
    assert example_id == "ex-uuid-abc"
    result = diff_resource(api_body, remote, ignore_fields=EXAMPLE_IGNORE_FIELDS)
    assert result.needs_update is False


def test_round_trip_with_long_multiline_action(tmp_path: Path):
    """Round-trip con un example cuya agentUtterance.text tiene
    cientos de chars con multi-linea (caso real de Petal)."""
    long_text = "PASO 1: saludar al cliente.\n" * 50
    remote = {
        "name": EX_PATH,
        "displayName": "Ex_Long",
        "actions": [{"agentUtterance": {"text": long_text}}],
    }
    local = cx_to_local(remote, parent_playbook_display_name="P")
    fp = tmp_path / "ex.yaml"
    fp.write_text(dump_yaml(local))

    playbook, example_id, api_body = load_example_yaml(fp)
    result = diff_resource(api_body, remote, ignore_fields=EXAMPLE_IGNORE_FIELDS)
    assert result.needs_update is False
