---
status: FAIL
tipo: Test mal calibrado
estimacion: ~5 min (Solución #1 recomendada)
---

## TC-C35

### Turnos vs Problemas detectados

| # | Quién | Acción / Texto | Problema detectado |
|---|-------|---------------|--------------------|
| 1 | Usuario | "Es para alguien especial" | — |
| 1 | Agente | "¡Claro! 🌸 ¿Tienes alguna flor o color en mente?" | Check espera `ocasion\|celebra\|regalo\|cumpleanos\|boda\|tipo` pero el agente pregunta por flor/color — **comportamiento correcto según playbook** |

### Causa raíz — evaluación de las 9 capas

🟢 1. **Capa Comportamiento** [verificada] · `compra.yaml PASO EXPLORAR + FLUJO TURNO INICIAL`
El Orquestador ya pasó `ocasion_detectada='Regalo'`. El playbook indica: `PASO EXPLORAR → Si $ocasion_detectada vacío → pregunta usando muestras 'no sabe que elegir'`. Como `ocasion_detectada` tiene valor, el bloque de pregunta de ocasión NO se activa. Petal avanza directo al FLUJO TURNO INICIAL y pregunta flor/color. El comportamiento del agente es exactamente el correcto.

🔴 2. **Capa Routing** [verificada] · `tc_1_1.yaml TC-C35 checks`
El check `ocasion|celebra|regalo|cumpleanos|boda|tipo` asume que el agente debe preguntar la ocasión. Pero el TC no configura parámetro de entrada `grupo_intent` ni `ocasion_detectada` — el test llega a Compra sin indicar que la ocasión ya fue detectada upstream. Hay una disonancia entre lo que el JSON de run reporta (`ocasion_detectada="Regalo"` en params) y lo que el YAML del TC define como expected. El check está mal calibrado para el estado real del agente en turno 1.

⚪ 3. **Capa Tool** · N/A — no hay llamada a PetalDataTool en este turno.

⚪ 4. **Capa Parámetros** · N/A — los params de entrada no son el origen del FAIL; el FAIL está en el check, no en el slot-filling.

🟡 5. **Capa Examples** [supuesta] · `definitions/examples/` (Sheet no disponible)
Si existen examples de COMPRA-ZG con `ocasion_detectada='Regalo'` en turno 1, deberían mostrar al agente preguntando flor/color, no ocasión. La respuesta del agente coincide con este patrón esperado. 🟡 [supuesta] — sin acceso a Sheet ni a ejemplos de CX para verificar.

⚪ 6. **Capa Orquestador** · N/A — el Orquestador transfirió correctamente `ocasion_detectada='Regalo'`; el problema está en el check del test, no en el routing upstream.

⚪ 7. **Capa Catálogo** · N/A — no hay consulta de inventario en el turno fallido.

⚪ 8. **Capa Flakiness** · N/A — el FAIL es determinista: el check está estructuralmente mal alineado con el comportamiento del playbook. No hay varianza esperada entre runs.

⚪ 9. **Capa Infraestructura** · N/A — la respuesta del agente es coherente y completa; no hay señal de error de infra.

**Resumen visual:** 1 🔴 · 1 🟢 · 1 🟡 · 6 ⚪

---

## Recomendación

### Dimensionamiento del bug

| Dimensión | Nivel | Justificación |
|-----------|-------|---------------|
| Impacto en usuarios reales | Ninguno | El agente se comporta correctamente |
| Riesgo de regresión | Bajo | El fix es solo en el YAML del TC |
| Complejidad del fix | Mínima | Cambiar 1 línea de check en `tc_1_1.yaml` |
| Urgencia | Media | FAIL espurio contamina el reporting de la suite |

**Nivel final:** Bajo → 3 soluciones

### Solución recomendada: #1 — Recalibrar el check para que valide flor/color

🟢 9/10 · ~5 min

El agente pregunta `¿Tienes alguna flor o color en mente?` porque el playbook, dado que ya tiene `ocasion_detectada`, salta la pregunta de ocasión y pregunta por producto. El check debe validar que el agente pregunta por flor, color o tipo de producto — no por la ocasión.

### Soluciones evaluadas

| # | Solución | Score | Dependencias | Por qué |
|---|----------|-------|--------------|---------|
| 1 | Cambiar check a `flor\|color\|mente\|tipo\|producto\|tenias` en `tc_1_1.yaml` | 9/10 | Ninguna | Alinea el check con el comportamiento real del playbook cuando `ocasion_detectada` tiene valor |
| 2 | Añadir parámetro `ocasion_detectada: ""` en el TC para forzar el flujo de pregunta de ocasión | 6/10 | Requiere entender si el runner CX acepta params de entrada por TC | Cambia el escenario de prueba; el caso "alguien especial con ocasión ya detectada" se pierde |
| 3 | Dividir en dos TCs: uno sin `ocasion_detectada` (pide ocasión) y otro con valor (pide flor/color) | 7/10 | Añadir TC nuevo | Más cobertura, pero mayor mantenimiento; el escenario sin ocasión ya está cubierto por COMPRA-ZG general |

### Plan de acción (Solución #1)

1. Abrir `/qap/tc_1_1.yaml`, localizar `TC-C35`.
2. Cambiar la línea de check:
   - **Antes:** `- ocasion|celebra|regalo|cumpleanos|boda|tipo`
   - **Después:** `- flor|color|mente|tipo|producto|tenias`
3. Verificar que el nuevo check es suficientemente amplio para atrapar variantes naturales de "¿tienes alguna flor o color en mente?" sin ser demasiado permisivo.
4. Hacer commit y rerun del TC para confirmar PASS.
