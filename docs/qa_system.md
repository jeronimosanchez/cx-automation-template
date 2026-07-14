# QA System — Runner y Analizador

> Versión: 1.0 | Fecha: 2026-07-02
>
> Este documento explica qué hace el sistema QA de Petal, cómo está estructurada la suite de TCs y qué produce como output.

---

## 1. Arquitectura actual

```
CI/CD (tras cada deploy)
        ↓
test_qa_playbooks.py
        ↓  detectIntent × 54 TCs (fuente: tc_1_1.yaml)
        ↓  check_turn() — regex positivo + negativo
        ↓
JSON por TC → HTML → GitHub Pages
                          ↓
              (manual, solo sobre FAILs)
                          ↓
              qa-tc-analyzer (🟡)
                          ↓
              análisis 9 dimensiones → HTML enriquecido → GitHub Pages
```

---

## 2. Runner — `test_qa_playbooks.py`

Ejecuta conversaciones reales contra el agente Petal vía `detectIntent` (Dialogflow CX API), compara las respuestas con regex y publica resultados.

**Qué hace turno a turno:**
1. Envía el mensaje del usuario al agente (`detect_intent`)
2. Extrae la respuesta, el playbook activo y los parámetros capturados
3. Evalúa la respuesta con `check_turn()`:
   - **`checks`** — patrones que el agente DEBE decir (regex positivo)
   - **`not_expected`** — patrones que el agente NO debe decir (regex negativo)
4. Acumula resultado por TC: PASS / FAIL / INESTABLE / QUOTA_ERROR

**Cómo funciona la rúbrica de evaluación:**

Cada TC define explícitamente qué debe y no debe decir el agente:
- **`checks`** — condiciones que la respuesta DEBE cumplir. Todas deben cumplirse (AND). Dentro de cada condición, `|` es OR: `"disponible|en stock"` pasa si el agente dice cualquiera de las dos
- **`not_expected`** — patrones que la respuesta NO puede contener. Si aparece cualquiera → FAIL

**Limitación — evaluación por palabras clave, no por objetivo:**

El sistema actual es determinístico: evalúa si ciertas palabras clave aparecen o no en la respuesta, no si el agente cumplió el objetivo de la conversación. Dos implicaciones directas:

- El agente puede dar una respuesta válida con palabras distintas a las del check → FAIL incorrecto
- El agente puede mencionar la palabra clave en un contexto incorrecto → PASS incorrecto

Esta es la razón por la que el runner es automático y gratuito (no requiere LLM) pero determinístico. La evaluación semántica real — si la respuesta cumple el objetivo independientemente de las palabras usadas — la resolverá `qap_ag_juez` cuando esté implementado.

**Ejemplo — TC-R04 (Compra directa):**

```yaml
- id: TC-R04
  turns:
  - user: Quiero comprar rosas rojas
    checks:
    - rosas|rosa|Ramo|Boutonniere|ocasi   # OR: basta con que aparezca cualquiera
  not_expected:
  - email
  - correo
```

→ PASS si la respuesta menciona alguna de las palabras del check Y no menciona "email" ni "correo".

**La limitación en acción:** si el agente responde *"Por supuesto, te ayudo a encontrar las flores perfectas"* — no menciona ninguna palabra del check → FAIL, aunque la respuesta sea válida. Si responde *"Tenemos rosas disponibles, ¿me das tu correo?"* — pasa el check pero falla el not_expected → FAIL correcto. El sistema detecta el segundo caso bien, pero no distingue el primero.

**Implementación técnica:** matching parcial (`re.search`) + insensible a mayúsculas + normalización NFD de tildes (`"ocasion"` matchea `"ocasión"`).

**`not_expected` puede vivir en dos niveles:**
- Nivel TC (aplica en el turno 1)
- Nivel turno (aplica solo en ese turno)

**Output por TC:**
```json
{
  "id": "TC-BODA-01",
  "status": "PASS",
  "pass_count": 1,
  "turns": [
    {
      "turn": 1,
      "user": "quiero flores para una boda",
      "agent": "Con mucho gusto te ayudo...",
      "playbook": "Compra",
      "params": {"ocasion": "boda"},
      "checks": {
        "pass": true,
        "details": ["OK: Agente dijo [boda]"]
      }
    }
  ]
}
```

