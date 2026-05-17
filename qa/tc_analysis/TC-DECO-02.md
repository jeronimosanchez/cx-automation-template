---
status: FAIL
tipo: Bug Playbook
estimacion: ~45 min
---

## T1

#### 📥 Input parseado

El usuario expresó: `tipo=Ramo`, `producto=rosas`, `ocasión=Decoración` (de "para decorar mi salón").

#### 🎯 Comportamiento observado

El agente NO encontró rosas. Mostró alternativas (Tulipanes Mix, Hortensias Blanco, Hortensias Azul). Clasificó correctamente como **G5** (gracias al fix Orquestador del PR #61).

#### 🔍 Causa raíz

Compra llamó a la tool con `producto=rosas + tipo=Ramo + categoria=Decoracion`. Pero:

- El catálogo **NO** tiene ramos de rosas con `Categoria_Uso=Decoracion` (todos los ramos de rosas tienen `Categoria_Uso=Regalo`).
- **SÍ existen rosas para decoración** en forma de Centros de Mesa (2 productos: `Centro de Mesa Rosas y Eucalipto` S/M).
- Pero esos Centros de Mesa NO pasan el filtro `tipo=Ramo` → tool devuelve 0 → fallback genérico → muestra Tulipanes/Hortensias.

#### 📊 Diagnóstico

Bug del playbook: falta lógica de **fallback escalonado** (relajar 1 filtro a la vez antes del fallback total). Hoy Compra hace fallback directo al genérico, perdiendo los matches relevantes que existen relajando solo el filtro `tipo`.

Nota: el backend filtra `producto=X` en la columna `Producto` del sheet (nombre comercial completo), no en `Flor`. Los Centros de Mesa con rosas pasan el filtro `producto=rosas` porque contienen "Rosas" en su nombre.

## Recomendación

**Fix propuesto**: añadir bloque `FALLBACK ESCALONADO` en sección `# CASOS ESPECIALES` del playbook Compra.

Cuando filtros estrictos devuelven 0 resultados:

- **Paso 1**: informar explícitamente del filtro no cumplido ("No tengo ramos de rosas para decoración").
- **Paso 2**: relajar UN filtro a la vez en este orden: `tipo` → `categoría` → `producto`.
- **Paso 3**: mostrar hasta 3 opciones combinando los matches escalonados:
  - Centro de Mesa con rosas (mismo producto, distinto formato)
  - Ramos de rosas tradicionales (mismo producto, otro uso)
  - Alternativas de decoración (otras flores)

**Validación esperada**: tras el fix, re-ejecutar el QA. TC-DECO-02 debería pasar mostrando los 2 Centros de Mesa Rosas y Eucalipto entre las opciones.

**Coste estimado**: ~45 min (edit playbook + PR + deploy + QA).
