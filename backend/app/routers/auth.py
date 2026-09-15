"""登录 / 登出 / 两步验证 / 修改密码。"""
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .. import config
from ..db import get_db
from ..deps import get_current_user, read_token
from ..models import User
from ..services import auth as auth_service

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _set_cookie(response: Response, token: str, remember: bool, request: Request) -> None:
    max_age = (auth_service.SESSION_DAYS_REMEMBER if remember else auth_service.SESSION_DAYS) * 86400
    secure = request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https"
    response.set_cookie(auth_service.SESSION_COOKIE, token, max_age=max_age, httponly=True,
                        samesite="lax", secure=secure, path="/")


class LoginIn(BaseModel):
    username: str = Field(..., min_length=1, max_length=40)
    password: str = Field(..., min_length=1, max_length=200)
    remember: bool = False


class TotpLoginIn(BaseModel):
    pending_token: str
    code: str = Field(..., min_length=4, max_length=12)


class PasswordChangeIn(BaseModel):
    current_password: str
    new_password: str = Field(..., min_length=8, max_length=200)


class TotpSetupIn(BaseModel):
    password: str


class TotpEnableIn(BaseModel):
    code: str


class TotpDisableIn(BaseModel):
    password: str
    code: str


class MeOut(BaseModel):
    id: int
    username: str
    display_name: Optional[str] = None
    role: str = "user"
    is_admin: bool = False
    totp_enabled: bool
    backup_codes_left: int
    sessions: int


def _me(db: Session, user: User) -> MeOut:
    import json
    left = len(json.loads(user.backup_codes)) if user.backup_codes else 0
    from ..models import AuthSession
    n = db.query(AuthSession).filter(AuthSession.user_id == user.id).count()
    return MeOut(id=user.id, username=user.username, display_name=user.display_name, role=user.role,
                 is_admin=user.is_admin, totp_enabled=bool(user.totp_enabled), backup_codes_left=left, sessions=n)


REGISTRATION_KEY = "allow_registration"
APPROVAL_KEY = "registration_approval"


def approval_required(db: Session) -> bool:
    """新注册账号是否需要管理员审核（默认开启）。"""
    from ..models import Setting
    row = db.get(Setting, APPROVAL_KEY)
    if row is None or row.value is None:
        return True
    return row.value not in ("0", "false", "False", "")


def _notify_admins_new_user(db: Session, user) -> None:
    """有人注册待审核时，向所有管理员的收件箱发一条通知。"""
    try:
        from ..models import User as _User
        from ..services import notify
        admins = db.query(_User).filter(_User.role == "admin", _User.is_active == True).all()  # noqa: E712
        msg = notify.Message(title="新用户注册待审核",
                             text=f"用户「{user.username}」（{user.display_name or '未填昵称'}）刚刚注册，等待你在「用户管理」中审核。",
                             markdown=f"用户 **{user.username}**（{user.display_name or '未填昵称'}）刚刚注册，等待审核。\n\n"
                                      f"请前往「用户管理」点击「通过」或「拒绝」。", sms_params=[])
        for a in admins:
            notify.send_inbox(db, a.id, msg, "admin_notice")
    except Exception:  # noqa: BLE001
        pass


def registration_enabled(db: Session) -> bool:
    from ..models import Setting
    row = db.get(Setting, REGISTRATION_KEY)
    if row is None or row.value is None:
        return True  # 默认开放注册（管理员可在用户管理页关闭）
    return row.value not in ("0", "false", "False", "")


class RegisterIn(BaseModel):
    username: str = Field(..., min_length=2, max_length=40, pattern=r"^[A-Za-z0-9_\-\.一-龥]+$")
    password: str = Field(..., min_length=8, max_length=200)
    display_name: Optional[str] = Field(None, max_length=40)


@router.get("/status")
def status(request: Request, db: Session = Depends(get_db)):
    """无需登录：告知前端当前是否已登录、是否开放注册。"""
    from ..deps import resolve_user
    user = resolve_user(request, db)
    return {"authenticated": user is not None, "username": user.username if user else None,
            "role": user.role if user else None, "is_admin": bool(user and user.is_admin),
            "display_name": user.display_name if user else None,
            "users_exist": auth_service.user_count(db) > 0,
            "allow_registration": registration_enabled(db),
            "require_approval": approval_required(db)}


@router.post("/register", status_code=201)
def register(payload: RegisterIn, request: Request, response: Response, db: Session = Depends(get_db)):
    """用户自主注册（可由管理员关闭）。注册成功即登录。同一 IP 每小时最多注册 5 个账号。"""
    if not registration_enabled(db):
        raise HTTPException(status_code=403, detail="管理员已关闭注册，请联系管理员开通账号")
    ip = _client_ip(request)
    if auth_service.check_registration_limit(ip):
        raise HTTPException(status_code=429, detail="注册过于频繁，请稍后再试")
    if auth_service.get_user_by_name(db, payload.username):
        raise HTTPException(status_code=400, detail="用户名已被使用")
    need_approval = approval_required(db)
    user = auth_service.create_user(db, payload.username, payload.password, "user", payload.display_name,
                                    is_approved=not need_approval)
    auth_service.record_registration(ip)
    if need_approval:
        _notify_admins_new_user(db, user)
        return {"ok": True, "pending_approval": True, "username": user.username, "display_name": user.display_name,
                "role": user.role, "message": "注册成功，账号需要管理员审核通过后才能登录"}
    token, expires = auth_service.create_session(db, user, ip, request.headers.get("user-agent", ""), False)
    _set_cookie(response, token, False, request)
    return {"ok": True, "pending_approval": False, "username": user.username, "display_name": user.display_name,
            "role": user.role, "expires_at": expires}


