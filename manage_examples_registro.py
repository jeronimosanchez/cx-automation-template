#!/usr/bin/env python3
"""
manage_examples_registro.py — Crea 3 Examples para Playbook Registro_Task
Sesion 60 — Floristeria Petal

Examples:
  Ex_Reg_01 — Particular con "no, es un bajo" (captura de planta + slot filling de letra)
  Ex_Reg_02 — Datos multiples en un turno
  Ex_Reg_03 — Empresa con CIF

Basado en patron de manage_examples_v2.py (S45) actualizado:
  - action = "consultarDatos" (operationId actual de la spec v3.9.0; antes era "petaldatatool")
  - auto-detect del Playbook Registro_Task via LIST playbooks (no se hardcodea ID)
  - tipo (no tipo_cliente) en inputActionParameters segun spec OpenAPI

Uso:
  python3 manage_examples_registro.py --list-playbooks   # ver playbooks del agente
  python3 manage_examples_registro.py --dry-run          # simula sin crear
  python3 manage_examples_registro.py                    # crea de verdad
"""

import argparse, json, sys, requests, google.auth, google.auth.transport.requests

PROJECT = "floristeria-petal-digital"
LOCATION = "europe-west1"
AGENT_ID = "745375ba-ac7e-4eb8-b8a0-d742891f2aa4"
BASE = f"https://{LOCATION}-dialogflow.googleapis.com/v3beta1"
PARENT = f"projects/{PROJECT}/locations/{LOCATION}/agents/{AGENT_ID}"
TOOL_PETAL = f"{PARENT}/tools/39e35fac-e018-4e98-b735-e45cb761bf5c"

# Display name del Playbook a buscar. Cambiar si el nombre real es distinto.
PLAYBOOK_DISPLAY_NAME = "Registro_Task"


def get_headers():
    creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/dialogflow"])
    creds.refresh(google.auth.transport.requests.Request())
    return {
        "Authorization": f"Bearer {creds.token}",
        "Content-Type": "application/json",
        "x-goog-user-project": PROJECT,
    }


def list_playbooks(headers):
    """Lista playbooks del agente. Devuelve [(name_full_path, displayName), ...]."""
    r = requests.get(f"{BASE}/{PARENT}/playbooks", headers=headers)
    if r.status_code != 200:
        print(f"  \u274c Error listando playbooks {r.status_code}: {r.text}")
        return []
    data = r.json()
    return [(pb["name"], pb.get("displayName", "")) for pb in data.get("playbooks", [])]


def find_playbook_by_name(headers, display_name):
    """Busca Playbook por displayName y devuelve path completo, o None."""
    pbs = list_playbooks(headers)
    matches = [name for name, dn in pbs if dn.lower() == display_name.lower()]
    if not matches:
        print(f"  \u274c No se encontro Playbook con displayName '{display_name}'")
        if pbs:
            print(f"     Playbooks disponibles:")
            for _, dn in pbs:
                print(f"       - {dn}")
        return None
    if len(matches) > 1:
        print(f"  \u26a0  Hay {len(matches)} playbooks con displayName '{display_name}'. Uso el primero.")
    return matches[0]


def create_example(headers, parent_path, body, dry_run=False):
    print(f"  \u2795 CREAR: {body['displayName']}")
    if dry_run:
        print("     (dry-run, no se envia)")
        return True
    r = requests.post(f"{BASE}/{parent_path}/examples", headers=headers, json=body)
    if r.status_code == 200:
        print(f"     \u2705 Creado")
        return True
    else:
        print(f"     \u274c Error {r.status_code}: {r.text}")
        return False


# ===============================================================
# EXAMPLES
# ===============================================================

