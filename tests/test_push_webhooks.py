"""Tests unitarios para src/push_webhooks.py.

Sin red. Sin auth. Mock de `requests.get/post/patch`. Cubre los 4
casos del brief: created, unchanged, updated, error 4xx + dry-run.
"""

from __future__ import annotations

import textwrap
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.push_webhooks import (
    WEBHOOK_IGNORE_FIELDS,
    create_webhook,
    discover_webhook_files,
    get_webhook,
    list_webhooks,
    load_webhook_yaml,
    patch_webhook,
    upsert_webhook,
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
# list_webhooks
# ============================================================
def test_list_webhooks_paginates():
    pages = [
        {"webhooks": [{"name": "w/1", "displayName": "A"}], "nextPageToken": "t1"},
        {"webhooks": [{"name": "w/2", "displayName": "B"}]},
    ]
    with patch("src.push_webhooks.requests.get") as mg:
        mg.side_effect = [_resp(200, p) for p in pages]
        result = list_webhooks(CFG, HEADERS)
    assert len(result) == 2


def test_list_webhooks_4xx_raises():
    with patch("src.push_webhooks.requests.get") as mg:
        mg.return_value = _resp(500, text="boom")
        with pytest.raises(RuntimeError, match="LIST /webhooks"):
            list_webhooks(CFG, HEADERS)


# ============================================================
# upsert_webhook — los 4 casos del brief
# ============================================================
def test_upsert_webhook_created_when_missing():
    body = {
        "displayName": "NewWH",
        "genericWebService": {"uri": "https://example.com/h"},
    }
    with patch("src.push_webhooks.requests.post") as mp:
        mp.return_value = _resp(200, {})
        action = upsert_webhook(CFG, HEADERS, body, {}, dry_run=False)
    assert action == "created"


def test_upsert_webhook_unchanged():
    body = {
        "displayName": "WH1",
        "genericWebService": {"uri": "https://example.com/h", "httpMethod": "POST"},
        "timeout": "5s",
    }
    full_remote = {
        "name": "w/1",
        "displayName": "WH1",
        "genericWebService": {"uri": "https://example.com/h", "httpMethod": "POST"},
        "timeout": "5s",
        "createTime": "2026-05-01T00:00:00Z",
    }
    existing = {"WH1": {"name": "w/1", "displayName": "WH1"}}
    with patch("src.push_webhooks.requests.get") as mg, \
         patch("src.push_webhooks.requests.patch") as mpa, \
         patch("src.push_webhooks.requests.post") as mp:
        mg.return_value = _resp(200, full_remote)
        action = upsert_webhook(CFG, HEADERS, body, existing, dry_run=False)
    assert action == "unchanged"
    mp.assert_not_called()
    mpa.assert_not_called()


def test_upsert_webhook_updated_when_uri_changes():
    body = {
        "displayName": "WH1",
        "genericWebService": {"uri": "https://NEW.example.com/h"},
    }
    full_remote = {
        "name": "w/1",
        "displayName": "WH1",
        "genericWebService": {"uri": "https://OLD.example.com/h"},
    }
    existing = {"WH1": {"name": "w/1", "displayName": "WH1"}}
    with patch("src.push_webhooks.requests.get") as mg, \
         patch("src.push_webhooks.requests.patch") as mpa:
        mg.return_value = _resp(200, full_remote)
        mpa.return_value = _resp(200, {})
        action = upsert_webhook(CFG, HEADERS, body, existing, dry_run=False)
    assert action == "updated"
    kwargs = mpa.call_args.kwargs
    assert "genericWebService.uri" in kwargs["params"]["updateMask"]


def test_upsert_webhook_post_4xx_returns_failed():
    with patch("src.push_webhooks.requests.post") as mp:
        mp.return_value = _resp(400, text="bad")
        action = upsert_webhook(
            CFG, HEADERS, {"displayName": "BadWH"}, {}, dry_run=False,
        )
    assert action == "failed"


def test_upsert_webhook_patch_4xx_returns_failed():
    body = {"displayName": "WH1", "timeout": "10s"}
    full_remote = {"name": "w/1", "displayName": "WH1", "timeout": "5s"}
    existing = {"WH1": {"name": "w/1", "displayName": "WH1"}}
    with patch("src.push_webhooks.requests.get") as mg, \
         patch("src.push_webhooks.requests.patch") as mpa:
        mg.return_value = _resp(200, full_remote)
        mpa.return_value = _resp(400, text="bad mask")
        action = upsert_webhook(CFG, HEADERS, body, existing, dry_run=False)
    assert action == "failed"


def test_upsert_webhook_get_4xx_returns_failed():
    body = {"displayName": "WH1"}
    existing = {"WH1": {"name": "w/1", "displayName": "WH1"}}
    with patch("src.push_webhooks.requests.get") as mg:
        mg.return_value = _resp(403, text="forbidden")
        action = upsert_webhook(CFG, HEADERS, body, existing, dry_run=False)
    assert action == "failed"


def test_upsert_webhook_dry_run_skips_post():
    with patch("src.push_webhooks.requests.post") as mp:
        action = upsert_webhook(
            CFG, HEADERS, {"displayName": "X"}, {}, dry_run=True,
        )
    assert action == "created"
    mp.assert_not_called()


# ============================================================
# load_webhook_yaml + helpers
# ============================================================
def test_load_webhook_yaml_ok(tmp_path: Path):
    yaml_content = textwrap.dedent("""
        displayName: WH1
        genericWebService:
          uri: https://example.com
    """).strip()
    fp = tmp_path / "w.yaml"
    fp.write_text(yaml_content)
    body = load_webhook_yaml(fp)
    assert body["displayName"] == "WH1"


def test_load_webhook_yaml_missing_displayname_raises(tmp_path: Path):
    fp = tmp_path / "bad.yaml"
    fp.write_text("timeout: 5s\n")
    with pytest.raises(ValueError, match="displayName"):
        load_webhook_yaml(fp)


def test_load_webhook_yaml_non_dict_raises(tmp_path: Path):
    fp = tmp_path / "list.yaml"
    fp.write_text("- a\n- b\n")
    with pytest.raises(ValueError, match="dict"):
        load_webhook_yaml(fp)


# ============================================================
# Constantes y helpers
# ============================================================
def test_webhook_ignore_fields():
    for field in ("name", "createTime", "updateTime"):
        assert field in WEBHOOK_IGNORE_FIELDS


def test_get_webhook_returns_body():
    full = {"name": "w/1", "displayName": "WH"}
    with patch("src.push_webhooks.requests.get") as mg:
        mg.return_value = _resp(200, full)
        assert get_webhook(CFG, HEADERS, "w/1") == full


def test_get_webhook_4xx_raises():
    with patch("src.push_webhooks.requests.get") as mg:
        mg.return_value = _resp(404, text="nf")
        with pytest.raises(RuntimeError, match="GET .* fallo"):
            get_webhook(CFG, HEADERS, "w/missing")


def test_create_and_patch_dry_run_helpers():
    with patch("src.push_webhooks.requests.post") as mp, \
         patch("src.push_webhooks.requests.patch") as mpa:
        assert create_webhook(CFG, HEADERS, {"displayName": "X"}, dry_run=True) is True
        assert patch_webhook(
            CFG, HEADERS, name="w/x",
            payload={"timeout": "5s"}, update_mask=["timeout"], dry_run=True,
        ) is True
    mp.assert_not_called()
    mpa.assert_not_called()


def test_discover_webhook_files_returns_list():
    assert isinstance(discover_webhook_files(), list)
