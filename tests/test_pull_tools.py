"""Tests unitarios para src/pull_tools.py.

Sin red. Sin auth. Cubre cx_to_local (strip + split openapi), is_builtin
filter, slugify, dump_yaml y round-trip end-to-end con archivos reales
via push_tools.load_tool_yaml + diff_resource.
"""
from __future__ import annotations

import pytest
import yaml

from src.diff import diff_resource
from src.pull_tools import (
    BUILTIN_TYPE,
    PULL_STRIP_FIELDS,
    cx_to_local,
    dump_yaml,
    is_builtin,
    slugify,
)
from src.push_tools import TOOL_IGNORE_FIELDS, load_tool_yaml


AGENT_PATH = "projects/test-project/locations/europe-west1/agents/agent-uuid"

OPENAPI_SAMPLE = """\
openapi: 3.0.0
info:
  title: SampleTool
  version: 1.0.0
servers:
  - url: https://example.test
paths:
  /exec:
    get:
      operationId: doStuff
      responses:
        '200':
          description: OK
"""


# ============================================================
# is_builtin
# ============================================================
def test_is_builtin_detects_builtin():
    assert is_builtin({"toolType": BUILTIN_TYPE}) is True


def test_is_builtin_returns_false_for_customized():
    assert is_builtin({"toolType": "CUSTOMIZED_TOOL"}) is False
    assert is_builtin({}) is False


# ============================================================
# cx_to_local — strip + split openapi
# ============================================================
def test_cx_to_local_strips_readonly_fields():
    remote = {
        "name": f"{AGENT_PATH}/tools/t-1",
        "displayName": "PetalDataTool",
        "description": "Tool descr",
        "toolType": "CUSTOMIZED_TOOL",
        "openApiSpec": {"textSchema": OPENAPI_SAMPLE},
        "createTime": "2026-05-01T00:00:00Z",
        "updateTime": "2026-05-02T00:00:00Z",
    }
    meta, openapi_text = cx_to_local(remote, openapi_filename="petaldatatool_openapi.yaml")
    for f in PULL_STRIP_FIELDS:
        assert f not in meta


def test_cx_to_local_splits_openapi_to_file():
    remote = {
        "displayName": "T",
        "toolType": "CUSTOMIZED_TOOL",
        "openApiSpec": {"textSchema": OPENAPI_SAMPLE},
    }
    meta, openapi_text = cx_to_local(remote, openapi_filename="t_openapi.yaml")
    # El metadata NO contiene openApiSpec inline
    assert "openApiSpec" not in meta
    # Referencia al archivo separado
    assert meta["openapi_spec_file"] == "t_openapi.yaml"
    # El texto OpenAPI vuelve como string crudo, intacto
    assert openapi_text == OPENAPI_SAMPLE


def test_cx_to_local_without_openapi_omits_file_ref():
    """Si CX devuelve un tool sin openApiSpec (raro), no se añade openapi_spec_file."""
    remote = {"displayName": "T", "toolType": "CUSTOMIZED_TOOL"}
    meta, openapi_text = cx_to_local(remote, openapi_filename="t_openapi.yaml")
    assert "openapi_spec_file" not in meta
    assert openapi_text == ""


def test_cx_to_local_emits_canonical_order():
    remote = {
        "toolType": "CUSTOMIZED_TOOL",
        "description": "d",
        "openApiSpec": {"textSchema": OPENAPI_SAMPLE},
        "displayName": "T",
        "newField": 1,
    }
    meta, _ = cx_to_local(remote, openapi_filename="t_openapi.yaml")
    keys = list(meta.keys())
    assert keys.index("displayName") < keys.index("description")
    assert keys.index("description") < keys.index("toolType")
    assert keys.index("toolType") < keys.index("openapi_spec_file")
    assert keys[-1] == "newField"


def test_cx_to_local_preserves_unknown_fields():
    remote = {
        "displayName": "T",
        "toolType": "CUSTOMIZED_TOOL",
        "openApiSpec": {"textSchema": OPENAPI_SAMPLE},
        "newFutureField": {"foo": 1},
    }
    meta, _ = cx_to_local(remote, openapi_filename="t_openapi.yaml")
    assert meta["newFutureField"] == {"foo": 1}


# ============================================================
# slugify
# ============================================================
@pytest.mark.parametrize("display_name,expected", [
    ("PetalDataTool", "petaldatatool"),
    ("My Tool", "my_tool"),
    ("Tool/V2", "tool_v2"),
])
def test_slugify_variations(display_name, expected):
    assert slugify(display_name) == expected


# ============================================================
# Round-trip END-TO-END con archivos reales
# ============================================================
def test_round_trip_writes_two_files_and_push_reads_them(tmp_path, monkeypatch):
    """pull(remote) -> escribe meta+openapi -> push.load_tool_yaml(meta_path)
    reconstruye body con openApiSpec.textSchema == OPENAPI_SAMPLE.
    Ese body, diffeado contra CX, reporta needs_update=False.
    """
    remote = {
        "name": f"{AGENT_PATH}/tools/t-1",
        "displayName": "PetalDataTool",
        "description": "Tool para consultar perfil/inventario",
        "toolType": "CUSTOMIZED_TOOL",
        "openApiSpec": {"textSchema": OPENAPI_SAMPLE},
        "createTime": "2026-05-01T00:00:00Z",
    }
    slug = slugify(remote["displayName"])
    openapi_filename = f"{slug}_openapi.yaml"
    meta, openapi_text = cx_to_local(remote, openapi_filename=openapi_filename)

    # Simular escritura de pull en disco
    meta_path = tmp_path / f"{slug}.yaml"
    spec_path = tmp_path / openapi_filename
    meta_path.write_text(dump_yaml(meta))
    spec_path.write_text(openapi_text)

    # push.load_tool_yaml lee meta + inyecta el textSchema del openapi file
    reconstructed = load_tool_yaml(meta_path)

    # El body reconstruido debe ser equivalente al remote (sin read-only) para diff
    result = diff_resource(reconstructed, remote, ignore_fields=TOOL_IGNORE_FIELDS)
    assert result.needs_update is False, (
        f"Round-trip dirty: mask={result.update_mask}, payload={result.patch_payload}"
    )


def test_round_trip_preserves_openapi_text_byte_for_byte(tmp_path):
    """El contenido del openapi_spec_file debe ser idéntico al textSchema original
    (re-cargable y comparable byte-a-byte como string)."""
    remote = {
        "displayName": "T",
        "toolType": "CUSTOMIZED_TOOL",
        "openApiSpec": {"textSchema": OPENAPI_SAMPLE},
    }
    meta, openapi_text = cx_to_local(remote, openapi_filename="t_openapi.yaml")
    spec_path = tmp_path / "t_openapi.yaml"
    spec_path.write_text(openapi_text)
    assert spec_path.read_text() == OPENAPI_SAMPLE
