# De aquí a desplegar Petal de verdad

**Qué es:** la lista ordenada y concreta de todo lo que falta para que este
sistema —panel + servidor + pipeline— pase de desplegar agentes desechables a
desplegar **Petal**. Sale de cosas identificadas por el camino durante las Fases
5 a 8; se escribe de corrido para poder ejecutarla sin volver a investigarla.

**Fecha:** 2026-08-10 · **Rama:** `build/intento-2`

**Quién ejecuta qué.** Todo lo de esta lista lo ejecuta Jero. Los comandos están
listos para copiar y pegar, con los valores reales ya dentro. Ningún agente
ejecuta nada de aquí: los pasos 1, 6 y 7 tocan IAM o producción, y los pasos 3, 4
y 5 retiran a propósito frenos que existen para que un agente no pueda llegar a
Petal por accidente.

**Datos que usa toda la lista:**

| | |
|---|---|
| Proyecto del servicio | `cloud-run-multiproyecto` (número `726296318377`) |
| Cuenta de servicio | `act-cloudrun-sa@cloud-run-multiproyecto.iam.gserviceaccount.com` |
| Proyecto de Petal | `floristeria-petal-digital` |
| Agente Petal 1.0 | `745375ba-ac7e-4eb8-b8a0-d742891f2aa4` |
| Agente Petal 1.1 | `cea66b60-192d-4b5a-af10-28f8661032e0` |
| Repositorio de Petal | `jeronimosanchez/cx-automation-template` |
| Región | `europe-west1` |

---

## Orden y dependencias

```
1 Permisos ──► 2 Desplegar ──► 3 Lista negra ──► 4 Registro ──► 5 Rama ──► 6 IAP ──► 7 Recorrido
   (IAM)        (Cloud Run)     (código)         (Firestore)     (decisión)  (IAM)     (Jero)
```

- **1 antes que 2**: un servicio desplegado sin permisos arranca, contesta
  `/health` y falla en la primera llamada que toque Firestore. Se ve como un
  fallo del panel.
- **3 antes que 4**: con la lista negra puesta, el registro de Petal en Firestore
  no sirve de nada — el servidor rechaza el destino antes de mirarlo.
- **5 es una decisión, no un paso técnico**, y puede quedarse sin hacer: el
  recorrido de la Fase 8 se hace a propósito con la rama principal desechable.
- **6 al final**, después del recorrido: IAP pone una pantalla de login delante
  del servicio, y con ella no se pueden ejecutar las pruebas automáticas de
  navegador.

---

## 1 · Los permisos que faltan

**Estado hoy, verificado el 2026-08-10:** `act-cloudrun-sa` **no tiene ningún rol
a nivel de proyecto**, ni en `cloud-run-multiproyecto` ni en
`floristeria-petal-digital`. Lo único que tiene es
`roles/secretmanager.secretAccessor` **sobre el secreto**
`github-app-private-key`, concedido en la política del propio secreto.

Con eso el servicio puede leer la clave de la GitHub App y nada más: la primera
llamada a Firestore falla con 403, y el panel lo muestra tal cual —el servidor
respeta el código que devuelve Google en vez de traducirlo a un 500 genérico,
justo para que se pueda pedir el permiso en vez de depurar a ciegas.

### 1.1 En el proyecto del servicio

```bash
# Firestore: el mapeo proyecto→repo, el candado, el log de auditoría y las
# versiones previas. Sin esto no funciona ni el Descubrimiento.
gcloud projects add-iam-policy-binding cloud-run-multiproyecto \
  --member=serviceAccount:act-cloudrun-sa@cloud-run-multiproyecto.iam.gserviceaccount.com \
  --role=roles/datastore.user
```

`roles/datastore.user` es el rol de datos de Firestore en modo nativo:
`datastore.entities.create/get/update/delete/list` — comprobado contra la
definición real del rol, no de memoria.

