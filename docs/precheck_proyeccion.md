# Precheck: proyección del backend de inventario

**Fecha:** 2026-07-05
**Auditor:** consistencia de datos CX (solo lectura)
**Alcance:** verificar que la proyección del backend (reducir a 9 campos por defecto) no rompa playbooks ni examples.

## La proyección auditada

Campos que el backend devolverá **por defecto** (9):
`Producto, Tipo_Producto, Especie, Color, Tamano, Ocasion, Stock, Precio, Descripcion_Cantidad`

Campos que **dejan de venir por defecto**:
- **Nunca** (internos/borrados): `Ventas_Anuales`, `Es_Temporada`, `Duracion`, `Tipo_Flor`.
- **Bajo demanda** (solo con `?fields=descripcion_corta,entrega`): `Descripcion_Corta`, `Entrega_Mismo_Dia`.

## Veredicto

**La proyección es SEGURA de desplegar tal cual. No hay que ajustar nada.**

Ningún playbook lee un campo dropeado, ningún example muestra un campo dropeado en `outputActionParameters`, y el contrato del tool no declara esquema por campo (los resultados son `object` libre), por lo que tampoco hay esquema fantasma a nivel de tool.

## Tabla de hallazgos

| Dónde (archivo/línea) | Campo dropeado usado | ¿Rompe con proyección? | Qué habría que ajustar |
|---|---|---|---|
| `playbooks/compra.yaml:613` (FORMATO AL USUARIO) | Ninguno. Usa `[Producto] [Color] -- [Tamano] ([Descripcion_Cantidad], [Precio]euros)`; dice "Omite: Stock" | NO | Nada. Todos los tokens ∈ set de 9 |
| `playbooks/compra.yaml:220-234` (DETECCIÓN RESTRICCIÓN TEMPORAL / entrega) | `Entrega_Mismo_Dia` — **NO se lee** | NO | La lógica de entrega responde desde política hardcodeada ("corte 14:00", "24h Madrid/BCN") y `$hora_actual`, no desde un campo de inventario |
| `playbooks/compra.yaml:326` (user pregunta 'cuanto duran' / 'se entrega hoy') | `Duracion` / `Entrega_Mismo_Dia` — **NO se leen** | NO | "Responde con datos" pero no hay regla que lea `Duracion`; ningún resultado de inventario transporta ese campo. Entrega se responde con la política temporal |
| `playbooks/compra.yaml:351` ("ya vienen ordenados por ventas") | `Ventas_Anuales` — uso **server-side** | NO | El backend ordena por ventas; el playbook no lee el campo, solo asume el orden. Sigue funcionando tras la proyección |
| `playbooks/checkout.yaml`, `petal_cx_orchestrator.yaml` | Ninguno de inventario | NO | Sus refs a "entrega" son `direccion_entrega` (dirección del pedido) y `Direccion_Entrega` (param de creación de pedido), NO campos de inventario |
| `tools/petaldatatool_openapi.yaml:265-268` | `resultados.items: type: object` (sin properties) | NO | El contrato del tool no enumera campos → no hay esquema fantasma a nivel de tool |

## Examples que muestran campos dropeados en sus outputs

**Ninguno.** Se auditaron los 8 examples de `compra/`, los 15 de `petal_cx_orchestrator/`, `checkout/` y `registro_task/`.

Las claves de campo presentes en todos los bloques `resultados:` de inventario son exclusivamente:
`Producto, Tipo_Producto, Especie, Color, Tamano, Ocasion, Stock, Precio, Descripcion_Cantidad` — es decir, el set de 9 exacto.

Ejemplos con resultados de inventario y campos que usan:
- `compra/exa_v9_...`, `exc_v9_...`, `exd_v13_...`, `exh_v16_...`: Producto/Especie/Color/Tamano/Precio/Descripcion_Cantidad/Ocasion.
- `compra/exi_v1_...`, `exj_v1_...`, `petal_cx_orchestrator/ex06_...`: los anteriores + `Tipo_Producto` y/o `Stock`.

No aparece en ningún output: `Ventas_Anuales`, `Es_Temporada`, `Duracion`, `Tipo_Flor`, `Descripcion_Corta`, `Entrega_Mismo_Dia`.

> Nota: las claves `Descripcion:` / `Valor:` / `Variable:` en los examples G1 del orquestador (`ex5b_g1_horario_apertura_business.yaml`, `ex5_ubicacin_tienda_pre-email_g1.yaml`) son resultados de **info de negocio** (horario, dirección de tienda), NO de inventario. Fuera del alcance de esta proyección.

## Matiz on-demand (`Descripcion_Corta`, `Entrega_Mismo_Dia`)

No aplica: **ningún artefacto los usa** — ni en flujo normal ni pidiéndolos explícitamente. No hay llamadas con `?fields=descripcion_corta,entrega`. La entrega se responde siempre desde la política temporal hardcodeada en `compra.yaml:220-234`, no leyendo `Entrega_Mismo_Dia`. Por tanto no hay ni riesgo de romper flujo ni dependencia on-demand que preservar.

## Conclusión operativa

Desplegar la proyección tal cual. No hay examples que limpiar, no hay FORMATO que ajustar, no hay reglas de playbook que lean campos dropeados. Riesgo de esquema fantasma: **nulo**.
