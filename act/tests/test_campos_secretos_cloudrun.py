"""
act/tests/test_campos_secretos_cloudrun.py — La clave de un tool no se compara ni se envía.

CX devuelve `openApiSpec.authentication.apiKeyConfig.apiKey` de dos formas según
el estado del tool: `"REDACTED"` si hay clave guardada, y nada si no la hay. El
YAML de un tool creado copiando otro arrastra la cadena literal `"REDACTED"`.

De ahí salían dos fallos de gravedad muy distinta:

  · el Paso 1 marcaba el tool como cambiado en cada vuelta, con el textSchema
    idéntico al byte — ruido que enseña a ignorar la pantalla;
  · y si ese tool llegaba a aplicarse por cualquier motivo, el PATCH escribía la
    palabra "REDACTED" como clave y el tool empezaba a dar 401 contra el
    backend, sin que nada lo explicara.

El segundo es el que hace daño, y NO lo tapa arreglar el primero. Por eso aquí
la prueba que manda es `test_el_patch_conserva_la_clave_remota`: sin ella, un
arreglo a medias —solo en la comparación— pasaría el resto del archivo.

Verificado contra la API el 2026-08-21 en el agente de Petal V2.
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from act.utils import cx_payloads_cloudrun as payloads


def _auth(**extra):
    """El bloque de autenticación de un tool, como lo escribe CX."""
    base = {"keyName": "X-API-Key", "requestLocation": "HEADER"}
    base.update(extra)
    return {"apiKeyConfig": base}


def _tool(spec="openapi: 3.0.0", auth=None):
    doc = {"displayName": "GestionPedidoTool", "toolType": "OPEN_API_TOOL",
           "openApiSpec": {"textSchema": spec}}
    if auth is not None:
        doc["openApiSpec"]["authentication"] = auth
    return doc


# ── Lo que arregla ───────────────────────────────────────────────────────────

def test_redacted_local_contra_campo_ausente_no_es_diferencia():
    """El caso real: tool sin clave en CX, YAML con la cadena literal."""
    local = _tool(auth=_auth(apiKey="REDACTED"))
    remoto = _tool(auth=_auth())          # CX no devuelve el campo
    assert not payloads.differs(remoto, local)


def test_redacted_en_los_dos_lados_tampoco():
    """Tool CON clave: CX devuelve el marcador y coincide. No debe saltar igual."""
    local = _tool(auth=_auth(apiKey="REDACTED"))
    remoto = _tool(auth=_auth(apiKey="REDACTED"))
    assert not payloads.differs(remoto, local)


def test_una_clave_de_verdad_en_el_yaml_tampoco_se_compara():
    """Aunque alguien escriba la clave real en el YAML, no es asunto del diff.

    Se ignora igual: el campo no es nuestro, venga como venga.
    """
    # Deliberadamente NO parece una clave real: el repo es público y un
    # literal con pinta de credencial dispara escáneres de secretos y enseña
    # un patrón que no queremos copiado.
    local = _tool(auth=_auth(apiKey="una-clave-cualquiera-no-real"))
    remoto = _tool(auth=_auth(apiKey="REDACTED"))
    assert not payloads.differs(remoto, local)


def test_el_patch_conserva_la_clave_remota():
    """LA PRUEBA QUE MANDA.

    Con el arreglo solo en `differs`, el recurso deja de salir marcado pero el
    PATCH sigue escribiendo "REDACTED" como clave el día que se aplique por otra
    razón. Esta comprobación es la que distingue el arreglo entero del arreglo
    a medias — se vio dejando `build_full_update_body` sin tocar: los demás
    tests del archivo pasaban y este no.
    """
    local = _tool(spec="openapi: 3.0.0  # cambio real",
                  auth=_auth(apiKey="REDACTED"))
    remoto = _tool(spec="openapi: 3.0.0", auth=_auth(apiKey="REDACTED"))

    cuerpo = payloads.build_full_update_body(
        remoto, local, ignore_fields=payloads.ignore_fields_for("tool"))

    enviado = cuerpo["openApiSpec"]["authentication"]["apiKeyConfig"]
    assert "apiKey" not in enviado, (
        "el cuerpo del PATCH lleva apiKey: sobrescribiría la clave del tool")
    # Y lo que sí es nuestro sigue viajando.
    assert enviado["keyName"] == "X-API-Key"
    assert cuerpo["openApiSpec"]["textSchema"] == "openapi: 3.0.0  # cambio real"


def test_el_patch_tampoco_devuelve_el_marcador_del_remoto():
    """El caso de PetalDataTool, que la primera versión de este archivo no cubría.

    El cuerpo del Full Update parte del REMOTO, y el remoto de un tool con clave
    trae `apiKey: "REDACTED"`. Quitarlo solo del local no bastaría si el merge
    conservara el del remoto: se le devolvería a CX su propio marcador, y no se
    sabe si lo interpreta como «déjala» o como «ponla a esa palabra».

    La primera prueba usaba un remoto SIN clave —el caso fácil— y pasaba igual.
    """
    local = _tool(spec="openapi: 3.0.0  # cambio", auth=_auth(apiKey="REDACTED"))
    remoto = _tool(spec="openapi: 3.0.0", auth=_auth(apiKey="REDACTED"))
    cuerpo = payloads.build_full_update_body(
        remoto, local, ignore_fields=payloads.ignore_fields_for("tool"))
    enviado = cuerpo["openApiSpec"]["authentication"]["apiKeyConfig"]
    assert "apiKey" not in enviado, (
        "el marcador del remoto viaja de vuelta a CX")


def test_el_post_de_creacion_tampoco_manda_la_clave():
    """Crear un tool con la palabra "REDACTED" de clave es el mismo daño,
    solo que desde el minuto cero."""
    doc = _tool(auth=_auth(apiKey="REDACTED"))
    doc["metadata"] = {"tipo": "tool", "agente": "x"}
    cuerpo = payloads.build_create_body("tool", doc)
    assert "apiKey" not in cuerpo["openApiSpec"]["authentication"]["apiKeyConfig"]


def test_no_muta_el_documento_local():
    """El cuerpo que va a la API no puede alterar el documento del que salió."""
    local = _tool(auth=_auth(apiKey="REDACTED"))
    payloads.build_full_update_body(_tool(auth=_auth()), local,
                                    ignore_fields=payloads.ignore_fields_for("tool"))
    assert local["openApiSpec"]["authentication"]["apiKeyConfig"]["apiKey"] == "REDACTED"


# ── Lo que NO debe romper ────────────────────────────────────────────────────

def test_un_cambio_real_del_spec_se_sigue_detectando():
    """El arreglo no puede volver ciego al comparador.

    Sin esto, poner `openApiSpec` entero en la lista de ignorados también haría
    pasar los tests de arriba, y el tool dejaría de desplegarse nunca.
    """
    local = _tool(spec="openapi: 3.0.0  # nuevo endpoint", auth=_auth(apiKey="REDACTED"))
    remoto = _tool(spec="openapi: 3.0.0", auth=_auth())
    assert payloads.differs(remoto, local)


def test_otro_campo_de_authentication_si_se_compara():
    """Solo el secreto se ignora. `keyName` y `requestLocation` son nuestros."""
    local = _tool(auth=_auth(apiKey="REDACTED", keyName="X-Otra-Cabecera"))
    remoto = _tool(auth=_auth(apiKey="REDACTED"))
    assert payloads.differs(remoto, local)


def test_un_parametro_llamado_apikey_en_otro_sitio_no_se_cuela():
    """El nombre se ignora a cualquier profundidad, y eso tiene un límite.

    Si algún día un recurso tuviera un campo de contenido llamado `apiKey`, esta
    prueba fallaría y avisaría de que la regla por nombre se quedó corta. Hoy no
    ocurre: el único `apiKey` del sistema es el del tool.
    """
    nombres = []
    for tipo in ("playbook", "example", "tool", "agent_config", "flow"):
        nombres.extend(payloads.IGNORE_FIELDS_BY_TYPE.get(tipo, []))
    assert "apiKey" not in nombres, (
        "apiKey se gestiona por CAMPOS_SECRETOS, no por la lista de ignorados")


def test_los_otros_tipos_no_cambian():
    """Un playbook sin `apiKey` en ninguna parte se comporta igual que antes."""
    local = {"displayName": "Compra", "goal": "vender"}
    assert not payloads.differs({"displayName": "Compra", "goal": "vender"}, local)
    assert payloads.differs({"displayName": "Compra", "goal": "otro"}, local)
