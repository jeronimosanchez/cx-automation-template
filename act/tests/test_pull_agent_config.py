"""Tests unitarios para act/pull_agent_config.py.

Sin red. Sin auth. Cubre cx_to_local (strip + transform + order),
surgical_write (preservacion de bloques no-CX y comentarios, idempotencia
del MARKER) y round-trip end-to-end contra resolve_local_body + diff_resource
de push_agent_config para garantizar pull -> push --dry-run == unchanged.
"""
from __future__ import annotations

from act.diff import diff_resource
from act.pull_agent_config import (
    MARKER,
    PULL_STRIP_FIELDS,
    cx_to_local,
    surgical_write,
)
from act.push_agent_config import AGENT_IGNORE_FIELDS, resolve_local_body


CFG = {
    "project": "test-project",
    "location": "europe-west1",
    "agent_id": "agent-uuid",
    "api": {
        "base_v3beta1": "https://example.test/v3beta1",
        "required_headers": {"x-goog-user-project": "test-project"},
    },
}
AGENT_PATH = "projects/test-project/locations/europe-west1/agents/agent-uuid"
PB_PATH = f"{AGENT_PATH}/playbooks/pb-uuid-123"


# ============================================================
# cx_to_local — transformaciones inversas a resolve_local_body
# ============================================================
def test_cx_to_local_strips_readonly_fields():
    remote = {
        "name": AGENT_PATH,
        "displayName": "TestAgent",
        "defaultLanguageCode": "es",
        "createTime": "2025-01-01T00:00:00Z",
        "updateTime": "2025-01-02T00:00:00Z",
        "tokenCount": 123,
        "satisfiesPzi": True,
    }
    local = cx_to_local(remote)
    for f in PULL_STRIP_FIELDS:
        assert f not in local, f"{f} debio ser strippeado"
    assert local["displayName"] == "TestAgent"
    assert local["defaultLanguageCode"] == "es"


def test_cx_to_local_transforms_start_playbook_to_id():
    remote = {"displayName": "A", "startPlaybook": PB_PATH}
    local = cx_to_local(remote)
    assert "startPlaybook" not in local
    assert local["start_playbook_id"] == "pb-uuid-123"


def test_cx_to_local_preserves_unknown_fields():
    """Si CX devuelve algo que no esperabamos, lo preservamos para que el
    siguiente push lo pueda diffear. Forward-compat."""
    remote = {"displayName": "A", "newFutureField": {"some": "value"}}
    local = cx_to_local(remote)
    assert local["newFutureField"] == {"some": "value"}


def test_cx_to_local_emits_canonical_order():
    # Remote intencionalmente desordenado.
    remote = {
        "enableMultiLanguageTraining": True,
        "timeZone": "Europe/Madrid",
        "displayName": "A",
        "defaultLanguageCode": "es",
        "advancedSettings": {},
        "speechToTextSettings": {},
        "startPlaybook": PB_PATH,
    }
    keys = list(cx_to_local(remote).keys())
    expected = [
        "displayName",
        "defaultLanguageCode",
        "timeZone",
        "speechToTextSettings",
        "advancedSettings",
        "start_playbook_id",
        "enableMultiLanguageTraining",
    ]
    assert keys == expected


def test_cx_to_local_unknown_keys_appended_after_canonical():
    remote = {
        "newFutureField": 1,
        "displayName": "A",
        "anotherFuture": 2,
    }
    keys = list(cx_to_local(remote).keys())
    # displayName (canonico) primero; los desconocidos preservan su orden relativo al final
    assert keys[0] == "displayName"
    assert keys[1:] == ["newFutureField", "anotherFuture"]


