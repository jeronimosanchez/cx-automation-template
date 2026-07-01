# TC-FRUSTRACION-01 — Análisis de causa raíz

**TC:** TC-FRUSTRACION-01  
**Nombre:** Múltiples rechazos consecutivos — debe escalar o reformular  
**Grupo:** COMPRA-ZG | **Tipo:** EDGE  
**Estado:** FAIL (0/1 runs)  
**Fecha análisis:** 2026-07-01  
**Analista:** qa-tc-analyzer (batch 20260701_170805)

---

## Resumen ejecutivo

FAIL real con causa mixta: **Bug Playbook por omisión** (escalación no se dispara cuando debería) + **calibración de test discutible en T2**. La instrucción `# GESTIÓN DE FRUSTRACIÓN` del playbook define correctamente la escalación a 4 rechazos, pero el agente no cuenta los rechazos correctamente ni aplica el protocolo en T2/T3. T4 es Bug Playbook claro: el cuarto rechazo debía escalar a Handoff y el agente sigue preguntando. T2 tiene calibración cuestionable: pedir clarificación ante ambigüedad es conducta razonable, pero el check lo penaliza.

---

## 1. Traza de turns

| Turn | User | Agent | Check | Veredicto |
|------|------|-------|-------|-----------|
| T1 | "quiero rosas" | Pregunta por ocasión | `[ocasion]` | PASS |
| T2 | "no me gustan" | Pide clarificación: ¿las rosas o la pregunta de ocasión? | `[otra\|alternativ\|otras\|propongo\|encaja\|tipo]` | FAIL |
| T3 | "tampoco me convencen, dame otras" | Ofrece Peonías, Girasoles, Gerberas | `[propongo\|alternativ.{0,30}tipo\|otra ocasion\|equipo\|persona\|humano]` | FAIL |
| T4 | "ninguna me gusta" | Sigue preguntando preferencias | `[equipo\|persona\|humano\|hablar\|asistente\|encontrar\|contacto\|disculpa\|otra ocasion]` | FAIL |

---

## 2. Análisis por capa (9 capas)

### Capa 1 — Clasificación de input

**T2:** El input "no me gustan" es genuinamente ambiguo en contexto. El agente acaba de preguntar "¿Es para alguna ocasión especial?" y el usuario responde "no me gustan" sin referente claro. La clasificación `RECHAZO EXPLICITO` (que dispararía `FLUJO TURNO DE ALTERNATIVAS`) requiere que el rechazo sea sobre las opciones mostradas — pero en T2 no se han mostrado opciones aún. El agente clasifica como petición de clarificación, lo cual es defensible.

**T3:** El input "tampoco me convencen, dame otras" es un `RECHAZO EXPLICITO` inequívoco. El agente clasifica correctamente y ejecuta `FLUJO TURNO DE ALTERNATIVAS`. Resultado correcto en conducta, pero el check espera también términos de escalación que no aplican aún según la lógica del playbook (es el primer rechazo claro sobre opciones mostradas).

**T4:** El input "ninguna me gusta" es otro `RECHAZO EXPLICITO`. Según los contadores del playbook, en este punto `contador_rechazos >= 4` (T2 ambiguo + T3 explícito + T4 explícito + posiblemente el rechazo implícito al no elegir nada en T1). El agente debía escalar. No lo hace.

### Capa 2 — Instrucción de escalación (sección `# GESTIÓN DE FRUSTRACIÓN`)

El playbook **sí tiene** instrucción explícita de escalación:

```
DISPARADORES:
1. RECHAZO ACUMULADO: rechazo 1 reformula. Rechazo 2 pregunta motivo. 
   Rechazo 3 reformula y muestra una más. Rechazo 4 ESCALAR.
```

Y la acción de escalación está definida:

```
ESCALACIÓN: transfiere a Handoff. Aplica $registro.
Activar: $razon_handoff='frustracion_usuario' -> ${PLAYBOOK:Handoff} con 
$razon_handoff, $id_cliente, $nombre_cliente, $registro, $es_urgente, $usuario_frustrado.
```

**Conclusión capa 2:** la instrucción existe. El problema es que el agente no la está aplicando. Esto puede ser:
- (a) El agente no contabiliza `contador_rechazos` correctamente (T2 es ambiguo, no cuenta → llega a T4 como rechazo 2, no 4).
- (b) El LLM pierde el hilo del contador entre turnos al no tener valor explícito en `params`.

### Capa 3 — Estado de parámetros en el trace

Los `params` del JSON del TC muestran en todos los turnos:
- `grupo_intent: "G5"`, `intencion_inicial: "quiero rosas"`, `producto: "rosas"`
- **Ausencia total de:** `contador_rechazos`, `frustracion_detectada`, `usuario_frustrado`

Esto confirma que el runner de QA no está capturando/propagando estos contadores entre turnos. El agente no tiene acceso explícito al valor acumulado — debe inferirlo del histórico de la conversación, lo que es inestable en un LLM.

