from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.modules.auth.logout.schemas import LogoutRequest
from app.modules.auth.logout.service import revoke_user_session

router = APIRouter(tags=["Autenticación - Logout (CU24)"])


@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Cerrar sesión",
    description="Revoca la sesión del usuario y todos sus tokens emitidos incrementando token_version y registrando en blacklist.",
)
def logout(request_data: LogoutRequest, request: Request, db: Session = Depends(get_db)):
    """Revoca los tokens incrementando la versión de sesión del usuario."""
    client_ip = request.headers.get("x-forwarded-for") or (request.client.host if request.client else None)
    if client_ip and "," in client_ip:
        client_ip = client_ip.split(",")[0].strip()
    revoke_user_session(db=db, refresh_token=request_data.refresh_token, client_ip=client_ip)
    return None
