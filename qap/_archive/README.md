# QA Promptfoo — ARCHIVADO (Sprint 6)

> **Estado:** archivado, no ejecutable desde el pipeline ACT.
> **Razón:** el motor QA del Sprint 1 (Promptfoo skeleton con un único TC trivial)
> fue sustituido en Sprint 6 por el runner real `test_QA_Playbooks_v23.py` (29 TCs).
> **Reactivación planificada:** EP-QA-04 — migración del motor QA a Promptfoo
> con cobertura completa, una vez consolidada la fase 1 con el runner Python.

## Contenido

Este directorio conserva los artefactos originales del Sprint 1 para rastreabilidad:

- `promptfooconfig.yaml` — suite mínima con un test trivial.
- `promptfoo_provider.py` — custom provider Python que llama a `detectIntent`.
- `package.json` + `package-lock.json` — dependencia npm de Promptfoo.

## Pipeline activo

El runner QA real vive en `qa/test_QA_Playbooks_v23.py` (29 TCs) y se ejecuta
desde `.github/workflows/qa.yml`. Reportes públicos en GitHub Pages:

- `https://jeronimosanchez.github.io/cx-automation-template/qa/qa_latest.html`
- `https://jeronimosanchez.github.io/cx-automation-template/qa/qa_latest.txt`

Ver `docs/setup-qa.md` para activar el pipeline.
