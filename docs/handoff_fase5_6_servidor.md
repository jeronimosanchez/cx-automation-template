# Handoff — Fase 5 y Fase 6: el servidor Cloud Run

**Para quién es este documento:** una sesión nueva (Opus), sin memoria de las sesiones anteriores, que va a construir `act/server_cloudrun.py` (Fase 5) y `act/validate_server_cloudrun.py` (Fase 6). Tienes libertad total de actuación dentro de esta tarea: construyes, pruebas, iteras y modificas archivos sin pedir permiso. Solo hay dos cosas que te paran en seco, y el ritmo importa más que la velocidad — está todo en el §0, léelo antes que nada.

**Estado (2026-08-10):** las Fases 1 a 4 ya existen y están probadas contra CX real — `act/act_cx_resources_deploy_cloudrun.py` y `act/validate_pipeline_cloudrun.py`. No arrancas de cero: léelos antes de escribir nada.

---

## 0. Libertad de actuación — qué haces sin preguntar, qué te para en seco

Tienes libertad total dentro de esta tarea. **No pidas permiso** para:

- Crear, escribir, reescribir y borrar archivos del repositorio: `act/`, `docs/`, el `Dockerfile`, tests, lo que haga falta.
- Instalar dependencias, ejecutar tests, arrancar el servidor en local, tirarlo y volverlo a arrancar las veces que quieras.
- Crear ramas, commitear y hacer `git push` **a tu rama desechable**.
- Crear, usar y borrar **tu** agente CX desechable y **tus** documentos de Firestore.
- Leer lo que necesites: `gcloud … list/describe`, `GET` a cualquier API, Firestore, GitHub.
- Equivocarte, deshacer y volver a intentarlo. Eso es trabajar, no es un incidente.

Si algo cae dentro de esa lista, hazlo y sigue. Preguntar paso a paso convierte una tarea de una noche en una conversación, y no es lo que se te pide.

**Paras en seco y preguntas solo en dos casos:**

1. **Cambio estructural a `CLAUDE.md`.** Corregir un dato desfasado dentro de una sección que ya existe es parte del trabajo. Añadir, quitar o reescribir secciones, reglas o constraints, no. *Por qué:* ese archivo es el contrato de todas las sesiones, no solo de la tuya — si lo cambias, cambias el comportamiento de trabajos que no has visto y que nadie va a revisar contigo.
2. **Cualquier cosa que toque Petal**, en el sentido amplio del §2. No es solo escribir en el agente: es también desplegar algo en su proyecto, habilitar una API allí, tocar su IAM o fusionar en `main`. Si tienes que preguntarte si algo cuenta como Petal, cuenta. Para y pregunta.

**Y una tercera regla que no es un permiso, es un ritmo: no vayas rápido.** No hay premio por terminar antes. Vale más un trabajo que tarda el doble y llega entero que uno que llega pronto con la mitad de los criterios de la Fase 6 dados por buenos "por inspección del código". Si tienes que elegir entre cerrar la tarea y hacerla bien, haz bien la parte que puedas y deja escrito qué queda pendiente y por qué. Eso es un resultado; un verde apresurado no.

---

## 1. Qué leer, en este orden

1. `CLAUDE.md` — completo.
2. `docs/panels/act_build_playbook_v2_cloudrun.html` — la Fase 5 y la Fase 6 completas (`objetivo`, `reglas`, `leer`, `outputs`, criterios de validación). Es tu especificación real, ya revisada y corregida esta noche.
3. `docs/cloudrun_diseno_servidor.md` — completo. Fuente de verdad de la Fase 5, incluida la infraestructura ya creada (§14).
4. `act/act_cx_resources_deploy_cloudrun.py` — las 9 funciones que el servidor va a exponer (5 pasos + `discover`, `register_agent`, `link_project_repo`, `manage_versions`). Entiende la firma de cada una antes de escribir un endpoint.
5. `act/utils/cx_client_cloudrun.py` — la capa de conexión que ya existe, para no reinventarla.