### 1.2 En el proyecto de Petal

```bash
# Leer y escribir el agente.
gcloud projects add-iam-policy-binding floristeria-petal-digital \
  --member=serviceAccount:act-cloudrun-sa@cloud-run-multiproyecto.iam.gserviceaccount.com \
  --role=roles/dialogflow.admin

# Cargar la cuota al proyecto correcto. Es lo que exige la cabecera
# `x-goog-user-project` que va en TODA llamada a la API de CX.
gcloud projects add-iam-policy-binding floristeria-petal-digital \
  --member=serviceAccount:act-cloudrun-sa@cloud-run-multiproyecto.iam.gserviceaccount.com \
  --role=roles/serviceusage.serviceUsageConsumer
```

**Los dos, no uno.** Verificado sobre la definición de los roles:
`roles/dialogflow.admin` **no incluye** `serviceusage.services.use`. Es el
hallazgo X1 de `docs/cloudrun_diseno_servidor.md §8.4`, y sin el segundo rol
todas las llamadas a CX salen con 403 aunque el primero esté concedido.

### 1.3 Opcional — que Petal aparezca en el desplegable

```bash
# Solo si se quiere que el proyecto de Petal salga en la lista del panel.
gcloud projects add-iam-policy-binding floristeria-petal-digital \
  --member=serviceAccount:act-cloudrun-sa@cloud-run-multiproyecto.iam.gserviceaccount.com \
  --role=roles/browser
```

*Por qué es aparte:* `roles/dialogflow.admin` da `resourcemanager.projects.get`
pero **no** `.list`, así que sin este rol el Descubrimiento lista los proyectos
donde el servicio sí puede listar y Petal no sale. **No bloquea nada**: el panel
tiene un campo para escribir el identificador del proyecto a mano, que es el
mismo camino previsto para cuando falta el permiso de Resource Manager entero.

### 1.4 Para poder desplegar con esa identidad

```bash
# Quien lanza el despliegue tiene que poder actuar como la cuenta de servicio.
gcloud iam service-accounts add-iam-policy-binding \
  act-cloudrun-sa@cloud-run-multiproyecto.iam.gserviceaccount.com \
  --member=user:jerosan1@gmail.com \
  --role=roles/iam.serviceAccountUser \
  --project cloud-run-multiproyecto
```

### Cómo saber que fue bien

```bash
gcloud projects get-iam-policy cloud-run-multiproyecto \
  --flatten="bindings[].members" \
  --filter="bindings.members:act-cloudrun-sa" --format="value(bindings.role)"
# esperado: roles/datastore.user

gcloud projects get-iam-policy floristeria-petal-digital \
  --flatten="bindings[].members" \
  --filter="bindings.members:act-cloudrun-sa" --format="value(bindings.role)"
# esperado: roles/dialogflow.admin y roles/serviceusage.serviceUsageConsumer
```

---

## 2 · Desplegar el servicio a Cloud Run

Nunca se ha desplegado: `docs/cloudrun_diseno_servidor.md §14` lo tiene como
*pendiente, sin construir*. Lo que sí está probado (2026-08-10) es la imagen: se
construye, arranca dentro de un contenedor, sirve el panel en `/panel` byte a
byte igual que el archivo del repositorio y redirige `/` a él.

```bash
gcloud run deploy act-server \
  --source . \
  --project cloud-run-multiproyecto \
  --region europe-west1 \
  --service-account act-cloudrun-sa@cloud-run-multiproyecto.iam.gserviceaccount.com \
  --set-env-vars FIRESTORE_PROJECT=cloud-run-multiproyecto,GITHUB_APP_ID=4474347,GITHUB_APP_SECRET_PROJECT=cloud-run-multiproyecto \
  --timeout 3600 \
  --concurrency 1 \
  --max-instances 1 \
  --no-allow-unauthenticated
```

