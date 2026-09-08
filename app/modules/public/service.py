from fastapi import HTTPException, status
from sqlalchemy.orm import Session
from app.core.security import hash_password
from app.modules.auth.models import Clinica, Rol, Usuario
from app.modules.public.schemas import ClinicaRegistroRequest


def registrar_clinica(db: Session, data: ClinicaRegistroRequest) -> tuple[Clinica, Usuario]:
    """
    Registers a new clinic along with its initial tenant administrator account.
    """
    # 1. Validate email uniqueness
    existing_user = db.query(Usuario).filter(Usuario.correo == data.admin_email).first()
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El correo electrónico ya está registrado en la plataforma",
        )

    # 2. Validate NIT uniqueness if provided
    if data.nit:
        existing_nit = db.query(Clinica).filter(Clinica.nit == data.nit).first()
        if existing_nit:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="El NIT ya está registrado",
            )

    try:
        # 3. Create Clinic
        nueva_clinica = Clinica(
            nombre=data.nombre,
            razon_social=data.razon_social,
            nit=data.nit,
            telefono=data.telefono,
            direccion=data.direccion,
            estado="ACTIVO",
        )
        db.add(nueva_clinica)
        db.flush()

        # 4. Create or assign Tenant Admin Role
        admin_rol = Rol(
            id_clinica=nueva_clinica.id_clinica,
            nombre="Administrador",
            descripcion="Administrador principal de la clínica",
            estado="ACTIVO",
        )
        db.add(admin_rol)
        db.flush()

        # 5. Create Tenant Admin User
        admin_usuario = Usuario(
            id_clinica=nueva_clinica.id_clinica,
            id_rol=admin_rol.id_rol,
            nombres=data.admin_nombres,
            apellidos=data.admin_apellidos,
            correo=data.admin_email,
            password_hash=hash_password(data.admin_password),
            estado="ACTIVO",
        )
        db.add(admin_usuario)
        db.commit()
        db.refresh(nueva_clinica)
        db.refresh(admin_usuario)

        return nueva_clinica, admin_usuario
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error al registrar la clínica: {str(e)}",
        )
