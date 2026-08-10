# Plan de las Fases 7 y 8 — el panel conectado y su validación

**Fecha:** 2026-08-10 · **Rama:** `build/intento-2` · **Punto de retorno:** `5d63ff4`

Escrito **antes** de tocar código, como exige el §4 del encargo
(`docs/handoff_fase7_8_panel.md`). El panel de referencia tiene 2.310 líneas y la
lógica de simulación está repartida por todo el archivo: sin este inventario
escrito, una función de simulación en un rincón sobrevive a la conversión y ese
paso sigue mintiendo.

---

## 0. Las cuatro decisiones de partida

**D1 · Mismo origen, rutas relativas.** El panel llama a `/step/1`, no a una URL
absoluta. Lo decide §16 (S25) de `docs/cloudrun_diseno_servidor.md`, que es
posterior a la regla del playbook que pedía «una constante configurable con la
URL de Cloud Run por defecto». Consecuencias: **no hay constante de URL**, **no
hay parámetro de sobreescritura** y **no hay CORS que configurar**. El mensaje de
error sí sigue diciendo a qué dirección llamó — se resuelve con
`new URL('/step/1', location.href).href`, que es la dirección real y absoluta.

*Por qué no se deja una sobreescritura «solo para desarrollo»:* un parámetro que
redirige todas las peticiones del panel a un host arbitrario es un vector abierto
—basta un enlace preparado— y la única prueba que justificaba tenerlo (servidor
caído) se hace mejor apagando el servidor de verdad, que es lo que se va a hacer.

**D2 · El panel se queda en `docs/panels/`.** El `Dockerfile` lo copia dentro de
la imagen; el original no se mueve (§5.1 del encargo).

**D3 · CORS se queda como está en el servidor.** `flask_cors` y `ALLOWED_ORIGIN`
dejan de hacer falta para el panel, pero el smoke test de la Fase 6
(`act/validate_server_cloudrun.py:478,791`) los comprueba. Quitarlos rompería una
suite que hoy está en verde a cambio de nada.

**D4 · El estado del pipeline vive en `localStorage`, con clave propia
(`act_panel_cloudrun_v1`).** Incluye una marca de «paso en curso» que sobrevive a
la recarga: si la página se recarga a mitad de una llamada, al volver **avisa de
que esa operación pudo terminar en el servidor**, en vez de fingir que no pasó
nada.

---

## 1. Inventario de la simulación

Sacado leyendo `docs/panels/act_cx_resources_deploy_v2.html` entero. Las líneas
son las del archivo original.

### 1.1 Datos falsos escritos en el HTML (no en el JS)

| Línea | Qué es | Con qué se sustituye |
|---|---|---|
| 199 | `topbar-agent` = «Petal 1.0» | `displayName` del agente elegido (`/discover`) |
| 202 | `GitHub: staging · 98fcbdd` | `data.repo` / `data.rama` / `data.commit` del Paso 1 |
| 204 | «Último deploy: hace 3 días» | se retira: no hay endpoint que lo dé |
| 249-250 | `<option>` fijo `floristeria-petal-digital` | `GET /discover` |
| 256-258 | `<option>` fijos `petal-1.0`, `petal-voz` | `GET /discover?project=…` |
| 283-319 | Las 4 tarjetas del inventario con números y listas fijos (42/4/2/2) | `data.emparejados`, `data.solo_cx`, `data.solo_repo`, `data.sin_agente` del `POST /step/1` |
| 325 | «48 resources · leídos de staging · commit 98fcbdd» | contadores reales del Paso 1 |
| 348, 355-358 | Tabla `tabla-repo` con 4 filas fijas | `data.solo_cx` del Paso 1 (con `traible`/`nativo`) |
| 380 | «Repositorio: jeronimosanchez/cx-automation-template · Rama: staging» | `data.repo` / `data.rama` |
| 411 | «4 resources en CX sin respaldo» | contador real |
| 436-440 | Tabla `tabla-cx` con 5 filas fijas | `data.operaciones` del `POST /step/3` con `dry_run:true` |
| 455 | `gate4-project` = `floristeria-petal-digital` fijo | proyecto elegido |
| 531 | Enlace al agente de Petal 1.0 cableado | URL construida con proyecto/región/agente reales |
| 573 | Gate del Paso 5: proyecto y agente fijos | proyecto y agente elegidos |
| 576 | «`staging` se fusiona en `main`» | `rama` → `rama_principal` reales |
| 611 | `done-timestamp` de ejemplo | hora real de la publicación |
| 655, 659 | Ruta y comando de sincronización con el repo cableado | `data.repo` real |
| 712 | Comando IAM con `<proyecto>` de ejemplo | `data.comando_iam` de `POST /link-project-repo` |
| 749-1132 | `<aside class="specs-panel">` completo | **se elimina** (regla de la Fase 7) |

