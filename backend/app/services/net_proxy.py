"""
网络加速服务：当服务器位于中国大陆、目标海外域名可能无法直连时，
把请求 URL 前面加上前缀代理（默认 https://proxy.linjiam.in/）。

- 模式：auto（自动探测）/ on（强制）/ off（关闭）；管理员可在设置页调整，存 settings.net_proxy_mode。
- 仅对白名单内的海外域名加前缀（维基、Open Food Facts、USDA、UPCitemdb 等），国内数据源直连。
- 探测结果带 TTL 缓存，避免每次请求都联网探测；不可达不影响业务（失败按“需要代理”处理）。
"""
import threading
import time
from typing import Optional

import httpx

from .. import config

_LOCK = threading.Lock()
_detected: Optional[bool] = None  # True = 疑似位于大陆，需要代理
_detected_at: float = 0.0
_TTL = 600.0  # 探测结果缓存 10 分钟

VALID_MODES = ("auto", "on", "off")


def _probe_needs_proxy() -> bool:
    """直连探针：能连通目标站点 → 不需要代理；连不通（超时/异常）→ 推断需要代理。"""
    try:
        r = httpx.get(
            config.NET_PROXY_PROBE_URL,
            timeout=2.5,
            follow_redirects=True,
            headers={"User-Agent": "DietDiary/0.9"},
        )
        # 能拿到任何 HTTP 响应都说明可以直连（被墙通常是超时/连接错误）
        return not (200 <= r.status_code < 500)
    except Exception:  # noqa: BLE001
        return True


def detect_needs_proxy(force: bool = False) -> bool:
    """返回是否疑似位于大陆（带缓存）。"""
    global _detected, _detected_at
    with _LOCK:
        now = time.time()
        if force or _detected is None or (now - _detected_at) > _TTL:
            _detected = _probe_needs_proxy()
            _detected_at = now
        return bool(_detected)


def peek_detected() -> Optional[bool]:
    """返回已缓存的探测结果（不触发探测）；未探测过返回 None。"""
    return _detected


def get_mode(db=None) -> str:
    """取加速模式：settings 表 > 环境变量。"""
    if db is not None:
        try:
            from ..models import Setting
            row = db.get(Setting, "net_proxy_mode")
            if row is not None and (row.value or "") in VALID_MODES:
                return row.value  # type: ignore[return-value]
        except Exception:  # noqa: BLE001
            pass
    mode = (config.NET_PROXY_MODE or "auto").lower()
    return mode if mode in VALID_MODES else "auto"


def get_url(db=None) -> str:
    """前缀代理地址（当前实现读环境变量；预留 db 参数以便将来可覆盖）。"""
    return config.NET_PROXY_URL


def is_enabled(db=None) -> bool:
    """加速是否生效。"""
    mode = get_mode(db)
    if mode == "on":
        return True
    if mode == "off":
        return False
    return detect_needs_proxy()


def should_proxy(url: str) -> bool:
    """该 URL 的域名是否在白名单内。"""
    try:
        host = (httpx.URL(url).host or "").lower()
    except Exception:  # noqa: BLE001
        return False
    if not host:
        return False
    return any(host == h or host.endswith("." + h) or host.endswith(h) for h in config.NET_PROXY_HOSTS)


def wrap(url: str, db=None) -> str:
    """按需给 URL 加前缀代理；不需要时原样返回。"""
    if not url or not should_proxy(url):
        return url
    if not is_enabled(db):
        return url
    base = (config.NET_PROXY_URL or "").strip()
    if not base:
        return url
    if not base.endswith("/"):
        base += "/"
    if url.startswith(base):
        return url
    return base + url


def status(db=None) -> dict:
    """给设置页用的状态：模式、是否生效、是否探测过、探测结果。"""
    mode = get_mode(db)
    detected = peek_detected()
    return {
        "mode": mode,
        "enabled": is_enabled(db),
        "detected": detected,  # True=疑似大陆 / False=可直连 / None=未探测
        "url": config.NET_PROXY_URL,
    }
