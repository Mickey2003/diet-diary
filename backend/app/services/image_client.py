"""
图片生成客户端（v0.8.6）。

支持两类「生图后端」，二者通过独立配置解耦于文本/识图模型：

1. **SenseAudio**（`https://api.senseaudio.cn`）
   - 同步：`POST /v1/image/sync`            → `{"url": "..."}`
   - 异步：`POST /v1/image/async`           → `{"task_id": "..."}`
           `GET  /v1/image/pending?task_id=` → `{"status": "completed|failed|pending", "url": "...", "error_message": "..."}`
   - 鉴权：`Authorization: Bearer <API_KEY>`
   - 模型：`senseaudio-image-2.0-260319` / `doubao-seedream-5-0-260128` / `sensenova-u1-fast`
   - 注意：不传参考图时 `size` 必填，且每个模型支持的尺寸清单不同。

2. **OpenAI 兼容**（`POST {base_url}/images/generations`，兼容 OpenAI / DashScope / 硅基流动 / 本地等）
   - 返回 b64_json 或 url。

设计原则：任何异常都不向上抛，统一返回 `ImageGenResult(ok=False, error=...)`，
由上层决定「回退 emoji / 占位图」。生图是锦上添花，绝不阻断餐单。
"""
from __future__ import annotations

import base64
import json
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import httpx

SENSEAUDIO_BASE_URL = "https://api.senseaudio.cn"

# ---------------------------------------------------------------------------
# SenseAudio 模型 → 支持尺寸
# 来源：https://docs.senseaudio.cn/api-reference/endpoint/image/sync
# ---------------------------------------------------------------------------
SENSEAUDIO_MODELS: Dict[str, Dict[str, Any]] = {
    "senseaudio-image-2.0-260319": {
        "label": "SenseAudio-Image-2.0（自研，尺寸最全，0.5 元/张）",
        "sizes": [
            "1024x1024", "1536x864", "864x1536", "2048x1024", "1024x2048",
            "2048x1152", "1152x2048", "1920x3840", "3840x1920", "3840x2160",
        ],
        "default_size": "1024x1024",
    },
    "doubao-seedream-5-0-260128": {
        "label": "Doubao-Seedream-5.0（高分辨率，0.22 元/张）",
        "sizes": [
            "2048x2048", "1728x2304", "2304x1728", "1664x2496", "2496x1664",
            "2560x1440", "1440x2560", "3072x3072", "4096x2304", "2304x4096",
        ],
        "default_size": "2048x2048",
    },
    "sensenova-u1-fast": {
        "label": "SenseNova-U1-Fast（加速版，适合信息图）",
        "sizes": [
            "2048x2048", "1664x2496", "2496x1664", "2368x1760", "1760x2368",
            "2752x1536", "1536x2752", "3072x1376",
        ],
        "default_size": "2048x2048",
    },
}

SENSEAUDIO_DEFAULT_MODEL = "senseaudio-image-2.0-260319"

# SenseAudio 错误码 → 人话（用于设置页与日志展示）
SENSEAUDIO_ERRORS: Dict[str, str] = {
    "invalid": "请求参数错误",
    "400000": "参数错误（size / prompt 不合法）",
    "400001": "已达到使用限制或余额不足",
    "400015": "已达到最大并发数量，请稍后再试",
    "400021": "文本内容无效",
    "400034": "模型不支持所需的功能",
    "400035": "模型缺失",
    "400038": "模型不支持请求的 API 协议",
    "400501": "图片内容包含敏感或违规信息",
    "500000": "服务繁忙，请稍后再试",
    "400900": "计费账户不存在",
    "400901": "计费账户已被冻结",
    "400902": "未找到计费交易，可能已过期",
    "429000": "请求过于频繁，请稍后再试",
    "429002": "已达到使用限制，请稍后再试",
    "authentication_error": "API 密钥不正确",
    "404000": "未找到资源",
}

# 这些错误码表示「配额/频率」问题：应停止继续批量生图，转 emoji 兜底
_QUOTA_ERRORS = {"400001", "400015", "429000", "429002", "400901", "400900"}
_AUTH_ERRORS = {"authentication_error", "401"}


@dataclass
class ImageGenResult:
    """生图结果（永不抛异常）。"""
    ok: bool
    image_url: Optional[str] = None      # 远端图片 URL
    data: Optional[bytes] = None         # 图片字节（若上游直接返回 b64）
    content_type: str = ""
    error: Optional[str] = None          # 人类可读错误
    error_code: Optional[str] = None     # 上游错误码
    fatal: bool = False                  # True 表示配额/鉴权类错误，应停止批量重试
    raw: Dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# 尺寸处理
# ---------------------------------------------------------------------------

def senseaudio_supported_sizes(model: str) -> List[str]:
    m = SENSEAUDIO_MODELS.get(model)
    return list(m["sizes"]) if m else []


