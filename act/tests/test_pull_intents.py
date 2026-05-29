"""Tests unitarios para act/pull_intents.py.

Sin red. Sin auth. Cubre cx_to_local (strip + order + annotations),
slugify, dump_yaml + round-trip mock vs push_intents.diff_resource.
"""
from __future__ import annotations

import pytest
import yaml

from act.diff import diff_resource
from act.pull_intents import (
    PULL_STRIP_FIELDS,
    _CANONICAL_ORDER,
    cx_to_local,
    dump_yaml,
    slugify,
)
from act.push_intents import INTENT_IGNORE_FIELDS


AGENT_PATH = "projects/test-project/locations/europe-west1/agents/agent-uuid"


# ============================================================
# cx_to_local — strip read-only + reorder
# ============================================================
def test_cx_to_local_strips_readonly_fields():
    remote = {
        "name": f"{AGENT_PATH}/intents/i-1",
        "displayName": "Default Welcome Intent",
        "trainingPhrases": [{"parts": [{"text": "hola"}]}],
        "createTime": "2026-05-01T00:00:00Z",
        "updateTime": "2026-05-02T00:00:00Z",
    }
    local = cx_to_local(remote)
    for f in PULL_STRIP_FIELDS:
        assert f not in local, f"{f} debio ser strippeado"
    assert local["displayName"] == "Default Welcome Intent"
    assert local["trainingPhrases"] == remote["trainingPhrases"]


def test_cx_to_local_preserves_unknown_fields():
    remote = {"displayName": "X", "newFutureField": {"foo": 1}}
    local = cx_to_local(remote)
    assert local["newFutureField"] == {"foo": 1}


def test_cx_to_local_emits_canonical_order():
    """displayName primero; lo desconocido al final."""
    remote = {
        "parameters": [],
        "trainingPhrases": [],
        "priority": 500000,
        "displayName": "I1",
        "isFallback": False,
        "newField": 1,
    }
    keys = list(cx_to_local(remote).keys())
    assert keys.index("displayName") < keys.index("priority")
    assert keys.index("priority") < keys.index("isFallback")
    assert keys.index("isFallback") < keys.index("trainingPhrases")
    assert keys.index("trainingPhrases") < keys.index("parameters")
    # newField (no canonico) al final
    assert keys[-1] == "newField"


def test_cx_to_local_preserves_training_phrases_annotations():
    """Las parts con parameterId (annotations) deben preservarse intactas."""
    remote = {
        "name": f"{AGENT_PATH}/intents/i-greet",
        "displayName": "Greeting",
        "trainingPhrases": [
            {
                "parts": [
                    {"text": "Hola, soy "},
                    {"text": "Jero", "parameterId": "nombre_usuario"},
                ],
                "repeatCount": 1,
            }
        ],
        "parameters": [
            {"id": "nombre_usuario", "entityType": "sys.person", "isList": False},
        ],
    }
    local = cx_to_local(remote)
    parts = local["trainingPhrases"][0]["parts"]
    assert parts[0] == {"text": "Hola, soy "}
    assert parts[1] == {"text": "Jero", "parameterId": "nombre_usuario"}
    assert local["parameters"][0]["id"] == "nombre_usuario"


def test_cx_to_local_empty_intent_no_phrases():
    """Caso Default Negative Intent: sin trainingPhrases."""
    remote = {
        "name": f"{AGENT_PATH}/intents/i-neg",
        "displayName": "Default Negative Intent",
    }
    local = cx_to_local(remote)
    assert local == {"displayName": "Default Negative Intent"}


# ============================================================
# slugify — generacion de nombres de fichero
# ============================================================
@pytest.mark.parametrize("display_name,expected", [
    ("Default Welcome Intent", "default_welcome_intent"),
    ("Default Negative Intent", "default_negative_intent"),
    ("Intent/With/Slashes", "intent_with_slashes"),
    ("  trim me  ", "trim_me"),
    ("UPPER_case-with.dots", "upper_case-with.dots"),
])
def test_slugify_variations(display_name, expected):
    assert slugify(display_name) == expected


def test_slugify_fallback_when_empty():
    assert slugify("") == "unnamed"
    assert slugify("___") == "unnamed"


# ============================================================
# dump_yaml — output valido y re-cargable
# ============================================================
def test_dump_yaml_roundtrip_via_pyyaml():
    body = {
        "displayName": "I1",
        "trainingPhrases": [{"parts": [{"text": "hola"}]}],
        "priority": 500000,
    }
    text = dump_yaml(body)
    reloaded = yaml.safe_load(text)
    assert reloaded == body


def test_dump_yaml_preserves_spanish_characters():
    """Los training phrases en espanol no deben escaparse a \\uXXXX."""
    body = {
        "displayName": "Saludo",
        "trainingPhrases": [{"parts": [{"text": "¡Hola! ¿Cómo estás?"}]}],
    }
    text = dump_yaml(body)
    # allow_unicode=True debe preservar los caracteres UTF-8 tal cual.
    assert "¡Hola!" in text
    assert "¿Cómo estás?" in text
    assert "\\u" not in text


def test_dump_yaml_preserves_key_order():
    body = {"displayName": "X", "priority": 500000, "trainingPhrases": []}
    text = dump_yaml(body)
    assert text.index("displayName") < text.index("priority")
    assert text.index("priority") < text.index("trainingPhrases")


# ============================================================
# Round-trip end-to-end (con mocks)
# ============================================================
def test_round_trip_pull_to_push_reports_unchanged():
    """cx_to_local(remote) -> diff vs remote == no-op."""
    remote = {
        "name": f"{AGENT_PATH}/intents/i-welcome",
        "displayName": "Default Welcome Intent",
        "trainingPhrases": [
            {"parts": [{"text": "hola"}]},
            {"parts": [{"text": "hey"}]},
            {"parts": [{"text": "saludos"}]},
        ],
        "createTime": "2026-05-01T00:00:00Z",
    }
    local = cx_to_local(remote)
    result = diff_resource(local, remote, ignore_fields=INTENT_IGNORE_FIELDS)
    assert result.needs_update is False, (
        f"Round-trip dirty: mask={result.update_mask}, payload={result.patch_payload}"
    )


def test_round_trip_with_annotations():
    """Round-trip clean cuando hay annotations (parts con parameterId)."""
    remote = {
        "name": f"{AGENT_PATH}/intents/i-greet",
        "displayName": "Greeting",
        "trainingPhrases": [
            {
                "parts": [
                    {"text": "Hola, soy "},
                    {"text": "Jero", "parameterId": "nombre_usuario"},
                ],
                "repeatCount": 1,
            }
        ],
        "parameters": [
            {"id": "nombre_usuario", "entityType": "sys.person", "isList": False},
        ],
    }
    local = cx_to_local(remote)
    result = diff_resource(local, remote, ignore_fields=INTENT_IGNORE_FIELDS)
    assert result.needs_update is False


def test_round_trip_empty_intent():
    """Round-trip clean para Default Negative Intent (sin trainingPhrases)."""
    remote = {
        "name": f"{AGENT_PATH}/intents/i-neg",
        "displayName": "Default Negative Intent",
    }
    local = cx_to_local(remote)
    result = diff_resource(local, remote, ignore_fields=INTENT_IGNORE_FIELDS)
    assert result.needs_update is False
