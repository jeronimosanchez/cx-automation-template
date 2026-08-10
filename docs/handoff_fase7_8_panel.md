# Handoff — Fase 7 y Fase 8: el panel conectado

**Para quién es este documento:** una sesión nueva (Opus), sin memoria de las sesiones anteriores, que va a construir el panel de producción conectado al servidor (Fase 7) y su validación (Fase 8). Tienes libertad total de actuación dentro de esta tarea. Empieza por el §0 y el §2 antes que nada.

**Estado (2026-08-10):** las Fases 1 a 6 están construidas y probadas. Existe el pipeline (`act/act_cx_resources_deploy_cloudrun.py`), su suite (`act/validate_pipeline_cloudrun.py`), el servidor HTTP (`act/server_cloudrun.py`), su smoke test (`act/validate_server_cloudrun.py`) y el `Dockerfile`. **No arrancas de cero: lee ese código antes de asumir nada.**

---

## 0. Libertad de actuación — qué haces sin preguntar, qué te para en seco

Tienes libertad total dentro de esta tarea. **No pidas permiso** para:

- Crear, escribir, reescribir y borrar archivos del repositorio.
- Modificar `act/server_cloudrun.py` y el `Dockerfile` — esta tarea incluye tocarlos (ver §5.1).
- Instalar dependencias, arrancar y tirar el servidor y el contenedor las veces que quieras.
- Crear ramas, commitear y hacer `git push` **a tu rama desechable**.
- Crear, usar y borrar **tu** agente CX desechable y **tus** documentos de Firestore.
- Desplegar a Cloud Run **en `cloud-run-multiproyecto`** y borrar lo que despliegues.
- Leer lo que necesites y equivocarte y volver a intentarlo. Eso es trabajar.

**Paras en seco y preguntas solo en dos casos:**

1. **Cambio estructural a `CLAUDE.md`.** Corregir un dato desfasado dentro de una sección existente es parte del trabajo. Añadir, quitar o reescribir secciones, reglas o constraints, no.
2. **Cualquier cosa que toque Petal**, en el sentido amplio del §2 — incluido desplegar en su proyecto, habilitar una API allí o tocar su IAM.

**Y una tercera regla que no es un permiso, es un ritmo: no vayas rápido.** Vale más un trabajo que tarda el doble y llega entero que uno que llega pronto con la mitad de las validaciones dadas por buenas "por inspección del código". Si tienes que elegir entre cerrar la tarea y hacerla bien, haz bien la parte que puedas y deja escrito qué queda pendiente y por qué.

---

## 1. Qué leer, en este orden

1. `CLAUDE.md` — completo.
2. `docs/panels/act_build_playbook_v2_cloudrun.html` — las **Fases 7 y 8** completas. Es tu especificación, revisada instrucción por instrucción el 2026-08-10 contra el código real.
3. `docs/cloudrun_diseno_servidor.md` — completo, y con atención especial al **§16 (S25)**, la decisión de acceso, que es de anoche y cambia esta fase.
4. `docs/panels/act_cx_resources_deploy_v2.html` — el panel de referencia que vas a duplicar y conectar. Léelo **entero** antes de editar nada: tiene ~2.300 líneas y la lógica de simulación está repartida, no concentrada.
5. `act/server_cloudrun.py` — los 9 endpoints y el sobre de respuesta que el panel consume.
6. `act/act_cx_resources_deploy_cloudrun.py` — qué devuelve cada función, para saber qué puede pintar el panel.

Si algo de lo que lees contradice lo que te parece mejor, para y pregunta — no lo decidas por tu cuenta.

---

## 2. Regla absoluta — más importante que completar la tarea

**Nunca, bajo ninguna circunstancia, toques el proyecto `floristeria-petal-digital` ni ningún agente real de Petal.**

- Proyecto prohibido: `floristeria-petal-digital`.
- Agentes prohibidos: `745375ba-ac7e-4eb8-b8a0-d742891f2aa4` (Petal 1.0) y `cea66b60-192d-4b5a-af10-28f8661032e0` (Petal 1.1).
- Rama prohibida: `main` de `jeronimosanchez/cx-automation-template`.

**Todo tu trabajo ocurre en `cloud-run-multiproyecto`**, con un agente CX y una rama que tú mismo crees para esta tarea. No reutilices ningún agente, rama ni documento de Firestore que encuentres ya existente, aunque parezca desechable — créalo tú de cero.

