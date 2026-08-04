# Diseño del servidor Cloud Run — decisiones cerradas

**Qué es:** el diseño del servicio que sustituye a `act/server.py` y pasa el pipeline ACT de correr en el Mac de Jero a correr en Cloud Run, con soporte multi-repo y multi-agente.

**Estado:** cerrado salvo tres mediciones (§7). Es la base para redactar la Fase 5 del `act_build_playbook_v2.html` y las specs del `act_cx_resources_deploy_v2.html`.

**Fecha:** 2026-08-03 · **Rama:** `build/intento-2`

**Relacionado:** `docs/cloudrun_handoff_opus.md` (infraestructura ya creada en la Fase A: proyecto GCP, cuenta de servicio, Secret Manager, GitHub App). El `docs/plan_cloudrun_multiproyecto.md` que ese handoff cita no está en esta rama — vive en `feature/cloudrun-multiproyecto`.

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

*Por qué:* el timeout por defecto son 5 minutos y la regla de polling de operaciones largas permite esperar hasta 5 minutos exactos. Los Pasos 5 y 8 morirían justo en el límite.

**Lock explícito con 409, mantenido en el código.**

*Por qué:* una instancia con concurrencia 1 **encola**, no rechaza. Sin el lock, un segundo deploy no rebota: espera y luego se ejecuta con un diff calculado antes de que aterrizara el primero, sin que nadie se entere.

### Identidad

**ADC en los dos lados, sin bifurcación local/cloud** — `google.auth.default()` más la cabecera `x-goog-user-project`. En Cloud Run por la cuenta de servicio; en el Mac por `gcloud auth application-default login`.

*Por qué:* el caso local existe —el estándar de la Fase 1 exige que el pipeline funcione por CLI sin servidor, y los cuatro `validate_*.py` corren en el Mac contra la API real— pero ADC funciona en los dos sitios, así que no hace falta bifurcar.

**CLAUDE.md §3 se reescribe *después* de medirlo**, no antes. Ver §7.

### De dónde salen los datos

**Las definiciones se leen de GitHub por la Contents API**, con token de la GitHub App, siempre desde `staging`.

*Por qué:* hoy `load_definitions()` usa `git show` sobre `origin/staging`, y en un contenedor `python:3.11-slim` no hay ni repo ni binario `git`.

**El flujo de escritura es unidireccional: Jero empuja desde local, el servidor lee.** Dos excepciones, las dos en el mismo sentido: el panel escribe el ID del agente en `agent.yaml` al vincular un repo, y escribe los artefactos que se traen con el `pull`.

*Por qué importa decirlo:* esas escrituras dejan el local de Jero un commit por detrás sin avisar. **El panel debe decirlo al terminar cada una**: "Guardado. Haz `git pull` antes de seguir trabajando en local." Sin ese mensaje, el conflicto llega semanas después sin origen aparente.

### Qué se elige y cómo

**Dos selectores: repo de GitHub y agente CX**, preseleccionados por `localStorage` con los últimos usados.

*Por qué:* un solo selector sería más simple, pero Jero necesita ver el destino completo antes de escribir en él. Es la función de un panel de deploy. No hay selector de proyecto GCP: es siempre el mismo.

**El selector de repos solo muestra los que llevan `cx-deploy.yaml` con `cx_project: true`** en la raíz.

*Por qué:* la GitHub App ve todos los repos de la cuenta. Filtrar por la existencia de `definitions/` es frágil; un marcador explícito no lo es. `cx-deploy.yaml` es solo marcador — **no lleva el agente**, que sigue en `agent.yaml`, para no tener dos archivos declarando el mismo destino.

**El emparejamiento repo↔agente lo vigila la Regla 11 de la Fase 3**, comparando la selección contra `definitions/agent.yaml` por ID de agente. Si el repo no tiene agente configurado, el panel muestra el desplegable y guarda el ID.

*Por qué:* dos selectores independientes permiten elegir repo A con agente B. Al descartar que `cx-deploy.yaml` llevara el agente, esa regla deja de ser un detalle y pasa a ser el único guardián.

**`agent.yaml` lleva `project: ""` y `agent: ""`; el código comprueba `if not agent_id`.** El `project` lo escribe Jero a mano una vez en el onboarding — el panel no lo escribe, porque no tiene selector de proyecto de donde sacarlo.

*Por qué esa forma:* `if not` cubre a la vez el campo vacío y el campo ausente, así que no hace falta decidir entre las dos.

### El estado entre pasos — dos capas independientes

**Capa 1, visibilidad.** `localStorage` preselecciona el último repo + agente, y los selectores están siempre visibles para que Jero verifique antes de arrancar.

**Capa 2, candado.** El inventario embebe **proyecto, agente, repo y marca de tiempo** en el momento de generarse. El Paso 3 rechaza la petición si cualquiera de los tres identificadores no coincide con los selectores actuales, y también si la marca de tiempo supera el umbral, aunque coincidan.

*Por qué hacen falta las dos:* la capa 1 protege contra equivocarse **al elegir**. La capa 2 protege contra que el inventario guardado sea del agente A mientras los selectores muestran el agente B — y eso ocurre **sin ningún error del usuario**, porque `localStorage` sobrevive a recargar la página y los selectores nunca se deshabilitan (verificado, §6). Sin el candado, el Paso 3 puede desplegar las definiciones del agente A sobre el agente B con un diff de aspecto perfectamente normal.

