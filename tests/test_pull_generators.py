"""Tests unitarios para src/pull_generators.py."""
from __future__ import annotations

import pytest
import yaml

from src.diff import diff_resource
from src.pull_generators import (
    PULL_STRIP_FIELDS,
    cx_to_local,
    dump_yaml,
    slugify,
)
from src.push_generators import GENERATOR_IGNORE_FIELDS


AGENT_PATH = "projects/test-project/locations/europe-west1/agents/agent-uuid"


def test_cx_to_local_strips_readonly_fields():
    remote = {
        "name": f"{AGENT_PATH}/generators/g-1",
        "displayName": "GreetingGen",
        "promptText": {"text": "Saluda al usuario $nombre"},
        "modelParameter": {"model": "gemini-1.5", "temperature": 0.5},
        "createTime": "2026-05-01T00:00:00Z",
    }
    local = cx_to_local(remote)
    for f in PULL_STRIP_FIELDS:
        assert f not in local
    assert local["displayName"] == "GreetingGen"
    assert local["promptText"]["text"] == "Saluda al usuario $nombre"


def test_cx_to_local_preserves_unknown_fields():
    remote = {"displayName": "X", "newField": 42}
    assert cx_to_local(remote)["newField"] == 42


def test_cx_to_local_emits_canonical_order():
    remote = {
        "placeholders": [],
        "modelParameter": {},
        "promptText": {},
        "displayName": "X",
        "newField": 1,
    }
    keys = list(cx_to_local(remote).keys())
    assert keys.index("displayName") < keys.index("promptText")
    assert keys.index("promptText") < keys.index("modelParameter")
    assert keys.index("modelParameter") < keys.index("placeholders")
    assert keys[-1] == "newField"


@pytest.mark.parametrize("display_name,expected", [
    ("GreetingGen", "greetinggen"),
    ("Greeting Generator", "greeting_generator"),
    ("Gen/V2", "gen_v2"),
])
def test_slugify_variations(display_name, expected):
    assert slugify(display_name) == expected


def test_slugify_fallback():
    assert slugify("") == "unnamed"


def test_dump_yaml_preserves_placeholders():
    """Los $variable de promptText deben quedar como strings literales."""
    body = {
        "displayName": "Gen",
        "promptText": {"text": "Hola $nombre, ¿qué tal?"},
    }
    reloaded = yaml.safe_load(dump_yaml(body))
    assert reloaded == body
    assert "$nombre" in dump_yaml(body)


def test_round_trip_pull_to_push_reports_unchanged():
    remote = {
        "name": f"{AGENT_PATH}/generators/g-1",
        "displayName": "GreetingGen",
        "promptText": {"text": "Saluda a $usuario"},
        "modelParameter": {
            "model": "gemini-1.5",
            "temperature": 0.5,
            "maxDecodeSteps": 200,
        },
        "placeholders": [{"id": "usuario", "name": "usuario"}],
        "createTime": "2026-05-01T00:00:00Z",
    }
    local = cx_to_local(remote)
    result = diff_resource(local, remote, ignore_fields=GENERATOR_IGNORE_FIELDS)
    assert result.needs_update is False