**Estado deliberado que te vas a encontrar, y que NO debes "arreglar":**

- `act/server_cloudrun.py` lleva cableada una lista negra (`PROYECTOS_PROHIBIDOS`, `AGENTES_PROHIBIDOS`) que rechaza Petal con `403`. **Es intencionado. No la retires.** El panel debe entender ese 403 y explicarlo, no esquivarlo.
- El registro de Petal en Firestore está apartado a propósito, con respaldo. Por eso `Contexto('floristeria-petal-digital', ...)` muere con `MappingNotFound`. **Es la barrera funcionando. No lo recrees.**
- El entorno local (gcloud y credenciales ADC) ya apunta a `cloud-run-multiproyecto`. Aun así, pasa `--project cloud-run-multiproyecto` explícito en toda orden `gcloud` y `FIRESTORE_PROJECT=cloud-run-multiproyecto` en todo script: defensa en profundidad, no redundancia.
- Un error que nombre `floristeria-petal-digital` es una señal de parada, no un problema que resolver. Nunca habilites una API ni añadas un binding de IAM en ese proyecto para que un error desaparezca.

---

## 3. Punto de retorno

El commit `5644240` (HEAD de `build/intento-2` al escribir este encargo) es el punto exacto al que volver si algo sale mal. Reconfírmalo con `git rev-parse --short HEAD` antes de empezar, por si han caído más commits.

---

## 4. Planifica antes de construir

**Antes de escribir una línea de código, produce y deja escrito un plan de las dos fases.** No es burocracia: el panel tiene ~2.300 líneas con lógica de simulación repartida, y las dos fases tocan cuatro archivos distintos. Un plan escrito es lo que hace que no se te olvide una función de simulación en un rincón.

El plan debe incluir, como mínimo:

- **Inventario de la simulación**: la lista completa de funciones, `setTimeout` y arrays de datos falsos del panel, con su línea, y con qué endpoint real sustituye a cada uno. Sácalo leyendo el archivo entero, no de memoria ni de un ejemplo.
- **Mapa de las 9 puertas**: qué elemento del panel dispara cada uno de los 9 endpoints. Ninguno puede quedar sin consumidor y ningún elemento puede quedar simulado.
- **Qué se rompe y cómo lo notarías**: por cada pieza, qué aspecto tendría un fallo silencioso. Esto alimenta el §6.
- **El orden de trabajo**, y qué dejas para el final.

Guárdalo en `docs/plan_fase7_8.md`. Es un entregable, no una nota.

---

## 5. Qué construir

### 5.1 Trabajo pendiente del servidor — esta tarea lo incluye

El servidor se construyó **antes** de la decisión §16 (S25), así que le falta la parte que esa decisión exige:

- **El servidor no sabe servir archivos** (cero `send_from_directory`/`static_folder`). Tiene que servir el panel de producción desde su mismo origen.
- **El `Dockerfile` solo copia `act/`.** Tiene que copiar también el panel.

**El panel se queda en `docs/panels/` — no lo muevas.** Esa es su carpeta y el repositorio no se reorganiza para esto. Lo que cambia es una línea del `Dockerfile` que copia ese archivo dentro de la imagen: el original sigue donde está.

**Por qué esto importa más de lo que parece:** si el panel se sirve desde el mismo origen que la API, desaparecen dos problemas en vez de gestionarse — el panel llama a rutas relativas (`/step/1`, sin URL que configurar) y CORS deja de existir. Si en algún momento te ves configurando una URL absoluta o peleando con CORS, es señal de que te has salido de esta decisión.

### 5.2 Fase 7 — el panel conectado

Sigue las reglas de la Fase 7 en el playbook. Output: `docs/panels/act_cx_resources_deploy_v2_output_cloudrun.html`. El original **no se toca**: es la referencia.

Los 9 endpoints que el panel consume (contrato ya construido, no lo cambies sin motivo):

| Endpoint | Quién lo dispara en el panel |
|---|---|
| `POST /step/1` … `/step/5` | El botón de acción de cada paso |
| `GET /discover` | Los selectores de proyecto y agente del Paso 1 |
| `POST /register-agent` | El botón de dar de alta un agente (Paso 1) |
| `POST /link-project-repo` | La Tool «Vincular proyecto y repositorio» (barra lateral) |
| `POST /manage-versions` | El desplegable «Ver versiones existentes» (Paso 5), listar y borrar |

