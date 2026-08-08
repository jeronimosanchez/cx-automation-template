# Diseño del servidor Cloud Run — decisiones cerradas

**Qué es:** el diseño del servicio que sustituye a `act/server.py` y pasa el pipeline ACT de correr en el Mac de Jero a correr en Cloud Run, con soporte multi-repo y multi-agente.

**Estado:** §3 y §4 están al día con el pipeline de **cinco pasos**. Las decisiones de §2, §10 y §11 se tomaron cuando eran ocho y hay que leerlas con esa reserva. Sigue abierto lo de §8: el diseño no cubre el modelo de confianza entre panel y servidor.

**Fecha:** 2026-08-03 · **Rama:** `build/intento-2`

**Infraestructura ya creada (Fase A):** ver §14 — proyecto GCP, cuenta de servicio, Secret Manager, GitHub App. (Antes vivía en `docs/cloudrun_handoff_opus.md`, eliminado el 2026-08-05 por duplicar contenido de este documento sin mantenerse sincronizado — causó 3 contradicciones de IAM en un solo día.) El `docs/plan_cloudrun_multiproyecto.md` que ese archivo citaba no está en esta rama — vive en `feature/cloudrun-multiproyecto`.

---

## 1. Cómo se llegó a este diseño

Seis rondas de revisión adversarial sobre la propuesta inicial de la Fase 5. Cada ronda: Jero propone, Opus busca lo que rompe, Jero decide.

| Ronda | Propuesta | Hallazgos |
|---|---|---|
| 1 | Fase 5 como `cloudrun_server.py` | 12: 3 bloqueantes, 2 contradicciones, 4 gaps, 3 criterios no verificables |
| 2 | Respuestas a los 12 | 9 firmadas · 3 con problema · 2 simplificaciones nuevas |
| 3 | Respuestas a los 7 | 6 firmadas · 1 tumbada con evidencia del código |
| 4 | 7 decisiones + onboarding | 6 firmadas · 2 matices · 1 dependencia oculta (el `pull`) |
| 5 | 12 decisiones | El diff propone borrar el agente entero con repo vacío · `traible: False` cableado |
| 6 | 17 decisiones | Cerrado, tras recuperar el candado del inventario |

---

## 2. Decisiones cerradas

### Dónde corre y quién entra

**Un solo servicio de Cloud Run sirve el panel y los endpoints desde la misma URL**, con IAP directo delante.

*Por qué:* mismo origen elimina el problema de CORS de raíz — un panel abierto con `file://` manda `Origin: null` y no puede autenticarse contra Google. Y con `--no-allow-unauthenticated` un navegador normal tampoco entra, porque no manda token: IAP hace el login en el navegador y pasa la identidad al servicio. Sin IAP las únicas salidas serían dejar público un servicio que escribe en CX, o que el panel no pueda llegar.

**Timeout del servicio a 60 minutos** (el máximo).

*Por qué:* el timeout por defecto son 5 minutos y esperar a que el agente termine una operación larga puede llevar otros tantos. El paso que publica moriría justo en el límite.

**Lock explícito con 409, mantenido en el código.**

*Por qué:* una instancia con concurrencia 1 **encola**, no rechaza. Sin el lock, un segundo deploy no rebota: espera y luego se ejecuta con un diff calculado antes de que aterrizara el primero, sin que nadie se entere.

### Identidad

**ADC en los dos lados, sin bifurcación local/cloud** — `google.auth.default()` más la cabecera `x-goog-user-project`. En Cloud Run por la cuenta de servicio; en el Mac por `gcloud auth application-default login`.

*Por qué:* el caso local existe —el estándar de la Fase 1 exige que el pipeline funcione por CLI sin servidor, y los cuatro `validate_*.py` corren en el Mac contra la API real— pero ADC funciona en los dos sitios, así que no hace falta bifurcar.

**CLAUDE.md §3 se reescribe *después* de medirlo**, no antes. Ver §7.

### De dónde salen los datos

**Las definiciones se leen de GitHub** con el token de la GitHub App, siempre desde la rama de trabajo. La lectura entra en todas las carpetas: si se quedara en el primer nivel dejaría fuera lo anidado.

*Por qué:* hoy el pipeline lee del árbol de git en el disco, y en el contenedor no hay ni repositorio ni git.

**El flujo de escritura es unidireccional: Jero empuja desde local, el servidor lee.** Dos excepciones, las dos en el mismo sentido: el panel escribe el ID del agente en `agent.yaml` al vincular un repo, y escribe los artefactos que se traen con el `pull`.

*Por qué importa decirlo:* esas escrituras dejan el local de Jero un commit por detrás sin avisar. **El panel debe decirlo al terminar cada una**: "Guardado. Haz `git pull` antes de seguir trabajando en local." Sin ese mensaje, el conflicto llega semanas después sin origen aparente.

### Qué se elige y cómo

~~**Dos selectores: repo de GitHub y agente CX**, preseleccionados por
`localStorage`... El emparejamiento repo↔agente lo vigila la Regla 11...~~
— **Sustituido por S4 (§10, hallazgo de la ronda adversarial, corregido
2026-08-05).** El documento nunca marcó esto como sustituido, aunque S4 es
posterior — quien leyera §2 primero construiría un selector y una
validación (Regla 11) que ya no hacen falta.

