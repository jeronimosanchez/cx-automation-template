"""Tests unitarios para src/pull_versions.py.

Sin red. Cubre cx_to_local (strip + id + flow_displayName), slugify,
manifest-friendly layout (subcarpetas por flow), y verifica que el
manifest preserva read-only informativos (state, createTime, nluSettings)
en lugar de strippearlos.

NO hay test de round-trip porque Versions son inmutables (POST crea
nueva, no hay PATCH).
"""
from __future__ import annotations

import pytest
import yaml

from src.pull_versions import (
    PULL_STRIP_FIELDS,
    _CANONICAL_ORDER,
    cx_to_local,
    dump_yaml,
    slugify,
)


AGENT_PATH = "projects/test-project/locations/europe-west1/agents/agent-uuid"
FLOW_PATH = f"{AGENT_PATH}/flows/flow-default"
VERSION_PATH = f"{FLOW_PATH}/versions/5"


# ============================================================
# cx_to_local — strip 'name' -> 'id', inject flow_displayName,
# preserve read-only informativos
# ============================================================
def test_cx_to_local_extracts_id_from_name():
    remote = {
        "name": VERSION_PATH,
        "displayName": "ci-8",
        "state": "SUCCEEDED",
    }
    local = cx_to_local(remote, parent_flow_display_name="Default Start Flow")
    assert "name" not in local
    assert local["id"] == "5"
    assert local["flow_displayName"] == "Default Start Flow"


def test_cx_to_local_preserves_state_createTime_nluSettings():
    """Las versions persisten read-only informativos (no se strippean
    como en otros recursos). Son metadata util para el manifest."""
    remote = {
        "name": VERSION_PATH,
        "displayName": "ci-8",
        "description": "Auto deploy abc123",
        "state": "SUCCEEDED",
        "createTime": "2026-05-12T14:49:02.616640Z",
        "nluSettings": {"modelType": "MODEL_TYPE_ADVANCED", "classificationThreshold": 0.3},
    }
    local = cx_to_local(remote, parent_flow_display_name="Default Start Flow")
    assert local["state"] == "SUCCEEDED"
    assert local["createTime"] == "2026-05-12T14:49:02.616640Z"
    assert local["nluSettings"]["modelType"] == "MODEL_TYPE_ADVANCED"
    assert local["description"] == "Auto deploy abc123"


def test_cx_to_local_canonical_order():
    """flow_displayName y id van primero (local-only); luego body."""
    remote = {
        "nluSettings": {},
        "createTime": "2026-01-01",
        "state": "SUCCEEDED",
        "description": "d",
        "displayName": "v1",
        "name": f"{FLOW_PATH}/versions/3",
        "newFutureField": 99,
    }
    keys = list(cx_to_local(remote, parent_flow_display_name="F").keys())
    assert keys[0] == "flow_displayName"
    assert keys[1] == "id"
    assert keys.index("displayName") < keys.index("description")
    assert keys.index("description") < keys.index("state")
    assert keys.index("state") < keys.index("createTime")
    assert keys.index("createTime") < keys.index("nluSettings")
    assert keys[-1] == "newFutureField"


def test_cx_to_local_preserves_unknown_fields():
    remote = {"name": VERSION_PATH, "displayName": "v1", "newFutureField": 42}
    local = cx_to_local(remote, parent_flow_display_name="F")
    assert local["newFutureField"] == 42


def test_pull_strip_fields_only_strips_name():
    """A diferencia de los otros pulls (que strippean createTime/updateTime),
    versions solo strippea 'name'. El resto es metadata informativa
    valida para el manifest."""
    assert PULL_STRIP_FIELDS == ("name",)
    assert "createTime" not in PULL_STRIP_FIELDS
    assert "state" not in PULL_STRIP_FIELDS


# ============================================================
# slugify — versions tienen displayNames como "ci-8", "v1.0.0"
# ============================================================
@pytest.mark.parametrize("display_name,expected", [
    ("ci-8", "ci-8"),
    ("ci-6", "ci-6"),
    ("v1.0.0", "v1.0.0"),
    ("Release 2024-Q1", "release_2024-q1"),
])
def test_slugify_version_naming(display_name, expected):
    assert slugify(display_name) == expected


# ============================================================
# Dumper — output valido y re-cargable
# ============================================================
def test_dump_yaml_roundtrip_via_pyyaml():
    body = {
        "flow_displayName": "Default Start Flow",
        "id": "5",
        "displayName": "ci-8",
        "description": "Auto deploy abc123def456",
        "state": "SUCCEEDED",
        "createTime": "2026-05-12T14:49:02.616640Z",
        "nluSettings": {
            "modelType": "MODEL_TYPE_ADVANCED",
            "classificationThreshold": 0.3,
        },
    }
    text = dump_yaml(body)
    reloaded = yaml.safe_load(text)
    assert reloaded == body


def test_dump_yaml_preserves_key_order():
    body = {
        "flow_displayName": "F",
        "id": "5",
        "displayName": "v1",
        "state": "SUCCEEDED",
        "createTime": "2026-01-01",
    }
    text = dump_yaml(body)
    # Buscar por linea completa para evitar colision de substring
    # (displayName es substring de flow_displayName).
    assert text.index("flow_displayName:") < text.index("\nid:")
    assert text.index("\nid:") < text.index("\ndisplayName:")
    assert text.index("\ndisplayName:") < text.index("\nstate:")
    assert text.index("\nstate:") < text.index("\ncreateTime:")


# ============================================================
# Conceptual: manifest-only — NO round-trip
# ============================================================
def test_canonical_order_omits_round_trip_specific_fields():
    """El _CANONICAL_ORDER incluye campos informativos (state, createTime,
    nluSettings) que son IRRELEVANTES para round-trip (push los ignoraria
    porque CX los rechaza como input). Sirven para auditoria del manifest."""
    informative_fields = {"state", "createTime", "nluSettings"}
    assert informative_fields.issubset(set(_CANONICAL_ORDER))
