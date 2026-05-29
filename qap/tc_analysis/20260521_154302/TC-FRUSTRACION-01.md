---
status: FAIL
tipo: Bug Playbook
estimacion: ~20 min (Solución #1 recomendada)
---

## TC-FRUSTRACION-01 — Rechazo 2 no pregunta motivo: el agente muestra más flores en lugar de preguntar qué falla

### Turnos vs Problemas detectados

| # | Quién | Acción / Texto | Problema detectado |
|---|-------|----------------|--------------------|
| 1 | Usuario | "quiero rosas" | — |
| 1 | Agente | "¿Para qué ocasión son las rosas?" | Sin problema. Entrada normal al flujo de compra. |
| 2 | Usuario | "no me gustan" | Rechazo 1. |
| 2 | Agente | "Entiendo, disculpa la confusión. Te busco una alternativa. ¿Qué tipo de flor te gustaría?" | Sin problema. TONO RECONOCIMIENTO + reformula = correcto para Rechazo 1. ✅ |
| 3 | Usuario | "tampoco me convencen, dame otras" | Rechazo 2. |
| 3 | Agente | "Vale, te enseño otras que tengo: Peonías, Girasoles, Gerberas…" | 🔴 **Bug**: Rechazo 2 debe "preguntar motivo", no mostrar más productos. El agente interpretó "dame otras" como petición de catálogo y omitió el paso de diagnóstico. Check FAIL: `[propongo|alternativ.{0,30}tipo|otra ocasion|equipo|persona|humano]`. |
| 4 | Usuario | "ninguna me gusta" | Rechazo 3 (o equivalente tras el salto de Rechazo 2 al 3). |
| 4 | Agente | "Creo que lo mejor es que hables con mi equipo…" | Sin problema. Escalación correcta. ✅ |

---

### Causa raíz — evaluación de las 9 capas del sistema [v1.1 Capas rediseñadas]

🔴 1. **Capa Comportamiento** [verificada] · `definitions/playbooks/compra.yaml` líneas 722-743
La sección GESTION DE FRUSTRACION (l.726) lista las reglas de rechazo en una sola línea compacta:
`"RECHAZO ACUMULADO: rechazo 1 reformula. Rechazo 2 pregunta motivo. Rechazo 3 reformula y muestra una mas. Rechazo 4 ESCALAR."`
El LLM tiene dos instrucciones que compiten en el mismo turno: la regla de Rechazo 2 ("pregunta motivo") y la lógica general del flujo de compra que responde a "dame otras" mostrando productos. La formulación en enumeración densa no diferencia con suficiente énfasis cuándo una petición de "más opciones" del usuario debe ser ignorada en favor de la pregunta de diagnóstico. El resultado observado (mostrar más flores) es consistente con un LLM que prioriza la intención literal del usuario ("dame otras") sobre la regla de secuencia de frustración.

⚪ 2. **Capa Routing** · N/A — el fallo ocurre dentro del playbook `compra`, no hay cambio de flow ni de página involucrado.

🟢 3. **Capa Parámetros / Slots** [verificada] · `definitions/playbooks/compra.yaml` líneas 722-724
`$contador_rechazos` y `$frustracion_detectada` existen como parámetros declarados. El Rechazo 1 se gestionó correctamente (turno 2), lo que sugiere que el contador sí se incrementa. El problema no es la ausencia del parámetro sino que la instrucción asociada al valor `$contador_rechazos=2` no es lo suficientemente imperativa para bloquear la respuesta de catálogo.

⚪ 4. **Capa Tool / API** · N/A — PetalDataTool no se invocó en el turno problemático (turno 3) de forma incorrecta; el bug es anterior a cualquier llamada a herramienta.

⚪ 5. **Capa Datos / Catálogo** · N/A — los productos mostrados (Peonías, Girasoles, Gerberas) son reales y correctos. El error no es qué se mostró sino que se mostró en lugar de preguntar el motivo.

🟢 6. **Capa Test** [verificada] · JSON del TC, turno 3
El check `[propongo|alternativ.{0,30}tipo|otra ocasion|equipo|persona|humano]` es correcto: captura tanto una pregunta de diagnóstico ("¿qué tipo…?", "¿otra ocasión?") como la escalación prematura. La respuesta del agente ("Vale, te enseño otras…") no contiene ninguno de esos términos. El test no está mal calibrado.

⚪ 7. **Capa Orquestador** · N/A — el orquestador (v65) cede el control al playbook `compra` correctamente; la secuencia de turnos es interna al playbook.

⚪ 8. **Capa Integración / Contexto externo** · N/A — no interviene ningún webhook, Sheet ni sistema externo en la lógica de frustración.

🟡 9. **Capa Flakiness / No determinismo** [supuesta] · sin datos de runs adicionales
Solo hay 1 run registrado. No se puede descartar que en algunos runs el LLM sí pregunte el motivo en Rechazo 2 (la instrucción existe pero es débil). Sin embargo, la redacción actual de la regla hace probable que el fallo sea consistente cuando el usuario usa el verbo "dame otras", que activa la rama de catálogo con más fuerza que la de diagnóstico.

**Resumen visual:** 1 🔴 · 2 🟢 · 1 🟡 · 5 ⚪

---

## Recomendación

### Dimensionamiento del bug

| Dimensión | Nivel | Justificación |
|---|---|---|
| Alcance | Trivial | Afecta exclusivamente la sección GESTION DE FRUSTRACION del playbook `compra.yaml`. Un solo bloque de texto a editar. |
| Profundidad | Trivial | La regla existe pero está redactada de forma ambigua. No requiere nueva lógica, solo refuerzo de la instrucción existente. |
| Riesgo de regresión | Trivial | La sección de frustración es autónoma; reforzar Rechazo 2 no afecta los turnos de Rechazo 1, 3 ni 4 ni ninguna otra rama del playbook. |

**Nivel final:** Trivial → 3 soluciones

---

### Solución recomendada: #1 — Reforzar la instrucción de Rechazo 2 con bloque imperativo explícito

🟢 **9/10** · ~20 min · sin dependencias externas

**Por qué**: La causa raíz es exclusivamente redaccional: la regla de Rechazo 2 compite en desventaja con la intención literal del usuario. Añadir un bloque explícito con verbo imperativo y condición de bloqueo ("NUNCA mostres productos antes de preguntar el motivo") elimina la ambigüedad sin tocar otros archivos ni lógica del sistema.

---

### Soluciones evaluadas (ordenadas por score)

| # | Solución | Score | Dependencias | Por qué este scoring |
|---|----------|-------|--------------|----------------------|
| 1 | Reforzar instrucción Rechazo 2 con bloque imperativo y ejemplo negativo en `compra.yaml` | 🟢 9/10 | Solo `compra.yaml` | Mínimo riesgo, ataca la causa raíz directamente, sin regresiones posibles. |
| 2 | Añadir ejemplo negativo al playbook (shot de lo que NO hacer en Rechazo 2) | 🟡 7/10 | Solo `compra.yaml` | Complementario a #1; por sí solo menos fiable que una instrucción imperativa. Puede combinarse con #1. |
| 3 | Añadir un `Example` de CX con el flujo de Rechazo 2 correcto para guiar al LLM por few-shot | 🟡 6/10 | `compra.yaml` + nuevo `Example` en Dialogflow CX | Mayor cobertura de guía, pero requiere crear y desplegar un artefacto adicional. Overkill para este bug. |

---

### Plan de acción (Solución #1)

1. Abrir `definitions/playbooks/compra.yaml`, sección GESTION DE FRUSTRACION (líneas 722-743).
2. Localizar la línea de RECHAZO ACUMULADO (l.726):
   ```
   1. RECHAZO ACUMULADO: rechazo 1 reformula. Rechazo 2 pregunta motivo. Rechazo 3 reformula y muestra una mas. Rechazo 4 ESCALAR.
   ```
3. Expandir el punto 1 añadiendo un sub-bloque imperativo para Rechazo 2, por ejemplo:
   ```
   1. RECHAZO ACUMULADO:
      - Rechazo 1: usa TONO RECONOCIMIENTO + reformula (pregunta tipo/color/presupuesto).
      - Rechazo 2: PREGUNTA MOTIVO OBLIGATORIAMENTE. NUNCA muestres productos en este paso.
        Pregunta: '¿Qué es lo que no te convence? ¿El tipo de flor, el color, el precio o el tamaño?'
        Solo cuando el usuario responda pasa al siguiente turno.
      - Rechazo 3: reformula aplicando la pista del Rechazo 2 y muestra una opción más.
      - Rechazo 4: ESCALAR con $razon_handoff='frustracion_usuario'.
   ```
4. Guardar, crear rama, commit, PR, merge y esperar deploy.
5. Rerun TC-FRUSTRACION-01: verificar que el turno 3 contiene `motivo`, `tipo`, `color`, `precio` o `tamaño` (cualquiera coincide con la regex del check).

**Coste total**: ~20 min (5 min edición + 2 min PR/merge + ~12 min deploy + 1 min rerun)
