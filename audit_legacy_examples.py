#!/usr/bin/env python3
"""
audit_legacy_examples.py

Audita TODOS los Examples de los 6 Playbooks del agente Floristeria-
Petal e identifica los que usan el operationId LEGACY "petaldatatool"
en lugar del actual "consultarDatos".

Genera reporte con listado de migracion para Automatizacion ACT
Sprint 2 (PATCH masivo).

NO modifica nada. Solo lectura.

Uso:
  python3 audit_legacy_examples.py
  python3 audit_legacy_examples.py --json   # output adicional en JSON
"""

import argparse
import json
import sys
from datetime import datetime
import requests
import google.auth
import google.auth.transport.requests


# ============================================================
# CONSTANTES
# ============================================================
PROJECT = "floristeria-petal-digital"
LOCATION = "europe-west1"
AGENT_ID = "745375ba-ac7e-4eb8-b8a0-d742891f2aa4"
BASE = f"https://{LOCATION}-dialogflow.googleapis.com/v3beta1"
PARENT = f"projects/{PROJECT}/locations/{LOCATION}/agents/{AGENT_ID}"

PLAYBOOKS = {
    "Petal CX Orchestrator": "00000000-0000-0000-0000-000000000000",
    "Compra":                 "c3e31ae0-9389-45b5-9081-142f1ce0d3e0",
    "Checkout":               "1d2698dd-0027-4881-a9b4-6970d61885cb",
    "Registro_Task":          "2d111e5e-e811-4098-b52b-ab1128a0d0e2",
    "Gestion_Deuda":          "871d4bbb-5c90-443b-bbb1-1d83d254c2c3",
    "Handoff":                "9d0d211b-e39e-40cd-932b-b732caa62334",
}

LEGACY_ACTION = "petaldatatool"
CURRENT_ACTION = "consultarDatos"


# ============================================================
# AUTH Y HTTP
# ============================================================
def get_headers():
    creds, _ = google.auth.default(
        scopes=["https://www.googleapis.com/auth/dialogflow"]
    )
    creds.refresh(google.auth.transport.requests.Request())
    return {
        "Authorization": f"Bearer {creds.token}",
        "Content-Type": "application/json",
        "x-goog-user-project": PROJECT,
    }


def list_all_examples(headers, playbook_id):
    """Lista TODOS los examples de un playbook con paginacion completa."""
    examples = []
    next_token = None
    pages = 0

    while True:
        params = {"pageSize": 50}
        if next_token:
            params["pageToken"] = next_token
        url = (f"{BASE}/{PARENT}/playbooks/{playbook_id}/examples")
        r = requests.get(url, headers=headers, params=params)
        if r.status_code != 200:
            return None, f"GET fallo {r.status_code}: {r.text[:200]}"
        data = r.json()
        examples.extend(data.get("examples", []))
        pages += 1
        next_token = data.get("nextPageToken")
        if not next_token or pages >= 20:
            break

    return examples, None


# ============================================================
# ANALISIS POR EXAMPLE
# ============================================================
def analyze_example(ex):
    """Devuelve dict con info del example para el reporte."""
    actions = ex.get("actions", [])
    tool_uses = [a["toolUse"] for a in actions if "toolUse" in a]
    tool_actions = [tu.get("action", "") for tu in tool_uses]

    has_legacy = any(a == LEGACY_ACTION for a in tool_actions)
    has_current = any(a == CURRENT_ACTION for a in tool_actions)
    other_actions = [a for a in tool_actions
                     if a not in (LEGACY_ACTION, CURRENT_ACTION)]

    return {
        "name": ex.get("name", ""),
        "id": ex.get("name", "").split("/")[-1],
        "displayName": ex.get("displayName", ""),
        "tokenCount": ex.get("tokenCount", "?"),
        "n_actions": len(actions),
        "n_tool_uses": len(tool_uses),
        "tool_actions": tool_actions,
        "has_legacy": has_legacy,
        "has_current": has_current,
        "other_actions": other_actions,
        "mixed": has_legacy and has_current,
    }