### 1.2 Constantes y arrays de datos falsos en el JS

| Línea | Símbolo | Qué simula | Sustituto |
|---|---|---|---|
| 1137 | `DIFF_COUNT = 4` | si hay cambios que aplicar | `data.operaciones.length` del dry-run |
| 1138 | `TEST_COUNT = 42` | nada — muerto | se elimina |
| 1139 | `DEPLOY_SIMULATE_FAIL` | fallo del Paso 3 | `result` real por operación |
| 1140 | `PRODUCTION_SIMULATE_CONFLICT` | conflicto de merge | `status:"conflict"` del Paso 5 |
| 1185-1195 | `INV_LINES` (9 líneas de log) | el log del Paso 1 | `data.log` real |
| 1212-1214 | `REPOS_POR_PROYECTO` | mapeo proyecto→repo | `/discover` (`data.repo`) |
| 1219-1222 | `RAMAS_POR_AGENTE` | rama de cada agente | `/discover` (`agente.rama`) |
| 1226-1228 | `RAMA_PROPUESTA_POR_AGENTE` | rama que se propondría | `/discover` (`agente.rama_propuesta`) |
| 1232-1235 | `REGION_POR_AGENTE` | región | `/discover` (`agente.region`) |
| 1240-1243 | `TIENE_ENTORNO_PRODUCCION_POR_AGENTE` | aviso de entorno | `data.tiene_entorno_produccion` del Paso 1 |
| 1247-1250 | `URL_CONSOLA_CX`, `URL_AGENTE` | enlace a la consola | se construye con proyecto/región/agente |
| 1617-1625 | `SIMULAR_DRAFT_MOVIDO`, `huellaDraft()` | el gate del borrador movido | lo decide el servidor (`status:"aborted"`) |
| 1653-1659 | `DEPLOY_RESOURCES` | qué fila «falla» | `operacion.result` real |
| 1841 | `VERSION_PREFIX` | nada — muerto | se elimina |
| 1843-1848 | `VERSIONES` (4 versiones falsas) | listado de versiones | `POST /manage-versions` (`list`) |
| 1854-1857 | `CONTENEDORES_CERCA_DEL_LIMITE` | aviso de límite | `data.contenedores_cerca_del_limite` |
| 1862-1864 | `PODA_PENDIENTE` | aviso de poda | `data.poda_pendiente` del Paso 5 |
| 1975-1978 | `TOOL_ONBOARDING_LOG_LINES` | log de vincular | `data.log` de `POST /link-project-repo` |
| 2237-2242 | `ESTADO_INICIAL` (HTML de partida de las tablas) | reinicio de la maqueta | las tablas se re-renderizan desde los datos |

### 1.3 Funciones con `setTimeout` que fingen trabajo

