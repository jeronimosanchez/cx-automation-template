# QAP — Quality Assurance y validación

Línea **QAP** del sistema de Automatización CD. Ejecuta la suite de TCs contra el
agente Petal en CX y publica reportes en GitHub Pages.

## Contenido

| Archivo | Qué hace |
|---|---|
| `test_qa_playbooks.py` | Runner principal — contiene los TCs y los ejecuta vía `detectIntent` |
| `regenerate_html.py` | Regenera el HTML del reporte sin llamar a CX (usa JSONs previos) |
| `rebuild_history.py` | Reconstruye `history.json` del dashboard histórico |
| `list_fails.py` | Lista los FAILs de un run y su estado de análisis |
| `publish_html.sh` · `rerun_single_tc.sh` · `regenerate_all_html.sh` | Utilidades locales de re-ejecución y publicación |
| `tc_analysis/` | Análisis por TC fallido (run-scoped) |
| `_archive/` | Skeleton Promptfoo del Sprint 1, archivado (reactivación: EP-QA-04) |

## Uso

```bash
# Listar TCs
python qap/test_qa_playbooks.py --list

# Ejecutar un TC concreto
python qap/test_qa_playbooks.py --test TC-C29 --runs 1
```

En CI lo dispara `qa.yml` (workflow_dispatch, PR a `main`, o tras deploy exitoso).
Los reportes se publican en GitHub Pages bajo la ruta `/qa/`.

> Nota: la ruta pública de Pages se mantiene en `/qa/` (no `/qap/`) para no romper
> enlaces existentes. El nombre de carpeta del código (`qap/`) y la URL publicada
> (`/qa/`) están deliberadamente desacoplados.
