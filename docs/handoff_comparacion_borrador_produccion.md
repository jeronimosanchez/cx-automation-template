# Encargo — El Paso 5 decide mirando, no recordando

**Fecha:** 2026-08-10 · **Rama:** `build/intento-2` · **Repo:** `cx-automation-sandbox-intento-1`

Este documento es autosuficiente. Contiene el porqué, el qué, el cómo paso a
paso, y todas las pruebas que hay que pasar para darlo por bueno. No hace falta
leer la conversación que lo originó.

---

## 0 · Guardarraíles — léelos antes de tocar nada

**Petal es un agente conversacional real, en producción. No se toca.**

Dos ids de agente y un proyecto GCP están prohibidos como destino de cualquier
llamada tuya — de lectura y, sobre todo, de escritura:

| Qué | Valor |
|---|---|
| Petal 1.0 | `745375ba-ac7e-4eb8-b8a0-d742891f2aa4` |
| Petal 1.1 | `cea66b60-192d-4b5a-af10-28f8661032e0` |
| Proyecto GCP de Petal | `floristeria-petal-digital` |

Si en algún momento no puedes confirmar **con certeza** que el agente contra el
que vas a escribir es el desechable, **para y pregunta**. No adivines.

El agente desechable de pruebas se llama `desechable-demo-panel`, id
`4718db23-4031-4e70-b899-f3eb693060f0`. Resuelve tú mismo su proyecto y región
—no los des por sabidos— con:

```python
import sys; sys.path.insert(0, ".")
from act.utils import firestore_client_cloudrun as store
for m in store.list_agent_mappings(store.get_client()):
    print(m)
```

**Otros límites, no negociables:**

- Nada de IAM, GitHub Secrets ni configuración de GCP.
- No hagas `git push` a `main` ni a ningún repositorio público.
- El validador `act/validate_pipeline_cloudrun.py` ya se niega a arrancar si el
  agente no lleva `desechable` en el nombre o si la rama principal del proyecto
  es `main`/`master`/`produccion`/`production`. **No desactives esas guardas.**
- Cero residuo: todo lo que crees para probar lo barres al terminar, y
  confirmas el borrado **leyendo el resultado**, nunca fiándote del código de
  respuesta HTTP.

**Libertad de acción:** dentro de esos límites, trabaja sin pedir permiso paso a
paso. Si te encuentras con algo que exige una decisión de arquitectura no
cubierta aquí, o que obligaría a cambiar `CLAUDE.md`, para y pregunta.

---

## 1 · Qué es este sistema, en 10 líneas

`cx-automation-sandbox-intento-1` despliega definiciones YAML de un repositorio
Git a un agente conversacional de **Google Dialogflow CX**. El motor es
`act/act_cx_resources_deploy_cloudrun.py`, servido por
`act/server_cloudrun.py` (Cloud Run) y operado desde un panel HTML.

El pipeline tiene 5 pasos:

| Paso | Qué hace | Escribe en |
|---|---|---|
| 1 | Inventario: lee CX y el repositorio y los empareja | nada (solo lectura) |
| 2 | Trae al repositorio lo que solo existe en CX | el repositorio |
| 3 | Aplica al **borrador** de CX lo marcado en el repositorio | el borrador de CX |
| 4 | Registra que los tests se declararon `superados` o `fallidos` | Firestore |
| 5 | Crea versiones y apunta el entorno `production` a ellas | CX (producción) |

---

## 2 · Los tres conceptos de CX que hay que tener claros

Verificado contra la documentación oficial y contra la API real. **No es
opinión, y el cambio entero descansa sobre esto.**

**Borrador (draft).** El estado editable del agente. Hay **uno solo**: el que
edita el pipeline y el que edita una persona desde la consola de CX son el
mismo. Cambia al instante con cada escritura. No lleva número ni se congela
solo.

**Versión.** Una foto **inmutable** de **un contenedor** — un flow, un playbook
o un tool. Nunca del agente entero: *"an immutable snapshot of your flow,
playbook or tool data"*. **Editar el borrador NO crea una versión**: hay que
pedirla explícitamente (`POST .../versions`). Una vez creada, su contenido no
cambia jamás.

**Entorno.** Una lista de punteros, uno por contenedor: *"A list of
configurations for flow versions"*. `production` no es una foto del agente —
es, por ejemplo, `playbook A → su versión 4`, `playbook B → su versión 2`,
`flow F → su versión 7`. Cada puntero se mueve por separado.

**Consecuencia:** publicar un cambio = crear la versión de ese contenedor +
mover su puntero. Los demás contenedores se quedan exactamente donde estaban.

### 2.1 · Dos comparaciones distintas — no las mezcles

El pipeline compara en dos sitios, y **miran hacia lados distintos**:

| Dónde | Compara | Responde |
|---|---|---|
| Pasos 2 y 3 | **repositorio ↔ borrador de CX** | ¿el repo y el borrador dicen lo mismo? |
| Paso 5 | **borrador de CX ↔ lo que produce sirve** | ¿el borrador y producción dicen lo mismo? |

El borrador es el punto común, pero cada comparación mira a un lado.

**Este encargo solo añade la segunda.** La primera —`calcular_diff`, que es lo
que alimenta los Pasos 2 y 3— **no se toca**: sigue comparando repositorio
contra borrador exactamente igual que hoy, sin enterarse de producción. Llevar
la comparación nueva al Paso 3 sería un error: ahí producción no pinta nada.

