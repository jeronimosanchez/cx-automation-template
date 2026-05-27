---
status: FAIL
tipo: Bug Playbook
estimacion: ~15 min (Solución #1 recomendada)
---

# TC-URGENCIA-03 — Entrega urgente, plazo "este viernes"

**Run:** 20260527_151044 · 3 runs · 0/3 PASS
**Grupo:** COMPRA-ZG · **Tipo:** EDGE
**Versiones:** Orquestador v65 · Compra v39 · Checkout v33 · Registro v7 · script v23

## T1

| Run | Usuario | Respuesta del agente | Check |
|---|---|---|---|
| 1 | "lo necesito para este viernes" | "De acuerdo, para este viernes. ¿Qué tipo de producto buscas, o para qué uso lo necesitas?" | FAIL |
| 2 | "lo necesito para este viernes" | "Entendido. ¿Para qué tipo de ocasión sería? ¿O tienes algún tipo de flor en mente?" | FAIL |
| 3 | "lo necesito para este viernes" | "De acuerdo, lo necesitas para este viernes. ¿Alguna de las opciones mostradas te sirve?" | FAIL |

**Regex esperada:** `24h|24 horas|plazo|días|dias|llega|tiempo.{0,20}entrega|entrega.{0,20}tiempo`

En ningún run el agente menciona el plazo de entrega, el tiempo estándar (24h/48h) ni confirma viabilidad para "este viernes". En 2 de 3 runs ni siquiera ecoa la fecha; en el run 3 la ecoa pero no la valida ni la enlaza con la política de envíos.

### Turnos vs Problemas detectados

| Turno | Problema |
|---|---|
| T1 | El usuario expresa una restricción temporal explícita ("este viernes") y el agente la ignora o la ecoa sin acción. No consulta `tiempo_entrega_estimado` del Sheet ni informa de la política de envíos (24h Madrid/Barcelona, 48h resto). La fecha relativa "este viernes" no se captura en ningún slot estructurado — se queda dentro de `intencion_inicial` como texto plano. |

### Causa raíz — evaluación de las 9 capas del sistema

**Capa 1 — Comportamiento (Playbooks + Examples + Generators):** 🔴 [verificada · `definitions/playbooks/compra.yaml`]
El playbook Compra **no contiene ningún bloque** que detecte expresiones de plazo/fecha del usuario ni que dispare una respuesta sobre tiempos de entrega. Verificado: `grep -n "URGENCIA\|24h\|plazo\|fecha" definitions/playbooks/compra.yaml` solo devuelve 3 matches y todos son ejemplos en otras secciones (línea 475 "tiene que llegar el viernes" como ejemplo de EXPANSION DE CONTEXTO, línea 484 "se entrega hoy" como ejemplo de PREGUNTA, línea 111 `direccion_entrega`). Ninguno es un bloque accionable. **Causa raíz directa.**

**Capa 2 — Routing (Flows + Pages + Intents):** ⚪ N/A — Petal usa arquitectura Playbook-first, no hay routing por Intents para este caso.

**Capa 3 — Parámetros / Slots:** 🟡 [supuesta · trace del JSON]
El Orquestador captura `intencion_inicial="lo necesito para este viernes"` pero **no extrae `fecha_solicitada` como slot estructurado**. La información temporal queda atrapada en texto plano dentro del campo `intencion_inicial`, por lo que aunque Compra quisiera consultarla, tendría que re-parsearla. Contribuye al problema pero no es la causa raíz: aunque el slot existiera, sin Capa 1 nadie lo consumiría.

**Capa 4 — Integración (Tools + Webhooks + API backend):** ⚪ N/A — la consulta a `petal-sheet-api` para `tiempo_entrega_estimado` está disponible pero no se está invocando (eso es Capa 1).

**Capa 5 — Datos (Sheet):** 🟢 [verificada · `_shared_context.md`]
El Sheet expone `tiempo_entrega_estimado="24h en Madrid y Barcelona, resto de ciudades 48 horas"` y además `horario_corte_mismo_dia="14:00"` (same-day en Madrid antes de las 14:00). Datos suficientes para responder con precisión sobre "este viernes": basta calcular si hoy+24/48h ≤ viernes para confirmar viabilidad. Los datos están — el playbook no los consulta.

**Capa 6 — Infraestructura (Environments + Versions + Agent Config):** ⚪ N/A — no hay indicios de problema de versión o entorno; las 3 ejecuciones fallan con el mismo patrón en versiones estables (Compra v39, Orquestador v65).

**Capa 7 — Modelo / LLM:** 🟡 [supuesta · 3/3 runs sin mención de plazo]
El LLM detecta lingüísticamente "este viernes" (en run 3 lo ecoa correctamente) pero sin instrucción explícita en el playbook no sabe que debe (a) capturarlo como dato accionable y (b) responder con la política de envíos. No es alucinación: es ausencia de instrucción. La variabilidad entre runs (eco vs no eco, pregunta tipo vs ocasión vs opciones) sugiere que el LLM intenta avanzar el flujo principal sin "ver" la restricción temporal.

**Capa 8 — Histórico:** 🟡 [verificada · git log]
Patrón de ping-pong sobre el bloque urgencia documentado en `_shared_context.md`:
```
3f041df (PR #83) add CASO ESPECIAL urgencia/plazo
aca187c (PR #84) Revert #83
3e0b2d1          add bloque DETECCION URGENCIA TEMPORAL
1f95cae          Revert
a10ab02          add (Sol#1 TC-URGENCIA-01)
2126c52          Revert (HEAD actual)
```
El bloque ha sido añadido y revertido tres veces. La última reversión (`2126c52`) es la causa de que TC-URGENCIA-01 y TC-URGENCIA-03 vuelvan a fallar. Cualquier nueva solución debe documentar por qué los reverts anteriores ocurrieron (probable: efectos colaterales sobre otros TCs) y cómo se mitigan.

**Capa 9 — Test:** 🟢 [verificada · regex del check]
El check `24h|24 horas|plazo|días|dias|llega|tiempo.{0,20}entrega|entrega.{0,20}tiempo` es razonable y amplio. Acepta múltiples formulaciones válidas (ej. "te llega el jueves", "el plazo es 24h", "el tiempo de entrega son 2 días"). No es restrictivo en exceso.

**Resumen visual:** 1 🔴 · 2 🟢 · 3 🟡 · 4 ⚪

### Dimensionamiento del bug

- **Alcance:** Medio — afecta a TC-URGENCIA-01 (mismo patrón con "hoy a las 18:00") y a TC-URGENCIA-03 (este TC). Probablemente afecta a cualquier expresión temporal del usuario en T1.
- **Profundidad:** Medio — requiere añadir un bloque al playbook Compra y, opcionalmente, un slot estructurado en el Orquestador. No requiere cambios en backend ni en Sheet.
- **Riesgo:** Medio — hay historial de reverts. El cambio puede tener efectos colaterales sobre otros TCs de Compra (especialmente los que usan "viernes" como ejemplo de EXPANSION DE CONTEXTO en línea 475).
- **Nivel final: Medio → 5 soluciones**

## Recomendación

**Solución #1 — añadir bloque DETECCIÓN PLAZO/FECHA en compra.yaml** que cubra simultáneamente expresiones absolutas ("hoy a las 18:00") y relativas ("este viernes", "el lunes", "para el día X"). Esto cierra **a la vez TC-URGENCIA-01 y TC-URGENCIA-03** (misma causa raíz, mismo fix). Antes de aplicarlo, revisar los diffs de los reverts anteriores (`aca187c`, `1f95cae`, `2126c52`) para entender qué efecto colateral disparó cada revert y mitigarlo en esta iteración — sin ese paso, alta probabilidad de un cuarto ping-pong.

### Solución recomendada: #1 — Bloque DETECCIÓN PLAZO/FECHA en compra.yaml

Añadir al FLUJO PRINCIPAL de Compra un bloque de prioridad alta que:

1. Detecte expresiones temporales del usuario (absolutas y relativas).
2. Consulte `tiempo_entrega_estimado` del Sheet (ya disponible vía Tool inventario).
3. Responda confirmando viabilidad o explicando la política (24h Madrid/Barcelona, 48h resto, same-day Madrid antes 14:00).
4. Continúe el flujo normal de Compra tras informar.

### Soluciones evaluadas (ordenadas por score)

| # | Solución | Coste | Riesgo | Cobertura | Score |
|---|---|---|---|---|---|
| 1 | Bloque DETECCIÓN PLAZO/FECHA en compra.yaml (absolutas + relativas) consultando Sheet | Bajo (~15 min) | Medio (historial reverts) | Alta (cierra URGENCIA-01 y URGENCIA-03 + futuras variantes) | **9/10** |
| 2 | Slot estructurado `fecha_solicitada` en Orquestador + rama en Compra | Medio (~45 min) | Bajo | Muy alta (datos reusables por Checkout/Registro) | 7/10 |
| 3 | Bloque simple con respuesta fija ("24h Madrid/Barcelona, 48h resto") sin consultar Sheet | Muy bajo (~5 min) | Bajo | Media (cierra el check pero no valida viabilidad real) | 6/10 |
| 4 | Sub-playbook `Consulta_Logistica` reutilizable | Alto (~2h) | Medio | Muy alta (futuros TCs envío/zonas/horarios) | 5/10 |
| 5 | Relajar el check del test | Mínimo | Alto | Nula (anti-patrón) | 1/10 |

**Por qué #1 gana frente a #3:** ambos tienen coste similar pero #1 aprovecha el dato real del Sheet (incluido `horario_corte_mismo_dia` para same-day Madrid), lo que permite responder con precisión a "este viernes" en lugar de soltar una frase fija. **Por qué #1 gana frente a #2:** #2 es arquitectónicamente más limpio pero triplica el coste y requiere coordinar dos playbooks. Conviene dejarlo para una iteración posterior si aparecen más TCs de plazos. **Por qué #4 queda fuera:** ROI bajo hasta que haya 3+ TCs de logística distintos. **Por qué #5 es anti-patrón:** el check actual es razonable; relajarlo enmascara el bug real.

### Plan de acción (Solución #1)

1. **Investigar reverts previos (5 min):** `git show aca187c -- definitions/playbooks/compra.yaml` y `git show 2126c52 -- definitions/playbooks/compra.yaml` para entender qué provocó cada revert. Documentar la razón en el commit message del fix.
2. **Diseñar el bloque (5 min):** redactar el bloque "DETECCIÓN PLAZO/FECHA" que cubra expresiones absolutas ("hoy a las 18:00", "esta tarde") y relativas ("este viernes", "el lunes", "para el día 15"). Posicionarlo al inicio del FLUJO PRINCIPAL de Compra, antes de la rama de slot-filling, para que se dispare en T1.
3. **Editar `definitions/playbooks/compra.yaml` (5 min):** añadir el bloque. Verificar que no rompe el ejemplo "tiene que llegar el viernes" de la línea 475 (EXPANSION DE CONTEXTO) — esos ejemplos deben quedar como contexto adicional, no como triggers exclusivos del nuevo bloque.
4. **Test local (dry-run):** revisar el diff antes de commitear.
5. **Commit, PR, merge, deploy** (vía workflow estándar) y rerun de TC-URGENCIA-01 + TC-URGENCIA-03 con `--runs 3` para validar que ambos pasan y que ningún otro TC de Compra regresa.
6. **Si aparece regresión:** NO revertir reflexivamente — esto sería el cuarto ping-pong. Diagnosticar el efecto colateral concreto y ajustar el bloque (probable: especificidad de triggers o orden de evaluación dentro del playbook).

> **Forma parte del patrón URGENCIA-PLAZO.** Si el fix de TC-URGENCIA-01 resuelve la causa raíz común (ausencia de bloque de detección de plazo en compra.yaml), TC-URGENCIA-03 pasará a PASS sin cambios adicionales. Re-ejecutar antes de planificar fixes individuales.
