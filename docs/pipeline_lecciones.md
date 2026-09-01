# Pipeline ACT — Lecciones aprendidas

Problemas reales encontrados al desplegar recursos con el pipeline. Leer antes de cada iteración.

---

## L1 · Repo equivocado para las definiciones del agente

**Síntoma:** los archivos YAML subidos a `cx-automation-template/staging` no aparecen en el pipeline.

**Causa:** el pipeline de cada agente lee de su propio repo de definiciones, no de `cx-automation-template`. Para Petal 1.1, el repo correcto es `jeronimosanchez/floristeria-petal-v2`, rama `agente/floristeria_petal_2`.

**Regla:** los YAMLs de recursos (playbooks, tools, flows, etc.) deben ir al repo del agente, no a `cx-automation-template`.

---

## L2 · Formato de cabecera incorrecto en el repo del agente

**Síntoma:** el pipeline no empareja el archivo con el recurso de CX, o no lo detecta como resource.

**Causa:** `cx-automation-template/definitions/` usa un formato simplificado (sin `metadata`). El repo del agente (`floristeria-petal-v2`) requiere un bloque `metadata` al inicio:

```yaml
metadata:
  tipo: playbook  # o tool, flow, intent, etc.
  padre: null
  cx_id: <uuid-real-o-vacío>
  agente: <agent-uuid>
```

**Regla:** copiar siempre la estructura de otro YAML del mismo repo antes de crear uno nuevo.

---

## L3 · Proyecto GCP equivocado al operar tools vía API

**Síntoma:** `curl` devuelve 0 tools o error de permisos.

**Causa:** el agente Petal 1.0 está en `floristeria-petal-digital`; Petal 1.1 está en `floristeria-petal-v2`. Confundirlos devuelve resultados vacíos o errores 403.

**Regla:** siempre verificar el proyecto GCP antes de llamar a la API de CX. Consultar la memoria `petal/agente_floristeria_petal_2.md` para los identificadores actuales.

---

## L4 · cx_id colisionando entre recursos nuevos (400)

**Síntoma:** `HTTP 400 — Hay archivos distintos del mismo agente con el mismo tipo y cx_id`.

**Causa:** dos archivos YAML del mismo tipo tienen `cx_id: 00000000-0000-0000-0000-000000000000`. El pipeline no puede distinguirlos.

**Regla:**
- Recurso ya existente en CX → `cx_id: <uuid-real>`.
- Recurso nuevo (aún no en CX) → `cx_id: ''` (cadena vacía).
- Solo puede haber un `00000000` por tipo: es el que el pipeline usa como "plantilla de nuevo". Si el repo ya tiene uno, el siguiente nuevo usa `''`.

---

## L5 · apiKey obligatoria en todo POST/PATCH de tool con apiKeyConfig (400)

**Síntoma:** `PATCH tool/X falló: 400 — Either API key secret string or secret version name should be specified if API key config is provided`.

**Causa:** CX exige que cada escritura sobre una tool con `apiKeyConfig` incluya la clave real (`apiKey: <valor>`) o un nombre de versión de Secret Manager. Si el YAML omite el campo, CX rechaza la llamada.

**Regla:** incluir siempre `apiKey` en el bloque `authentication.apiKeyConfig` del YAML de la tool. El pipeline no puede cachear ni reutilizar la clave que ya está en CX.

---

## L6 · El pipeline no gestiona tools — hay que crearlas directamente en CX

**Síntoma:** una tool nueva no aparece en el Paso 3 (Aplicar en CX) aunque esté en el YAML del repo.

**Causa:** el pipeline ACT actual gestiona playbooks, flows, intents, etc., pero NO crea tools nuevas en CX. Solo puede PATCH tools que ya existan (emparejadas por `displayName`).

**Regla:** las tools nuevas hay que crearlas manualmente vía API de CX antes de ejecutar el pipeline. Después, añadir el YAML al repo con el `cx_id` real para que el pipeline pueda hacer PATCH en el futuro.

```bash
# Crear tool en CX (ejemplo)
curl -X POST "https://europe-west1-dialogflow.googleapis.com/v3/projects/$PROJECT/locations/europe-west1/agents/$AGENT/tools" \
  -H "Authorization: Bearer $(gcloud auth print-access-token)" \
  -H "Content-Type: application/json" \
  -H "x-goog-user-project: $PROJECT" \
  -d '{
    "displayName": "NombreTool",
    "openApiTool": {
      "textSchema": "<openapi yaml>",
      "authentication": { "apiKeyConfig": { "keyName": "X-API-Key", "apiKey": "<key>", "requestLocation": "HEADER" } }
    }
  }'
```
