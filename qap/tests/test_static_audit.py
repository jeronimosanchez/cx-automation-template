"""Tests para qap/static_audit.py — 14 checks, unit + integración.

Sin red. Sin LLM. Sin CX. Todos los tests son deterministas: dado el mismo
input, siempre el mismo output.

Dos capas:
  · Unit  — cada _check_*() en aislamiento con datos sintéticos mínimos.
  · Integ — audit() con un definitions/ ficticio en tmp_path + mock de petal_agent.
"""
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import yaml

import qap.static_audit as sa


# ── helpers ────────────────────────────────────────────────────────────────────

def _pb(steps=None, params_in=None, params_out=None, tools=None,
        display_name="TestPlaybook", refs=None):
    """Playbook dict mínimo válido."""
    instr_steps = []
    for s in (steps or []):
        instr_steps.append({"text": s})
    if refs:
        instr_steps.append({"text": " ".join(f"${{PLAYBOOK:{r}}}" for r in refs)})
    return {
        "displayName": display_name,
        "instruction": {"steps": instr_steps},
        "inputParameterDefinitions":  [{"name": n, "type": "STRING"} for n in (params_in  or [])],
        "outputParameterDefinitions": [{"name": n, "type": "STRING"} for n in (params_out or [])],
        "referencedTools": tools or [],
    }


def _write_examples(base: Path, name: str, examples: list) -> str:
    """Crea definitions/examples/<name>/*.yaml y devuelve la ruta."""
    ex_dir = base / name
    ex_dir.mkdir(parents=True, exist_ok=True)
    for i, data in enumerate(examples):
        (ex_dir / f"{i:02d}.yaml").write_text(yaml.dump(data, allow_unicode=True))
    return str(ex_dir)


# ── CX-25: tamaño ──────────────────────────────────────────────────────────────

def test_size_ok():
    assert sa._check_size(4999) == "✅"

def test_size_warn():
    assert "🟡" in sa._check_size(5001)

def test_size_urgent():
    assert "🔴" in sa._check_size(10001)


# ── CX-34: DSL density ────────────────────────────────────────────────────────

def test_dsl_ok():
    text = "\n".join(["consulta el inventario y responde"] * 10)
    pct, flag = sa._check_dsl(text)
    assert flag == "✅" and pct == 0.0

def test_dsl_warn():
    # 2 de 10 líneas tienen $ → 20 % (entre 15 % y 30 %)
    lines = ["usa $idioma para responder"] * 2 + ["consulta el sistema sin variables"] * 8
    pct, flag = sa._check_dsl("\n".join(lines))
    assert "🟡" in flag and 0.15 < pct <= 0.30

def test_dsl_fail():
    lines = ["$param1 = valor de ejemplo", "$param2 = otro dato"] * 5
    pct, flag = sa._check_dsl("\n".join(lines))
    assert "🔴" in flag and pct > 0.30

def test_dsl_empty_text():
    pct, flag = sa._check_dsl("")
    assert flag == "✅" and pct == 0.0


# ── CX-27: exit paths ─────────────────────────────────────────────────────────

def test_exit_ok():
    assert sa._check_exit("Si no puedes ayudar, escala al agente humano.") == "✅"

def test_exit_fail():
    assert "🔴" in sa._check_exit("Responde siempre de forma amable y positiva.")

@pytest.mark.parametrize("kw", ["handoff", "transferir", "escalación", "no puedo", "escalar"])
def test_exit_all_keywords(kw):
    assert sa._check_exit(f"El agente debe hacer {kw} cuando sea necesario.") == "✅"


# ── CX-31: params hygiene ─────────────────────────────────────────────────────

def test_params_ok():
    pb   = _pb(params_in=["idioma"], params_out=["resultado"])
    text = "Responde en $idioma y guarda en $resultado."
    assert sa._check_params(pb, text) == "✅"

def test_params_orphan():
    pb   = _pb(params_in=["idioma"])
    text = "Usa $idioma y también $desconocido."
    result = sa._check_params(pb, text)
    assert "🟡" in result and "desconocido" in result

