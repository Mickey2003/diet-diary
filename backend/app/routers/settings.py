"""模型设置：所有用户可查看（掩码），仅管理员可修改与测试。密钥只存在后端。"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from .. import config
from ..db import get_db
from ..deps import get_current_user, require_admin
from ..models import Setting, User
from ..schemas import ConnectionTestOut, SettingsIn, SettingsOut
from ..services import barcode as barcode_svc
from ..services import dish_image, image_client, llm_client, net_proxy

router = APIRouter(prefix="/api/settings", tags=["settings"])


def _presets():
    return {k: {"label": v["label"], "base_url": v["base_url"], "text_model": v["text_model"],
                "fast_model": v.get("fast_model", ""), "vision_model": v["vision_model"]}
            for k, v in llm_client.PROVIDER_PRESETS.items()}


def _out(db: Session, user: User) -> SettingsOut:
    cfg = llm_client.get_llm_config(db)
    img = dish_image.get_image_config(db)
    return SettingsOut(provider=cfg.provider, base_url=cfg.base_url, text_model=cfg.text_model, fast_model=cfg.fast_model,
                       vision_model=cfg.vision_model, image_model=cfg.image_model,
                       api_key_masked=llm_client.mask_key(cfg.api_key),
                       has_api_key=bool(cfg.api_key), source=cfg.source, presets=_presets(),
                       can_edit=user.is_admin, vision_async=llm_client.get_vision_async(db),
                       net_proxy_mode=net_proxy.get_mode(db), net_proxy_url=net_proxy.get_url(db),
                       barcode_sources=barcode_svc.enabled_sources_value(db),
                       dish_ai_images=dish_image.ai_images_enabled(db),
                       barcode_source_options=barcode_svc.SOURCE_LABELS,
                       # 生图专用配置（key 只回掩码）
                       image_provider=img["provider"],
                       image_base_url=img["base_url"],
                       image_model_id=img["model"],
                       image_key_masked=llm_client.mask_key(img["api_key"]),
                       has_image_key=bool(img["api_key"]),
                       image_size=img["size"] or "1024x1024",
                       image_providers=image_client.describe_providers()["providers"],
                       image_ready=dish_image.image_config_ready(db),
                       image_emoji_fallback=config.DISH_EMOJI_FALLBACK)


@router.get("", response_model=SettingsOut)
def get_settings(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return _out(db, user)


def _set(db: Session, key: str, value: str) -> None:
    row = db.get(Setting, key)
    if row is None:
        db.add(Setting(key=key, value=value))
    else:
        row.value = value


@router.put("", response_model=SettingsOut)
def update_settings(payload: SettingsIn, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    if payload.provider is not None:
        provider = payload.provider if payload.provider in llm_client.PROVIDER_PRESETS else "custom"
        _set(db, "provider", provider)
    for key in ("base_url", "text_model", "fast_model", "vision_model", "image_model"):
        v = getattr(payload, key)
        if v is not None:
            _set(db, key, v.strip())
    if payload.vision_async is not None:
        _set(db, "vision_async", "true" if payload.vision_async else "false")
    if payload.net_proxy_mode is not None and payload.net_proxy_mode in net_proxy.VALID_MODES:
        _set(db, "net_proxy_mode", payload.net_proxy_mode)
    if payload.barcode_sources is not None:
        _set(db, "barcode_sources",
             ",".join(sorted({s.strip() for s in payload.barcode_sources.split(",") if s.strip()})))
    if payload.dish_ai_images is not None:
        _set(db, "dish_ai_images", "true" if payload.dish_ai_images else "false")
    if payload.api_key is not None:
        if payload.api_key == "__clear__":
            _set(db, "api_key", "")
        elif payload.api_key.strip():
            _set(db, "api_key", payload.api_key.strip())

    # ---------- 生图专用配置 ----------
    if payload.image_provider is not None:
        _set(db, "image_provider", payload.image_provider.strip())
    for key in ("image_base_url", "image_size"):
        v = getattr(payload, key)
        if v is not None:
            _set(db, key, v.strip())
    if payload.image_model_id is not None:
        # 独立 key：老字段 "image_model" 已被「OpenAI 兼容配图模型」占用，不能复用，
        # 否则两边互相覆盖。兼容：早期前端可能传 image_model，当 dish_image_model 为空时采纳。
        _set(db, "dish_image_model", payload.image_model_id.strip())
    if payload.image_api_key is not None:
        if payload.image_api_key == "__clear__":
            _set(db, "image_api_key", "")
        elif payload.image_api_key.strip():
            _set(db, "image_api_key", payload.image_api_key.strip())

    db.commit()
    return _out(db, admin)


@router.post("/image/test", response_model=ConnectionTestOut)
def test_image_connection(db: Session = Depends(get_db), _admin: User = Depends(require_admin)):
    """测试生图配置：真发一张极小尺寸的请求验证鉴权与模型可用性。"""
    import time as _time

    from ..schemas import ConnectionTestOut as _Out
    cfg = dish_image.get_image_config(db)
    if not (cfg["provider"] and cfg["api_key"] and cfg["model"]):
        return _Out(ok=False, message="生图配置不完整（需要提供商、API Key、模型）")
    size = cfg["size"] or "1024x1024"
    start = _time.time()
    res = image_client.generate_image(
        "一个白色盘子里的简单炒青菜，3D 卡通渲染风格，柔和奶油色背景，居中构图",
        provider=cfg["provider"], api_key=cfg["api_key"], model=cfg["model"],
        base_url=cfg["base_url"], size=size, timeout=float(getattr(config, "IMAGE_TIMEOUT", 120)),
    )
    latency = int((_time.time() - start) * 1000)
    if res.ok:
        return _Out(ok=True, message=f"生图连通正常（{cfg['model']}）", latency_ms=latency, model=cfg["model"])
    return _Out(ok=False, message=res.error or "生图调用失败", latency_ms=latency, model=cfg["model"])


@router.post("/test", response_model=ConnectionTestOut)
def test_connection(db: Session = Depends(get_db), _admin: User = Depends(require_admin)):
    client = llm_client.get_client(db)
    return client.test_connection()


@router.get("/net-proxy/status")
def net_proxy_status(force: bool = False, db: Session = Depends(get_db),
                     _admin: User = Depends(require_admin)):
    """网络加速状态（仅管理员）；force=true 时重新探测是否位于大陆。"""
    if force:
        net_proxy.detect_needs_proxy(force=True)
    return net_proxy.status(db)
