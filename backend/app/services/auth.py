"""
认证与两步验证（单用户 / 少量用户场景）。

- 密码：PBKDF2-HMAC-SHA256（标准库），每个用户独立随机盐，260k 次迭代。
- 会话：随机 32 字节令牌，数据库只保存其 SHA-256；通过 HttpOnly Cookie 下发（同时也接受 Bearer 头）。
- 两步验证：TOTP（RFC 6238，兼容 Google Authenticator / Microsoft Authenticator / Authy 等）+ 10 个一次性备用码。
- 登录限速：同一 IP + 用户名 连续失败 5 次后锁定 60 秒（进程内存）。
- 首次启动：若没有任何用户，则创建 admin，密码来自 .env ADMIN_PASSWORD，否则随机生成并写入 data/initial_password.txt。
"""
import base64
import hashlib
import hmac
import io
import json
import os
import secrets
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pyotp
from sqlalchemy.orm import Session

from .. import config
from ..models import AuthSession, User

PBKDF2_ITERATIONS = 260_000
SESSION_COOKIE = "dd_session"
SESSION_DAYS = 7
SESSION_DAYS_REMEMBER = 30
PENDING_TOTP_TTL = 300  # 秒
MAX_FAILS = 5
LOCK_SECONDS = 60
APP_ISSUER = "今天吃得怎么样"


# ---------- 密码 ----------
def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, PBKDF2_ITERATIONS)
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${base64.b64encode(salt).decode()}${base64.b64encode(dk).decode()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, iters, salt_b64, dk_b64 = stored.split("$")
        if algo != "pbkdf2_sha256":
            return False
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(dk_b64)
        dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, int(iters))
        return hmac.compare_digest(dk, expected)
    except Exception:  # noqa: BLE001
        return False


