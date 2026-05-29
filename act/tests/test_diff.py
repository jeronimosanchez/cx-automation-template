"""Tests unitarios para act/diff.py.

Sin red. Sin side effects. Cubre los 7 casos pedidos por el brief
Sprint 2 + casos adicionales (cambio de tipo, multi-cambio, payload
anidado, errores de input).
"""

from __future__ import annotations

import os
import sys

import pytest

# Permitir `from act.diff import ...` cuando se ejecuta `pytest tests/`
# desde la raiz del repo o desde tests/.
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from act.diff import DiffResult, diff_resource  # noqa: E402


# ============================================================
# Caso 1 — Recursos identicos -> no-op
# ============================================================
def test_identical_returns_noop():
    local = {"displayName": "X", "actions": [1, 2, 3]}
    remote = {"displayName": "X", "actions": [1, 2, 3]}

    r = diff_resource(local, remote)

    assert r.needs_update is False
    assert r.update_mask == []
    assert r.patch_payload == {}


def test_identical_empty_dicts_returns_noop():
    r = diff_resource({}, {})
    assert r.needs_update is False
    assert r.update_mask == []
    assert r.patch_payload == {}


# ============================================================
# Caso 2 — Cambio en campo plano (string)
# ============================================================
def test_flat_string_change():
    local = {"displayName": "new"}
    remote = {"displayName": "old"}

    r = diff_resource(local, remote)

    assert r.needs_update is True
    assert r.update_mask == ["displayName"]
    assert r.patch_payload == {"displayName": "new"}


def test_flat_int_change():
    local = {"limit": 10}
    remote = {"limit": 5}

    r = diff_resource(local, remote)

    assert r.needs_update is True
    assert r.update_mask == ["limit"]
    assert r.patch_payload == {"limit": 10}


# ============================================================
# Caso 3 — Cambio en lista (orden distinto)
# ============================================================
def test_list_different_order_is_diff():
    local = {"steps": ["a", "b", "c"]}
    remote = {"steps": ["c", "b", "a"]}

    r = diff_resource(local, remote)

    assert r.needs_update is True
    assert r.update_mask == ["steps"]
    assert r.patch_payload == {"steps": ["a", "b", "c"]}


def test_list_same_order_is_noop():
    local = {"steps": ["a", "b", "c"]}
    remote = {"steps": ["a", "b", "c"]}

    r = diff_resource(local, remote)

    assert r.needs_update is False


def test_list_with_dict_elements_diff():
    local = {"actions": [{"k": 1}, {"k": 2}]}
    remote = {"actions": [{"k": 1}, {"k": 9}]}

    r = diff_resource(local, remote)

    assert r.needs_update is True
    assert r.update_mask == ["actions"]
    assert r.patch_payload == {"actions": [{"k": 1}, {"k": 2}]}


# ============================================================
# Caso 4 — Cambio en dict anidado
# ============================================================
def test_nested_dict_change():
    local = {"instruction": {"steps": ["s1"], "lang": "es"}}
    remote = {"instruction": {"steps": ["s1"], "lang": "en"}}

    r = diff_resource(local, remote)

    assert r.needs_update is True
    assert r.update_mask == ["instruction.lang"]
    assert r.patch_payload == {"instruction": {"lang": "es"}}


def test_deeply_nested_change():
    local = {"a": {"b": {"c": {"v": 2}}}}
    remote = {"a": {"b": {"c": {"v": 1}}}}

    r = diff_resource(local, remote)

    assert r.needs_update is True
    assert r.update_mask == ["a.b.c.v"]
    assert r.patch_payload == {"a": {"b": {"c": {"v": 2}}}}


# ============================================================
# Caso 5 — ignore_fields excluye correctamente
# ============================================================
def test_ignore_fields_top_level():
    local = {"name": "n1", "tokenCount": 100, "displayName": "X"}
    remote = {"name": "n2", "tokenCount": 200, "displayName": "X"}

    r = diff_resource(
        local,
        remote,
        ignore_fields=["name", "tokenCount", "createTime", "updateTime"],
    )

    assert r.needs_update is False
    assert r.update_mask == []
    assert r.patch_payload == {}


def test_ignore_fields_prefix_match():
    """ignore=['meta'] tambien excluye `meta.x`, `meta.x.y`..."""
    local = {"meta": {"x": 1, "y": 2}, "real": "a"}
    remote = {"meta": {"x": 9, "y": 8}, "real": "a"}

    r = diff_resource(local, remote, ignore_fields=["meta"])

    assert r.needs_update is False


