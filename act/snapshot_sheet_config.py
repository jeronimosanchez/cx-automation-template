#!/usr/bin/env python3
"""snapshot_sheet_config.py — Exporta los tabs de CONFIG del Google Sheet de Petal a YAML versionado.

Para TRAZABILIDAD en git de la config de comportamiento (pesos del scoring) que vive en el
Sheet. NO snapshotea data viva (inventario/perfil/pedidos) — solo config que cambia poco.
El Sheet sigue siendo la superficie de edición; esto es solo una foto en git para auditoría/rollback.

Auth: gcloud auth print-access-token (convención del repo, nunca google.auth.default).
Uso:  python act/snapshot_sheet_config.py [--agent 1.1]
Salida: definitions/config/<tab>.yaml
"""
import subprocess, json, sys, argparse, urllib.request
import yaml
from pathlib import Path

SHEETS = {
    "1.0": "1lkaeVdDC_Pu5lPqBXJGAh0j8rKpVzk5p9-V5Xocj8DA",
    "1.1": "1Kzj_MjAAH49M4Eo8u3HTM8lA5--svKh5rhRauTN2EII",
}
PROJECT = "floristeria-petal-digital"
# Solo tabs de CONFIG (cambian poco, afectan comportamiento). NO data viva.
CONFIG_TABS = ["scoring_config"]


def _token():
    return subprocess.run(["gcloud", "auth", "print-access-token"],
                          capture_output=True, text=True, check=True).stdout.strip()


def _read_tab(sid, tab, token):
    url = f"https://sheets.googleapis.com/v4/spreadsheets/{sid}/values/{tab}!A1:ZZ"
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {token}",
        "x-goog-user-project": PROJECT,
    })
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8")).get("values", [])


def _rows_to_dicts(values):
    if not values:
        return []
    headers = values[0]
    return [{headers[i]: (row[i] if i < len(row) else "") for i in range(len(headers))}
            for row in values[1:] if any(str(c).strip() for c in row)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--agent", default="1.1", choices=list(SHEETS),
                    help="Agente cuyo Sheet snapshotear (default 1.1)")
    args = ap.parse_args()
    sid = SHEETS[args.agent]
    token = _token()
    out_dir = Path(__file__).parent.parent / "definitions" / "config"
    out_dir.mkdir(parents=True, exist_ok=True)
    written = 0
    for tab in CONFIG_TABS:
        try:
            rows = _rows_to_dicts(_read_tab(sid, tab, token))
        except Exception as e:
            print(f"[WARN] no se pudo leer '{tab}': {e}", file=sys.stderr)
            continue
        out = out_dir / f"{tab}.yaml"
        with open(out, "w", encoding="utf-8") as f:
            f.write(f"# Snapshot de la hoja '{tab}' del Sheet de Petal {args.agent} (id {sid}).\n")
            f.write(f"# Generado por act/snapshot_sheet_config.py — NO editar a mano (se regenera).\n")
            f.write(f"# Fuente de edición: el Google Sheet. Esto es solo trazabilidad/rollback en git.\n")
            yaml.safe_dump(rows, f, sort_keys=False, allow_unicode=True, default_flow_style=False)
        print(f"✓ {out} ({len(rows)} filas)")
        written += 1
    if not written:
        sys.exit(1)


if __name__ == "__main__":
    main()
