---
status: FAIL
tipo: Bug Playbook
estimacion: ~10 min (Solución #1 recomendada)
---

## TC-URGENCIA-03 — Entrega urgente — plazo viernes, agente confirma viabilidad y política de envío

**Grupo:** COMPRA-ZG | **Run:** 2026-07-01 17:08 | **Resultado:** 0/1 PASS

---

### Turnos vs Problemas detectados

| # | Quién | Acción / Texto | Problema detectado |
|---|-------|----------------|--------------------|
| 1 | User | *"lo necesito para este viernes"* | — |
| 2 | Compra | *"Entendido, para este viernes. ¿Qué tipo de flores o plantas te gustaría para la oficina?"* | 🔴 El bloque DETECCION RESTRICCION TEMPORAL existe en el YAML, pero el agente salta al slot-filling sin verbalizar plazo ni política de envío |

**Síntoma diferenciador respecto a runs anteriores:** el agente hace ECO del marcador temporal ("para este viernes") pero omite la respuesta obligatoria de política. Esto difiere del patrón histórico donde el agente ignoraba totalmente el marcador — aquí lo reconoce pero no actúa sobre él.

**Sesión params inyectados:** `es_urgente=true`, `intencion_inicial="algo para la oficina"`, `ocasion_detectada="Corporativo"`.

**Regex esperado (turno 1):** `24h|24 horas|plazo|días|dias|llega|tiempo.{0,20}entrega|entrega.{0,20}tiempo`

---

### Causa raíz — evaluación de las 9 capas del sistema [v1.1]

🔴 **1. Capa Comportamiento** [verificada] · Fuente: `Read definitions/playbooks/compra.yaml` (líneas 272-286) + `git diff aa05036^..aa05036 -- definitions/playbooks/compra.yaml`

**Causa principal.** El bloque `⛔ DETECCION RESTRICCION TEMPORAL ⛔` existe en `compra.yaml` (líneas 272-286 en el HEAD actual). El bloque lista explícitamente los días de semana como marcadores que lo activan: `'lunes'...'domingo'`, `'este X'`, `'para este X'`. El input "lo necesito para este viernes" contiene "viernes" y "para este" — debería disparar el bloque incondicionalmente.

**Root cause:** el commit `aa05036` (2026-07-01, el más reciente) eliminó la frase de refuerzo de obligatoriedad de la línea OBLIGATORIO del bloque:

```
ANTES (76cbe39):
⛔ OBLIGATORIO: si $intencion_inicial o el input contiene CUALQUIER marcador temporal de
entrega, EJECUTA ESTE BLOQUE ANTES de cualquier otra cosa [...]. NUNCA saltes al catalogo
ni al slot-filling sin haber informado primero la politica de envio.

DESPUÉS (aa05036 — HEAD actual):
⛔ OBLIGATORIO: si $intencion_inicial o el input contiene CUALQUIER marcador temporal de
entrega, EJECUTA ESTE BLOQUE ANTES de cualquier otra cosa [...].
```

La frase eliminada — "NUNCA saltes al catálogo ni al slot-filling sin haber informado primero la política de envío" — era el antipatrón explícito que impedía exactamente el comportamiento observado. Sin ella, el modelo interpreta el ECO del marcador ("Entendido, para este viernes") como suficiente cumplimiento del bloque y continúa al slot-filling.

⚪ **2. Capa Routing** · N/A — arquitectura Playbooks. El routing a Compra es responsabilidad del Orquestador y funcionó correctamente (sesión params inyectados, `ocasion_detectada="Corporativo"`, grupo COMPRA-ZG activo).

🟢 **3. Capa Parámetros / Slots** [verificada] · Fuente: `JSON campo params turno 1`

`$es_urgente=true`, `$intencion_inicial="algo para la oficina"`, `$ocasion_detectada="Corporativo"` llegan correctamente a Compra. El agente tiene acceso al marcador temporal vía el input directo del usuario. La omisión no es de slot — es de instrucción de respuesta.

Nota: `$intencion_inicial="algo para la oficina"` no contiene la marca temporal "viernes". El marcador llega **solo en el input del turno 1**, no en session params. El bloque está diseñado para detectarlo en "el input" — lo cual incluye el turn text — por lo que la condición sí se cumple.

🟢 **4. Capa Integración** [verificada] · Fuente: `JSON campo agent turno 1`

No hay tool call en el turno 1. El agente responde en texto libre. Sin error de integración.

🟢 **5. Capa Datos** [no accesible — UNAUTHORIZED] · Sheet no disponible en esta sesión.

Basado en análisis previos confirmados (batch 20260527): `tiempo_entrega_estimado="24h en Madrid y Barcelona, 48h resto de ciudades"` y `envio_madrid_ciudad="Mismo día (pedidos antes 14:00)"`. El contenido de la política existe en Sheet y es el que el bloque debe verbalizar. No hay causa raíz en datos.

⚪ **6. Capa Infraestructura** · N/A — el YAML desplegado es el estado actual del repo. El commit `aa05036` ya está en producción (deploy CI/CD activo).

🟢 **7. Capa Modelo / LLM** [verificada] · Fuente: `JSON campo agent turno 1`

El agente sigue las instrucciones del YAML con fidelidad: el bloque debilitado por `aa05036` no prohíbe explícitamente el salto al slot-filling → el modelo hace ECO contextual ("Entendido, para este viernes") y continúa al flujo natural. Comportamiento determinista dado el prompt actual. La causa está en la instrucción, no en el modelo.

🔴 **8. Capa Histórico** [verificada] · Fuente: `git log --oneline -8 -- definitions/playbooks/compra.yaml`

Patrón de regresión con nueva variante:

| Commit | Acción | Efecto en TC-URGENCIA-03 |
|--------|--------|--------------------------|
| `3bec490` | Introduce DETECCION RESTRICCION TEMPORAL + `$hora_actual` | TC → PASS |
| `167ed77` | Revert | TC → FAIL (bloque eliminado) |
| `76cbe39` | Recupera bloque (PR #116, explícitamente para TC-URGENCIA-01 + TC-URGENCIA-03) | TC → PASS (validado) |
| `aa05036` | Refactor "convierte prohibiciones en reglas positivas (parcial)" — elimina frase antipatrón del bloque | TC → FAIL (**regresión colateral**) |

Esta es la primera vez que TC-URGENCIA-03 falla con el bloque presente. Los FAILs anteriores eran por ausencia del bloque. El FAIL actual es por **debilitamiento colateral** de la instrucción durante un refactor de estilo (no de lógica).

🟢 **9. Capa Test** [verificada] · Fuente: `grep -A 10 "TC-URGENCIA-03" qap/tc_1_0.yaml`

Regex `24h|24 horas|plazo|días|dias|llega|tiempo.{0,20}entrega|entrega.{0,20}tiempo` bien calibrado para día futuro (no requiere "no" ni "imposible" como variante "hoy"). El bloque en su estado correcto produce "Sin problema para el viernes, el plazo es 24h en Madrid y Barcelona, 48h resto" → matches "plazo" y "24h". TC válido, sin problema de calibración.

**Resumen visual:** 2 🔴 · 4 🟢 · 0 🟡 · 3 ⚪

---

## Recomendación

### Dimensionamiento del bug

| Dimensión | Nivel | Justificación |
|---|---|---|
| Alcance | Trivial | 1 archivo (`compra.yaml`), restaurar 1 frase en 1 línea |
| Profundidad | Trivial | Frase eliminada es exactamente el antipatrón que cierra el gap |
| Riesgo de regresión | Trivial | Restaura texto que existía en `76cbe39` (validado en producción) |

**Nivel final:** Trivial → 3 soluciones

---

### Soluciones evaluadas (3 soluciones, DESC por score)

| # | Solución | Score | Dependencias | Por qué este scoring |
|---|----------|-------|--------------|----------------------|
| 1 | **Restaurar frase antipatrón en la línea OBLIGATORIO** del bloque DETECCION RESTRICCION TEMPORAL | 🟢 9/10 | — | Quirúrgico: 1 frase, 1 archivo. Restaura exactamente el texto que `76cbe39` tenía y que pasó en producción. Sin riesgo de regresión en otros TCs |
| 2 | **Añadir example few-shot** de `"lo necesito para este viernes"` → respuesta con plazo | 🟡 6/10 | — | Refuerzo complementario. No elimina el gap de instrucción, pero puede reducir flakiness si el refuerzo por sí solo no es 100% determinista. Útil como segunda capa |
| 3 | **Revert parcial de `aa05036`** (solo la línea del bloque URGENCIA, mantener resto del refactor) | 🟡 5/10 | Requiere cherry-pick selectivo | Equivalente a Solución #1 pero con más riesgo operativo. El refactor `aa05036` tiene cambios válidos en otras secciones — revertir todo sería regresión en esas áreas |

---

### Plan de acción (Solución #1)

**Archivo:** `definitions/playbooks/compra.yaml`

**Línea a editar (~línea 273):** la instrucción OBLIGATORIO del bloque.

Estado actual (HEAD `aa05036`):
```
⛔ OBLIGATORIO: si $intencion_inicial o el input contiene CUALQUIER marcador temporal de entrega, EJECUTA ESTE BLOQUE ANTES de cualquier otra cosa — aunque NO haya producto mencionado todavia. Un input como 'lo necesito para este viernes' o 'necesito algo para hoy' activa este bloque aunque no se sepa aun que producto quiere el usuario.
```

Estado objetivo (restaurar frase de `76cbe39`):
```
⛔ OBLIGATORIO: si $intencion_inicial o el input contiene CUALQUIER marcador temporal de entrega, EJECUTA ESTE BLOQUE ANTES de cualquier otra cosa — aunque NO haya producto mencionado todavia. Un input como 'lo necesito para este viernes' o 'necesito algo para hoy' activa este bloque aunque no se sepa aun que producto quiere el usuario. NUNCA saltes al catalogo ni al slot-filling sin haber informado primero la politica de envio.
```

**Pasos:**
1. Editar `definitions/playbooks/compra.yaml` — añadir la frase al final de la línea OBLIGATORIO (ver diff arriba)
2. Commit + PR + merge
3. Esperar deploy CI/CD
4. Re-ejecutar: `python qap/surgical_run.py --test TC-URGENCIA-01,TC-URGENCIA-03 --runs 3`

**Coste total estimado:** ~10 min (1 min edición + 3 min deploy + 6 min rerun × 3)

---

### Nota de patrón cruzado

Este TC comparte bloque de código con **TC-URGENCIA-01** (variante "hoy a las 6"). Ambos dependen del mismo bloque DETECCION RESTRICCION TEMPORAL. Aplicar Solución #1 resuelve ambos TCs simultáneamente — re-ejecutar los dos en el mismo rerun post-fix.

> **Diferencia respecto a análisis 20260527:** en runs anteriores el FAIL era por ausencia total del bloque (revert `2126c52`). En este run (20260701) el bloque existe pero fue debilitado colateralmente por el refactor `aa05036`. El fix es diferente: antes era cherry-pick de 14 líneas; ahora es restaurar 1 frase.
