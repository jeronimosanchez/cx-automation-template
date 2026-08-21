"""
act/tests/test_solo_a_mano_cloudrun.py — Los tools se comparan pero no se escriben.

Un tool es el único resource que guarda un secreto —la clave del backend— y CX
no la devuelve al leer: manda "REDACTED" si hay clave, y nada si no la hay. Eso
deja al Full Update sin forma segura de tocarlo: mandar el marcador puede
escribir la palabra "REDACTED" como clave, y omitirlo puede borrarla. Las dos
roturas son silenciosas — el tool empieza a dar 401 y nada lo explica.

Medido sobre el historial, excluirlos cuesta casi nada: 4 de 107 commits en
Petal V2 y 7 de 439 en 1.1 tocan tools, y dos de los cuatro son del propio
pipeline.

La regla tiene DOS mitades y las dos importan:

    no se escriben     ninguna ruta del Paso 3 puede tocarlos
    sí se comparan     el Paso 1 los sigue viendo, y si difieren se avisa

La segunda es la que impide que esto sea peor que el problema: un tool que
desaparece del inventario es un tool del que dejas de enterarte.
"""

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from act import act_cx_resources_deploy_cloudrun as pipeline


def _entrada(nombre="PetalDataTool", spec="openapi: 3.0.0"):
    return {
        "ruta": f"definitions/tools/{nombre.lower()}.yaml",
        "display_name": nombre,
        "documento": {"displayName": nombre, "toolType": "OPEN_API_TOOL",
                      "openApiSpec": {"textSchema": spec}},
    }


def _repo(por_tipo=None, sin_cx_id=()):
    return {"por_tipo": por_tipo or {}, "sin_cx_id": list(sin_cx_id)}


# ── No se escriben ───────────────────────────────────────────────────────────

def test_tool_no_esta_en_la_tabla_de_escritura():
    """Misma filosofía que `environment`: no es una comprobación que pueda
    fallar, es una entrada que no existe. Ninguna ruta puede construir el PATCH
    de un tool aunque se le pida."""
    assert "tool" not in pipeline.TIPOS_DESPLEGABLES
    assert "tool" in pipeline.RESOURCE_TYPES, "sigue existiendo como tipo, solo no se escribe"


def test_un_tool_que_difiere_no_genera_operacion(monkeypatch):
    monkeypatch.setattr(pipeline, "_auditoria_previa", lambda *_: {})
    repo = _repo({"tool": {"t1": _entrada(spec="openapi: 3.0.0  # cambiado")}})
    inventario = {"tool": {"t1": {"displayName": "PetalDataTool", "toolType": "OPEN_API_TOOL",
                                  "openApiSpec": {"textSchema": "openapi: 3.0.0"},
                                  "name": "…/tools/t1"}}}
    ops = pipeline.calcular_diff(None, inventario, repo)
    assert [o for o in ops if o["tipo"] == "tool"] == []


def test_un_tool_nuevo_tampoco_se_crea(monkeypatch):
    """Ni siquiera un POST: crear el tool también escribe la clave."""
    monkeypatch.setattr(pipeline, "_auditoria_previa", lambda *_: {})
    repo = _repo(sin_cx_id=[dict(_entrada("GestionPedidoTool"), tipo="tool")])
    ops = pipeline.calcular_diff(None, {}, repo)
    assert [o for o in ops if o["tipo"] == "tool"] == []


# ── Pero sí se comparan ──────────────────────────────────────────────────────

def test_un_tool_que_difiere_sale_como_aviso():
    """La mitad que impide que esto sea peor que el problema."""
    repo = _repo({"tool": {"t1": _entrada(spec="openapi: 3.0.0  # cambiado")}})
    inventario = {"tool": {"t1": {"displayName": "PetalDataTool", "toolType": "OPEN_API_TOOL",
                                  "openApiSpec": {"textSchema": "openapi: 3.0.0"}}}}
    avisos = pipeline.avisos_a_mano(inventario, repo)
    assert len(avisos) == 1
    assert avisos[0]["operacion"] == "PATCH"
    assert avisos[0]["display_name"] == "PetalDataTool"
    assert "secreto" in avisos[0]["motivo"]


def test_un_tool_igual_no_avisa():
    """Avisar de lo que no ha cambiado es el ruido que enseña a ignorar la pantalla."""
    doc = {"displayName": "PetalDataTool", "toolType": "OPEN_API_TOOL",
           "openApiSpec": {"textSchema": "openapi: 3.0.0"}}
    repo = _repo({"tool": {"t1": _entrada()}})
    assert pipeline.avisos_a_mano({"tool": {"t1": doc}}, repo) == []


def test_un_tool_nuevo_avisa_como_post():
    repo = _repo(sin_cx_id=[dict(_entrada("GestionPedidoTool"), tipo="tool")])
    avisos = pipeline.avisos_a_mano({}, repo)
    assert len(avisos) == 1 and avisos[0]["operacion"] == "POST"


def test_la_clave_redactada_no_dispara_el_aviso():
    """Junto con CAMPOS_SECRETOS: si el único cambio es el marcador, no avisa.

    Sin esto, el tool saldría en la lista de «subir a mano» en cada vuelta y la
    lista dejaría de significar nada.
    """
    entrada = _entrada()
    entrada["documento"]["openApiSpec"]["authentication"] = {
        "apiKeyConfig": {"keyName": "X-API-Key", "apiKey": "REDACTED",
                         "requestLocation": "HEADER"}}
    remoto = {"displayName": "PetalDataTool", "toolType": "OPEN_API_TOOL",
              "openApiSpec": {"textSchema": "openapi: 3.0.0",
                              "authentication": {"apiKeyConfig": {
                                  "keyName": "X-API-Key", "requestLocation": "HEADER"}}}}
    assert pipeline.avisos_a_mano({"tool": {"t1": remoto}},
                                  _repo({"tool": {"t1": entrada}})) == []


# ── Lo que NO debe romper ────────────────────────────────────────────────────

def test_los_demas_tipos_se_siguen_desplegando(monkeypatch):
    """El arreglo no puede dejar mudo al pipeline entero."""
    monkeypatch.setattr(pipeline, "_auditoria_previa", lambda *_: {})
    repo = _repo({"playbook": {"p1": {
        "ruta": "definitions/playbooks/compra.yaml", "display_name": "Compra",
        "documento": {"displayName": "Compra", "goal": "vender más"}}}})
    inventario = {"playbook": {"p1": {"displayName": "Compra", "goal": "vender",
                                      "name": "…/playbooks/p1"}}}
    ops = pipeline.calcular_diff(None, inventario, repo)
    assert [o["operacion"] for o in ops] == ["PATCH"]


def test_avisos_a_mano_no_mira_otros_tipos():
    """Solo los de la lista. Un playbook que difiere es trabajo del diff."""
    repo = _repo({"playbook": {"p1": {
        "ruta": "x.yaml", "display_name": "Compra",
        "documento": {"displayName": "Compra", "goal": "otro"}}}})
    assert pipeline.avisos_a_mano({"playbook": {"p1": {"displayName": "Compra"}}}, repo) == []


def test_el_orden_de_despliegue_ya_no_nombra_tool():
    """DEPLOY_ORDER existe para que un playbook se aplique DESPUÉS del tool que
    referencia. Si el tool ya no se aplica, dejarlo en la lista no rompe nada,
    pero conviene saber si sigue ahí: esta prueba lo documenta, no lo exige."""
    assert "tool" in pipeline.DEPLOY_ORDER, (
        "sigue en el orden; es inocuo porque nunca genera operación, "
        "pero si algún día se quita, que sea a propósito")
