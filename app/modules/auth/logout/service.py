from fastapi import HTTPException, status
from sqlalchemy.orm import Session
from app.core.security import decode_refresh_token
from app.modules.auth.models import TokenBlacklist, Usuario


def revoke_user_session(db: Session, refresh_token: str) -> None:
    payload = decode_refresh_token(refresh_token)
    user_id_str = payload.get("sub")
    try:
        user_id = int(user_id_str)
    except (TypeError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token inválido",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user = db.query(Usuario).filter(Usuario.id_usuario == user_id).first()
    if user:
        user.token_version += 1
        # Registrar en blacklist
        blacklist_entry = TokenBlacklist(token=refresh_token[:500])
        db.add(blacklist_entry)
        db.commit()
