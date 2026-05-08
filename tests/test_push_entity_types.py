"""Tests unitarios para src/push_entity_types.py.

Sin red. Sin auth. Mock de `requests.get/post/patch`. Cubre los 4
casos del brief + escenario especifico: los 3 `kind` posibles
(KIND_MAP, KIND_LIST, KIND_REGEXP) procesados sin error.
"""

from __future__ import annotations

import textwrap
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.push_entity_types import (
    ENTITY_TYPE_IGNORE_FIELDS,
    create_entity_type,
    discover_entity_type_files,
    get_entity_type,
    list_entity_types,
    load_entity_type_yaml,
    patch_entity_type,
    upsert_entity_type,
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
# list_entity_types — paginacion y errores
# ============================================================
def test_list_entity_types_paginates():
    pages = [
        {"entityTypes": [{"name": "e/1", "displayName": "A"}], "nextPageToken": "t1"},
        {"entityTypes": [{"name": "e/2", "displayName": "B"}]},
    ]
    with patch("src.push_entity_types.requests.get") as mg:
        mg.side_effect = [_resp(200, p) for p in pages]
        result = list_entity_types(CFG, HEADERS)
    assert len(result) == 2


def test_list_entity_types_4xx_raises():
    with patch("src.push_entity_types.requests.get") as mg:
        mg.return_value = _resp(500, text="boom")
        with pytest.raises(RuntimeError, match="LIST /entityTypes"):
            list_entity_types(CFG, HEADERS)


# ============================================================
# upsert_entity_type — los 4 casos del brief
# ============================================================
def test_upsert_entity_type_created_when_missing():
    body = {"displayName": "NewET", "kind": "KIND_MAP", "entities": []}
    with patch("src.push_entity_types.requests.post") as mp:
        mp.return_value = _resp(200, {})
        action = upsert_entity_type(CFG, HEADERS, body, {}, dry_run=False)
    assert action == "created"


def test_upsert_entity_type_unchanged():
    body = {
        "displayName": "Color",
        "kind": "KIND_MAP",
        "entities": [{"value": "red", "synonyms": ["red"]}],
    }
    full_remote = {
        "name": "et/1",
        "displayName": "Color",
        "kind": "KIND_MAP",
        "entities": [{"value": "red", "synonyms": ["red"]}],
        "createTime": "2026-05-01T00:00:00Z",
    }
    existing = {"Color": {"name": "et/1", "displayName": "Color"}}
    with patch("src.push_entity_types.requests.get") as mg, \
         patch("src.push_entity_types.requests.patch") as mpa, \
         patch("src.push_entity_types.requests.post") as mp:
        mg.return_value = _resp(200, full_remote)
        action = upsert_entity_type(CFG, HEADERS, body, existing, dry_run=False)
    assert action == "unchanged"
    mp.assert_not_called()
    mpa.assert_not_called()


def test_upsert_entity_type_updated():
    body = {"displayName": "Color", "kind": "KIND_MAP", "entities": [{"value": "red"}]}
    full_remote = {
        "name": "et/1", "displayName": "Color", "kind": "KIND_MAP",
        "entities": [{"value": "blue"}],
    }
    existing = {"Color": {"name": "et/1", "displayName": "Color"}}
    with patch("src.push_entity_types.requests.get") as mg, \
         patch("src.push_entity_types.requests.patch") as mpa:
        mg.return_value = _resp(200, full_remote)
        mpa.return_value = _resp(200, {})
        action = upsert_entity_type(CFG, HEADERS, body, existing, dry_run=False)
    assert action == "updated"


def test_upsert_entity_type_post_4xx_returns_failed():
    with patch("src.push_entity_types.requests.post") as mp:
        mp.return_value = _resp(400, text="bad")
        action = upsert_entity_type(
            CFG, HEADERS, {"displayName": "X", "kind": "KIND_MAP"}, {},
            dry_run=False,
        )
    assert action == "failed"


def test_upsert_entity_type_dry_run_skips_post():
    with patch("src.push_entity_types.requests.post") as mp:
        action = upsert_entity_type(
            CFG, HEADERS, {"displayName": "X", "kind": "KIND_MAP"}, {},
            dry_run=True,
        )
    assert action == "created"
    mp.assert_not_called()


def test_upsert_entity_type_get_4xx_returns_failed():
    body = {"displayName": "C", "kind": "KIND_MAP"}
    existing = {"C": {"name": "et/1", "displayName": "C"}}
    with patch("src.push_entity_types.requests.get") as mg:
        mg.return_value = _resp(403, text="forbidden")
        action = upsert_entity_type(CFG, HEADERS, body, existing, dry_run=False)
    assert action == "failed"


# ============================================================
# Escenario especifico: los 3 kind posibles del brief.
# ============================================================
@pytest.mark.parametrize("kind,entities", [
    ("KIND_MAP", [{"value": "rojo", "synonyms": ["rojo", "red"]}]),
    ("KIND_LIST", [{"value": "alfa"}, {"value": "beta"}]),
    ("KIND_REGEXP", [{"value": "[A-Z]{3}-[0-9]{4}"}]),
])
def test_entity_type_supports_three_kinds(kind, entities):
    """Los 3 kinds deben procesarse sin crash en el flujo created."""
    body = {"displayName": f"Test_{kind}", "kind": kind, "entities": entities}
    with patch("src.push_entity_types.requests.post") as mp:
        mp.return_value = _resp(200, {})
        action = upsert_entity_type(CFG, HEADERS, body, {}, dry_run=False)
    assert action == "created"
    sent_body = mp.call_args.kwargs["json"]
    assert sent_body["kind"] == kind
    assert sent_body["entities"] == entities


@pytest.mark.parametrize("kind", ["KIND_MAP", "KIND_LIST", "KIND_REGEXP"])
def test_load_entity_type_yaml_accepts_each_kind(tmp_path: Path, kind):
    yaml_content = textwrap.dedent(f"""
        displayName: ET_{kind}
        kind: {kind}
        entities: []
    """).strip()
    fp = tmp_path / f"{kind}.yaml"
    fp.write_text(yaml_content)
    body = load_entity_type_yaml(fp)
    assert body["kind"] == kind


# ============================================================
# load_entity_type_yaml — schema valido
# ============================================================
def test_load_entity_type_yaml_missing_displayname_raises(tmp_path: Path):
    fp = tmp_path / "bad.yaml"
    fp.write_text("kind: KIND_MAP\nentities: []\n")
    with pytest.raises(ValueError, match="displayName"):
        load_entity_type_yaml(fp)


def test_load_entity_type_yaml_missing_kind_raises(tmp_path: Path):
    fp = tmp_path / "bad.yaml"
    fp.write_text("displayName: ET\n")
    with pytest.raises(ValueError, match="kind"):
        load_entity_type_yaml(fp)


def test_load_entity_type_yaml_non_dict_raises(tmp_path: Path):
    fp = tmp_path / "list.yaml"
    fp.write_text("- a\n- b\n")
    with pytest.raises(ValueError, match="dict"):
        load_entity_type_yaml(fp)


# ============================================================
# Constantes y helpers
# ============================================================
def test_entity_type_ignore_fields():
    for field in ("name", "createTime", "updateTime"):
        assert field in ENTITY_TYPE_IGNORE_FIELDS


def test_get_entity_type_returns_body():
    full = {"name": "et/1", "displayName": "ET", "kind": "KIND_MAP"}
    with patch("src.push_entity_types.requests.get") as mg:
        mg.return_value = _resp(200, full)
        assert get_entity_type(CFG, HEADERS, "et/1") == full


def test_get_entity_type_4xx_raises():
    with patch("src.push_entity_types.requests.get") as mg:
        mg.return_value = _resp(404, text="nf")
        with pytest.raises(RuntimeError, match="GET .* fallo"):
            get_entity_type(CFG, HEADERS, "et/missing")


def test_create_and_patch_dry_run_helpers():
    with patch("src.push_entity_types.requests.post") as mp, \
         patch("src.push_entity_types.requests.patch") as mpa:
        assert create_entity_type(
            CFG, HEADERS, {"displayName": "X", "kind": "KIND_MAP"}, dry_run=True,
        ) is True
        assert patch_entity_type(
            CFG, HEADERS, name="et/x",
            payload={"x": 1}, update_mask=["x"], dry_run=True,
        ) is True
    mp.assert_not_called()
    mpa.assert_not_called()


def test_discover_entity_type_files_returns_list():
    assert isinstance(discover_entity_type_files(), list)
