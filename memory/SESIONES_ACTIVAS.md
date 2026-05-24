# Sesiones activas — cx-automation-template

Última actualización: 2026-05-17 23:00 CEST

Este archivo lista las sesiones de Claude Code paralelas que están trabajando en este proyecto.
**Lee este archivo al arrancar cualquier sesión nueva** para saber qué hace cada una y evitar pisarse.

---

## 🎯 Demo Martes

- **Tema**: organizar la demo para cliente del 19-may (próximo martes)
- **Capa**: Petal (es demo de Petal)
- **Archivos del repo que toca**: docs/demo/* (si existe), slides en Google Drive (fuera del repo)
- **Memoria propia**: aún en `memory/` central (mover a worktree propio si crece)
- **Estado**: en preparación
- **Próximo paso**: definir guion + slides
- **⚠️ NO TOCAR desde otras sesiones**: nada de qa/ ni definitions/ que pueda romper la demo en vivo

## 🔬 Optimización QA (test usuario)

- **Tema**: investigar capacidad de análisis y solución del agente con test usuarios reales
- **Capa**: mixta (Petal + Automatización)
- **Archivos del repo que toca**: borrador qa/user_studies/* (si existe), métricas en sheets
- **Memoria propia**: aún en `memory/` central
- **Estado**: investigación/exploración
- **Próximo paso**: definir métricas a capturar
- **⚠️ NO TOCAR**: nada todavía, está explorando

## 📐 HTML Redesign (TRANSITORIA — pausada para mañana)

- **Tema**: rediseñar visual del reporte HTML del QA
- **Capa**: Automatización (toca el runner del template)
- **Archivos del repo**: `qa/test_QA_Playbooks_v23.py` (generate_html, extract_response, run_single, generate_reports), `qa/tc_analysis/*.md`
- **Worktree**: `~/cx-automation-template/.claude/worktrees/hungry-sanderson-d8def1/` (rama `qa/html-redesign`, PR #65 mergeado pero v3 con MUCHOS cambios sin commitear)
- **Estado al 18-may 02:00**: iteración v3 trabajada toda la noche. Cambios masivos en local (~400 líneas), nada commiteado. Jero pausa hasta mañana — "hay mas ajustes pero haz handover".
- **Logs del último QA real**: `~/petal-qa/qa_20260518_0118_logs/` (3 TCs × 2 runs)
- **Próximo paso**: leer `current/handoff_2026-05-18_html-redesign-v3.md` para retomar. Preguntar a Jero qué ajustes faltan antes de continuar.
- **Memoria asociada**: `current/handoff_2026-05-18_html-redesign-v3.md` (handoff completo de la noche del 17→18-may)
- **⚠️ NO TOCAR desde otras sesiones**: `qa/test_QA_Playbooks_v23.py`, `qa/tc_analysis/*.md` y el worktree hasta que esta sesión cierre.

## 🔄 Reorganización Handoffs

- **Tema**: rediseñar el sistema de handoffs entre sesiones (este mismo archivo es parte del trabajo)
- **Capa**: Automatización (transversal)
- **Archivos del repo que toca**: ninguno hoy (es estructura de memoria/Notion)
- **Memoria propia**: aún en `memory/` central
- **Estado**: iterativo
- **Próximo paso**: definir plantilla estándar de handoff

## ⚙️ Automatización (general)

- **Tema**: mejoras al template, scripts push_*, workflows CI/CD
- **Capa**: Automatización
- **Archivos del repo que toca**: `src/push_*.py`, `.github/workflows/*.yml`
- **Memoria propia**: aún en `memory/` central
- **Estado**: iterativo
- **Próximo paso**: pendiente de priorizar

---

## Sesiones cerradas/archivadas

Cuando una sesión se cierra (su trabajo termina), mover su sección a esta zona y archivar su memoria en `archived/`.

(Vacío por ahora.)

---

## Convenciones para sesiones paralelas

1. **Antes de modificar un archivo del repo**: verifica en este dashboard si otra sesión ya lo toca.
2. **Antes de lanzar `gh workflow run`**: avisa por mensaje a Jero para coordinar (no debe haber 2 workflow runs paralelos por la `cancel-in-progress=true`).
3. **Antes de cerrar una sesión por agotamiento de tokens**: escribe handoff en `current/handoff_YYYY-MM-DD_<sesion>.md` y actualiza esta tabla.
4. **Cuando una sesión termina su scope**: archivar memoria en `archived/`, quitar entrada de "Sesiones activas".
5. **Política nueva (16-may)**: permiso explícito para `git commit`, `git push`, `gh workflow run`, modificar archivos del repo. Anula el patrón "lanza/dale" del CLAUDE.md §8.3.