---

## 3 · Por qué hacemos este cambio — el problema real

### Cómo decide hoy el Paso 5 qué versionar

No mira el borrador. Lee una lista de Firestore:

- Al escribir en el borrador, `step_3_apply_to_cx` llama a
  `store.record_resource_write(..., pendiente_publicar=True)`.
- `step_5_publish` ([línea 1478](../act/act_cx_resources_deploy_cloudrun.py#L1478))
  llama a `store.list_pending_publication(...)` y versiona solo lo que salga ahí.
- Al terminar, `store.mark_published(...)` quita la marca.

Es decir: **el sistema decide recordando lo que él mismo hizo.**

### El fallo

El dueño del sistema va a trabajar **directamente en la consola de CX**, no
solo a través del pipeline. Ese es su flujo de trabajo real, no un caso raro.

Cuando edita un playbook en la consola:

1. El cambio entra en el borrador. Correcto, visible.
2. Nadie apunta nada en Firestore — el Paso 3 no ha intervenido.
3. Corre el Paso 4 y declara `superados`.
4. Corre el Paso 5. **La lista está vacía. No crea ninguna versión.**
5. El paso reporta éxito. El cambio se queda en el borrador para siempre.

**Falla en silencio y diciendo que fue bien.** Ese es el defecto a corregir.

### El mismo defecto, con un borrado

Si borra un recurso en la consola: producción sigue sirviendo la versión
antigua, que todavía lo contiene. Nada lo detecta ni lo avisa.

### La corrección

**Que el Paso 5 decida mirando, no recordando:** comparar el contenido de cada
contenedor en el borrador contra el de la versión que producción sirve.
Da igual quién hizo el cambio — el borrador es el mismo.

**Y sigue versionando solo lo que difiere**, nunca el agente entero. Esto no es
un detalle: los límites de versiones vivas de CX son reales (20 por flow, 100
por playbook, 50 por tool — el de playbook confirmado reventando en 100 con
`FAILED_PRECONDITION`), y versionar todo publicaría además trabajo a medias de
contenedores que nadie quería publicar.

---

## 4 · Lo verificado contra la API — evidencia, para que no lo redescubras

Todo esto se comprobó el 2026-08-10 contra el agente desechable y la
documentación oficial. **Está confirmado; no lo vuelvas a investigar.**

### 4.1 · Una versión de flow NO guarda contenido

`LIST .../flows/{id}/versions` devolvió exactamente:

```
['createTime', 'displayName', 'name', 'nluSettings', 'state']
```

Sin contenido. **No se puede comparar un flow leyendo su versión.**

### 4.2 · Pero CX tiene un endpoint hecho justo para esto: `compareVersions`

`POST {version_name}:compareVersions` con cuerpo
`{"targetVersion": "{flow_name}/versions/0"}` — donde **`0` significa "el
borrador"**.

Llamada real ejecutada, `status 200`, respuesta:

```
['baseVersionContentJson', 'compareTime', 'targetVersionContentJson']
```

Y el hallazgo que simplifica todo: **cuando nada ha cambiado, los dos JSON son
idénticos byte a byte** (`a == b` → `True`). Los genera CX con el mismo
serializador en ambos lados, así que **no hace falta normalizar nada** para
comparar flows.

El contenido devuelto trae las claves `['flow', 'intents']` — es decir, **un
cambio en un intent hace que su flow salga como cambiado**. Los intents no
necesitan tratamiento aparte.

> `compareVersions` es técnicamente un `POST`, pero no muta nada: solo compara.
> Está autorizado para este trabajo.

### 4.3 · Playbooks y tools SÍ guardan su contenido dentro de la versión

Según la documentación:

- `PlaybookVersion` → campos `playbook` (*"Snapshot of the playbook when the
  playbook version is created"*) y `examples[]` (*"Snapshot of the examples
  belonging to the playbook..."*).
- `ToolVersion` → campo `tool` (*"Snapshot of the tool..."*).

**Lo que falta comprobar (hazlo tú, primera tarea):** si el `LIST` de versiones
devuelve ese contenido en línea o si hay que pedir cada versión con un `GET`.
Cambia el coste (0 ó 1 llamada por contenedor publicado), **no la estructura del
cambio**. En el agente desechable no había ninguna versión de playbook al
escribir esto: tendrás que crear una para comprobarlo (permitido, es el agente
desechable — bórrala después).

### 4.4 · Claves distintas por contenedor en el LIST de versiones

Ya está resuelto en el código y documentado en `RESOURCE_TYPES["version"]`:
`flow → "versions"`, `playbook → "playbookVersions"`, `tool → "toolVersions"`.

### 4.5 · Un entorno exige la cadena completa de flows

Documentación del campo `versionConfigs`: *"You should include version configs
for all flows that are reachable from [Start Flow] in the agent. Otherwise, an
error will be returned."*

**Consecuencia:** un playbook o un tool sí se pueden sacar del entorno; **un
flow alcanzable desde el inicio, no** — CX rechazará el `PATCH`. Hay que
manejarlo con un mensaje claro, no dejar que reviente con un error críptico.

### 4.6 · Tipos que CX no versiona nunca

`TIPOS_SIN_VERSION = ("agent_config", "generator")`. Los cambios en ellos los
ven los usuarios en cuanto se aplican, sin pasar por ningún gate. **Es el
comportamiento actual y no cambia con este encargo** — pero la función de
comparación nunca debe incluirlos.

---

## 5 · El cambio, paso por paso

### 5.0 · La regla que no se puede romper: mínimo consumo de versiones

**Una versión nueva solo se crea para un contenedor cuyo contenido difiere de
lo que producción sirve. Para todo lo demás, el entorno conserva el puntero que
ya tenía, sin tocarlo y sin crear nada.**

Esto no es una optimización: es la razón por la que el sistema sigue siendo
usable. Los límites de versiones vivas de CX son reales y se agotan —
**20 por flow, 100 por playbook, 50 por tool**, y el de playbook está
confirmado reventando exactamente en 100 con `FAILED_PRECONDITION`. Un diseño
que versionara el agente entero en cada publicación quemaría un hueco en cada
contenedor cada vez, y además publicaría trabajo a medias de contenedores que
nadie quería publicar.

Las tres consecuencias, en concreto:

1. **Publicar sin cambios no crea ninguna versión.** Cero. El entorno se queda
   exactamente como estaba (check **3.31**).
2. **Cambiar 1 de 10 playbooks crea 1 versión, no 10.** Los otros 9 punteros ni
   se tocan (check **3.32**).
3. **Una versión sobrante de un intento fallido se reutiliza** si su contenido
   coincide con el borrador actual, en vez de crear otra (ver 5.3).

El cambio de este encargo **no relaja esta regla: la refuerza**. Hoy la lista de
Firestore puede marcar como pendiente algo que en realidad ya coincide con
producción — y se le crea versión igual, gastando un hueco para nada. Comparando
contenido, eso deja de pasar: si no difiere, no se versiona, aunque alguien lo
hubiera marcado.

El check **4.4 del Nivel 4** lo verifica contando: **ninguna versión creada
puede corresponder a un contenedor que no cambió.**

> **Nota de lectura:** en este documento `4.3`, `4.5`… con este formato son
> **secciones**; `check 4.4`, `check 3.31`… son **pruebas**. Cuando haya riesgo
> de confusión se dice cuál es.

### 5.1 · Función nueva: la comparación

Es el corazón del cambio y **no existe nada parecido hoy**.

Firma sugerida (ajústala si encuentras algo mejor, justificándolo en el
docstring):

```python
def _contenedores_cambiados(contexto, inventario):
    """Qué contenedores difieren de lo que producción sirve ahora mismo."""
```

Devuelve, como mínimo:

- **`cambiados`** — contenedores del borrador cuyo contenido difiere de su
  versión publicada, **o que no tienen ninguna versión todavía** (necesitan la
  primera). Es lo que el Paso 5 tiene que versionar.
- **`borrados`** — contenedores fijados en el entorno que ya no están en el
  borrador. Producción los sirve y no existen.
- **`iguales`** — para poder afirmar en las pruebas que no se versiona de más.

Cómo compara, por tipo:

| Tipo | Método | Coste |
|---|---|---|
| `flow` | `compareVersions` contra `versions/0`; iguales ⇔ los dos JSON son idénticos | 1 llamada por flow publicado |
| `playbook` | contenido del borrador (playbook + sus examples) vs. el congelado en la versión | 0 ó 1 (según 4.3) |
| `tool` | igual que playbook | 0 ó 1 (según 4.3) |

**Para playbooks y tools, reutiliza lo que ya existe** en vez de escribir una
comparación nueva: `huella_resource`
([línea 629](../act/act_cx_resources_deploy_cloudrun.py#L629)) ya calcula un
hash del contenido excluyendo los campos que la API gestiona por su cuenta
(`CAMPOS_LEIDOS_NO_ENVIADOS`), y `payloads.differs` ya compara dos objetos con
ese mismo criterio. Si comparas en crudo, campos como `createTime` harán que
todo parezca cambiado siempre.

**Cuidado con los examples:** un playbook y sus examples son un solo contenedor
a efectos de versión. Si cambia un example, el playbook está cambiado. La
comparación tiene que incluirlos. Y esto vale también para el **borrado de un
hijo**: si se borra un example, su playbook ha cambiado.

**⚠ Compara contra la versión que el entorno FIJA, nunca contra la última
versión creada.** No son lo mismo. Se puede crear una versión y no llegar a
publicarla — el Paso 5 muere a mitad, o alguien la crea a mano en la consola.
En ese momento existe una versión más nueva que la que producción sirve. Si la
comparación coge "la última", concluirá que no hay nada que hacer y **el cambio
nunca llegará a producción**, reproduciendo el mismo fallo silencioso que este
encargo viene a corregir. La referencia correcta es siempre el `versionConfigs`
del entorno.

**Un contenedor que existe, tiene versiones, pero no está fijado en el entorno
cuenta como cambiado** — hay que publicarlo. No tener puntero no es lo mismo
que estar al día.

**El coste tiene que estar acotado por el número de contenedores publicados, no
por el tamaño del agente.** Es un criterio de aceptación, no una preferencia.

### 5.2 · `step_5_publish` cambia su fuente de decisión

En [línea 1478](../act/act_cx_resources_deploy_cloudrun.py#L1478), donde hoy
hace `store.list_pending_publication(...)`, pasa a llamar a la función nueva.

**Todo lo demás del paso se queda igual:** el candado (`agent_lock`), el gate
del Paso 4 (`declarado != "superados"` → abortar), el gate de huella del
borrador, el merge de la rama, `_crear_versiones`, `_apuntar_entorno`,
`save_previous_versions`, `save_inflight_versions`.

### 5.3 · Adaptar las funciones que hoy reciben `pendientes`

Cambia su firma para recibir la lista ya calculada de contenedores. **El cuerpo
no cambia.**

- `_crear_versiones` ([línea 1724](../act/act_cx_resources_deploy_cloudrun.py#L1724))
- `_versiones_reutilizables` ([línea 1649](../act/act_cx_resources_deploy_cloudrun.py#L1649))
- La llamada a `_contenedores_sobre_limite` al final del Paso 5

**`_versiones_reutilizables` mejora con el cambio.** Hoy decide si una versión
sobrante de un intento anterior sigue valiendo comparando marcas de tiempo
contra los pendientes. Con la comparación de contenido, la respuesta es directa:
**una versión sobrante vale si su contenido coincide con el borrador actual.**
Simplifícala en esa dirección.

### 5.4 · Sacar del entorno lo borrado

Hoy `_combinar_versiones`
([línea 1814](../act/act_cx_resources_deploy_cloudrun.py#L1814)) fusiona lo
anterior con lo nuevo mediante un diccionario por padre: **solo puede añadir o
mantener, nunca quitar.** Por eso un puntero a algo borrado sobrevive a
cualquier número de publicaciones.

Hay que poder restar: la lista final del entorno debe excluir los punteros de
los contenedores detectados como borrados.

**Con la excepción de 4.5:** si el borrado es un flow alcanzable desde el flow
de inicio, CX rechazará el `PATCH`. Detéctalo y explícalo con un mensaje que se
entienda, en vez de propagar el error de la API.

### 5.5 · El Paso 1 informa

`step_1_inventory` añade a su respuesta el resumen de la comparación: qué va a
cambiar y qué está borrado. Es solo lectura, como todo el Paso 1.

### 5.6 · El panel avisa antes de publicar un borrado

Cuando la comparación detecta contenedores borrados, el panel muestra un
**popup** (no un espacio fijo — esto va a pasar poco) con **una fila por cada
uno**, porque puede haber varios y la decisión es individual.

El popup **informa, no bloquea**: si continúas al Paso 5, eso desaparece de
producción, y eso puede ser exactamente lo que quieres.

Estilo: reutiliza los tokens y componentes que ya existen en el panel
(`.btn-primary`, `.btn-danger`, `.btn-ghost`, el patrón de tarjeta con borde
ámbar de los avisos). Texto de cada fila: qué tipo es, cómo se llama, y que
producción lo sirve pero el borrador ya no lo tiene.

**⚠ Hay DOS paneles y los dos hay que tocarlos:**

| Archivo | Qué es |
|---|---|
| `docs/panels/act_cx_resources_deploy_v2.html` | **La especificación.** Es la constante `PANEL` del validador, y varios checks del Nivel 0 contrastan el código contra ella |
| `docs/panels/act_cx_resources_deploy_v2_output_cloudrun.html` | El panel real que sirve Cloud Run |

**Esto puede romper un check que ya existe.** El Nivel 0 tiene
`el_panel_ensena_lo_que_el_paso_1_averigua`: cada dato nuevo que el Paso 1
devuelve **tiene que llegar a la pantalla con un `id` identificable**, no con un
texto suelto. El precedente es `aviso-sin-entorno`. Dale al popup un `id`
propio en la misma línea, y **añade su comprobación a ese check** (o uno
hermano) — si no, el dato existe y nadie lo ve, que es justo lo que ese check
está para impedir.

### 5.7 · El servidor no necesita endpoint nuevo

`act/server_cloudrun.py` devuelve el `data` de cada paso tal cual, así que el
campo nuevo del Paso 1 viaja solo. **Confírmalo, no lo des por hecho** — y si
hubiera algún filtrado de campos por el camino, ajústalo.

### 5.8 · Tres detalles que se olvidan y dejan el sistema mintiendo

**El texto del log del Paso 5.** Hoy dice
`"· 2/3 Versionando · N resources tocados desde la última publicación"`. Con el
cambio ya no hay "resources tocados": hay contenedores que difieren. **Si no se
actualiza, el paso informa de algo que ya no es cierto.**

**Firestore no necesita migración.** Los documentos existentes con
`pendiente_publicar: True` quedan inertes: nadie los lee. No hay que limpiarlos
ni escribir ningún script de migración. Dilo en el informe para que quede
constancia de que fue una decisión y no un olvido.

**La documentación.** `CLAUDE.md` §4 (mapa de dependencias) dice que tocar
`act/` obliga a actualizar `act/tests/` y el README. Además, el documento vivo
de diseño del servidor (`docs/cloudrun_diseno_servidor.md`) describe el
comportamiento del Paso 5: si se queda describiendo el mecanismo de
`pendientes`, pasa a ser documentación falsa. **Actualízalo.**

### 5.9 · Lo que desaparece

- `store.list_pending_publication`
- `store.mark_published`
- El campo `pendiente_publicar` en `record_resource_write`
- `_padres_versionables` ([línea 1768](../act/act_cx_resources_deploy_cloudrun.py#L1768)) entera

### 5.10 · Lo que NO desaparece — dos trampas

**1. `huella_cx` y `record_resource_write` se quedan.** Están en el mismo
documento de Firestore que `pendiente_publicar`, pero sirven para otra cosa
completamente distinta: son el tercer punto de referencia que permite a
`_marcar_conflicto` ([línea 668](../act/act_cx_resources_deploy_cloudrun.py#L668))
avisar de que un recurso cambió **en el repositorio y en CX a la vez**. Esa
protección importa **más** después de este cambio, no menos, porque el dueño va
a editar en la consola a propósito. **Borrarla sería una regresión grave.**

**2. El parámetro `only_pending` de `step_3_apply_to_cx`
([línea 1261](../act/act_cx_resources_deploy_cloudrun.py#L1261)) no tiene nada
que ver con esto.** Se llama parecido, pero es el filtro de "reintentar solo lo
que falló", lo manda el panel en la petición, y no lee Firestore. **No lo
toques.**

---

## 6 · Las validaciones

Van en `act/validate_pipeline_cloudrun.py`, con el patrón `runner.check(nivel,
"nombre", funcion)` que ya usa el archivo. Cada check devuelve `(ok, detalle)` o
un booleano.

Los niveles ya existen y significan esto:

| Nivel | Qué es |
|---|---|
| 0 | Estático y **ficticio**: sin red, sin credenciales |
| 1 | Solo lectura contra CX real (desechable) |
| 2 | Dry-run |
| 3 | Escritura real contra el agente desechable |
| 4 | Fallo inyectado y concurrencia |

### 6.1 · Nivel 0 — el agente ficticio

**Aquí está el grueso de la cobertura, y no toca la red.** Construye un
inventario ficticio en memoria, con la forma exacta que devuelve
`inventariar_cx` (diccionario `{tipo: {cx_id: item}}`), y pásaselo a la función
de comparación.

**Fabrica este agente ficticio** — cubre los seis casos de una vez:

| Contenedor | Situación | Resultado esperado |
|---|---|---|
| playbook `A` | contenido idéntico a su versión publicada | **igual** — no se versiona |
| playbook `B` | contenido distinto | **cambiado** |
| playbook `C` | en el borrador, sin ninguna versión | **cambiado** (primera versión) |
| flow `F` | contenido distinto | **cambiado** |
| tool `T` | contenido idéntico | **igual** |
| playbook `D` | fijado en el entorno, **ausente del borrador** | **borrado** |

El entorno `production` ficticio apunta a versiones de `A`, `B`, `F`, `T` y `D`.

Para el flow `F`, `compareVersions` es una llamada de red: **sustitúyela por un
doble** en el Nivel 0 (el archivo ya tiene el patrón en `ContadorHttp`, que
reemplaza `cx.api_request` temporalmente).

**Checks del Nivel 0:**

| # | Qué comprueba |
|---|---|
| 0.1 | El agente ficticio completo produce exactamente el reparto de la tabla |
| 0.2 | Contenido idéntico → no aparece como cambiado |
| 0.3 | Contenido distinto → aparece como cambiado |
| 0.4 | Contenedor sin ninguna versión → aparece como cambiado |
| 0.5 | Fijado en el entorno y ausente del borrador → aparece como borrado |
| 0.6 | Entorno vacío (agente nunca publicado) → **todos** los contenedores salen como cambiados, ninguno como borrado |
| 0.7 | Agente sin entorno `production` → no revienta; devuelve algo coherente |
| 0.8 | Un cambio **solo** en `createTime` u otro campo de `CAMPOS_LEIDOS_NO_ENVIADOS` **no** cuenta como cambio |
| 0.9 | Cambiar un **example** hace que su playbook salga como cambiado |
| 0.10 | `generator` y `agent_config` no aparecen nunca en la lista de cambiados |
| 0.11 | Determinismo: dos llamadas con el mismo inventario dan el mismo resultado, con el mismo orden |
| **0.12** | **Se compara contra la versión FIJADA, no contra la última creada.** Contenedor con versión `v3` fijada en el entorno y una `v4` creada pero sin publicar, y borrador distinto de `v3` → **cambiado**. Si el código coge `v4`, este check lo caza |
| 0.13 | Contenedor con versiones pero **sin puntero en el entorno** → **cambiado** (hay que publicarlo) |
| 0.14 | **Borrar un hijo** (un example) hace que su playbook salga como cambiado |
| 0.15 | Borrador degenerado (sin ningún contenedor) → no revienta |
| 0.16 | **Estático:** `list_pending_publication`, `mark_published` y `pendiente_publicar` ya no aparecen en el pipeline |
| 0.17 | **Estático:** `_padres_versionables` ya no existe ni se llama |
| 0.18 | **Anti-regresión estático:** `record_resource_write`, `huella_cx` y `_marcar_conflicto` **siguen** existiendo y llamándose |
| 0.19 | **Anti-regresión estático:** el parámetro `only_pending` de `step_3_apply_to_cx` sigue intacto |
| 0.20 | **Panel ↔ Paso 1:** el campo nuevo del Paso 1 llega a la pantalla con un `id` identificable, en el panel de especificación **y** en el de Cloud Run — siguiendo el precedente `aviso-sin-entorno` |
| 0.21 | El check existente `el_panel_ensena_lo_que_el_paso_1_averigua` **sigue pasando** tras añadir el campo |
| 0.22 | El texto del log del Paso 5 ya no habla de "resources tocados" (5.8) |
| 0.23 | Ningún literal de Petal en el código nuevo (`LITERALES_PROHIBIDOS`, ya existe) |

### 6.2 · Nivel 1 — solo lectura contra el desechable

| # | Qué comprueba |
|---|---|
| 1.1 | La comparación corre contra el agente real y **no escribe nada**: instrumentada con `ContadorHttp`, las únicas escrituras admitidas son `compareVersions` |
| 1.2 | El número de llamadas está acotado por los contenedores **publicados**, no por el tamaño del agente |
| 1.3 | `compareVersions` con `targetVersion=.../versions/0` devuelve 200 y las tres claves esperadas |
| 1.4 | Con el borrador sin tocar desde la última versión, los dos JSON son **idénticos** |
| 1.5 | `step_1_inventory` devuelve el resumen nuevo con las claves esperadas |
| 1.6 | El resumen del Paso 1 y lo que el Paso 5 usaría coinciden (no hay dos criterios distintos) |
| 1.7 | **El servidor pasa el campo nuevo:** la respuesta HTTP de `/step/1` lo incluye, no se pierde por el camino (5.7) |

### 6.3 · Nivel 2 — dry-run

| # | Qué comprueba |
|---|---|
| 2.1 | `step_3_apply_to_cx(dry_run=True)` sigue sin escribir (no regresión) |
| 2.2 | Si añades un dry-run al Paso 5, lista qué versionaría sin crear nada |

### 6.4 · Nivel 3 — escritura real contra el desechable

Es el nivel más largo, y va en cuatro bloques: los recorridos completos, las
cabeceras, la matriz por tipo y origen, y los casos límite.

#### Cómo se demuestra que "producción sirve exactamente esto"

No basta con que el Paso 5 diga que publicó. **Hay que leerlo de CX.** Dos
formas, según el tipo, y las dos son exactas:

- **Flow:** `compareVersions(version_recién_creada, .../versions/0)` — si
  producción sirve lo mismo que el borrador, los dos JSON son **idénticos**.
- **Playbook y tool:** la versión guarda el contenido dentro (`playbook` +
  `examples`, `tool`) — se lee y se compara contra el borrador.

**Ninguna prueba de este nivel puede darse por buena leyendo el código de
respuesta HTTP ni el log del paso. Siempre releyendo el efecto en CX.**

#### 6.4.1 · Recorridos completos, de punta a punta

| # | Recorrido |
|---|---|
| **3.1** | **GitHub → draft → producción.** Commitear un playbook nuevo en la rama del agente → Paso 3 → confirmar que **está en el borrador de CX** → Paso 4 `superados` → Paso 5 → confirmar que **la versión creada contiene exactamente lo que se subió** y que el entorno la apunta |
| **3.2** | **CX → producción.** Editar un playbook **directamente en la consola de CX** (sin tocar el repositorio ni el Paso 3) → Paso 4 `superados` → Paso 5 → confirmar que se publicó y que producción sirve esa edición. **Hoy esto falla en silencio: es la prueba que justifica el encargo** |
| **3.3** | **CX → GitHub → CX.** Crear un recurso en la consola de CX → Paso 2 lo trae al repositorio → confirmar la cabecera → Paso 3 lo vuelve a aplicar → **no genera ninguna operación** (ya coincide). El viaje de ida y vuelta no cambia nada |
| **3.4** | **Los dos orígenes en la misma publicación.** Un playbook cambiado desde GitHub y otro distinto cambiado en la consola → un solo Paso 5 → **los dos** llegan a producción |
| **3.5** | **No regresión del ciclo normal:** Paso 3 → 4 → 5 publica lo mismo que publicaba antes del cambio |

#### 6.4.2 · Cabeceras (`metadata`) — en los dos sentidos

La cabecera de cada YAML es `metadata: {tipo, padre, cx_id, agente}`. Es lo que
sostiene el emparejamiento; si se rompe, el pipeline crea duplicados o escribe
sobre el recurso equivocado.

| # | Qué comprueba |
|---|---|
| 3.6 | **CX → GitHub:** el Paso 2 escribe la cabecera **completa y correcta** — `tipo`, `cx_id` real asignado por CX, `agente`, y `padre` cuando el recurso cuelga de otro |
| 3.7 | **GitHub → CX:** la cabecera **nunca viaja a CX**. Instrumentado: ningún cuerpo enviado contiene `metadata` (ya hay test unitario, aquí se comprueba contra la API real) |
| 3.8 | **`cx_id` decide la operación:** con `cx_id` → `PATCH`; sin `cx_id` → `POST`. Nunca al revés |
| 3.9 | **Escritura de vuelta:** tras un `POST`, el `cx_id` que CX asignó se escribe en el YAML y se commitea (`_guardar_cx_id`). Confirmado leyendo el archivo en la rama, no el log |
| 3.10 | **`cx_id` fantasma:** un YAML cuyo `cx_id` ya no existe en CX se trata como creación nueva (`POST`), y el `cx_id` nuevo sustituye al viejo en el archivo |
| 3.11 | **`agente` filtra:** un YAML con el `agente` de otro agente **no** se despliega en este. Un YAML **sin** `agente` no se despliega en ninguno |
| 3.12 | **`padre` se respeta:** un example se aplica bajo su playbook, una page bajo su flow. Nunca colgando del agente |
| 3.13 | **Aviso de cambio de archivo:** el mismo `cx_id` en un archivo distinto al de la última vez dispara el aviso (`avisar_cambio_de_archivo`) |
| 3.14 | **Idempotencia de cabeceras:** Paso 2 seguido de Paso 2 no cambia ningún archivo; Paso 3 seguido de Paso 3 no escribe nada |

#### 6.4.3 · Matriz — por tipo de recurso y por origen del cambio

Cada celda: hacer el cambio, correr hasta el Paso 5, y confirmar en CX el
resultado esperado. **La columna que más importa es qué se versiona**, porque
es donde se juega el límite de cuota.

| # | Tipo | Origen | Operación | Qué tiene que pasar |
|---|---|---|---|---|
| 3.15 | playbook | GitHub | crear | Versión **del playbook**. Producción lo sirve |
| 3.16 | playbook | CX | modificar | Versión **del playbook**. Producción sirve la edición |
| 3.17 | playbook | GitHub | borrar | Sale del entorno. **Ninguna versión nueva suya** |
| 3.18 | playbook | CX | borrar | Detectado como borrado. Sale del entorno |
| 3.19 | example | GitHub | crear/modificar | Versión **de su playbook** — el example no tiene versión propia |
| 3.20 | example | CX | modificar | Versión **de su playbook** |
| 3.21 | flow | GitHub | modificar | Versión **del flow**, detectada vía `compareVersions` |
| 3.22 | page | GitHub | crear/modificar | Versión **de su flow** — la page no tiene versión propia |
| 3.23 | intent | CX | modificar | Versión **del flow que lo contiene**. Verificado: el contenido del flow incluye `intents` |
| 3.24 | intent | GitHub | modificar | Igual que 3.23 |
| 3.25 | entity_type / webhook | cualquiera | modificar | Versión del flow que los contiene |
| 3.26 | tool | GitHub | modificar | Versión **del tool** |
| 3.27 | transition_route_group | GitHub | modificar | Versión de su flow |
| 3.28 | generator | GitHub | modificar | **Ninguna versión** (`TIPOS_SIN_VERSION`). Aviso de que los usuarios lo ven al aplicarlo |
| 3.29 | agent_config | GitHub | modificar | **Ninguna versión**. Mismo aviso |
| 3.30 | playbook | **GitHub y CX a la vez** | modificar | **Conflicto marcado** por `_marcar_conflicto`, no se pisa en silencio |

#### 6.4.4 · Casos límite y gates

| # | Qué comprueba |
|---|---|
| 3.31 | **Publicar sin ningún cambio:** cero versiones creadas, entorno idéntico |
| 3.32 | **Uno de tres:** con tres playbooks y uno modificado, se crea versión de **ese y solo ese**; los otros dos punteros intactos |
| 3.33 | **Agente nunca publicado** (entorno vacío): la primera publicación crea versión de todos los contenedores del borrador y ninguno sale como borrado |
| 3.34 | **Borrar un flow alcanzable desde el inicio:** CX lo rechaza; el paso lo explica con un mensaje que se entiende, no propaga el error de la API |
| 3.35 | **Borrar y recrear** el mismo recurso: `cx_id` nuevo, cabecera actualizada, una sola copia en CX |
| 3.36 | El gate del Paso 4 sigue abortando si lo declarado no fue `superados` |
| 3.37 | El gate de huella sigue abortando si el borrador se movió tras declarar |
| 3.38 | El Paso 3 sigue sin mover el puntero de ningún entorno |
| 3.39 | Idempotencia del Paso 5: correr dos veces no duplica versiones ni punteros |
| 3.40 | Tras cada bloque, el entorno de producción es **legible y coherente**: todos sus punteros resuelven a versiones que existen |
| 3.41 | **Versión creada y no publicada:** crear una versión a mano, cambiar el borrador y publicar → el cambio llega. Es el caso 0.12 contra CX real |
| 3.42 | **Rollback:** `save_previous_versions` guardó los punteros de antes, y con ellos se puede devolver el entorno a su estado anterior |
| 3.43 | **Aviso de límite:** `_contenedores_sobre_limite` sigue avisando de los contenedores que superan su cuota, y **sigue sin borrar nada** por su cuenta |
| 3.44 | **`manage_versions` no se rompe:** listar y borrar versiones sigue funcionando, y sigue negándose a borrar una que un entorno fija |
| 3.45 | **Orden estable:** tras restar un puntero, el resto de `versionConfigs` conserva su orden — dos publicaciones seguidas sin cambios no reordenan nada |
| 3.46 | **Paso 3 y Paso 5 concurrentes:** el candado los serializa; el Paso 5 no publica un borrador a medio escribir |

### 6.5 · Nivel 4 — fallo inyectado y concurrencia

| # | Qué comprueba |
|---|---|
| 4.1 | Si `compareVersions` falla para un flow, el Paso 5 **para y lo dice** — nunca publica a ciegas asumiendo "sin cambios" |
| 4.2 | Si el Paso 5 muere entre crear versiones y apuntar el entorno, el reintento **reutiliza** las versiones creadas en vez de duplicarlas |
| 4.3 | Dos Paso 5 concurrentes: el candado los serializa, ninguno corrompe el entorno |
| 4.4 | Cuota: contando las versiones creadas, ninguna corresponde a un contenedor que no cambió |
| 4.5 | Cero residuo tras toda la tanda, confirmado leyendo CX |

### 6.6 · No regresión general

| # | Qué comprueba |
|---|---|
| R.1 | `python -m pytest act/tests/ -q` pasa entero |
| R.2 | `act/validate_pipeline_cloudrun.py --levels 0-4` pasa entero, incluidos los checks que ya existían |
| R.3 | `act/validate_html_dom_cloudrun.js` sigue pasando tras tocar los paneles |
| R.4 | `docs/cloudrun_diseno_servidor.md` ya no describe el mecanismo de `pendientes` — describe el real (5.8) |
| R.5 | El README y `act/tests/` reflejan el cambio, según el mapa de dependencias de `CLAUDE.md` §4 |

---

## 7 · Criterios de aceptación

Se da por bueno cuando **todos** se cumplen:

1. **Los dos recorridos completos funcionan y coinciden** — checks **3.1** y
   **3.2**: un cambio subido desde GitHub y un cambio hecho en la consola de CX
   llegan **los dos** a producción, y lo que producción sirve se ha confirmado
   **releyéndolo de CX**, no por el log del paso.
2. **Las cabeceras siguen funcionando en los dos sentidos** — checks **3.6 a
   3.14**: el pull las escribe completas, el push nunca las manda a CX, y el
   `cx_id` vuelve al archivo tras cada creación.
3. **La regla de 5.0 se cumple** — checks **3.31, 3.32 y 4.4**: publicar sin
   cambios crea **cero** versiones, cambiar uno de varios crea **una**, y
   ninguna versión creada corresponde a un contenedor que no cambió.
4. **Se compara contra la versión fijada, no contra la última creada** — checks
   **0.12 y 3.41**. Es el error que reproduciría el fallo original.
5. **Los borrados se detectan y salen del entorno** — checks **3.17, 3.18 y
   3.34**, incluido el caso en que CX no deja quitarlo.
6. **La matriz por tipo pasa entera** — checks **3.15 a 3.30**: cada tipo se
   versiona donde le toca, y los que CX no versiona no generan versión.
7. **El aviso llega a la pantalla** — checks **0.20, 0.21 y 1.7**: en los dos
   paneles, con `id` propio, y el servidor lo transporta.
8. Los checks **0.18 y 0.19** pasan — no se borró de más.
9. `pytest`, el validador completo y el DOM pasan enteros; la documentación
   quedó al día (**R.1 a R.5**).
10. El agente desechable queda **sin residuo**, confirmado por lectura.
11. Ninguna llamada de la sesión tuvo como destino Petal.

---

## 8 · Fuera de alcance — no lo construyas

- **El "Caso B"**: una versión publicada que por dentro referencia un recurso
  borrado (un intent, un webhook). Se verificó que CX **bloquea** borrar algo
  que el borrador todavía referencia, y **también bloquea** escribir una
  referencia a algo inexistente — así que solo puede ocurrir por un camino muy
  estrecho. Se aborda aparte, si acaso.
- **"Retirar de producción" como acción con botón propio.** Ya no hace falta:
  el Paso 5 normal saca del entorno lo que no está en el borrador.
- **Cloud Audit Logs**, cualquier cambio de IAM, cualquier infraestructura nueva.
- **Tocar Petal**, en cualquier forma.

---

## 9 · Orden sugerido

1. Comprobar lo que queda abierto en la **sección 4.3** (¿el LIST de versiones
   de playbook trae el contenido?) — una llamada, y condiciona el coste.
2. La función de comparación + todos los checks del Nivel 0. **No toca nada en
   marcha**: se puede construir y probar entera antes de enchufarla. Presta
   atención especial al check **0.12** (versión fijada vs. última creada).
3. Enchufarla al Paso 5 (5.2, 5.3) + Niveles 1 y 3, empezando por los
   recorridos completos (**3.1** y **3.2**).
4. Restar del entorno lo borrado (5.4) + checks **3.17, 3.18 y 3.34**.
5. El resumen del Paso 1 (5.5), los dos paneles (5.6) y el servidor (5.7) +
   checks **0.20, 0.21 y 1.7**.
6. Los detalles de 5.8 (log, migración, documentación) + checks **0.22, R.4,
   R.5**.
7. Nivel 4 y la no regresión general.

---

## 10 · Cómo reportar

Al terminar, un informe con:

- Qué pasó y qué falló, con el resultado real de cada nivel — **sin adornar**.
  Un check que no llegaste a ejecutar se declara como tal; no se omite.
- El resultado de la comprobación 4.3, con la evidencia.
- Cualquier decisión de diseño que tomaras y que no estuviera en este documento,
  con su porqué.
- Confirmación de limpieza del agente desechable, leída de CX.
- Confirmación de que ninguna llamada fue a Petal.
- Lo que te sorprendió o no encajaba con este documento.

**No declares "validado" por tu cuenta.** Reporta los resultados; la
aprobación final es humana.
