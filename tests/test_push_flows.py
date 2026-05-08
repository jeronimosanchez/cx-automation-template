"""Tests unitarios para src/push_flows.py.

Sin red. Sin auth. Mock de `requests.get/post/patch`. Cubre los 4
casos del brief: created, unchanged, updated, error 4xx + dry-run.
"""

from __future__ import annotations

import textwrap
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.push_flows import (
    FLOW_IGNORE_FIELDS,
    create_flow,
    discover_flow_files,
    get_flow,
    list_flows,
    load_flow_yaml,
    patch_flow,
    upsert_flow,
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
# list_flows — paginacion y errores
# ============================================================
def test_list_flows_paginates():
    pages = [
        {"flows": [{"name": "f/1", "displayName": "A"}], "nextPageToken": "t1"},
        {"flows": [{"name": "f/2", "displayName": "B"}]},
    ]
    with patch("src.push_flows.requests.get") as mg:
        mg.side_effect = [_resp(200, p) for p in pages]
        result = list_flows(CFG, HEADERS)
    assert len(result) == 2
    assert mg.call_count == 2


def test_list_flows_4xx_raises():
    with patch("src.push_flows.requests.get") as mg:
        mg.return_value = _resp(500, text="Internal Server Error")
        with pytest.raises(RuntimeError, match="LIST /flows"):
            list_flows(CFG, HEADERS)


# ============================================================
# get_flow — full body fetch
# ============================================================
def test_get_flow_returns_body():
    full = {"name": "f/1", "displayName": "A", "nluSettings": {"modelType": "X"}}
    with patch("src.push_flows.requests.get") as mg:
        mg.return_value = _resp(200, full)
        result = get_flow(CFG, HEADERS, "f/1")
    assert result == full


def test_get_flow_4xx_raises():
    with patch("src.push_flows.requests.get") as mg:
        mg.return_value = _resp(404, text="Not Found")
        with pytest.raises(RuntimeError, match="GET .* fallo"):
            get_flow(CFG, HEADERS, "f/missing")


# ============================================================
# upsert_flow — los 4 casos del brief
# ============================================================
def test_upsert_flow_created_when_missing():
    body = {"displayName": "NewFlow", "description": "d"}
    with patch("src.push_flows.requests.post") as mp:
        mp.return_value = _resp(200, {})
        action = upsert_flow(CFG, HEADERS, body, {}, dry_run=False)
    assert action == "created"
    mp.assert_called_once()


def test_upsert_flow_unchanged_when_match():
    body = {"displayName": "F1", "description": "X", "nluSettings": {"modelType": "STD"}}
    full_remote = {
        "name": "projects/.../flows/f-uuid",
        "displayName": "F1",
        "description": "X",
        "nluSettings": {"modelType": "STD"},
        "createTime": "2026-05-01T00:00:00Z",  # ignorado
    }
    existing_summary = {"F1": {"name": full_remote["name"], "displayName": "F1"}}
    with patch("src.push_flows.requests.get") as mg, \
         patch("src.push_flows.requests.patch") as mpa, \
         patch("src.push_flows.requests.post") as mp:
        mg.return_value = _resp(200, full_remote)
        action = upsert_flow(CFG, HEADERS, body, existing_summary, dry_run=False)
    assert action == "unchanged"
    mp.assert_not_called()
    mpa.assert_not_called()


def test_upsert_flow_updated_when_diff():
    body = {"displayName": "F1", "description": "NEW"}
    full_remote = {
        "name": "projects/.../flows/f-uuid",
        "displayName": "F1",
        "description": "OLD",
    }
    existing_summary = {"F1": {"name": full_remote["name"], "displayName": "F1"}}
    with patch("src.push_flows.requests.get") as mg, \
         patch("src.push_flows.requests.patch") as mpa:
        mg.return_value = _resp(200, full_remote)
        mpa.return_value = _resp(200, {})
        action = upsert_flow(CFG, HEADERS, body, existing_summary, dry_run=False)
    assert action == "updated"
    mpa.assert_called_once()
    kwargs = mpa.call_args.kwargs
    assert "description" in kwargs["params"]["updateMask"]


def test_upsert_flow_post_4xx_returns_failed():
    body = {"displayName": "BadFlow"}
    with patch("src.push_flows.requests.post") as mp:
        mp.return_value = _resp(400, text="INVALID_ARGUMENT")
        action = upsert_flow(CFG, HEADERS, body, {}, dry_run=False)
    assert action == "failed"


def test_upsert_flow_patch_4xx_returns_failed():
    body = {"displayName": "F1", "description": "new"}
    full_remote = {"name": "f/1", "displayName": "F1", "description": "old"}
    existing = {"F1": {"name": "f/1", "displayName": "F1"}}
    with patch("src.push_flows.requests.get") as mg, \
         patch("src.push_flows.requests.patch") as mpa:
        mg.return_value = _resp(200, full_remote)
        mpa.return_value = _resp(400, text="bad mask")
        action = upsert_flow(CFG, HEADERS, body, existing, dry_run=False)
    assert action == "failed"


def test_upsert_flow_get_4xx_returns_failed():
    body = {"displayName": "F1", "description": "x"}
    existing = {"F1": {"name": "f/1", "displayName": "F1"}}
    with patch("src.push_flows.requests.get") as mg:
        mg.return_value = _resp(403, text="Forbidden")
        action = upsert_flow(CFG, HEADERS, body, existing, dry_run=False)
    assert action == "failed"


# ============================================================
# Dry-run no llama a la red
# ============================================================
def test_upsert_flow_dry_run_skips_post():
    body = {"displayName": "NewF"}
    with patch("src.push_flows.requests.post") as mp:
        action = upsert_flow(CFG, HEADERS, body, {}, dry_run=True)
    assert action == "created"
    mp.assert_not_called()


def test_upsert_flow_dry_run_skips_patch():
    body = {"displayName": "F1", "description": "new"}
    full_remote = {"name": "f/1", "displayName": "F1", "description": "old"}
    existing = {"F1": {"name": "f/1", "displayName": "F1"}}
    with patch("src.push_flows.requests.get") as mg, \
         patch("src.push_flows.requests.patch") as mpa:
        mg.return_value = _resp(200, full_remote)
        action = upsert_flow(CFG, HEADERS, body, existing, dry_run=True)
    assert action == "updated"
    mpa.assert_not_called()


# ============================================================
# load_flow_yaml + discover
# ============================================================
def test_load_flow_yaml_top_level_displayname(tmp_path: Path):
    yaml_content = textwrap.dedent("""
        displayName: TestFlow
        description: smoke
    """).strip()
    fp = tmp_path / "test.yaml"
    fp.write_text(yaml_content)
    body = load_flow_yaml(fp)
    assert body["displayName"] == "TestFlow"
    assert body["description"] == "smoke"


def test_load_flow_yaml_missing_display_name_raises(tmp_path: Path):
    fp = tmp_path / "bad.yaml"
    fp.write_text("description: only desc\n")
    with pytest.raises(ValueError, match="displayName"):
        load_flow_yaml(fp)


def test_load_flow_yaml_non_dict_raises(tmp_path: Path):
    fp = tmp_path / "list.yaml"
    fp.write_text("- not\n- a\n- dict\n")
    with pytest.raises(ValueError, match="dict"):
        load_flow_yaml(fp)


# ============================================================
# Constantes
# ============================================================
def test_flow_ignore_fields_includes_standard():
    for field in ("name", "createTime", "updateTime"):
        assert field in FLOW_IGNORE_FIELDS


def test_create_and_patch_dry_run_helpers():
    with patch("src.push_flows.requests.post") as mp, \
         patch("src.push_flows.requests.patch") as mpa:
        assert create_flow(CFG, HEADERS, {"displayName": "X"}, dry_run=True) is True
        assert patch_flow(
            CFG, HEADERS, name="f/x",
            payload={"description": "g"}, update_mask=["description"], dry_run=True,
        ) is True
    mp.assert_not_called()
    mpa.assert_not_called()


def test_discover_flow_files_returns_list():
    """Smoke test: la funcion responde sin crash y devuelve lista."""
    result = discover_flow_files()
    assert isinstance(result, list)