Si algo de lo que lees contradice lo que te parece mejor, para y pregunta — no lo decidas por tu cuenta.

---

## 2. Regla absoluta — más importante que completar la tarea

**Nunca, bajo ninguna circunstancia, toques el proyecto `floristeria-petal-digital` ni ningún agente real de Petal.**

Lista negra explícita:
- Proyecto: `floristeria-petal-digital` — nunca lo pases como `project` a ninguna función ni llamada HTTP, ni en pruebas ni en ningún otro contexto.
- Agentes: `745375ba-ac7e-4eb8-b8a0-d742891f2aa4` (Petal 1.0) y `cea66b60-192d-4b5a-af10-28f8661032e0` (Petal 1.1).
- Rama `main` del repositorio `jeronimosanchez/cx-automation-template` — nunca la toques directamente.

Antes de cualquier llamada que escriba (POST/PATCH/DELETE, `git push`), confirma que el proyecto y el agente son los que tú mismo creaste para esta tarea — nunca uno preexistente que encuentres por el camino. Si en algún momento algo apunta, aunque sea remotamente, a Petal, para inmediatamente y reporta — no sigas ni intentes arreglarlo.

### 2.1 Este Mac apunta a Petal por defecto — en `gcloud` y en las credenciales

El entorno local no es neutro. Apunta a Petal por dos vías independientes, y ninguna te avisa:

- `gcloud config list` → `project = floristeria-petal-digital`. Es la **única** configuración que existe, y la cuenta es `roles/owner` en ese proyecto.
- El fichero de credenciales de aplicación (`~/.config/gcloud/application_default_credentials.json`) lleva `quota_project_id: floristeria-petal-digital`. De ahí sale el proyecto de los clientes de Python cuando nadie se lo dice.

No hay `.env`, no hay `load_dotenv`, no hay `.claude/settings.json` y no hay ningún flag en el repo que lo corrija. Si no lo corriges tú en cada comando, nadie lo corrige.

**Tres reglas, las tres obligatorias:**

**1. `--project cloud-run-multiproyecto` explícito en TODA orden `gcloud`, sin una sola excepción.** Nunca ejecutes `gcloud config set project`. Antes del primer comando, lanza `gcloud config get-value project` y deja constancia en tu log de que lo comprobaste.

*Por qué:* en `floristeria-petal-digital` ya están habilitadas Cloud Run, Cloud Build, Artifact Registry, IAM y Resource Manager; ya existe el repositorio `cloud-run-source-deploy` en `europe-west1`; y ahí viven `petal-sheet-api` y `petal-sheet-api-v11`, los dos ACTIVOS, que el `CLAUDE.md` §7 punto 5 declara intocables desde este repo. Un `gcloud run deploy --source . --region europe-west1` sin `--project` **no da error**: despliega, y deja un servicio y unas imágenes dentro del proyecto de producción de Petal. El daño es silencioso justamente porque tienes permiso. Lo mismo con `gcloud services enable` sin `--project`: habilita APIs en Petal.

*Y hay un detalle que juega en tu contra:* en `cloud-run-multiproyecto` **Cloud Build no está habilitada**, mientras que en Petal sí. O sea: el camino correcto pide un paso extra y el equivocado funciona a la primera. Si en algún momento te ves eligiendo el camino por donde nada protesta, esa es exactamente la trampa.

**2. `export FIRESTORE_PROJECT=cloud-run-multiproyecto` antes de ejecutar cualquier script**, y la misma variable inyectada como variable de entorno del contenedor.