| Línea | Función | Qué finge | Endpoint real |
|---|---|---|---|
| 1303-1340 | `darDeAltaAgente()` | 2 líneas de log y marca la rama como creada | `POST /register-agent` |
| 1342-1374 | `startInventory()` | recorre `INV_LINES` a 400 ms | `POST /step/1` |
| 1485-1518 | `traerAlRepo()` | inventa un commit `4a91c02` | `POST /step/2` |
| 1707-1767 | `confirmDeploy()` | aplica fila a fila con `DEPLOY_RESOURCES` | `POST /step/3` |
| 1778-1810 | `retryFailed()` | reintenta y **siempre sale bien** | `POST /step/3` con `only_pending` |
| 1988-2017 | `ejecutarToolOnboarding()` | 2 líneas de log | `POST /link-project-repo` |
| 2096-2146 | `confirmProduction()` | 7 líneas de log de merge + versión + entorno | `POST /step/5` |
| 2198-2209 | `completeAuto(idx)` | avanza pasos solos a los 800 ms | se elimina: ningún paso avanza sin respuesta |
| 1548-1606 | `toggleVersiones` / `renderVersionPool` / `borrarVersiones` | listado y borrado en memoria | `POST /manage-versions` (`list` y `delete`) |
| 1627-1630 | `validarTests()` | no llama a nadie | `POST /step/4` (`superados`) |
| 1632-1635 | `marcarTestsFallidos()` | no llama a nadie | `POST /step/4` (`fallidos`) |

Los `setTimeout` que **se quedan** son los que no simulan trabajo: los 1.500 ms
del «Copiado» del botón de copiar (1985, 2086).

### 1.4 Código muerto que arrastra el original (áreas oscuras del §6)

Se documentan porque son exactamente lo que el §6 pide buscar: código al que no
llega ninguna prueba.

- `resetVersionUI()` (2211) manipula `snap-gate`, `snap-log`, `snap-done`, que
  **no existen** en el HTML. Nadie la llama. → se elimina.
- `cancelDeploy(true)` (2219) llama a `showRollbackConfirm()`, **que no está
  definida**. Solo se invoca con `false` desde la línea 463. → se simplifica.
- `abortProduction()` (2148) toca `#prod-conflict`, que **no existe** en el HTML.
  Nadie la llama. → se elimina; el conflicto de merge se pinta con el bloque de
  error general.
- `renderStep3Diff()` (1644) decide con `DIFF_COUNT`, una constante. → pasa a
  decidir con el número real de operaciones.
- `toggleGrupo()` (1386) sustituye `▴`/`▾` dentro de `innerHTML`; con listas
  generadas se rehace como render por estado.
- `viewTool()` (1957) resetea a mano los tres `div` del onboarding: si mañana hay
  una Tool más, deja de valer. → se generaliza.

---

## 2. Mapa de las 9 puertas

Ningún endpoint sin consumidor, ningún elemento del panel simulado.

| # | Endpoint | Quién lo dispara | Cuerpo / parámetros | Qué pinta la respuesta |
|---|---|---|---|---|
| 1 | `GET /health` | Al cargar la página y antes de cada paso que escribe | — | Un aviso de «no hay servidor» antes de que el usuario pulse nada |
| 2 | `GET /discover` | Carga inicial del Paso 1 | — | Opciones del selector de proyecto |
| 3 | `GET /discover?project=` | `onProjectSelected()` | `project` | Opciones de agente · repo del proyecto · rama y `rama_propuesta` de cada agente · aviso «proyecto sin repositorio» |
| 4 | `POST /register-agent` | Botón «Dar de alta este agente» (Paso 1) | `project`, `agent`, `region`, `rama` | Región y rama creadas; refresca el descubrimiento |
| 5 | `POST /link-project-repo` | Botón «Vincular» de la Tool | `project`, `repo_url`, `rama_principal` | Log real + `comando_iam` real en el bloque de copiar |
| 6 | `POST /step/1` | Botón «Iniciar inventario» | `project`, `agent` | Las 4 tarjetas, los contadores, repo/rama/commit, aviso de entorno de producción |
| 7 | `POST /step/2` | Botón «Traer al repositorio» | `project`, `agent`, `traer:[{tipo,cx_id}]` | Archivos escritos y commit reales; las filas traídas desaparecen |
| 8 | `POST /step/3` (dry-run) | Al entrar en el Paso 3 | `+ dry_run:true`, `eliminar:[…]` | La tabla de operaciones (crear/modificar/eliminar), conflictos, avisos de cambio de archivo, tipos sin versión |
| 9 | `POST /step/3` (real) | Botón «Aplicar en CX» | `+ aplicar:[{tipo,cx_id,ruta}]`, `eliminar:[…]` | `result` por operación; parcial → reintento con `only_pending` |
| 10 | `POST /step/4` | «Tests superados» / «Tests fallidos» | `resultado` | Registro de la declaración y huella del borrador |
| 11 | `POST /step/5` | Botón «Publicar en producción» | `version_label` | Merge, versiones creadas, entorno apuntado, `poda_pendiente` |
| 12 | `POST /manage-versions` | Desplegable «Ver versiones existentes» | `action:"list"` | Lista, marca de `en_uso`, `contenedores_cerca_del_limite` |
| 13 | `POST /manage-versions` | «Eliminar versiones marcadas» | `action:"delete"`, `version_names` | `borradas` y `protegidas` |

