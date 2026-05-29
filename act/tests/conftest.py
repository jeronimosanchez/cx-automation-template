"""Pytest config — anade el repo root a sys.path para que los tests
puedan importar `from act.X import ...` sin necesidad de instalar el
paquete ni manipular sys.path en cada test file.

Este conftest vive en act/tests/, por lo que el repo root esta 3 niveles
por encima (act/tests -> act -> repo root).
"""
import os
import sys

_REPO_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)