def _sha256(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


# ---------- 登录限速（内存） ----------
_fails: Dict[str, Tuple[int, float]] = {}  # key -> (count, locked_until)


def _rl_key(ip: str, username: str) -> str:
    return f"{ip}|{username.lower()}"


def check_locked(ip: str, username: str) -> int:
    """返回剩余锁定秒数，0 表示未锁定。"""
    count, until = _fails.get(_rl_key(ip, username), (0, 0.0))
    remaining = int(until - time.time())
    return remaining if remaining > 0 else 0


def record_fail(ip: str, username: str) -> None:
    key = _rl_key(ip, username)
    count, until = _fails.get(key, (0, 0.0))
    count += 1
    if count >= MAX_FAILS:
        _fails[key] = (0, time.time() + LOCK_SECONDS)
    else:
        _fails[key] = (count, until)


def clear_fails(ip: str, username: str) -> None:
    _fails.pop(_rl_key(ip, username), None)


# ---------- 注册限速：同一 IP 每小时最多 5 次 ----------
_registrations: Dict[str, List[float]] = {}
REGISTRATIONS_PER_HOUR = 5


def check_registration_limit(ip: str) -> bool:
    """返回 True 表示已超限。"""
    now = time.time()
    stamps = [t for t in _registrations.get(ip, []) if now - t < 3600]
    _registrations[ip] = stamps
    return len(stamps) >= REGISTRATIONS_PER_HOUR


def record_registration(ip: str) -> None:
    _registrations.setdefault(ip, []).append(time.time())


# ---------- 用户 ----------
def get_user_by_name(db: Session, username: str) -> Optional[User]:
    return db.query(User).filter(User.username == username.strip()).first()


def user_count(db: Session) -> int:
    return db.query(User).count()


def create_user(db: Session, username: str, password: str, role: str = "user",
                display_name: Optional[str] = None, is_approved: bool = True) -> User:
    u = User(username=username.strip(), password_hash=hash_password(password), role=role,
             display_name=(display_name or "").strip() or None, is_active=True, is_approved=is_approved)
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


def ensure_admin(db: Session) -> Optional[str]:
    """没有任何用户时创建管理员。返回明文初始密码（仅在随机生成时），否则 None。"""
    if user_count(db) > 0:
        return None
    username = os.getenv("ADMIN_USERNAME", "admin").strip() or "admin"
    password = os.getenv("ADMIN_PASSWORD", "").strip()
    generated = False
    if not password:
        password = secrets.token_urlsafe(12)
        generated = True
    create_user(db, username, password, role="admin", display_name="管理员")
    if generated:
        p = Path(config.DATA_DIR) / "initial_password.txt"
        p.write_text(f"用户名: {username}\n初始密码: {password}\n登录后请立即在「模型设置 → 账户与安全」修改密码并开启两步验证。\n", encoding="utf-8")
        try:
            os.chmod(p, 0o600)
        except OSError:
            pass
        print(f"[auth] 已创建初始管理员 {username}，密码见 {p}", flush=True)
        return password
    print(f"[auth] 已根据 .env 创建管理员 {username}", flush=True)
    return None


# ---------- 会话 ----------
def create_session(db: Session, user: User, ip: str, ua: str, remember: bool = False) -> Tuple[str, datetime]:
    token = secrets.token_urlsafe(32)
    days = SESSION_DAYS_REMEMBER if remember else SESSION_DAYS
    expires = datetime.now() + timedelta(days=days)
    db.add(AuthSession(user_id=user.id, token_hash=_sha256(token), ip=ip[:64], user_agent=(ua or "")[:200],
                       expires_at=expires))
    db.commit()
    return token, expires


def get_session_user(db: Session, token: str) -> Optional[User]:
    if not token:
        return None
    s = db.query(AuthSession).filter(AuthSession.token_hash == _sha256(token)).first()
    if s is None or s.expires_at < datetime.now():
        return None
    s.last_seen_at = datetime.now()
    db.commit()
    user = db.get(User, s.user_id)
    return user if user is not None and user.is_active and user.is_approved else None


def revoke_session(db: Session, token: str) -> None:
    db.query(AuthSession).filter(AuthSession.token_hash == _sha256(token)).delete()
    db.commit()


def revoke_all_sessions(db: Session, user: User) -> int:
    n = db.query(AuthSession).filter(AuthSession.user_id == user.id).delete()
    db.commit()
    return n


def purge_expired(db: Session) -> None:
    db.query(AuthSession).filter(AuthSession.expires_at < datetime.now()).delete()
    db.commit()


# ---------- 两步验证：待验证令牌（密码已通过，等待 TOTP） ----------
def _pending_secret() -> bytes:
    # 进程级随机密钥：重启后待验证令牌失效，重新输入密码即可
    global _PENDING_KEY
    try:
        return _PENDING_KEY
    except NameError:
        _PENDING_KEY = secrets.token_bytes(32)
        return _PENDING_KEY


def make_pending_token(user: User, remember: bool) -> str:
    payload = json.dumps({"uid": user.id, "exp": int(time.time()) + PENDING_TOTP_TTL, "r": remember}).encode()
    sig = hmac.new(_pending_secret(), payload, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(payload).decode() + "." + base64.urlsafe_b64encode(sig).decode()


def parse_pending_token(token: str) -> Optional[Tuple[int, bool]]:
    try:
        p_b64, s_b64 = token.split(".")
        payload = base64.urlsafe_b64decode(p_b64)
        sig = base64.urlsafe_b64decode(s_b64)
        if not hmac.compare_digest(sig, hmac.new(_pending_secret(), payload, hashlib.sha256).digest()):
            return None
        data = json.loads(payload)
        if data["exp"] < time.time():
            return None
        return int(data["uid"]), bool(data.get("r"))
    except Exception:  # noqa: BLE001
        return None


# ---------- TOTP ----------
def new_totp_secret() -> str:
    return pyotp.random_base32()


def totp_uri(user: User, secret: str) -> str:
    return pyotp.TOTP(secret).provisioning_uri(name=user.username, issuer_name=APP_ISSUER)


def totp_qr_data_url(uri: str) -> str:
    import qrcode
    img = qrcode.make(uri, box_size=6, border=2)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def verify_totp(secret: str, code: str) -> bool:
    code = (code or "").strip().replace(" ", "")
    if not code.isdigit():
        return False
    return pyotp.TOTP(secret).verify(code, valid_window=1)


def generate_backup_codes(n: int = 10) -> Tuple[List[str], str]:
    """返回 (明文备用码列表, 存库用的哈希 JSON)。"""
    codes = [f"{secrets.randbelow(10**4):04d}-{secrets.randbelow(10**4):04d}" for _ in range(n)]
    hashes = [_sha256(c) for c in codes]
    return codes, json.dumps(hashes)


def consume_backup_code(db: Session, user: User, code: str) -> bool:
    code = (code or "").strip()
    if not code or not user.backup_codes:
        return False
    hashes: List[str] = json.loads(user.backup_codes)
    h = _sha256(code)
    if h not in hashes:
        return False
    hashes.remove(h)
    user.backup_codes = json.dumps(hashes)
    db.commit()
    return True


def verify_second_factor(db: Session, user: User, code: str) -> bool:
    """TOTP 或备用码任一通过即可。"""
    if user.totp_secret and verify_totp(user.totp_secret, code):
        return True
    return consume_backup_code(db, user, code)
