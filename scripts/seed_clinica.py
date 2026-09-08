# DEPRECATED: Este archivo ha sido unificado en scripts/seed.py
# Ejecuta directamente scripts/seed.py para poblar clínicas, superadmins y usuarios.
import sys
import os

sys.path.insert(0, os.path.realpath(os.path.join(os.path.dirname(__file__), "..")))
from scripts.seed import seed_database

if __name__ == "__main__":
    print("[AVISO] scripts/seed_clinica.py está obsoleto. Redirigiendo a scripts/seed.py...")
    seed_database()