*Por qué el umbral de antigüedad:* los tres identificadores coinciden cuando el inventario es simplemente **viejo del agente correcto**. Ese fallo ya se observó en el intento 1 — relanzar solo el Paso 3 con una foto anterior hizo que el diff propusiera crear algo que ya existía y la API devolvió 409.

*Por qué el inventario vive en el navegador:* Cloud Run es stateless y su disco es efímero; el archivo `docs/data/...json` que hoy comunica el Paso 1 con el Paso 3 no sobrevive entre peticiones.

### El diff nunca borra

**El diff solo propone POST y PATCH.** Los recursos que existen en CX y no en el repo se muestran aparte, con tres botones en el propio Paso 3:

1. **Traer al repo** *(opción por defecto)* — `pull` con casillas, Jero elige cuáles.
2. **Ignorar** — el deploy no los toca, siguen en CX.
3. **Eliminar de CX** — destructivo, con confirmación adicional.

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

## 3. Dónde aterriza cada cosa en el playbook

| Fase | Qué cambia |
|---|---|
| **3** — pipeline | ADC en `cx_client.py` · definiciones por Contents API · candado del inventario · el diff deja de proponer DELETE · Regla 11 reescrita · recuperar la Regla 9 (Pages) del intento 1 |
| **4** — validación | Los tests actuales son referencia, no contrato: el diff cambia de comportamiento. Se redefinen fase por fase |
| **5** — servidor | `cloudrun_server.py` · Dockerfile · GitHub App · lock 409 · endpoint de repos · endpoint que escribe `agent.yaml` · IAP · timeout |
| **6** — validación | Se reescribe entera como smoke test post-deploy |
| **7** — panel | Tres botones del diff · contador de deriva · panel informativo de onboarding · el panel lo sirve Cloud Run |
| **nueva** | El `pull` CX → repo |
| **8** — prueba de onboarding | Repo desechable + agente desechable, recorriendo el flujo completo. Termina antes de cualquier escritura sobre recursos reales |
| diferido | Fusión de los Pasos 2 y 3 en uno |

---

## 4. Onboarding de un proyecto nuevo

Las instrucciones viven **en el Paso 1 del panel**, no en un documento aparte.

*Por qué ahí:* es donde se necesitan. Nadie recuerda una lista de doce pasos que usa tres veces al año.

| # | Dónde | Acción |
|---|---|---|
| 1 | Dialogflow CX | Crear el agente → CX asigna un ID |
| 2 | Dialogflow CX | Crear los entornos `staging` y `production` |
| 3 | Local | Crear el repo con `cx-deploy.yaml`, `definitions/`, `agent.yaml` y rama `staging` — a mano o desde `cx-project-template` |
| 4 | Local | Escribir el ID del proyecto GCP en `project` de `agent.yaml` (sale de la URL de CX) |
| 5 | Local | Subir a GitHub |
| 6 | Panel · Paso 1 | Seleccionar el repo → el panel detecta que no tiene agente configurado |
| 7 | Panel · Paso 1 | Elegir el agente CX → el panel guarda el ID y avisa de hacer `git pull` |
| 8 | Local | `git pull` |
| 9 | Panel · Paso 3 | Traer CX → repo, eligiendo artefactos con las casillas |
| 10 | Local | `git pull` |
| 11 | Panel | Comprobar que `staging` ✓ y `production` ✓ están visibles |
| 12 | Panel | Pipeline listo |

**Los entornos no se crean automáticamente** (paso 2). *Por qué:* el panel es para desplegar, no para crear infraestructura — y crearlos sería una escritura en CX fuera de todos los gates numerados.

**`cx-project-template` es opcional**, repo privado marcado como *template* nativo de GitHub. Si se usa, hay que marcar **"Include all branches"** al crear el repo, o `staging` no viaja. Si falta esa rama, el panel debe decirlo con un mensaje claro en vez de fallar de forma oscura.

---

## 5. Lo que aún no se ha medido

Tres cosas, todas de una sola comprobación. Ninguna bloquea la redacción del playbook, pero **ninguna debe darse por buena sin medirla** — en el intento 1 cuatro afirmaciones heredadas resultaron falsas al comprobarlas.

| Qué | Por qué importa |
|---|---|
| **IAP directo en Cloud Run** en `europe-west1` | La alternativa es un balanceador, que tiene **coste fijo mensual** y rompe la propiedad de "escala a cero y no cobra" |
| **ADC + `x-goog-user-project` desde el Mac** | `cx_client.py:77` afirma que ADC *"causó problemas en Sprint 1"* y nunca se volvió a comprobar. Sospecha: faltaba esa cabecera, hoy obligatoria. Medir antes de reescribir CLAUDE.md §3 |
| **Ruido de formato del `pull`** | Los YAMLs generados desde CX deben salir con la misma forma que `definitions/` — sin los campos que gestiona el servidor y con los que solo existen en el repo (`openapi_spec_file`, `id`, `playbook`, `flow`, `start_playbook_id`). Si no, cada `pull` produce un diff enorme de cambios que no son cambios. Primera medición antes de declarar el `pull` funcional |

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
| `cx_client.py:77` — "ADC causó problemas en Sprint 1" | **Sin medir.** Afirmación heredada. Ver §5 |
| Nombres de los entornos | `staging` y `production`, verificado en `definitions/environments/` |
