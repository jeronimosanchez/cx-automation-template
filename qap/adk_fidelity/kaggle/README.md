# Cribador ADK en Kaggle (GPU, $0)

Mover la **inferencia del LLM** fuera del Mac a una GPU gratis (Kaggle). El harness,
el webhook y la rúbrica no cambian — solo el hardware donde corre el modelo.

## ⚠️ El número de Kaggle NO es comparable con el del Mac

```
Mismo modelo/quant/digest, PERO backend distinto (Metal vs CUDA) → coma flotante no asociativa
→ TCs borderline voltean. Mac 88% vs Kaggle 82% (P100). NO mezclar números entre entornos.
```
La reproducibilidad cross-hardware es **físicamente imposible** → cada entorno tiene su PROPIO baseline.
Entorno canónico = **el Mac**. Kaggle = secundario. Y la **P100 es mala** (cc 6.0, sin flash real,
fallback de build CUDA) → si usas cloud, T4 o Ampere.

## Por qué (y qué esperar)

| | |
|---|---|
| **Modelo** | el MISMO que en local: `qwen2.5:14b` q4 (digest idéntico). |
| **Coste** | €0. ~30 h/semana de GPU gratis. Sin secretos (rúbrica determinista, webhook público). Internet en kernels requiere **cuenta verificada por teléfono**. |
| **Velocidad** | modesta vs Mac; el valor real es off-Mac + presupuesto + margen para Gemma-27B. |

## Pasos

1. **Empaquetar** (en el Mac): `bash qap/adk_fidelity/kaggle/package_for_kaggle.sh` → `build/petal-fidelity.zip`
2. **Subir** ese zip a Kaggle como **Dataset**.
3. **Crear Notebook**, subir `kaggle_fidelity.ipynb`, `Settings → GPU + Internet ON + Add Input dataset`, **Run All**.
4. Celda 5 da el enlace de `fidelity_result.json`.

### Vía API (todo desde el Mac, sin la web)
```
python -m kaggle datasets create -p build/ds/        # dataset privado (con dataset-metadata.json)
python -m kaggle kernels push -p build/kernel/       # kernel con GPU+internet+dataset (kernel-metadata.json)
python -m kaggle kernels status jerosan1/petal-fidelity-run
python -m kaggle kernels output jerosan1/petal-fidelity-run -p build/kout
```
Auth: `python -m kaggle auth login` (OAuth, no hace falta pegar token).
