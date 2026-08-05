# Handoff para Opus — Cloud Run multi-proyecto

Estado: en construcción (se va populando durante la Fase A).
Destino: sesión de Opus que implementará la Fase B (código).

---

## 1. Por qué existe este servicio

Hoy el pipeline ACT corre en local, en el Mac de Jero, y solo sabe trabajar con un proyecto conversacional (Petal). Si Jero quisiera usar la misma herramienta con otro agente de Dialogflow CX, no hay forma segura de hacerlo sin arriesgar mezclar archivos entre proyectos.

Este servicio en Cloud Run reemplaza al servidor local (`server.py`) y añade soporte multi-proyecto: Jero le dice dónde está el proyecto en GitHub y en CX, y el servicio se encarga del resto — incluyendo la gestión de permisos hacia CX.

---

## 2. Qué es Cloud Run (para este contexto)

Cloud Run es un servicio de Google Cloud que ejecuta contenedores Docker sin que haya que gestionar servidores. Las características relevantes para este proyecto:

- **Stateless**: no guarda estado entre peticiones. Todo lo que necesita lo recibe en cada llamada o lo lee de Secret Manager.
- **Escala a 0**: cuando no hay peticiones, no corre (y no cobra). Cuando llega una, arranca en segundos.
- **HTTP**: expone endpoints HTTPS. El panel HTML llama a esos endpoints igual que hoy llama a `server.py`.
- **Concurrencia controlada**: configurado a 1 instancia, reproduce el comportamiento de lock global de `server.py` — dos despliegues no pueden correr a la vez.

---

## 3. Con qué se conecta

```
Panel HTML (Mac de Jero)
        │
        │ HTTPS (autenticado con identidad Google de Jero)
        ▼
┌─────────────────────────────────┐
│        Cloud Run (este servicio) │
│                                 │
│  • Mismos 8 endpoints de hoy    │
│  • Corre en cloud-run-multiproyecto (GCP) │
└──────────┬──────────────────────┘
           │                    │
           │ (cuenta de servicio)│ (GitHub App)
           ▼                    ▼
   Dialogflow CX            GitHub
   (proyecto Petal           (repo cx-automation-template
    y futuros)                y repos futuros)
```

**Hacia Dialogflow CX:**
- Usa la cuenta de servicio `act-cloudrun-sa@cloud-run-multiproyecto.iam.gserviceaccount.com`
- Tiene `roles/dialogflow.admin` sobre los proyectos CX registrados
- Autenticación vía ADC (Application Default Credentials) — NO `gcloud auth print-access-token` (eso es para sesiones humanas interactivas, no existe en Cloud Run). Ver excepción documentada en `CLAUDE.md §3.1`.

**Hacia GitHub:**
- Usa una GitHub App (no un token fijo)
- La App genera tokens de corta duración (~1h) bajo demanda en cada operación de push
- La clave privada de la App vive en Secret Manager, nunca en variables de entorno ni en el código
- La App está instalada en los repos de los proyectos registrados

**Desde el panel HTML:**
- El panel llama a los mismos endpoints que hoy llama a `server.py`
- La diferencia: la URL base cambia de `localhost` a la URL de Cloud Run
- La autenticación del panel hacia Cloud Run usa la identidad Google de Jero (el servicio tiene `--no-allow-unauthenticated`)

---

## 4. Infraestructura creada (Fase A — completada)

### Proyecto GCP
- **Nombre:** `cloud-run-multiproyecto`
- **Facturación:** vinculada a cuenta `015D46-707718-D2A984` (Mi cuenta de facturación 1)
- **APIs habilitadas:** Cloud Run, Secret Manager, IAM

### Cuenta de servicio
- **ID:** `act-cloudrun-sa@cloud-run-multiproyecto.iam.gserviceaccount.com`
- **Permisos:** `roles/dialogflow.admin` sobre los proyectos CX registrados
- **Nota sobre multi-proyecto:** el servidor **no concede IAM automáticamente** (decisión S6b — evita que un servicio con URL pública tenga poder de modificar permisos sobre proyectos GCP ajenos, y respeta `CLAUDE.md §7.1`). Cuando Jero registra un proyecto CX nuevo en el wizard de onboarding, el panel calcula y muestra el comando `gcloud` exacto — con el ID del proyecto ya escrito y el nombre de esta cuenta de servicio ya puesto — y Jero lo ejecuta una vez, fuera del panel (S11, S22).

### Secret Manager
- **Secreto:** `github-app-private-key` en proyecto `cloud-run-multiproyecto`
- **Acceso:** solo `act-cloudrun-sa` — rol `roles/secretmanager.secretAccessor`
- **Contenido:** clave privada de la GitHub App `act-cloudrun-deploy`

### GitHub App
- **Nombre:** `act-cloudrun-deploy`
- **App ID:** `4474347`
- **Instalada en:** todos los repositorios de `jeronimosanchez` (actuales y futuros)
- **Permiso:** `Contents: Read and write`
- **Sin webhook**, sin OAuth, sin permisos de organización

### Firestore
- **Base de datos:** `(default)` en `europe-west1`
- **Capa gratuita:** sí (`freeTier: true`)
- **Uso:** almacena los proyectos registrados (agente CX + repo GitHub)

