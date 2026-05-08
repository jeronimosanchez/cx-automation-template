"""Tests unitarios para src/push_pages.py.

Sin red. Sin auth. Mock de `requests.get/post/patch`. Cubre:
  - created, unchanged, updated, error 4xx, dry-run
  - resolucion flow_id por displayName (incluido caso "flow padre no
    encontrado" requerido por el brief)
  - separacion de campos local-only (parent_flow_displayName)
"""

from __future__ import annotations

import textwrap
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.push_pages import (
    PAGE_IGNORE_FIELDS,
    create_page,
    discover_page_files,
    get_page,
    list_flows,
    list_pages,
    load_page_yaml,
    patch_page,
    resolve_flow_id,
    split_local_fields,
    upsert_page,
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
FLOW_NAME = "projects/p/locations/l/agents/a/flows/flow-uuid"


def _resp(status=200, json_data=None, text=""):
    m = MagicMock()
    m.status_code = status
    m.json.return_value = json_data or {}
    m.text = text
    return m


# ============================================================
# resolve_flow_id — caso encontrado y NO encontrado (brief)
# ============================================================
def test_resolve_flow_id_match():
    flows = [
        {"name": "projects/p/locations/l/agents/a/flows/x", "displayName": "Other"},
        {"name": FLOW_NAME, "displayName": "Test_Flow"},
    ]
    with patch("src.push_pages.requests.get") as mg:
        mg.return_value = _resp(200, {"flows": flows})
        result = resolve_flow_id(CFG, HEADERS, "Test_Flow")
    assert result == FLOW_NAME


def test_resolve_flow_id_not_found_raises():
    """Brief Sprint 3, Task 7: 'flow padre no encontrado'."""
    flows = [{"name": "x", "displayName": "Other"}]
    with patch("src.push_pages.requests.get") as mg:
        mg.return_value = _resp(200, {"flows": flows})
        with pytest.raises(RuntimeError, match="Flow padre"):
            resolve_flow_id(CFG, HEADERS, "Missing_Flow")


# ============================================================
# list_flows / list_pages — paginacion
# ============================================================
def test_list_flows_paginates():
    pages = [
        {"flows": [{"name": "f/1", "displayName": "A"}], "nextPageToken": "t1"},
        {"flows": [{"name": "f/2", "displayName": "B"}]},
    ]
    with patch("src.push_pages.requests.get") as mg:
        mg.side_effect = [_resp(200, p) for p in pages]
        result = list_flows(CFG, HEADERS)
    assert len(result) == 2


def test_list_pages_paginates():
    pages = [
        {"pages": [{"name": "p/1", "displayName": "A"}], "nextPageToken": "t1"},
        {"pages": [{"name": "p/2", "displayName": "B"}]},
    ]
    with patch("src.push_pages.requests.get") as mg:
        mg.side_effect = [_resp(200, p) for p in pages]
        result = list_pages(CFG, HEADERS, FLOW_NAME)
    assert len(result) == 2


def test_list_pages_4xx_raises():
    with patch("src.push_pages.requests.get") as mg:
        mg.return_value = _resp(500, text="server error")
        with pytest.raises(RuntimeError, match=r"LIST .*/pages"):
            list_pages(CFG, HEADERS, FLOW_NAME)


# ============================================================
# upsert_page — los 4 casos del brief
# ============================================================
def test_upsert_page_created_when_missing():
    body = {"displayName": "NewPage"}
    with patch("src.push_pages.requests.post") as mp:
        mp.return_value = _resp(200, {})
        action = upsert_page(CFG, HEADERS, FLOW_NAME, body, {}, dry_run=False)
    assert action == "created"
    mp.assert_called_once()


def test_upsert_page_unchanged_when_match():
    body = {"displayName": "P1", "entryFulfillment": {"messages": []}}
    full_remote = {
        "name": f"{FLOW_NAME}/pages/p-uuid",
        "displayName": "P1",
        "entryFulfillment": {"messages": []},
        "createTime": "2026-05-01T00:00:00Z",
    }
    existing = {"P1": {"name": full_remote["name"], "displayName": "P1"}}
    with patch("src.push_pages.requests.get") as mg, \
         patch("src.push_pages.requests.patch") as mpa, \
         patch("src.push_pages.requests.post") as mp:
        mg.return_value = _resp(200, full_remote)
        action = upsert_page(CFG, HEADERS, FLOW_NAME, body, existing, dry_run=False)
    assert action == "unchanged"
    mp.assert_not_called()
    mpa.assert_not_called()


def test_upsert_page_updated_when_diff():
    body = {"displayName": "P1", "entryFulfillment": {"messages": ["new"]}}
    full_remote = {
        "name": f"{FLOW_NAME}/pages/p-uuid",
        "displayName": "P1",
        "entryFulfillment": {"messages": ["old"]},
    }
    existing = {"P1": {"name": full_remote["name"], "displayName": "P1"}}
    with patch("src.push_pages.requests.get") as mg, \
         patch("src.push_pages.requests.patch") as mpa:
        mg.return_value = _resp(200, full_remote)
        mpa.return_value = _resp(200, {})
        action = upsert_page(CFG, HEADERS, FLOW_NAME, body, existing, dry_run=False)
    assert action == "updated"
    mpa.assert_called_once()


def test_upsert_page_post_4xx_returns_failed():
    body = {"displayName": "BadPage"}
    with patch("src.push_pages.requests.post") as mp:
        mp.return_value = _resp(400, text="bad")
        action = upsert_page(CFG, HEADERS, FLOW_NAME, body, {}, dry_run=False)
    assert action == "failed"


def test_upsert_page_get_4xx_returns_failed():
    body = {"displayName": "P1"}
    existing = {"P1": {"name": "p/1", "displayName": "P1"}}
    with patch("src.push_pages.requests.get") as mg:
        mg.return_value = _resp(403, text="forbidden")
        action = upsert_page(CFG, HEADERS, FLOW_NAME, body, existing, dry_run=False)
    assert action == "failed"


def test_upsert_page_dry_run_skips_post():
    body = {"displayName": "NewP"}
    with patch("src.push_pages.requests.post") as mp:
        action = upsert_page(CFG, HEADERS, FLOW_NAME, body, {}, dry_run=True)
    assert action == "created"
    mp.assert_not_called()


# ============================================================
# split_local_fields — separacion del campo parent_flow_displayName
# ============================================================
def test_split_local_fields_removes_parent_flow():
    raw = {
        "displayName": "P1",
        "parent_flow_displayName": "Test_Flow",
        "entryFulfillment": {},
    }
    api_body, parent = split_local_fields(raw)
    assert parent == "Test_Flow"
    assert "parent_flow_displayName" not in api_body
    assert api_body["displayName"] == "P1"
    assert api_body["entryFulfillment"] == {}


def test_split_local_fields_no_parent_returns_none():
    raw = {"displayName": "P1"}
    api_body, parent = split_local_fields(raw)
    assert parent is None


# ============================================================
# load_page_yaml — schema valido
# ============================================================
def test_load_page_yaml_ok(tmp_path: Path):
    yaml_content = textwrap.dedent("""
        parent_flow_displayName: Test_Flow
        displayName: P1
    """).strip()
    fp = tmp_path / "page.yaml"
    fp.write_text(yaml_content)
    data = load_page_yaml(fp)
    assert data["displayName"] == "P1"
    assert data["parent_flow_displayName"] == "Test_Flow"


def test_load_page_yaml_missing_display_name_raises(tmp_path: Path):
    fp = tmp_path / "bad.yaml"
    fp.write_text("parent_flow_displayName: Test_Flow\n")
    with pytest.raises(ValueError, match="displayName"):
        load_page_yaml(fp)


def test_load_page_yaml_missing_parent_flow_raises(tmp_path: Path):
    fp = tmp_path / "bad.yaml"
    fp.write_text("displayName: P1\n")
    with pytest.raises(ValueError, match="parent_flow_displayName"):
        load_page_yaml(fp)


def test_load_page_yaml_non_dict_raises(tmp_path: Path):
    fp = tmp_path / "list.yaml"
    fp.write_text("- a\n- b\n")
    with pytest.raises(ValueError, match="dict"):
        load_page_yaml(fp)


# ============================================================
# Constantes y helpers
# ============================================================
def test_page_ignore_fields():
    for field in ("name", "createTime", "updateTime"):
        assert field in PAGE_IGNORE_FIELDS


def test_create_and_patch_dry_run_helpers():
    with patch("src.push_pages.requests.post") as mp, \
         patch("src.push_pages.requests.patch") as mpa:
        assert create_page(CFG, HEADERS, FLOW_NAME, {"displayName": "X"}, dry_run=True) is True
        assert patch_page(
            CFG, HEADERS, name="p/x",
            payload={"x": 1}, update_mask=["x"], dry_run=True,
        ) is True
    mp.assert_not_called()
    mpa.assert_not_called()


def test_get_page_returns_body():
    full = {"name": "p/1", "displayName": "P", "entryFulfillment": {}}
    with patch("src.push_pages.requests.get") as mg:
        mg.return_value = _resp(200, full)
        assert get_page(CFG, HEADERS, "p/1") == full


def test_get_page_4xx_raises():
    with patch("src.push_pages.requests.get") as mg:
        mg.return_value = _resp(404, text="nf")
        with pytest.raises(RuntimeError, match="GET .* fallo"):
            get_page(CFG, HEADERS, "p/missing")


def test_discover_page_files_returns_list():
    result = discover_page_files()
    assert isinstance(result, list)
