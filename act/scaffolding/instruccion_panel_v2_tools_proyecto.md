# Instrucción para la instancia del panel — Tools y alta de agente

**Archivo a modificar:** `docs/panels/act_cx_resources_deploy_v2.html`
**Contexto:** el repositorio pasó a ser del proyecto GCP, no del agente (S24). Varios
agentes hermanos comparten repositorio; cada uno tiene su propia rama de trabajo.

**Las Tools pasan de dos a una.** «Desplegar un resource suelto» se elimina; «Vincular
agente y repositorio» pasa a ser «Vincular proyecto y repositorio». Y una tercera que
este modelo habría hecho necesaria —registrar agente— no se crea: es un botón dentro
del Paso 1. Cuatro bloques de cambio.

---

## A · Paso 1 — el bloque de alta de agente (lo nuevo)

Hoy la caja del destino tiene dos estados: repositorio resuelto, o aviso de que el
proyecto no tiene repositorio. **Hace falta un tercer estado**, entre medias:

> el proyecto sí tiene repositorio, pero el agente elegido todavía no tiene rama de trabajo.

### Qué se ve

Con un agente en ese estado, la caja del destino muestra:

- El repositorio del proyecto, resuelto y no editable, igual que siempre.
- Donde iría la rama: **«Este agente todavía no tiene rama de trabajo.»**
- El nombre que el servidor propone, tal cual, visible antes de que exista:
  `agente/petal_voz` (viene del servidor en `rama_propuesta`, no lo calcula el panel).
- Un botón **«Dar de alta este agente»**.
- El botón **Iniciar inventario** sigue apagado mientras el agente no tenga rama.

### Qué pasa al pulsarlo

Un registro en vivo corto, del mismo estilo que los de los pasos, con dos líneas:
la región del agente y la rama creada. Al terminar, la caja pasa al estado normal
—repositorio y rama resueltos— e **Iniciar inventario** se enciende. No navega a
ningún sitio: se queda en el Paso 1.

Mientras corre, bloquea el panel como cualquier otra acción que escribe.

### Por qué es un botón y no automático

Es una escritura: crea una rama real en GitHub, visible para todo el equipo y
permanente. El desplegable lista **todos** los agentes del proyecto en todas las
regiones, incluidos los que nadie piensa gestionar. Si el alta ocurriera al pulsar
Iniciar inventario, pinchar la fila de al lado dejaría una rama que nadie pidió y que
hay que borrar a mano sabiendo que existe.

Y la spec 1.2 dice que el agente se elige en el Paso 1 *"porque es la única pantalla
que no escribe nada: equivocarse aquí no cuesta"*. Esa frase es el motivo de que la
elección esté ahí. Con el botón sigue siendo verdad: **el Paso 1 no escribe; escribe
el botón.**

### Specs que hay que tocar por esto

**1.4 — Qué escribe y dónde.** Añadir al final del párrafo actual, sin quitar nada:

> El alta de un agente —crear su rama de trabajo la primera vez que se elige— sí
> escribe, y por eso no es parte de este paso: es un botón aparte, con su propia
> confirmación, y hasta pulsarlo el Paso 1 sigue sin dejar rastro.

