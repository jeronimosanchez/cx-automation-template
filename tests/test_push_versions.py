"""Tests unitarios para src/push_versions.py.

Sin red. Sin auth. Mock de `requests.get/post`. Cubre:
  - LIST de versiones (paginacion).
  - Resolucion de flow_id por displayName (match + not-found).
  - Creacion de version: ad-hoc (--description), declarativa (--file)
    y dry-run.
  - Schema YAML (flow_displayName + description requeridos).
  - Errores 4xx en POST.
"""

from __future__ import annotations

import argparse
import textwrap
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.push_versions import (
    DEFAULT_FLOW_DISPLAY_NAME,
    cmd_create,
    cmd_list,
    create_version,
    discover_version_files,
    list_flows,
    list_versions,
    load_version_yaml,
    resolve_flow_id,
    split_local_fields,
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
DEFAULT_FLOW_NAME = "projects/p/locations/l/agents/a/flows/default-uuid"


def _resp(status=200, json_data=None, text=""):
    m = MagicMock()
    m.status_code = status
    m.json.return_value = json_data or {}
    m.text = text
    return m


def _make_args(**kwargs):
    """Construye un Namespace con defaults razonables para cmd_create."""
    defaults = {
        "list_mode": False, "create": True,
        "description": None, "display_name": None,
        "file": None, "all": False,
        "dry_run": False, "flow": None,
    }
    defaults.update(kwargs)
    return argparse.Namespace(**defaults)


# ============================================================
# list_flows / list_versions — paginacion y errores
# ============================================================
def test_list_flows_paginates():
    pages = [
        {"flows": [{"name": "f/1", "displayName": "A"}], "nextPageToken": "t1"},
        {"flows": [{"name": "f/2", "displayName": "B"}]},
    ]
    with patch("src.push_versions.requests.get") as mg:
        mg.side_effect = [_resp(200, p) for p in pages]
        result = list_flows(CFG, HEADERS)
    assert len(result) == 2


def test_list_versions_paginates():
    pages = [
        {"versions": [{"name": "v/1", "displayName": "A"}], "nextPageToken": "t1"},
        {"versions": [{"name": "v/2", "displayName": "B"}]},
    ]
    with patch("src.push_versions.requests.get") as mg:
        mg.side_effect = [_resp(200, p) for p in pages]
        result = list_versions(CFG, HEADERS, FLOW_NAME)
    assert len(result) == 2


def test_list_versions_4xx_raises():
    with patch("src.push_versions.requests.get") as mg:
        mg.return_value = _resp(500, text="boom")
        with pytest.raises(RuntimeError, match=r"LIST .*/versions"):
            list_versions(CFG, HEADERS, FLOW_NAME)


# ============================================================
# resolve_flow_id — match + not-found
# ============================================================
def test_resolve_flow_id_match():
    flows = [
        {"name": FLOW_NAME, "displayName": "Test_Flow"},
        {"name": DEFAULT_FLOW_NAME, "displayName": DEFAULT_FLOW_DISPLAY_NAME},
    ]
    with patch("src.push_versions.requests.get") as mg:
        mg.return_value = _resp(200, {"flows": flows})
        result = resolve_flow_id(CFG, HEADERS, "Test_Flow")
    assert result == FLOW_NAME


def test_resolve_flow_id_not_found_raises():
    with patch("src.push_versions.requests.get") as mg:
        mg.return_value = _resp(200, {"flows": [{"displayName": "Other"}]})
        with pytest.raises(RuntimeError, match="Flow .* no encontrado"):
            resolve_flow_id(CFG, HEADERS, "Missing_Flow")


# ============================================================
# create_version — POST de snapshot inmutable
# ============================================================
def test_create_version_success():
    body = {"displayName": "v1", "description": "first"}
    with patch("src.push_versions.requests.post") as mp:
        mp.return_value = _resp(200, {})
        ok = create_version(CFG, HEADERS, FLOW_NAME, body, dry_run=False)
    assert ok is True
    mp.assert_called_once()


def test_create_version_201_success():
    """POST puede devolver 201 Created en algunas APIs CX."""
    with patch("src.push_versions.requests.post") as mp:
        mp.return_value = _resp(201, {})
        ok = create_version(CFG, HEADERS, FLOW_NAME, {"description": "d"}, dry_run=False)
    assert ok is True


def test_create_version_4xx_returns_false():
    with patch("src.push_versions.requests.post") as mp:
        mp.return_value = _resp(400, text="bad")
        ok = create_version(CFG, HEADERS, FLOW_NAME, {"description": "d"}, dry_run=False)
    assert ok is False


def test_create_version_dry_run_skips_post():
    with patch("src.push_versions.requests.post") as mp:
        ok = create_version(CFG, HEADERS, FLOW_NAME, {"description": "d"}, dry_run=True)
    assert ok is True
    mp.assert_not_called()


# ============================================================
# split_local_fields — extrae flow_displayName del body API
# ============================================================
def test_split_local_fields_removes_flow_display_name():
    raw = {"flow_displayName": "F1", "displayName": "v1", "description": "d"}
    api_body, flow = split_local_fields(raw)
    assert flow == "F1"
    assert "flow_displayName" not in api_body
    assert api_body["displayName"] == "v1"


def test_split_local_fields_no_flow_returns_none():
    raw = {"displayName": "v1"}
    api_body, flow = split_local_fields(raw)
    assert flow is None


# ============================================================
# load_version_yaml — schema (flow_displayName + description requeridos)
# ============================================================
def test_load_version_yaml_ok(tmp_path: Path):
    yaml_content = textwrap.dedent("""
        flow_displayName: Default Start Flow
        description: snapshot
    """).strip()
    fp = tmp_path / "v.yaml"
    fp.write_text(yaml_content)
    data = load_version_yaml(fp)
    assert data["flow_displayName"] == "Default Start Flow"
    assert data["description"] == "snapshot"


def test_load_version_yaml_missing_flow_display_name_raises(tmp_path: Path):
    fp = tmp_path / "bad.yaml"
    fp.write_text("description: only\n")
    with pytest.raises(ValueError, match="flow_displayName"):
        load_version_yaml(fp)


def test_load_version_yaml_missing_description_raises(tmp_path: Path):
    fp = tmp_path / "bad.yaml"
    fp.write_text("flow_displayName: F1\n")
    with pytest.raises(ValueError, match="description"):
        load_version_yaml(fp)


def test_load_version_yaml_non_dict_raises(tmp_path: Path):
    fp = tmp_path / "list.yaml"
    fp.write_text("- a\n")
    with pytest.raises(ValueError, match="dict"):
        load_version_yaml(fp)


def test_discover_version_files_returns_list():
    assert isinstance(discover_version_files(), list)


# ============================================================
# cmd_create — modos ad-hoc (--description) y declarativo (--file)
# ============================================================
def test_cmd_create_adhoc_uses_default_flow():
    """`--create --description X` sin --flow debe usar Default Start Flow."""
    args = _make_args(description="Auto deploy abc123")
    flows = [{"name": DEFAULT_FLOW_NAME, "displayName": DEFAULT_FLOW_DISPLAY_NAME}]
    with patch("src.push_versions.requests.get") as mg, \
         patch("src.push_versions.requests.post") as mp:
        mg.return_value = _resp(200, {"flows": flows})
        mp.return_value = _resp(200, {})
        rc = cmd_create(CFG, HEADERS, args)
    assert rc == 0
    # Verifica que el body POST lleva la description y NO lleva flow_displayName.
    sent = mp.call_args.kwargs["json"]
    assert sent["description"] == "Auto deploy abc123"
    assert "flow_displayName" not in sent


def test_cmd_create_adhoc_with_explicit_flow():
    args = _make_args(description="d", flow="Test_Flow")
    flows = [{"name": FLOW_NAME, "displayName": "Test_Flow"}]
    with patch("src.push_versions.requests.get") as mg, \
         patch("src.push_versions.requests.post") as mp:
        mg.return_value = _resp(200, {"flows": flows})
        mp.return_value = _resp(200, {})
        rc = cmd_create(CFG, HEADERS, args)
    assert rc == 0
    posted_url = mp.call_args.args[0]
    assert FLOW_NAME in posted_url


def test_cmd_create_adhoc_dry_run_skips_post():
    args = _make_args(description="d", flow="Test_Flow", dry_run=True)
    flows = [{"name": FLOW_NAME, "displayName": "Test_Flow"}]
    with patch("src.push_versions.requests.get") as mg, \
         patch("src.push_versions.requests.post") as mp:
        mg.return_value = _resp(200, {"flows": flows})
        rc = cmd_create(CFG, HEADERS, args)
    assert rc == 0
    mp.assert_not_called()


def test_cmd_create_flow_not_found_returns_failed():
    args = _make_args(description="d", flow="Missing")
    with patch("src.push_versions.requests.get") as mg:
        mg.return_value = _resp(200, {"flows": [{"displayName": "Other"}]})
        rc = cmd_create(CFG, HEADERS, args)
    assert rc == 1


def test_cmd_create_from_file(tmp_path: Path):
    yaml_content = textwrap.dedent("""
        flow_displayName: Test_Flow
        displayName: v1
        description: First snapshot
    """).strip()
    fp = tmp_path / "v.yaml"
    fp.write_text(yaml_content)

    args = _make_args(description=None, file=str(fp))
    flows = [{"name": FLOW_NAME, "displayName": "Test_Flow"}]
    with patch("src.push_versions.requests.get") as mg, \
         patch("src.push_versions.requests.post") as mp:
        mg.return_value = _resp(200, {"flows": flows})
        mp.return_value = _resp(200, {})
        rc = cmd_create(CFG, HEADERS, args)
    assert rc == 0
    sent = mp.call_args.kwargs["json"]
    assert sent["displayName"] == "v1"
    assert sent["description"] == "First snapshot"
    assert "flow_displayName" not in sent  # debe haberse separado


def test_cmd_create_no_mode_returns_failed():
    """`--create` sin --description, --file ni --all debe fallar limpio."""
    args = _make_args(description=None, file=None, all=False)
    rc = cmd_create(CFG, HEADERS, args)
    assert rc == 1


def test_cmd_create_post_4xx_returns_failed():
    args = _make_args(description="d", flow="F")
    flows = [{"name": FLOW_NAME, "displayName": "F"}]
    with patch("src.push_versions.requests.get") as mg, \
         patch("src.push_versions.requests.post") as mp:
        mg.return_value = _resp(200, {"flows": flows})
        mp.return_value = _resp(400, text="bad")
        rc = cmd_create(CFG, HEADERS, args)
    assert rc == 1


# ============================================================
# cmd_list — lista versiones por flow
# ============================================================
def test_cmd_list_no_filter_iterates_all_flows():
    """Sin --flow, recorre todos los flows y lista versions de cada uno."""
    flows = [
        {"name": FLOW_NAME, "displayName": "F1"},
        {"name": DEFAULT_FLOW_NAME, "displayName": DEFAULT_FLOW_DISPLAY_NAME},
    ]
    versions_per_flow = [
        {"versions": [{"name": "v/1", "displayName": "v1", "state": "RUNNING",
                       "createTime": "2026-05-01"}]},
        {"versions": []},
    ]
    with patch("src.push_versions.requests.get") as mg:
        mg.side_effect = [
            _resp(200, {"flows": flows}),
            _resp(200, versions_per_flow[0]),
            _resp(200, versions_per_flow[1]),
        ]
        rc = cmd_list(CFG, HEADERS, flow_filter=None)
    assert rc == 0


def test_cmd_list_flow_filter_match():
    flows = [{"name": FLOW_NAME, "displayName": "F1"}]
    with patch("src.push_versions.requests.get") as mg:
        mg.side_effect = [
            _resp(200, {"flows": flows}),
            _resp(200, {"versions": []}),
        ]
        rc = cmd_list(CFG, HEADERS, flow_filter="F1")
    assert rc == 0


def test_cmd_list_flow_filter_not_found_returns_failed():
    flows = [{"displayName": "Other"}]
    with patch("src.push_versions.requests.get") as mg:
        mg.return_value = _resp(200, {"flows": flows})
        rc = cmd_list(CFG, HEADERS, flow_filter="Missing")
    assert rc == 1