*Por qué:* `store.get_client()` sin argumento cae en el proyecto por defecto de las credenciales, y hay **13 llamadas así** en el pipeline actual — 4 en `act/act_cx_resources_deploy_cloudrun.py` (líneas 223, 1845, 1941, 2025) y 9 en `act/validate_pipeline_cloudrun.py`. `FIRESTORE_PROJECT` aparece **una sola vez en todo el repositorio**: la propia línea que la lee (`act/utils/firestore_client_cloudrun.py:111`). No está documentada en el diseño §14 ni en el playbook, que solo nombran `PORT` y `ALLOWED_ORIGIN`. Es una variable que existe solo si la pones tú.

**3. Un error que nombre `floristeria-petal-digital` es la señal de parada del §2, no un problema que resolver.** Si ves algo como `403 … has not been used in project floristeria-petal-digital`, la causa es que algo tuyo apunta al proyecto equivocado. Arregla el apuntado. **Nunca** habilites una API, crees una base de datos ni añadas un binding de IAM en ese proyecto para que el error desaparezca — aunque el propio mensaje de Google te ofrezca el enlace para hacerlo, que es literalmente lo que hace.

---

## 3. Infraestructura de pruebas — crea la tuya, no reutilices nada existente

Esta noche se encontraron varios restos de sesiones anteriores (agentes de prueba y un repositorio "desechable" viviendo dentro del proyecto real de Petal, sin limpiar). Para evitar ese mismo problema:

- **Crea un agente CX nuevo, propio de esta tarea**, en el proyecto `cloud-run-multiproyecto` (la API de Dialogflow ya está habilitada ahí). Región sugerida: `europe-west1`. `displayName` con la palabra "desechable" en el nombre.
- **No reutilices ningún agente ni repositorio que encuentres ya registrado** en Firestore o en GitHub, aunque parezca desechable — créalo tú, de cero, para esta tarea concreta.
- Repositorio: usa `jeronimosanchez/cx-automation-template` con una **rama nueva y propia**, nunca `main`. Nombra la rama con un prefijo identificable (`desechable/fase5-<algo>`).

### 3.1 Petal 1.0 está dado de alta ahora mismo como destino desplegable

No es un riesgo teórico: **el pipeline acepta hoy a Petal 1.0 como destino y resuelve entero, sin un solo error.**

En Firestore de `cloud-run-multiproyecto` existe el documento `agentes/floristeria-petal-digital__745375ba-ac7e-4eb8-b8a0-d742891f2aa4`, con `repo: jeronimosanchez/cx-automation-template`, `carpeta_raiz: definitions` y `rama: build/intento-2` — la misma rama en la que trabajas. Y existe `proyectos/floristeria-petal-digital`, que es además **el único proyecto vinculado que hay**. Con eso, `Contexto('floristeria-petal-digital', '745375ba-…')` se construye sin `MappingNotFound` y los cinco pasos funcionan de punta a punta contra el agente de producción.

No hay red debajo: la única guarda que existe en el repo (`exigir_agente_desechable`) vive dentro de `act/validate_pipeline_cloudrun.py`, no en el pipeline ni en el cliente de CX. Ni tu servidor de la Fase 5 ni tu validador de la Fase 6 la heredan por escribirlos.

Y `GET /discover` te va a poner Petal delante: sin proyecto lista todos los proyectos GCP de la cuenta, y con `project=floristeria-petal-digital` devuelve sus agentes marcados `vinculado: true` y `registrado: true`. El endpoint que la Fase 6 te obliga a probar presenta Petal como un destino listo para desplegar.

**Reglas:**

- **No borres ni modifiques ese documento**, ni ningún otro de Firestore que no hayas creado tú. Está ahí a propósito; su limpieza no es tuya y no entra en el §7.
- **No lo uses jamás como destino.** Ni "solo para ver si `discover` funciona", ni copiando un ejemplo, ni como el tercer proyecto del criterio de vinculación.
- **Comprueba el `agent_id` contra un literal tuyo, no contra lo que devuelve `discover`.** Al crear tu agente, anota su `project` y su `agentId` en una constante de tu script, y que toda llamada que escriba compare contra esa constante. Fiarse de "el que salió en el listado" es exactamente cómo se cuela el equivocado.
- **Replica la guarda en tu propio código.** En `server_cloudrun.py` y en `validate_server_cloudrun.py`, rechaza `floristeria-petal-digital` y los dos IDs de Petal antes de emitir ninguna llamada. Una lista negra en código para sola; una instrucción depende de que te acuerdes a las cuatro horas.

