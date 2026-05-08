"""Tests unitarios para src/push_environments.py.

Sin red. Sin auth. Mock de `requests.get/post/patch`. Cubre los 4
casos del brief: created, unchanged, updated, error 4xx + dry-run.
"""

from __future__ import annotations

import textwrap
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.push_environments import (
    ENVIRONMENT_IGNORE_FIELDS,
    create_environment,
    discover_environment_files,
    get_environment,
    list_environments,
    load_environment_yaml,
    patch_environment,
    upsert_environment,
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
# list_environments — paginacion y errores
# ============================================================
def test_list_environments_paginates():
    pages = [
        {"environments": [{"name": "e/1", "displayName": "A"}], "nextPageToken": "t1"},
        {"environments": [{"name": "e/2", "displayName": "B"}]},
    ]
    with patch("src.push_environments.requests.get") as mg:
        mg.side_effect = [_resp(200, p) for p in pages]
        result = list_environments(CFG, HEADERS)
    assert len(result) == 2


def test_list_environments_4xx_raises():
    with patch("src.push_environments.requests.get") as mg:
        mg.return_value = _resp(500, text="boom")
        with pytest.raises(RuntimeError, match="LIST /environments"):
            list_environments(CFG, HEADERS)


# ============================================================
# upsert_environment — los 4 casos del brief
# ============================================================
def test_upsert_environment_created_when_missing():
    body = {"displayName": "NewEnv", "description": "d"}
    with patch("src.push_environments.requests.post") as mp:
        mp.return_value = _resp(200, {})
        action = upsert_environment(CFG, HEADERS, body, {}, dry_run=False)
    assert action == "created"


def test_upsert_environment_unchanged_when_match():
    body = {"displayName": "E1", "description": "X", "versionConfigs": []}
    full_remote = {
        "name": "projects/.../environments/e-uuid",
        "displayName": "E1",
        "description": "X",
        "versionConfigs": [],
        "createTime": "2026-05-01T00:00:00Z",
        "updateTime": "2026-05-01T00:00:00Z",
        "lastUpdateTime": "2026-05-01T00:00:00Z",  # ignorado
    }
    existing = {"E1": {"name": full_remote["name"], "displayName": "E1"}}
    with patch("src.push_environments.requests.get") as mg, \
         patch("src.push_environments.requests.patch") as mpa, \
         patch("src.push_environments.requests.post") as mp:
        mg.return_value = _resp(200, full_remote)
        action = upsert_environment(CFG, HEADERS, body, existing, dry_run=False)
    assert action == "unchanged"
    mp.assert_not_called()
    mpa.assert_not_called()


def test_upsert_environment_updated_when_diff():
    body = {"displayName": "E1", "description": "NEW"}
    full_remote = {
        "name": "projects/.../environments/e-uuid",
        "displayName": "E1",
        "description": "OLD",
    }
    existing = {"E1": {"name": full_remote["name"], "displayName": "E1"}}
    with patch("src.push_environments.requests.get") as mg, \
         patch("src.push_environments.requests.patch") as mpa:
        mg.return_value = _resp(200, full_remote)
        mpa.return_value = _resp(200, {})
        action = upsert_environment(CFG, HEADERS, body, existing, dry_run=False)
    assert action == "updated"
    kwargs = mpa.call_args.kwargs
    assert "description" in kwargs["params"]["updateMask"]


def test_upsert_environment_post_4xx_returns_failed():
    with patch("src.push_environments.requests.post") as mp:
        mp.return_value = _resp(400, text="bad")
        action = upsert_environment(
            CFG, HEADERS, {"displayName": "BadE"}, {}, dry_run=False,
        )
    assert action == "failed"


def test_upsert_environment_patch_4xx_returns_failed():
    body = {"displayName": "E1", "description": "new"}
    full_remote = {"name": "e/1", "displayName": "E1", "description": "old"}
    existing = {"E1": {"name": "e/1", "displayName": "E1"}}
    with patch("src.push_environments.requests.get") as mg, \
         patch("src.push_environments.requests.patch") as mpa:
        mg.return_value = _resp(200, full_remote)
        mpa.return_value = _resp(400, text="bad mask")
        action = upsert_environment(CFG, HEADERS, body, existing, dry_run=False)
    assert action == "failed"


def test_upsert_environment_get_4xx_returns_failed():
    body = {"displayName": "E1"}
    existing = {"E1": {"name": "e/1", "displayName": "E1"}}
    with patch("src.push_environments.requests.get") as mg:
        mg.return_value = _resp(403, text="forbidden")
        action = upsert_environment(CFG, HEADERS, body, existing, dry_run=False)
    assert action == "failed"


def test_upsert_environment_dry_run_skips_post():
    with patch("src.push_environments.requests.post") as mp:
        action = upsert_environment(
            CFG, HEADERS, {"displayName": "X"}, {}, dry_run=True,
        )
    assert action == "created"
    mp.assert_not_called()


def test_upsert_environment_dry_run_skips_patch():
    body = {"displayName": "E1", "description": "new"}
    full_remote = {"name": "e/1", "displayName": "E1", "description": "old"}
    existing = {"E1": {"name": "e/1", "displayName": "E1"}}
    with patch("src.push_environments.requests.get") as mg, \
         patch("src.push_environments.requests.patch") as mpa:
        mg.return_value = _resp(200, full_remote)
        action = upsert_environment(CFG, HEADERS, body, existing, dry_run=True)
    assert action == "updated"
    mpa.assert_not_called()


# ============================================================
# load_environment_yaml + helpers
# ============================================================
def test_load_environment_yaml_ok(tmp_path: Path):
    yaml_content = textwrap.dedent("""
        displayName: Test_Env
        description: smoke
    """).strip()
    fp = tmp_path / "e.yaml"
    fp.write_text(yaml_content)
    body = load_environment_yaml(fp)
    assert body["displayName"] == "Test_Env"


def test_load_environment_yaml_missing_displayname_raises(tmp_path: Path):
    fp = tmp_path / "bad.yaml"
    fp.write_text("description: only desc\n")
    with pytest.raises(ValueError, match="displayName"):
        load_environment_yaml(fp)


def test_load_environment_yaml_non_dict_raises(tmp_path: Path):
    fp = tmp_path / "list.yaml"
    fp.write_text("- a\n- b\n")
    with pytest.raises(ValueError, match="dict"):
        load_environment_yaml(fp)


# ============================================================
# Constantes y helpers
# ============================================================
def test_environment_ignore_fields_includes_lastUpdateTime():
    """Environments tienen `lastUpdateTime` ademas de los habituales."""
    for field in ("name", "createTime", "updateTime", "lastUpdateTime"):
        assert field in ENVIRONMENT_IGNORE_FIELDS


def test_get_environment_returns_body():
    full = {"name": "e/1", "displayName": "E"}
    with patch("src.push_environments.requests.get") as mg:
        mg.return_value = _resp(200, full)
        assert get_environment(CFG, HEADERS, "e/1") == full


def test_get_environment_4xx_raises():
    with patch("src.push_environments.requests.get") as mg:
        mg.return_value = _resp(404, text="nf")
        with pytest.raises(RuntimeError, match="GET .* fallo"):
            get_environment(CFG, HEADERS, "e/missing")


def test_create_and_patch_dry_run_helpers():
    with patch("src.push_environments.requests.post") as mp, \
         patch("src.push_environments.requests.patch") as mpa:
        assert create_environment(CFG, HEADERS, {"displayName": "X"}, dry_run=True) is True
        assert patch_environment(
            CFG, HEADERS, name="e/x",
            payload={"description": "d"}, update_mask=["description"], dry_run=True,
        ) is True
    mp.assert_not_called()
    mpa.assert_not_called()


def test_discover_environment_files_returns_list():
    assert isinstance(discover_environment_files(), list)
