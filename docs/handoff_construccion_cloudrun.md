# Handoff — construcción del pipeline ACT en Cloud Run

**Para quién es este documento:** una sesión nueva de Opus, sin memoria de las sesiones anteriores, que va a ejecutar la construcción real del pipeline de deploy en Cloud Run. No has visto nada de lo que llevó a este punto — este documento te da el contexto mínimo necesario para empezar bien, sin adivinar nada.

**Estado:** listo para ejecutar. La metodología está terminada y revisada a fondo (ver §5). No existe todavía ninguna línea de código del pipeline Cloud Run — solo el plan de cómo construirlo.

---

## 1. Qué es este proyecto

`cx-automation-template` es el repo de la línea **ACT** del sistema de Automatización CD de Jero. Automatiza el despliegue de artefactos al agente conversacional **Petal** (una floristería online, en español) en Dialogflow CX.

Lee **`CLAUDE.md`** completo antes de tocar nada — tiene las decisiones técnicas no negociables, el mapa de dependencias, los constraints de IAM/producción/templates, y el protocolo de arranque de sesión. Todo lo que digas o construyas tiene que respetarlo.

## 2. Qué existe hoy y qué vas a construir

Existe un pipeline de deploy que corre **en local**, en el Mac de Jero: `act/act_cx_resources_deploy.py` + `act/server.py` + un panel HTML, con 8 pasos. **Ese pipeline sigue siendo el único camino real a producción — no lo toques, no lo importes, no lo modifiques.** Sigue siendo la referencia de patrones que ya funcionan (idempotencia, capas, polling de operaciones), pero el que vas a construir es una implementación nueva y separada, que no depende de él en tiempo de ejecución.

Vas a construir un **segundo pipeline**, agnóstico de proyecto y agente, pensado para correr como servicio en **Cloud Run**: lee un repositorio de GitHub, lo compara con un agente real de Dialogflow CX, y aplica solo lo que cambió — en **5 pasos**, no 8: Inventario, Traer al repositorio, Aplicar en CX, Validar tests, Publicar en producción.

## 3. Dónde está el plan de construcción — tu fuente de verdad

**`docs/panels/act_build_playbook_v2_cloudrun.html`** — ábrelo en un navegador o léelo como HTML/JS. Es un documento interactivo con 8 fases (Goal, Discovery, construir el pipeline, validarlo, construir el servidor, validarlo, conectar el panel HTML real, validarlo de extremo a extremo). Cada fase tiene:
- `objetivo` — qué construye esa fase y por qué.
- `reglas` — lo que hay que saber para construirla bien, incluidos gotchas no obvios.
- `leer` — qué archivos hay que estudiar antes de escribir código.
- `outputs` — los archivos concretos que la fase entrega.
- Criterios de validación — cómo se comprueba que la fase quedó bien hecha, organizados en niveles de riesgo creciente.

Este documento es el resultado de una revisión muy exhaustiva — se construyó fase por fase, y luego se sometió a una ronda final de revisión adversarial con varias perspectivas independientes (contrato HTML↔backend, consistencia entre fases, suficiencia de la validación, seguridad) antes de darse por cerrado. Trátalo como la especificación real, no como una guía aproximada — si algo ahí contradice lo que tú crees que es mejor, para y pregúntalo, no lo decidas por tu cuenta.

**Si este archivo no existe todavía en el repo cuando empieces:** para y avísalo — significa que el volcado desde el artifact de Claude.ai donde se construyó no se hizo, y no puedes continuar sin él.

## 4. Cómo trabajar, fase por fase

1. Lee el Build Playbook **completo** una vez, de principio a fin, antes de tocar la Fase 1 — para tener el mapa entero en la cabeza, aunque cada fase se ejecute por separado.
2. Empieza por la Fase 1 (Goal). Escribe tu comprensión del objetivo, los constraints y la filosofía de colaboración — el propio documento te pide esto explícitamente antes de dejarte avanzar.
3. Para cada fase siguiente: lee su `objetivo`, `reglas` y `leer` primero, construye lo que pide, y antes de darla por terminada revisa tú mismo los criterios de validación de esa fase — no esperes a que Jero los revise por ti como primer filtro.
4. **Cada fase tiene un gate humano.** No avances a la siguiente fase sin que Jero confirme explícitamente que la fase actual está bien — nunca te autoapruebes. Esto no es una formalidad: es la única forma de que Jero pueda corregir un malentendido antes de que se propague a las 7 fases siguientes.
5. Si encuentras una contradicción dentro del propio Build Playbook, o entre el Build Playbook y lo que ves en el código/API real, para y pregunta — propone una resolución sencilla en lenguaje natural, con su justificación, y espera confirmación antes de construir sobre ella. No decidas tú solo cuál de las dos fuentes tiene prioridad.

## 5. Reglas no negociables a tener siempre presentes

Están todas en el Constraints de la Fase 1 del Build Playbook, con más detalle — este es solo el resumen para que no se te olvide ninguna mientras trabajas:

- **Nomenclatura:** todo archivo que crees para este pipeline lleva la palabra `cloudrun` como sufijo — nunca como prefijo, sin excepción. Si necesitas el contenido de un archivo del pipeline local, lo clonas en un archivo nuevo con el sufijo — nunca lo importas directamente.
- **Nunca escribir sobre Petal**, con una única excepción: el recorrido manual y supervisado de la Fase 8, donde Jero ejecuta cada paso en persona, usa un recurso claramente ficticio, y lo elimina por completo al terminar (incluida una segunda publicación si llegó a producción real). Toda prueba automática va siempre contra un agente y repositorio **desechables**, nunca contra Petal — ni siquiera para lecturas.
- **Región nunca fija.** Se autodetecta una sola vez al vincular un agente y queda guardada en Firestore. Ningún módulo puede asumir `europe-west1` como constante.
- **El candado de concurrencia vive en Firestore**, nunca en memoria del proceso ni se asume por la infraestructura de Cloud Run — una sola instancia de Cloud Run no rechaza peticiones concurrentes, las encola, así que sin candado explícito dos escrituras pueden solaparse.
- **Cero residuo.** Ninguna prueba puede dejar nada a medias: candados sin liberar, commits parciales, versiones huérfanas, recursos de prueba sin borrar. Está tratado con rigor especial en las fases de validación — no lo relajes al construir.
- **13 tipos de recurso**, no 12 (incluye Transition Route Groups).
- Auth hacia CX: ADC en Cloud Run (nunca `gcloud auth print-access-token`, eso es solo para el pipeline local). Verificado a nivel de API — todavía no verificado dentro de un contenedor Cloud Run real; eso lo confirma el Nivel 5 de la Fase 4.

## 6. Qué leer antes de escribir la primera línea

En este orden:
1. `CLAUDE.md` — completo.
2. `docs/panels/act_build_playbook_v2_cloudrun.html` — completo, las 8 fases.
3. `docs/cloudrun_diseno_servidor.md` — las decisiones S1 a S23 que el Build Playbook da por hechas.
4. `docs/panels/act_cx_resources_deploy_v2.html` — el panel de referencia, visual y Specs. Es la especificación de comportamiento de los 5 pasos y las Tools que vas a hacer reales.

## 7. Primer paso concreto

Confirma que has leído y entendido la Fase 1 del Build Playbook — qué se construye, por qué, los constraints, y el protocolo de colaboración — y espera el OK explícito de Jero antes de escribir ninguna línea de código.