def test_params_local_assignment_not_orphan():
    pb   = _pb()
    text = "$resumen = el cliente quiere flores rojas"
    assert sa._check_params(pb, text) == "✅"

def test_params_glue_not_orphan():
    # Escenario real de glue: $precio y $preciototal ambos en el texto →
    # $preciototal es un artefacto de regex (prefijo $precio + sufijo alfabético "total")
    pb   = _pb(params_out=["precio"])
    text = "El precio es $precio y el total es $preciototal."
    assert sa._check_params(pb, text) == "✅"


# ── CX-13: examples count ─────────────────────────────────────────────────────

def test_examples_dir_missing(tmp_path):
    n, ex_cnt, *_ = sa._check_examples(str(tmp_path / "no_existe"))
    assert n == 0 and "🔴" in ex_cnt

def test_examples_too_few(tmp_path):
    ex_dir = _write_examples(tmp_path, "pb", [{"description": "x"}] * 2)
    n, ex_cnt, *_ = sa._check_examples(ex_dir)
    assert "🟡" in ex_cnt and n == 2

def test_examples_ok(tmp_path):
    ex_dir = _write_examples(tmp_path, "pb", [{"description": "x"}] * 4)
    n, ex_cnt, *_ = sa._check_examples(ex_dir)
    assert ex_cnt == "✅" and n == 4


# ── CX-36: always_select ──────────────────────────────────────────────────────

def test_always_select_found(tmp_path):
    files = [
        {"selectionStrategy": "ALWAYS_SELECT", "actions": []},
        *[{"description": "var"}] * 3,
    ]
    ex_dir = _write_examples(tmp_path, "pb", files)
    _, _, always, *_ = sa._check_examples(ex_dir)
    assert always == "✅"

def test_always_select_missing_but_strategy_present(tmp_path):
    files = [{"selectionStrategy": "DYNAMICALLY_SELECT", "actions": []}] + [{"description": "x"}] * 3
    ex_dir = _write_examples(tmp_path, "pb", files)
    _, _, always, *_ = sa._check_examples(ex_dir)
    assert "🟡" in always

def test_always_select_nd_when_no_strategy_field(tmp_path):
    # Sin campo selectionStrategy en ningún example → inmedible → "➖ n/d"
    files = [{"description": "x"}] * 4
    ex_dir = _write_examples(tmp_path, "pb", files)
    _, _, always, *_ = sa._check_examples(ex_dir)
    assert "➖" in always


# ── CX-26: tool fail examples ─────────────────────────────────────────────────

def test_tool_fail_found_in_agent_utterance(tmp_path):
    files = [
        {"actions": [{"agentUtterance": {"text": "Lo siento, hay un error con la herramienta."}}]},
        *[{"description": "x"}] * 3,
    ]
    ex_dir = _write_examples(tmp_path, "pb", files)
    *_, fail, _ = sa._check_examples(ex_dir)
    assert fail == "✅"

def test_tool_fail_found_in_description(tmp_path):
    files = [{"description": "ejemplo de fallo de tool"}] + [{"description": "x"}] * 3
    ex_dir = _write_examples(tmp_path, "pb", files)
    *_, fail, _ = sa._check_examples(ex_dir)
    assert fail == "✅"

def test_tool_fail_missing(tmp_path):
    files = [{"description": "todo correcto, sin problemas"}] * 4
    ex_dir = _write_examples(tmp_path, "pb", files)
    *_, fail, _ = sa._check_examples(ex_dir)
    assert "🟡" in fail


# ── CX-36: negación ───────────────────────────────────────────────────────────

def test_negation_found(tmp_path):
    files = [
        {"actions": [{"userUtterance": {"text": "No quiero continuar, cancelar por favor."}}]},
        *[{"description": "x"}] * 3,
    ]
    ex_dir = _write_examples(tmp_path, "pb", files)
    *_, neg = sa._check_examples(ex_dir)
    assert neg == "✅"

