"""管理员：用户管理（创建、停用、审核、重置密码、改角色、删除）、注册开关与注册审核开关。"""
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import require_admin
from ..models import AuthSession, Meal, User
from ..services import auth as auth_service

router = APIRouter(prefix="/api/admin/users", tags=["admin"])


class UserOut(BaseModel):
    id: int
    username: str
    display_name: Optional[str]
    role: str
    is_active: bool
    is_approved: bool = True
    totp_enabled: bool
    created_at: datetime
    meal_count: int = 0


class UserCreate(BaseModel):
    username: str = Field(..., min_length=2, max_length=40, pattern=r"^[A-Za-z0-9_\-\.一-龥]+$")
    password: str = Field(..., min_length=8, max_length=200)
    role: str = Field("user", pattern="^(admin|user)$")
    display_name: Optional[str] = Field(None, max_length=40)


class UserPatch(BaseModel):
    role: Optional[str] = Field(None, pattern="^(admin|user)$")
    is_active: Optional[bool] = None
    is_approved: Optional[bool] = None
    display_name: Optional[str] = Field(None, max_length=40)
    new_password: Optional[str] = Field(None, min_length=8, max_length=200)
    reset_totp: Optional[bool] = None


def _out(db: Session, u: User) -> UserOut:
    n = db.scalar(select(func.count()).select_from(Meal).where(Meal.user_id == u.id)) or 0
    return UserOut(id=u.id, username=u.username, display_name=u.display_name, role=u.role, is_active=u.is_active,
                   is_approved=bool(u.is_approved), totp_enabled=bool(u.totp_enabled), created_at=u.created_at, meal_count=n)


@router.get("", response_model=List[UserOut])
def list_users(db: Session = Depends(get_db), _admin: User = Depends(require_admin)):
    return [_out(db, u) for u in db.scalars(select(User).order_by(User.id)).all()]


class RegistrationIn(BaseModel):
    allow_registration: Optional[bool] = None
    require_approval: Optional[bool] = None


def _registration_out(db: Session) -> dict:
    from .auth import approval_required, registration_enabled
    pending = db.scalar(select(func.count()).select_from(User).where(User.is_approved == False)) or 0  # noqa: E712
    return {"allow_registration": registration_enabled(db), "require_approval": approval_required(db),
            "pending_count": int(pending)}


@router.get("/registration")
def get_registration(db: Session = Depends(get_db), _admin: User = Depends(require_admin)):
    return _registration_out(db)


@router.put("/registration")
def put_registration(payload: RegistrationIn, db: Session = Depends(get_db), _admin: User = Depends(require_admin)):
    from ..models import Setting
    from .auth import APPROVAL_KEY, REGISTRATION_KEY
    for key, val in ((REGISTRATION_KEY, payload.allow_registration), (APPROVAL_KEY, payload.require_approval)):
        if val is None:
            continue
        row = db.get(Setting, key)
        value = "1" if val else "0"
        if row is None:
            db.add(Setting(key=key, value=value))
        else:
            row.value = value
    db.commit()
    return _registration_out(db)


@router.post("/{user_id}/approve", response_model=UserOut)
def approve_user(user_id: int, db: Session = Depends(get_db), _admin: User = Depends(require_admin)):
    """审核通过待注册用户。拒绝 = 直接删除该用户（DELETE /{user_id}）。"""
    u = db.get(User, user_id)
    if not u:
        raise HTTPException(status_code=404, detail="用户不存在")
    u.is_approved = True
    db.commit()
    db.refresh(u)
    try:
        from ..services import notify
        notify.send_inbox(db, u.id, notify.Message(title="账号审核已通过", text="管理员已通过你的注册申请，现在可以正常使用了。",
                                                    sms_params=[]), "admin_notice")
    except Exception:  # noqa: BLE001
        pass
    return _out(db, u)


@router.post("", response_model=UserOut, status_code=201)
def create_user(payload: UserCreate, db: Session = Depends(get_db), _admin: User = Depends(require_admin)):
    if auth_service.get_user_by_name(db, payload.username):
        raise HTTPException(status_code=400, detail="用户名已存在")
    u = auth_service.create_user(db, payload.username, payload.password, payload.role, payload.display_name)
    return _out(db, u)


@router.patch("/{user_id}", response_model=UserOut)
def patch_user(user_id: int, payload: UserPatch, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    u = db.get(User, user_id)
    if not u:
        raise HTTPException(status_code=404, detail="用户不存在")
    if payload.role is not None:
        if u.id == admin.id and payload.role != "admin":
            raise HTTPException(status_code=400, detail="不能取消自己的管理员身份")
        u.role = payload.role
    if payload.is_active is not None:
        if u.id == admin.id and not payload.is_active:
            raise HTTPException(status_code=400, detail="不能停用自己")
        u.is_active = payload.is_active
        if not payload.is_active:
            db.query(AuthSession).filter(AuthSession.user_id == u.id).delete()
    if payload.is_approved is not None:
        if u.id == admin.id and not payload.is_approved:
            raise HTTPException(status_code=400, detail="不能取消自己的审核状态")
        u.is_approved = payload.is_approved
    if payload.display_name is not None:
        u.display_name = payload.display_name.strip() or None
    if payload.new_password:
        u.password_hash = auth_service.hash_password(payload.new_password)
        db.query(AuthSession).filter(AuthSession.user_id == u.id).delete()
    if payload.reset_totp:
        u.totp_enabled = False
        u.totp_secret = None
        u.totp_pending_secret = None
        u.backup_codes = None
    db.commit()
    db.refresh(u)
    return _out(db, u)


@router.delete("/{user_id}", status_code=204)
def delete_user(user_id: int, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    u = db.get(User, user_id)
    if not u:
        raise HTTPException(status_code=404, detail="用户不存在")
    if u.id == admin.id:
        raise HTTPException(status_code=400, detail="不能删除自己")
    db.delete(u)  # 级联删除该用户全部数据
    db.commit()
    return None
