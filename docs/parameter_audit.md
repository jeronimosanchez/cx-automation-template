# Auditoría de parámetros — Petal Playbooks

Versión: v1.0 | Fecha: 2026-06-24 | Sprint: Fase 0.0

> Prerequisito del refactor Compra → ConsultaInventario_Task.  
> Documenta qué parámetro fluye por dónde antes de tocar ninguna declaración.

---

## 1. Inventario de parámetros por playbook

| Playbook | INPUT declarados | OUTPUT declarados |
|---|---|---|
| `petal_cx_orchestrator` | 9 | 16 |
| `compra` | 17 | 16 |
| `checkout` | 16 | 17 |
| `registro_task` | 1 | 11 |
| `gestion_deuda` | 8 | 3 |
| `handoff` | 4 | 0 |

### petal_cx_orchestrator

**INPUT (9):** `id_cliente`, `nombre_cliente`, `recien_registrado`, `intencion_inicial`, `cantidad`, `Direccion_Habitual`, `tipo_cliente`, `estado_pago`, `producto`

**OUTPUT (16):** `producto`, `cantidad`, `id_cliente`, `tipo_cliente`, `estado_pago`, `intencion_inicial`, `nombre_cliente`, `razon_handoff`, `Direccion_Habitual`, `recien_registrado`, `sesion_cerrada`, `email`, `ocasion_detectada`, `grupo_intent`, `precio_max`, `modo_tono`

### compra

**INPUT (17):** `id_cliente`, `nombre_cliente`, `Direccion_Habitual`, `tipo_cliente`, `estado_pago`, `intencion_inicial`, `cantidad`, `producto`, `ocasion_detectada`, `grupo_intent`, `presupuesto_duro`, `contador_presupuesto`, `modo_tono`, `contador_rechazos`, `contador_repeticion_slot`, `contador_sugerencias`, `frustracion_detectada`

**OUTPUT (16):** `producto`, `cantidad`, `precio_estimado`, `direccion_entrega`, `razon_handoff`, `sesion_cerrada`, `presupuesto_duro`, `contador_presupuesto`, `modo_tono`, `contador_rechazos`, `contador_repeticion_slot`, `contador_sugerencias`, `frustracion_detectada`, `producto_2`, `cantidad_2`, `precio_2`

### checkout

**INPUT (16):** `producto`, `cantidad`, `precio_estimado`, `id_cliente`, `nombre_cliente`, `direccion_entrega`, `tipo_cliente`, `estado_pago`, `referencia_pedido`, `razon_handoff`, `sesion_cerrada`, `ocasion_detectada`, `modo_tono`, `producto_2`, `cantidad_2`, `precio_2`

**OUTPUT (17):** `tipo_cliente`, `nombre_cliente`, `id_cliente`, `razon_handoff`, `cantidad`, `sesion_cerrada`, `direccion_entrega`, `recien_registrado`, `apellidos`, `email`, `Direccion_Habitual`, `estado_pago`, `telefono`, `producto`, `precio_estimado`, `ocasion_detectada`, `referencia_pedido`

### registro_task

**INPUT (1):** `email`

**OUTPUT (11):** `id_cliente`, `nombre_cliente`, `apellidos`, `email`, `tipo_cliente`, `Direccion_Habitual`, `telefono`, `sesion_cerrada`, `razon_handoff`, `recien_registrado`, `estado_pago`

---

## 2. Matriz de handoff explícito

Análisis de gaps entre OUTPUT del emisor e INPUT del receptor (handoff declarado).

### Orquestador → Compra

| | |
|---|---|
| **Orquestador emite** | `producto`, `cantidad`, `id_cliente`, `tipo_cliente`, `estado_pago`, `intencion_inicial`, `nombre_cliente`, `Direccion_Habitual`, `ocasion_detectada`, `grupo_intent`, `modo_tono` (+ `razon_handoff`, `recien_registrado`, `sesion_cerrada`, `email`, `precio_max`) |
| **Compra recibe (handoff)** | `id_cliente`, `nombre_cliente`, `Direccion_Habitual`, `tipo_cliente`, `estado_pago`, `intencion_inicial`, `cantidad`, `producto`, `ocasion_detectada`, `grupo_intent`, `modo_tono` |
| **Handoff limpio** | ✅ Los 11 parámetros de negocio coinciden |

**Gap aparente — variables no emitidas por Orquestador pero declaradas en INPUT de Compra:**

| Variable | Por qué no viene de Orquestador | Origen real |
|---|---|---|
| `presupuesto_duro` | Orquestador no lo detecta | Compra lo extrae de la conversación inline (`"máximo X"`, `"no más de X"`) |
| `contador_presupuesto` | No existe en Orquestador | Compra lo inicializa a 0 internamente |
| `contador_rechazos` | No existe en Orquestador | Compra lo inicializa a 0 internamente |
| `contador_repeticion_slot` | No existe en Orquestador | Compra lo inicializa a 0 internamente |
| `contador_sugerencias` | No existe en Orquestador | Compra lo inicializa a 0 internamente |
| `frustracion_detectada` | No existe en Orquestador | Compra lo detecta internamente |

**Gap aparente — Orquestador emite pero Compra no declara en INPUT:**

| Variable | Por qué | Diagnóstico |
|---|---|---|
| `precio_max` | Orquestador lo detecta si el usuario lo menciona durante la fase inicial | Compra lo re-extrae de la conversación inline; también está disponible en session state. Redundancia aceptable. |
| `razon_handoff`, `sesion_cerrada` | Variables de control de sesión | Gestionadas por el engine de CX, no por el playbook |
| `recien_registrado`, `email` | Datos de registro | Usados por Checkout y Registro, no por Compra |

