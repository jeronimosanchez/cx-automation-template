"""Genera kaggle_fidelity.ipynb (JSON válido garantizado).
Regenerar tras tocar las celdas: python _gen_notebook.py
Las celdas se documentan aquí; el .ipynb es el artefacto que se sube a Kaggle.
"""
import json, os

MD = lambda s: {"cell_type": "markdown", "metadata": {}, "source": s}
CODE = lambda s: {"cell_type": "code", "metadata": {}, "execution_count": None, "outputs": [], "source": s}

cells = [
    MD(
        "# Cribador ADK — fidelidad vs CX (en GPU Kaggle, $0)\n"
        "\n"
        "Corre el MISMO modelo que en local (`qwen2.5:14b` q4 vía Ollama) sobre GPU → "
        "**fidelidad NO idéntica al Mac** (backend distinto: Metal vs CUDA → coma flotante → "
        "algunos TCs borderline voltean). Baseline propio por entorno.\n"
        "\n"
        "**Antes de ejecutar:**\n"
        "1. `Settings → Accelerator → GPU`\n"
        "2. `Settings → Internet → ON` (requiere cuenta verificada por teléfono)\n"
        "3. Sube el bundle (`package_for_kaggle.sh`) como **Dataset** y adjúntalo (`Add Input`).\n"
    ),
    MD("## 1 · Ollama + GPU"),
    CODE(
        "import os, subprocess, time, shutil\n"
        "# El instalador de Ollama necesita zstd para descomprimir; la imagen Kaggle no lo trae.\n"
        "subprocess.run('apt-get update -qq && apt-get install -y -qq zstd', shell=True)\n"
        "r = subprocess.run('curl -fsSL https://ollama.com/install.sh | sh', shell=True, capture_output=True, text=True)\n"
        "print('install rc:', r.returncode); print(r.stdout[-600:]); print(r.stderr[-600:])\n"
        "# El binario suele ir a /usr/local/bin, pero ese dir puede NO estar en el PATH del kernel Kaggle.\n"
        "ollama = shutil.which('ollama') or '/usr/local/bin/ollama'\n"
        "assert os.path.exists(ollama), f'ollama NO instalado en {ollama}'\n"
        "os.environ['PATH'] = os.path.dirname(ollama) + ':' + os.environ.get('PATH', '')\n"
        "os.environ['OLLAMA_FLASH_ATTENTION'] = '1'\n"
        "os.environ['OLLAMA_CONTEXT_LENGTH'] = '32768'   # el prompt de Petal (~32k) cabe sin truncar\n"
        "os.environ['OLLAMA_HOST'] = '127.0.0.1:11434'\n"
        "subprocess.Popen([ollama, 'serve'], env={**os.environ})\n"
        "time.sleep(8)\n"
        "print('ollama en', ollama, '· serve lanzado')"
    ),
    CODE(
        "# Descarga del modelo (~9 GB, requiere Internet ON). Tarda unos minutos la 1a vez.\n"
        "# PATH + OLLAMA_HOST ya quedaron en os.environ (celda anterior) → los hereda el shell.\n"
        "!ollama pull qwen2.5:14b\n"
        "!nvidia-smi --query-gpu=name,memory.total,memory.used --format=csv\n"
        "!ollama list"
    ),
    MD("## 2 · Dependencias Python"),
    CODE("!pip install -q google-adk litellm google-genai pyyaml requests"),
    MD("## 3 · Reconstruir el repo desde el Dataset\n"
       "Auto-detecta el bundle dentro de `/kaggle/input` (sin importar el slug del dataset)."),
    CODE(
        "import glob, os, shutil, zipfile\n"
        "DST = '/kaggle/working/repo'\n"
        "if os.path.exists(DST): shutil.rmtree(DST)\n"
        "# Kaggle puede dejar el dataset como ZIP o ya extraído → soportamos ambos.\n"
        "zips = glob.glob('/kaggle/input/**/*.zip', recursive=True)\n"
        "if zips:\n"
        "    with zipfile.ZipFile(zips[0]) as z: z.extractall('/kaggle/working/_extract')\n"
        "    base = '/kaggle/working/_extract'\n"
        "else:\n"
        "    base = '/kaggle/input'\n"
        "cands = glob.glob(base + '/**/definitions', recursive=True)\n"
        "assert cands, f'No encuentro definitions/ en {base} — ¿adjuntaste el Dataset?'\n"
        "SRC = os.path.dirname(cands[0])\n"
        "shutil.copytree(SRC, DST)\n"
        "if not os.path.exists(DST + '/.env'):\n"
        "    open(DST + '/.env', 'w').write('GEMINI_API_KEY=unused-on-kaggle\\n')\n"
        "print('repo →', DST, '·', sorted(os.listdir(DST)))"
    ),
    MD("## 4 · Correr la fidelidad\n"
       "`ADK_RECON=multi` → multi-agente. Quítalo para la reconstrucción plana.\n"
       "`--limit N` para una prueba corta; sin flag = los 51 TCs."),
    CODE(
        "RECON = 'multi'          # 'multi' | 'flat'\n"
        "LIMIT = ''               # ej. '--limit 8' para prueba corta; '' = los 51\n"
        "env = ('ADK_RECON=multi ' if RECON == 'multi' else '')\n"
        "cmd = (f'cd /kaggle/working/repo && OLLAMA_API_BASE=http://127.0.0.1:11434 '\n"
        "       f'OLLAMA_FLASH_ATTENTION=1 OLLAMA_CONTEXT_LENGTH=32768 {env}'\n"
        "       f'python -u qap/adk_fidelity/run_fidelity.py {LIMIT}')\n"
        "print(cmd)\n"
        "get_ipython().system(cmd)"
    ),
    MD("## 5 · Descargar el resultado"),
    CODE(
        "from IPython.display import FileLink\n"
        "p = '/kaggle/working/repo/qap/adk_fidelity/fidelity_result.json'\n"
        "import shutil; shutil.copy(p, '/kaggle/working/fidelity_result.json')\n"
        "FileLink('/kaggle/working/fidelity_result.json')"
    ),
]

nb = {
    "cells": cells,
    "metadata": {
        "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
        "language_info": {"name": "python"},
        "accelerator": "GPU",
    },
    "nbformat": 4,
    "nbformat_minor": 5,
}

out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "kaggle_fidelity.ipynb")
json.dump(nb, open(out, "w"), ensure_ascii=False, indent=1)
print("escrito:", out)
