"""Tests unitarios para src/push_intents.py.

Sin red. Sin auth. Mock de `requests.get/post/patch`. Cubre los 4
casos del brief + escenario especifico: training phrases con
annotations preservadas en el diff.
"""

from __future__ import annotations

import textwrap
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.push_intents import (
    INTENT_IGNORE_FIELDS,
    create_intent,
    discover_intent_files,
    get_intent,
    list_intents,
    load_intent_yaml,
    patch_intent,
    upsert_intent,
)


CFG = {
    "project": "test-project",
    "location": "europe-west1",
    "agent_id": "agent-uuid",
    "api": {
        "base_v3beta1": "https://example.test/v3beta1",
        "required_headers": {"x-goog-user-project": "test-project"},
    },
}
HEADERS = {"Authorization": "Bearer fake"}


def _resp(status=200, json_data=None, text=""):
    m = MagicMock()
    m.status_code = status
    m.json.return_value = json_data or {}
    m.text = text
    return m


# ============================================================
# list_intents — paginacion y errores
# ============================================================
def test_list_intents_paginates():
    pages = [
        {"intents": [{"name": "i/1", "displayName": "A"}], "nextPageToken": "t1"},
        {"intents": [{"name": "i/2", "displayName": "B"}]},
    ]
    with patch("src.push_intents.requests.get") as mg:
        mg.side_effect = [_resp(200, p) for p in pages]
        result = list_intents(CFG, HEADERS)
    assert len(result) == 2


def test_list_intents_4xx_raises():
    with patch("src.push_intents.requests.get") as mg:
        mg.return_value = _resp(500, text="boom")
        with pytest.raises(RuntimeError, match="LIST /intents"):
            list_intents(CFG, HEADERS)


# ============================================================
# upsert_intent — los 4 casos del brief
# ============================================================
def test_upsert_intent_created_when_missing():
    body = {"displayName": "NewIntent", "trainingPhrases": []}
    with patch("src.push_intents.requests.post") as mp:
        mp.return_value = _resp(200, {})
        action = upsert_intent(CFG, HEADERS, body, {}, dry_run=False)
    assert action == "created"
    mp.assert_called_once()


def test_upsert_intent_unchanged_when_match():
    body = {
        "displayName": "I1",
        "trainingPhrases": [{"parts": [{"text": "hola"}]}],
        "priority": 500000,
    }
    full_remote = {
        "name": "projects/.../intents/i-uuid",
        "displayName": "I1",
        "trainingPhrases": [{"parts": [{"text": "hola"}]}],
        "priority": 500000,
        "createTime": "2026-05-01T00:00:00Z",
    }
    existing = {"I1": {"name": full_remote["name"], "displayName": "I1"}}
    with patch("src.push_intents.requests.get") as mg, \
         patch("src.push_intents.requests.patch") as mpa, \
         patch("src.push_intents.requests.post") as mp:
        mg.return_value = _resp(200, full_remote)
        action = upsert_intent(CFG, HEADERS, body, existing, dry_run=False)
    assert action == "unchanged"
    mp.assert_not_called()
    mpa.assert_not_called()


def test_upsert_intent_updated_when_diff():
    body = {"displayName": "I1", "priority": 600000}
    full_remote = {"name": "i/1", "displayName": "I1", "priority": 500000}
    existing = {"I1": {"name": "i/1", "displayName": "I1"}}
    with patch("src.push_intents.requests.get") as mg, \
         patch("src.push_intents.requests.patch") as mpa:
        mg.return_value = _resp(200, full_remote)
        mpa.return_value = _resp(200, {})
        action = upsert_intent(CFG, HEADERS, body, existing, dry_run=False)
    assert action == "updated"
    mpa.assert_called_once()
    kwargs = mpa.call_args.kwargs
    assert "priority" in kwargs["params"]["updateMask"]


def test_upsert_intent_post_4xx_returns_failed():
    with patch("src.push_intents.requests.post") as mp:
        mp.return_value = _resp(400, text="bad")
        action = upsert_intent(
            CFG, HEADERS, {"displayName": "BadI"}, {}, dry_run=False,
        )
    assert action == "failed"


def test_upsert_intent_patch_4xx_returns_failed():
    body = {"displayName": "I1", "priority": 1}
    full_remote = {"name": "i/1", "displayName": "I1", "priority": 2}
    existing = {"I1": {"name": "i/1", "displayName": "I1"}}
    with patch("src.push_intents.requests.get") as mg, \
         patch("src.push_intents.requests.patch") as mpa:
        mg.return_value = _resp(200, full_remote)
        mpa.return_value = _resp(400, text="bad mask")
        action = upsert_intent(CFG, HEADERS, body, existing, dry_run=False)
    assert action == "failed"


def test_upsert_intent_dry_run_skips_post():
    with patch("src.push_intents.requests.post") as mp:
        action = upsert_intent(
            CFG, HEADERS, {"displayName": "X"}, {}, dry_run=True,
        )
    assert action == "created"
    mp.assert_not_called()


