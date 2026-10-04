"""Caso de uso clinicas dentro del dominio auth (project.md §4).

Super Admin SaaS: listar clínicas, cambiar estado operativo y
onboarding público (registro de clínica + admin inicial).
"""

from app.modules.auth.clinicas.router import router

__all__ = ["router"]