def test_negation_missing(tmp_path):
    files = [{"description": "el usuario acepta todo"}] * 4
    ex_dir = _write_examples(tmp_path, "pb", files)
    *_, neg = sa._check_examples(ex_dir)
    assert "🟡" in neg


# ── CX-29: name length ────────────────────────────────────────────────────────

def test_name_len_ok():
    assert sa._check_name_len({"displayName": "A" * 64}, "test") == "✅"

def test_name_len_fail():
    result = sa._check_name_len({"displayName": "A" * 65}, "test")
    assert "🔴" in result and "65" in result

def test_name_len_no_field():
    assert sa._check_name_len({}, "test") == "✅"


# ── CX-33: snake_case ─────────────────────────────────────────────────────────

def test_snake_ok():
    pb = _pb(params_in=["nombre_completo", "idioma"], params_out=["precio_total"])
    assert sa._check_snake(pb) == "✅"

def test_snake_fail_camel():
    pb = _pb(params_in=["nombreCompleto"])
    result = sa._check_snake(pb)
    assert "🔴" in result and "nombreCompleto" in result

def test_snake_fail_uppercase():
    pb = _pb(params_out=["PRECIO"])
    result = sa._check_snake(pb)
    assert "🔴" in result


# ── CX-35: steps ──────────────────────────────────────────────────────────────

def test_steps_ok():
    pb = _pb(steps=["paso"] * 10)
    assert "✅" in sa._check_steps(pb)

def test_steps_warn():
    pb = _pb(steps=["paso"] * 20)
    assert "🟡" in sa._check_steps(pb)

def test_steps_fail():
    pb = _pb(steps=["paso"] * 30)
    assert "🔴" in sa._check_steps(pb)

def test_steps_singular():
    pb = _pb(steps=["paso"])
    result = sa._check_steps(pb)
    assert "✅" in result and "paso" in result and "pasos" not in result


# ── CX-28: ciclos de delegación ───────────────────────────────────────────────

def test_no_cycle():
    graph = {"A": {"B"}, "B": {"C"}, "C": set()}
    assert sa._build_cycles(graph) == set()

def test_simple_cycle():
    graph = {"A": {"B"}, "B": {"A"}}
    assert sa._build_cycles(graph) == {"A", "B"}

def test_longer_cycle():
    graph = {"A": {"B"}, "B": {"C"}, "C": {"A"}}
    assert sa._build_cycles(graph) == {"A", "B", "C"}

def test_self_cycle():
    graph = {"A": {"A"}}
    assert "A" in sa._build_cycles(graph)

def test_no_cycle_with_ref_outside_graph():
    # B referencia a X que no existe en el grafo → se ignora
    graph = {"A": {"B"}, "B": {"X_inexistente"}}
    assert sa._build_cycles(graph) == set()


# ── CX-30: max playbooks ──────────────────────────────────────────────────────

def test_max_pb_ok():
    assert "✅" in sa._check_max_playbooks(10)

def test_max_pb_near_limit():
    assert "🟡" in sa._check_max_playbooks(45)

def test_max_pb_over_limit():
    assert "🔴" in sa._check_max_playbooks(51)


# ── CX-32: single responsibility ──────────────────────────────────────────────

def test_single_resp_ok_few_tools():
    pb = _pb(tools=["t1", "t2"], refs=["OtroPlaybook", "OtroMas"])
    assert sa._check_single_resp(pb) == "✅"

def test_single_resp_warn():
    # >1 delegación Y >3 tools → candidato a dividir
    pb = _pb(tools=["t1", "t2", "t3", "t4"], refs=["A", "B"])
    result = sa._check_single_resp(pb)
    assert "🟡" in result

def test_single_resp_ok_few_delegations():
    # Muchas tools pero solo 1 delegación → ok
    pb = _pb(tools=["t1", "t2", "t3", "t4", "t5"], refs=["SoloUno"])
    assert sa._check_single_resp(pb) == "✅"


# ── Integración: audit() con definitions/ ficticio ────────────────────────────

