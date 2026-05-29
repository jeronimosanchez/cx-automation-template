"""Tests unitarios para act/pull_webhooks.py.

Sin red. Sin auth. Cubre cx_to_local (strip + order + forward-compat),
slugify, dump_yaml y round-trip mock vs push_webhooks.diff_resource.
"""
from __future__ import annotations

import pytest
import yaml

from act.diff import diff_resource
from act.pull_webhooks import (
    PULL_STRIP_FIELDS,
    _CANONICAL_ORDER,
    cx_to_local,
    dump_yaml,
    slugify,
)
from act.push_webhooks import WEBHOOK_IGNORE_FIELDS


AGENT_PATH = "projects/test-project/locations/europe-west1/agents/agent-uuid"


def test_cx_to_local_strips_readonly_fields():
    remote = {
        "name": f"{AGENT_PATH}/webhooks/wh-1",
        "displayName": "OrderHook",
        "genericWebService": {"uri": "https://example.test/hook"},
        "timeout": "5s",
        "createTime": "2026-05-01T00:00:00Z",
        "updateTime": "2026-05-02T00:00:00Z",
    }
    local = cx_to_local(remote)
    for f in PULL_STRIP_FIELDS:
        assert f not in local
    assert local["displayName"] == "OrderHook"
    assert local["genericWebService"]["uri"] == "https://example.test/hook"


def test_cx_to_local_preserves_unknown_fields():
    remote = {"displayName": "X", "newFutureField": 42}
    assert cx_to_local(remote)["newFutureField"] == 42


def test_cx_to_local_emits_canonical_order():
    remote = {
        "disabled": False,
        "timeout": "5s",
        "displayName": "X",
        "genericWebService": {"uri": "u"},
        "newField": 1,
    }
    keys = list(cx_to_local(remote).keys())
    assert keys.index("displayName") < keys.index("genericWebService")
    assert keys.index("genericWebService") < keys.index("timeout")
    assert keys.index("timeout") < keys.index("disabled")
    assert keys[-1] == "newField"


@pytest.mark.parametrize("display_name,expected", [
    ("OrderHook", "orderhook"),
    ("Order Hook", "order_hook"),
    ("API/V2", "api_v2"),
    ("  trim  ", "trim"),
])
def test_slugify_variations(display_name, expected):
    assert slugify(display_name) == expected


def test_slugify_fallback():
    assert slugify("") == "unnamed"
    assert slugify("___") == "unnamed"


def test_dump_yaml_roundtrip():
    body = {
        "displayName": "OrderHook",
        "genericWebService": {
            "uri": "https://example.test/hook",
            "requestHeaders": {"x-api-key": "secret"},
        },
        "timeout": "5s",
    }
    reloaded = yaml.safe_load(dump_yaml(body))
    assert reloaded == body


def test_round_trip_pull_to_push_reports_unchanged():
    remote = {
        "name": f"{AGENT_PATH}/webhooks/wh-1",
        "displayName": "OrderHook",
        "genericWebService": {
            "uri": "https://example.test/hook",
            "httpMethod": "POST",
            "requestHeaders": {"x-api-key": "secret"},
        },
        "timeout": "5s",
        "createTime": "2026-05-01T00:00:00Z",
    }
    local = cx_to_local(remote)
    result = diff_resource(local, remote, ignore_fields=WEBHOOK_IGNORE_FIELDS)
    assert result.needs_update is False