EX_REG_01 = {
    "displayName": "Ex_Reg_01 — Particular con bajo (captura planta + slot filling letra)",
    "actions": [
        # Tool inicial: agent_copy/leer/bienvenida_nuevo_cliente
        {"toolUse": {
            "tool": TOOL_PETAL,
            "action": "consultarDatos",
            "inputActionParameters": {
                "recurso": "agent_copy",
                "accion": "leer",
                "clave": "bienvenida_nuevo_cliente",
            },
            "outputActionParameters": {
                "200": {
                    "ok": True,
                    "recurso": "agent_copy",
                    "resultados": [{"valor": "\u00a1Perfecto! Vamos a registrarte. Solo necesito unos datos."}],
                },
            },
        }},
        {"agentUtterance": {"text": "\u00a1Perfecto! Vamos a registrarte. Solo necesito unos datos. Para registrarte, necesito tu correo electronico."}},
        {"userUtterance": {"text": "zara.vidal@correo.com"}},
        {"agentUtterance": {"text": "Entendido. \u00bfCual es tu nombre?"}},
        {"userUtterance": {"text": "Zara"}},
        {"agentUtterance": {"text": "Zara. \u00bfY tus apellidos?"}},
        {"userUtterance": {"text": "Vidal"}},
        {"agentUtterance": {"text": "Vidal, anotado. \u00bfEres particular o empresa?"}},
        {"userUtterance": {"text": "particular"}},
        {"agentUtterance": {"text": "Perfecto. Indicame tu direccion completa: calle con numero, portal, planta y letra si aplica, codigo postal y ciudad."}},
        {"userUtterance": {"text": "Paseo del Prado 22, Madrid"}},
        {"agentUtterance": {"text": "Paseo del Prado 22, Madrid. \u00bfTu codigo postal?"}},
        {"userUtterance": {"text": "28014"}},
        {"agentUtterance": {"text": "\u00bfTu direccion incluye portal, planta o letra?"}},
        {"userUtterance": {"text": "No, es un bajo"}},
        {"agentUtterance": {"text": "Bajo, anotado. \u00bfY la letra?"}},
        {"userUtterance": {"text": "no, no hay letra"}},
        {"agentUtterance": {"text": "Vale, sin letra. \u00bfTienes un telefono de contacto? Facilita mucho las entregas."}},
        {"userUtterance": {"text": "611222333"}},
        {"agentUtterance": {"text": "Antes de completar tu registro, revisa tus datos:\n\u2022 Nombre: Zara Vidal\n\u2022 Email: zara.vidal@correo.com\n\u2022 Tipo: particular\n\u2022 Direccion: Paseo del Prado 22, bajo, 28014 Madrid\n\u2022 Telefono: 611222333\n\u00bfEs todo correcto? Revisa especialmente la direccion — portal, planta y letra si aplica."}},
        {"userUtterance": {"text": "Si, correcto"}},
        # Tool final: registro/crear
        {"toolUse": {
            "tool": TOOL_PETAL,
            "action": "consultarDatos",
            "inputActionParameters": {
                "recurso": "registro",
                "accion": "crear",
                "email": "zara.vidal@correo.com",
                "nombre": "Zara",
                "apellidos": "Vidal",
                "tipo": "particular",
                "calle": "Paseo del Prado 22, bajo",
                "codigo_postal": "28014",
                "ciudad": "Madrid",
                "telefono": "611222333",
            },
            "outputActionParameters": {
                "200": {
                    "ok": True,
                    "recurso": "registro",
                    "id_cliente": "155",
                    "nombre": "Zara",
                    "apellidos": "Vidal",
                    "email": "zara.vidal@correo.com",
                    "tipo": "particular",
                    "tier": "Nuevo",
                },
            },
        }},
        {"agentUtterance": {"text": "\u00a1Perfecto, Zara! Ya estas registrado/a. Continuamos con lo que me pedias."}},
    ],
    "playbookOutput": {
        "actionParameters": {
            "id_cliente": "155",
            "nombre_cliente": "Zara",
            "apellidos": "Vidal",
            "email": "zara.vidal@correo.com",
            "tipo_cliente": "particular",
            "Direccion_Habitual": "Paseo del Prado 22, bajo, 28014 Madrid",
            "telefono": "611222333",
            "recien_registrado": True,
            "estado_pago": "Al dia",
            "sesion_cerrada": False,
            "razon_handoff": "",
        }
    },
}