Son 9 rutas distintas (los pasos 8-9 y 12-13 comparten ruta) y **13 disparadores
distintos en el panel**. Ninguna ruta se queda sin consumidor.

### 2.1 Rutas nuevas del servidor (Fase 5 pendiente, §5.1 del encargo)

| Ruta | Qué hace |
|---|---|
| `GET /` | Redirige a `/panel` |
| `GET /panel` | Sirve `act_cx_resources_deploy_v2_output_cloudrun.html` con `Cache-Control: no-store` |

`no-store` porque el panel cambia con cada despliegue de la imagen y un panel
cacheado contra un servidor nuevo es exactamente el fallo que nadie relaciona con
la caché.

---

## 3. Qué se rompe y cómo lo notaría — los fallos silenciosos

Por pieza, qué aspecto tendría el fallo si nadie lo mira. Esto alimenta las
pruebas del §6 y las averías inyectadas del §7.

| Pieza | Fallo silencioso posible | Cómo se caza |
|---|---|---|
| **`status` de error con HTTP 200** | El Paso 3 devuelve `{"status":"error"}` con **HTTP 200** (`server_cloudrun.py:322` envuelve el resultado del pipeline tal cual). Un panel que mire solo `response.ok` pinta un deploy parcial como éxito | Comprobar `cuerpo.status` **siempre**, no `response.ok`. Prueba dedicada con un fallo real de operación |
| **`status:"aborted"` del Paso 5** | Igual: HTTP 200 con `aborted` cuando el gate del Paso 4 no pasa. Pintarlo como éxito diría «publicado» sin haber publicado | Prueba: publicar sin declarar tests → tiene que salir bloqueado |
| **`catch` vacío** | Un `fetch` que falla y no pinta nada deja el botón girando para siempre | Regla: un solo helper `llamar()` con `try/catch` que **siempre** escribe en pantalla; el validador estático prohíbe `catch {}` vacíos |
| **Campo ausente** | `data.commit` `undefined` se pinta como texto vacío y parece un commit sin nombre | Los renderizadores usan un valor de respaldo visible (`—`) y el validador comprueba que no se concatena `undefined` |
| **Doble clic** | Dos `POST /step/3` en paralelo: el segundo choca con el candado (409) o aplica dos veces | Botón deshabilitado en el mismo gesto + bandera global `peticionEnCurso` |
| **Recarga a mitad** | El paso queda «en progreso» para siempre, o peor: vuelve a «pendiente» y se repite una escritura ya hecha | Marca `en_curso` en `localStorage` + aviso explícito al volver |
| **Petal en el selector** | El 403 se pinta como error genérico y parece que el panel está roto | Rama propia por `data.reason === 'destino_protegido'` |
| **Avisos de límite** | `contenedores_cerca_del_limite` y `poda_pendiente` llegan y no se pintan: nadie se entera hasta que la API rechaza la siguiente versión | Prueba con los dos casos, presente y ausente |
| **Versiones en uso** | Una casilla marcable sobre una versión que sirve producción → borrado que el servidor rechaza y el panel da por hecho | `en_uso` deshabilita la casilla; el resumen cuenta `protegidas` |
| **Gates 3 y 5** | Muestran un proyecto de ejemplo y se confirma un destino que no es | Se leen del estado, y una prueba compara el texto del gate con el destino elegido |
| **Servidor caído** | «Cargando…» eterno | Mensaje con la dirección exacta a la que se llamó |

