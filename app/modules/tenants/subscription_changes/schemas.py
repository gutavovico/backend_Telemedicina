from datetime import datetime
from decimal import Decimal
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field
from app.modules.auth.planes.schemas import VersionResponse


class QuoteRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    plan_version_id: int = Field(strict=True, gt=0)


class ChangeRequest(QuoteRequest):
    mode: Literal['IMMEDIATE', 'NEXT_CYCLE']
    idempotency_key: str = Field(min_length=8, max_length=64)
    quote_token: str | None = Field(default=None, max_length=3000)


class CancelRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    idempotency_key: str = Field(min_length=8, max_length=64)


class QuoteResponse(BaseModel):
    amount: Decimal
    currency: Literal['BOB'] = 'BOB'
    effective_at: datetime
    cycle_end: datetime
    quote_token: str
    expires_at: datetime


class ChangeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    source_version_id: int
    target_version_id: int | None
    operation: str
    status: str
    amount: Decimal
    effective_at: datetime
    applied_at: datetime | None
    payment_id: str | None
    reason: str | None
    checkout_url: str | None = None
    target_version: VersionResponse | None = None
