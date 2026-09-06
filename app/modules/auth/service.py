# Re-exports for backward compatibility
from app.modules.auth.login.service import (
    authenticate_user,
    create_user,
    get_user_by_email,
    get_user_by_id,
)
from app.modules.auth.logout.service import revoke_user_session
from app.modules.auth.password_recovery.service import (
    FORGOT_PASSWORD_GENERIC,
    request_password_reset,
    reset_password,
)
from app.modules.auth.users_management.service import (
    create_admin_user,
    get_user_detail,
    list_users,
    set_user_status,
    update_admin_user,
)
from app.modules.auth.roles_permissions.service import (
    create_role,
    get_role_detail,
    get_role_permissions,
    list_permissions,
    list_roles,
    replace_role_permissions,
    set_role_status,
    update_role,
)
