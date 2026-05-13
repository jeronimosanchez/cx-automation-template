"""Tests unitarios para src/pull_playbooks.py.

Sin red. Cubre cx_to_local (strip + tokenCount + order), slugify,
dumper custom con bloque literal | y round-trip mock vs
push_playbooks.diff_resource.
"""
from __future__ import annotations

import pytest
import yaml

from src.diff import diff_resource
from src.pull_playbooks import (
    PULL_STRIP_FIELDS,
    cx_to_local,
    dump_yaml,
    slugify,
)
from src.push_playbooks import PLAYBOOK_IGNORE_FIELDS


AGENT_PATH = "projects/test-project/locations/europe-west1/agents/agent-uuid"


# ============================================================
# cx_to_local — strip + order
# ============================================================
def test_cx_to_local_strips_readonly_including_tokenCount():
    remote = {
        "name": f"{AGENT_PATH}/playbooks/p-1",
        "displayName": "Petal CX Orchestrator",
        "goal": "Resolver consultas",
        "playbookType": "ROUTINE",
        "tokenCount": 5440,  # specific to Playbooks
        "createTime": "2026-05-01T00:00:00Z",
        "updateTime": "2026-05-02T00:00:00Z",
        "referencedTools": [f"{AGENT_PATH}/tools/t-1"],
    }
    local = cx_to_local(remote)
    for f in PULL_STRIP_FIELDS:
        assert f not in local, f"{f} debio ser strippeado"
    assert "tokenCount" not in local
    assert local["displayName"] == "Petal CX Orchestrator"
    assert local["goal"] == "Resolver consultas"


def test_cx_to_local_preserves_unknown_fields():
    """Forward-compat: si CX agrega un campo nuevo, lo preservamos."""
    remote = {"displayName": "P", "newFutureField": {"foo": 1}}
    local = cx_to_local(remote)
    assert local["newFutureField"] == {"foo": 1}


def test_cx_to_local_emits_canonical_order():
    remote = {
        "instruction": {"steps": []},
        "outputParameterDefinitions": [],
        "inputParameterDefinitions": [],
        "referencedTools": [],
        "playbookType": "ROUTINE",
        "goal": "g",
        "displayName": "P",
        "newField": 1,
    }
    keys = list(cx_to_local(remote).keys())
    assert keys.index("displayName") < keys.index("goal")
    assert keys.index("goal") < keys.index("playbookType")
    assert keys.index("playbookType") < keys.index("referencedTools")
    assert keys.index("referencedTools") < keys.index("inputParameterDefinitions")
    assert keys.index("inputParameterDefinitions") < keys.index("outputParameterDefinitions")
    assert keys.index("outputParameterDefinitions") < keys.index("instruction")
    assert keys[-1] == "newField"


def test_cx_to_local_preserves_instruction_steps_intact():
    """instruction.steps puede tener miles de chars en español — debe
    preservarse byte-a-byte (round-trip clean)."""
    long_text = "IDENTIDAD DEL AGENTE\n" + ("Eres Petal, asistente.\n" * 50)
    remote = {
        "displayName": "P",
        "instruction": {
            "steps": [
                {"text": long_text},
                {"text": "Otro paso\ncon multi-linea"},
            ],
        },
    }
    local = cx_to_local(remote)
    assert local["instruction"]["steps"][0]["text"] == long_text
    assert local["instruction"]["steps"][1]["text"] == "Otro paso\ncon multi-linea"


def test_cx_to_local_handles_zero_referenced_tools():
    """Caso Handoff: 0 referencedTools."""
    remote = {"displayName": "Handoff", "goal": "Escalado a humano"}
    local = cx_to_local(remote)
    # Si no esta en remote, no lo inventamos
    assert "referencedTools" not in local


# ============================================================
# slugify
# ============================================================
@pytest.mark.parametrize("display_name,expected", [
    ("Petal CX Orchestrator", "petal_cx_orchestrator"),
    ("Checkout", "checkout"),
    ("Registro_Task", "registro_task"),
    ("Gestion_Deuda", "gestion_deuda"),
    ("Handoff", "handoff"),
    ("Compra", "compra"),
])
def test_slugify_for_actual_petal_playbooks(display_name, expected):
    assert slugify(display_name) == expected


