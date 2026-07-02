#!/usr/bin/env python3
"""
gen_rename_params.py — Renombrado transversal de params CX en Petal.

Fases por param:
  1. AUDIT  — grep de todas las ocurrencias (siempre, incluso en dry-run)
  2. REPLACE — sustitución word-boundary (solo con --execute)
  3. VERIFY  — assert 0 residuos del nombre antiguo (obligatorio tras replace)

Params EXCLUIDOS por colisión (3):
  - precio_estimado : nombre idéntico en la API + usado como 'precio_estimado=$precio_estimado'.
  - ocasion_detectada : el destino 'ocasion' es un nombre de param de la API (+ bug de tipo pendiente).
  - nombre_cliente : el destino 'nombre' ya existe como variable temporal ($nombre) en registro_task.
  Renombrarlos rompería el mapeo instrucción→API o fusionaría params distintos.

Uso:
  python gen_rename_params.py                               # AUDIT (dry-run)
  python gen_rename_params.py --execute                     # AUDIT + REPLACE + VERIFY
  python gen_rename_params.py --param nombre_cliente        # AUDIT un param
  python gen_rename_params.py --param nombre_cliente --execute  # REPLACE un param
"""

import argparse
import glob
import os
import re
import sys
from pathlib import Path

# ── Rename map (10 params) ────────────────────────────────────────────────────
# Excluidos por colisión (3): precio_estimado, ocasion_detectada, nombre_cliente (ver docstring).
RENAMES = [
    ("Direccion_Habitual", "dir_habitual"),
    ("estado_emocional",   "emocion"),
    ("intencion_inicial",  "intencion"),
    ("presupuesto_duro",   "pres_duro"),
    ("razon_handoff",      "razon"),
    ("recien_registrado",  "recien_reg"),
    ("referencia_pedido",  "referencia"),
    ("sesion_cerrada",     "fin_sesion"),
    ("usuario_frustrado",  "frustrado"),
    ("es_urgente",         "urgente"),
]

# ── Scope ────────────────────────────────────────────────────────────────────
REPO_ROOT = Path(__file__).resolve().parent

SCOPE_PATTERNS = [
    "definitions/playbooks/*.yaml",
    "definitions/examples/**/*.yaml",
    "qap/tc_*.yaml",
    "qap/test_qa_playbooks.py",
    "act/tests/test_pull_playbooks.py",
    "docs/param_rename_map.md",
    "docs/plan_reduccion_tokens_compra.md",
]

# Archivos fuera de scope (intocables — namespaces distintos)
EXCLUDED = {
    "definitions/tools/petaldatatool_openapi.yaml",
    "definitions/_legacy_placeholders",
    "qap/tc_analysis",
}


def get_scope_files():
    seen = set()
    files = []
    for pattern in SCOPE_PATTERNS:
        for path in sorted(glob.glob(str(REPO_ROOT / pattern), recursive=True)):
            if path not in seen:
                seen.add(path)
                files.append(path)
    return files


def rel(path):
    return os.path.relpath(path, REPO_ROOT)


# ── Core phases ───────────────────────────────────────────────────────────────

def make_pattern(old):
    """Patrón word-boundary: detecta y reemplaza cualquier ocurrencia de old."""
    return re.compile(r'\b' + re.escape(old) + r'\b')


def audit(old, files):
    """Devuelve lista de (filepath, lineno, line) con ocurrencias de old."""
    pattern = make_pattern(old)
    hits = []
    for filepath in files:
        with open(filepath, encoding="utf-8") as f:
            for i, line in enumerate(f, 1):
                if pattern.search(line):
                    hits.append((filepath, i, line.rstrip()))
    return hits


def replace_in_files(old, new, files):
    """Reemplaza todas las ocurrencias word-boundary de old por new. Devuelve total."""
    pattern = make_pattern(old)
    total = 0
    for filepath in files:
        with open(filepath, encoding="utf-8") as f:
            content = f.read()
        new_content, count = pattern.subn(new, content)
        if count > 0:
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(new_content)
            print(f"    replaced {count:3d}x  {rel(filepath)}")
            total += count
    return total


def verify(old, files):
    """Busca residuos del nombre antiguo. Devuelve lista de hits (debe ser vacía)."""
    return audit(old, files)


# ── Runner por param ──────────────────────────────────────────────────────────

def run_param(old, new, files, execute):
    print(f"\n{'─' * 60}")
    print(f"  {old}  →  {new}")
    print(f"{'─' * 60}")

    # Fase 1: AUDIT
    hits = audit(old, files)
    if not hits:
        print(f"  AUDIT: 0 ocurrencias — param no encontrado en scope")
        return True

    affected = len({h[0] for h in hits})
    print(f"  AUDIT: {len(hits)} ocurrencias en {affected} fichero(s)")
    for filepath, lineno, line in hits:
        print(f"    {rel(filepath)}:{lineno}  {line.strip()[:90]}")

    if not execute:
        return True

    # Fase 2: REPLACE
    print(f"\n  REPLACE:")
    count = replace_in_files(old, new, files)
    print(f"  → {count} sustituciones realizadas")

    # Fase 3: VERIFY
    residuals = verify(old, files)
    if residuals:
        print(f"\n  ❌ VERIFY FAILED — {len(residuals)} residuo(s):")
        for filepath, lineno, line in residuals:
            print(f"    {rel(filepath)}:{lineno}  {line.strip()[:90]}")
        return False
    else:
        print(f"  ✅ VERIFY OK — 0 residuos")
        return True


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Renombra params CX en Petal (dry-run por defecto)"
    )
    parser.add_argument(
        "--execute", action="store_true",
        help="Aplica los renames. Sin este flag: solo AUDIT."
    )
    parser.add_argument(
        "--param", metavar="NOMBRE",
        help="Procesa solo este param (nombre antiguo)."
    )
    args = parser.parse_args()

    files = get_scope_files()
    rename_map = dict(RENAMES)

    if args.param:
        if args.param not in rename_map:
            validos = ", ".join(old for old, _ in RENAMES)
            print(f"Error: '{args.param}' no está en el mapa de rename.")
            print(f"Params disponibles: {validos}")
            sys.exit(1)
        pairs = [(args.param, rename_map[args.param])]
    else:
        pairs = RENAMES

    mode = "AUDIT + REPLACE + VERIFY" if args.execute else "AUDIT (dry-run)"
    print(f"\ngen_rename_params.py — {mode}")
    print(f"Scope: {len(files)} ficheros | Params: {len(pairs)}")

    failures = []
    for old, new in pairs:
        ok = run_param(old, new, files, args.execute)
        if not ok:
            failures.append(old)

    print(f"\n{'═' * 60}")
    if args.execute:
        if failures:
            print(f"❌ {len(failures)} param(s) con residuos: {', '.join(failures)}")
            sys.exit(1)
        else:
            print(f"✅ Todos los renames completados y verificados")
    else:
        print(f"Dry-run completo. Añade --execute para aplicar.")


if __name__ == "__main__":
    main()
