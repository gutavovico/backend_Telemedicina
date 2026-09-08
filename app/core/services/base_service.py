from typing import Any, Optional, Type
from fastapi import HTTPException, status
from sqlalchemy.orm import Query, Session
from app.modules.auth.models import Clinica


class TenantAwareService:
    """
    Base service class for tenant-isolated data operations.
    Enforces that all queries, validations, and injections are strictly scoped to the active tenant.
    """
    Model: Optional[Type[Any]] = None

    def __init__(self, db: Session, tenant: Clinica):
        self.db = db
        self.tenant = tenant
        self.tenant_id = tenant.id_clinica

    def filter_by_tenant(self, query: Query, model: Optional[Type[Any]] = None) -> Query:
        """Applies tenant isolation filter to a query for the service model."""
        target_model = model or self.Model
        if target_model is None:
            raise ValueError("Model must be defined on TenantAwareService or passed explicitly.")
        if hasattr(target_model, "id_clinica"):
            return query.filter(target_model.id_clinica == self.tenant_id)
        return query

    def validate_ownership(self, obj: Any) -> bool:
        """Validates that a resource belongs to the active tenant."""
        if obj is None:
            return False
        return getattr(obj, "id_clinica", None) == self.tenant_id

    def get_or_404(self, model_class: Type[Any], pk_field: str, pk_value: Any) -> Any:
        """
        Retrieves an entity by primary key strictly within the active tenant.
        Returns 404 if the entity does not exist OR belongs to another tenant (zero information leakage).
        """
        query = self.db.query(model_class).filter(getattr(model_class, pk_field) == pk_value)
        if hasattr(model_class, "id_clinica"):
            query = query.filter(model_class.id_clinica == self.tenant_id)
        
        entity = query.first()
        if not entity:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Recurso no encontrado"
            )
        return entity

    def inject_tenant(self, obj: Any) -> Any:
        """Injects the active tenant ID into a model instance or dict."""
        if isinstance(obj, dict):
            obj["id_clinica"] = self.tenant_id
        else:
            setattr(obj, "id_clinica", self.tenant_id)
        return obj