def test_ignore_fields_does_not_swallow_unrelated_changes():
    local = {"name": "n1", "displayName": "X"}
    remote = {"name": "n2", "displayName": "Y"}

    r = diff_resource(local, remote, ignore_fields=["name"])

    assert r.needs_update is True
    assert r.update_mask == ["displayName"]
    assert r.patch_payload == {"displayName": "X"}


def test_ignore_fields_exact_does_not_match_nested_same_name():
    """ignore=['name'] cubre top-level pero NO `foo.name` interno."""
    local = {"foo": {"name": "inner-new"}}
    remote = {"foo": {"name": "inner-old"}}

    r = diff_resource(local, remote, ignore_fields=["name"])

    assert r.needs_update is True
    assert r.update_mask == ["foo.name"]


# ============================================================
# Caso 6 — Campo solo en remoto -> NO se toca (no DELETE via PATCH)
# ============================================================
def test_field_only_in_remote_is_ignored():
    local = {"a": 1}
    remote = {"a": 1, "extra_remote": "no-tocar", "tokenCount": 99}

    r = diff_resource(local, remote)

    assert r.needs_update is False
    assert r.update_mask == []
    assert r.patch_payload == {}


# ============================================================
# Caso 7 — Campo solo en local -> entra en mask + payload
# ============================================================
def test_field_only_in_local_enters_mask():
    local = {"a": 1, "new_field": "fresh"}
    remote = {"a": 1}

    r = diff_resource(local, remote)

    assert r.needs_update is True
    assert r.update_mask == ["new_field"]
    assert r.patch_payload == {"new_field": "fresh"}


# ============================================================
# Casos extra
# ============================================================
def test_multiple_changes_combine_in_payload():
    local = {"a": 1, "b": "new", "c": [1, 2], "d": {"x": 1}}
    remote = {"a": 1, "b": "old", "c": [3, 4], "d": {"x": 1}}

    r = diff_resource(local, remote)

    assert r.needs_update is True
    assert set(r.update_mask) == {"b", "c"}
    assert r.patch_payload == {"b": "new", "c": [1, 2]}


def test_multiple_nested_changes_merge_into_one_subtree():
    local = {"outer": {"a": 1, "b": 2}}
    remote = {"outer": {"a": 9, "b": 8}}

    r = diff_resource(local, remote)

    assert r.needs_update is True
    assert set(r.update_mask) == {"outer.a", "outer.b"}
    assert r.patch_payload == {"outer": {"a": 1, "b": 2}}


def test_type_change_dict_to_scalar():
    local = {"a": "scalar"}
    remote = {"a": {"nested": True}}

    r = diff_resource(local, remote)

    assert r.needs_update is True
    assert r.update_mask == ["a"]
    assert r.patch_payload == {"a": "scalar"}


def test_type_change_scalar_to_dict():
    local = {"a": {"nested": True}}
    remote = {"a": "scalar"}

    r = diff_resource(local, remote)

    assert r.needs_update is True
    assert r.update_mask == ["a"]
    assert r.patch_payload == {"a": {"nested": True}}


def test_returns_dataclass_instance():
    r = diff_resource({"a": 1}, {"a": 1})
    assert isinstance(r, DiffResult)


def test_invalid_input_raises_type_error():
    with pytest.raises(TypeError):
        diff_resource("not a dict", {})  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        diff_resource({}, [1, 2, 3])  # type: ignore[arg-type]


def test_realistic_example_payload():
    """Caso realista basado en el schema Examples descubierto en S60."""
    local = {
        "displayName": "ejemplo_registro",
        "actions": [
            {"userUtterance": {"text": "registra mi compra"}},
            {"agentUtterance": {"text": "Vale, dime el codigo de pedido."}},
        ],
        "playbookOutput": {
            "actionParameters": {"resultado": "ok"},
        },
    }
    remote = {
        "name": "projects/p/locations/l/agents/a/playbooks/pb/examples/e",
        "displayName": "ejemplo_registro",
        "tokenCount": 42,
        "createTime": "2025-01-01T00:00:00Z",
        "updateTime": "2025-02-02T00:00:00Z",
        "actions": [
            {"userUtterance": {"text": "registra mi compra"}},
            {"agentUtterance": {"text": "OBSOLETO"}},
        ],
        "playbookOutput": {
            "actionParameters": {"resultado": "ok"},
        },
    }

    r = diff_resource(
        local,
        remote,
        ignore_fields=["name", "tokenCount", "createTime", "updateTime"],
    )

    assert r.needs_update is True
    assert r.update_mask == ["actions"]
    assert r.patch_payload == {"actions": local["actions"]}
