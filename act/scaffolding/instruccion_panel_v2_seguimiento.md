# Seguimiento — dos ajustes sobre el HTML ya optimizado

**Archivo:** `docs/panels/act_cx_resources_deploy_v2.html`
**Contexto:** la instrucción anterior (`instruccion_panel_v2_tools_proyecto.md`) está
aplicada y correcta — verificado punto por punto. Estos dos ajustes son por cambios en
el pipeline **posteriores** a esa instrucción, no por nada mal hecho.

---

## 1 · Vincular ya no escribe nada en el repositorio

`cx-deploy.yaml` se retiró del pipeline el 2026-08-08. Era un marcador en la raíz del
repositorio que decía de qué proyecto era, y **nadie lo leía nunca**: se escribía y no se
consultaba. Encima el Paso 1 lo contaba como un YAML más del repositorio, ensuciando sus
cifras. El vínculo vive donde se consulta, en el registro del proyecto.

Con esto, **vincular un proyecto no escribe absolutamente nada en el repositorio**: lee
la rama principal para comprobar que llega, y apunta la correspondencia. Dos campos, un
botón. Es lo que Jero pidió: «solo decir este proyecto va con este repositorio y listo».

### Qué hay que cambiar

| Dónde | Ahora dice | Debe decir |
|---|---|---|
| **T.1.1** | «…comprueba que llega al repositorio, registra el vínculo y deja un marcador `cx-deploy.yaml` en la rama principal» | «…comprueba que llega al repositorio y registra el vínculo. No escribe nada dentro del repositorio.» |
| **T.1.3** | «El vínculo proyecto→repositorio, el marcador `cx-deploy.yaml`, y el comando `gcloud`…» | «El vínculo proyecto→repositorio y el comando `gcloud` que hay que ejecutar una vez, a mano.» |
| **T.1.4** | «En el repositorio (`cx-deploy.yaml` en la rama principal, solo la primera vez) y en el registro del proyecto» | «Solo en el registro del proyecto. **En el repositorio no escribe nada**: leerlo, para comprobar que llega, es todo lo que hace con él.» |
| **Registro en vivo** | 3 líneas, la última `✓ cx-deploy.yaml creado` | 2 líneas: `✓ acceso al repositorio` · `✓ repositorio del proyecto registrado` |
| **Badge de la pantalla** | `escribe en el repositorio` (write-gh) | **`solo lectura`** (read) — ya no escribe en GitHub |

Quitar también cualquier mención a **S23** que quede en el panel: la decisión se retira
con el archivo. Si algún día hace falta declarar algo por repositorio, se creará
entonces, junto con quien lo lea.

El contrato de `link_project_repo` pierde el campo `commit`: ya no hay commit que
devolver. Queda `repo` · `rama_principal` · `ya_estaba` · `comando_iam`.

---

## 2 · El Paso 1 avisa si al agente le falta el entorno de producción

Sin entorno de producción el Paso 5 no tiene dónde publicar y falla — pero fallaba **al
final**, con el agente ya escrito y el pipeline entero recorrido. El dato lo tiene el
Paso 1 desde siempre: inventaría los entornos junto con todo lo demás. Solo faltaba
mirarlo y decirlo donde todavía no cuesta nada arreglarlo.

`step_1_inventory` devuelve ahora **`tiene_entorno_produccion`** (booleano), y su
registro en vivo emite una línea de aviso cuando falta.

### Qué hay que añadir

**En el resultado del Paso 1**, cuando `tiene_entorno_produccion` es `false`, un aviso
naranja debajo de las cuatro tarjetas, del mismo estilo que el de «este proyecto no
tiene repositorio vinculado»:

> ⚠ **Este agente no tiene entorno de producción.**
> El Paso 5 publica apuntando el entorno `production` a las versiones nuevas; sin él no
> hay dónde publicar. Créalo en la consola de Dialogflow CX — el panel despliega, no
> crea infraestructura.

**No bloquea el paso.** Los Pasos 1 a 4 funcionan igual sin entorno: se inventaría, se
trae, se aplica al borrador y se valida. Lo único que no se puede es publicar. Así que
el aviso informa y deja seguir; quien vaya a quedarse en el borrador no tiene por qué
crear un entorno para eso.

**En la línea de cierre del Paso 1** —la que hoy dice «48 resources en total · leídos de
`staging` · commit `98fcbdd` · 2 sin agente asignado»— añadir al final, solo cuando
falte: `· sin entorno de producción`, en naranja, como el contador de huérfanos.

### Specs que hay que tocar

**1.3 — Qué produce.** Añadir al final:

> Y una advertencia si al agente le falta el entorno de producción: se detecta aquí, que
> es donde todavía no cuesta nada, en vez de en el Paso 5, que es donde impide publicar
> después de haber escrito ya en el agente.

**Criterios de evaluación del Paso 1** — añadir uno:

> 14. Si al agente le falta el entorno de producción, el Paso 1 lo dice y deja seguir:
> los cuatro primeros pasos no lo necesitan, solo publicar. Y lo dice en el mismo sitio
> donde se elige el agente, no cinco pasos después.

### Contrato actualizado

`step_1_inventory(project, agent_id)` → además de lo que ya devolvía:
`tiene_entorno_produccion` (bool).
