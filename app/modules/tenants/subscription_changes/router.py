from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.modules.auth.dependencies import get_required_tenant_id
from .dependencies import require_entity_admin as require_admin
from app.modules.auth.models import Usuario
from . import service
from .schemas import QuoteRequest, QuoteResponse, ChangeRequest, CancelRequest, ChangeResponse

router = APIRouter(prefix='/api/v1/subscriptions', tags=['CU35 - Cambios de suscripción'])


@router.post('/quote', response_model=QuoteResponse)
def quote(data: QuoteRequest, db: Session=Depends(get_db), tenant: int=Depends(get_required_tenant_id),
          user: Usuario=Depends(require_admin)):
    return service.quote(db, tenant, data.plan_version_id)


@router.get('/changes', response_model=list[ChangeResponse])
def history(db: Session=Depends(get_db), tenant: int=Depends(get_required_tenant_id),
            user: Usuario=Depends(require_admin)):
    return service.list_changes(db, tenant)


@router.post('/changes', response_model=ChangeResponse, status_code=201)
def change(data: ChangeRequest, db: Session=Depends(get_db), tenant: int=Depends(get_required_tenant_id),
           user: Usuario=Depends(require_admin)):
    return service.request_change(db,tenant,user,data.idempotency_key,data.mode,data.plan_version_id,data.quote_token)


@router.post('/cancellation', response_model=ChangeResponse, status_code=201)
def cancel(data: CancelRequest, db: Session=Depends(get_db), tenant: int=Depends(get_required_tenant_id),
           user: Usuario=Depends(require_admin)):
    return service.request_change(db,tenant,user,data.idempotency_key,'CANCEL')
