---
name: qa-fix
description: Aplica una de las soluciones propuestas por qa-tc-analyzer a un TC. Crea branch, edita el archivo correspondiente (Playbook/Test/Tool según el tipo), commit + PR + merge, espera Deploy a Petal CX y valida con rerun. Pre-requisito: que ya exista análisis del TC (`/qa-tc-analyzer TC-XYZ` antes). NO incluye revert (eso es `/qa-revert`). Tiempo ~3 min (90% es Deploy). Uso: "/qa-fix TC-XYZ <num-solución>".
---

# qa-fix — Aplica una solución concreta a un TC

## Cuándo invocar

Cuando el usuario ya ha visto el análisis (`/qa-tc-analyzer`) y quiere aplicar una de las soluciones propuestas:

| Frase del usuario | Acción |
|---|---|
| `/qa-fix TC-URGENCIA-01 1` | Aplica la solución #1 del análisis previo |
| `aplica solución 2 de TC-XYZ` | Equivalente |
| `fix TC-XYZ con la #3` | Equivalente |

Si el usuario solo dice `/qa-fix TC-XYZ` sin número:
- Si el `.md` tiene "Solución recomendada: #N" → asume esa N y confirma con el usuario
- Si no → pregunta cuál solución aplicar

## Argumentos

- `TC-ID` (obligatorio).
- `<num-solución>` (opcional, default = solución recomendada del `.md`): número entre 1-7.

## Pre-requisitos

1. Análisis previo del TC: `qap/tc_analysis/TC-XYZ.md` debe existir (lo crea `/qa-tc-analyzer`).
2. `main` actualizado:
   ```bash
   cd ~/cx-automation-template
   git fetch origin main && git checkout main && git pull --ff-only
   ```
3. Venv + gcloud OK (deben estarlo).

Si el `.md` no existe → reporta al usuario y sugiere correr `/qa-tc-analyzer TC-XYZ` primero.

## Flujo

### Paso 1 — Lee el análisis y la solución elegida

```bash
cat qap/tc_analysis/TC-XYZ.md
```

Extrae:
- `tipo` (frontmatter): determina qué archivo modificar
- Solución elegida (por número en la tabla de 7): texto + plan de acción

Confirma al usuario qué vas a hacer:
> "Aplico solución #N (\"<título>\"): edito `<archivo>`, deploy, valido."

### Paso 2 — Determina archivo a modificar según `tipo`

| Tipo del .md | Archivo(s) | Requiere Deploy CX |
|---|---|---|
| **Bug Playbook** | `definitions/playbooks/<nombre>.yaml` | ✅ Sí |
| **Bug Orquestador** | `definitions/playbooks/orquestador.yaml` | ✅ Sí |
| **Bug Tool** | `definitions/tools/<nombre>.yaml` | ✅ Sí |
| **Test mal calibrado** / **Falso negativo** | `qap/test_qa_playbooks.py` (regex) | ❌ No |
| **Bug Catálogo** | Backend Cloud Run (fuera del repo) | ⚠️ Manual |
| **Flakiness** | Examples o ajuste de test | Depende |

- Si **Bug Catálogo** → avisar al usuario que es fuera del repo y parar.
- Si tipo **no requiere deploy** → avisa que el agente no cambiará (solo el test).

### Paso 3 — Branch + edit + commit + push

```bash
git checkout -b fix/qa-fix-TC-XYZ-$(date +%H%M%S)

# Edit del archivo siguiendo el plan de acción de la solución elegida.
# Verifica sintaxis (Python compile / YAML valid si aplica).

git add <archivos>
git commit -m "fix(scope): descripción (TC-XYZ)"
git push -u origin <branch>
```

### Paso 4 — PR + merge

```bash
gh pr create --title "fix(...): ... (TC-XYZ)" --body "Solución #N del análisis qap/tc_analysis/TC-XYZ.md ..."
gh pr merge <PR> --squash --admin
```

**Guarda el commit SHA del fix** — el usuario lo necesitará si después invoca `/qa-revert`.

### Paso 5 — Espera Deploy (si aplica)

Si el tipo requiere deploy:
```bash
RUN_ID=$(gh run list --workflow="Deploy to Petal CX" --limit 1 --json databaseId --jq '.[0].databaseId')
gh run watch $RUN_ID --interval 15  # ~2 min
```

Si no requiere deploy → skip a Paso 6.

### Paso 6 — Valida con rerun

```bash
./qap/rerun_single_tc.sh TC-XYZ
```

Lee el JSON resultado:
```bash
cat ~/petal-qa/$(ls -t ~/petal-qa/ | grep "logs$" | head -1)/TC-XYZ.json
```

### Paso 7 — Reporta resultado al usuario

Si **PASS** ✅:
- Respuesta del agente (primeros 250 chars)
- Métricas globales (PASS/FAIL del total)
- URL del nuevo run en gh-pages
- **Commit del fix**: `<SHA>` (importante para `/qa-revert` si lo decide)
- Mensaje: *"Fix aplicado y validado. Si quieres dejar el agente roto otra vez, invoca `/qa-revert TC-XYZ`."*

Si **FAIL** ❌:
- Respuesta del agente real (qué dijo)
- Sugerencias de qué ajustar (otra solución, refinar el cambio, etc.)
- NO revertir automáticamente.
- Espera nueva instrucción del usuario.

## Política

- **NO commitea el `.md`** a `main` (sigue siendo artefacto local + gh-pages).
- **NO ejecuta revert** automáticamente. Si el usuario lo quiere → `/qa-revert TC-XYZ`.
- **NO repite análisis**: si quieres re-analizar, usa `/qa-tc-analyzer TC-XYZ`.

## Ejemplo

```
Usuario: /qa-fix TC-URGENCIA-01 1
Claude:  → Lee qap/tc_analysis/TC-URGENCIA-01.md → tipo=Bug Playbook, solución #1
         → "Aplico solución #1 (CASOS ESPECIALES urgencia/plazo) editando compra.yaml"
         → Branch fix/qa-fix-TC-URGENCIA-01-094530
         → Edit compra.yaml + commit + PR + merge
         → Deploy CX (~2 min) ✅
         → rerun TC-URGENCIA-01 → PASS ✅
         → "Fix aplicado y validado. Commit: 3f041df.
            Si quieres revertir → /qa-revert TC-URGENCIA-01"
```