### Servicio Cloud Run
- *(pendiente — Fase B)*

---

## 5. Diferencias clave con el servidor local actual

| | `server.py` (local) | Cloud Run (nuevo) |
|---|---|---|
| Dónde corre | Mac de Jero | GCP `europe-west1` |
| Auth hacia CX | `gcloud auth print-access-token` | ADC (cuenta de servicio) |
| Auth hacia GitHub | No existe (carpeta local) | GitHub App, tokens ~1h |
| Multi-proyecto | No | Sí — selector repo+agente |
| Disponibilidad | Solo con el Mac encendido | 24/7 |
| Concurrencia | Lock local (409) | 1 instancia (mismo efecto) |

---

## 6. GitHub App — autenticación hacia GitHub

### Qué es y por qué
La GitHub App es la identidad que Cloud Run usa para leer y escribir en los repos de GitHub. No es un usuario, no es un token fijo — es una "llave" registrada en la cuenta de Jero que genera tokens de corta duración (~1h) bajo demanda en cada operación.

**Por qué no un token personal (PAT):** un PAT es fijo — si se filtra, tiene acceso indefinido hasta que se rote manualmente. Con una GitHub App los tokens caducan solos, sin intervención de Jero.

### Alcance
- **App:** `act-cloudrun-deploy`, registrada en la cuenta `jeronimosanchez`
- **Instalada en:** todos los repositorios de la cuenta (`all repositories`)
- **Permiso único:** `Repository contents: Read and write`
- **Sin webhook**, sin permisos de organización, sin acceso a nada más

### Por qué "todos los repositorios"
La App tiene acceso a cualquier repo que Jero cree en el futuro, automáticamente. Cuando se añade un proyecto nuevo al panel, Cloud Run ya puede acceder a su repo — sin ningún paso manual, sin dependencia técnica. Cero configuración extra por proyecto nuevo.

### Cómo funciona en cada operación
1. Cloud Run lee la clave privada de la App desde Secret Manager
2. Genera un token JWT firmado con esa clave (válido ~1h)
3. Usa ese token para la operación de lectura/escritura en GitHub
4. El token caduca solo — nunca se almacena ni se reutiliza

### Lo que Jero hace una sola vez
Registrar la App en `github.com/settings/apps/new` e instalarla en "todos los repositorios". Después no vuelve a tocarla nunca.

---

## 7. Persistencia y UX del selector

### Dónde se guardan los proyectos registrados
Cloud Run es stateless — no guarda nada entre peticiones. Los proyectos registrados (proyecto CX + repo GitHub) se persisten en **Firestore**, dentro del mismo proyecto GCP `cloud-run-multiproyecto`. Un documento por proyecto registrado. Cuando Jero registra un nuevo proyecto, el tool graba en Firestore y concede `dialogflow.admin` a la cuenta de servicio sobre ese proyecto CX — Jero no hace pasos manuales.

### UX del selector — último proyecto pre-seleccionado
El panel HTML guarda en `localStorage` del navegador el último proyecto CX y el último repo GitHub seleccionados. Al abrir el panel:
- Ambos aparecen pre-seleccionados al instante (sin llamada al backend).
- En paralelo, se carga la lista completa de proyectos desde Cloud Run.
- `localStorage` es memoria local del navegador — no consume tiempo ni hace llamadas. Es instantáneo.

---

## 7. Lo que Opus debe implementar (Fase B)

Ver `docs/plan_cloudrun_multiproyecto.md` §6 Fase B para el detalle completo. Resumen:

1. Migrar los 8 endpoints de `server.py` a Cloud Run con ADC en vez de `gcloud auth print-access-token`
2. Implementar generación de tokens GitHub App en cada push
3. Rediseñar selector de proyecto: proyecto/agente CX + repo de GitHub
4. Construir botón único de sincronización (CX→GitHub→Mac, dos saltos encadenados)
5. Construir pieza local mínima (git fetch + aviso + pull con confirmación)
6. Construir log de seguimiento por salto (CX ✓/✗, GitHub ✓/✗, Local ✓/✗)
7. Aplicar regla origen→destino en toda la UI (pull/push nunca sin especificar de dónde a dónde)

**Prerequisito antes de empezar Fase B:** confirmar con Jero la actualización de `CLAUDE.md §6` (ya aplicada en `staging`) y el nombre del proyecto GCP (ya creado: `cloud-run-multiproyecto`).

---

## 7. Decisiones tomadas — no re-litigar

- Proyecto GCP nuevo y separado: `cloud-run-multiproyecto` ✅
- GitHub App en vez de token fijo ✅
- Selector de repo GitHub en vez de carpeta local ✅
- Pieza local mínima sigue existiendo (limitación técnica, no decisión) ✅
- `CLAUDE.md §6` actualizado: pipeline puede ser local o Cloud Run ✅
- La opción local se elimina cuando Jero lo decida explícitamente (no hay fecha) ✅
- Permisos IAM hacia nuevos proyectos CX: el servidor **no** los concede — el panel calcula y muestra el comando `gcloud` en el wizard de onboarding, y Jero lo ejecuta una vez, fuera del panel (S6b, S11, S22) ✅
