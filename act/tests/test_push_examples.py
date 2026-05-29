"""Tests unitarios para act/push_examples.py.

Sin red. Sin auth. Mock de `requests.get/post/patch` en el namespace
del modulo. Cubre:
- list_examples paginado y errores
- upsert_example los 4 casos (created/unchanged/updated/failed) + dry-run
- inject_tool_path
- split_local_fields (PR10a, schema nuevo)
- find_existing_example (lookup rename-resistant: id primero, displayName fallback)
- load_example_yaml (schema nuevo: 1 example por fichero)
- discover_example_files (recursivo, subcarpetas por playbook)
"""

from __future__ import annotations

import textwrap
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from act.push_examples import (
    EXAMPLE_IGNORE_FIELDS,
    create_example,
    discover_example_files,
    find_existing_example,
    inject_tool_path,
    list_examples,
    load_example_yaml,
    patch_example,
    split_local_fields,
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


def _remote_ex(name_suffix, display, **fields):
    """Helper para construir un dict remoto con name = .../examples/<suffix>."""
    return {
        "name": f"{PARENT_PB}/examples/{name_suffix}",
        "displayName": display,
        **fields,
    }


# ============================================================
# list_examples — paginacion
# ============================================================
def test_list_examples_paginates_with_next_token():
    pages = [
        {"examples": [{"name": "ex/1", "displayName": "A"}], "nextPageToken": "tok1"},
        {"examples": [{"name": "ex/2", "displayName": "B"}], "nextPageToken": "tok2"},
        {"examples": [{"name": "ex/3", "displayName": "C"}]},
    ]
    with patch("act.push_examples.requests.get") as mg:
        mg.side_effect = [_resp(200, p) for p in pages]
        result = list_examples(CFG, HEADERS, PARENT_PB)
    assert len(result) == 3
    assert mg.call_count == 3
    assert mg.call_args_list[1].kwargs["params"]["pageToken"] == "tok1"
    assert mg.call_args_list[2].kwargs["params"]["pageToken"] == "tok2"


def test_list_examples_4xx_raises_runtime_error():
    with patch("act.push_examples.requests.get") as mg:
        mg.return_value = _resp(403, text="Forbidden")
        with pytest.raises(RuntimeError, match="LIST /examples"):
            list_examples(CFG, HEADERS, PARENT_PB)


# ============================================================
# split_local_fields — PR10a nuevo
# ============================================================
def test_split_local_fields_extracts_playbook_and_id():
    raw = {
        "playbook": "Registro_Task",
        "id": "abc-123",
        "displayName": "Ex_Reg_01",
        "actions": [{"text": "hi"}],
    }
    api_body, playbook, example_id = split_local_fields(raw)
    assert playbook == "Registro_Task"
    assert example_id == "abc-123"
    assert "playbook" not in api_body
    assert "id" not in api_body
    assert api_body == {"displayName": "Ex_Reg_01", "actions": [{"text": "hi"}]}


def test_split_local_fields_handles_missing_id():
    """id es opcional (recomendado pero no requerido)."""
    raw = {"playbook": "P", "displayName": "Ex", "actions": []}
    api_body, playbook, example_id = split_local_fields(raw)
    assert example_id is None
    assert playbook == "P"
    assert api_body == {"displayName": "Ex", "actions": []}


# ============================================================
# find_existing_example — lookup rename-resistant
# ============================================================
def test_find_existing_example_by_id_takes_priority():
    """Si example_id machea, ignora displayName aunque haya cambiado."""
    remotes = [
        _remote_ex("uuid-123", "OLD_NAME_in_CX"),
        _remote_ex("uuid-456", "OtherEx"),
    ]
    # Localmente el displayName cambio a "NEW_NAME" pero id sigue siendo uuid-123
    found = find_existing_example(remotes, "uuid-123", "NEW_NAME")
    assert found["name"].endswith("/uuid-123")
    assert found["displayName"] == "OLD_NAME_in_CX"


def test_find_existing_example_falls_back_to_displayname_when_id_none():
    remotes = [
        _remote_ex("uuid-A", "ExA"),
        _remote_ex("uuid-B", "ExB"),
    ]
    found = find_existing_example(remotes, None, "ExB")
    assert found["name"].endswith("/uuid-B")


def test_find_existing_example_falls_back_to_displayname_when_id_mismatch():
    """Si el id local no machea ningun remoto, usa displayName."""
    remotes = [_remote_ex("uuid-real", "ExReal")]
    found = find_existing_example(remotes, "uuid-bogus", "ExReal")
    assert found["name"].endswith("/uuid-real")


def test_find_existing_example_returns_none_when_neither_matches():
    remotes = [_remote_ex("uuid-X", "ExX")]
    assert find_existing_example(remotes, "uuid-Y", "ExY") is None


# ============================================================
# upsert_example — los 4 casos con la firma nueva
# ============================================================
def test_upsert_example_created_when_remote_missing():
    body = {"displayName": "NewEx", "actions": [{"agentUtterance": {"text": "hi"}}]}
    remote_examples = []  # vacio
    with patch("act.push_examples.requests.post") as mp, \
         patch("act.push_examples.requests.patch") as mpa:
        mp.return_value = _resp(200, {})
        action = upsert_example(CFG, HEADERS, PARENT_PB, body,
                                example_id=None, remote_examples=remote_examples,
                                dry_run=False)
    assert action == "created"
    mp.assert_called_once()
    mpa.assert_not_called()
    assert mp.call_args.args[0].endswith("/examples")


def test_upsert_example_unchanged_when_remote_matches():
    body = {"displayName": "Ex1", "actions": [{"agentUtterance": {"text": "hello"}}]}
    remote_examples = [
        _remote_ex("ex-uuid", "Ex1",
                   actions=[{"agentUtterance": {"text": "hello"}}],
                   tokenCount="42",
                   createTime="2025-01-01T00:00:00Z"),
    ]
    with patch("act.push_examples.requests.post") as mp, \
         patch("act.push_examples.requests.patch") as mpa:
        action = upsert_example(CFG, HEADERS, PARENT_PB, body,
                                example_id="ex-uuid", remote_examples=remote_examples,
                                dry_run=False)
    assert action == "unchanged"
    mp.assert_not_called()
    mpa.assert_not_called()


def test_upsert_example_updated_when_remote_differs():
    body = {"displayName": "Ex1", "actions": [{"agentUtterance": {"text": "NEW"}}]}
    remote_examples = [
        _remote_ex("ex-uuid", "Ex1",
                   actions=[{"agentUtterance": {"text": "OLD"}}]),
    ]
    with patch("act.push_examples.requests.post") as mp, \
         patch("act.push_examples.requests.patch") as mpa:
        mpa.return_value = _resp(200, {})
        action = upsert_example(CFG, HEADERS, PARENT_PB, body,
                                example_id="ex-uuid", remote_examples=remote_examples,
                                dry_run=False)
    assert action == "updated"
    mp.assert_not_called()
    mpa.assert_called_once()
    kwargs = mpa.call_args.kwargs
    assert "params" not in kwargs
    assert kwargs["json"] == body
    assert mpa.call_args.args[0].endswith("/examples/ex-uuid")


def test_upsert_example_post_4xx_returns_failed():
    body = {"displayName": "BadEx", "actions": []}
    with patch("act.push_examples.requests.post") as mp:
        mp.return_value = _resp(400, text="INVALID_ARGUMENT: missing field")
        action = upsert_example(CFG, HEADERS, PARENT_PB, body,
                                example_id=None, remote_examples=[],
                                dry_run=False)
    assert action == "failed"


def test_upsert_example_patch_4xx_returns_failed():
    body = {"displayName": "Ex1", "actions": [{"agentUtterance": {"text": "new"}}]}
    remote_examples = [
        _remote_ex("ex-uuid", "Ex1",
                   actions=[{"agentUtterance": {"text": "old"}}]),
    ]
    with patch("act.push_examples.requests.patch") as mpa:
        mpa.return_value = _resp(400, text="bad mask")
        action = upsert_example(CFG, HEADERS, PARENT_PB, body,
                                example_id="ex-uuid", remote_examples=remote_examples,
                                dry_run=False)
    assert action == "failed"


def test_upsert_example_dry_run_post_skips_network():
    body = {"displayName": "NewEx", "actions": []}
    with patch("act.push_examples.requests.post") as mp:
        action = upsert_example(CFG, HEADERS, PARENT_PB, body,
                                example_id=None, remote_examples=[],
                                dry_run=True)
    assert action == "created"
    mp.assert_not_called()


def test_upsert_example_dry_run_patch_skips_network():
    body = {"displayName": "Ex1", "actions": [{"text": "new"}]}
    remote_examples = [_remote_ex("ex-uuid", "Ex1", actions=[{"text": "old"}])]
    with patch("act.push_examples.requests.patch") as mpa:
        action = upsert_example(CFG, HEADERS, PARENT_PB, body,
                                example_id="ex-uuid", remote_examples=remote_examples,
                                dry_run=True)
    assert action == "updated"
    mpa.assert_not_called()


def test_upsert_example_with_rename_uses_id_match():
    """Caso clave de PR10a: localmente displayName cambio, pero id es el mismo.
    Push debe matchear por id y PATCH, NO crear duplicado."""
    body = {"displayName": "RenamedExample", "actions": [{"text": "same"}]}
    remote_examples = [
        _remote_ex("stable-uuid", "OriginalName",
                   actions=[{"text": "same"}]),
    ]
    with patch("act.push_examples.requests.post") as mp, \
         patch("act.push_examples.requests.patch") as mpa:
        mpa.return_value = _resp(200, {})
        action = upsert_example(CFG, HEADERS, PARENT_PB, body,
                                example_id="stable-uuid", remote_examples=remote_examples,
                                dry_run=False)
    mp.assert_not_called()
    assert action == "updated"
    kwargs = mpa.call_args.kwargs
    assert "params" not in kwargs
    assert kwargs["json"] == body


# ============================================================
# inject_tool_path
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
    assert out["actions"][1]["toolUse"]["tool"] == "preexistente"


# ============================================================
# load_example_yaml — schema nuevo (1 example por fichero)
# ============================================================
def test_load_example_yaml_parses_new_schema(tmp_path: Path):
    yaml_content = textwrap.dedent("""
        playbook: Registro_Task
        id: abc-123
        displayName: Ex_Reg_01
        actions:
          - agentUtterance:
              text: Hola
    """).strip()
    fp = tmp_path / "ex.yaml"
    fp.write_text(yaml_content)
    playbook, example_id, api_body = load_example_yaml(fp)
    assert playbook == "Registro_Task"
    assert example_id == "abc-123"
    assert api_body["displayName"] == "Ex_Reg_01"
    assert "playbook" not in api_body
    assert "id" not in api_body
    assert api_body["actions"][0]["agentUtterance"]["text"] == "Hola"


def test_load_example_yaml_missing_playbook_raises(tmp_path: Path):
    fp = tmp_path / "bad.yaml"
    fp.write_text("displayName: ExX\nactions: []\n")
    with pytest.raises(ValueError, match="playbook"):
        load_example_yaml(fp)


def test_load_example_yaml_missing_displayname_raises(tmp_path: Path):
    fp = tmp_path / "bad.yaml"
    fp.write_text("playbook: P\nactions: []\n")
    with pytest.raises(ValueError, match="displayName"):
        load_example_yaml(fp)


def test_load_example_yaml_non_dict_raises(tmp_path: Path):
    fp = tmp_path / "bad.yaml"
    fp.write_text("- a\n- b\n")
    with pytest.raises(ValueError, match="dict"):
        load_example_yaml(fp)


def test_load_example_yaml_id_optional(tmp_path: Path):
    """id es recomendado pero no requerido. Sin id, example_id == None."""
    fp = tmp_path / "ex.yaml"
    fp.write_text("playbook: P\ndisplayName: Ex\nactions: []\n")
    playbook, example_id, api_body = load_example_yaml(fp)
    assert example_id is None
    assert playbook == "P"


# ============================================================
# discover_example_files — recursivo, subcarpetas por playbook
# ============================================================
def test_discover_example_files_recurses_subdirs(monkeypatch, tmp_path: Path):
    """Descubre yamls en definitions/examples/<playbook>/<example>.yaml."""
    examples_root = tmp_path / "examples"
    (examples_root / "registro_task").mkdir(parents=True)
    (examples_root / "compra").mkdir(parents=True)
    (examples_root / "registro_task" / "ex_reg_01.yaml").write_text("playbook: R\ndisplayName: E\n")
    (examples_root / "registro_task" / "ex_reg_02.yaml").write_text("playbook: R\ndisplayName: E\n")
    (examples_root / "compra" / "exa_v9.yaml").write_text("playbook: C\ndisplayName: E\n")
    (examples_root / ".gitkeep").write_text("")  # debe excluirse (no es .yaml)

    monkeypatch.setattr("act.push_examples.EXAMPLES_DIR", examples_root)
    result = discover_example_files()
    assert len(result) == 3
    # Todos los .yaml descubiertos, .gitkeep excluido
    names = {p.name for p in result}
    assert names == {"ex_reg_01.yaml", "ex_reg_02.yaml", "exa_v9.yaml"}


def test_discover_example_files_returns_empty_when_dir_missing(monkeypatch, tmp_path: Path):
    monkeypatch.setattr("act.push_examples.EXAMPLES_DIR", tmp_path / "nonexistent")
    assert discover_example_files() == []


# ============================================================
# Helpers y constantes
# ============================================================
def test_example_ignore_fields_includes_standard_readonly():
    assert "name" in EXAMPLE_IGNORE_FIELDS
    assert "tokenCount" in EXAMPLE_IGNORE_FIELDS
    assert "createTime" in EXAMPLE_IGNORE_FIELDS
    assert "updateTime" in EXAMPLE_IGNORE_FIELDS


def test_create_example_dry_run_skips_post():
    with patch("act.push_examples.requests.post") as mp:
        ok = create_example(CFG, HEADERS, PARENT_PB, {"displayName": "X"}, dry_run=True)
    assert ok is True
    mp.assert_not_called()


def test_patch_example_sends_full_body_without_update_mask():
    with patch("act.push_examples.requests.patch") as mpa:
        mpa.return_value = _resp(200, {})
        ok = patch_example(
            CFG, HEADERS,
            name="projects/.../examples/abc",
            full_body={"actions": ["new"]},
            changed_fields=["actions"],
            dry_run=False,
        )
    assert ok is True
    kwargs = mpa.call_args.kwargs
    assert "params" not in kwargs
    assert kwargs["json"] == {"actions": ["new"]}