# ============================================================
# Dumper custom: bloque literal | para strings multi-linea
# ============================================================
def test_dump_yaml_uses_literal_block_for_multiline_strings():
    body = {
        "displayName": "P",
        "instruction": {
            "steps": [
                {"text": "linea 1\nlinea 2\nlinea 3"},
            ],
        },
    }
    text = dump_yaml(body)
    # Debe usar | (literal block), no comillas dobles con \n escapado
    assert "|" in text or "|-" in text
    assert "\\n" not in text  # nada de escape de saltos
    # Y debe ser reloadable a la estructura original
    reloaded = yaml.safe_load(text)
    assert reloaded == body


def test_dump_yaml_short_strings_stay_inline():
    body = {"displayName": "Compra", "goal": "Gestionar compra"}
    text = dump_yaml(body)
    # Para strings cortos sin newlines, NO debe usar bloque literal
    assert "displayName: Compra" in text
    assert "goal: Gestionar compra" in text


def test_dump_yaml_preserves_spanish_characters():
    body = {
        "displayName": "P",
        "goal": "Gestión de pedidos con ¿variables?",
        "instruction": {"steps": [{"text": "¡Hola!\n¿Cómo?"}]},
    }
    text = dump_yaml(body)
    assert "¿variables?" in text
    assert "¡Hola!" in text
    assert "¿Cómo?" in text
    assert "\\u" not in text


def test_dump_yaml_preserves_long_lines_without_folding():
    """width=1000 evita que PyYAML rompa una linea larga en multiples."""
    long_line = "a" * 500
    body = {"goal": long_line}
    text = dump_yaml(body)
    # La linea debe estar sin folding (no roto en multiples lineas)
    assert long_line in text


# ============================================================
# Round-trip end-to-end (con mocks)
# ============================================================
def test_round_trip_pull_to_push_reports_unchanged_full_playbook():
    """cx_to_local(remote) -> diff vs remote == no-op para un playbook
    representativo de Petal (con tokenCount, instruction.steps multi-linea,
    referencedTools, params)."""
    remote = {
        "name": f"{AGENT_PATH}/playbooks/p-orch",
        "displayName": "Petal CX Orchestrator",
        "goal": "Resolver consultas",
        "playbookType": "ROUTINE",
        "tokenCount": 5440,
        "referencedTools": [f"{AGENT_PATH}/tools/t-petaldata"],
        "inputParameterDefinitions": [
            {"name": "id_cliente", "type": "STRING"},
            {"name": "nombre_cliente", "type": "STRING"},
        ],
        "outputParameterDefinitions": [
            {"name": "producto", "type": "STRING"},
        ],
        "instruction": {
            "steps": [
                {"text": "IDENTIDAD DEL AGENTE\nEres Petal, asistente."},
            ],
        },
        "createTime": "2026-05-01T00:00:00Z",
    }
    local = cx_to_local(remote)
    result = diff_resource(local, remote, ignore_fields=PLAYBOOK_IGNORE_FIELDS)
    assert result.needs_update is False, (
        f"Round-trip dirty: mask={result.update_mask}, payload={result.patch_payload}"
    )


def test_round_trip_handoff_zero_tools():
    """Round-trip para Handoff (0 referencedTools, sin params output)."""
    remote = {
        "name": f"{AGENT_PATH}/playbooks/p-handoff",
        "displayName": "Handoff",
        "goal": "escalado a humano",
        "playbookType": "ROUTINE",
        "tokenCount": 467,
        "inputParameterDefinitions": [{"name": "razon_handoff", "type": "STRING"}],
        "instruction": {"steps": [{"text": "Eres Alicia, gestora."}]},
    }
    local = cx_to_local(remote)
    result = diff_resource(local, remote, ignore_fields=PLAYBOOK_IGNORE_FIELDS)
    assert result.needs_update is False


def test_round_trip_with_multiline_instruction():
    """Round-trip para playbook con instruction.steps de >1000 chars."""
    long_step = "PARRAFO\n" * 200  # ~1600 chars
    remote = {
        "name": f"{AGENT_PATH}/playbooks/p-x",
        "displayName": "X",
        "goal": "g",
        "playbookType": "ROUTINE",
        "tokenCount": 999,
        "instruction": {"steps": [{"text": long_step}]},
    }
    local = cx_to_local(remote)
    # El dump produces literal block; reload it and diff stays clean
    text = dump_yaml(local)
    reloaded = yaml.safe_load(text)
    result = diff_resource(reloaded, remote, ignore_fields=PLAYBOOK_IGNORE_FIELDS)
    assert result.needs_update is False