### Capa 4 — Calibración del check T2

**T2 check:** `[otra|alternativ|otras|propongo|encaja|tipo]`

La respuesta del agente en T2 es: *"¿No te gustan las rosas o no te gusta la idea de que sea para una ocasión especial?"*

Esta respuesta es razonable ante input ambiguo. El playbook no tiene instrucción explícita sobre qué hacer cuando un input pre-catálogo es ambiguo entre "rechazo del producto" y "rechazo de la pregunta de ocasión". Pedir clarificación es la conducta más segura para no asumir un rechazo de producto que tal vez no existe.

**Veredicto calibración T2:** el check es **demasiado exigente**. Espera alternativas directas en un momento donde el agente aún no sabe si hay rechazo de producto. Se podría aceptar tanto la clarificación como ofrecer alternativas.

### Capa 5 — Calibración del check T3

**T3 check:** `[propongo|alternativ.{0,30}tipo|otra ocasion|equipo|persona|humano]`

El agente en T3 dice: *"Vale, entiendo. Mira, te puedo ofrecer: Ramo de Peonías Coral — M (15 flores, 35€), Ramo de Girasoles Amarillo — M (10 flores, 20€), Ramo de Gerberas Amarillo — M (10 flores, 18€). ¿Alguna de estas te convence más?"*

El agente claramente ofrece alternativas. El problema es que el check usa `alternativ.{0,30}tipo` (la palabra "alternativa" seguida en 30 chars de "tipo") y el agente usa "te puedo ofrecer" en lugar de "alternativas". La palabra "alternativas" no aparece en la respuesta.

**Veredicto calibración T3:** el check es **parcialmente mal calibrado**. El agente hace lo correcto (ofrece otras flores) pero el check no captura esa conducta. Alternativa: añadir `ofrecer|ofrezco|puedo ofrecer` al regex, o revisar si en este punto ya se esperaba escalación parcial.

### Capa 6 — T4: Bug Playbook claro

**T4:** El agente dice *"Entiendo que no encuentras lo que buscas. ¿Quizás tienes alguna flor o color en mente que te guste más?"*

En T4, el historial de rechazos es:
- T2: rechazo ambiguo (¿cuenta como 1?)
- T3: rechazo explícito (cuenta como rechazo 1 o 2)
- T4: rechazo explícito sobre 3 alternativas nuevas (cuenta como rechazo 2 o 3)

Bajo la lógica más conservadora (solo T3 y T4 cuentan como rechazos claros sobre opciones), el agente debería estar en "rechazo 2 → pregunta motivo". Eso es lo que hace: pregunta si tiene preferencia de flor/color.

Bajo la lógica más generosa (T2 ambiguo + T3 + T4 = 3 rechazos), debería "reformular y mostrar una más".

**El agente nunca llega al umbral 4 de escalación** en esta conversación de 4 turnos. El TC tiene el nombre "múltiples rechazos consecutivos — debe escalar" pero el flujo de la conversación no alcanza el umbral definido en el playbook (rechazo 4).

**Conclusión capa 6:** hay un desajuste entre la expectativa del TC (que espera escalación en T4) y la instrucción del playbook (que escala en rechazo 4, no antes). Si el contador parte desde T1 o T2, la aritmética no cierra en 4 rechazos dentro de este TC de 4 turnos.

### Capa 7 — Problema raíz real

Hay **dos problemas independientes**:

**P1 (Bug Playbook — omisión de umbral claro):** La instrucción no define desde cuándo empieza a contar el `contador_rechazos`. ¿Cuenta T2 (ambiguo, pre-catálogo)? ¿Solo cuentan rechazos sobre opciones mostradas? Sin esta definición, el LLM no puede aplicar el umbral de forma consistente.

**P2 (Bug Test — expectativa adelantada):** El TC espera escalación en T4, pero el playbook escala en rechazo 4. Si T2 no cuenta (razonable: no había opciones), T3 es rechazo 1 y T4 es rechazo 2. La escalación ocurriría en un hipotético T6, no en T4. El TC está mal dimensionado para validar la escalación: necesita al menos 5-6 turnos.

### Capa 8 — Patterns cruzados

- El parámetro `usuario_frustrado` existe como input/output del playbook pero el trace no lo muestra propagado. Esto sugiere que el runner de QA no envía parámetros de estado acumulado en turnos subsiguientes, lo que impide que el LLM aplique lógica de contadores de forma fiable.
- La instrucción de frustración tiene `$frustracion_detectada=true` como disparador por "palabras negativas", pero "no me gustan" / "no me convencen" / "ninguna me gusta" no están en la lista de palabras negativas explícitas del playbook (`'no funciona','que mal','no me entiendes','un desastre','esto no va'`). El usuario de este TC no usa lenguaje explícitamente negativo — solo expresa preferencias negativas, que son distintas.

