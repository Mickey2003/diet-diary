"""
ASGI 中间件：
1. UserContextMiddleware —— 在事件循环里解析当前用户并写入 contextvar。
   （依赖函数 get_current_user 在线程池里 set 的 contextvar 不会传回请求上下文，
     导致模型用量记录拿不到 user_id；放在中间件里设置就能被后续线程池调用继承。）
   为避免每个请求都查库，对会话令牌做 60 秒内存缓存。
2. CacheHeadersMiddleware —— 前端构建产物（/assets，文件名带内容哈希）设置一年不可变缓存；
   index.html 不缓存；/uploads 图片缓存 7 天。服务器上行带宽小时，缓存能显著减少重复下载。
"""
import hashlib
import time
from typing import Dict, Optional, Tuple

from starlette.concurrency import run_in_threadpool
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from .deps import API_TOKEN_PREFIX, current_user_id
from .services.auth import SESSION_COOKIE

_CACHE: Dict[str, Tuple[Optional[int], float]] = {}
_TTL = 60.0


def _extract_token(scope: Scope) -> Optional[str]:
    headers = {k.decode().lower(): v.decode() for k, v in scope.get("headers", [])}
    cookie = headers.get("cookie", "")
    for part in cookie.split(";"):
        k, _, v = part.strip().partition("=")
        if k == SESSION_COOKIE and v:
            return v
    auth = headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return None


def _lookup(token: str) -> Optional[int]:
    from .db import SessionLocal
    from .deps import user_from_api_token
    from .services.auth import get_session_user
    with SessionLocal() as db:
        user = user_from_api_token(db, token) if token.startswith(API_TOKEN_PREFIX) else get_session_user(db, token)
        return user.id if user else None


class UserContextMiddleware:
    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not scope.get("path", "").startswith(("/api/", "/mcp")):
            await self.app(scope, receive, send)
            return
        token = _extract_token(scope)
        uid: Optional[int] = None
        if token:
            key = hashlib.sha256(token.encode()).hexdigest()
            hit = _CACHE.get(key)
            now = time.time()
            if hit and hit[1] > now:
                uid = hit[0]
            else:
                try:
                    uid = await run_in_threadpool(_lookup, token)
                except Exception:  # noqa: BLE001
                    uid = None
                _CACHE[key] = (uid, now + _TTL)
                if len(_CACHE) > 5000:
                    _CACHE.clear()
        reset = current_user_id.set(uid)
        try:
            await self.app(scope, receive, send)
        finally:
            current_user_id.reset(reset)


class CacheHeadersMiddleware:
    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path: str = scope.get("path", "")
        if path.startswith("/assets/"):
            cache = b"public, max-age=31536000, immutable"
        elif path.startswith("/uploads/"):
            cache = b"private, max-age=604800"
        elif path.startswith(("/api/", "/mcp")):
            cache = None
        else:
            cache = b"no-cache"  # index.html / SPA 路由

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start" and cache is not None:
                headers = [(k, v) for k, v in message.get("headers", []) if k.lower() != b"cache-control"]
                headers.append((b"cache-control", cache))
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, send_wrapper)
