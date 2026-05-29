"""Tests unitarios para act/push_generators.py.

Sin red. Sin auth. Mock de `requests.get/post/patch`. Cubre los 4
casos del brief: created, unchanged, updated, error 4xx + dry-run.
"""

from __future__ import annotations

import textwrap
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from act.push_generators import (
    GENERATOR_IGNORE_FIELDS,
    create_generator,
    discover_generator_files,
    get_generator,
    list_generators,
    load_generator_yaml,
    patch_generator,
    upsert_generator,
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
# list_generators
# ============================================================
def test_list_generators_paginates():
    pages = [
        {"generators": [{"name": "g/1", "displayName": "A"}], "nextPageToken": "t1"},
        {"generators": [{"name": "g/2", "displayName": "B"}]},
    ]
    with patch("act.push_generators.requests.get") as mg:
        mg.side_effect = [_resp(200, p) for p in pages]
        result = list_generators(CFG, HEADERS)
    assert len(result) == 2


def test_list_generators_4xx_raises():
    with patch("act.push_generators.requests.get") as mg:
        mg.return_value = _resp(500, text="boom")
        with pytest.raises(RuntimeError, match="LIST /generators"):
            list_generators(CFG, HEADERS)


# ============================================================
# upsert_generator — los 4 casos del brief
# ============================================================
def test_upsert_generator_created_when_missing():
    body = {
        "displayName": "NewGen",
        "promptText": {"text": "Hola $usuario"},
        "modelParameter": {"model": "gemini-1.5-flash"},
    }
    with patch("act.push_generators.requests.post") as mp:
        mp.return_value = _resp(200, {})
        action = upsert_generator(CFG, HEADERS, body, {}, dry_run=False)
    assert action == "created"


def test_upsert_generator_unchanged():
    body = {
        "displayName": "Gen1",
        "promptText": {"text": "Hola $u"},
        "modelParameter": {"model": "gemini-1.5-flash", "temperature": 0.2},
    }
    full_remote = {
        "name": "g/1",
        "displayName": "Gen1",
        "promptText": {"text": "Hola $u"},
        "modelParameter": {"model": "gemini-1.5-flash", "temperature": 0.2},
        "createTime": "2026-05-01T00:00:00Z",
    }
    existing = {"Gen1": {"name": "g/1", "displayName": "Gen1"}}
    with patch("act.push_generators.requests.get") as mg, \
         patch("act.push_generators.requests.patch") as mpa, \
         patch("act.push_generators.requests.post") as mp:
        mg.return_value = _resp(200, full_remote)
        action = upsert_generator(CFG, HEADERS, body, existing, dry_run=False)
    assert action == "unchanged"
    mp.assert_not_called()
    mpa.assert_not_called()


def test_upsert_generator_updated_when_temp_changes():
    body = {
        "displayName": "Gen1",
        "promptText": {"text": "Hola"},
        "modelParameter": {"temperature": 0.7},
    }
    full_remote = {
        "name": "g/1",
        "displayName": "Gen1",
        "promptText": {"text": "Hola"},
        "modelParameter": {"temperature": 0.2},
    }
    existing = {"Gen1": {"name": "g/1", "displayName": "Gen1"}}
    with patch("act.push_generators.requests.get") as mg, \
         patch("act.push_generators.requests.patch") as mpa:
        mg.return_value = _resp(200, full_remote)
        mpa.return_value = _resp(200, {})
        action = upsert_generator(CFG, HEADERS, body, existing, dry_run=False)
    assert action == "updated"
    kwargs = mpa.call_args.kwargs
    assert "modelParameter.temperature" in kwargs["params"]["updateMask"]


def test_upsert_generator_post_4xx_returns_failed():
    with patch("act.push_generators.requests.post") as mp:
        mp.return_value = _resp(400, text="bad")
        action = upsert_generator(
            CFG, HEADERS, {"displayName": "BadG"}, {}, dry_run=False,
        )
    assert action == "failed"


def test_upsert_generator_patch_4xx_returns_failed():
    body = {"displayName": "G1", "promptText": {"text": "new"}}
    full_remote = {"name": "g/1", "displayName": "G1", "promptText": {"text": "old"}}
    existing = {"G1": {"name": "g/1", "displayName": "G1"}}
    with patch("act.push_generators.requests.get") as mg, \
         patch("act.push_generators.requests.patch") as mpa:
        mg.return_value = _resp(200, full_remote)
        mpa.return_value = _resp(400, text="bad mask")
        action = upsert_generator(CFG, HEADERS, body, existing, dry_run=False)
    assert action == "failed"


def test_upsert_generator_get_4xx_returns_failed():
    body = {"displayName": "G1"}
    existing = {"G1": {"name": "g/1", "displayName": "G1"}}
    with patch("act.push_generators.requests.get") as mg:
        mg.return_value = _resp(403, text="forbidden")
        action = upsert_generator(CFG, HEADERS, body, existing, dry_run=False)
    assert action == "failed"


def test_upsert_generator_dry_run_skips_post():
    with patch("act.push_generators.requests.post") as mp:
        action = upsert_generator(
            CFG, HEADERS, {"displayName": "X"}, {}, dry_run=True,
        )
    assert action == "created"
    mp.assert_not_called()


def test_upsert_generator_promptText_with_placeholders_round_trip():
    """promptText con placeholders ($variable) debe pasar como esta."""
    body = {
        "displayName": "G",
        "promptText": {"text": "Hola $usuario, sobre $tema"},
        "placeholders": [
            {"id": "usuario", "name": "usuario"},
            {"id": "tema", "name": "tema"},
        ],
    }
    with patch("act.push_generators.requests.post") as mp:
        mp.return_value = _resp(200, {})
        upsert_generator(CFG, HEADERS, body, {}, dry_run=False)
    sent = mp.call_args.kwargs["json"]
    assert sent["promptText"]["text"] == "Hola $usuario, sobre $tema"
    assert len(sent["placeholders"]) == 2


# ============================================================
# load_generator_yaml + helpers
# ============================================================
def test_load_generator_yaml_ok(tmp_path: Path):
    yaml_content = textwrap.dedent("""
        displayName: G1
        promptText:
          text: hola
    """).strip()
    fp = tmp_path / "g.yaml"
    fp.write_text(yaml_content)
    body = load_generator_yaml(fp)
    assert body["displayName"] == "G1"


def test_load_generator_yaml_missing_displayname_raises(tmp_path: Path):
    fp = tmp_path / "bad.yaml"
    fp.write_text("promptText:\n  text: x\n")
    with pytest.raises(ValueError, match="displayName"):
        load_generator_yaml(fp)


def test_load_generator_yaml_non_dict_raises(tmp_path: Path):
    fp = tmp_path / "list.yaml"
    fp.write_text("- a\n- b\n")
    with pytest.raises(ValueError, match="dict"):
        load_generator_yaml(fp)


# ============================================================
# Constantes y helpers
# ============================================================
def test_generator_ignore_fields():
    for field in ("name", "createTime", "updateTime"):
        assert field in GENERATOR_IGNORE_FIELDS


def test_get_generator_returns_body():
    full = {"name": "g/1", "displayName": "G"}
    with patch("act.push_generators.requests.get") as mg:
        mg.return_value = _resp(200, full)
        assert get_generator(CFG, HEADERS, "g/1") == full


def test_get_generator_4xx_raises():
    with patch("act.push_generators.requests.get") as mg:
        mg.return_value = _resp(404, text="nf")
        with pytest.raises(RuntimeError, match="GET .* fallo"):
            get_generator(CFG, HEADERS, "g/missing")


def test_create_and_patch_dry_run_helpers():
    with patch("act.push_generators.requests.post") as mp, \
         patch("act.push_generators.requests.patch") as mpa:
        assert create_generator(CFG, HEADERS, {"displayName": "X"}, dry_run=True) is True
        assert patch_generator(
            CFG, HEADERS, name="g/x",
            payload={"x": 1}, update_mask=["x"], dry_run=True,
        ) is True
    mp.assert_not_called()
    mpa.assert_not_called()


def test_discover_generator_files_returns_list():
    assert isinstance(discover_generator_files(), list)