### Capa 9 — Veredicto consolidado

| Componente | Tipo problema | Severidad |
|---|---|---|
| T4: agente no escala | Bug Playbook — umbral mal definido (inicio del contador) | MEDIA |
| T3: check no captura "te puedo ofrecer" | Bug Test — regex incompleto | MEDIA |
| T2: check penaliza clarificación razonable | Bug Test — calibración excesiva | BAJA |
| TC no alcanza umbral de 4 rechazos | Bug Test — TC mal dimensionado | ALTA |

---

## 3. Causa raíz principal

**Bug Test — TC mal dimensionado (primario):** el TC tiene 4 turnos y espera escalación por "múltiples rechazos", pero la instrucción del playbook escala en rechazo 4, y la conversación solo puede acumular 2-3 rechazos netos en 4 turnos. El TC no puede pasar sin que el agente escale antes de lo que el playbook indica, o sin que el TC tenga más turnos.

**Bug Playbook — omisión de definición de umbral de contador (secundario):** la instrucción no especifica si rechazos ambiguos pre-catálogo cuentan para `contador_rechazos`. Sin esa definición, el LLM aplica el umbral de forma inestable.

---

## 4. Soluciones propuestas (ordenadas DESC por score)

### Solución A — Alargar el TC a 6 turnos + ajustar check T3 [SCORE: 9/10]

**Tipo:** Bug Test  
**Archivos:** `qap/test_cases/` (TC-FRUSTRACION-01)  
**Tiempo estimado:** 15 min  

**Cambios:**
1. Añadir T5 y T6 al TC para que el agente acumule 4 rechazos claros sobre opciones mostradas.
2. Mover el check de escalación (`equipo|persona|humano|...`) a T5 o T6.
3. En T3, cambiar el check a `[ofrecer|ofrezco|puedo ofrecer|otra|alternativ|mira|encaj]` para capturar la conducta correcta del agente.
4. En T2, cambiar check a `[otra|alternativ|aclar|refieres|quieres decir]` (acepta tanto clarificación como alternativas directas).

**Justificación:** el agente sigue la instrucción del playbook. El TC está mal calibrado para validarla. Alargar el TC es la solución que valida la conducta real sin cambiar el diseño del playbook.

**Riesgo:** ninguno sobre producción.

---

### Solución B — Añadir al playbook definición explícita del inicio del contador [SCORE: 7/10]

**Tipo:** Bug Playbook (mejora de robustez)  
**Archivos:** `definitions/playbooks/compra.yaml`  
**Tiempo estimado:** 10 min  

**Cambios en sección `# GESTIÓN DE FRUSTRACIÓN`:**

Añadir tras el bloque DISPARADORES:

```
NOTA CONTADOR: $contador_rechazos se incrementa SOLO cuando el usuario rechaza 
opciones de producto que Petal ha mostrado explicitamente. 
Inputs ambiguos pre-catalogo (ej: 'no me gustan' antes de mostrar opciones) 
NO cuentan. El contador parte de 0 al inicio del flujo.
```

**Justificación:** elimina la ambigüedad sobre qué cuenta como rechazo, haciéndolo reproducible para el LLM.

**Riesgo:** cambio en instrucción del playbook → requiere deploy vía pipeline.

---

### Solución C — Combinada A + B [SCORE: 8/10]

**Tipo:** Bug Test + Bug Playbook  
**Tiempo estimado:** 25 min  

Aplicar ambas soluciones: alargar el TC (A) y aclarar el contador en el playbook (B). La combinación garantiza que el TC valide correctamente la instrucción clarificada.

**Orden recomendado:** primero B (deploy playbook), luego A (ajustar TC y rerun).

---

## 5. Recomendación

**Aplicar Solución A primero** (solo test, sin deploy): ajustar el TC para que tenga 6 turnos con 4 rechazos claros sobre opciones, y corregir los checks de T2 y T3. Esto permite validar si el agente escala correctamente con el playbook actual.

Si el agente sigue sin escalar tras el TC ampliado, aplicar también Solución B para clarificar el contador en el playbook.

**No bloquear por T2:** la calibración de T2 es el problema menor. El agente pide clarificación ante input genuinamente ambiguo — eso es conducta correcta que el check penaliza incorrectamente.

---

## 6. Metadata

```
tc_id: TC-FRUSTRACION-01
causa_primaria: bug_test
causa_secundaria: bug_playbook_omision
playbook_afectado: compra.yaml
seccion_playbook: GESTIÓN DE FRUSTRACIÓN > DISPARADORES
turns_fail: [T2, T3, T4]
turns_pass: [T1]
calibracion_check_t2: excesiva
calibracion_check_t3: incompleta (falta "ofrecer")
tc_dimension: insuficiente (4 turnos vs umbral rechazo-4)
sheet_disponible: false
fix_deploy_requerido: false (Solución A) / true (Solución B)
```
