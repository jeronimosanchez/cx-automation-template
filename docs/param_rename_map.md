# Mapa de renombrado de parámetros — Petal Playbooks

**Fecha:** 2026-07-02 | **Estado:** borrador — pendiente de validación QA post-rename

> Fuente de verdad para el script de rename transversal.
> Generado sobre `definitions/playbooks/*.yaml` — reproducible con `python3` + `yaml`.

---

## Reglas de nomenclatura aplicadas

| Regla | Descripción | Tipo |
|---|---|---|
| R1 | snake_case estricto — sin mayúsculas internas | INDUSTRIA (AIP-140) |
| R2 | Sin prefijo booleano `es_` — el tipo ya declara BOOLEAN | INDUSTRIA (AIP-140) |
| R3 | Sin sufijo de proceso implícito (`_detectada`, `_inicial`, `_duro`) | PROPIA |
| R4 | Sin prefijo de sujeto redundante (`usuario_`) | PROPIA |
| R5 | 5 términos AIP siempre abreviados: `config`, `id`, `info`, `spec`, `stats`. Resto: solo si >~15 chars y abreviación inequívoca | INDUSTRIA+PROPIA |
| R6 | Preservar diferenciador mínimo ante colisión de nombres | PROPIA |
| R7 | Singular para escalares, plural para listas (ARRAY) | INDUSTRIA |
| R8 | Nunca mayúsculas — CX es case-insensitive (colisión silenciosa) | Adapter CX |

---

## Tabla completa — 30 parámetros

`⚠️` = bug de tipo inconsistente entre playbooks — requiere decisión antes de ejecutar rename.

| Nombre actual | Nombre nuevo | Tipo | Regla | Playbooks afectados | Descripción |
|---|---|---|---|---|---|
| `Direccion_Habitual` | `dir_habitual` | STRING | R1+R5 | Compra, Orchestrator, Checkout, Registro_Task | Dirección guardada en BD del cliente. Default de entrega. |
| `apellidos` | igual | STRING | — | Registro_Task | Apellidos del cliente, capturado en Registro_Task. |
| `cantidad` | igual | NUMBER | — | Compra, Checkout, Gestion_Deuda, Orchestrator | Unidades del producto principal confirmadas. |
| `cantidad_2` | igual | NUMBER | — | Compra, Checkout | Unidades del segundo producto (flujo multi-producto). |
| `contador_rechazos` | igual | NUMBER | — | Compra | Contador interno de rechazos. Controla escalado a Handoff. |
| `direccion_entrega` | `dir_entrega` | STRING | R5 | Checkout, Gestion_Deuda | Dirección de entrega confirmada para el pedido actual. |
| `email` | igual | STRING | — | Registro_Task, Checkout, Orchestrator | Email del cliente. Si existe, Registro no lo pide. |
| `es_urgente` | `urgente` | BOOLEAN | R2 | Compra, Checkout, Handoff, Orchestrator | Restricción temporal explícita. Modifica estructura del flujo. |
| `estado_emocional` | `emocion` | STRING | R3 | Orchestrator | Estado emocional detectado: duelo / frustración / neutro. |
| `estado_pago` | igual | STRING | — | Compra, Checkout, Orchestrator, Registro_Task | Estado de cuenta: Al día / Pendiente / Deuda. |
| `grupo_intent` | igual | STRING | — | Compra, Orchestrator | Grupo semántico detectado (G3, G5, G6, G7). |
| `id_cliente` | igual | STRING | — | Compra, Checkout, Gestion_Deuda, Handoff, Orchestrator, Registro_Task | ID numérico único del cliente en el Google Sheet. |
| `intencion_inicial` | `intencion` | STRING | R3 | Compra, Orchestrator | Intención del cliente al inicio (compra, consulta, reclamación…). |
| `nombre_cliente` | `nombre` | STRING | R4 | Compra, Checkout, Gestion_Deuda, Handoff, Orchestrator, Registro_Task | Nombre del cliente obtenido del perfil en BD. |
| `ocasion_detectada` | `ocasion` | ⚠️ ARRAY/STRING | R3 | Compra, Checkout, Orchestrator | Ocasión del pedido: Funeral, Boda, Regalo, Decoración. |
| `precio_2` | igual | NUMBER | — | Compra, Checkout | Precio estimado del segundo producto (multi-producto). |
| `precio_estimado` | `precio_est` | NUMBER | R3+R6 | Compra, Checkout, Gestion_Deuda | Precio total estimado del pedido en euros. |
| `precio_max` | igual | NUMBER | — | Orchestrator | Presupuesto máximo indicado por el cliente. |
| `presupuesto_duro` | `pres_duro` | BOOLEAN | R3 | Compra | `precio_max` es tope firme (true) o aproximado (false). |
| `producto` | igual | STRING | — | Compra, Checkout, Gestion_Deuda, Orchestrator | Nombre del producto principal confirmado. |
| `producto_2` | igual | STRING | — | Compra, Checkout | Segundo producto en flujo multi-producto. |
| `razon_handoff` | `razon` | STRING | R3 | Compra, Checkout, Gestion_Deuda, Handoff, Orchestrator, Registro_Task | Motivo del traspaso a operador humano. |
| `recien_registrado` | `recien_reg` | ⚠️ BOOLEAN/STRING | R5 | Orchestrator, Checkout, Registro_Task | El cliente se registró en esta sesión. |
| `referencia_pedido` | `referencia` | STRING | R3 | Checkout | Número de referencia del pedido confirmado. |
| `registro` | igual | STRING | — | Compra, Checkout, Gestion_Deuda, Handoff, Orchestrator | Tono activo: solemne / celebracion / estandar. |
| `saldo` | igual | NUMBER | — | Gestion_Deuda, Handoff | Saldo del cliente en euros. Negativo = deuda. |
| `sesion_cerrada` | `fin_sesion` | BOOLEAN | R3 | Checkout, Orchestrator, Registro_Task | La sesión terminó (cancelación, despedida, rechazo). |
| `telefono` | igual | STRING | — | Registro_Task | Teléfono del cliente. Puede quedar vacío. |
| `tipo_cliente` | igual | STRING | — | Compra, Checkout, Gestion_Deuda, Orchestrator | Particular o Empresa. Afecta tono y condiciones. |
| `usuario_frustrado` | `frustrado` | BOOLEAN | R4 | Compra, Checkout, Gestion_Deuda, Handoff, Orchestrator | Frustración activa detectada. |

**13 cambios — 17 sin cambio.**

---

## Bugs de tipo pendientes de decisión

Antes de ejecutar el rename, resolver:

| Param | Tipo actual | Conflicto | Decisión pendiente |
|---|---|---|---|
| `ocasion_detectada` | ARRAY en un playbook, STRING en otros | Tipo inconsistente entre playbooks | ¿ARRAY o STRING? |
| `recien_registrado` | BOOLEAN en uno, STRING en otros | Tipo inconsistente entre playbooks | ¿BOOLEAN o STRING? |

---

## Scope del script de rename

Archivos que el script debe procesar:

- `definitions/playbooks/*.yaml` — declarations + instruction body
- `definitions/examples/*.yaml` — si los params aparecen en examples
- `qap/tc_*.yaml` — test cases que referencian params por nombre
- `docs/parameter_audit.md` — tablas de params (actualizar en el mismo paso)