@pytest.fixture
def fixture_root(tmp_path):
    """Árbol mínimo definitions/ con 2 playbooks y examples válidos."""
    pb_dir = tmp_path / "definitions" / "playbooks"
    ex_dir = tmp_path / "definitions" / "examples"
    pb_dir.mkdir(parents=True)

    # ── playbook 'perfecto' — todos los checks pasan ──
    (pb_dir / "perfecto.yaml").write_text(yaml.dump({
        "displayName": "Perfecto",
        "goal": "Gestiona la consulta del cliente.",
        "instruction": {"steps": [
            {"text": "Consulta el inventario con la herramienta."},
            {"text": "Si no puedes ayudar, escala al agente humano."},
        ]},
        "inputParameterDefinitions":  [{"name": "idioma",    "type": "STRING"}],
        "outputParameterDefinitions": [{"name": "resultado", "type": "STRING"}],
        "referencedTools": ["consultarDatos"],
    }, allow_unicode=True))
    _write_examples(ex_dir, "perfecto", [
        {"selectionStrategy": "ALWAYS_SELECT", "actions": [
            {"userUtterance":  {"text": "quiero flores rojas"}},
            {"agentUtterance": {"text": "Tenemos rosas disponibles."}},
        ]},
        {"description": "fallo de herramienta", "actions": [
            {"agentUtterance": {"text": "Lo siento, hay un error con la herramienta."}},
        ]},
        {"description": "negacion", "actions": [
            {"userUtterance": {"text": "no quiero continuar, cancelar"}},
        ]},
        {"description": "variante happy path"},
    ])

    # ── playbook 'problema' — falla exit + params ──
    (pb_dir / "problema.yaml").write_text(yaml.dump({
        "displayName": "Problema",
        "goal": "Test con errores.",
        "instruction": {"steps": [
            {"text": "Usa $parametro_no_declarado para responder."},
        ]},
    }, allow_unicode=True))
    (ex_dir / "problema").mkdir(parents=True)

    return tmp_path


def test_audit_devuelve_dos_filas(fixture_root):
    fake = MagicMock()
    fake._playbook_text = lambda name: "texto " * 100
    sys.modules["petal_agent"] = fake

    rows = sa.audit(str(fixture_root))
    assert len(rows) == 2


def test_audit_perfecto_checks_estructurales(fixture_root):
    fake = MagicMock()
    fake._playbook_text = lambda name: "texto " * 100  # ~50 tokens → size ✅
    sys.modules["petal_agent"] = fake

    rows = sa.audit(str(fixture_root))
    r = next(r for r in rows if r["name"] == "perfecto")

    assert r["exit"]     == "✅", f"exit: {r['exit']}"
    assert r["params"]   == "✅", f"params: {r['params']}"
    assert r["ex_cnt"]   == "✅", f"ex_cnt: {r['ex_cnt']}"
    assert r["name_len"] == "✅", f"name_len: {r['name_len']}"
    assert r["snake"]    == "✅", f"snake: {r['snake']}"
    assert r["cycle"]    == "✅", f"cycle: {r['cycle']}"
    assert r["single"]   == "✅", f"single: {r['single']}"
    assert r["tool_fail"] == "✅", f"tool_fail: {r['tool_fail']}"
    assert r["neg"]       == "✅", f"neg: {r['neg']}"


def test_audit_problema_falla_exit_y_params(fixture_root):
    fake = MagicMock()
    fake._playbook_text = lambda name: "texto " * 100
    sys.modules["petal_agent"] = fake

    rows = sa.audit(str(fixture_root))
    r = next(r for r in rows if r["name"] == "problema")

    assert "🔴" in r["exit"],  f"esperaba fallo exit, got: {r['exit']}"
    assert "🟡" in r["params"], f"esperaba warn params, got: {r['params']}"


# ── Config loading: _load_config() ────────────────────────────────────────────
#
# Este es el test más crítico del fichero: cubre el sistema KB→sync→config→audit.
# Si _load_config() no funciona, los umbrales del KB se ignoran silenciosamente.

