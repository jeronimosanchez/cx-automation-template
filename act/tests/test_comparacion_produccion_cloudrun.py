"""
act/tests/test_comparacion_produccion_cloudrun.py — Comparar borrador y versión.

CX devuelve **lo mismo escrito de dos formas** según de dónde se lea: una
referencia entre resources sale por nombre en el borrador y resuelta a
identificador en la versión congelada, y un secreto sale como `REDACTED` al leer
el borrador y entero dentro de la versión.

Comparando en crudo, todo contenedor que mencionara a otro salía como distinto
de producción **en cada publicación**, y el Paso 5 lo versionaba otra vez —
quemando huecos de un límite que en CX es real: 100 versiones por playbook, 50
por tool. Se vio en Petal V2: 7 de 11 contenedores marcados como cambiados
inmediatamente después de publicarlos.

La mitad de estos tests comprueba que esos dos casos dejan de contar. La otra
mitad, que el comparador sigue viendo lo que sí cambia — sin ella, «0 cambiados»
no distingue un arreglo de una ceguera.
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from act import act_cx_resources_deploy_cloudrun as pipeline


NOMBRES = {("PLAYBOOK", "Handoff"): "9d0d211b", ("TOOL", "PetalDataTool"): "39e35fac"}


def _playbook(texto):
    return {"name": "p/playbooks/x", "displayName": "Gestion_Deuda",
            "instruction": {"steps": [{"text": texto}]}}


def _huella(item, hijos=None):
    return pipeline._huella_contenedor(item, hijos or {}, NOMBRES)


# ── Lo que NO es un cambio ───────────────────────────────────────────────────

def test_la_misma_referencia_por_nombre_o_por_id_es_la_misma():
    """El borrador dice el nombre; la versión, el identificador."""
    assert (_huella(_playbook("Escala a ${PLAYBOOK:Handoff} y termina."))
            == _huella(_playbook("Escala a ${PLAYBOOK:9d0d211b} y termina.")))


def test_tambien_para_tools_y_flows():
    assert (_huella(_playbook("Llama a ${TOOL:PetalDataTool}."))
            == _huella(_playbook("Llama a ${TOOL:39e35fac}.")))


def test_un_secreto_oculto_no_cuenta_como_cambio():
    """La API nunca enseña la clave del borrador, así que no hay nada que comparar.

    Fingir que se compara es lo que dejaba el tool marcado como cambiado para
    siempre: `REDACTED` contra la clave real nunca iban a coincidir.
    """
    oculto = {"name": "p/tools/t", "displayName": "PetalDataTool",
              "openApiSpec": {"authentication": {"apiKeyConfig": {
                  "keyName": "X-API-Key", "apiKey": "REDACTED",
                  "requestLocation": "HEADER"}}}}
    entera = {"name": "p/tools/t", "displayName": "PetalDataTool",
              "openApiSpec": {"authentication": {"apiKeyConfig": {
                  "keyName": "X-API-Key", "apiKey": "mUaaZ6MBCJDiPCTHcFUD",
                  "requestLocation": "HEADER"}}}}
    assert _huella(oculto) == _huella(entera)


def test_una_referencia_a_algo_que_no_esta_en_el_mapa_se_deja_como_viene():
    """No se inventa un identificador para lo que no se conoce."""
    a = _huella(_playbook("Escala a ${PLAYBOOK:NoExiste}."))
    b = _huella(_playbook("Escala a ${PLAYBOOK:NoExiste}."))
    c = _huella(_playbook("Escala a ${PLAYBOOK:OtroQueTampoco}."))
    assert a == b and a != c


# ── Lo que SÍ es un cambio ──────────────────────────────────────────────────
#
# Sin esta mitad, «0 cambiados» no distingue un comparador arreglado de uno
# ciego, y un cambio real no llegaría nunca a producción.

def test_un_cambio_de_texto_sigue_viendose():
    assert (_huella(_playbook("Escala a ${PLAYBOOK:Handoff}."))
            != _huella(_playbook("NO escales a ${PLAYBOOK:Handoff}.")))


def test_cambiar_el_destino_de_una_referencia_sigue_viendose():
    """Renombrar el destino no es un cambio; apuntar a otro sitio sí."""
    assert (_huella(_playbook("Escala a ${PLAYBOOK:Handoff}."))
            != _huella(_playbook("Escala a ${PLAYBOOK:Checkout}.")))


def test_lo_demas_de_la_autenticacion_sigue_comparandose():
    """Solo el valor del secreto queda fuera, no el resto de la configuración."""
    def tool(key_name, donde):
        return {"name": "p/tools/t", "displayName": "T",
                "openApiSpec": {"authentication": {"apiKeyConfig": {
                    "keyName": key_name, "apiKey": "REDACTED",
                    "requestLocation": donde}}}}
    assert _huella(tool("X-API-Key", "HEADER")) != _huella(tool("X-Otra", "HEADER"))
    assert _huella(tool("X-API-Key", "HEADER")) != _huella(tool("X-API-Key", "QUERY"))


def test_un_hijo_que_cambia_sigue_viendose():
    base = _playbook("Igual.")
    uno = {"e1": {"name": "p/examples/e1", "displayName": "Ex", "description": "a"}}
    otro = {"e1": {"name": "p/examples/e1", "displayName": "Ex", "description": "b"}}
    assert _huella(base, uno) != _huella(base, otro)


def test_un_hijo_de_menos_sigue_viendose():
    base = _playbook("Igual.")
    dos = {"e1": {"displayName": "Ex1"}, "e2": {"displayName": "Ex2"}}
    uno = {"e1": {"displayName": "Ex1"}}
    assert _huella(base, dos) != _huella(base, uno)


def test_el_orden_de_los_hijos_no_cuenta():
    """CX no garantiza el orden del LIST, y la huella no puede depender de él."""
    base = _playbook("Igual.")
    a = {"e1": {"displayName": "Ex1"}, "e2": {"displayName": "Ex2"}}
    b = {"e2": {"displayName": "Ex2"}, "e1": {"displayName": "Ex1"}}
    assert _huella(base, a) == _huella(base, b)