def senseaudio_pick_size(model: str, want: str = "1024x1024") -> str:
    """在模型允许的尺寸里挑一个最接近的；挑不到就用默认尺寸。"""
    info = SENSEAUDIO_MODELS.get(model)
    if not info:
        return want
    sizes: List[str] = info["sizes"]
    if want in sizes:
        return want
    try:
        ww, wh = (int(x) for x in want.lower().split("x"))
    except Exception:  # noqa: BLE001
        return info["default_size"]
    want_ratio = ww / wh if wh else 1.0

    def _score(s: str) -> float:
        try:
            aw, ah = (int(x) for x in s.lower().split("x"))
        except Exception:  # noqa: BLE001
            return 1e9
        return abs(aw / ah - want_ratio) + abs(aw - ww) / 10000.0

    return min(sizes, key=_score)


def is_senseaudio_base(base_url: str) -> bool:
    b = (base_url or "").strip().lower()
    return "senseaudio" in b


def _err_text(resp: httpx.Response) -> Tuple[str, Optional[str]]:
    """从 SenseAudio 错误响应中提取 (人类可读, 错误码)。"""
    code: Optional[str] = None
    msg = ""
    try:
        j = resp.json()
        if isinstance(j, dict):
            code = str(j.get("ref_code") or j.get("code") or "") or None
            msg = str(j.get("message") or j.get("error_message") or j.get("error") or "")
            err = j.get("error")
            if isinstance(err, dict):
                code = code or str(err.get("code") or "") or None
                msg = msg or str(err.get("message") or "")
    except Exception:  # noqa: BLE001
        msg = (resp.text or "")[:200]
    if code and code in SENSEAUDIO_ERRORS:
        msg = SENSEAUDIO_ERRORS[code] or msg
    if not msg:
        msg = f"HTTP {resp.status_code}"
    return msg, code


# ---------------------------------------------------------------------------
# SenseAudio 后端
# ---------------------------------------------------------------------------

def _senseaudio_headers(api_key: str) -> Dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }


def generate_senseaudio(
    prompt: str,
    *,
    api_key: str,
    model: str = SENSEAUDIO_DEFAULT_MODEL,
    size: str = "1024x1024",
    base_url: str = SENSEAUDIO_BASE_URL,
    timeout: float = 120.0,
    reference: Optional[str] = None,
    use_async: bool = False,
    poll_interval: float = 3.0,
    max_wait: float = 180.0,
) -> ImageGenResult:
    """调用 SenseAudio 生成一张图片。

    默认走同步接口（实现简单、返回即 URL）；`use_async=True` 时走异步 + 轮询，
    适合并发较高、单张耗时长的场景。
    """
    if not api_key:
        return ImageGenResult(ok=False, error="未配置 SenseAudio API Key", error_code="missing_key", fatal=True)

    base = (base_url or SENSEAUDIO_BASE_URL).rstrip("/")
    payload: Dict[str, Any] = {
        "model": model,
        "prompt": prompt[:6000],
    }
    if reference:
        payload["reference"] = reference
    if not reference:
        # 未传参考图时 size 必填
        payload["size"] = senseaudio_pick_size(model, size)

    try:
        if not use_async:
            with httpx.Client(timeout=timeout) as c:
                r = c.post(f"{base}/v1/image/sync", headers=_senseaudio_headers(api_key), json=payload)
            if r.status_code != 200:
                msg, code = _err_text(r)
                return ImageGenResult(ok=False, error=msg, error_code=code,
                                      fatal=(code in _QUOTA_ERRORS or code in _AUTH_ERRORS
                                             or str(r.status_code) in _AUTH_ERRORS))
            j = r.json() if r.content else {}
            url = (j or {}).get("url")
            if not url:
                return ImageGenResult(ok=False, error="响应中没有图片 URL", raw=j or {})
            return ImageGenResult(ok=True, image_url=url, raw=j or {})

        # ---- 异步 ----
        with httpx.Client(timeout=timeout) as c:
            r = c.post(f"{base}/v1/image/async", headers=_senseaudio_headers(api_key), json=payload)
            if r.status_code != 200:
                msg, code = _err_text(r)
                return ImageGenResult(ok=False, error=msg, error_code=code,
                                      fatal=(code in _QUOTA_ERRORS or code in _AUTH_ERRORS
                                             or str(r.status_code) in _AUTH_ERRORS))
            task_id = (r.json() or {}).get("task_id")
            if not task_id:
                return ImageGenResult(ok=False, error="未返回 task_id", raw=r.json() or {})

            deadline = time.time() + max_wait
            while time.time() < deadline:
                time.sleep(poll_interval)
                pr = c.get(f"{base}/v1/image/pending",
                           headers=_senseaudio_headers(api_key),
                           params={"task_id": task_id})
                if pr.status_code != 200:
                    msg, code = _err_text(pr)
                    return ImageGenResult(ok=False, error=msg, error_code=code,
                                          fatal=(code in _QUOTA_ERRORS or code in _AUTH_ERRORS))
                pj = pr.json() or {}
                status = str(pj.get("status") or "").lower()
                if status == "completed":
                    url = pj.get("url")
                    if url:
                        return ImageGenResult(ok=True, image_url=url, raw=pj)
                    return ImageGenResult(ok=False, error="任务完成但无图片 URL", raw=pj)
                if status == "failed":
                    return ImageGenResult(ok=False,
                                          error=str(pj.get("error_message") or "生成失败"),
                                          error_code="failed", raw=pj)
                # pending → 继续等
            return ImageGenResult(ok=False, error=f"等待超时（>{int(max_wait)}s）", error_code="timeout")
    except Exception as e:  # noqa: BLE001
        return ImageGenResult(ok=False, error=f"请求失败：{str(e)[:180]}")