- **`--timeout 3600`** (el máximo): publicar poléa una operación por cada
  contenedor versionado. Con el timeout de 5 minutos por defecto, el Paso 5
  muere justo en el peor momento.
- **`--concurrency 1` y `--max-instances 1`**: no sustituyen al candado de
  Firestore —una instancia con concurrencia 1 **encola**, no rechaza— pero
  reducen la ventana en la que dos escrituras se pisan.
- **`--no-allow-unauthenticated`**: el servicio escribe en Dialogflow y en
  GitHub. Dejarlo abierto significa que cualquiera con la URL despliega. Es
  además la condición para poner IAP delante (paso 6).

### Cómo saber que fue bien

```bash
URL=$(gcloud run services describe act-server --project cloud-run-multiproyecto \
      --region europe-west1 --format='value(status.url)')
curl -s -H "Authorization: Bearer $(gcloud auth print-identity-token)" "$URL/health"
# esperado: {"status":"ok", …, "endpoints":[ "/", "/discover", "/health", … "/panel", "/step/1" … ]}
```

Doce rutas: las nueve del pipeline más `/health`, `/` y `/panel`. Si `/panel`
faltara, la imagen se construyó sin el panel dentro.

---

## 3 · Retirar la lista negra de Petal

Está en `act/server_cloudrun.py`, en el bloque «Destinos que este servidor no
acepta». **Hay que retirar tres cosas y ninguna más:**

| Qué | Dónde |
|---|---|
| `PROYECTOS_PROHIBIDOS = frozenset({"floristeria-petal-digital"})` | declaración, junto a `AGENTES_PROHIBIDOS` |
| `AGENTES_PROHIBIDOS = frozenset({...})` con los dos ids de Petal | la línea siguiente |
| La función `_comprobar_destino(project, agent_id=None)` y sus **nueve llamadas** | una por endpoint que recibe destino (comprobado el 2026-08-10: líneas 378, 387, 398, 414, 431, 449, 463, 491 y 512) |

La forma más segura de retirarla es **vaciar los dos conjuntos**
(`frozenset()`) y dejar la función y sus llamadas en su sitio: el efecto es el
mismo, el diff es de dos líneas, y volver a poner la barrera el día que haga
falta es rellenar los conjuntos otra vez.

**Qué protección se pierde.** Hoy ningún script, ninguna prueba y ningún panel a
medio conectar puede alcanzar Petal a través del servidor, se equivoque quien se
equivoque al copiar un identificador. Ya ocurrió dos veces en este repositorio:
hay dos agentes de prueba creados dentro del proyecto real. Al retirarla, lo
único que queda entre una petición mal formada y el agente en producción son los
gates del propio panel — que son de pantalla, no del servidor.

**Lo que NO se pierde:** las guardas de las suites automáticas
(`exigir_agente_desechable` y `exigir_rama_principal_desechable`, en
`act/validate_pipeline_cloudrun.py`) son independientes y siguen negándose a
escribir contra cualquier agente que no se declare desechable. Esas no se tocan.

### Cómo saber que fue bien

Elegir Petal en el desplegable del panel deja de dar 403 y pasa a listar sus
agentes.

---

## 4 · Devolver el registro de Petal a Firestore

**Estado hoy, leído el 2026-08-10:**

- `proyectos/floristeria-petal-digital` **sí existe**, con
  `repo: jeronimosanchez/cx-automation-template` y
  `rama_principal: pruebas/principal-desechable`.
- `agentes/floristeria-petal-digital__745375ba-…` (Petal 1.0) y
  `…__cea66b60-…` (Petal 1.1) **no existen**. Los únicos documentos de agente de
  ese proyecto son los de dos agentes desechables de fases anteriores.

Es decir: lo apartado es **el alta de los agentes reales**, no el vínculo del
proyecto. Por eso `Contexto('floristeria-petal-digital', '745375ba-…')` muere con
`MappingNotFound`.