# ============================================================
# surgical_write — preservacion + idempotencia
# ============================================================
def test_surgical_write_preserves_non_cx_blocks_and_comments(tmp_path):
    src = tmp_path / "agent.yaml"
    src.write_text(
        "# Top comment block\n"
        "# describing the file purpose.\n"
        "project: floristeria-petal-digital\n"
        "location: europe-west1\n"
        "\n"
        "api:\n"
        "  base_v3beta1: https://example.test/v3beta1\n"
        "  required_headers:\n"
        "    x-goog-user-project: floristeria-petal-digital\n"
        "\n"
        "# Comment immediately before the CX block\n"
        "agent_definition:\n"
        "  displayName: OldName\n"
        "  defaultLanguageCode: en\n"
    )
    new_def = {"displayName": "NewName", "defaultLanguageCode": "es"}
    _, new_text = surgical_write(src, new_def)

    # Bloques no-CX preservados (cuerpo + comentarios)
    assert "# Top comment block" in new_text
    assert "# describing the file purpose." in new_text
    assert "project: floristeria-petal-digital" in new_text
    assert "location: europe-west1" in new_text
    assert "base_v3beta1: https://example.test/v3beta1" in new_text
    assert "x-goog-user-project: floristeria-petal-digital" in new_text
    assert "# Comment immediately before the CX block" in new_text

    # Bloque CX reemplazado
    assert "OldName" not in new_text
    assert "NewName" in new_text
    assert "defaultLanguageCode: es" in new_text
    assert "defaultLanguageCode: en" not in new_text

    # MARKER inyectado
    assert MARKER in new_text


def test_surgical_write_idempotent_when_marker_present(tmp_path):
    """En la segunda pasada (MARKER ya existe), no duplica el MARKER ni
    descarta el head; corta exactamente desde la linea del MARKER."""
    src = tmp_path / "agent.yaml"
    src.write_text(
        "project: foo\n"
        "\n"
        f"{MARKER}\n"
        "agent_definition:\n"
        "  displayName: First\n"
    )
    _, after_first = surgical_write(src, {"displayName": "Second"})
    src.write_text(after_first)
    _, after_second = surgical_write(src, {"displayName": "Third"})

    assert after_first.count(MARKER) == 1
    assert after_second.count(MARKER) == 1
    assert "First" not in after_second
    assert "Second" not in after_second
    assert "Third" in after_second
    assert "project: foo" in after_second  # head intacto


def test_surgical_write_raises_when_no_marker_nor_agent_definition(tmp_path):
    src = tmp_path / "agent.yaml"
    src.write_text("project: foo\napi:\n  base_v3beta1: x\n")
    import pytest
    with pytest.raises(RuntimeError, match="no se encontro"):
        surgical_write(src, {"displayName": "X"})


# ============================================================
# Round-trip end-to-end
# ============================================================
def test_round_trip_pull_to_push_reports_unchanged():
    """pull(remote) -> local -> resolve_local_body -> diff vs remote == no-op.
    Garantiza que `pull_agent_config.py` produce un YAML que el siguiente
    `push_agent_config.py --dry-run` reporta como `unchanged=1`."""
    remote = {
        "name": AGENT_PATH,
        "displayName": "Floristeria-Petal",
        "defaultLanguageCode": "es",
        "timeZone": "America/Los_Angeles",
        "speechToTextSettings": {},
        "advancedSettings": {
            "audioExportGcsDestination": {},
            "speechSettings": {
                "endpointerSensitivity": 90,
                "noSpeechTimeout": "5s",
            },
            "loggingSettings": {},
        },
        "startPlaybook": f"{AGENT_PATH}/playbooks/00000000-0000-0000-0000-000000000000",
        "enableMultiLanguageTraining": True,
        "satisfiesPzi": True,
        "createTime": "2025-01-01T00:00:00Z",
    }
    local = cx_to_local(remote)
    body = resolve_local_body(CFG, local)
    result = diff_resource(body, remote, ignore_fields=AGENT_IGNORE_FIELDS)
    assert result.needs_update is False, (
        f"Round-trip dirty: mask={result.update_mask}, payload={result.patch_payload}"
    )
