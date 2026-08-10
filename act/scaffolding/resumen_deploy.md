# Resumen deploy — qué llega a draft y a producción

Medido contra el agente desechable (`floristeria-petal-digital` /
`8d15e440-ab8f-4072-b144-d44919296cd9`), con control y cero rastro verificado
por lectura (no asumido) en cada prueba. 2026-08-09.

**Modelo de fondo:** solo tres tipos son contenedores con su propia pila de
versiones — `flow`, `playbook`, `tool`. Todo lo demás, o viaja dentro de la
versión de su contenedor (`page` en su flow, `example` en su playbook), o no
tiene contenedor y por tanto no se congela nunca (`generator`,
`agent_config`), o debería viajar dentro de un contenedor pero el pipeline hoy
no sabe encontrar cuál (`intent`, `entity_type`, `webhook`).

Un `environment` no es un contenedor: es una **lista de punteros**, uno por
cada contenedor, a la versión que sirve. Publicar = crear una versión nueva de
cada contenedor tocado + mover sus punteros en el entorno.

---

## Recursos LLM (playbooks) — CERRADO, medido de punta a punta

| Recurso | Draft | Producción | Cero rastro |
|---|---|---|---|
| playbook | ✅ recibe el cambio | ✅ solo tras publicar | ✅ |
| example | ✅ recibe el cambio | ✅ solo tras publicar (dentro del playbook) | ✅ |
| tool | ✅ recibe el cambio | ✅ solo tras publicar — antes de publicar seguía en la URL vieja | ✅ |
| generator | ✅ recibe el cambio | ✅ al instante, sin publicar | ✅ |
| agent_config | ✅ recibe el cambio | ✅ al instante, sin publicar | ✅ |

**Arreglado hoy:** `playbook` y `tool` tenían sus versiones invisibles para el
pipeline — CX las devuelve con clave `playbookVersions` / `toolVersions`, no
`versions`, y el pipeline solo pedía `versions`. Se acumulaban sin que nadie
las viera hasta el límite de CX. Corregido: cada contenedor declara su propia
clave, y el inventario ya no confunde una versión de playbook con una de flow
que comparta número (CX numera dentro de cada contenedor, no globalmente).

**Límites verificados contra CX** (`FAILED_PRECONDITION` real al tocar el
tope): playbook = 100 versiones. Documentados por Google
(`docs.cloud.google.com/dialogflow/quotas`, actualizado 2026-07-29, coincide
con lo medido): playbooks por agente = 50 · tools por agente = 100. **Sin
documentar:** versiones por tool.

---

## Recursos NLU (flujos) — problema real, diseño decidido, sin construir

| Recurso | ¿Llega al borrador? | ¿Llega a producción al publicar? | Medido |
|---|---|---|---|
| flow | Sí | Sí — el pipeline crea su versión | leído del código, no medido |
| page | Sí | Sí — versiona su flow | leído del código, no medido — **sin pages reales para probarlo** |
| transition_route_group | Sí | Sí — versiona su flow | ✅ medido con control |
| intent | Sí | **No — no versiona nada.** Se queda atascado en el borrador para siempre | ✅ medido con control |
| entity_type | Sí | **No — no versiona nada.** Igual | ✅ medido con control |
| webhook | Sí | **No — no versiona nada.** Igual | ✅ medido con control |

**Límites documentados** (`docs.cloud.google.com/dialogflow/quotas`):
versiones por flow = **20** (Petal está en 9/20 en su flow por defecto) ·
intents por agente = 10.000 · entity types = 250 · webhooks = 100 · flows =
50 · pages por flow = 250 · route groups por flow = 100 · environments = 20.

### Causa raíz

`intent`, `entity_type` y `webhook` no tienen un único contenedor dueño —a
diferencia de `page` (siempre de un flow) o `example` (siempre de un
playbook)—. Un mismo intent puede estar referenciado desde las rutas de
varios flows a la vez. Hoy su cabecera declara `padre: null`, así que al
publicar el pipeline no sabe qué contenedor versionar y no versiona ninguno.
**No es una limitación de CX** — medido que CX sí los congela dentro de la
versión del flow que los usa — es que el pipeline nunca calculó esa relación.

Confirmado que en un sistema mixto esto no cambia: un playbook no tiene
ningún campo estructurado que referencie un intent (solo
`referencedPlaybooks` y `referencedTools`), así que el intent sigue viviendo
enteramente del lado flow aunque el agente arranque por un playbook.

### Diseño de la solución (no implementado)

Al publicar, con el inventario completo ya en memoria (todos los flows y
pages, ya se leen hoy), construir un mapa de referencias sin llamar a CX de
más:

- recorrer `transitionRoutes` y `eventHandlers` de cada flow y cada page
- `intent_cx_id → {flows que lo usan}`, buscando su cx_id en esas rutas
- `webhook_cx_id → {flows que lo usan}`, buscando en `triggerFulfillment.webhook`
- `entity_cx_id → {flows}`, vía los intents que lo usan en `parameters[].entityType` (dos saltos)

En `_padres_versionables`, para estos tres tipos, sustituir la lectura de
`padre` (que es `null`) por una consulta a este mapa: versionar todos los
flows que aparezcan. Si el mapa no encuentra ninguno, no fallar en silencio:
avisar explícitamente que ese recurso no está usado en ningún flow y publicar
no lo llevará a ningún sitio.

### Lo que falta antes de construir esto

- **Verificar con pages reales.** Ni el agente desechable ni Petal tienen
  ninguna hoy — hay que crear una de prueba y confirmar que su estructura de
  rutas (`transitionRoutes`) es igual que la de un flow.
- **Decidir el Paso 2** (traer al repositorio): si al bajar un intent nuevo se
  calcula y se guarda `padre` en el YAML, o se calcula siempre en caliente sin
  guardarlo nunca (para no arriesgarse a que quede desactualizado si el
  intent se usa en un flow nuevo después).

### Decisión de alcance (2026-08-09)

Se cierra primero el lado LLM entero — pipeline + servidor Cloud Run — antes
de construir esto. No hace falta rehacer nada para añadirlo después: el
pipeline ya recorre una tabla única de 13 tipos de recursos sin distinguir
LLM de NLU, así que este arreglo se añade como una pieza más cuando toque
NLU, sin tocar playbook/example/tool/generator/agent_config.
