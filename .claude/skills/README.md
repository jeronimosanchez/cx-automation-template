# Skills disponibles en este proyecto

Skills locales (no commiteadas) que Claude Code carga automáticamente al abrir sesión en `~/cx-automation-template`.

## Las 3 skills (atómicas, responsabilidad única)

| # | Skill | Invocación | Qué hace | Tiempo |
|---|---|---|---|---|
| 1 | **qa-tc-analyzer** | `/qa-tc-analyzer TC-XYZ` | Análisis del FAIL: descarga JSON, genera `.md` con 7 soluciones + score, regenera HTML y publica en gh-pages. **No toca el agente**. | ~30 seg |
| 2 | **qa-fix** | `/qa-fix TC-XYZ <num-solución>` | Aplica una de las 7 soluciones propuestas: edita el archivo (Playbook/Test/Tool), commit + PR + merge, espera Deploy, valida con rerun. **Requiere análisis previo**. | ~3 min |
| 3 | **qa-revert** | `/qa-revert TC-XYZ` | Revierte el último fix del TC para dejar el agente en estado roto (típicamente para demos). PR revert + merge + deploy + confirma FAIL. | ~2-3 min |

## Flujo típico de demo

```
/qa-tc-analyzer TC-URGENCIA-01    ← entiende el bug + ve 7 soluciones
/qa-fix TC-URGENCIA-01 1      ← aplica la solución #1 (deploy + valida)
                              ← chat con agente → ya responde bien
/qa-revert TC-URGENCIA-01     ← devuelve el agente al estado roto
```

3 pasos, 3 comandos. Cada uno con propósito único.

## Cómo elegir

- **Solo quieres entender un FAIL** → `qa-tc-analyzer`
- **Sabes qué solución aplicar y quieres ejecutarla** → `qa-fix`
- **Quieres deshacer un fix previo (para demo o porque te equivocaste)** → `qa-revert`

## Notas técnicas

- Las skills están en `~/cx-automation-template/.claude/skills/<nombre>/SKILL.md`.
- `.claude/` está en `.gitignore` → las skills son **locales y personales** (no se sincronizan vía git).
- Si quieres compartir una skill con otro repo o sesión, copia el directorio manualmente.

## Cómo añadir una skill nueva

```
mkdir -p ~/cx-automation-template/.claude/skills/<nombre>
# Crear SKILL.md con frontmatter:
# ---
# name: <nombre>
# description: <una frase explicando qué hace y cuándo invocarla>
# ---
# # <nombre> — Título
# ...
```

Claude la cargará en la próxima sesión.

## Cómo borrar una skill

```
rm -rf ~/cx-automation-template/.claude/skills/<nombre>
```
