"""sync_static_config.py — genera qap/static_audit_config.yaml desde bloques `static:` del KB.

Lee todos los archivos .md en --kb-root, extrae los bloques de código etiquetados `static`,
los parsea como YAML y genera un config consolidado que static_audit.py carga en cada run.

Uso:
  python qap/sync_static_config.py --kb-root ~/CD/kb/
  python qap/sync_static_config.py --kb-root ~/CD/kb/ --dry-run   # imprime sin escribir

Flujo completo:
  1. Editar umbral en KB (ej. DSL_WARN en CX-34)
  2. python qap/sync_static_config.py --kb-root ~/CD/kb/
  3. static_audit.py carga static_audit_config.yaml en el siguiente run — sin tocar el código.
"""
import os, sys, re, argparse
import yaml

BLOCK_RE = re.compile(r"```static\n(.*?)```", re.DOTALL)

SUPPORTED_CHECKS = {
    "size", "min_examples", "dsl_density",
    "exit_paths", "tool_fail_examples", "negation_examples",
    "always_select", "param_hygiene",
}


def extract_blocks(md_text):
    """Devuelve lista de dicts parseados desde los bloques ```static en el texto."""
    blocks = []
    for m in BLOCK_RE.finditer(md_text):
        raw = m.group(1).strip()
        try:
            data = yaml.safe_load(raw)
        except yaml.YAMLError as e:
            print(f"  WARN: bloque static inválido (YAML): {e}", file=sys.stderr)
            continue
        if not isinstance(data, dict):
            print(f"  WARN: bloque static no es un dict — ignorado: {raw!r}", file=sys.stderr)
            continue
        blocks.append(data)
    return blocks


def build_config(kb_root):
    """Recorre los .md del KB y construye el config consolidado."""
    cfg = {}
    md_files = sorted(
        p for p in (
            os.path.join(kb_root, f) for f in os.listdir(kb_root) if f.endswith(".md")
        )
        if os.path.isfile(p)
    )

    if not md_files:
        print(f"WARN: no se encontraron .md en {kb_root}", file=sys.stderr)
        return cfg

    for path in md_files:
        with open(path, encoding="utf-8") as f:
            text = f.read()
        blocks = extract_blocks(text)
        for block in blocks:
            check = block.get("check")
            if not check:
                continue
            if check not in SUPPORTED_CHECKS:
                print(f"  WARN: check desconocido '{check}' en {os.path.basename(path)} — ignorado",
                      file=sys.stderr)
                continue
            entry = {k: v for k, v in block.items() if k != "check"}
            cfg[check] = entry

    return cfg


def main():
    ap = argparse.ArgumentParser(description="Genera static_audit_config.yaml desde el KB.")
    ap.add_argument("--kb-root", required=True,
                    help="Directorio raíz del KB (contiene kb_*.md y _politica_kb.md)")
    ap.add_argument("--dry-run", action="store_true",
                    help="Imprime el YAML resultante sin escribirlo")
    args = ap.parse_args()

    kb_root = os.path.expanduser(args.kb_root)
    if not os.path.isdir(kb_root):
        sys.exit(f"ERROR: --kb-root no existe: {kb_root}")

    print(f"Leyendo KB desde: {kb_root}")
    cfg = build_config(kb_root)

    if not cfg:
        sys.exit("ERROR: no se encontró ningún bloque `static:` en el KB.")

    header = (
        "# Auto-generado por sync_static_config.py — NO editar manualmente.\n"
        "# Fuente de verdad: bloques `static:` en el KB.\n"
        "# Regenerar: python qap/sync_static_config.py --kb-root ~/CD/kb/\n\n"
    )
    output = header + yaml.dump(cfg, allow_unicode=True, default_flow_style=False, sort_keys=True)

    if args.dry_run:
        print("\n── static_audit_config.yaml (dry-run) ──────────────────────────")
        print(output)
        return

    out_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "static_audit_config.yaml"
    )
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(output)

    print(f"✅  Escrito: {out_path}")
    print(f"   Checks sincronizados: {sorted(cfg.keys())}")


if __name__ == "__main__":
    main()