# ============================================================
# Escenario especifico del brief: training phrases con annotations
# (parts con parameterId) deben preservarse en el diff.
# ============================================================
def _annotated_training_phrases():
    """Estructura mixta: texto plano + parts con parameterId."""
    return [
        {
            "parts": [
                {"text": "Hola, soy "},
                {"text": "Jero", "parameterId": "nombre_usuario"},
            ],
            "repeatCount": 1,
        }
    ]


def test_intent_annotated_phrases_unchanged_round_trip():
    """Si remote == local con annotations, el diff es vacio."""
    body = {
        "displayName": "Greeting",
        "trainingPhrases": _annotated_training_phrases(),
        "parameters": [
            {"id": "nombre_usuario", "entityType": "sys.person", "isList": False},
        ],
    }
    full_remote = {
        "name": "projects/.../intents/i-uuid",
        "displayName": "Greeting",
        "trainingPhrases": _annotated_training_phrases(),
        "parameters": [
            {"id": "nombre_usuario", "entityType": "sys.person", "isList": False},
        ],
    }
    existing = {"Greeting": {"name": full_remote["name"], "displayName": "Greeting"}}
    with patch("src.push_intents.requests.get") as mg, \
         patch("src.push_intents.requests.patch") as mpa:
        mg.return_value = _resp(200, full_remote)
        action = upsert_intent(CFG, HEADERS, body, existing, dry_run=False)
    assert action == "unchanged"
    mpa.assert_not_called()


def test_intent_annotated_phrases_diff_detected():
    """Si una annotation cambia, el PATCH se dispara con la lista entera."""
    local_phrases = _annotated_training_phrases()
    remote_phrases = [
        {
            "parts": [
                {"text": "Hola, soy "},
                {"text": "OtroNombre", "parameterId": "nombre_usuario"},
            ],
            "repeatCount": 1,
        }
    ]
    body = {"displayName": "Greeting", "trainingPhrases": local_phrases}
    full_remote = {
        "name": "i/1",
        "displayName": "Greeting",
        "trainingPhrases": remote_phrases,
    }
    existing = {"Greeting": {"name": "i/1", "displayName": "Greeting"}}
    with patch("src.push_intents.requests.get") as mg, \
         patch("src.push_intents.requests.patch") as mpa:
        mg.return_value = _resp(200, full_remote)
        mpa.return_value = _resp(200, {})
        action = upsert_intent(CFG, HEADERS, body, existing, dry_run=False)
    assert action == "updated"
    kwargs = mpa.call_args.kwargs
    # La lista entera entra al mask bajo su path padre (orden importa).
    assert "trainingPhrases" in kwargs["params"]["updateMask"]
    # El payload preserva la annotation parameterId.
    sent = kwargs["json"]["trainingPhrases"]
    assert sent[0]["parts"][1]["parameterId"] == "nombre_usuario"


# ============================================================
# load_intent_yaml + helpers
# ============================================================
def test_load_intent_yaml_ok(tmp_path: Path):
    yaml_content = textwrap.dedent("""
        displayName: I1
        trainingPhrases:
          - parts:
              - text: hola
    """).strip()
    fp = tmp_path / "i.yaml"
    fp.write_text(yaml_content)
    body = load_intent_yaml(fp)
    assert body["displayName"] == "I1"


def test_load_intent_yaml_missing_displayname_raises(tmp_path: Path):
    fp = tmp_path / "bad.yaml"
    fp.write_text("trainingPhrases: []\n")
    with pytest.raises(ValueError, match="displayName"):
        load_intent_yaml(fp)


def test_intent_ignore_fields():
    for field in ("name", "createTime", "updateTime"):
        assert field in INTENT_IGNORE_FIELDS


def test_get_intent_returns_body():
    full = {"name": "i/1", "displayName": "I"}
    with patch("src.push_intents.requests.get") as mg:
        mg.return_value = _resp(200, full)
        assert get_intent(CFG, HEADERS, "i/1") == full


def test_get_intent_4xx_raises():
    with patch("src.push_intents.requests.get") as mg:
        mg.return_value = _resp(404, text="nf")
        with pytest.raises(RuntimeError, match="GET .* fallo"):
            get_intent(CFG, HEADERS, "i/missing")


def test_create_and_patch_dry_run_helpers():
    with patch("src.push_intents.requests.post") as mp, \
         patch("src.push_intents.requests.patch") as mpa:
        assert create_intent(CFG, HEADERS, {"displayName": "X"}, dry_run=True) is True
        assert patch_intent(
            CFG, HEADERS, name="i/x",
            payload={"priority": 1}, update_mask=["priority"], dry_run=True,
        ) is True
    mp.assert_not_called()
    mpa.assert_not_called()


def test_discover_intent_files_returns_list():
    assert isinstance(discover_intent_files(), list)