**Lo que aplica de verdad, hoy:** dos desplegables — **proyecto GCP y
agente CX** (confirmado contra §3, endpoint "Descubrimiento": *"rellenar
los desplegables de proyecto y de agente"*). El **repo** no se elige —
se asigna solo desde el mapeo Firestore (S4) en cuanto se elige el
agente. No hay Regla 11 ni comparación contra `agent.yaml`: ese archivo
y ese mecanismo pertenecían al modelo viejo.

*Por qué proyecto y agente, y no solo agente:* un agente vive dentro de
un proyecto GCP concreto: hace falta saber en cuál para construir la URL
de la API de CX (C3). El repo es el único que se infiere, porque es lo
único que depende de una tabla propia (Firestore) en vez de la propia
identidad del recurso en CX.

### El estado entre pasos

**Capa 1, visibilidad.** `localStorage` preselecciona el último repo + agente, y los selectores están siempre visibles para que Jero verifique antes de arrancar. Sigue vigente, sin cambios.

**Capa 2, candado — eliminada (decisión 2026-08-05).** Existía para proteger contra que el Paso 3 aplicara un diff calculado con una foto vieja del inventario (guardada en `localStorage`), si esa foto ya no coincidía con los selectores actuales. Se elimina porque deja de tener sentido: con el modelo de 5 pasos, **el Paso 2 y el Paso 3 recalculan siempre en fresco** — vuelven a mirar el estado real de CX y del repo en el momento de actuar, usando el `project`/`agent` de los selectores actuales, en vez de fiarse de una foto guardada por el Paso 1. Sin foto guardada, no hay foto que pueda estar desincronizada.

*Coste de recalcular en fresco:* con Petal (12 tipos de recurso, 60 archivos) son ~73 llamadas por paso (12 `LIST` a CX + 1 listado de árbol + 60 lecturas de archivo a GitHub). Con candado, esas 73 se hacían una vez; sin candado, se repiten en cada paso que actúa (~219 en total para un deploy completo). Estimado, no medido: tiempo añadido del orden de unos segundos por paso (no medido con precisión); coste monetario insignificante en Cloud Run (fracción de céntimo) y muy por debajo del límite de la API de GitHub (5.000 peticiones/hora) salvo en repos mucho más grandes con deploys muy frecuentes en la misma hora — a medir en Fase B si el repo de algún proyecto crece mucho.

*Riesgo que sí se acepta al quitar el candado (extiende S1b):* como cada paso recalcula en el momento de actuar, no hay garantía de que lo que Jero aprobó viendo el Paso 1 sea exactamente lo que se aplica en el Paso 3, si algo cambió en CX entre medias. Aceptado por el mismo motivo que S1b: el diff nunca propone `DELETE`, y solo trabaja Jero (sin deploys en paralelo, por el lock de concurrencia de S13b — un mecanismo distinto de este candado).

*Por qué el inventario ya no necesita vivir en el navegador:* al no guardarse una foto para comparar más tarde, el problema que resolvía guardarlo en `localStorage` (Cloud Run es stateless, `docs/data/...json` no sobrevive entre peticiones) deja de aplicar — cada paso pide lo que necesita en el momento, no depende de lo que generó un paso anterior.

### El diff nunca borra

**El diff solo propone crear y modificar.** Los resources que existen en el agente y no en el repositorio se tratan aparte:

En el **Paso 2**, no en el del diff: se traen al repositorio los que se marquen, y los que no se marcan se quedan como están. La otra salida es eliminarlos del agente, que se decide ahí y se aplica en el Paso 3 junto con el resto de escrituras.

*Por qué:* hoy el diff hace *"POST lo que falta, PATCH lo que cambió, DELETE lo que sobra"*, así que un recurso creado directamente en CX se borraría en el siguiente deploy sin que nadie lo pidiera. Y con un repo recién creado —vacío— el diff proponía borrar el agente entero, que es justo la primera pantalla que vería alguien estrenando un proyecto.

**El Paso 3 muestra siempre el contador "N recursos en CX sin respaldo en el repo"**, aunque estén ignorados.

*Por qué:* ignorar no es lo mismo que no ver. Sin contador el repo deriva del agente sin que nada lo recuerde, y al tercer mes no hay forma de saber cuánto del agente describe el repo.

**Se mantiene el filtro de `toolType == "BUILTIN_TOOL"`.**

*Por qué:* ya no hace falta para evitar DELETEs, pero sin él las herramientas nativas de la plataforma —`code-interpreter` y compañía— aparecerían en la lista de "solo en CX" en cada deploy para siempre, y no se pueden traer al repo.

**Borrar pasa a ser una operación en dos sitios.** Si el recurso tiene copia en el repo: quitar el YAML **y** confirmar "Eliminar de CX". Si solo existe en CX: eliminarlo desde el botón del diff.

*Por qué documentarlo:* es un cambio de modelo mental. Hasta ahora bastaba con quitar el YAML. La primera vez que borres un playbook y siga vivo en CX parecerá un fallo.

### El `pull` CX → repo

**Se levanta el `traible: False` cableado y pasa a ser alcance real**: lista de artefactos con casillas, Jero elige cuáles traer, el panel los escribe en GitHub por la GitHub App.

*Por qué deja de ser deuda del intento 1:* con repos nuevos vacíos, el `pull` es el primer paso real. Sin él el onboarding no funciona.

### Lo que desaparece

Firestore entero · el registro manual de proyectos · cualquier paso de IAM · la variable `ALLOWED_ORIGIN` · `act/server.py`.

*Por qué el IAM desaparece:* todos los agentes CX viven en el mismo proyecto GCP, así que la cuenta de servicio tiene acceso permanente y no hay que conceder nada al añadir un proyecto. Esto evita chocar con CLAUDE.md §7.1, que prohíbe tocar IAM sin aprobación explícita.

---

## 3. Lo que el servidor tiene que ofrecer

El pipeline pasó de ocho pasos a cinco. Esta es la superficie del servidor
contra los cinco actuales.

| Paso del panel | Qué le pide al servidor | Qué escribe |
|---|---|---|
| **1 · Inventario** | Averiguar qué repositorio corresponde al agente elegido, leer el agente entero, leer el repositorio entero y emparejar cada resource con su archivo | Nada |
| **2 · Traer al repositorio** | Escribir en el repositorio los resources que solo están en el agente | Archivos y un commit en la rama de trabajo |
| **3 · Aplicar en CX** | Crear, modificar y eliminar en el **borrador** del agente lo que se haya marcado | El borrador del agente |
| **4 · Validar tests** | **Nada.** El panel no lanza las pruebas ni conoce su resultado: solo registra lo que declara quien lo usa | Nada |
| **5 · Publicar** | Fusionar la rama de trabajo en la principal, crear la versión y apuntar producción a ella | La rama principal del repositorio y el entorno de producción |

Además, tres cosas que no pertenecen a ningún paso:

| | Para qué | Qué escribe |
|---|---|---|
| **Descubrimiento** | Rellenar los desplegables de proyecto y de agente | Nada |
| **Vincular agente y repositorio** | Guardar a qué repositorio pertenece un agente | El mapeo, y el identificador del agente en su archivo del repositorio |
| **Versiones existentes** | Listar las que guarda el agente y borrar las que se marquen | Borra versiones del agente |

### Lo que desaparece respecto al diseño anterior

**El paso que publicaba en un entorno intermedio** y **el que lo validaba**.
Ya no hay entorno intermedio: se prueba contra el borrador.

**La rotación automática de versiones.** Se creaba una en cada despliegue y
por eso hacía falta un pool que rotara solo. Ahora se crea una por
publicación —muchas menos— y se borran a mano desde el panel.

**Todo lo que fijaba o revertía ese entorno intermedio.**

### Lo que aparece y no estaba previsto

**Escribir en el repositorio** (Paso 2). El diseño anterior daba por hecho
que el servidor solo leía del repositorio.

**Listar y borrar versiones.** El panel lo ofrece y no había endpoint que lo
cubriera.

**Publicar hace tres cosas de una vez.** Antes eran pasos separados con su
propio gate cada uno; ahora van juntas y en orden dentro del último.

---

## 4. Onboarding de un proyecto nuevo

~~Las instrucciones viven en el Paso 1 del panel... tabla de 11 pasos,
Jero crea el repositorio, la carpeta, `agent.yaml` y la rama a mano antes
de tocar el panel...~~ — **Sustituido por S22/S23 (§11, hallazgo de la
ronda adversarial, corregido 2026-08-05).** Ese wizard es posterior a esta
tabla y nunca se marcó como sustituto — describían dos formas de dar de
alta un proyecto incompatibles entre sí.

**Flujo real, hoy:**

| # | Dónde | Acción |
|---|---|---|
| 1 | Dialogflow CX | Crear el agente (manual, no se automatiza) |
| 2 | Dialogflow CX | Crear el entorno de **producción** (manual, a propósito — ver por qué abajo) |
| 3 | Panel · pestaña Proyectos | Wizard: **ID de agente + URL de repo** → el servidor crea la estructura, el `cx-deploy.yaml` (S23), registra el mapeo en Firestore (S4) y hace el `pull` inicial (S22) |
| 4 | Local | Ejecutar el comando IAM que muestra el wizard (S6b) |
| 5 | Local | `git pull` — el servidor ya escribió en GitHub |
| 6 | Panel | Pipeline listo |

**El entorno de producción no se crea automáticamente** (paso 2), y esto
no cambió con S22/S23. *Por qué:* el panel es para desplegar, no para
crear infraestructura — y crearlo sería una escritura en el agente fuera
de todos los gates.

---

## 5. Lo que aún no se ha medido

Ninguna pendiente — las dos que había (IAP directo en Cloud Run, ruido de
formato del `pull`) se midieron el 2026-08-06. Ver §6.

---

## 6. Hallazgos verificados contra el código

Registrados para que no se vuelvan a discutir de memoria.

| Afirmación | Realidad medida |
|---|---|
| "El selector está fijo durante el pipeline por diseño" | **Falso.** En `act_cx_resources_deploy_v1.html` los dos `<select>` solo se deshabilitan mientras cargan sus listas (líneas 836 y 845). Nada los bloquea tras el Paso 1 |
| "El caso local no existe, el panel siempre corre en Cloud Run" | **Falso.** La CLI y los cuatro `validate_*.py` corren en el Mac contra la API real |
| "Una instancia de Cloud Run reproduce el lock global" | **Falso.** Encola, no rechaza |
| "El diff solo toca lo que cambió" | **Incompleto.** Hace *"POST lo que falta, PATCH lo que cambió, DELETE lo que sobra"* (`act_cx_resources_deploy.py:366`) y construye un DELETE por cada recurso de CX ausente del repo (línea 397). Con el repo vacío, propone borrar el agente entero |
| "El `pull` solo necesita completarse" | **No basta.** Los recursos que solo existen en CX están marcados `"traible": False` (línea 892): el botón se niega a traerlos por diseño. Hay que levantar la restricción explícitamente |
| `cx_client.py:77` — "ADC causó problemas en Sprint 1" | **Verificado, 2026-08-06.** Con `x-goog-user-project`, ADC funciona igual que `gcloud auth print-access-token` (200 OK); sin la cabecera, 403 — el fallo de Sprint 1 era casi con toda seguridad la cabecera que faltaba, no ADC en sí |
| Nombres de los entornos | `staging` y `production`, verificado en `definitions/environments/` |
| **IAP directo en Cloud Run**, sin balanceador | **Verificado, 2026-08-06** contra la documentación oficial de Google Cloud. Se habilita con un solo flag (`gcloud run deploy --iap`), sin coste fijo mensual (sin balanceador, IP estática ni certificado aparte). Los propios ejemplos de la documentación usan `europe-west1` — la misma región de este proyecto |
| **Ruido de formato del `pull`** | **Verificado, 2026-08-06**, de forma indirecta pero repetida: las comparaciones de contenido de hoy entre CX y el repo (9 playbooks, 2 intents, 2 environments, 1 tool, 1 flow, 45 examples — más de 60 recursos) dieron cero diferencias espurias, excluyendo solo los campos ya conocidos como locales (`metadata`, `id`, `playbook`, `openapi_spec_file`) |
| "Solo hay 12 tipos de recurso built-in" | **Incompleto, verificado 2026-08-06** contra el discovery document real de la API v3beta1. Son **13** — falta Transition Route Groups (cuelga de Flow, como Pages). Ver S15 |
| Ruido de formato en los 6 tipos que Petal no usa (Entity Type, Webhook, Generator, Page, Transition Route Group, Version) | **Verificado, 2026-08-06** en un agente desechable creado y borrado para la prueba (`4617f5d2-...`, confirmado el borrado con un 404 posterior). Los 6 salieron idénticos, sin ruido — mismo comportamiento que playbooks/examples: la API omite los campos con valor por defecto en vez de devolverlos vacíos. **Matiz real:** `Version` trae un campo `state` (ej. `SUCCEEDED`) de solo lectura, no estaba en la lista de exclusión conocida (`name`/`tokenCount`/`createTime`/`updateTime`) — hay que leerlo y usarlo para confirmar el éxito de la creación (el Paso 5 debe polear hasta verlo), pero excluirlo de lo que se compara/envía como definición, igual que los demás campos de solo lectura |

---

## 8. Revisión adversarial — hallazgos abiertos (2026-08-03)

Tres revisores independientes en paralelo, cada uno con una lente distinta (modos de fallo externos · el tercer proyecto · superficie de escritura), sobre este documento y el código real. Regla impuesta: cada hallazgo con `archivo:línea` o marcado como no verificado.

**Los tres convergieron por su cuenta en el mismo hallazgo de fondo.**

### 8.1 El hallazgo de fondo — el modelo de confianza

Las decisiones de §2 tratan panel y servidor como una sola pieza. Dejan de serlo en cuanto el servidor tiene una URL pública.

| Qué | Evidencia |
|---|---|
| `POST /step/8` promociona **producción** sin haber pasado por ningún paso anterior. `run_step` despacha cada paso de forma independiente; solo exige `project` y `agent` | `act/server.py:67` |
| El Paso 4 ejecuta el array de `operations` que recibe **sin recalcular nada**, incluidos los DELETE, usando la ruta absoluta de cada operación. La decisión *"el diff nunca propone DELETE"* está en la capa equivocada: quitarlo del diff no lo quita del ejecutor | `act_cx_resources_deploy.py:554` · `server.py:54` |
| Una petición puede convertir el token de la cuenta de servicio en una llamada a **cualquier URL**: `url = path if path.startswith("http") else …`, y `path` llega del cliente en cuatro sitios | `act/utils/cx_client.py:108` |
| `previous_versions` (Pasos 6/7) y `version_names` (Paso 8) viajan por el mismo canal, con rutas absolutas | `server.py:58`, `:63` |
| `/versions/protect` escribe en CX **sin coger el lock** ni validar la ruta | `server.py:143-152` |

**Por qué no era un problema antes:** el servidor escuchaba en `127.0.0.1`, el cliente era el mismo Mac y el token era la sesión de `gcloud` de Jero. Nada de eso sobrevive a Cloud Run.

**Consecuencia:** el candado de §2 protege el Paso 3, que es el único que **no escribe**. Falta una decisión que hoy no existe en el documento: **qué recomprueba el servidor y qué se cree**. Responderla de una vez cierra la mayoría de los hallazgos de arriba.

### 8.2 Cuatro decisiones de §2 que son incorrectas

1. **`agent` vs `agent_id`.** §2 fija `agent: ""`, pero el código lee `config.get("agent_id")` y el archivo real usa `agent_id`. Con el nombre decidido, la Regla 11 da **siempre falso** y el Paso 3 devuelve `ok` con cero operaciones — indistinguible de un paso superado. `act_cx_resources_deploy.py:157` · `definitions/agent.yaml:11`
2. **La Contents API no es recursiva.** `definitions/examples/` tiene cuatro subdirectorios (`checkout`, `compra`, `petal_cx_orchestrator`, `registro_task`). `git ls-tree -r` los recorre; la Contents API sobre un directorio devuelve solo el primer nivel. Los 28 examples desaparecerían a ojos del servidor y el `pull` los reescribiría encima. Hace falta la Git Trees API con `recursive=1`, o el tarball.
3. **El Paso 8 hace `gh pr merge` y `merge_staging_into_main()` no recibe ningún parámetro de repo** (`:1404`). Con multi-repo no es que le falte el binario: estructuralmente no sabe de qué repo habla. Y la GitHub App solo tiene `Contents: write` — el merge por API necesita permiso de pull requests, no concedido.
4. **`write_run_log` escribe en disco efímero** (`:119-128`), igual que el inventario. Es el único rastro forense de las cinco operaciones que escriben en CX. §2 solo resolvió el inventario. Lo mismo `cx_repo_drift`, que sigue leyendo `docs/data/...json` (`:874`): el contador de deriva se queda sin fuente.

### 8.3 Cuatro huecos

- **Dos repos pueden reclamar el mismo agente.** La Regla 11 valida repo→agente; nunca agente→repos. El desplegable lista los agentes sin marcar cuáles ya tienen repo. Con *Traer al repo* de opción por defecto, un repo nuevo mal vinculado se lleva el agente ajeno entero. `cx_client.py:309-321`
- **El `pull` no sabe dónde escribir un recurso que solo existe en CX.** La única función que resuelve rutas devuelve `"definitions/<tipo>/(sin localizar)"` (`:916`). Es justo el caso del onboarding.
- **Perder `previous_versions` deja el rollback imposible y no se regenera con nada.** El inventario perdido se rehace con el Paso 1; esto no. `:1347-1350`
- **El Paso 5 puede pasar de 60 minutos.** Una LRO por cada flow, playbook y tool, con 300 s de tope cada una. Con 10 playbooks y 2 flows son 65 min potenciales, más el PATCH del entorno.

### 8.4 Choque con una decisión cerrada

**`x-goog-user-project` es la cabecera de cuota** (`cx_client.py:89`). Con ADC exige `serviceusage.services.use` sobre ese proyecto, permiso que `roles/dialogflow.admin` **no incluye**. §2 decidió "cero pasos de IAM" precisamente para no chocar con CLAUDE.md §7.1. Entra en la medición pendiente de ADC (§5).

---

## 9. Seguimiento de los hallazgos

Estado de los 14 hallazgos de §8. Se completa a medida que Jero decide.
**Abierto** = sin solución · **Standby** = solución propuesta con dudas
pendientes · **Resuelto** = cerrado, listo para redactar.

| ID | Hallazgo | Estado | Solución |
|---|---|---|---|
| **C1** | `POST /step/8` promociona producción sin paso previo | ✅ | S1 — el servidor no acepta el array del panel |
| **C2** | El Paso 4 ejecuta el array de `operations` recibido | ✅ | S1 + S1b — recalcula y aplica sin comparar (decisión de Jero) |
| **C3** | Una petición puede dirigir el token a cualquier URL | ✅ | C3 — el servidor construye todas las URLs desde `project`/`agent` |
| **C4** | `previous_versions` y `version_names` por el mismo canal | ✅ | S8 — Firestore |
| **C5** | `/versions/protect` escribe sin lock | ✅ | S13 + S13b — lock en Firestore, todos los endpoints que escriben |
| **D1** | §2 fija `agent: ""` pero el código lee `agent_id` | ✅ | S2 |
| **D2** | La Contents API no es recursiva | ✅ | S5 — Git Trees API con `recursive=1` |
| **D3** | `merge_staging_into_main()` sin repo, usa `gh` | ✅ | S6 — merge directo de ramas por API, sin permiso nuevo |
| **D4** | `write_run_log` y `cx_repo_drift` usan disco efímero | ✅ | S12 — Firestore con timestamp |
| **H1** | Dos repos pueden reclamar el mismo agente | ✅ | S4 — mapeo agente→repo en Firestore |
| **H2** | El `pull` no sabe dónde escribir un recurso nuevo | ✅ | S7 + S14 — carpeta = tipo (fija), nombre desde `displayName` |
| **H3** | Perder `previous_versions` impide el rollback | ✅ | S8 |
| **H4** | El Paso 5 puede pasar de 60 minutos | ⏸ | Versionar solo lo que el diff tocó — **hoy versiona todo, hay que construirlo** |
| **X1** | `x-goog-user-project` exige `serviceusage.services.use` | ✅ | S10 + S6b — permiso manual, el panel muestra el comando |

**13 resueltos · 1 pendiente de matizar (H4).**

**Cuando los 14 estén resueltos, se lanza una segunda ronda de adversariales** antes de redactar la Fase 5.

---

## 10. Decisiones de la ronda de soluciones

Respuestas a los 14 hallazgos de §8, acordadas el 2026-08-04. Sustituyen o
matizan lo escrito en §2 donde entren en conflicto — **esta sección manda.**

| ID | Decisión | Por qué | Estado |
|---|---|---|---|
| **S1** | El servidor **recalcula el diff** en el Paso 4 y no acepta el array de `operations` del panel | El panel valida para dar buena UX; el servidor valida para garantizar que no pasa nada malo pase lo que pase en el panel | ✅ |
| **S1b** | Recalcula y **aplica sin comparar** contra lo aprobado | Solo trabaja Jero y el lock impide deploys en paralelo | ✅ riesgo asumido |
| **S1c** | El servidor acepta `project` y `agent` del panel | Con S1 y C3, el servidor nunca acepta un `repo` del cliente — siempre lo deriva fresco desde Firestore a partir de `agent` (S4), así que un `repo` desincronizado es estructuralmente imposible. Un `project`/`agent` erróneo falla en la propia llamada a CX si esa combinación no existe. **Riesgo residual aceptado** (revisado 2026-08-05, tras quitar el candado de §2): si el `project`/`agent` erróneos apuntan por coincidencia a un agente real que sí existe ahí, nada lo detecta antes de aplicar — mismo riesgo que S1b, mismo motivo para aceptarlo | ✅ |
| **C3** | El servidor **construye todas las URLs** desde `project`/`agent`. Nunca acepta rutas del panel | Hoy `cx_client.py:108` acepta URLs completas del cliente: podría apuntar a otro agente, otro proyecto o un host externo | ✅ |
| **S2** | El campo de `agent.yaml` se llama **`agent_id`**, no `agent` | Con `agent` el código no lo encuentra, el Paso 3 devuelve OK con cero operaciones y el deploy no aplica nada sin avisar | ✅ |
| ~~S3~~ | ~~El panel tiene dos pestañas: Deploy (por defecto) y Proyectos (onboarding y sincronización)~~ | **Sustituida (2026-08-06), durante el maquetado del panel.** Una sola pantalla, sin pestañas: el pipeline de 5 pasos ocupa el área principal, y una sección **"Tools"** al pie del sidebar (~25% de su altura, con espacio para crecer) reúne las acciones sueltas que no son parte del flujo secuencial — el wizard de onboarding (S22, vincular agente↔repositorio) y desplegar un resource suelto (S20). Más simple que mantener dos pestañas separadas para dos pantallas que en la práctica se usan poco | ❌ |
| ~~S4~~ | ~~El mapeo agente→repo vive en Firestore~~ | **Sustituida por S24 (§15, 2026-08-08).** Un proyecto puede tener varios agentes relacionados y con un repositorio por agente esa relación quedaba partida en repositorios sueltos. La región y la autodetección de S4 siguen vigentes; lo que cambia es de quién es el repositorio | ❌ |
| **S5** | Leer los YAML con **Git Trees API `recursive=1`**, no Contents API | Contents API solo devuelve el primer nivel; `definitions/examples/` tiene 4 subdirectorios | ✅ |
| **S6** | Paso 8: **merge directo de ramas por API**, no `gh pr merge` | Solo necesita `contents:write`, que la GitHub App ya tiene. Sin permiso nuevo | ✅ |
| **S6b** | El servidor **no concede IAM**. El panel muestra el comando exacto y Jero lo ejecuta una vez | Conceder permisos automáticamente exige un privilegio muy alto sobre proyectos ajenos, y CLAUDE.md §7.1 pide aprobación explícita | ✅ |
| ~~S7~~ | ~~Deducir la ruta del nombre del recurso CX~~ | **Sustituida por S18+S19** — la correspondencia es por `cx_id`, no por ruta | ❌ |
| **S7b** | **Prueba obligatoria de punta a punta** antes de dar el `pull` por bueno: traer un recurso real y confirmar que aparece en la ruta correcta | Si falla en silencio, el recurso llega al sitio equivocado sin que nadie lo sepa | ✅ |
| **S8** | `previous_versions` se guarda en **Firestore** | No se regenera con nada: perderlo hace el rollback imposible | ✅ |
| **S9** | El servidor corre en **`cloud-run-multiproyecto`**, separado de los proyectos CX | Lo hace agnóstico: puede gestionar cualquier agente de cualquier proyecto | ✅ |
| **S10** | Mantener `x-goog-user-project` y añadir **`serviceusage.services.use`** al SA | Con servidor y agentes en proyectos distintos, Google exige ese permiso para cargar la cuota al proyecto correcto | ✅ |
| **S11** | Proyecto nuevo: crear en GCP → registrar en la pestaña Proyectos → ejecutar el comando IAM que muestra el panel | Libertad para añadir proyectos con **un solo paso manual**, documentado y bajo control de Jero | ✅ |
| **S12** | Log de auditoría en **Firestore con timestamp**, cada entrada indexada por `project` + `agent_id` + `tipo` además del `cx_id`, y guardando también **la ruta del archivo del repo** que escribió esa entrada (ronda adversarial, 2026-08-05 — permite avisar si un `cx_id` cambia de archivo entre deploys, ver §12) | El disco de Cloud Run es efímero: sin esto no queda rastro forense de qué se escribió en producción. El `cx_id` de S18 solo es único **dentro de su propio agente y su propio tipo** — CX puede asignar el mismo ID a recursos de dos agentes distintos, y también a recursos de dos tipos distintos dentro del mismo agente (verificado dos veces: el Playbook orquestador de Petal y el Intent "Default Welcome Intent" comparten el ID `00000000-0000-0000-0000-000000000000`). Un log que guarde solo `cx_id` — o incluso `cx_id` + agente, sin el tipo — no podría distinguir a qué recurso pertenece cada entrada | ✅ |
| **S13** | **Todos** los endpoints que escriben en CX pasan por el lock, sin excepción | `/versions/protect` y `/cx-repo-check` lo saltaban: se podía renombrar una versión mientras el Paso 5 la rotaba | ✅ |
| **S13b** | El lock vive en **Firestore**, no `threading.Lock` | `threading.Lock` es por proceso: con más de una instancia no protege nada | ✅ |
| ~~S14~~ | ~~Nombres de carpeta como convención fija~~ | **Sustituida por S19** — la estructura es libre y el tipo lo declara el propio YAML | ❌ |
| **S15** | **13 tipos built-in** (verificado 2026-08-06 contra el discovery document real de la API — eran 12 conocidos + Transition Route Groups, que cuelga de Flow igual que Pages y es un recurso de definición real, no algo exótico). Los **tipos adicionales de verdad exóticos se declaran en `cx-deploy.yaml`** con su endpoint | CX tiene más tipos que los 13 actuales — voz, NLU, telefonía. El sistema debe cubrirlos sin reescribirse | ✅ |
| **S15b** | Cada tipo nuevo exige **medir si acepta `updateMask` o requiere Full Update** — y esto también aplica **por región**, no solo por tipo (añadido 2026-08-06, ligado a S4): el bug de `CLAUDE.md §3.8` está documentado específicamente para `europe-west1`, nunca verificado en otras regiones. Un proyecto nuevo en otra región no puede asumir el mismo comportamiento — hay que remedirlo la primera vez, no copiar el resultado de Petal | CLAUDE.md §3.8: varía por recurso y solo se sabe midiendo contra la API real | ✅ |
| **S16** | La pestaña Proyectos guía el discovery de un tipo nuevo: endpoint, campos, comportamiento POST/PATCH. Una vez por tipo | Flexibilidad y cobertura para cualquier proyecto futuro | ✅ |
| **H4** | El Paso 5 versiona **solo los recursos que el diff tocó** | El tiempo pasa a ser proporcional a los cambios, no al tamaño del agente | ✅ **hay que construirlo** |

### 10.1 Los cuatro puntos abiertos

**H4 — hay que construirlo, hoy no es así.** Verificado: `create_versions_for_snapshot` (`:978`) recorre **todos** los flows, **todos** los playbooks y **todos** los tools referenciados, no los que tocó el diff. Beneficio extra no previsto: hoy cada deploy quema un hueco de versión en los 10 playbooks contra un límite de 20. Al construirlo, el entorno debe fijar **versión nueva para lo que cambió y la existente para lo que no** (Regla 16 exige la cadena completa) — el snapshot deja de ser una foto atómica, pero el rollback sigue funcionando porque `previous_versions` registra lo que estaba fijado.

**S1b — el supuesto no se sostiene.** "No puede haber cambios en CX entre el Paso 3 y el Paso 4" falla por dos vías: editar el agente directamente en la consola de CX (el caso normal, es por lo que existe la comprobación de deriva) y el tiempo, porque el flujo declarado de Jero es quedarse en el Paso 4 acumulando cambios en draft. Consecuencia acotada —sin DELETE automático, lo peor es un POST o PATCH no revisado— pero rompe el gate por el otro lado. Comparar cuesta casi nada: el servidor ya tiene las dos listas.

**Simplificación que abre S1.** Si el servidor recalcula en el Paso 4, el Paso 3 también puede. Entonces el inventario no necesita viajar al navegador, y desaparecen cuatro piezas: el inventario en `localStorage`, el candado de proyecto/agente/repo, el umbral de antigüedad y la mitad de D4. Coste: un LIST más de CX por Paso 3 — lo que ya hace el Paso 1.

**S7 + S14 — falta una línea.** Dentro de `definitions/examples/` hay subcarpetas por playbook. Cuando el `pull` trae un example nuevo, ¿va a `examples/<playbook>/` o directo a `examples/`? El servidor conoce el padre, así que puede hacer lo primero — solo hay que decidirlo.

---

## 11. Segunda ronda de decisiones (S17–S23)

Acordadas el 2026-08-04, después de §10. **Sustituyen a S7 y S14.**

| ID | Decisión | Por qué | Estado |
|---|---|---|---|
| **S17** | Renombrar "artefactos" → **"resources"** en todo el sistema | Es el término oficial de la API de CX | ✅ |
| **S18** | Cada YAML lleva **metadata: tipo, padre y `cx_id`**. El servidor escribe el `cx_id` al subirlo por primera vez | La correspondencia repo↔CX pasa a ser por `cx_id`, no por nombre de archivo ni por carpeta | ✅ |
| **S19** | **La estructura de carpetas es libre.** El servidor la ignora — va por `cx_id` | Resuelve la contradicción entre S7 y S14 | ✅ |
| **S20** | El servidor puede **desplegar un resource concreto** bajo demanda leyendo su `cx_id`, vía `POST /deploy-resource` con body `{project, agent, tipo, cx_id}` — el resto (contenido, comparación) se recalcula en fresco del repo y CX en ese momento, como el Paso 2/3. Pasa por el lock (S13) y el log de auditoría (S12), sin excepción. Revisado 2026-08-05 (ronda adversarial): el código de este endpoint **no tiene ninguna forma de construir una URL con `/environments/`** — solo sabe llamar a `.../{tipo}/{cx_id}` (borrador). No es que la API lo impida por su naturaleza (sin verificar); es que el endpoint no aprendió a escribir esa URL, así que no puede alcanzar producción aunque se le pida | Permite iterar rápido sin pasar por el pipeline completo | ✅ |
| ~~S21~~ | ~~Templates YAML en `/templates` dentro de la imagen Docker~~ | **Sustituida (2026-08-05)** — sin plantillas estáticas guardadas. Para un recurso nuevo, se pide la información necesaria y se construye el YAML directamente (el LLM ya conoce la forma de cada tipo). Para un proyecto nuevo con repo vacío, Jero copia un YAML real de otro repo a mano. Evita el coste de "cambiar un template exige reconstruir la imagen" (§12) — no hay nada que reconstruir porque no hay plantilla guardada. Cierra también la duda de S21 vs `CLAUDE.md §6`: sin la capacidad de "desplegar sin intervención manual" en la definición, no hay conflicto que resolver | ❌ |
| **S22** | **Wizard de onboarding** en la pestaña Proyectos: ID de agente + URL de repo → el servidor crea la estructura, muestra el comando IAM, registra en Firestore y hace el `pull` inicial | Reduce el onboarding a dos datos y un comando manual | ✅ |
| **S23** | `cx-deploy.yaml` lo **crea el servidor** en el paso 3 del wizard | Marcador que identifica el repo como proyecto CX. Jero no lo toca | ✅ |

---

## 12. Notas para quien implemente

No son decisiones pendientes: son consecuencias de lo acordado que hay que
tener delante al construir.

**Fallo parcial: Paso 3 lo hereda bien, Paso 5 necesita el mismo patrón
que le falta** (hallazgo de la ronda adversarial, corregido 2026-08-06,
verificado contra el código real). El Paso 3 hereda tal cual
`step_4_deploy` (`act_cx_resources_deploy.py:1268-1290`): cada operación
queda con su resultado (`OK`/`ERROR`/`NO_INTENTADO`), se para en el
primer fallo, y hay un modo para reintentar solo lo pendiente
(`only_pending`) sin repetir lo que ya salió bien. **El Paso 5, en la
parte de crear versiones, no puede heredar el código actual tal cual** —
`create_versions_for_snapshot` (`:978`) es un bucle simple que crea
versiones una a una y, si falla a mitad, lanza el error y para: las
versiones ya creadas antes se quedan huérfanas, sin registrar ni limpiar.
El servidor nuevo debe aplicar en esa parte **el mismo patrón que ya
funciona en el Paso 3** — registrar cada versión creada con su resultado,
parar en el primer fallo, dejar claro qué se creó. El resto del Paso 5
(fusionar antes de apuntar producción, parar sin tocar nada si el merge
falla) sí se hereda bien de `step_8_approve_production` (`:1414`).

**Todos los endpoints comparten el mismo sobre de respuesta — no hace
falta un schema distinto por cada uno** (hallazgo de la ronda adversarial,
implementabilidad, corregido 2026-08-06). Se hereda el patrón que ya usa
el pipeline local (`act/act_cx_resources_deploy.py:140`):

```python
def step_result(status, log, data=None):
    return {"status": status, "log": log, "data": data or {}}
```

`status` (`"ok"` o error), `log` (líneas de texto para el panel), `data`
(lo específico de cada endpoint — operaciones del diff, nombre del
snapshot, lista de proyectos...). Errores con códigos HTTP estándar: 400
si faltan datos, 403 si el permiso falla, 404 si el recurso no existe,
409 si el lock está ocupado, 500 si algo interno falla — consistente con
`PipelineError` en el código actual.

**El diff cambia de mecanismo.** Hoy la correspondencia va por `displayName`
y `load_definitions()` recorre `definitions/<tipo>/` carpeta por carpeta.
Con S18 y S19 el servidor lee **todos** los YAML del repo recursivamente y
agrupa por el `tipo` declarado dentro de cada archivo. Un YAML sin ese campo
se vuelve invisible para el pipeline — que dé error explícito, no silencio.

**Detectar `cx_id` duplicados y parar.** Duplicar un archivo para crear una
variante es natural; olvidarse de vaciar el `cx_id` deja dos YAML
reclamando el mismo resource de CX. Cubre solo el caso de **dos archivos
del mismo repo** con el mismo `cx_id` — no cubre un `cx_id` válido pero
equivocado en un único archivo (por edición manual, o por copiar un YAML
de **otro** repo/agente sin vaciarlo, S21 sustituida en §11).

**Aviso si un `cx_id` cambia de archivo entre deploys (hallazgo de la
ronda adversarial, 2026-08-05).** El log de auditoría (S12) guarda, además
de `project`+`agent_id`+`tipo`+`cx_id`, **qué archivo del repo** llevaba
ese `cx_id` la última vez que se escribió. Si en un deploy nuevo el mismo
`cx_id` aparece en un archivo distinto al registrado, el servidor avisa
antes de aplicar — mostrando archivo antes/después **y** `displayName`
antes/después como contexto, no como lo que decide. El disparador es
siempre el archivo, nunca el nombre: un renombrado legítimo (mismo
archivo, `displayName` distinto) no dispara nada — comparar por nombre
reintroduciría la fragilidad que S18 eliminó (un `displayName` puede
cambiar a propósito). Sin este aviso, un `cx_id` copiado de otro repo sin
vaciar (H-C, ronda adversarial multi-proyecto) se aplicaría en silencio
sobre el recurso equivocado.

**H4 hay que construirlo.** `create_versions_for_snapshot` (`:978`) hoy
recorre todos los flows, todos los playbooks y todos los tools referenciados
— no los que tocó el diff. Al cambiarlo, el entorno debe fijar versión nueva
para lo que cambió y la existente para lo que no (Regla 16 exige la cadena
completa).

**El servidor escribe en el repo de forma sistemática.** `agent.yaml`, el
`cx_id` de cada resource nuevo, los artefactos del `pull`, la estructura del
wizard y el `cx-deploy.yaml`. El flujo unidireccional de §2 queda anulado, y
con S18 un deploy deja de ser de solo lectura hacia GitHub. El aviso de
hacer `git pull` es parte del funcionamiento normal, no una excepción.

**S1b — riesgo asumido.** El servidor recalcula y aplica sin comparar contra
lo aprobado. Si CX cambia entre el Paso 3 y el Paso 4 —edición directa en
consola, o tiempo transcurrido— se aplican operaciones que nadie revisó.
Acotado porque el diff ya no propone DELETE.

**Cambiar un template exige reconstruir la imagen**, al vivir en `/templates`
dentro del contenedor (S21).

**El bloque `metadata` nunca se compara ni se envía a CX — regla única, no
una lista por tipo.** Cada YAML lleva `metadata: {tipo, padre, cx_id}` (S18)
más el resto de sus campos sueltos al mismo nivel, sin envoltorio. La regla
para el diff es: todo lo que está dentro de `metadata` se excluye de la
comparación y del body que se manda a la API; todo lo que está fuera, se
compara y se envía tal cual. Verificado con caso real: los 9 Playbooks de
`definitions/playbooks/` ya llevan esta cabecera, con el `cx_id` real
confirmado contra un `LIST /playbooks` en vivo — incluido el caso del
Playbook orquestador, cuyo `cx_id` es `00000000-0000-0000-0000-000000000000`
(ID real asignado por CX a ese rol, no un placeholder).

**La clave de emparejamiento es `tipo` + `cx_id`, nunca `cx_id` suelto.**
Verificado con caso real: el Playbook orquestador y el Intent "Default
Welcome Intent" comparten el mismo `cx_id`
(`00000000-0000-0000-0000-000000000000`) — cada tipo de recurso tiene su
propio espacio de IDs en CX, no hay unicidad entre tipos. No hace falta un
campo compuesto nuevo: como el servidor ya agrupa los YAML por `tipo` antes
de comparar nada (S18), basta con que esa agrupación sea el paso previo
obligatorio a cualquier búsqueda por `cx_id` — nunca buscar un `cx_id` en
una bolsa que mezcle recursos de distinto tipo.

**El emparejamiento pasa de `displayName` a `cx_id`, pero no puede migrar de
golpe.** Mientras existan YAML sin `metadata.cx_id` en el repo, emparejar
por `cx_id` los trataría como inexistentes en CX y el diff propondría
crearlos de nuevo (viola idempotencia, `CLAUDE.md §3.4`). Decisión: migrar
primero **todos** los YAML de un tipo con su cabecera de `metadata`, y solo
entonces activar el emparejamiento por `cx_id` para ese tipo — sin lógica
híbrida de transición, que quedaría como deuda permanente si nadie la
retira después.

**El `cx_id` es único solo dentro de su agente** (ver S12) — no sirve como
clave si se llega a comparar o auditar entre agentes distintos sin
acompañarlo siempre de `project` + `agent_id`.

---

## 13. Dudas abiertas

Quedaba una, cerrada el 2026-08-05. Las otras tres se resolvieron el mismo día
(ver S20 en §10, S21 sustituida en §11) tras validar el mecanismo contra CX
real con Petal.

1. ~~S21 y CLAUDE.md §6~~ — **cerrada.** Al sustituir S21 (sin plantillas
   estáticas, sin capacidad de "desplegar sin intervención manual"), el
   conflicto con `§6` desaparece: no queda ninguna vía por la que un LLM
   escriba en CX sin que Jero confirme esa escritura en concreto. En la
   práctica, un LLM sí puede escribir directamente en CX fuera del pipeline
   — es el mismo gate que ya exige `CLAUDE.md §8.2` para cualquier `PATCH`
   directo: enseñar el body exacto y esperar confirmación explícita por
   cada escritura, nunca en bloque ni automático.

2. ~~Dónde escribe el `pull` un archivo nuevo~~ — **cerrada.** Por `tipo` +
   `cx_id` (ver §12). Verificado trayendo 18 resources reales de Petal que
   solo existían en CX.

3. ~~¿S20 se acota a draft?~~ — **cerrada** (ver S20, §10). Con el modelo de
   5 pasos, solo el Paso 5 (Publicar) toca producción — S20 usa el mismo
   mecanismo que el Paso 3, así que cae en el borrador por construcción, sin
   necesitar una regla aparte.

4. ~~Alcance de S17~~ — **cerrada (2026-08-05).** "Resources" en todas
   partes: texto de cara al usuario, identificadores en el código y campos
   en los YAML (`tipo`, no `tipo_artefacto` ni similar — ya aplicado en la
   cabecera `metadata` de los 45 examples, 9 playbooks, 2 intents, 2
   environments, 1 tool y 1 flow migrados hoy).

**Las cuatro dudas de §13 quedan cerradas.**

---

## 14. Infraestructura ya creada (Fase A)

Absorbido de `docs/cloudrun_handoff_opus.md` (2026-08-05) — ese archivo
se elimina. Son hechos de lo ya provisionado en GCP, no decisiones de
diseño; se guardan aquí para que no vuelvan a vivir duplicados en dos
sitios (motivo real de las 3 contradicciones de IAM encontradas y
corregidas hoy en el propio handoff).

### Proyecto GCP
- **Nombre:** `cloud-run-multiproyecto`
- **Facturación:** vinculada a cuenta `015D46-707718-D2A984` (Mi cuenta de facturación 1)
- **APIs habilitadas:** Cloud Run, Secret Manager, IAM

### Cuenta de servicio
- **ID:** `act-cloudrun-sa@cloud-run-multiproyecto.iam.gserviceaccount.com`
- **Permisos:** `roles/dialogflow.admin` sobre los proyectos CX registrados
- **Cómo gana permisos sobre un proyecto CX nuevo:** nunca automático — el panel muestra el comando `gcloud` y Jero lo ejecuta una vez, fuera del panel (S6b, S11, S22)

### Secret Manager
- **Secreto:** `github-app-private-key` en proyecto `cloud-run-multiproyecto`
- **Acceso:** solo `act-cloudrun-sa` — rol `roles/secretmanager.secretAccessor`
- **Contenido:** clave privada de la GitHub App `act-cloudrun-deploy`

### GitHub App
- **Nombre:** `act-cloudrun-deploy`
- **App ID:** `4474347`
- **Instalada en:** todos los repositorios de `jeronimosanchez` (actuales y futuros)
- **Permiso:** `Contents: Read and write` — sin webhook, sin OAuth, sin permisos de organización
- **Cómo genera acceso:** lee la clave privada desde Secret Manager, genera un JWT firmado (válido ~1h), lo usa para la operación, nunca lo guarda ni lo reutiliza
- **Por qué "todos los repositorios":** cualquier repo que Jero cree en el futuro ya es accesible, sin configuración extra por proyecto nuevo

### Firestore
- **Base de datos:** `(default)` en `europe-west1`
- **Capa gratuita:** sí (`freeTier: true`)
- **Uso:** mapeo agente→repo (S4), lock de concurrencia (S13b), log de auditoría (S12), `previous_versions` (S8)

### Servicio Cloud Run
- *(pendiente — Fase B, sin construir)*

---

## 15. El repositorio es del proyecto (S24 · 2026-08-08)

Sustituye a S4 en lo que toca al repositorio. Verificado contra dos agentes
reales del mismo proyecto antes de aplicarse.

### El mapeo se parte en dos

```
proyectos/<proyecto>          repo · rama_principal
agentes/<proyecto>__<agente>  region · rama · carpeta_raiz
```

**Por qué el repositorio sube al proyecto:** un proyecto de GCP puede tener
varios agentes relacionados —uno de texto y uno de voz para el mismo negocio— y
con un repositorio por agente esa relación queda partida en repositorios
sueltos, sin historial común.

**Por qué la región no sube:** es del agente. Dos agentes del mismo proyecto
pueden estar en regiones distintas — la API declara 17.

**Por qué la rama de trabajo tampoco:** publicar fusiona la rama de trabajo en
la principal. Con una rama compartida, publicar un agente arrastraría a la
principal todo lo que sus hermanos tuvieran sin publicar. Se comparte el
repositorio y su rama principal, no el trabajo en curso de cada uno.

### La clave de emparejamiento pasa a ser `agente` + `tipo` + `cx_id`

No es una preferencia: **CX reutiliza los mismos identificadores en todos los
agentes.** Medido sobre 86 resources de dos agentes reales — sus *Default Start
Flow* y *Default Welcome Intent* comparten `cx_id`. Con la clave anterior salían
**4 colisiones**; con la nueva, **0**. Sin el agente en la clave, la defensa de
`cx_id` duplicados salta el primer día con los resources que CX crea solo por
existir, y nada arranca.

### La cabecera gana `agente`

`metadata: {tipo, padre, cx_id, agente}`. **`proyecto` no entra**: se deduce del
repositorio. Lo escribe el pull; solo se pone a mano al crear un archivo desde
cero, igual que `tipo`.

**Un archivo con cabecera y sin `agente` no es de nadie.** No se puede aplicar
en ningún agente y, filtrando por agente, desaparecería de todas las vistas sin
dejar rastro. El Paso 1 es el único momento que lee el repositorio entero antes
de repartirlo, así que es el único sitio donde se puede avisar — y se cuenta
aparte, en su propia categoría.

### Cada agente tiene su carpeta

`<carpeta_raiz>/<nombre-del-agente>/<tipo>/…`, con `carpeta_raiz` por agente
(`definitions` de serie; `act/scaffolding` para los desechables).

Al pipeline la estructura le da igual —empareja por la cabecera, no por la
ruta— pero **el nombre del archivo sí tiene que ser único**, y no lo era: los
*Default Start Flow* de dos agentes caían en la misma ruta y el segundo pisaba
al primero. 4 rutas repetidas con el esquema anterior, 0 con el nuevo.

Se usa el nombre del agente y no su identificador porque quien abra el
repositorio tiene que entender qué mira. Si el agente se renombra, la carpeta
queda desfasada y no pasa nada: la verdad está en la cabecera.

### El candado pasa a ser del proyecto

Amplía S13/S13b. Lo que protege no es solo el agente: es también el
repositorio, y ese lo comparten todos sus agentes. Con un candado por agente,
dos deploys hermanos escribirían en el mismo repositorio sin verse.

### El repositorio se lee en una sola petición

Amplía S5. La Git Trees API sigue siendo la vía para conocer el árbol, pero el
**contenido** se descarga entero con el tarball: una petición en vez de una por
archivo.

No es una optimización cosmética. Con el repositorio compartido, leer archivo a
archivo crece con cada agente que se añade: **el límite de la API de GitHub
(5.000 peticiones/hora por instalación) se agotó en un día de trabajo real**. De
111 peticiones a 2, y de 40 segundos a 2.

Y no se filtra por carpeta para descartar archivos ajenos: la estructura es
libre y lo que dice de quién es un archivo es su cabecera. Leerlo todo y
repartir después es lo único que respeta esa regla — y ahora cuesta una
petición.

### Incidente registrado

Mientras la rama de trabajo era del proyecto, las pruebas de publicación
fusionaron **la rama de trabajo en `main`**: cinco commits de merge con nombres
como *"Publicar corte_inyectado en producción"*. No hubo pérdida de trabajo —un
merge añade— pero fue una escritura en `main` no autorizada.

De ahí salen dos cosas de este documento: la rama por agente, y que el smoke
test se niegue a arrancar su nivel de escritura si la rama principal del
proyecto es `main`, `master` o `production`.
