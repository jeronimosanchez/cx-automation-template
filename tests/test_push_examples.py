"""Tests unitarios para src/push_examples.py.

Sin red. Sin auth. Mock de `requests.get/post/patch` en el namespace
del modulo. Cubre los 4 casos exigidos por el brief: created,
unchanged, updated, error 4xx.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.push_examples import (
    EXAMPLE_IGNORE_FIELDS,
    create_example,
    inject_tool_path,
    list_examples,
    patch_example,
    upsert_example,
)


# ============================================================
# Fixtures comunes
# ============================================================
CFG = {
    "project": "test-project",
    "location": "europe-west1",
    "agent_id": "agent-uuid",
    "api": {
        "base_v3beta1": "https://example.test/v3beta1",
        "required_headers": {"x-goog-user-project": "test-project"},
    },
    "tool": {"id": "tool-uuid"},
}
HEADERS = {"Authorization": "Bearer fake-token"}
PARENT_PB = (
    "projects/test-project/locations/europe-west1/agents/agent-uuid"
    "/playbooks/pb-uuid"
)


def _resp(status=200, json_data=None, text=""):
    m = MagicMock()
    m.status_code = status
    m.json.return_value = json_data or {}
    m.text = text
    return m


# ============================================================
# list_examples — paginacion
# ============================================================
def test_list_examples_paginates_with_next_token():
    pages = [
        {"examples": [{"name": "ex/1", "displayName": "A"}], "nextPageToken": "tok1"},
        {"examples": [{"name": "ex/2", "displayName": "B"}], "nextPageToken": "tok2"},
        {"examples": [{"name": "ex/3", "displayName": "C"}]},
    ]
    with patch("src.push_examples.requests.get") as mg:
        mg.side_effect = [_resp(200, p) for p in pages]
        result = list_examples(CFG, HEADERS, PARENT_PB)
    assert len(result) == 3
    assert mg.call_count == 3
    # Verifica que el 2o y 3er call llevan pageToken
    assert mg.call_args_list[1].kwargs["params"]["pageToken"] == "tok1"
    assert mg.call_args_list[2].kwargs["params"]["pageToken"] == "tok2"


def test_list_examples_4xx_raises_runtime_error():
    with patch("src.push_examples.requests.get") as mg:
        mg.return_value = _resp(403, text="Forbidden")
        with pytest.raises(RuntimeError, match="LIST /examples"):
            list_examples(CFG, HEADERS, PARENT_PB)


# ============================================================
# upsert_example — los 4 casos del brief
# ============================================================
def test_upsert_example_created_when_remote_missing():
    body = {"displayName": "NewEx", "actions": [{"agentUtterance": {"text": "hi"}}]}
    existing = {}  # vacio
    with patch("src.push_examples.requests.post") as mp, \
         patch("src.push_examples.requests.patch") as mpa:
        mp.return_value = _resp(200, {})
        action = upsert_example(CFG, HEADERS, PARENT_PB, body, existing, dry_run=False)
    assert action == "created"
    mp.assert_called_once()
    mpa.assert_not_called()
    # POST debe ir a /examples del playbook
    url_arg = mp.call_args.args[0]
    assert url_arg.endswith("/examples")


def test_upsert_example_unchanged_when_remote_matches():
    body = {"displayName": "Ex1", "actions": [{"agentUtterance": {"text": "hello"}}]}
    existing = {
        "Ex1": {
            "name": "projects/.../examples/ex-uuid",
            "displayName": "Ex1",
            "actions": [{"agentUtterance": {"text": "hello"}}],
            "tokenCount": "42",
            "createTime": "2025-01-01T00:00:00Z",
        }
    }
    with patch("src.push_examples.requests.post") as mp, \
         patch("src.push_examples.requests.patch") as mpa:
        action = upsert_example(CFG, HEADERS, PARENT_PB, body, existing, dry_run=False)
    assert action == "unchanged"
    mp.assert_not_called()
    mpa.assert_not_called()


def test_upsert_example_updated_when_remote_differs():
    body = {"displayName": "Ex1", "actions": [{"agentUtterance": {"text": "NEW"}}]}
    existing = {
        "Ex1": {
            "name": "projects/.../examples/ex-uuid",
            "displayName": "Ex1",
            "actions": [{"agentUtterance": {"text": "OLD"}}],
        }
    }
    with patch("src.push_examples.requests.post") as mp, \
         patch("src.push_examples.requests.patch") as mpa:
        mpa.return_value = _resp(200, {})
        action = upsert_example(CFG, HEADERS, PARENT_PB, body, existing, dry_run=False)
    assert action == "updated"
    mp.assert_not_called()
    mpa.assert_called_once()
    # updateMask debe ir en params y contener `actions`
    kwargs = mpa.call_args.kwargs
    assert "updateMask" in kwargs["params"]
    assert "actions" in kwargs["params"]["updateMask"]
    # PATCH va sobre el name remoto
    assert mpa.call_args.args[0].endswith("/examples/ex-uuid")


def test_upsert_example_post_4xx_returns_failed():
    body = {"displayName": "BadEx", "actions": []}
    existing = {}
    with patch("src.push_examples.requests.post") as mp:
        mp.return_value = _resp(400, text="INVALID_ARGUMENT: missing field")
        action = upsert_example(CFG, HEADERS, PARENT_PB, body, existing, dry_run=False)
    assert action == "failed"


def test_upsert_example_patch_4xx_returns_failed():
    body = {"displayName": "Ex1", "actions": [{"agentUtterance": {"text": "new"}}]}
    existing = {
        "Ex1": {
            "name": "projects/.../examples/ex-uuid",
            "displayName": "Ex1",
            "actions": [{"agentUtterance": {"text": "old"}}],
        }
    }
    with patch("src.push_examples.requests.patch") as mpa:
        mpa.return_value = _resp(400, text="bad mask")
        action = upsert_example(CFG, HEADERS, PARENT_PB, body, existing, dry_run=False)
    assert action == "failed"


# ============================================================
# dry-run no llama a la red
# ============================================================
def test_upsert_example_dry_run_post_skips_network():
    body = {"displayName": "NewEx", "actions": []}
    with patch("src.push_examples.requests.post") as mp:
        action = upsert_example(CFG, HEADERS, PARENT_PB, body, {}, dry_run=True)
    assert action == "created"  # reporta lo que haria
    mp.assert_not_called()


def test_upsert_example_dry_run_patch_skips_network():
    body = {"displayName": "Ex1", "actions": [{"text": "new"}]}
    existing = {
        "Ex1": {"name": "ex/path", "displayName": "Ex1", "actions": [{"text": "old"}]}
    }
    with patch("src.push_examples.requests.patch") as mpa:
        action = upsert_example(CFG, HEADERS, PARENT_PB, body, existing, dry_run=True)
    assert action == "updated"
    mpa.assert_not_called()


# ============================================================
# Helpers
# ============================================================
def test_inject_tool_path_only_when_missing():
    example = {
        "actions": [
            {"toolUse": {"action": "consultarDatos"}},
            {"toolUse": {"action": "consultarDatos", "tool": "preexistente"}},
            {"agentUtterance": {"text": "no toolUse aqui"}},
        ]
    }
    out = inject_tool_path(example, CFG)
    expected_path = "projects/test-project/locations/europe-west1/agents/agent-uuid/tools/tool-uuid"
    assert out["actions"][0]["toolUse"]["tool"] == expected_path
    # no se sobrescribe el preexistente
    assert out["actions"][1]["toolUse"]["tool"] == "preexistente"


def test_example_ignore_fields_includes_standard_readonly():
    assert "name" in EXAMPLE_IGNORE_FIELDS
    assert "tokenCount" in EXAMPLE_IGNORE_FIELDS
    assert "createTime" in EXAMPLE_IGNORE_FIELDS
    assert "updateTime" in EXAMPLE_IGNORE_FIELDS


# ============================================================
# create_example y patch_example unitarios
# ============================================================
def test_create_example_dry_run_skips_post():
    with patch("src.push_examples.requests.post") as mp:
        ok = create_example(CFG, HEADERS, PARENT_PB, {"displayName": "X"}, dry_run=True)
    assert ok is True
    mp.assert_not_called()


def test_patch_example_sends_update_mask():
    with patch("src.push_examples.requests.patch") as mpa:
        mpa.return_value = _resp(200, {})
        ok = patch_example(
            CFG, HEADERS,
            name="projects/.../examples/abc",
            payload={"actions": ["new"]},
            update_mask=["actions"],
            dry_run=False,
        )
    assert ok is True
    kwargs = mpa.call_args.kwargs
    assert kwargs["params"]["updateMask"] == "actions"
