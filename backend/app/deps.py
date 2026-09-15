"""FastAPI 依赖：当前登录用户（Cookie 会话或 Bearer 令牌）、管理员校验。"""
import contextvars
import hashlib
from datetime import datetime
from typing import Optional

# 当前请求的用户 id（供模型用量记录等无法直接拿到 user 的地方使用）
current_user_id: contextvars.ContextVar[Optional[int]] = contextvars.ContextVar("current_user_id", default=None)

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from .db import get_db
from .models import ApiToken, User
from .services import auth as auth_service

API_TOKEN_PREFIX = "ddt_"


def read_token(request: Request) -> Optional[str]:
    """优先 Cookie，其次 Authorization: Bearer。"""
    token = request.cookies.get(auth_service.SESSION_COOKIE)
    if token:
        return token
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return None


def user_from_api_token(db: Session, token: str) -> Optional[User]:
    if not token.startswith(API_TOKEN_PREFIX):
        return None
    h = hashlib.sha256(token.encode()).hexdigest()
    row = db.query(ApiToken).filter(ApiToken.token_hash == h).first()
    if row is None:
        return None
    if row.expires_at and row.expires_at < datetime.now():
        return None
    row.last_used_at = datetime.now()
    db.commit()
    user = db.get(User, row.user_id)
    return user if user and user.is_active and user.is_approved else None


def resolve_user(request: Request, db: Session) -> Optional[User]:
    token = read_token(request) or ""
    if not token:
        return None
    if token.startswith(API_TOKEN_PREFIX):
        return user_from_api_token(db, token)
    user = auth_service.get_session_user(db, token)
    if user is not None and (not user.is_active or not user.is_approved):
        return None
    return user


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    user = resolve_user(request, db)
    if user is None:
        raise HTTPException(status_code=401, detail="未登录或会话已过期")
    current_user_id.set(user.id)
    return user


def require_admin(user: User = Depends(get_current_user)) -> User:
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="需要管理员权限")
    return user