---

## 4. Orden de trabajo

1. **Servidor + Dockerfile** (§5.1). Es lo que hace que el panel se pueda abrir
   desde el mismo origen: sin esto no hay nada que probar en un navegador.
2. **Panel conectado** (Fase 7) — `docs/panels/act_cx_resources_deploy_v2_output_cloudrun.html`.
   Por bloques: base y helpers de red → Paso 1 y descubrimiento → alta de agente
   → Tool → Paso 2 → Paso 3 → Paso 4 → Paso 5 → versiones → persistencia.
3. **Destino desechable propio**: agente CX nuevo en `cloud-run-multiproyecto`,
   ramas nuevas en un repositorio de pruebas, documentos de Firestore nuevos.
   Nada reutilizado (§2 del encargo).
4. **`act/validate_html_cloudrun.py`** (Fase 8) — estático **y** de navegador.
5. **Catálogo de TCs** — `docs/data/tc_deploy_pipeline_cloudrun.yaml`.
6. **Recorrido completo en navegador** contra el contenedor local, los 5 pasos
   hasta publicar, comprobando el resultado en CX y en GitHub.
7. **Casos límite y de error** (§6).
8. **Adversarial** (§7): inyectar averías una a una y comprobar que cada una sale
   en rojo.
9. **Limpieza verificada** (§8) y **`docs/paso_a_petal.md`** (§11).

**Lo que se deja para el final, a propósito:** el despliegue a Cloud Run real.

**Decisión al cerrar la tarea: no se despliega, y queda escrito por qué.** Un
despliegue hoy no probaría lo que un despliegue tiene que probar. Con la cuenta
de servicio real (`act-cloudrun-sa`) el servicio arranca y muere en la primera
llamada, porque **no tiene ningún rol de proyecto** —conceder esos roles es un
gate que no es mío—; y con la cuenta por defecto de Compute, que sí tiene
`roles/editor`, funcionaría por tener una identidad **distinta de la real**, que
es la forma más cara de dar confianza falsa: el motivo por el que el nivel de
Cloud Run existe en la Fase 6 es precisamente descubrir un problema de IAM antes
de que ocurra en el primer despliegue real.

Lo que sí se probó, y cubre lo demás: **la imagen construida y corriendo en un
contenedor**, sirviendo el panel en `/panel` byte a byte igual que el archivo del
repositorio, con `/` redirigiendo y las doce rutas en `/health`.

El despliegue queda en `docs/paso_a_petal.md §2`, con el comando completo y sus
comprobaciones, detrás del paso de permisos del que depende.

**Lo que no se hace, por regla:** el recorrido manual contra Petal (§10 del
encargo) y activar IAP (§9).

---

## 5. Adversarial — el resultado (§7 del encargo)

Escrito **después** de construir. Una prueba que nunca ha fallado no ha
demostrado nada, así que se rompieron el panel y el servidor a propósito, una
avería cada vez, corriendo `act/validate_html_cloudrun.py` con el defecto dentro
y restaurando el archivo después.

**19 averías inyectadas · 19 cazadas · 0 sin cazar.** Los archivos se restauraron
byte a byte, comprobado con `sha256` antes y después de cada tanda.

