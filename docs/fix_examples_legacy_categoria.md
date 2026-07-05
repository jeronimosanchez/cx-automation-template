# Fix: migración param legacy `categoria` → `ocasion` (examples Compra)

Fecha: 2026-07-05
Scope: SOLO 3 examples de `definitions/examples/compra/`. No se tocó exd, exa, exc, exh ni ningún otro.

## Cambio aplicado

En `inputActionParameters` de los `toolUse`, se reemplazó el param muerto `categoria: <valor minúscula>` por `ocasion: <Valor normalizado>` (7 ocasiones válidas, primera en mayúscula). Se subió el sufijo de versión en el `displayName`. Se preservó `id`, `playbook` y toda la estructura conversacional.

| Archivo | id (preservado) | displayName | Cambios |
|---|---|---|---|
| `exb_v15_funeral_tipoproducto_con_filtros.yaml` | `838860ed-db3b-4d67-8449-5f3af4165830` | ExB v15 → **v16** | `categoria: funeral` → `ocasion: Funeral` (1 toolUse) |
| `exf_v15_g3_boda_pregunta_abierta_rechaza_alternativas.yaml` | `7ef37b01-6698-42d3-95e1-6ed6b377a7ac` | ExF v15 → **v16** | `categoria: boda` → `ocasion: Boda` (1 toolUse) |
| `exg_v15_refinamiento_progresivo_filtros_acumulados.yaml` | `e4b848ff-bd82-4e39-912a-c03a34225861` | ExG v15 → **v16** | `categoria: regalo` → `ocasion: Regalo` (2 toolUse) |

## executionSummary

Ningún `executionSummary` de los 3 examples mencionaba "categoria". No requirió cambios.

## Bonus (campos muertos de inventario)

No aplicó. Los 3 examples usan `outputActionParameters.resultado` como string plano (p.ej. `resultado: opciones funeral encontradas`), no resultados estructurados de inventario. Por tanto no había `Flores_Tallos`, `Categoria_Uso`, ni `Producto` con color/talla embebidos que normalizar. No se consultó el backend.

## Validación

Los 3 `.yaml` pasan `yaml.safe_load` sin error. `grep categoria` sobre los 3 archivos: 0 coincidencias.