EX_REG_02 = {
    "displayName": "Ex_Reg_02 — Datos multiples en un turno",
    "actions": [
        {"toolUse": {
            "tool": TOOL_PETAL,
            "action": "consultarDatos",
            "inputActionParameters": {
                "recurso": "agent_copy",
                "accion": "leer",
                "clave": "bienvenida_nuevo_cliente",
            },
            "outputActionParameters": {
                "200": {
                    "ok": True,
                    "recurso": "agent_copy",
                    "resultados": [{"valor": "\u00a1Perfecto! Vamos a registrarte. Solo necesito unos datos."}],
                },
            },
        }},
        {"agentUtterance": {"text": "\u00a1Perfecto! Vamos a registrarte. Solo necesito unos datos. Para registrarte, necesito tu correo electronico."}},
        {"userUtterance": {"text": "Soy Marcos Ruiz, mi correo es marcos.ruiz@empresa.es"}},
        {"agentUtterance": {"text": "Marcos Ruiz, anotado. \u00bfEres particular o empresa?"}},
        {"userUtterance": {"text": "particular, vivo en Calle Mayor 5, 2A, 28013 Madrid"}},
        {"agentUtterance": {"text": "Perfecto, particular. Calle Mayor 5, 2A, 28013 Madrid. \u00bfTienes un telefono de contacto? Facilita mucho las entregas."}},
        {"userUtterance": {"text": "no tengo, gracias"}},
        {"agentUtterance": {"text": "Antes de completar tu registro, revisa tus datos:\n\u2022 Nombre: Marcos Ruiz\n\u2022 Email: marcos.ruiz@empresa.es\n\u2022 Tipo: particular\n\u2022 Direccion: Calle Mayor 5, 2A, 28013 Madrid\n\u2022 Telefono: no facilitado\n\u00bfEs todo correcto? Revisa especialmente la direccion — portal, planta y letra si aplica."}},
        {"userUtterance": {"text": "si"}},
        {"toolUse": {
            "tool": TOOL_PETAL,
            "action": "consultarDatos",
            "inputActionParameters": {
                "recurso": "registro",
                "accion": "crear",
                "email": "marcos.ruiz@empresa.es",
                "nombre": "Marcos",
                "apellidos": "Ruiz",
                "tipo": "particular",
                "calle": "Calle Mayor 5, 2A",
                "codigo_postal": "28013",
                "ciudad": "Madrid",
            },
            "outputActionParameters": {
                "200": {
                    "ok": True,
                    "recurso": "registro",
                    "id_cliente": "156",
                    "nombre": "Marcos",
                    "apellidos": "Ruiz",
                    "email": "marcos.ruiz@empresa.es",
                    "tipo": "particular",
                    "tier": "Nuevo",
                },
            },
        }},
        {"agentUtterance": {"text": "\u00a1Genial, Marcos! Ya estas registrado/a. Continuamos con lo que me pedias."}},
    ],
    "playbookOutput": {
        "actionParameters": {
            "id_cliente": "156",
            "nombre_cliente": "Marcos",
            "apellidos": "Ruiz",
            "email": "marcos.ruiz@empresa.es",
            "tipo_cliente": "particular",
            "Direccion_Habitual": "Calle Mayor 5, 2A, 28013 Madrid",
            "telefono": "",
            "recien_registrado": True,
            "estado_pago": "Al dia",
            "sesion_cerrada": False,
            "razon_handoff": "",
        }
    },
}


