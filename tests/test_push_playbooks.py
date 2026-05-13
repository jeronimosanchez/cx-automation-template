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
    build_full_update_body,
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
    """Full Update (§3.8): PATCH sin updateMask, body completo con
    todos los campos remotos + locales overlayed."""
    body = {"displayName": "PB1", "goal": "NEW_GOAL", "playbookType": "ROUTINE"}
    full_remote = {
        "name": "projects/.../playbooks/pb-uuid",
        "displayName": "PB1",
        "goal": "OLD_GOAL",
        "playbookType": "ROUTINE",
        "instruction": {"steps": [{"text": "step en remote"}]},  # campo NO en local
        "tokenCount": "100",  # read-only — debe strippearse del body enviado
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
    # CRITICO §3.8: NO updateMask en params.
    assert "params" not in kwargs or "updateMask" not in (kwargs.get("params") or {}), (
        f"Bug §3.8: PATCH no debe enviar updateMask. params={kwargs.get('params')}"
    )
    sent_body = kwargs["json"]
    # El cambio local se aplico.
    assert sent_body["goal"] == "NEW_GOAL"
    # Campos del remote NO en local se preservaron (Full Update — no se borran).
    assert sent_body["instruction"] == {"steps": [{"text": "step en remote"}]}
    # Read-only strippeados.
    assert "tokenCount" not in sent_body
    assert "name" not in sent_body


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
    """Firma nueva de patch_playbook tras §3.8 workaround: recibe `body` completo
    (no `payload` + `update_mask`)."""
    with patch("src.push_playbooks.requests.post") as mp, \
         patch("src.push_playbooks.requests.patch") as mpa:
        assert create_playbook(CFG, HEADERS, {"displayName": "X"}, dry_run=True) is True
        assert patch_playbook(
            CFG, HEADERS, name="pb/x",
            body={"displayName": "X", "goal": "g"}, dry_run=True,
        ) is True
    mp.assert_not_called()
    mpa.assert_not_called()


# ============================================================
# §3.8 workaround — Full Update sin updateMask
# ============================================================
def test_patch_playbook_does_not_send_update_mask():
    """REGRESSION GUARD §3.8: en europe-west1 el PATCH con updateMask
    falla silenciosamente para Playbooks. patch_playbook NUNCA debe
    enviar `params['updateMask']`."""
    with patch("src.push_playbooks.requests.patch") as mpa:
        mpa.return_value = _resp(200, {})
        patch_playbook(
            CFG, HEADERS, name="projects/.../playbooks/pb-x",
            body={"displayName": "X", "goal": "g", "playbookType": "ROUTINE"},
            dry_run=False,
        )
    kwargs = mpa.call_args.kwargs
    # Aceptable: kwargs sin 'params', o params=None, o params={} sin updateMask.
    params = kwargs.get("params") or {}
    assert "updateMask" not in params, (
        f"Bug §3.8: patch_playbook no debe enviar updateMask. params={params}"
    )


def test_patch_playbook_sends_full_body_as_json():
    """El body completo va como JSON request body."""
    body = {"displayName": "X", "goal": "g", "instruction": {"steps": [{"text": "..."}]}}
    with patch("src.push_playbooks.requests.patch") as mpa:
        mpa.return_value = _resp(200, {})
        patch_playbook(CFG, HEADERS, name="pb/x", body=body, dry_run=False)
    assert mpa.call_args.kwargs["json"] == body


def test_build_full_update_body_local_overrides_remote():
    """Campos en local sobrescriben los del remote."""
    remote = {"displayName": "P", "goal": "OLD", "playbookType": "ROUTINE"}
    local = {"displayName": "P", "goal": "NEW"}
    merged = build_full_update_body(remote, local)
    assert merged["goal"] == "NEW"
    assert merged["playbookType"] == "ROUTINE"  # remote-only, preservado


def test_build_full_update_body_preserves_remote_only_fields():
    """Campos solo en remote (que local no menciona) se preservan."""
    remote = {
        "displayName": "P",
        "goal": "g",
        "instruction": {"steps": [{"text": "remote step"}]},
        "referencedTools": ["projects/.../tools/t-1"],
    }
    local = {"displayName": "P", "goal": "g_changed"}
    merged = build_full_update_body(remote, local)
    assert merged["instruction"] == {"steps": [{"text": "remote step"}]}
    assert merged["referencedTools"] == ["projects/.../tools/t-1"]


def test_build_full_update_body_strips_readonly():
    """Read-only del PLAYBOOK_IGNORE_FIELDS se strippean del merged."""
    remote = {
        "name": "projects/.../playbooks/pb-uuid",
        "displayName": "P",
        "goal": "g",
        "tokenCount": "5000",
        "createTime": "2026-01-01",
        "updateTime": "2026-01-02",
    }
    local = {"displayName": "P", "goal": "g_new"}
    merged = build_full_update_body(remote, local)
    for f in PLAYBOOK_IGNORE_FIELDS:
        assert f not in merged, f"{f} debio ser strippeado del Full Update body"


def test_upsert_playbook_unchanged_does_not_call_patch():
    """Cuando el diff es vacio NO se llama a patch (el bug §3.8 no
    se dispara), y NO se construye Full Update body innecesariamente."""
    body = {"displayName": "PB1", "goal": "X", "playbookType": "ROUTINE"}
    full_remote = {
        "name": "pb/uuid", "displayName": "PB1",
        "goal": "X", "playbookType": "ROUTINE",
        "tokenCount": "42",
    }
    existing = {"PB1": {"name": "pb/uuid", "displayName": "PB1"}}
    with patch("src.push_playbooks.requests.get") as mg, \
         patch("src.push_playbooks.requests.patch") as mpa:
        mg.return_value = _resp(200, full_remote)
        action = upsert_playbook(CFG, HEADERS, body, existing, dry_run=False)
    assert action == "unchanged"
    mpa.assert_not_called()  # CRITICO: no PATCH si no hay diff
