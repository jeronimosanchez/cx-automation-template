"""Pytest config — anade el repo root a sys.path para que los tests
puedan importar `from src.X import ...` sin necesidad de instalar el
paquete ni manipular sys.path en cada test file.
"""
import os
import sys

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)