*Por qué se subraya, si el §2 ya lo prohíbe:* porque la prohibición ya existía y ya falló dos veces en este mismo repo, de forma documentada. Hay dos agentes de prueba registrados dentro de `floristeria-petal-digital` (`3eef28e8-…` y `8d15e440-…`), con sus documentos de Firestore todavía ahí sin limpiar.

---

## 4. Punto de retorno

El commit `5d122b5` (HEAD de `build/intento-2` en el momento de este encargo) es el punto exacto al que se puede volver si algo sale mal. **No uses `ab99300`:** quedó dos commits atrás, y entre medias están `3651064` y `5d122b5`, que son precisamente este encargo y la corrección del playbook de construcción — un `git reset --hard ab99300` borraría el documento que estás siguiendo. No hace falta nada más elaborado que esto: si el resultado final no es bueno, `git reset`/`git checkout` a `ab99300` deja el repo exactamente como estaba antes de empezar.

Esto cubre el código. La infraestructura en la nube (agente CX, ramas, documentos de Firestore) que tú mismo crees para esta tarea se cubre con la limpieza obligatoria del punto 7 — no con el punto de retorno de git.

---

## 5. Qué construir

**Fase 5 — `act/server_cloudrun.py`:** servidor Flask con 8 endpoints (5 pasos numerados + `discover`, `register_agent`, `link_project_repo`, `manage_versions`), más `act/utils/github_app_client_cloudrun.py` y el `Dockerfile`. Reglas completas en el playbook — auth por ADC hacia CX, GitHub App hacia GitHub, puerto por `PORT` (8080 por defecto), CORS por variable de entorno, candado de Firestore en todos los endpoints que escriben, sobre de respuesta `{status, log, data}` siempre.

**Fase 6 — `act/validate_server_cloudrun.py`:** smoke test del servidor, contra el agente desechable que tú creaste. Las 13 reglas están en el playbook.

**`GITHUB_APP_ID`: `4474347`** (App `act-cloudrun-deploy`, documentado en `docs/cloudrun_diseno_servidor.md` §14).

---

## 6. Pruebas — no solo el camino feliz

Construye y ejecuta **todos** los criterios de validación que la Fase 6 ya especifica, no un subconjunto. En particular, no te quedes solo en que los 8 endpoints respondan bien con datos correctos — prueba también:

- Los casos de error ya definidos: falta `project`/`agent` → 400, JSON mal formado → 400 (nunca 500 crudo), CORS y su preflight `OPTIONS`, permisos IAM insuficientes con error claro.
- Cero residuo bajo fallo: matar el servidor con `SIGKILL` a mitad de una escritura, y una operación que sigue viva tras un timeout del cliente.
- **El candado del Paso 5, a través del servidor HTTP.** Esta noche se arregló para que `step_5_publish` exija un Paso 4 declarado "superados" antes de publicar. Confirma que llamar a `POST /step/5` sin haber pasado por `/step/4` falla igual por HTTP que falla llamando a la función Python directamente — es fácil que un cambio de este tipo se rompa al portarlo a HTTP sin que nadie lo note.
- **La poda de versiones, a través del servidor.** Publicar ya no borra versiones automáticamente (arreglado esta noche) — confirma que sigue siendo así llamando por HTTP, no solo en la función directa.
- El camino feliz completo, incluyendo publicar de verdad contra el agente desechable — pero **solo** contra el agente desechable que tú creaste, nunca contra nada que se parezca a Petal.

### 6.1 Dos criterios de la Fase 6 te piden algo que no puedes hacer por tu cuenta

