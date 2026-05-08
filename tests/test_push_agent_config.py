"""Tests unitarios para src/push_agent_config.py.

Sin red. Sin auth. Mock de `requests.get/patch`. No hay LIST: solo
GET -> diff -> PATCH. Cubre los 3 casos relevantes (no aplica
'created' porque solo existe un agente): unchanged, updated, error 4xx.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.diff import diff_resource
from src.push_agent_config import (
    AGENT_IGNORE_FIELDS,
    agent_path,
    get_agent,
    patch_agent,
    resolve_local_body,
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
EXPECTED_AGENT_PATH = (
    "projects/test-project/locations/europe-west1/agents/agent-uuid"
)
EXPECTED_PB_PATH = f"{EXPECTED_AGENT_PATH}/playbooks/pb-uuid"


def _resp(status=200, json_data=None, text=""):
    m = MagicMock()
    m.status_code = status
    m.json.return_value = json_data or {}
    m.text = text
    return m


# ============================================================
# get_agent
# ============================================================
def test_get_agent_returns_body():
    body = {
        "name": EXPECTED_AGENT_PATH,
        "displayName": "TestAgent",
        "defaultLanguageCode": "es",
    }
    with patch("src.push_agent_config.requests.get") as mg:
        mg.return_value = _resp(200, body)
        result = get_agent(CFG, HEADERS)
    assert result == body
    # URL esperada
    url_arg = mg.call_args.args[0]
    assert url_arg.endswith(EXPECTED_AGENT_PATH)


def test_get_agent_4xx_raises_runtime_error():
    with patch("src.push_agent_config.requests.get") as mg:
        mg.return_value = _resp(403, text="Forbidden")
        with pytest.raises(RuntimeError, match="GET agent fallo"):
            get_agent(CFG, HEADERS)


# ============================================================
# resolve_local_body — transformacion start_playbook_id
# ============================================================
def test_resolve_local_body_resolves_start_playbook_id():
    agent_def = {
        "displayName": "A",
        "defaultLanguageCode": "es",
        "start_playbook_id": "pb-uuid",
    }
    body = resolve_local_body(CFG, agent_def)
    assert "start_playbook_id" not in body
    assert body["startPlaybook"] == EXPECTED_PB_PATH
    assert body["displayName"] == "A"


def test_resolve_local_body_keeps_explicit_start_playbook():
    agent_def = {
        "displayName": "A",
        "startPlaybook": "pre-existing-path",
        "start_playbook_id": "pb-uuid",  # NO debe sobrescribir
    }
    body = resolve_local_body(CFG, agent_def)
    assert body["startPlaybook"] == "pre-existing-path"
    assert "start_playbook_id" not in body


def test_resolve_local_body_without_start_playbook_id():
    agent_def = {"displayName": "A", "defaultLanguageCode": "es"}
    body = resolve_local_body(CFG, agent_def)
    assert "startPlaybook" not in body
    assert body == {"displayName": "A", "defaultLanguageCode": "es"}


# ============================================================
# Caso unchanged — diff dice no-op
# ============================================================
def test_diff_unchanged_when_local_matches_remote():
    """Verifica que la combinacion resolve_local_body + diff_resource
    reporta no-op cuando local refleja exactamente el estado remoto.
    """
    agent_def = {
        "displayName": "TestAgent",
        "defaultLanguageCode": "es",
        "timeZone": "Europe/Madrid",
        "start_playbook_id": "pb-uuid",
    }
    local = resolve_local_body(CFG, agent_def)
    remote = {
        "name": EXPECTED_AGENT_PATH,
        "displayName": "TestAgent",
        "defaultLanguageCode": "es",
        "timeZone": "Europe/Madrid",
        "startPlaybook": EXPECTED_PB_PATH,
        "satisfiesPzi": True,  # solo en remoto -> ignorado por diff
        "createTime": "2025-01-01T00:00:00Z",  # ignored
    }
    result = diff_resource(local, remote, ignore_fields=AGENT_IGNORE_FIELDS)
    assert result.needs_update is False


# ============================================================
# Caso updated — diff detecta cambio
# ============================================================
def test_diff_detects_changes_for_update():
    agent_def = {
        "displayName": "TestAgent",
        "defaultLanguageCode": "en",  # cambio: era 'es' en remoto
        "start_playbook_id": "pb-uuid",
    }
    local = resolve_local_body(CFG, agent_def)
    remote = {
        "name": EXPECTED_AGENT_PATH,
        "displayName": "TestAgent",
        "defaultLanguageCode": "es",  # difiere
        "startPlaybook": EXPECTED_PB_PATH,
    }
    result = diff_resource(local, remote, ignore_fields=AGENT_IGNORE_FIELDS)
    assert result.needs_update is True
    assert "defaultLanguageCode" in result.update_mask
    assert result.patch_payload == {"defaultLanguageCode": "en"}


# ============================================================
# patch_agent — verifica request y manejo de errores 4xx
# ============================================================
def test_patch_agent_sends_update_mask_param():
    with patch("src.push_agent_config.requests.patch") as mpa:
        mpa.return_value = _resp(200, {})
        ok = patch_agent(
            CFG, HEADERS,
            payload={"defaultLanguageCode": "en"},
            update_mask=["defaultLanguageCode"],
            dry_run=False,
        )
    assert ok is True
    kwargs = mpa.call_args.kwargs
    assert kwargs["params"]["updateMask"] == "defaultLanguageCode"
    # URL apunta al agente
    assert mpa.call_args.args[0].endswith(EXPECTED_AGENT_PATH)


def test_patch_agent_4xx_returns_false():
    with patch("src.push_agent_config.requests.patch") as mpa:
        mpa.return_value = _resp(400, text="INVALID_ARGUMENT: bad mask")
        ok = patch_agent(
            CFG, HEADERS,
            payload={"defaultLanguageCode": "en"},
            update_mask=["defaultLanguageCode"],
            dry_run=False,
        )
    assert ok is False


def test_patch_agent_dry_run_skips_network():
    with patch("src.push_agent_config.requests.patch") as mpa:
        ok = patch_agent(
            CFG, HEADERS,
            payload={"defaultLanguageCode": "en"},
            update_mask=["defaultLanguageCode"],
            dry_run=True,
        )
    assert ok is True
    mpa.assert_not_called()


# ============================================================
# Constantes y helpers
# ============================================================
def test_agent_ignore_fields_includes_standard():
    for field in ("name", "createTime", "updateTime", "tokenCount"):
        assert field in AGENT_IGNORE_FIELDS


def test_agent_path_format():
    assert agent_path(CFG) == EXPECTED_AGENT_PATH
