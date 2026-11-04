from datetime import datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict, EmailStr


class TenantRequestCreateResponse(BaseModel):
    id_request: str
    tracking_code: str
    status: str

    model_config = ConfigDict(from_attributes=True)


class TenantRequestTrackingResponse(BaseModel):
    institucion: str
    status: str
    mensaje: str
    fecha_decision: Optional[datetime] = None
    access_email: Optional[str] = None
    temporary_password: Optional[str] = None
    expires_at: Optional[datetime] = None
    remaining_reveals: Optional[int] = None

    model_config = ConfigDict(from_attributes=True)

