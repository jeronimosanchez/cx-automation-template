---
name: epic-separar-qa-html-generator
description: "Separar test_QA_Playbooks_v23.py en módulos independientes: definición de TCs, runner y generador HTML."
metadata:
  node_type: memory
  type: project
  originSessionId: 355c502d-d654-4309-91d4-934b4e3abeab
---

# Épica — Separar QA en módulos independientes

**Origen:** 27-may-2026. Detectado durante sesión de rediseño del dashboard HTML que `test_QA_Playbooks_v23.py` acumula tres responsabilidades distintas que deberían vivir en ficheros separados.

**Problema:** el fichero tiene ~2600 líneas y mezcla:
1. **Definición de TCs** — los ~50 test cases con sus turnos, checks y grupos
2. **Runner** — ejecución de TCs contra Dialogflow CX (`run_single()`, polling, logs)
3. **Generador HTML** — `generate_html()`, CSS, JavaScript del dashboard

Esto provoca que cualquier cambio visual del dashboard (CSS, layout, etiquetas) toque el mismo fichero que los TCs y el runner, aumentando el riesgo de regresiones accidentales.

---

## Split propuesto

```
test_QA_Playbooks_v23.py  →  qa/tc_definitions.py       (solo TCs: turns, checks, grupos)
                          →  qa/qa_runner.py             (solo ejecución: run_single, polling)
                          →  qa/qa_html_generator.py     (solo HTML: generate_html, CSS, JS)
```

El script `qa/regenerate_html.py` ya existe como entry point del generador — solo hay que mover `generate_html()` fuera del fichero principal.

---

## User stories

- **US-SEP-1:** Extraer `generate_html()` + CSS + JS a `qa/qa_html_generator.py`. Actualizar `regenerate_html.py` para importar desde ahí.
- **US-SEP-2:** Extraer los TCs (lista `TESTS`) a `qa/tc_definitions.py`. El runner importa desde ahí.
- **US-SEP-3:** Renombrar el fichero principal a `qa/qa_runner.py` o equivalente, eliminando responsabilidades ya extraídas.
- **US-SEP-4:** Actualizar `qa.yml` (GitHub Actions) para referenciar los nuevos nombres.
- **US-SEP-5:** Añadir test de smoke que verifique que el split no rompe la generación HTML ni la ejecución de TCs.

---

## Cuándo abordar

- **No urgente** — el fichero funciona y está bajo control.
- **Trigger recomendado:** cuando el fichero supere 3000 líneas O cuando haya colaboradores que toquen el HTML sin tocar los TCs.
- **Pre-requisito:** ninguno. Es refactor puro, sin dependencias externas.

---

## Estimación

~1 día de sprint. Bajo riesgo si se hace con tests de smoke previos.

---

## Anti-patrones a evitar

- Hacer el split sin tests de smoke → riesgo de romper el pipeline CI/CD silenciosamente.
- Cambiar la lógica durante el split → separar primero, optimizar después.
- Renombrar sin actualizar `qa.yml` → el pipeline deja de encontrar el fichero de entrada.