@router.post("/login")
def login(payload: LoginIn, request: Request, response: Response, db: Session = Depends(get_db)):
    ip = _client_ip(request)
    locked = auth_service.check_locked(ip, payload.username)
    if locked:
        raise HTTPException(status_code=429, detail=f"失败次数过多，请 {locked} 秒后再试")
    user = auth_service.get_user_by_name(db, payload.username)
    if user is None or not auth_service.verify_password(payload.password, user.password_hash):
        auth_service.record_fail(ip, payload.username)
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="账户已被停用，请联系管理员")
    if not user.is_approved:
        raise HTTPException(status_code=403, detail="账号正在等待管理员审核，审核通过后即可登录")
    auth_service.clear_fails(ip, payload.username)
    if user.totp_enabled:
        return {"need_totp": True, "pending_token": auth_service.make_pending_token(user, payload.remember)}
    token, expires = auth_service.create_session(db, user, ip, request.headers.get("user-agent", ""), payload.remember)
    _set_cookie(response, token, payload.remember, request)
    return {"need_totp": False, "username": user.username, "expires_at": expires}


@router.post("/login/totp")
def login_totp(payload: TotpLoginIn, request: Request, response: Response, db: Session = Depends(get_db)):
    parsed = auth_service.parse_pending_token(payload.pending_token)
    if parsed is None:
        raise HTTPException(status_code=401, detail="验证已过期，请重新输入密码")
    uid, remember = parsed
    user = db.get(User, uid)
    if user is None or not user.totp_enabled:
        raise HTTPException(status_code=401, detail="账户状态已变化，请重新登录")
    ip = _client_ip(request)
    locked = auth_service.check_locked(ip, f"totp:{user.username}")
    if locked:
        raise HTTPException(status_code=429, detail=f"验证码错误次数过多，请 {locked} 秒后再试")
    if not auth_service.verify_second_factor(db, user, payload.code):
        auth_service.record_fail(ip, f"totp:{user.username}")
        raise HTTPException(status_code=401, detail="验证码或备用码不正确")
    auth_service.clear_fails(ip, f"totp:{user.username}")
    token, expires = auth_service.create_session(db, user, ip, request.headers.get("user-agent", ""), remember)
    _set_cookie(response, token, remember, request)
    return {"need_totp": False, "username": user.username, "expires_at": expires}


@router.post("/logout")
def logout(request: Request, response: Response, db: Session = Depends(get_db)):
    token = read_token(request)
    if token:
        auth_service.revoke_session(db, token)
    response.delete_cookie(auth_service.SESSION_COOKIE, path="/")
    return {"ok": True}


@router.post("/logout-all")
def logout_all(request: Request, response: Response, db: Session = Depends(get_db),
               user: User = Depends(get_current_user)):
    n = auth_service.revoke_all_sessions(db, user)
    response.delete_cookie(auth_service.SESSION_COOKIE, path="/")
    return {"ok": True, "revoked": n}


@router.get("/me", response_model=MeOut)
def me(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return _me(db, user)


@router.post("/password")
def change_password(payload: PasswordChangeIn, request: Request, response: Response,
                    db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    if not auth_service.verify_password(payload.current_password, user.password_hash):
        raise HTTPException(status_code=400, detail="当前密码不正确")
    user.password_hash = auth_service.hash_password(payload.new_password)
    db.commit()
    # 改密后让其他设备下线，当前设备重新签发
    auth_service.revoke_all_sessions(db, user)
    token, _ = auth_service.create_session(db, user, _client_ip(request), request.headers.get("user-agent", ""))
    _set_cookie(response, token, False, request)
    return {"ok": True}


@router.post("/totp/setup")
def totp_setup(payload: TotpSetupIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """生成新密钥与二维码（尚未启用，需 /totp/enable 用一次验证码确认）。"""
    if not auth_service.verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=400, detail="密码不正确")
    secret = auth_service.new_totp_secret()
    user.totp_pending_secret = secret
    db.commit()
    uri = auth_service.totp_uri(user, secret)
    return {"secret": secret, "otpauth_uri": uri, "qr_data_url": auth_service.totp_qr_data_url(uri)}


@router.post("/totp/enable")
def totp_enable(payload: TotpEnableIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    if not user.totp_pending_secret:
        raise HTTPException(status_code=400, detail="请先生成二维码")
    if not auth_service.verify_totp(user.totp_pending_secret, payload.code):
        raise HTTPException(status_code=400, detail="验证码不正确，请确认手机时间准确后重试")
    codes, hashes = auth_service.generate_backup_codes()
    user.totp_secret = user.totp_pending_secret
    user.totp_pending_secret = None
    user.totp_enabled = True
    user.backup_codes = hashes
    db.commit()
    return {"ok": True, "backup_codes": codes}


@router.post("/totp/disable")
def totp_disable(payload: TotpDisableIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    if not auth_service.verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=400, detail="密码不正确")
    if not auth_service.verify_second_factor(db, user, payload.code):
        raise HTTPException(status_code=400, detail="验证码或备用码不正确")
    user.totp_enabled = False
    user.totp_secret = None
    user.totp_pending_secret = None
    user.backup_codes = None
    db.commit()
    return {"ok": True}


@router.post("/totp/backup-codes")
def regenerate_backup_codes(payload: TotpSetupIn, db: Session = Depends(get_db),
                            user: User = Depends(get_current_user)):
    if not user.totp_enabled:
        raise HTTPException(status_code=400, detail="尚未开启两步验证")
    if not auth_service.verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=400, detail="密码不正确")
    codes, hashes = auth_service.generate_backup_codes()
    user.backup_codes = hashes
    db.commit()
    return {"ok": True, "backup_codes": codes}