# ---------------------------------------------------------------------------
# OpenAI 兼容后端
# ---------------------------------------------------------------------------

def generate_openai_compatible(
    prompt: str,
    *,
    api_key: str,
    model: str,
    base_url: str,
    size: str = "1024x1024",
    timeout: float = 120.0,
) -> ImageGenResult:
    """OpenAI 兼容 `/images/generations`（返回 b64_json 或 url）。"""
    if not api_key:
        return ImageGenResult(ok=False, error="未配置 API Key", error_code="missing_key", fatal=True)
    base = (base_url or "").rstrip("/")
    if not base:
        return ImageGenResult(ok=False, error="未配置 Base URL", error_code="missing_base", fatal=True)
    if not base.endswith("/v1") and "/v1/" not in base:
        base = f"{base}/v1"
    url = f"{base}/images/generations"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    def _post(extra: Dict[str, Any]) -> httpx.Response:
        body = {"model": model, "prompt": prompt[:4000], "n": 1, "size": size}
        body.update(extra)
        with httpx.Client(timeout=timeout) as c:
            return c.post(url, headers=headers, json=body)

    try:
        # 优先要 b64（避免二次下载依赖外网可达）
        r = _post({"response_format": "b64_json"})
        if r.status_code >= 400:
            # 部分服务不支持 response_format，退回默认
            r = _post({})
        if r.status_code >= 400:
            msg, code = _err_text(r)
            return ImageGenResult(ok=False, error=msg, error_code=code,
                                  fatal=(str(r.status_code) in _AUTH_ERRORS or code in _AUTH_ERRORS))
        j = r.json() if r.content else {}
        item = ((j or {}).get("data") or [None])[0]
        if not isinstance(item, dict):
            return ImageGenResult(ok=False, error="响应结构异常", raw=j or {})
        b64 = item.get("b64_json")
        if b64:
            try:
                return ImageGenResult(ok=True, data=base64.b64decode(b64), content_type="image/png",
                                      raw={"model": model})
            except Exception:  # noqa: BLE001
                return ImageGenResult(ok=False, error="base64 解码失败", raw={"model": model})
        u = item.get("url")
        if u:
            return ImageGenResult(ok=True, image_url=u, raw={"model": model})
        return ImageGenResult(ok=False, error="响应中既无 b64_json 也无 url", raw=j or {})
    except Exception as e:  # noqa: BLE001
        return ImageGenResult(ok=False, error=f"请求失败：{str(e)[:180]}")


# ---------------------------------------------------------------------------
# 统一入口
# ---------------------------------------------------------------------------

def generate_image(
    prompt: str,
    *,
    provider: str = "senseaudio",
    api_key: str = "",
    model: str = "",
    base_url: str = "",
    size: str = "1024x1024",
    timeout: float = 120.0,
    reference: Optional[str] = None,
) -> ImageGenResult:
    """按 provider 分派到具体后端。provider ∈ {senseaudio, openai, custom, auto}。"""
    prov = (provider or "auto").strip().lower()
    if prov == "auto":
        prov = "senseaudio" if is_senseaudio_base(base_url) else "openai"

    if prov == "senseaudio":
        return generate_senseaudio(
            prompt, api_key=api_key,
            model=model or SENSEAUDIO_DEFAULT_MODEL,
            base_url=base_url or SENSEAUDIO_BASE_URL,
            size=size, timeout=timeout, reference=reference,
        )
    return generate_openai_compatible(
        prompt, api_key=api_key, model=model, base_url=base_url, size=size, timeout=timeout,
    )


def describe_providers() -> Dict[str, Any]:
    """给设置页/接口用的能力清单。"""
    return {
        "providers": [
            {"id": "senseaudio", "label": "SenseAudio（商汤，推荐）",
             "base_url": SENSEAUDIO_BASE_URL, "protocol": "senseaudio",
             "models": [{"id": k, "label": v["label"], "sizes": v["sizes"]}
                        for k, v in SENSEAUDIO_MODELS.items()]},
            {"id": "openai", "label": "OpenAI 兼容（/images/generations）",
             "base_url": "https://api.openai.com/v1", "protocol": "openai",
             "models": [{"id": "dall-e-3", "label": "DALL·E 3", "sizes": ["1024x1024", "1792x1024", "1024x1792"]},
                        {"id": "gpt-image-1", "label": "GPT Image 1", "sizes": ["1024x1024", "1536x1024", "1024x1536"]}]},
            {"id": "custom", "label": "自定义 OpenAI 兼容接口", "base_url": "", "protocol": "openai", "models": []},
        ],
        "senseaudio_errors": SENSEAUDIO_ERRORS,
    }