Todos devuelven `{status, log, data}`. Hay además un `GET /health` que no recibe destino y no toca nada — úsalo si te sirve para saber si el servidor responde antes de intentar un paso.

### 5.3 Fase 8 — validación, lo más automatizada posible

El playbook describe la Fase 8 como análisis estático del código fuente. **Eso ya no basta y se amplía a propósito:** un `grep` confirma que el código llama al servidor, pero no que la pantalla funcione — un botón que no responde, un aviso que no aparece o un estado que se queda colgado no los caza ningún análisis de texto.

**Automatiza todo lo que se pueda automatizar**, incluido conducir el panel en un navegador de verdad. En este entorno tienes herramientas de navegador disponibles (`mcp__Claude_Browser__*`; si aparecen como diferidas, cárgalas con `ToolSearch` en una sola llamada). Con ellas puedes abrir el panel, pulsar botones, leer lo que aparece en pantalla y comprobar el estado real — no lo que el código promete.

Output: `act/validate_html_cloudrun.py` y el catálogo de TCs que pide el playbook.

---

## 6. Validación — exhaustiva, no solo el camino feliz

Construye y ejecuta una lista **exhaustiva** de comprobaciones. Como mínimo:

**Camino feliz completo**, con el panel de verdad, en un navegador, contra tu agente desechable: recorrer los 5 pasos de principio a fin hasta publicar, y comprobar leyendo el resultado real (CX y GitHub) que pasó lo que el panel dice que pasó.

**Casos límite y de error** — al menos:
- El servidor no responde: mensaje claro que diga a qué dirección llamó, nunca un estado colgado ni un éxito falso.
- El servidor responde error (400, 403, 404, 409, 500): cada uno con su mensaje propio, ninguno como error genérico.
- **El 403 de Petal**: elegir Petal en el selector devuelve 403 por la lista negra. El panel debe explicarlo como destino bloqueado a propósito, no como avería.
- Doble clic en un botón de acción: una sola petición, no dos.
- Recargar la página (F5) a mitad de un paso: el estado se recupera de `localStorage`.
- Cerrar y reabrir la pestaña: igual.
- Una respuesta vacía o sin los campos esperados: el panel no debe romperse en silencio.
- El desplegable de versiones: listar, marcar, y que las que un entorno sirve no se dejen marcar. Y que la confirmación previa al borrado siga ahí.
- Los dos avisos de límite de versiones (`contenedores_cerca_del_limite` al listar, `poda_pendiente` al publicar) se pintan cuando llegan y se ocultan cuando no.
- Los gates de los Pasos 3 y 5 muestran el proyecto y el agente reales, no un ejemplo fijo.

**Áreas oscuras — búscalas activamente.** Una función del panel que no dispare ninguna petición; un endpoint sin nadie que lo llame; una rama de código a la que no llegue ninguna prueba; un dato que el servidor devuelve y el panel tira sin mostrar. Enumera lo que encuentres aunque no sepas arreglarlo.

**Errores en silencio — el peor fallo posible.** Un `fetch` cuyo error se traga un `catch` vacío; un `status` de error que se pinta como éxito; un campo que llega `undefined` y se muestra como texto vacío en vez de avisar. Búscalos a propósito.

---

## 7. Adversarial — no te fíes de tus propias pruebas

**Una prueba que nunca ha fallado no ha demostrado nada.** Antes de dar la validación por buena, rómpela a propósito:

- **Inyecta averías, una a una**, en el panel y en el servidor: quita un `fetch`, cambia un endpoint por otro, haz que un botón no dispare nada, devuelve un `status` de error como si fuera éxito, borra el manejo de un error. **Cada avería tiene que salir en rojo.** La que no salga señala una prueba que pasa sin comprobar nada.
- Deja escrito cuántas averías inyectaste, cuáles cazó cada prueba, y qué corregiste.

Este ejercicio ya se hizo en la Fase 6 y encontró **3 pruebas que pasaban sin probar nada** — una daba por terminada una operación que ni siquiera había empezado. No es un trámite: es lo que separa una suite en verde de una suite que sirve.

**Revisa además tu propio trabajo con ojo adversarial** al terminar: ¿qué has dado por bueno sin comprobar? ¿qué comprobaste una sola vez y podría ser casualidad? ¿qué prueba pasa por el motivo equivocado?