**M.1 — Resolución del repositorio.** El último párrafo hoy describe dos casos ("el
proyecto no tiene repositorio, o este agente no tiene rama propia") con un solo botón
que "remite a otra pantalla". Ahora son dos botones distintos y solo uno remite:

> La caja muestra el repositorio del proyecto y la rama del agente elegido. Si al
> proyecto le falta el repositorio, avisa con un botón que no vincula nada aquí, solo
> remite a la herramienta. Si el repositorio está pero el agente no tiene rama, el aviso
> es otro: enseña el nombre de rama que se le crearía y un botón que sí actúa, aquí
> mismo, y solo al pulsarlo.

**Criterios de evaluación del Paso 1** — añadir dos:

> 12. Un agente sin rama de trabajo no bloquea el paso en silencio: se dice que le falta,
> se enseña el nombre que se le propone antes de crearlo, y hasta pulsar el botón no
> existe ninguna rama nueva. Cambiar de agente sin pulsarlo no deja nada.
> 13. Los dos avisos de la caja del destino no se confunden: al proyecto le falta el
> repositorio (remite a la herramienta) o al agente le falta la rama (se resuelve aquí).

---

## B · «Desplegar un resource suelto» — se elimina entera

**Decisión de Jero (2026-08-08).** No se renombra ni se arregla: se quita.

*Por qué:* daba más problemas que soluciones. Escribía en CX saltándose el diff, y para
usarla con seguridad habría hecho falta añadirle un selector de agente propio,
impedirle crear, y una confirmación en dos tiempos que enseñara el nombre del resource
—porque un `cx_id` son 36 caracteres que nadie puede revisar de un vistazo—. Tres
parches para una pantalla que se usa poco. El camino que la sustituye ya existe y es
mejor: aplicar el cambio en CX a mano y después recorrer el pipeline, que deja
repositorio y agente cuadrados.

### Qué hay que borrar del HTML

1. La tarjeta del sidebar «Desplegar un resource suelto» (~línea 218). El bloque Tools
   queda con **una sola** tarjeta.
2. La vista entera `<div class="step-view" id="view-tool-deploy-resource">` (~665-712):
   formulario, desplegable de tipos, registro y pantalla de fin.
3. En el JS: `TOOL_LOG_LINES`, `ejecutarToolDeployResource()`, y la rama
   `name === 'deploy-resource'` de `viewTool()` — que se queda sin alternativa, así que
   `viewTool` ya no necesita elegir prefijo.
4. En las Specs: el bloque **T.1 completo** (T.1.1 a T.1.6). La antigua T.2 pasa a ser
   **T.1** y sus sub-bloques se renumeran (T.2.1 → T.1.1, y así).
5. Cualquier mención a **S20** en el panel: la decisión desaparece con la herramienta.

No queda nada del lado del servidor a lo que llamar: `deploy_single_resource` ya está
borrada del pipeline, y con ella sus cinco checks de validación. Un desplegable de
tipos escrito a mano en el HTML era además una lista que podía separarse de la del
servidor sin que nada avisara; al desaparecer, esa deriva deja de ser posible.

---

## C · La Tool que queda — «Vincular proyecto y repositorio»

Se renombra y se simplifica. Deja de pedir agente y deja de traer nada.

### Cambios de interfaz

| Dónde | Antes | Ahora |
|---|---|---|
| Tarjeta del sidebar (~línea 225) | Vincular agente y repositorio | **Vincular proyecto y repositorio** |
| Descripción de la tarjeta | Onboarding de un proyecto nuevo · S22 | Una vez por proyecto · S22/S24 |
| Título de la pantalla | Vincular agente y repositorio | **Vincular proyecto y repositorio** |
| Campo 1 del formulario | ID del agente CX | **Proyecto GCP** |
| Campo 2 | URL del repositorio | igual |
| Registro en vivo | 4 líneas, con detección de región y pull inicial | 3 líneas: acceso al repositorio · repositorio registrado · `cx-deploy.yaml` creado |
| Pantalla de fin | banner con el comando IAM | la lista de puesta en marcha del bloque D |

La frase de cabecera de la pantalla, que hoy dice que el servidor "crea la estructura
del repositorio... y trae lo que ya exista en CX", pasa a:

> Solo hace falta una vez por proyecto. El repositorio lo creas tú; aquí se le dice al
> sistema cuál es. Los agentes de ese proyecto se dan de alta después, uno a uno, desde
> el Paso 1.

### Lo que hay que hacer a mano antes de abrir esta pantalla

Son dos cosas, y ninguna es de GitHub Apps:

1. Crear el proyecto GCP.
2. Crear el repositorio en GitHub, con su rama principal.

**El acceso del servidor a GitHub ya está resuelto y no se repite:** la GitHub App
`act-cloudrun-deploy` (§14 del diseño) está instalada en *todos* los repositorios de la
cuenta, actuales y futuros. Un repositorio nuevo es accesible sin configurar nada.
No pedir en el panel ningún paso de instalación de la App.

Si algún día el acceso falla, el primer paso —leer la rama principal— es el que lo
detecta, y lo hace antes de escribir nada.

### Specs de esta Tool (la antigua T.2, ahora T.1)

- **T.1.1** — «Formulario de una sola pantalla: proyecto GCP y URL del repositorio. Al
  pulsar Vincular, el servidor comprueba que llega al repositorio, registra el vínculo y
  deja un marcador `cx-deploy.yaml` en la rama principal.»
- **T.1.2** — hoy dice «un agente recién creado no tiene ningún repositorio asociado».
  Es falso: lo hereda del proyecto. Lo que no tiene es rama. Reescribir: «Sin él, el
  proyecto no tiene repositorio y ninguno de sus agentes tiene con qué compararse. Se
  hace una vez; los agentes que lleguen después heredan el repositorio y solo necesitan
  su rama.»
- **T.1.3** — quitar el pull inicial y el mapeo agente→repo. Produce: el vínculo
  proyecto→repositorio, el marcador, y el comando IAM.
- **T.1.4** — «En el repositorio (`cx-deploy.yaml` en la rama principal, solo la primera
  vez) y en el registro del proyecto. Nunca concede IAM por su cuenta (S6b).» Añadir:
  «El permiso IAM es de proyecto, no de agente: se concede una vez aquí y cubre a todos
  los agentes que vivan dentro, también a los que se creen después.»
- **T.1.5 — Región detectada automáticamente** → se queda, pero cambia de sitio y de
  motivo. Ya no la detecta esta herramienta: la detecta el alta del agente, y
  normalmente sin barrer nada, porque el desplegable del Paso 1 ya trae la región de
  cada agente —listarlos obliga a recorrer las regiones de todos modos—. Reescribir:
  «La región no se pide nunca a mano. Viene con el listado de agentes, se comprueba con
  una sola petición al dar de alta, y solo si esa comprobación falla se recorren las
  regiones que declara la API.»
- **T.1.6 — El pull inicial no usa plantillas** → **eliminar el bloque entero.** No hay
  pull inicial: traer lo que ya existe en CX es el Paso 2 del pipeline normal, la primera
  vez que se trabaja con ese agente. Tener dos caminos para lo mismo era el problema.
- **T.1.7** (la antigua T.2.7, bloqueo del panel) — se queda igual.

### Bloque nuevo, T.1.8 — El alta de agente no vive aquí

> Vincular es del proyecto y ocurre una vez. Dar de alta un agente es de cada agente y
> ocurre la primera vez que se elige, desde el Paso 1, con su botón. Están separados
> porque tienen ritmos distintos: un proyecto se vincula una vez y no se vuelve a tocar;
> los agentes se van sumando con el tiempo, y obligar a volver a una herramienta de
> onboarding cada vez que aparece uno nuevo sería pedir que se rehaga algo que ya está
> hecho.

---

## D · La lista de puesta en marcha, visible en el panel

Jero no sabía que hubiera nada más que vincular. La secuencia completa existe pero solo
vive en un documento de diseño, así que hay que enseñarla **donde se necesita**, y
diciendo siempre qué se copia y dónde se pega.

**Dónde va:** en la pantalla de resultado de la Tool, sustituyendo al banner de IAM que
hay hoy. En vez de un solo aviso, una lista de lo que queda, con el comando dentro:

> **Proyecto vinculado ✓ — queda esto:**
>
> **1 · Pega este comando en tu terminal** *(una vez por proyecto; cubre todos sus
> agentes, también los que crees después)*
> `[el comando completo]` `[Copiar]`
>
> **2 · Crea el agente en Dialogflow CX** — el panel despliega, no crea infraestructura.
>
> **3 · Crea su entorno de producción en Dialogflow CX** — sin él, el Paso 5 no tiene
> dónde publicar.
>
> **4 · Vuelve al Paso 1, elige el agente y pulsa «Dar de alta»** — le crea su rama.
>
> Los pasos 2, 3 y 4 se repiten por cada agente nuevo. El 1 no: es del proyecto.

Reglas para esa lista:
- El comando se enseña **completo y copiable**, con el proyecto real y la cuenta de
  servicio real dentro. Nunca `$VARIABLE`: pegado en una terminal donde esa variable no
  existe, `--member=` queda vacío y gcloud falla con un error que no menciona el alta.
- Cada punto dice **dónde** ocurre (terminal · consola de CX · panel), porque son tres
  sitios distintos y ninguno es obvio.
- Nada de esa lista lo ejecuta el panel. Es una lista de lo que queda por hacer, no una
  secuencia de botones.

---

## E · Contrato con el servidor (para que el panel no invente nada)

Tres funciones. Los nombres de campo son los que devuelve el servidor tal cual.

**`discover(project)`** → por cada agente:
`agentId` · `displayName` · `region` · `repo` (del proyecto) · `rama` (null si no está
dado de alta) · `vinculado` (el proyecto tiene repositorio) · `registrado` (el agente
tiene rama) · `rama_propuesta` (el nombre a enseñar; null si ya está registrado).

El tercer estado de la caja del destino es exactamente `vinculado && !registrado`.

**`register_agent(project, agent_id)`** — lo que dispara el botón del Paso 1 →
`region` · `repo` · `rama` · `rama_creada` (false si la rama ya existía).

**`link_project_repo(project, repo_url)`** — lo que dispara la Tool →
`repo` · `rama_principal` · `commit` · `ya_estaba` · `comando_iam`.

---

## Lo que NO cambia

- Los 5 pasos numerados y sus gates.
- El Paso 2 sigue siendo el único sitio donde se trae de CX al repositorio.
- El Paso 3 sigue siendo el único que escribe resources en CX — y ahora, el único.
- La cuarta tarjeta «Sin agente asignado» del Paso 1, recién añadida.
- La promesa de que el Paso 1 no escribe: sigue siendo literal.
