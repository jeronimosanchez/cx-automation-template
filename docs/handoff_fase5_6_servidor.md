# Handoff — Fase 5 y Fase 6: el servidor Cloud Run

**Para quién es este documento:** una sesión nueva (Opus), sin memoria de las sesiones anteriores, que va a construir `act/server_cloudrun.py` (Fase 5) y `act/validate_server_cloudrun.py` (Fase 6). Tienes libertad de actuación para construir, probar e iterar sin pedir permiso en cada paso — pero lee primero las reglas duras de abajo, que no son negociables.

**Estado (2026-08-10):** las Fases 1 a 4 ya existen y están probadas contra CX real — `act/act_cx_resources_deploy_cloudrun.py` y `act/validate_pipeline_cloudrun.py`. No arrancas de cero: léelos antes de escribir nada.

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

---

## 3. Infraestructura de pruebas — crea la tuya, no reutilices nada existente

Esta noche se encontraron varios restos de sesiones anteriores (agentes de prueba y un repositorio "desechable" viviendo dentro del proyecto real de Petal, sin limpiar). Para evitar ese mismo problema:

- **Crea un agente CX nuevo, propio de esta tarea**, en el proyecto `cloud-run-multiproyecto` (la API de Dialogflow ya está habilitada ahí). Región sugerida: `europe-west1`. `displayName` con la palabra "desechable" en el nombre.
- **No reutilices ningún agente ni repositorio que encuentres ya registrado** en Firestore o en GitHub, aunque parezca desechable — créalo tú, de cero, para esta tarea concreta.
- Repositorio: usa `jeronimosanchez/cx-automation-template` con una **rama nueva y propia**, nunca `main`. Nombra la rama con un prefijo identificable (`desechable/fase5-<algo>`).

---

## 4. Punto de retorno

El commit `ab99300` (HEAD de `build/intento-2` en el momento de este encargo) es el punto exacto al que se puede volver si algo sale mal. No hace falta nada más elaborado que esto: si el resultado final no es bueno, `git reset`/`git checkout` a `ab99300` deja el repo exactamente como estaba antes de empezar.

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