# ============================================================
# REPORTE
# ============================================================
def build_report(audit_data, timestamp):
    """audit_data: {playbook_name: {error|examples}}"""
    lines = []
    lines.append("=" * 70)
    lines.append(f"AUDIT_LEGACY_EXAMPLES  {timestamp}")
    lines.append(f"Agent: {AGENT_ID}")
    lines.append(f"Legacy operationId buscado:  '{LEGACY_ACTION}'")
    lines.append(f"Current operationId actual:  '{CURRENT_ACTION}'")
    lines.append("=" * 70)
    lines.append("")

    # Resumen tabla
    lines.append("RESUMEN POR PLAYBOOK")
    lines.append("-" * 70)
    lines.append(
        f"{'Playbook':25s} {'Total':>7s} {'Legacy':>7s} "
        f"{'Current':>8s} {'Mixed':>6s} {'Other':>6s}"
    )
    lines.append("-" * 70)

    total_examples = 0
    total_legacy = 0

    for pb_name in PLAYBOOKS:
        info = audit_data.get(pb_name, {})
        if "error" in info:
            lines.append(f"{pb_name:25s}  ERROR: {info['error'][:40]}")
            continue
        exs = info["examples"]
        n_total = len(exs)
        n_legacy = sum(1 for e in exs if e["has_legacy"])
        n_current = sum(1 for e in exs if e["has_current"])
        n_mixed = sum(1 for e in exs if e["mixed"])
        n_other = sum(1 for e in exs if e["other_actions"])

        total_examples += n_total
        total_legacy += n_legacy

        lines.append(
            f"{pb_name:25s} {n_total:7d} {n_legacy:7d} "
            f"{n_current:8d} {n_mixed:6d} {n_other:6d}"
        )

    lines.append("-" * 70)
    pct_legacy = (total_legacy / total_examples * 100) \
                 if total_examples > 0 else 0
    lines.append(
        f"{'TOTAL':25s} {total_examples:7d} {total_legacy:7d}  "
        f"({pct_legacy:.1f}% legacy)"
    )
    lines.append("")

    # Detalle: examples con legacy
    lines.append("=" * 70)
    lines.append("DETALLE — EXAMPLES CON ACTION LEGACY (a migrar)")
    lines.append("=" * 70)
    lines.append("")

    for pb_name in PLAYBOOKS:
        info = audit_data.get(pb_name, {})
        if "error" in info:
            continue
        exs = info["examples"]
        legacy_exs = [e for e in exs if e["has_legacy"]]
        if not legacy_exs:
            lines.append(f"## {pb_name}")
            lines.append("  (sin Examples legacy)")
            lines.append("")
            continue

        lines.append(f"## {pb_name}  —  {len(legacy_exs)} Examples a migrar")
        lines.append("")
        for e in legacy_exs:
            mixed_tag = " [MIXED legacy+current]" if e["mixed"] else ""
            lines.append(f"  - {e['displayName']}{mixed_tag}")
            lines.append(f"      id: {e['id']}")
            lines.append(
                f"      actions: {e['n_actions']}, "
                f"toolUses: {e['n_tool_uses']}, "
                f"tokenCount: {e['tokenCount']}"
            )
            lines.append(f"      tool_actions: {e['tool_actions']}")
        lines.append("")

    # Recomendacion
    lines.append("=" * 70)
    lines.append("RECOMENDACION PARA AUTOMATIZACION ACT")
    lines.append("=" * 70)
    lines.append("")
    if total_legacy == 0:
        lines.append("No hay Examples legacy. Migracion no necesaria.")
    else:
        lines.append(
            f"Hay {total_legacy} Examples con action='{LEGACY_ACTION}' "
            f"(legacy)."
        )
        lines.append(
            "Estos Examples NO fallan en runtime (estan fosilizados, "
            "Gemini los lee como contexto sintetico)."
        )
        lines.append(
            "Pero si Automatizacion intenta hacer PATCH sobre cualquiera "
            "de ellos, la API rechazara porque la spec actual del Tool "
            f"no tiene operationId '{LEGACY_ACTION}'."
        )
        lines.append("")
        lines.append("Plan de migracion sugerido para Sprint 2:")
        lines.append(
            f"  1. PATCH masivo sustituyendo action='{LEGACY_ACTION}' "
            f"por action='{CURRENT_ACTION}' en cada toolUse."
        )
        lines.append(
            "  2. Mantener inputActionParameters intactos (mismos "
            "campos)."
        )
        lines.append(
            f"  3. Verificar que outputActionParameters esta envuelto "
            f"bajo clave '200' (segun schema descubierto en S60). "
            f"Algunos Examples legacy pueden tener outputs sueltos."
        )
        lines.append(
            "  4. Tras PATCH, ejecutar un QA del agente para asegurar "
            "que Gemini sigue interpretando los Examples como antes."
        )
    lines.append("")

    return "\n".join(lines)


# ============================================================
# MAIN
# ============================================================
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true",
                        help="genera ademas un .json con datos crudos")
    args = parser.parse_args()

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    print("=" * 65)
    print(f"AUDIT_LEGACY_EXAMPLES {timestamp}")
    print(f"Buscando operationId LEGACY '{LEGACY_ACTION}' en 6 Playbooks")
    print("=" * 65)

    print("\n[SETUP] Obteniendo token...")
    headers = get_headers()
    print("[SETUP] Token OK")

    audit_data = {}
    for pb_name, pb_id in PLAYBOOKS.items():
        print(f"\n[FETCH] {pb_name}  (ID: {pb_id[:8]}...)")
        examples, err = list_all_examples(headers, pb_id)
        if err:
            print(f"  ERROR: {err}")
            audit_data[pb_name] = {"error": err}
            continue
        analyzed = [analyze_example(e) for e in examples]
        n_legacy = sum(1 for e in analyzed if e["has_legacy"])
        print(f"  {len(analyzed)} Examples leidos. "
              f"Legacy: {n_legacy}.")
        audit_data[pb_name] = {"examples": analyzed}

    # Generar reporte
    report = build_report(audit_data, timestamp)
    report_path = f"audit_legacy_examples_{timestamp}.txt"
    with open(report_path, "w") as f:
        f.write(report)

    # JSON opcional
    if args.json:
        json_path = f"audit_legacy_examples_{timestamp}.json"
        with open(json_path, "w") as f:
            json.dump(audit_data, f, indent=2)
        print(f"\n[OUT] JSON: {json_path}")

    print("\n" + "=" * 65)
    print(f"REPORTE: {report_path}")
    print("=" * 65)
    print()
    print(report)

    return 0


if __name__ == "__main__":
    sys.exit(main())