**Qué produce:**
- JSON por TC → `reports/<run_id>/results.json`
- HTML con dashboard completo → `reports/index.html` → GitHub Pages

---

## 3. Suite de TCs — `qap/tc_1_1.yaml`

54 TCs end-to-end organizados en grupos de cobertura. Es la fuente de verdad independiente del runner — versionada en git, portable a cualquier runner futuro.

**Evolución:** hasta junio 2026 los TCs estaban hardcodeados en el runner (29 TCs). Se extrajeron a YAML para separar datos de lógica y facilitar el mantenimiento.

### Grupos de cobertura

| Grupo | Qué verifica | TCs |
|---|---|---|
| G1 | Información de negocio (horario, políticas) | 1 |
| G2 | Catálogo e información de precios | 1 |
| G3 | Recomendación / derivación a Compra | 1 |
| G4 | Saludo e inicio de conversación | 1 |
| G5 | Compra directa + variantes (boda, funeral, color, presupuesto) | 6 |
| G5>CK | Handoff Compra → Checkout | 1 |
| G5>CK>REG | Flujo completo Compra → Checkout → Registro | 1 |
| G6 | Perfil: email, saldo, devolución, cliente moroso | 4 |
| G7 | Registro: happy path, error, cancelación, post-registro | 4 |
| COMPRA-ZG | Zona gris: ambigüedad, robustez, tono mid-flow, urgencia | 22 |
| COMPRA-INV | Inventario real: catálogo, multi-producto | 3 |
| ESP | Especiales: hablar con humano, email espontáneo | 2 |

**Tipos de TC:**
- `REG` — comportamiento estándar esperado en producción
- `NEW` — flujos nuevos añadidos en Petal 1.1
- `EDGE` — casos límite, zona gris, robustez

---

## 4. Analizador — `qa-tc-analyzer` (🟡 SKILL.md v1.3)

Se activa **manualmente** cuando hay FAILs que entender, y corre **solo sobre los TCs fallidos**. Decisión de economía: cada análisis consume tokens de Claude API. No está integrado en el pipeline automático precisamente por esto — el runner corre gratis con regex, el analizador se activa bajo demanda cuando el coste está justificado.

Lee los JSONs del runner y añade diagnóstico de causa raíz al mismo HTML del dashboard. Lanza **1 sub-agente por TC fallido** (no por dimensión).

Cada sub-agente evalúa 9 dimensiones:

| Dimensión | Fuente que lee | Qué razona |
|---|---|---|
| Comportamiento | playbook YAML | ¿La instrucción cubre el caso? ¿Es suficientemente directiva? |
| Routing | orquestador YAML | ¿Enrutado correcto al playbook? |
| Parámetros/Slots | JSON del TC | ¿Los slots llegaron correctos al turno que falló? |
| Integración | JSON del TC | ¿Error de tool? ¿El backend respondió? |
| Datos | Sheet API (endpoint real) | ¿Los valores de negocio son coherentes? |
| Infraestructura | Environment activo, versiones | ¿El deploy llegó? ¿Versión correcta en el environment? |
| Modelo/LLM | — | Solo se marca si las 8 capas restantes son 🟢 y el fallo es reproducible |
| Histórico | git log del playbook | ¿Regresión introducida en un commit reciente? |
| Test | tc_1_1.yaml + regex | ¿El propio test está mal escrito o el regex es incorrecto? |

---

## 5. Archivos del sistema

| Archivo | Función |
|---|---|
| `qap/test_qa_playbooks.py` | Runner principal |
| `qap/tc_1_1.yaml` | Suite 54 TCs (fuente de verdad) |
| `qap/tc_1_0.yaml` | Suite baseline Petal 1.0 (referencia) |
| `qap/surgical_run.py` | Runner selectivo — corre un subconjunto de TCs por ID o grupo |
| `qap/list_fails.py` | Lista FAILs del último run (entrada para qa-tc-analyzer) |
| `qap/rebuild_history.py` | Reconstruye el histórico de runs para el dashboard |
| `qap/publish_html.sh` | Publica el HTML en GitHub Pages |
| `.claude/skills/qa-tc-analyzer/` | Skill de análisis de causa raíz |
