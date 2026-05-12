"""Tests unitarios para src/pull_environments.py."""
from __future__ import annotations

import pytest
import yaml

from src.diff import diff_resource
from src.pull_environments import (
    PULL_STRIP_FIELDS,
    cx_to_local,
    dump_yaml,
    slugify,
)
from src.push_environments import ENVIRONMENT_IGNORE_FIELDS


AGENT_PATH = "projects/test-project/locations/europe-west1/agents/agent-uuid"


def test_cx_to_local_strips_readonly_including_lastUpdateTime():
    remote = {
        "name": f"{AGENT_PATH}/environments/e-1",
        "displayName": "Production",
        "description": "Live env",
        "versionConfigs": [{"version": "flow-x/versions/1"}],
        "createTime": "2026-05-01T00:00:00Z",
        "updateTime": "2026-05-02T00:00:00Z",
        "lastUpdateTime": "2026-05-02T00:00:00Z",  # specific to Environments
    }
    local = cx_to_local(remote)
    for f in PULL_STRIP_FIELDS:
        assert f not in local
    # lastUpdateTime es read-only en Environments (no en otros recursos).
    assert "lastUpdateTime" not in local
    assert local["displayName"] == "Production"
    assert local["versionConfigs"][0]["version"] == "flow-x/versions/1"


def test_cx_to_local_preserves_unknown_fields():
    remote = {"displayName": "X", "newField": 99}
    assert cx_to_local(remote)["newField"] == 99


def test_cx_to_local_emits_canonical_order():
    remote = {
        "webhookConfig": {},
        "testCasesConfig": {},
        "versionConfigs": [],
        "description": "d",
        "displayName": "X",
        "newField": 1,
    }
    keys = list(cx_to_local(remote).keys())
    assert keys.index("displayName") < keys.index("description")
    assert keys.index("description") < keys.index("versionConfigs")
    assert keys[-1] == "newField"


@pytest.mark.parametrize("display_name,expected", [
    ("Production", "production"),
    ("Default Environment", "default_environment"),
    ("Staging/v2", "staging_v2"),
])
def test_slugify_variations(display_name, expected):
    assert slugify(display_name) == expected


def test_slugify_fallback():
    assert slugify("") == "unnamed"


def test_dump_yaml_roundtrip():
    body = {
        "displayName": "Production",
        "description": "Live",
        "versionConfigs": [{"version": "projects/.../flows/f/versions/3"}],
    }
    reloaded = yaml.safe_load(dump_yaml(body))
    assert reloaded == body


def test_round_trip_pull_to_push_unchanged():
    remote = {
        "name": f"{AGENT_PATH}/environments/e-prod",
        "displayName": "Production",
        "description": "Live env",
        "versionConfigs": [
            {"version": f"{AGENT_PATH}/flows/flow-x/versions/1"},
        ],
        "createTime": "2026-05-01T00:00:00Z",
        "lastUpdateTime": "2026-05-02T00:00:00Z",
    }
    local = cx_to_local(remote)
    result = diff_resource(local, remote, ignore_fields=ENVIRONMENT_IGNORE_FIELDS)
    assert result.needs_update is False
