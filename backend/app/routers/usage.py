"""模型用量与余额：用户看自己的用量；管理员看全站用量、余额与单价设置。"""
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import get_current_user, require_admin
from ..models import User
from ..services import usage as usage_service

router = APIRouter(prefix="/api/usage", tags=["usage"])


class PriceIn(BaseModel):
    input_per_1k: Optional[float] = Field(None, ge=0)
    output_per_1k: Optional[float] = Field(None, ge=0)
    currency: Optional[str] = Field(None, max_length=8)


@router.get("/summary")
def get_summary(db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> Dict[str, Any]:
    return usage_service.summary(db, user.id, user.is_admin)


@router.get("/balance")
def get_balance(db: Session = Depends(get_db), _admin: User = Depends(require_admin)) -> Dict[str, Any]:
    return usage_service.balance(db)


@router.put("/price")
def put_price(payload: PriceIn, db: Session = Depends(get_db), _admin: User = Depends(require_admin)) -> Dict[str, Any]:
    return usage_service.set_price(db, payload.model_dump(exclude_none=True))
