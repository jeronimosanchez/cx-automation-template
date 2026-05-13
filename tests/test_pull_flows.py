"""Tests unitarios para src/pull_flows.py."""
from __future__ import annotations

import pytest
import yaml

from src.diff import diff_resource
from src.pull_flows import (
    PULL_STRIP_FIELDS,
    cx_to_local,
    dump_yaml,
    slugify,
)
from src.push_flows import FLOW_IGNORE_FIELDS


AGENT_PATH = "projects/test-project/locations/europe-west1/agents/agent-uuid"


def test_cx_to_local_strips_readonly_fields():
    remote = {
        "name": f"{AGENT_PATH}/flows/f-1",
        "displayName": "Default Start Flow",
        "description": "Root flow",
        "transitionRoutes": [{"intent": "i-welcome", "triggerFulfillment": {}}],
        "createTime": "2026-05-01T00:00:00Z",
        "updateTime": "2026-05-02T00:00:00Z",
    }
    local = cx_to_local(remote)
    for f in PULL_STRIP_FIELDS:
        assert f not in local
    assert local["displayName"] == "Default Start Flow"
    assert local["description"] == "Root flow"
    assert local["transitionRoutes"][0]["intent"] == "i-welcome"


def test_cx_to_local_preserves_unknown_fields():
    remote = {"displayName": "X", "newFutureField": 42}
    assert cx_to_local(remote)["newFutureField"] == 42


def test_cx_to_local_emits_canonical_order():
    remote = {
        "advancedSettings": {},
        "nluSettings": {"modelType": "MODEL_TYPE_ADVANCED"},
        "transitionRouteGroups": [],
        "eventHandlers": [],
        "transitionRoutes": [],
        "description": "d",
        "displayName": "F",
        "newField": 1,
    }
    keys = list(cx_to_local(remote).keys())
    assert keys.index("displayName") < keys.index("description")
    assert keys.index("description") < keys.index("transitionRoutes")
    assert keys.index("transitionRoutes") < keys.index("eventHandlers")
    assert keys.index("eventHandlers") < keys.index("transitionRouteGroups")
    assert keys.index("transitionRouteGroups") < keys.index("nluSettings")
    assert keys.index("nluSettings") < keys.index("advancedSettings")
    assert keys[-1] == "newField"


def test_cx_to_local_preserves_nlu_settings():
    """nluSettings es un sub-dict importante (modelType, classificationThreshold)."""
    remote = {
        "displayName": "F",
        "nluSettings": {
            "modelType": "MODEL_TYPE_ADVANCED",
            "classificationThreshold": 0.3,
        },
    }
    local = cx_to_local(remote)
    assert local["nluSettings"]["modelType"] == "MODEL_TYPE_ADVANCED"
    assert local["nluSettings"]["classificationThreshold"] == 0.3


@pytest.mark.parametrize("display_name,expected", [
    ("Default Start Flow", "default_start_flow"),
    ("Flow A", "flow_a"),
    ("Flow/V2", "flow_v2"),
])
def test_slugify_variations(display_name, expected):
    assert slugify(display_name) == expected


def test_slugify_fallback():
    assert slugify("") == "unnamed"


def test_dump_yaml_preserves_nested_structures():
    body = {
        "displayName": "F",
        "transitionRoutes": [
            {
                "intent": f"{AGENT_PATH}/intents/i-1",
                "triggerFulfillment": {
                    "messages": [{"text": {"text": ["Hola"]}}],
                },
                "targetPage": f"{AGENT_PATH}/flows/f-1/pages/p-1",
            }
        ],
    }
    reloaded = yaml.safe_load(dump_yaml(body))
    assert reloaded == body


def test_round_trip_pull_to_push_reports_unchanged():
    """cx_to_local(remote) -> diff vs remote == no-op."""
    remote = {
        "name": f"{AGENT_PATH}/flows/f-1",
        "displayName": "Default Start Flow",
        "description": "Root flow",
        "transitionRoutes": [
            {
                "intent": f"{AGENT_PATH}/intents/i-welcome",
                "triggerFulfillment": {
                    "messages": [{"text": {"text": ["Hola"]}}],
                },
            }
        ],
        "nluSettings": {
            "modelType": "MODEL_TYPE_ADVANCED",
            "classificationThreshold": 0.3,
        },
        "createTime": "2026-05-01T00:00:00Z",
    }
    local = cx_to_local(remote)
    result = diff_resource(local, remote, ignore_fields=FLOW_IGNORE_FIELDS)
    assert result.needs_update is False, (
        f"Round-trip dirty: mask={result.update_mask}, payload={result.patch_payload}"
    )


def test_round_trip_minimal_flow():
    """Flow mínimo (solo displayName) — caso de Default Start Flow vacío."""
    remote = {
        "name": f"{AGENT_PATH}/flows/f-1",
        "displayName": "Default Start Flow",
    }
    local = cx_to_local(remote)
    result = diff_resource(local, remote, ignore_fields=FLOW_IGNORE_FIELDS)
    assert result.needs_update is False