**Cómo devolverlo: con el propio panel, no a mano.** Paso 1 → elegir el proyecto
→ elegir el agente → **Dar de alta este agente**. Eso apunta su región, apunta su
rama y crea esa rama en el repositorio, que es exactamente lo que falta. No hay
ningún archivo de respaldo que restaurar —se buscó y no existe— y escribir el
documento a mano dejaría el alta sin su rama, que es el caso que el propio
pipeline avisa que no hay que provocar.

**Antes de pulsar, mirar el nombre de rama que propone.** Para Petal 1.0 será
`agente/petal-1-0` o similar, derivado de su `displayName`. Esa rama pasa a ser
donde el Paso 2 escribe y desde donde el Paso 5 fusiona.

### Cómo saber que fue bien

El Paso 1 deja de avisar de que al agente le falta rama, y el botón «Iniciar
inventario» se enciende.

---

## 5 · La rama principal del proyecto de Petal

Hoy `proyectos/floristeria-petal-digital` dice
`rama_principal: pruebas/principal-desechable`. **Es deliberado** y **se queda
así durante el recorrido manual de la Fase 8**: publicar fusiona la rama de
trabajo en la principal, y con `main` los commits del playbook de prueba
acabarían en la rama real.

**Consecuencia que hay que tener presente:** ese recorrido prueba el camino
completo hasta CX —el playbook de prueba sí llega a producción de Petal— pero
**no prueba la fusión a `main`**. La primera vez que eso se ejercite será en el
primer deploy real.

**Cuándo cambiarlo:** después del recorrido, cuando el destino pase a ser de
verdad. Cómo:

```bash
FIRESTORE_PROJECT=cloud-run-multiproyecto python3 -c "
from act.utils import firestore_client_cloudrun as store
c = store.get_client()
store.save_project_mapping(c, 'floristeria-petal-digital',
                           'jeronimosanchez/cx-automation-template', 'main')
print(store.get_project_mapping(c, 'floristeria-petal-digital'))
"
```

**Qué implica:** a partir de ahí, cada publicación hace un merge real sobre
`main` del repositorio público. Y desaparece el aviso que el Paso 5 imprime en
cada publicación diciendo que la rama principal «no parece la definitiva» — ese
aviso salta por las marcas `pruebas`/`desechable` del nombre.

### Cómo saber que fue bien

El `print` del comando muestra `rama_principal: main`, y la siguiente
publicación deja de imprimir el aviso.

---

## 6 · Activar IAP y autorizar las cuentas

Decisión S25 (`docs/cloudrun_diseno_servidor.md §16`): el acceso lo controla
Google, no código propio. **Va al final**, después del recorrido manual: con IAP
puesto, cualquier prueba automática de navegador se encuentra una pantalla de
login que no puede pasar.

> **Los cuatro comandos de abajo NO están ejecutados ni verificados.** Este paso
> queda fuera del alcance de la Fase 8 a propósito, así que su sintaxis viene de
> la documentación y no de haberla corrido. Lo que sí está comprobado el
> 2026-08-10 es que la API de IAP **no está habilitada** en el proyecto, y que la
> cuenta de servicio de IAP (`6.3`) no existe todavía — se crea al habilitarla,
> así que ese binding hay que hacerlo **después** del `services enable` y no
> antes. Espera tener que ajustar algún flag la primera vez.

```bash
# 6.1 La API de IAP no está habilitada en el proyecto — comprobado el 2026-08-10.
gcloud services enable iap.googleapis.com --project cloud-run-multiproyecto

# 6.2 IAP delante del servicio. Un solo flag, sin balanceador ni certificado
#     aparte (verificado contra la documentación oficial, 2026-08-06).
gcloud run services update act-server \
  --project cloud-run-multiproyecto --region europe-west1 --iap

# 6.3 Que IAP pueda invocar el servicio, con su propia cuenta de servicio.
gcloud run services add-iam-policy-binding act-server \
  --project cloud-run-multiproyecto --region europe-west1 \
  --member=serviceAccount:service-726296318377@gcp-sa-iap.iam.gserviceaccount.com \
  --role=roles/run.invoker

# 6.4 Quién puede entrar. Una línea por cuenta autorizada.
gcloud beta iap web add-iam-policy-binding \
  --project cloud-run-multiproyecto --region europe-west1 \
  --resource-type=cloud-run --service=act-server \
  --member=user:jerosan1@gmail.com \
  --role=roles/iap.httpsResourceAccessor
```

