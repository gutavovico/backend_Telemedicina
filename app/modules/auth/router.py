from fastapi import APIRouter
from app.modules.auth.login.router import router as login_router
from app.modules.auth.logout.router import router as logout_router
from app.modules.auth.password_recovery.router import router as password_recovery_router
from app.modules.auth.users_management.router import router as users_management_router
from app.modules.auth.roles_permissions.router import router as roles_permissions_router
from app.modules.auth.audit.router import router as audit_router

router = APIRouter()

# 1. Endpoints de sesión, perfil y recuperación bajo /auth
auth_subrouter = APIRouter(prefix="/auth")
auth_subrouter.include_router(login_router)
auth_subrouter.include_router(logout_router)
auth_subrouter.include_router(password_recovery_router)

# Montar en router maestro
router.include_router(auth_subrouter)

# 2. Endpoints de Usuarios (CU02) - accesible tanto en /users como en /auth/users
router.include_router(users_management_router)
router.include_router(users_management_router, prefix="/auth")

# 3. Endpoints de Roles y Permisos (CU26) - accesible en /roles, /permissions y /auth/roles
router.include_router(roles_permissions_router)
router.include_router(roles_permissions_router, prefix="/auth")

# 4. Endpoints de Bitácora de Auditoría (CU21) - accesible en /api/v1/audit-log, /audit-log y /auth/audit-log
router.include_router(audit_router)
router.include_router(audit_router, prefix="/api/v1")
router.include_router(audit_router, prefix="/auth")

