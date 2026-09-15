"""个人访问令牌（供 MCP 客户端 / 移动 App / 脚本使用）。明文只在创建时返回一次。"""
import hashlib
import secrets
from datetime import datetime, timedelta
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import API_TOKEN_PREFIX, get_current_user
from ..models import ApiToken, User

router = APIRouter(prefix="/api/tokens", tags=["tokens"])


class TokenOut(BaseModel):
    id: int
    name: str
    prefix: str
    scopes: str
    created_at: datetime
    last_used_at: Optional[datetime]
    expires_at: Optional[datetime]


class TokenCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=60)
    scopes: str = Field("all", pattern="^(all|read|mcp|app)$")
    expires_days: Optional[int] = Field(None, ge=1, le=3650)


class TokenCreated(TokenOut):
    token: str  # 明文，仅此一次


def _out(t: ApiToken) -> TokenOut:
    return TokenOut(id=t.id, name=t.name, prefix=t.prefix, scopes=t.scopes, created_at=t.created_at,
                    last_used_at=t.last_used_at, expires_at=t.expires_at)


@router.get("", response_model=List[TokenOut])
def list_tokens(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    rows = db.scalars(select(ApiToken).where(ApiToken.user_id == user.id).order_by(ApiToken.id.desc())).all()
    return [_out(t) for t in rows]


@router.post("", response_model=TokenCreated, status_code=201)
def create_token(payload: TokenCreate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    raw = API_TOKEN_PREFIX + secrets.token_urlsafe(32)
    t = ApiToken(user_id=user.id, name=payload.name.strip(), token_hash=hashlib.sha256(raw.encode()).hexdigest(),
                 prefix=raw[:10], scopes=payload.scopes,
                 expires_at=(datetime.now() + timedelta(days=payload.expires_days)) if payload.expires_days else None)
    db.add(t)
    db.commit()
    db.refresh(t)
    return TokenCreated(**_out(t).model_dump(), token=raw)


@router.delete("/{token_id}", status_code=204)
def revoke_token(token_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    t = db.get(ApiToken, token_id)
    if not t or t.user_id != user.id:
        raise HTTPException(status_code=404, detail="令牌不存在")
    db.delete(t)
    db.commit()
    return None