### Cómo saber que fue bien

Abrir la URL del servicio **en un navegador normal, sin token**: tiene que
aparecer la pantalla de login de Google y, después de entrar con la cuenta
autorizada, el panel. Y desde una cuenta no autorizada, un 403 de IAP.

**Pendiente de medir** (`§16` lo deja escrito): que IAP y Cloud Run se combinan
como aquí se asume. Es la combinación estándar y está documentada, pero este
proyecto no da por buena ninguna asunción de infraestructura sin medirla.

---

## 7 · El recorrido manual de Jero

Es el criterio de cierre de la Fase 8 y **no lo hace ningún agente**: cada clic
es la aprobación explícita que exige el proyecto. Se hace **contra el servicio
desplegado en Cloud Run**, no contra un contenedor local: lo local no prueba ni
el despliegue, ni la identidad de ejecución, ni el origen real.

1. Antes de empezar, **contar cuántas versiones tiene ya el agente** («Ver
   versiones existentes» en el Paso 5) para no acercarse al límite por playbook.
2. Crear en el repositorio un Playbook nuevo y claramente ficticio —por ejemplo
   `prueba-buildplaybook`—. **No modificar ni tocar ningún resource que ya
   exista.**
3. Recorrer los 5 pasos desde cero en el panel real, sin recargar, hasta
   publicarlo en producción.
   **Esperado:** cada paso muestra datos reales de Petal, y el Playbook de prueba
   llega a producción sin que ningún resource existente cambie.
4. **Retirarlo:** borrar el Playbook del borrador y **publicar una segunda vez
   sin él**. Comprobar leyendo el entorno de producción —no confiando en que el
   borrado se aplicó— que la versión nueva ya no lo incluye.
   *Por qué es obligatorio:* publicar crea una versión y apunta producción a
   ella; borrar el Playbook después no retira esa versión. Mientras no se
   publique de nuevo, producción está sirviendo el Playbook de prueba a usuarios
   reales.
5. Localizar la versión de producción anterior a la prueba, por si hiciera falta
   un rollback inmediato.
6. Provocar, a mitad de un paso, que el servidor deje de responder —retirando
   temporalmente el acceso al servicio—. **Esperado:** el panel dice a qué
   dirección llamó, y si ocurre durante el Paso 5 añade la advertencia de que no
   se sabe cuáles de las tres acciones se completaron.

---

## Lo que ya está hecho y no hay que repetir

Para no volver a investigarlo:

- **El panel conectado** (`docs/panels/act_cx_resources_deploy_v2_output_cloudrun.html`):
  sin simulación, con las nueve rutas consumidas, estado en `localStorage` y
  mensajes propios por cada código de error del servidor.
- **El servidor sirve el panel** desde su mismo origen (`/` y `/panel`), y el
  `Dockerfile` lo mete en la imagen. Probado dentro del contenedor.
- **La validación automática**: `act/validate_html_cloudrun.py` (4 niveles, 55
  comprobaciones) y `act/validate_html_dom_cloudrun.js` (25 escenarios que
  ejecutan el panel de verdad).
- **El recorrido completo de los 5 pasos**, hasta publicar, contra un agente
  desechable — verificado leyendo el resultado en CX y en GitHub, no el código de
  respuesta.
- **El catálogo de TCs**: `docs/data/tc_deploy_pipeline_cloudrun.yaml`.