| # | Avería inyectada | Quién la cazó |
|---|---|---|
| 1 | El Paso 1 deja de llamar al servidor | N0 (rutas sin consumidor) + 6 escenarios de N3 |
| 2 | El Paso 2 llama al endpoint del Paso 1 | N0 + N3 (doble clic, Paso 2) |
| 3 | El botón «Aplicar en CX» no dispara nada | N3 (deploy parcial) |
| 4 | El Paso 3 da por bueno un `status` de error | N3 (deploy parcial) |
| 5 | `catch` vacío en el Paso 1 | N3 (4 escenarios de error) |
| 6 | Se retira la guarda del doble clic | N0 + N3 (doble clic) |
| 7 | El estado deja de guardarse en `localStorage` | N3 (recarga) |
| 8 | El aviso de poda pendiente deja de pintarse | N3 (publicar con poda) |
| 9 | Las versiones en uso se dejan marcar | N3 (desplegable de versiones) |
| 10 | El gate del Paso 3 vuelve a un proyecto de ejemplo | N3 (gates) |
| 11 | El mensaje de «no conecta» pierde la dirección | N0 — **y N3 solo tras reforzarlo** |
| 12 | El Paso 5 trata `aborted` como publicación buena | N3 (aborted + conflict) |
| 13 | El aviso de límite se enciende siempre | N3 (sin contenedores cerca) |
| 14 | El servidor deja de servir el panel | N1 + 5 checks de N2 |
| 15 | El `Dockerfile` deja de copiar el panel | N1 |
| 16 | Vuelve un `<option>` de proyecto escrito en el HTML | N0 (selectores + literales reales) |
| 17 | Una llamada vuelve a `http://localhost:8080/...` | N0 (URL a fuego) |
| 18 | Vuelve el array de log simulado del Paso 1 | N0 (simulación residual) |
| 19 | Repetición de la 11 tras reforzar N3 | N0 **y** N3 |

### Lo que el ejercicio corrigió

**Una prueba que pasaba por el motivo equivocado, en el propio arnés.** El
escenario del 403 de Petal declaraba una respuesta para
`/discover?project=floristeria-petal-digital`, pero el servidor de mentira
resolvía las rutas por *la primera que encajara* y `/discover?project=` la
tapaba: el escenario estaba ejecutando el camino feliz y dándolo por bueno. Se
corrigió haciendo que gane la ruta **más específica**. Es exactamente el fallo
que la Fase 6 encontró tres veces, ahora en el arnés en vez de en el producto.

**Una comprobación que se apoyaba en el sitio equivocado.** La avería 11 —quitar
la dirección del mensaje de red— la cazaba el análisis estático pero **no** el
escenario de navegador: éste leía la caja de error entera, y la dirección
aparecía igualmente en el pie. Se reforzó para leer solo el párrafo del mensaje.
Repetida la avería, ahora la cazan los dos niveles.

**Lo que sigue siendo débil, dicho en voz alta.** La comprobación estática
«cada respuesta se juzga por el `status` del sobre» cuenta cuántos sitios lo
miran y exige un mínimo: la avería 4 —quitar **una** de esas comprobaciones— la
cazó el escenario de navegador, no el recuento. Un umbral no distingue seis de
siete. Se deja así a propósito: la comprobación de verdad es la de
comportamiento, y el recuento solo existe para que un panel que no mirara el
sobre en ningún sitio no llegue ni a arrancar el nivel 3.

**Cuatro comprobaciones que fallaban por su propia redacción, no por el panel**
(encontradas al estrenarlas): buscaban `<option value="…">` en el archivo entero
—y encontraban las plantillas que el JS usa para rellenar el desplegable—,
buscaban `width:420px` —que también es el ancho de los formularios de la Tool—,
buscaban `operaciones:` dentro de un comentario que explicaba esa misma regla, y
daban por buena una salida a `console.error`. Las cuatro se reescribieron para
mirar el sitio correcto; la de `console.error` se endureció: el registro del
navegador no lo mira nadie mientras despliega, así que no cuenta como que el
error salió a algún sitio.
