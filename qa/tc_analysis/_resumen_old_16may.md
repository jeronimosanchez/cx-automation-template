---
generated_by: Análisis manual (Jero + Claude, 16-may-2026)
qa_baseline: 22 PASS / 3 INESTABLE / 6 FAIL (--runs 3 contra Compra v39)
---

# Resumen agrupado por causa común

Los 9 TCs que no pasan en el QA actual se agrupan en **5 causas distintas**. Priorización por esfuerzo creciente y dependencia.

| Causa | TCs afectados | Esfuerzo | Tipo | Acción |
|---|---|---|---|---|
| **Test mal calibrado** | TC-C41 (T1 contradicción `not_expected`) | 5 min | Test | Ajustar regex o quitar overlap en `not_expected` |
| **Test resuelto en PR #48** | TC-C42, TC-C43 | 0 (esperar) | Test | Re-ejecutar QA post-deploy PR #48 para reevaluar |
| **Errores 400 transitorios** | TC-C37 (parcial), TC-C38, TC-DECO-01, TC-DECO-02 | Investigar | Infra | PR #49 ya añadió throttle+retry quota. Re-ejecutar y medir si quedan errores 400. |
| **Bug delegación (Playbook Compra)** | TC-C41 (T2) | ~1h | Playbook | Añadir regla en sección "Casos especiales" del playbook: si usuario delega ("tú decides"), mostrar 3 opciones populares sin más refinamiento. |
| **Bug mapeo "decoración" (Playbook Compra o Tool)** | TC-DECO-01, TC-DECO-02 | ~1-2h | Playbook | Opción C recomendada: que Compra NO mapee "decorar" a `ocasion=Decoracion` — pase solo `producto=X` y deje al catálogo responder. Una vez fix, ambos TCs pasan. |
| **Flakiness aceptable** | TC-R01, TC-C30, TC-C37 | — | N/A | Bug intermitente del Orquestador (acceso a info de negocio + clarificación de inputs ambiguos). Baja prioridad — no afecta flujo crítico de venta. |

## Plan de acción priorizado

1. **Re-ejecutar QA con `--runs 3`** tras PR #48 y #49 desplegados → confirmar cuántos TCs realmente siguen fallando.
2. **Test mal calibrado (5 min):** ajustar `not_expected` de TC-C41 T1 para que no contradiga el `check`.
3. **Bug "decoración" (~1-2h):** PR sobre Compra para no asumir `ocasion=Decoracion` desde "decorar". Resuelve TC-DECO-01 y TC-DECO-02 juntos.
4. **Bug "delegación" (~1h):** añadir regla "casos especiales" en Compra. Resuelve TC-C41 T2.
5. **Flakiness (sin fecha):** investigar Orquestador cuando haya espacio. No bloquea ventas.

## Coste total estimado

| Bloque | Esfuerzo |
|---|---|
| Re-ejecutar QA + verificar | 30 min |
| Fixes de tests | 5 min |
| Fixes de playbook (decoración + delegación) | 2-3h |
| **Total acciones inmediatas** | **~3-4h** para potencialmente resolver 6-7 de los 9 TCs |
| Flakiness (diferido) | sin estimar |

## Notas

- Este resumen es **manual**, generado el 16-may-2026 desde el QA report de esa fecha (22 PASS / 3 INESTABLE / 6 FAIL).
- En la **iteración 2** (EP-QA-07 + EP-MAS-01), este resumen se generará automáticamente con consenso multi-LLM y semáforo verde/naranja/rojo por dimensión.
- Si tras re-ejecutar el conteo de FAILs sigue siendo alto, revisar individualmente los 9 archivos `qa/tc_analysis/TC-*.md` y actualizar.
