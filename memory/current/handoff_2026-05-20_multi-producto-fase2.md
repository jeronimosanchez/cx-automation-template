---
name: handoff-multi-producto-fase2
description: Handoff antes de reinicio Claude Code — plan robust multi-producto pendiente de aplicar
metadata: 
  node_type: memory
  type: project
  originSessionId: 98f2eccc-717f-49ea-91ff-41b63a7ceeb7
---

# Handoff 2026-05-20 sesión tarde — antes de reinicio

**Why**: el usuario reinicia Claude Code para activar las nuevas reglas de permisos añadidas durante esta sesión (Monitor, cat *, cd+git, etc. — todas en `.claude/settings.local.json`).

## Estado al cierre

- **Demo Petal QA** es esta tarde
- **Agente está en estado** parcialmente arreglado: TC-MULTI-PRODUCTO-01 PASS para T1, pero rompe en T5/T6 (no captura segundo producto correctamente)
- **TC-URGENCIA-01 sigue en FAIL** (no se ha aplicado fix aún) — es el TC estrella de la demo
- **Análisis publicados** en main para los 3 FAILs (PR #92)
- **Fix Compra multi-producto v1** mergeado (PR #93, commit 8405613) — añadió CASO ESPECIAL básico pero incompleto
- **HTML dashboard** funciona OK con history.json estático + 11 runs

## Lo que está pendiente (al retomar)

### Plan acordado: "3 cambios robustos multi-producto"

1. **`definitions/playbooks/compra.yaml`** — reforzar CASO ESPECIAL multi-producto añadiendo:
   - Captura explícita en slots `$producto_1`/`$cantidad_1`/`$precio_1` tras elegir el primer producto
   - Captura en slots `$producto_2`/`$cantidad_2`/`$precio_2` tras elegir el segundo
   - ECO obligatorio del resumen antes de Checkout: *"Tu pedido: 1x Ramo Lirios (30€) + 3x Centro Rosas (105€) = 135€. Confirmo?"*

2. **`definitions/playbooks/checkout.yaml`** — añadir slots opcionales + render condicional:
   - `inputParameterDefinitions`: añadir `producto_2`, `cantidad_2`, `precio_2` (opcionales)
   - PASO 2 (confirmación): si `$producto_2` está vacío → comportamiento actual; si tiene valor → render multi-línea con total combinado

3. **`.claude/skills/qa-tc-analyzer/SKILL.md`** — añadir nueva sección al formato del MD:
   - "Parámetros / slots requeridos entre playbooks" — tabla que identifica slots cross-playbook necesarios para el fix

### Tras aplicar (validación)

- Commit + PR + merge + monitor deploy
- Rerun TC-MULTI-PRODUCTO-01 vía `./qa/rerun_single_tc.sh` — debe seguir en PASS
- **Verificación manual de los 6 turnos**: ejecutar `/tmp/reproduce_multi_token_issue.py` o equivalente. T1-T6 deben fluir hasta Checkout con resumen combinado correcto.

### Después: "romper algo controlado para la demo"

Tras validar que multi-producto está sólido, el usuario quiere **romper algo pequeño en Compra** (ej: quitar la captura del segundo producto en el CASO ESPECIAL) para tener un bug controlado para la demo del ciclo `bug→analyze→fix→PASS`.

## Comando para retomar

```
Retomo demo Petal QA. Lee handoff_2026-05-20_multi-producto-fase2.md. Aplica el plan
de 3 cambios robustos multi-producto (Compra + Checkout + skill qa-tc-analyzer).
Modo autónomo con red de seguridad (PR + revert si rompe). Ve directo.
```