---

## 8. Limpieza — obligatoria, verificada, no solo intentada

Pase lo que pase, al terminar:

1. Borra el agente CX que creaste. Confírmalo con un `GET` → 404.
2. Borra las ramas de GitHub que creaste. Confírmalo con `git ls-remote`.
3. Borra los documentos de Firestore que tu tarea creó. Confírmalo leyendo después.
4. Borra los servicios de Cloud Run y las imágenes que despliegues. Confírmalo listando.

No dejes esto para "si sobra tiempo". Y no toques nada preexistente que no hayas creado tú.

---

## 9. El login va al final — no lo actives

La decisión §16 (S25) dice que el acceso al servidor lo controla IAP, el login de Google. **No lo actives en esta tarea.** Si estuviera puesto, tus pruebas automáticas de navegador se encontrarían una pantalla de login que no pueden pasar, y perderías justo la validación que se te está pidiendo.

Activarlo es el último paso, después de esta tarea y del recorrido manual de Jero. Además es un cambio de IAM, o sea un gate: no es tuyo.

Mientras tanto el riesgo está acotado: el servicio no tiene dirección conocida por nadie más y Petal sigue bloqueado por la lista negra.

---

## 10. Lo que NO haces: el recorrido manual de Jero

La Fase 8 termina con un recorrido manual contra Petal —crear un playbook ficticio, publicarlo, retirarlo— que **por regla del proyecto lo hace Jero en persona, no un agente**. Cada clic suyo es la aprobación explícita que el proyecto exige.

**No lo intentes.** Tu trabajo es dejarlo preparado: construye todo, automatiza todo lo automatizable, y para ahí.

---

## 11. Al terminar — las indicaciones para apuntar a Petal

Además del resumen, deja escrito en `docs/paso_a_petal.md` **la lista ordenada y concreta de todo lo que hay que hacer para que este sistema pase a desplegar Petal de verdad**. Es lo último que falta del proyecto y nadie lo tiene escrito de corrido.

Sale de cosas que ya están identificadas por el camino — enuméralas con el detalle suficiente para ejecutarlas sin volver a investigarlas, y en el orden correcto. Debe cubrir al menos:

- **Los permisos que faltan.** `act-cloudrun-sa@cloud-run-multiproyecto.iam.gserviceaccount.com` no tiene hoy **ningún rol a nivel de proyecto** (solo `secretmanager.secretAccessor` sobre un secreto). Necesita al menos leer y escribir Firestore en `cloud-run-multiproyecto`, y administrar Dialogflow más consumir cuota en el proyecto de Petal. Averigua los roles exactos y deja el comando `gcloud` listo para copiar y pegar — Jero lo ejecuta, tú no.
- **La lista negra de Petal** cableada en `act/server_cloudrun.py`: qué líneas exactas hay que retirar y qué protección se pierde al hacerlo.
- **El registro de Petal en Firestore**, hoy apartado con respaldo: cómo devolverlo.
- **La rama principal del proyecto de Petal**, hoy `pruebas/principal-desechable`: cuándo y cómo pasarla a `main`, y qué implica.
- **Activar IAP** y autorizar las cuentas.
- **El recorrido manual de Jero**, con sus pasos.

Ordénalo por dependencias: qué va antes de qué, y qué se puede comprobar después de cada paso para saber que fue bien.

---

## 12. El gate humano — tu autocrítica no lo sustituye

Cuando termines, preséntalo como **"construido, autoprobado, listo para revisión"** — nunca como "ya validado" o "ya es seguro", aunque toda tu suite esté en verde.

Motivo concreto, no hipotético: la noche del 2026-08-09 al 10, el pipeline de las Fases 1-4 llegó ya "construido y probado" por una sesión anterior, y una revisión fresca encontró 2 fallos reales de seguridad —un candado que se podía saltar del todo y una condición de carrera al borrar versiones— que la autocrítica original no había visto. Que tu suite esté en verde es la condición para pedir la revisión, no para saltártela.

**Resume al terminar:** qué construiste, el plan del §4, el resultado completo de la validación (qué se probó y cómo, no solo "todo pasó"), el ejercicio adversarial del §7 con sus números, las áreas oscuras que encontraste, y la confirmación punto por punto de la limpieza del §8. Si algo se desvía de este documento, dilo explícitamente en vez de improvisar en silencio.
