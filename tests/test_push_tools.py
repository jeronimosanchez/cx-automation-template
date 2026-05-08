"""Tests unitarios para src/push_tools.py.

Sin red. Sin auth. Mock de `requests.get/post/patch`. Cubre los 4
casos exigidos por el brief: created, unchanged, updated, error 4xx.
"""

from __future__ import annotations

import textwrap
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.push_tools import (
    TOOL_IGNORE_FIELDS,
    create_tool,
    discover_tool_files,
    get_tool,
    list_tools,
    load_tool_yaml,
    patch_tool,
    upsert_tool,
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

OPENAPI_SPEC_RAW = textwrap.dedent("""\
    openapi: 3.0.0
    info:
      title: TestTool
      version: 1.0.0
    paths: {}
""")


def _resp(status=200, json_data=None, text=""):
    m = MagicMock()
    m.status_code = status
    m.json.return_value = json_data or {}
    m.text = text
    return m


# ============================================================
# list_tools — paginacion y errores
# ============================================================
def test_list_tools_paginates():
    pages = [
        {"tools": [{"name": "t/1", "displayName": "A"}], "nextPageToken": "t1"},
        {"tools": [{"name": "t/2", "displayName": "B"}]},
    ]
    with patch("src.push_tools.requests.get") as mg:
        mg.side_effect = [_resp(200, p) for p in pages]
        result = list_tools(CFG, HEADERS)
    assert len(result) == 2
    assert mg.call_count == 2


def test_list_tools_4xx_raises():
    with patch("src.push_tools.requests.get") as mg:
        mg.return_value = _resp(503, text="Service Unavailable")
        with pytest.raises(RuntimeError, match="LIST /tools"):
            list_tools(CFG, HEADERS)


# ============================================================
# get_tool
# ============================================================
def test_get_tool_returns_full_body():
    full = {
        "name": "t/1",
        "displayName": "T",
        "openApiSpec": {"textSchema": OPENAPI_SPEC_RAW},
        "toolType": "CUSTOMIZED_TOOL",
    }
    with patch("src.push_tools.requests.get") as mg:
        mg.return_value = _resp(200, full)
        result = get_tool(CFG, HEADERS, "t/1")
    assert result == full


def test_get_tool_4xx_raises():
    with patch("src.push_tools.requests.get") as mg:
        mg.return_value = _resp(404, text="Not Found")
        with pytest.raises(RuntimeError, match="GET .* fallo"):
            get_tool(CFG, HEADERS, "t/missing")


# ============================================================
# upsert_tool — los 4 casos del brief
# ============================================================
def test_upsert_tool_created_when_missing():
    body = {
        "displayName": "NewTool",
        "description": "test",
        "toolType": "CUSTOMIZED_TOOL",
        "openApiSpec": {"textSchema": OPENAPI_SPEC_RAW},
    }
    with patch("src.push_tools.requests.post") as mp:
        mp.return_value = _resp(200, {})
        action = upsert_tool(CFG, HEADERS, body, {}, dry_run=False)
    assert action == "created"
    mp.assert_called_once()


def test_upsert_tool_unchanged_when_match():
    body = {
        "displayName": "T1",
        "description": "x",
        "toolType": "CUSTOMIZED_TOOL",
        "openApiSpec": {"textSchema": OPENAPI_SPEC_RAW},
    }
    full_remote = {
        "name": "projects/.../tools/t-uuid",
        **body,
        "createTime": "2025-01-01T00:00:00Z",  # ignorado
    }
    existing = {"T1": {"name": full_remote["name"], "displayName": "T1"}}
    with patch("src.push_tools.requests.get") as mg, \
         patch("src.push_tools.requests.patch") as mpa, \
         patch("src.push_tools.requests.post") as mp:
        mg.return_value = _resp(200, full_remote)
        action = upsert_tool(CFG, HEADERS, body, existing, dry_run=False)
    assert action == "unchanged"
    mp.assert_not_called()
    mpa.assert_not_called()


def test_upsert_tool_updated_when_description_changes():
    body = {
        "displayName": "T1",
        "description": "NUEVO",
        "toolType": "CUSTOMIZED_TOOL",
        "openApiSpec": {"textSchema": OPENAPI_SPEC_RAW},
    }
    full_remote = {
        "name": "projects/.../tools/t-uuid",
        "displayName": "T1",
        "description": "VIEJO",
        "toolType": "CUSTOMIZED_TOOL",
        "openApiSpec": {"textSchema": OPENAPI_SPEC_RAW},
    }
    existing = {"T1": {"name": full_remote["name"], "displayName": "T1"}}
    with patch("src.push_tools.requests.get") as mg, \
         patch("src.push_tools.requests.patch") as mpa:
        mg.return_value = _resp(200, full_remote)
        mpa.return_value = _resp(200, {})
        action = upsert_tool(CFG, HEADERS, body, existing, dry_run=False)
    assert action == "updated"
    kwargs = mpa.call_args.kwargs
    assert "description" in kwargs["params"]["updateMask"]


def test_upsert_tool_post_4xx_returns_failed():
    body = {"displayName": "BadTool", "toolType": "CUSTOMIZED_TOOL"}
    with patch("src.push_tools.requests.post") as mp:
        mp.return_value = _resp(400, text="INVALID openApiSpec")
        action = upsert_tool(CFG, HEADERS, body, {}, dry_run=False)
    assert action == "failed"


def test_upsert_tool_patch_4xx_returns_failed():
    body = {"displayName": "T1", "description": "new"}
    full_remote = {
        "name": "t/1",
        "displayName": "T1",
        "description": "old",
    }
    existing = {"T1": {"name": "t/1", "displayName": "T1"}}
    with patch("src.push_tools.requests.get") as mg, \
         patch("src.push_tools.requests.patch") as mpa:
        mg.return_value = _resp(200, full_remote)
        mpa.return_value = _resp(400, text="bad")
        action = upsert_tool(CFG, HEADERS, body, existing, dry_run=False)
    assert action == "failed"


def test_upsert_tool_get_4xx_returns_failed():
    body = {"displayName": "T1"}
    existing = {"T1": {"name": "t/1", "displayName": "T1"}}
    with patch("src.push_tools.requests.get") as mg:
        mg.return_value = _resp(403, text="Forbidden")
        action = upsert_tool(CFG, HEADERS, body, existing, dry_run=False)
    assert action == "failed"


# ============================================================
# Dry-run no llama a la red
# ============================================================
def test_upsert_tool_dry_run_skips_post():
    with patch("src.push_tools.requests.post") as mp:
        action = upsert_tool(
            CFG, HEADERS, {"displayName": "X"}, {}, dry_run=True,
        )
    assert action == "created"
    mp.assert_not_called()


def test_upsert_tool_dry_run_skips_patch():
    body = {"displayName": "T1", "description": "new"}
    full_remote = {"name": "t/1", "displayName": "T1", "description": "old"}
    existing = {"T1": {"name": "t/1", "displayName": "T1"}}
    with patch("src.push_tools.requests.get") as mg, \
         patch("src.push_tools.requests.patch") as mpa:
        mg.return_value = _resp(200, full_remote)
        action = upsert_tool(CFG, HEADERS, body, existing, dry_run=True)
    assert action == "updated"
    mpa.assert_not_called()


# ============================================================
# load_tool_yaml — schema con openapi_spec_file y inline
# ============================================================
def test_load_tool_yaml_with_openapi_spec_file(tmp_path: Path):
    spec_file = tmp_path / "openapi.yaml"
    spec_file.write_text(OPENAPI_SPEC_RAW)
    wrapper = tmp_path / "tool.yaml"
    wrapper.write_text(
        "displayName: TestTool\n"
        "description: smoke\n"
        "toolType: CUSTOMIZED_TOOL\n"
        "openapi_spec_file: openapi.yaml\n"
    )
    body = load_tool_yaml(wrapper)
    assert body["displayName"] == "TestTool"
    # textSchema debe ser EXACTAMENTE el contenido raw, byte-a-byte
    assert body["openApiSpec"]["textSchema"] == OPENAPI_SPEC_RAW
    # openapi_spec_file ya no esta en el body
    assert "openapi_spec_file" not in body


def test_load_tool_yaml_with_inline_text_schema(tmp_path: Path):
    wrapper = tmp_path / "tool.yaml"
    wrapper.write_text(
        "displayName: T\n"
        "description: test\n"
        "toolType: CUSTOMIZED_TOOL\n"
        "openApiSpec:\n"
        "  textSchema: |\n"
        "    openapi: 3.0.0\n"
        "    info: {title: T}\n"
    )
    body = load_tool_yaml(wrapper)
    assert "textSchema" in body["openApiSpec"]
    assert "openapi: 3.0.0" in body["openApiSpec"]["textSchema"]


def test_load_tool_yaml_missing_spec_raises(tmp_path: Path):
    wrapper = tmp_path / "tool.yaml"
    wrapper.write_text("displayName: T\ntoolType: CUSTOMIZED_TOOL\n")
    with pytest.raises(ValueError, match="textSchema"):
        load_tool_yaml(wrapper)


def test_load_tool_yaml_missing_display_name_raises(tmp_path: Path):
    wrapper = tmp_path / "bad.yaml"
    wrapper.write_text("description: x\n")
    with pytest.raises(ValueError, match="displayName"):
        load_tool_yaml(wrapper)


def test_load_tool_yaml_missing_spec_file_raises(tmp_path: Path):
    wrapper = tmp_path / "tool.yaml"
    wrapper.write_text(
        "displayName: T\n"
        "toolType: CUSTOMIZED_TOOL\n"
        "openapi_spec_file: doesnotexist.yaml\n"
    )
    with pytest.raises(ValueError, match="no existe"):
        load_tool_yaml(wrapper)


# ============================================================
# Constantes y helpers
# ============================================================
def test_tool_ignore_fields_includes_standard():
    for field in ("name", "createTime", "updateTime"):
        assert field in TOOL_IGNORE_FIELDS


def test_create_and_patch_dry_run_helpers():
    with patch("src.push_tools.requests.post") as mp, \
         patch("src.push_tools.requests.patch") as mpa:
        assert create_tool(CFG, HEADERS, {"displayName": "X"}, dry_run=True) is True
        assert patch_tool(
            CFG, HEADERS, name="t/x",
            payload={"description": "d"}, update_mask=["description"], dry_run=True,
        ) is True
    mp.assert_not_called()
    mpa.assert_not_called()