**Veredicto: No hay bugs. El handoff Orquestador → Compra es correcto.**

---

### Compra → Checkout

| | |
|---|---|
| **Compra emite** | `producto`, `cantidad`, `precio_estimado`, `direccion_entrega`, `razon_handoff`, `sesion_cerrada`, `modo_tono`, `producto_2`, `cantidad_2`, `precio_2` (+ contadores/flags internos) |
| **Checkout recibe (handoff)** | `producto`, `cantidad`, `precio_estimado`, `direccion_entrega`, `razon_handoff`, `sesion_cerrada`, `modo_tono`, `producto_2`, `cantidad_2`, `precio_2` |
| **Handoff limpio** | ✅ Los parámetros de compra coinciden |

**Gap aparente — Checkout declara en INPUT pero Compra no emite:**

| Variable | Por qué no la emite Compra | Origen real |
|---|---|---|
| `id_cliente`, `nombre_cliente`, `tipo_cliente`, `estado_pago` | Compra no los re-emite | Session state persistente desde Orquestador |
| `ocasion_detectada` | Compra no la re-emite | Session state persistente desde Orquestador |
| `referencia_pedido` | No se pasa como handoff | Checkout la genera internamente al llamar al backend (`id_pedido` en la respuesta de la API) |

**Gap aparente — Compra emite pero Checkout no usa:**

| Variables | Diagnóstico |
|---|---|
| `contador_presupuesto`, `contador_rechazos`, `contador_repeticion_slot`, `contador_sugerencias`, `frustracion_detectada`, `presupuesto_duro` | Estado interno de Compra, no relevante para Checkout |

**Veredicto: No hay bugs. El handoff Compra → Checkout es correcto.**

---

### Checkout → Registro_Task

Registro_Task solo necesita `email`. Checkout emite 17 parámetros; Registro ignora los 16 restantes. 

**Veredicto: Correcto.**

---

### Registro_Task → Orquestador (re-entrada)

Los 3 parámetros que Orquestador declara como INPUT y Registro no emite (`cantidad`, `intencion_inicial`, `producto`) persisten en session state desde el inicio de la conversación.

**Veredicto: Correcto.**

---

## 3. Tres canales de parámetros en CX

El análisis revela que CX usa tres canales distintos, no uno solo:

```
┌─────────────────────────────────────────────────────────────┐
│  Canal A: Handoff explícito                                 │
│  outputParameterDefinitions → inputParameterDefinitions     │
│  Ejemplo: Compra → precio_estimado → Checkout               │
├─────────────────────────────────────────────────────────────┤
│  Canal B: Session state persistente                         │
│  Variable creada en playbook anterior, persiste en sesión   │
│  Ejemplo: Orquestador → id_cliente → disponible en Checkout │
├─────────────────────────────────────────────────────────────┤
│  Canal C: Extracción inline de conversación                 │
│  El playbook extrae slots del utterance del usuario         │
│  Ejemplo: Compra → precio_max a partir de "máximo 50€"      │
└─────────────────────────────────────────────────────────────┘
```

**Consecuencia para el refactor:** ConsultaInventario_Task recibirá sus parámetros vía handoff explícito (Canal A) desde Compra. No puede usar Canal C directamente — la extracción de slots ocurre en Compra antes de invocar la Task.

---

## 4. Parámetros que ConsultaInventario_Task necesitará

Basado en el análisis de cómo Compra llama a PetalDataTool:

| Parámetro | Fuente | Canal |
|---|---|---|
| `ocasion` | Slot extraído por Compra | A (Compra → Task) |
| `producto` | Slot extraído / heredado | A |
| `tipo` | Slot extraído por Compra | A |
| `color` | Slot extraído por Compra | A |
| `precio_max` | Slot extraído por Compra | A |
| `precio_min` | Slot extraído por Compra | A |
| `productos_excluidos` | Estado de Compra (rechazados) | A |

**Output de la Task:**
- `top_productos` (lista estructurada, top 3 rankeados)
- `sin_stock` (bool — fallback)

---

## 5. Hallazgos no bloqueantes

| Hallazgo | Impacto | Acción |
|---|---|---|
| `precio_max` duplicado (Orquestador emite, Compra re-extrae) | Ninguno en producción. Si el usuario cambia de precio entre Orquestador y Compra, Compra gana. | Aceptable. Documentar en Compra que lo re-extrae. |
| Contadores declarados en INPUT de Compra pero nunca recibidos | Ninguno (Compra los inicializa). La declaración permite re-invocar Compra con estado preservado si algún día se necesita. | Mantener. Es intencional. |
| Checkout emite 17 parámetros, Registro solo usa 1 | Ruido de handoff, sin impacto funcional. | Aceptable en V0. |

---

## 6. Estado de la auditoría

- [x] **0.0.1** Parámetros OUTPUT de cada playbook
- [x] **0.0.2** Parámetros INPUT de cada playbook
- [x] **0.0.3** Matriz de handoff cruzada
- [x] **0.0.4** Gaps y ruido detectados y clasificados
- [ ] **0.0.5** Commit — `docs(audit): parámetros entrada/salida entre playbooks`

---

## Notas

- Generado con script Python sobre `definitions/playbooks/*.yaml` — reproducible.
- Verificación manual de anomalías: `precio_max`, `presupuesto_duro`, `referencia_pedido`.
- Próximo paso: **Fase 0.1** — crear YAMLs de variables de negocio (`delivery_config`, `frustration_config`, `escalation_config`).
