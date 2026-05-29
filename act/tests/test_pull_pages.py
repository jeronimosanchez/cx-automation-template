"""Tests unitarios para act/pull_pages.py.

Cubre cx_to_local con inyeccion de parent_flow_displayName, slugify
cross-flow para evitar colisiones, y round-trip mock contra
push_pages.diff_resource + split_local_fields.
"""
from __future__ import annotations

import pytest
import yaml

from act.diff import diff_resource
from act.pull_pages import (
    PULL_STRIP_FIELDS,
    cx_to_local,
    dump_yaml,
    slugify,
)
from act.push_pages import PAGE_IGNORE_FIELDS, split_local_fields


AGENT_PATH = "projects/test-project/locations/europe-west1/agents/agent-uuid"
FLOW_PATH = f"{AGENT_PATH}/flows/flow-1"


def test_cx_to_local_strips_readonly_and_injects_parent():
    remote = {
        "name": f"{FLOW_PATH}/pages/p-1",
        "displayName": "Welcome Page",
        "entryFulfillment": {"messages": []},
        "createTime": "2026-05-01T00:00:00Z",
        "updateTime": "2026-05-02T00:00:00Z",
    }
    local = cx_to_local(remote, parent_flow_display_name="Default Start Flow")
    for f in PULL_STRIP_FIELDS:
        assert f not in local
    assert local["parent_flow_displayName"] == "Default Start Flow"
    assert local["displayName"] == "Welcome Page"


def test_cx_to_local_parent_flow_first_then_displayname():
    """parent_flow_displayName debe aparecer ANTES que displayName en el YAML."""
    remote = {"displayName": "P1", "entryFulfillment": {}}
    keys = list(cx_to_local(remote, parent_flow_display_name="F1").keys())
    assert keys.index("parent_flow_displayName") < keys.index("displayName")


def test_cx_to_local_preserves_unknown_fields():
    remote = {"displayName": "P", "newFutureField": 99}
    local = cx_to_local(remote, parent_flow_display_name="F")
    assert local["newFutureField"] == 99


@pytest.mark.parametrize("flow_dn,page_dn,expected", [
    ("Default Start Flow", "Welcome Page", "default_start_flow__welcome_page"),
    ("Flow A", "Page A", "flow_a__page_a"),
    ("Flow/B", "Page B", "flow_b__page_b"),
])
def test_slug_avoids_cross_flow_collisions(flow_dn, page_dn, expected):
    """El slug compuesto evita que 2 pages con mismo nombre en flows
    distintos se sobrescriban en disco."""
    slug = f"{slugify(flow_dn)}__{slugify(page_dn)}"
    assert slug == expected


def test_two_pages_same_name_different_flows_yield_different_slugs():
    """Caso real: 'Start Page' en Flow A y en Flow B."""
    s1 = f"{slugify('Flow A')}__{slugify('Start Page')}"
    s2 = f"{slugify('Flow B')}__{slugify('Start Page')}"
    assert s1 != s2


def test_dump_yaml_roundtrip():
    body = {
        "parent_flow_displayName": "Default Start Flow",
        "displayName": "Welcome",
        "entryFulfillment": {"messages": [{"text": {"text": ["¡Hola!"]}}]},
    }
    reloaded = yaml.safe_load(dump_yaml(body))
    assert reloaded == body


def test_round_trip_pull_to_push_unchanged():
    """cx_to_local(remote, parent) -> split_local_fields() -> diff vs remote == no-op."""
    remote = {
        "name": f"{FLOW_PATH}/pages/p-welcome",
        "displayName": "Welcome",
        "entryFulfillment": {
            "messages": [{"text": {"text": ["Hola"]}}],
        },
        "createTime": "2026-05-01T00:00:00Z",
    }
    local = cx_to_local(remote, parent_flow_display_name="Default Start Flow")
    # Lo que push_pages haria: separar parent_flow_displayName del body que va a API.
    api_body, parent_flow = split_local_fields(local)
    assert parent_flow == "Default Start Flow"
    assert "parent_flow_displayName" not in api_body
    result = diff_resource(api_body, remote, ignore_fields=PAGE_IGNORE_FIELDS)
    assert result.needs_update is False, (
        f"Round-trip dirty: mask={result.update_mask}, payload={result.patch_payload}"
    )
