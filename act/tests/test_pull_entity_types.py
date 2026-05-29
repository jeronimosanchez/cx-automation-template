"""Tests unitarios para act/pull_entity_types.py.

Sin red. Sin auth. Cubre cx_to_local (strip + order), slugify,
dump_yaml + round-trip mock vs push_entity_types.diff_resource.
"""
from __future__ import annotations

import pytest
import yaml

from act.diff import diff_resource
from act.pull_entity_types import (
    PULL_STRIP_FIELDS,
    _CANONICAL_ORDER,
    cx_to_local,
    dump_yaml,
    slugify,
)
from act.push_entity_types import ENTITY_TYPE_IGNORE_FIELDS


AGENT_PATH = "projects/test-project/locations/europe-west1/agents/agent-uuid"


# ============================================================
# cx_to_local — strip read-only + reorder
# ============================================================
def test_cx_to_local_strips_readonly_fields():
    remote = {
        "name": f"{AGENT_PATH}/entityTypes/et-1",
        "displayName": "Color",
        "kind": "KIND_MAP",
        "entities": [{"value": "rojo", "synonyms": ["rojo", "red"]}],
        "createTime": "2026-05-01T00:00:00Z",
        "updateTime": "2026-05-02T00:00:00Z",
    }
    local = cx_to_local(remote)
    for f in PULL_STRIP_FIELDS:
        assert f not in local, f"{f} debio ser strippeado"
    assert local["displayName"] == "Color"
    assert local["kind"] == "KIND_MAP"
    assert local["entities"] == remote["entities"]


def test_cx_to_local_preserves_unknown_fields():
    """Si CX agrega un campo nuevo, lo preservamos para forward-compat."""
    remote = {"displayName": "X", "kind": "KIND_MAP", "newFutureField": 42}
    local = cx_to_local(remote)
    assert local["newFutureField"] == 42


def test_cx_to_local_emits_canonical_order():
    """displayName y kind primero; entities despues; lo desconocido al final."""
    remote = {
        "entities": [],
        "kind": "KIND_LIST",
        "displayName": "Z",
        "redact": False,
        "newField": 1,
    }
    keys = list(cx_to_local(remote).keys())
    assert keys.index("displayName") < keys.index("kind")
    assert keys.index("kind") < keys.index("entities")
    # 'redact' es canonico tambien (esta en _CANONICAL_ORDER)
    assert "redact" in _CANONICAL_ORDER
    # newField (no canonico) va al final
    assert keys[-1] == "newField"


@pytest.mark.parametrize("kind,entities", [
    ("KIND_MAP", [{"value": "rojo", "synonyms": ["rojo", "red"]}]),
    ("KIND_LIST", [{"value": "alfa"}, {"value": "beta"}]),
    ("KIND_REGEXP", [{"value": "[A-Z]{3}-[0-9]{4}"}]),
])
def test_cx_to_local_supports_three_kinds(kind, entities):
    """Los 3 kinds de Entity Type se preservan en el output."""
    remote = {
        "name": f"{AGENT_PATH}/entityTypes/et-x",
        "displayName": f"Test_{kind}",
        "kind": kind,
        "entities": entities,
    }
    local = cx_to_local(remote)
    assert local["kind"] == kind
    assert local["entities"] == entities


# ============================================================
# slugify — generacion de nombres de fichero
# ============================================================
@pytest.mark.parametrize("display_name,expected", [
    ("Color", "color"),
    ("Producto Floral", "producto_floral"),
    ("Email/Phone", "email_phone"),
    ("Nombre con Acentos áéí", "nombre_con_acentos"),  # trailing _ stripped
    ("  trim me  ", "trim_me"),
    ("UPPER_case-with.dots", "upper_case-with.dots"),
])
def test_slugify_variations(display_name, expected):
    assert slugify(display_name) == expected


def test_slugify_fallback_when_empty():
    assert slugify("") == "unnamed"
    assert slugify("!!!") == "unnamed"
    assert slugify("___") == "unnamed"


# ============================================================
# dump_yaml — output valido y re-cargable
# ============================================================
def test_dump_yaml_roundtrip_via_pyyaml():
    body = {
        "displayName": "Color",
        "kind": "KIND_MAP",
        "entities": [{"value": "rojo", "synonyms": ["rojo", "red"]}],
    }
    text = dump_yaml(body)
    reloaded = yaml.safe_load(text)
    assert reloaded == body


def test_dump_yaml_preserves_key_order():
    body = {"displayName": "X", "kind": "KIND_LIST", "entities": []}
    text = dump_yaml(body)
    # displayName aparece antes que kind, kind antes que entities
    assert text.index("displayName") < text.index("kind")
    assert text.index("kind") < text.index("entities")


# ============================================================
# Round-trip end-to-end (con mocks)
# ============================================================
def test_round_trip_pull_to_push_reports_unchanged():
    """cx_to_local(remote) -> diff vs remote == no-op.

    Garantiza que un YAML pulleado, cuando push_entity_types lo lea de vuelta
    y lo diffee contra CX, reporta unchanged.
    """
    remote = {
        "name": f"{AGENT_PATH}/entityTypes/et-1",
        "displayName": "Color",
        "kind": "KIND_MAP",
        "entities": [{"value": "rojo", "synonyms": ["rojo", "red"]}],
        "createTime": "2026-05-01T00:00:00Z",
    }
    local = cx_to_local(remote)
    result = diff_resource(local, remote, ignore_fields=ENTITY_TYPE_IGNORE_FIELDS)
    assert result.needs_update is False, (
        f"Round-trip dirty: mask={result.update_mask}, payload={result.patch_payload}"
    )


def test_round_trip_for_each_kind():
    """Mismo round-trip para los 3 kinds: KIND_MAP, KIND_LIST, KIND_REGEXP."""
    fixtures = [
        ("KIND_MAP", [{"value": "rojo", "synonyms": ["rojo", "red"]}]),
        ("KIND_LIST", [{"value": "a"}, {"value": "b"}]),
        ("KIND_REGEXP", [{"value": "[0-9]{4}"}]),
    ]
    for kind, entities in fixtures:
        remote = {
            "name": f"{AGENT_PATH}/entityTypes/et-{kind}",
            "displayName": f"ET_{kind}",
            "kind": kind,
            "entities": entities,
            "createTime": "2026-05-01T00:00:00Z",
        }
        local = cx_to_local(remote)
        result = diff_resource(local, remote, ignore_fields=ENTITY_TYPE_IGNORE_FIELDS)
        assert result.needs_update is False, f"Round-trip dirty para {kind}"