@pytest.fixture
def saved_globals():
    """Guarda y restaura los globals de static_audit después del test."""
    orig = {
        "SIZE_PROPOSE": sa.SIZE_PROPOSE,
        "SIZE_URGENT":  sa.SIZE_URGENT,
        "MIN_EXAMPLES": sa.MIN_EXAMPLES,
        "DSL_WARN":     sa.DSL_WARN,
        "DSL_FAIL":     sa.DSL_FAIL,
        "EXIT_KW":      list(sa.EXIT_KW),
        "FAIL_KW":      list(sa.FAIL_KW),
        "NEG_KW":       list(sa.NEG_KW),
    }
    yield
    sa.SIZE_PROPOSE = orig["SIZE_PROPOSE"]
    sa.SIZE_URGENT  = orig["SIZE_URGENT"]
    sa.MIN_EXAMPLES = orig["MIN_EXAMPLES"]
    sa.DSL_WARN     = orig["DSL_WARN"]
    sa.DSL_FAIL     = orig["DSL_FAIL"]
    sa.EXIT_KW      = orig["EXIT_KW"]
    sa.FAIL_KW      = orig["FAIL_KW"]
    sa.NEG_KW       = orig["NEG_KW"]


def _write_config(tmp_path, cfg: dict) -> None:
    """Escribe static_audit_config.yaml en tmp_path y llama a _load_config."""
    (tmp_path / "static_audit_config.yaml").write_text(yaml.dump(cfg, allow_unicode=True))
    sa._load_config(str(tmp_path / "static_audit.py"))


def test_config_size(tmp_path, saved_globals):
    _write_config(tmp_path, {"size": {"propose": 3000, "urgent": 7000}})
    assert sa.SIZE_PROPOSE == 3000
    assert sa.SIZE_URGENT  == 7000


def test_config_min_examples(tmp_path, saved_globals):
    _write_config(tmp_path, {"min_examples": {"min": 6}})
    assert sa.MIN_EXAMPLES == 6


def test_config_dsl_density(tmp_path, saved_globals):
    _write_config(tmp_path, {"dsl_density": {"warn": 0.10, "fail": 0.20}})
    assert sa.DSL_WARN == 0.10
    assert sa.DSL_FAIL == 0.20


def test_config_keywords(tmp_path, saved_globals):
    _write_config(tmp_path, {
        "exit_paths":         {"keywords": ["ayuda", "soporte"]},
        "tool_fail_examples": {"keywords": ["timeout", "unavailable"]},
        "negation_examples":  {"keywords": ["no thanks", "stop"]},
    })
    assert sa.EXIT_KW == ["ayuda", "soporte"]
    assert sa.FAIL_KW == ["timeout", "unavailable"]
    assert sa.NEG_KW  == ["no thanks", "stop"]


def test_config_no_file_keeps_defaults(tmp_path, saved_globals):
    """Sin config.yaml los defaults no cambian."""
    original = sa.SIZE_PROPOSE
    sa._load_config(str(tmp_path / "static_audit.py"))  # no hay yaml en tmp_path
    assert sa.SIZE_PROPOSE == original


def test_config_partial_override(tmp_path, saved_globals):
    """Solo las claves presentes en el config se sobreescriben."""
    original_dsl = sa.DSL_WARN
    _write_config(tmp_path, {"size": {"propose": 2000, "urgent": 8000}})
    assert sa.SIZE_PROPOSE == 2000
    assert sa.DSL_WARN == original_dsl  # no estaba en el config → sin cambiar


def test_config_change_propagates_to_check(tmp_path, saved_globals):
    """Cambiar el umbral en config cambia el comportamiento real de _check_size.

    Este es el test end-to-end del sistema KB→sync→config→check:
    si el umbral baja a 1000, un playbook de 1500 tokens debe ser 🟡 refactor
    (con los defaults sería ✅).
    """
    _write_config(tmp_path, {"size": {"propose": 1000, "urgent": 2000}})
    assert "🟡" in sa._check_size(1500)  # entre 1000 y 2000 → refactor
    assert "🔴" in sa._check_size(2500)  # por encima de 2000 → urgente
    assert "✅"  == sa._check_size(999)  # por debajo de 1000 → ok
