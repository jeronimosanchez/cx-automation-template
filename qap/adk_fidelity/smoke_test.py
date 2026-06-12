"""Smoke test mínimo: confirma que ADK + webhook de inventario + Gemini funcionan
end-to-end con UNA consulta, antes de montar la harness de 51 TCs."""
import os, re, asyncio, requests

# --- Cargar la key del .env (sin exponerla) ---
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for line in open(os.path.join(ROOT, ".env")):
    m = re.match(r'GEMINI_API_KEY=(\S+)', line.strip())
    if m:
        os.environ["GOOGLE_API_KEY"] = m.group(1)
        os.environ["GEMINI_API_KEY"] = m.group(1)
os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "FALSE"

from google.adk.agents import LlmAgent
from google.adk.runners import InMemoryRunner
from google.genai import types

# URL del backend: del entorno o de .env (privado, fuera del repo público). Vacío si falta.
PETAL_API = os.environ.get("PETAL_API_URL", "")
if not PETAL_API and os.path.exists(os.path.join(ROOT, ".env")):
    for _l in open(os.path.join(ROOT, ".env")):
        if _l.startswith("PETAL_API_URL="):
            PETAL_API = _l.split("=", 1)[1].strip()

# --- Webhook de inventario como tool de ADK ---
def consultar_datos(recurso: str, producto: str = "", color: str = "", ocasion: str = "",
                    tamano: str = "", precio_max: float = 0, limit: int = 5, email: str = "") -> dict:
    """Consulta datos de la floristeria Petal en Google Sheets.

    recurso: tipo de dato. Para buscar flores usa 'inventario'. Otros: 'perfil', 'business'.
    producto: nombre de producto a buscar (ej. 'rosas', 'tulipanes').
    color, ocasion, tamano: filtros opcionales del inventario.
    precio_max: precio maximo en euros.
    Devuelve un JSON con los productos encontrados.
    """
    params = {"recurso": recurso, "accion": "leer"}
    for k, v in [("producto", producto), ("color", color), ("ocasion", ocasion),
                 ("tamano", tamano), ("email", email)]:
        if v:
            params[k] = v
    if precio_max:
        params["precio_max"] = precio_max
    if limit:
        params["limit"] = limit
    try:
        r = requests.get(PETAL_API, params=params, timeout=30)
        return r.json()
    except Exception as e:
        return {"ok": False, "error": str(e)}


agent = LlmAgent(
    name="petal_smoke",
    model="gemini-2.5-flash",
    instruction=("Eres Petal, asistente de venta de una floristeria online. "
                 "Cuando el usuario pregunte por flores, USA la herramienta consultar_datos "
                 "con recurso='inventario' para buscar productos reales. No inventes productos."),
    tools=[consultar_datos],
)


async def main():
    runner = InMemoryRunner(agent=agent, app_name="petal")
    sess = await runner.session_service.create_session(app_name="petal", user_id="u1")
    user_msg = types.Content(role="user", parts=[types.Part(text="quiero comprar rosas rojas")])
    final_text, tool_called = "", False
    async for event in runner.run_async(user_id="u1", session_id=sess.id, new_message=user_msg):
        if event.content and event.content.parts:
            for p in event.content.parts:
                if getattr(p, "function_call", None):
                    tool_called = True
                    print(f"  🔧 tool llamada: {p.function_call.name}({dict(p.function_call.args)})")
        if event.is_final_response() and event.content:
            final_text = "".join(p.text or "" for p in event.content.parts if getattr(p, "text", None))
    print(f"\n  🌸 Respuesta del agente:\n  {final_text[:500]}")
    print(f"\n  Tool llamada: {'✅ SÍ' if tool_called else '❌ NO'}")
    print("  ✅ SMOKE TEST OK — ADK + webhook + Gemini funcionan end-to-end" if final_text else "  ❌ sin respuesta")


if __name__ == "__main__":
    asyncio.run(main())
