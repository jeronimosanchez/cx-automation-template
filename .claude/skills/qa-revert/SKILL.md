---
name: qa-revert
description: Revierte el último fix aplicado a un TC para volver al estado roto (típicamente útil para demos donde quieres reproducir el bug original). Crea PR de revert, mergea, espera deploy, y confirma con un rerun que el TC vuelve a FAIL. Coste ~0,01€ + ~2 min de deploy. Uso típico: tras `/qa-fix TC-XYZ` o un fix manual, cuando quieres dejar el agente roto otra vez.
---

# qa-revert — Revierte el último fix de un TC

## Cuándo invocar esta skill

| Frase del usuario | Acción |
|---|---|
| `/qa-revert TC-URGENCIA-01` | Revertir el último fix de ese TC |
| `revierte TC-XYZ` | Equivalente |
| `vuelve TC-XYZ al estado roto` | Equivalente |

## Argumentos

- `TC-ID` (obligatorio): identificador del TC cuyo fix quieres revertir.
- `--commit SHA` (opcional): SHA específico del commit a revertir (si no, busca el más reciente que mencione el TC).

## Pre-requisitos

1. El TC debe tener un fix previo en `main` (busca commit con `TC-XYZ` en el mensaje).
2. Estar en `~/cx-automation-template` con `main` actualizado.

## Flujo

### Paso 1 — Identificar el commit a revertir

```bash
cd ~/cx-automation-template
git fetch origin main
git checkout main && git pull --ff-only

# Buscar commit reciente del fix:
FIX_COMMIT=$(git log origin/main --oneline | grep -iE "TC-XYZ|fix.*TC-XYZ" | head -1 | awk '{print $1}')
echo "Fix commit: $FIX_COMMIT"
```

Si no se encuentra: reporta al usuario y pide el SHA manualmente.

### Paso 2 — Crear branch + revert + push

```bash
git checkout -b revert/qa-fix-TC-XYZ-$(date +%H%M%S)
git revert --no-edit $FIX_COMMIT
git push -u origin <branch>
```

### Paso 3 — PR + merge

```bash
gh pr create --title "revert: fix TC-XYZ (vuelta a estado roto)" --body "..."
gh pr merge <PR> --squash --admin
```

### Paso 4 — Esperar Deploy

```bash
RUN_ID=$(gh run list --workflow="Deploy to Petal CX" --limit 1 --json databaseId --jq '.[0].databaseId')
gh run watch $RUN_ID --interval 15  # ~2 min
```

### Paso 5 — Confirmar estado roto

```bash
python3 qap/surgical_run.py --test TC-XYZ --runs 1   # repo agent-validation-engine
```

Lee el resultado:
```bash
cat ~/petal-qa/$(ls -t ~/petal-qa/ | grep "logs$" | head -1)/TC-XYZ.json
```

Reporta al usuario:
- Si vuelve a FAIL ✅ → confirma estado roto restaurado
- Si sigue en PASS ⚠️ → algo está mal (el revert no aplicó). Investigar
- URL del nuevo run
- **Commit del fix original guardado para reaplicarlo después**: `<FIX_COMMIT>`

## Política importante

- Solo revierte cambios en `definitions/` (Playbooks, Tools, Orquestador). Si el commit toca `qa/` (test), no requiere deploy — el revert es instantáneo tras merge.
- No usar en producción real (este patrón "fix → revert" es solo para demos).

## Ejemplo

```
Usuario: /qa-revert TC-URGENCIA-01
Claude:  → Fix commit identificado: 3f041df
         → PR revert creado: #84
         → Mergeado
         → Deploy en curso (~2 min)...
         → Deploy ✅
         → rerun TC-URGENCIA-01 → FAIL (esperado)
         → Estado roto restaurado.
         → Commit del fix guardado: 3f041df (cherry-pick para reaplicar).
```