EX_REG_03 = {
    "displayName": "Ex_Reg_03 — Empresa con CIF",
    "actions": [
        {"toolUse": {
            "tool": TOOL_PETAL,
            "action": "consultarDatos",
            "inputActionParameters": {
                "recurso": "agent_copy",
                "accion": "leer",
                "clave": "bienvenida_nuevo_cliente",
            },
            "outputActionParameters": {
                "200": {
                    "ok": True,
                    "recurso": "agent_copy",
                    "resultados": [{"valor": "\u00a1Perfecto! Vamos a registrarte. Solo necesito unos datos."}],
                },
            },
        }},
        {"agentUtterance": {"text": "\u00a1Perfecto! Vamos a registrarte. Solo necesito unos datos. Para registrarte, necesito tu correo electronico."}},
        {"userUtterance": {"text": "info@logisticasur.com"}},
        {"agentUtterance": {"text": "Vale. \u00bfCual es tu nombre?"}},
        {"userUtterance": {"text": "Lorena"}},
        {"agentUtterance": {"text": "Lorena. \u00bfY tus apellidos?"}},
        {"userUtterance": {"text": "Pereira Mota"}},
        {"agentUtterance": {"text": "Anotado. \u00bfEres particular o empresa?"}},
        {"userUtterance": {"text": "empresa"}},
        {"agentUtterance": {"text": "Como empresa, necesito tu CIF o NIF fiscal."}},
        {"userUtterance": {"text": "B87123456"}},
        {"agentUtterance": {"text": "B87123456, recibido. Indicame la direccion completa: calle con numero, portal, planta y letra si aplica, codigo postal y ciudad."}},
        {"userUtterance": {"text": "Avenida de la Industria 45, planta 3, oficina B, 41020 Sevilla"}},
        {"agentUtterance": {"text": "Perfecto. \u00bfTienes un telefono de contacto? Facilita mucho las entregas."}},
        {"userUtterance": {"text": "954112233"}},
        {"agentUtterance": {"text": "Antes de completar tu registro, revisa tus datos:\n\u2022 Nombre: Lorena Pereira Mota\n\u2022 Email: info@logisticasur.com\n\u2022 Tipo: empresa\n\u2022 CIF: B87123456\n\u2022 Direccion: Avenida de la Industria 45, planta 3, oficina B, 41020 Sevilla\n\u2022 Telefono: 954112233\n\u00bfEs todo correcto? Revisa especialmente la direccion — portal, planta y letra si aplica."}},
        {"userUtterance": {"text": "todo correcto"}},
        {"toolUse": {
            "tool": TOOL_PETAL,
            "action": "consultarDatos",
            "inputActionParameters": {
                "recurso": "registro",
                "accion": "crear",
                "email": "info@logisticasur.com",
                "nombre": "Lorena",
                "apellidos": "Pereira Mota",
                "tipo": "empresa",
                "cif": "B87123456",
                "calle": "Avenida de la Industria 45, planta 3, oficina B",
                "codigo_postal": "41020",
                "ciudad": "Sevilla",
                "telefono": "954112233",
            },
            "outputActionParameters": {
                "200": {
                    "ok": True,
                    "recurso": "registro",
                    "id_cliente": "157",
                    "nombre": "Lorena",
                    "apellidos": "Pereira Mota",
                    "email": "info@logisticasur.com",
                    "tipo": "empresa",
                    "tier": "Nuevo",
                },
            },
        }},
        {"agentUtterance": {"text": "Listo, Lorena. Ya estas registrado/a. Continuamos con lo que me pedias."}},
    ],
    "playbookOutput": {
        "actionParameters": {
            "id_cliente": "157",
            "nombre_cliente": "Lorena",
            "apellidos": "Pereira Mota",
            "email": "info@logisticasur.com",
            "tipo_cliente": "empresa",
            "Direccion_Habitual": "Avenida de la Industria 45, planta 3, oficina B, 41020 Sevilla",
            "telefono": "954112233",
            "recien_registrado": True,
            "estado_pago": "Al dia",
            "sesion_cerrada": False,
            "razon_handoff": "",
        }
    },
}


def main():
    parser = argparse.ArgumentParser(description="Subir 3 Examples al Playbook Registro_Task")
    parser.add_argument("--dry-run", action="store_true", help="No envia POST, solo simula")
    parser.add_argument("--list-playbooks", action="store_true", help="Solo lista los playbooks del agente")
    parser.add_argument("--only", choices=["EX_REG_01", "EX_REG_02", "EX_REG_03"], help="Crear solo un Example especifico")
    args = parser.parse_args()

    print("\U0001f511 Obteniendo token...")
    headers = get_headers()

    # Modo solo listing
    if args.list_playbooks:
        print(f"\n\U0001f4cb Playbooks del agente {AGENT_ID}:")
        pbs = list_playbooks(headers)
        for name, dn in pbs:
            short_id = name.split("/")[-1]
            print(f"   {dn:35s}  ID: {short_id}")
        return 0

    # Resolucion del Playbook Registro_Task
    print(f"\n\U0001f50d Buscando Playbook con displayName '{PLAYBOOK_DISPLAY_NAME}'...")
    parent_path = find_playbook_by_name(headers, PLAYBOOK_DISPLAY_NAME)
    if not parent_path:
        return 1
    short_id = parent_path.split("/")[-1]
    print(f"   \u2713 Encontrado: ID {short_id}")

    # Crear los Examples (todos o el seleccionado por --only)
    all_examples = {"EX_REG_01": EX_REG_01, "EX_REG_02": EX_REG_02, "EX_REG_03": EX_REG_03}
    if args.only:
        examples_to_create = [all_examples[args.only]]
    else:
        examples_to_create = list(all_examples.values())

    stats = {"creados": 0, "errores": 0}
    print(f"\n\U0001f4dd Creando {len(examples_to_create)} Example(s) {'(DRY-RUN)' if args.dry_run else ''}...\n")

    for body in examples_to_create:
        if create_example(headers, parent_path, body, args.dry_run):
            stats["creados"] += 1
        else:
            stats["errores"] += 1

    print(f"\n{'='*50}")
    print(f"\U0001f4ca RESUMEN {'(DRY-RUN)' if args.dry_run else ''}")
    print(f"   Creados: {stats['creados']}")
    print(f"   Errores: {stats['errores']}")
    print(f"{'='*50}")

    return 0 if stats["errores"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