Arriba dice que ejecutes **todos** los criterios. Dos de ellos chocan con reglas que están por encima de esta tarea. No los ejecutes: prepáralos, para y pregunta.

**1. «Forzar la falta del permiso IAM de Resource Manager».** Forzarlo implica quitar o añadir un binding de IAM, y el `CLAUDE.md` hace de IAM un gate innegociable (§7 punto 1 y la tabla del §8.2), sin excepción por "es una prueba".

Hay además una razón práctica, no solo de reglas. La cuenta de servicio `act-cloudrun-sa@cloud-run-multiproyecto.iam.gserviceaccount.com` **existe pero no tiene ningún rol a nivel de proyecto**: su único permiso es `roles/secretmanager.secretAccessor` sobre el secreto `github-app-private-key`. No tiene `dialogflow.admin` en ningún proyecto, ni acceso a Firestore. Así que en cuanto despliegues el staging "con el Service Account de runtime real", como pide el criterio, te vas a comer 403 en Firestore y en CX.

**Eso no es un bug de tu código: es un permiso que falta y que solo Jero puede conceder.** Cuando lo veas, párate y pídelo — no lo arregles tú con `add-iam-policy-binding`. Si quieres cubrir el manejo del error mientras tanto, simula el caso sin permiso con un doble o un monkeypatch, y deja anotado que el criterio real quedó pendiente del gate.

**2. «Un tercer proyecto GCP desechable sin ningún documento previo en Firestore».** Créalo solo si puedes crear un proyecto nuevo de verdad. **No lo sustituyas por uno que ya exista en la cuenta:** los que hay son `floristeria-petal-digital` (Petal), `fluted-legacy-491416-b8` y `gen-lang-client-0914039209`, y ninguno es desechable. Si no puedes crear uno nuevo, para y pregunta; no improvises un reemplazo.

**Y una regla general que cubre los dos: un criterio de validación no es una autorización.** El playbook describe qué habría que probar; no levanta ninguno de los gates del `CLAUDE.md` ni la regla absoluta del §2 de este documento. Si un criterio solo se puede cumplir cruzando un gate, el criterio se queda pendiente y se dice en el resumen final — no se cumple a la brava.

---

## 7. Limpieza — obligatoria, verificada, no solo intentada

Pase lo que pase (éxito o fallo), al terminar:
1. Borra el agente CX que creaste. Confírmalo con un `GET` posterior → 404.
2. Borra la rama de GitHub que creaste. Confírmalo con `git ls-remote`.
3. Borra los documentos de Firestore que tu tarea creó (mapeo de agente, ejecuciones, versiones en vuelo). Confírmalo leyendo después.

No dejes esto para "si sobra tiempo" — es tan obligatorio como el resto.

---

## 8. El gate humano — no es la autocrítica del modelo

Tienes libertad para construir, probar e iterar hasta que tu propia suite (Fase 6) pase en verde, sin pedir permiso en cada paso intermedio. Pero cuando termines:

- **No avances a la Fase 7** (conectar el panel real) sin que Jero confirme explícitamente que la Fase 5 y 6 están bien. Preséntalo como "construido, autoprobado, listo para revisión" — nunca como "ya validado" o "ya es seguro".
- Motivo concreto, no hipotético: la noche del 2026-08-09 al 10, el pipeline de las Fases 1-4 llegó ya "construido y probado" por una sesión anterior, y una revisión fresca encontró 2 fallos reales de seguridad (un candado que se podía saltar del todo, y una condición de carrera al borrar versiones) que la autocrítica original no había visto. Que tu suite esté en verde es la condición para pedir la revisión, no para saltártela.

---

## 9. Al terminar

Resume: qué construiste, resultado completo de la Fase 6 (no solo "todo pasó" — qué se probó y cómo), y confirmación punto por punto de que la limpieza del punto 7 se verificó completa. Si algo se desvía de este documento, dilo explícitamente en vez de improvisar en silencio.
