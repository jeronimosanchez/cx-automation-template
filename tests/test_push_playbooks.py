"""Tests unitarios para src/push_playbooks.py.

Sin red. Sin auth. Mock de `requests.get/post/patch`. Cubre los 4
casos exigidos por el brief: created, unchanged, updated, error 4xx.
"""

from __future__ import annotations

import textwrap
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.push_playbooks import (
    PLAYBOOK_IGNORE_FIELDS,
    create_playbook,
    discover_playbook_files,
    get_playbook,
    list_playbooks,
    load_playbook_yaml,
    patch_playbook,
    upsert_playbook,
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
# list_playbooks — paginacion y errores
# ============================================================
def test_list_playbooks_paginates():
    pages = [
        {"playbooks": [{"name": "pb/1", "displayName": "A"}], "nextPageToken": "t1"},
        {"playbooks": [{"name": "pb/2", "displayName": "B"}]},
    ]
    with patch("src.push_playbooks.requests.get") as mg:
        mg.side_effect = [_resp(200, p) for p in pages]
        result = list_playbooks(CFG, HEADERS)
    assert len(result) == 2
    assert mg.call_count == 2


def test_list_playbooks_4xx_raises():
    with patch("src.push_playbooks.requests.get") as mg:
        mg.return_value = _resp(500, text="Internal Server Error")
        with pytest.raises(RuntimeError, match="LIST /playbooks"):
            list_playbooks(CFG, HEADERS)


# ============================================================
# get_playbook — full body fetch
# ============================================================
def test_get_playbook_returns_body():
    full = {"name": "pb/1", "displayName": "A", "instruction": {"steps": [{"text": "..."}]}}
    with patch("src.push_playbooks.requests.get") as mg:
        mg.return_value = _resp(200, full)
        result = get_playbook(CFG, HEADERS, "pb/1")
    assert result == full


def test_get_playbook_4xx_raises():
    with patch("src.push_playbooks.requests.get") as mg:
        mg.return_value = _resp(404, text="Not Found")
        with pytest.raises(RuntimeError, match="GET .* fallo"):
            get_playbook(CFG, HEADERS, "pb/missing")


# ============================================================
# upsert_playbook — los 4 casos del brief
# ============================================================
def test_upsert_playbook_created_when_missing():
    body = {"displayName": "NewPB", "goal": "test", "playbookType": "ROUTINE"}
    existing = {}
    with patch("src.push_playbooks.requests.post") as mp:
        mp.return_value = _resp(200, {})
        action = upsert_playbook(CFG, HEADERS, body, existing, dry_run=False)
    assert action == "created"
    mp.assert_called_once()


def test_upsert_playbook_unchanged_when_match():
    body = {"displayName": "PB1", "goal": "X", "playbookType": "ROUTINE"}
    full_remote = {
        "name": "projects/.../playbooks/pb-uuid",
        "displayName": "PB1",
        "goal": "X",
        "playbookType": "ROUTINE",
        "tokenCount": "100",  # ignorado
    }
    existing_summary = {"PB1": {"name": full_remote["name"], "displayName": "PB1"}}
    with patch("src.push_playbooks.requests.get") as mg, \
         patch("src.push_playbooks.requests.patch") as mpa, \
         patch("src.push_playbooks.requests.post") as mp:
        mg.return_value = _resp(200, full_remote)
        action = upsert_playbook(CFG, HEADERS, body, existing_summary, dry_run=False)
    assert action == "unchanged"
    mp.assert_not_called()
    mpa.assert_not_called()


def test_upsert_playbook_updated_when_diff():
    body = {"displayName": "PB1", "goal": "NEW_GOAL", "playbookType": "ROUTINE"}
    full_remote = {
        "name": "projects/.../playbooks/pb-uuid",
        "displayName": "PB1",
        "goal": "OLD_GOAL",
        "playbookType": "ROUTINE",
    }
    existing_summary = {"PB1": {"name": full_remote["name"], "displayName": "PB1"}}
    with patch("src.push_playbooks.requests.get") as mg, \
         patch("src.push_playbooks.requests.patch") as mpa:
        mg.return_value = _resp(200, full_remote)
        mpa.return_value = _resp(200, {})
        action = upsert_playbook(CFG, HEADERS, body, existing_summary, dry_run=False)
    assert action == "updated"
    mpa.assert_called_once()
    kwargs = mpa.call_args.kwargs
    assert "goal" in kwargs["params"]["updateMask"]


def test_upsert_playbook_post_4xx_returns_failed():
    body = {"displayName": "BadPB", "playbookType": "ROUTINE"}
    with patch("src.push_playbooks.requests.post") as mp:
        mp.return_value = _resp(400, text="INVALID_ARGUMENT")
        action = upsert_playbook(CFG, HEADERS, body, {}, dry_run=False)
    assert action == "failed"


def test_upsert_playbook_patch_4xx_returns_failed():
    body = {"displayName": "PB1", "goal": "new"}
    full_remote = {"name": "pb/1", "displayName": "PB1", "goal": "old"}
    existing = {"PB1": {"name": "pb/1", "displayName": "PB1"}}
    with patch("src.push_playbooks.requests.get") as mg, \
         patch("src.push_playbooks.requests.patch") as mpa:
        mg.return_value = _resp(200, full_remote)
        mpa.return_value = _resp(400, text="bad mask")
        action = upsert_playbook(CFG, HEADERS, body, existing, dry_run=False)
    assert action == "failed"


def test_upsert_playbook_get_4xx_returns_failed():
    """Si el GET completo falla, el upsert reporta failed (no crash)."""
    body = {"displayName": "PB1", "goal": "x"}
    existing = {"PB1": {"name": "pb/1", "displayName": "PB1"}}
    with patch("src.push_playbooks.requests.get") as mg:
        mg.return_value = _resp(403, text="Forbidden")
        action = upsert_playbook(CFG, HEADERS, body, existing, dry_run=False)
    assert action == "failed"


# ============================================================
# Dry-run no llama a la red
# ============================================================
def test_upsert_playbook_dry_run_skips_post():
    body = {"displayName": "NewPB"}
    with patch("src.push_playbooks.requests.post") as mp:
        action = upsert_playbook(CFG, HEADERS, body, {}, dry_run=True)
    assert action == "created"
    mp.assert_not_called()


def test_upsert_playbook_dry_run_skips_patch():
    body = {"displayName": "PB1", "goal": "new"}
    full_remote = {"name": "pb/1", "displayName": "PB1", "goal": "old"}
    existing = {"PB1": {"name": "pb/1", "displayName": "PB1"}}
    with patch("src.push_playbooks.requests.get") as mg, \
         patch("src.push_playbooks.requests.patch") as mpa:
        mg.return_value = _resp(200, full_remote)
        action = upsert_playbook(CFG, HEADERS, body, existing, dry_run=True)
    assert action == "updated"
    mpa.assert_not_called()


# ============================================================
# load_playbook_yaml + discover
# ============================================================
def test_load_playbook_yaml_top_level_displayname(tmp_path: Path):
    yaml_content = textwrap.dedent("""
        displayName: TestPB
        goal: smoke
        playbookType: ROUTINE
    """).strip()
    fp = tmp_path / "test.yaml"
    fp.write_text(yaml_content)
    body = load_playbook_yaml(fp)
    assert body["displayName"] == "TestPB"
    assert body["goal"] == "smoke"


def test_load_playbook_yaml_missing_display_name_raises(tmp_path: Path):
    yaml_content = "goal: just a goal\n"
    fp = tmp_path / "bad.yaml"
    fp.write_text(yaml_content)
    with pytest.raises(ValueError, match="displayName"):
        load_playbook_yaml(fp)


def test_load_playbook_yaml_non_dict_raises(tmp_path: Path):
    fp = tmp_path / "list.yaml"
    fp.write_text("- not\n- a\n- dict\n")
    with pytest.raises(ValueError, match="dict"):
        load_playbook_yaml(fp)


# ============================================================
# Constantes
# ============================================================
def test_playbook_ignore_fields_includes_standard():
    for field in ("name", "tokenCount", "createTime", "updateTime"):
        assert field in PLAYBOOK_IGNORE_FIELDS


def test_create_and_patch_dry_run_helpers():
    with patch("src.push_playbooks.requests.post") as mp, \
         patch("src.push_playbooks.requests.patch") as mpa:
        assert create_playbook(CFG, HEADERS, {"displayName": "X"}, dry_run=True) is True
        assert patch_playbook(
            CFG, HEADERS, name="pb/x",
            payload={"goal": "g"}, update_mask=["goal"], dry_run=True,
        ) is True
    mp.assert_not_called()
    mpa.assert_not_called()
