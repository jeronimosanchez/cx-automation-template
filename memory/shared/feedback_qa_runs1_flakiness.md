---
name: QA con --runs 1 tiene flakiness de ±2-3 TCs
description: Para confirmar un fix real usar --runs 3 local. Para verificar regresiones globales, full QA en CI con --runs 1 sirve pero hay ruido.
type: feedback
originSessionId: 288e30ad-19ad-43ff-9e5f-fca510d83ba2
---
El runner `qa/test_QA_Playbooks_v23.py --runs 1` produce variabilidad de 2-3 TCs entre runs sin que el agente haya cambiado. TCs típicamente flakies (mismos vistos oscilar en una sola tarde): TC-C30, TC-C37, TC-C40, TC-REG01, TC-C36 antes del fix.

**Why:** Gemini es no-determinístico y los checks usan regex frágiles. Un solo run no es suficiente para confirmar fix ni para confirmar regresión.

**How to apply:**
- **Validar un fix concreto:** local con `--test TC-XX --runs 3`. ~1-2 min. Determinístico.
- **Verificar regresiones globales:** full QA en CI con `--runs 1` está bien pero filtra el ruido — solo cuentan flips estables (3+ runs) o flips de TCs que toca el fix.
- Aparentes "regresiones" en CI tras un fix que solo toca X playbook → casi siempre flakiness. Confirmar antes de actuar.
- Pendiente debt técnica: subir `qa.yml` a `--runs 3` cuando el coste de 9 min por run sea aceptable.
