# Re-exports for backward compatibility
from app.modules.auth.login.schemas import (
    UsuarioCreate,
    UsuarioResponse,
    LoginRequest,
    TokenResponse,
    RefreshTokenRequest,
)
from app.modules.auth.logout.schemas import LogoutRequest
from app.modules.auth.password_recovery.schemas import (
    ForgotPasswordRequest,
    ForgotPasswordResponse,
    ResetPasswordRequest,
)
from app.modules.auth.users_management.schemas import (
    AdminUserCreate,
    AdminUserUpdate,
    AdminUserStatusUpdate,
    AdminUserResponse,
)
from app.modules.auth.roles_permissions.schemas import (
    RoleBase,
    RoleCreate,
    RoleUpdate,
    RoleStatusUpdate,
    RoleResponse,
    PermissionResponse,
    RolePermissionsUpdate,
)
