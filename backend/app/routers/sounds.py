"""提醒音效：预设列表与文件、用户上传/删除、就餐提醒设置。"""
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import get_current_user, require_admin
from ..models import User
from ..services import sounds as svc

router = APIRouter(prefix="/api/sounds", tags=["sounds"])


class AlertSettingsIn(BaseModel):
    enabled: Optional[bool] = None
    sound: Optional[str] = Field(None, max_length=40)
    lead_minutes: Optional[int] = Field(None, ge=0, le=60)
    meal_types: Optional[List[str]] = None
    volume: Optional[float] = Field(None, ge=0, le=1)
    vibrate: Optional[bool] = None


def _settings_out(db: Session, user_id: int) -> Dict[str, Any]:
    cfg = svc.get_alert_settings(db, user_id)
    return {**cfg, "sound_url": svc.resolve_sound_url(db, user_id, cfg["sound"])}


@router.get("")
def list_sounds(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return {"presets": svc.list_presets(db), "mine": svc.list_user_sounds(db, user.id),
            "settings": _settings_out(db, user.id), "can_manage_presets": bool(user.is_admin)}


@router.get("/preset/{name}")
def preset_file(name: str, _user: User = Depends(get_current_user)):
    p = svc.preset_path(name)
    if p is None:
        raise HTTPException(status_code=404, detail="预设音效不存在")
    return FileResponse(str(p), media_type="audio/wav", headers={"Cache-Control": "private, max-age=604800"})


@router.get("/file/{sound_id}")
def user_file(sound_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    found = svc.user_sound_path(db, user.id, sound_id)
    if not found:
        raise HTTPException(status_code=404, detail="音效不存在")
    path, mime = found
    return FileResponse(str(path), media_type=mime, headers={"Cache-Control": "private, max-age=604800"})


@router.post("", status_code=201)
async def upload_sound(file: UploadFile = File(...), name: Optional[str] = Form(None),
                       db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    data = await file.read()
    try:
        row = svc.save_user_sound(db, user.id, name or "", data, file.content_type or "", file.filename or "")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"key": f"user:{row.id}", "id": row.id, "name": row.name, "url": f"/api/sounds/file/{row.id}",
            "mime": row.mime, "size": row.size}


class RenameIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=60)


@router.patch("/{sound_id}")
def rename_sound(sound_id: int, payload: RenameIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """重命名自己的音效；管理员还可重命名系统预设音效。"""
    try:
        row = svc.rename_sound(db, sound_id, payload.name, user.id, user.is_admin)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if row is None:
        raise HTTPException(status_code=404, detail="音效不存在或无权修改")
    return {"key": f"{'system' if row.is_system else 'user'}:{row.id}", "id": row.id, "name": row.name,
            "url": f"/api/sounds/file/{row.id}"}


@router.delete("/{sound_id}", status_code=204)
def delete_sound(sound_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """删除自己的音效；管理员还可删除系统预设音效。"""
    if not svc.delete_user_sound(db, user.id, sound_id, is_admin=user.is_admin):
        raise HTTPException(status_code=404, detail="音效不存在或无权删除")
    return None


# ---------- 管理员：系统预设音效管理 ----------
class BuiltinPatchIn(BaseModel):
    name: Optional[str] = Field(None, max_length=60)
    hidden: Optional[bool] = None


@router.get("/admin/presets")
def admin_list_presets(db: Session = Depends(get_db), _admin: User = Depends(require_admin)):
    """所有预设（含被隐藏的内置预设）；builtin=True 的可隐藏 / 重命名，False 的为管理员上传，可删除 / 重命名。"""
    return {"presets": svc.list_presets(db, include_hidden=True), "max_system": svc.MAX_SYSTEM_SOUNDS}


@router.post("/admin/presets", status_code=201)
async def admin_upload_preset(file: UploadFile = File(...), name: Optional[str] = Form(None),
                              db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    """管理员上传系统预设音效，所有用户可选用。"""
    data = await file.read()
    try:
        row = svc.save_user_sound(db, admin.id, name or "", data, file.content_type or "", file.filename or "", is_system=True)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"key": f"system:{row.id}", "id": row.id, "name": row.name, "url": f"/api/sounds/file/{row.id}",
            "mime": row.mime, "size": row.size, "builtin": False, "hidden": False}


@router.patch("/admin/presets/builtin/{name}")
def admin_patch_builtin(name: str, payload: BuiltinPatchIn, db: Session = Depends(get_db),
                        _admin: User = Depends(require_admin)):
    """重命名 / 隐藏内置合成预设（内置文件本身不可删除，隐藏后用户不可见、已选用者回退默认）。"""
    try:
        svc.set_builtin_preset(db, name, label=payload.name, hidden=payload.hidden)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"presets": svc.list_presets(db, include_hidden=True)}


@router.get("/alert-settings")
def get_alert(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return _settings_out(db, user.id)


@router.put("/alert-settings")
def put_alert(payload: AlertSettingsIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    svc.save_alert_settings(db, user.id, payload.model_dump(exclude_none=True))
    return _settings_out(db, user.id)


@router.post("/alert-settings/test")
def test_alert(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """立刻向收件箱发一条就餐提醒（含音效），用于验证 App 端播放。"""
    from ..services import notify
    cfg = svc.get_alert_settings(db, user.id)
    msg = notify.Message(title="【测试】到用餐时间了", text="这是一条测试就餐提醒。", sms_params=[])
    ok, detail = notify.send_inbox(db, user.id, msg, "meal_alert",
                                   extra={"sound_url": svc.resolve_sound_url(db, user.id, cfg["sound"]),
                                          "volume": cfg.get("volume", 0.8), "vibrate": cfg.get("vibrate", True)})
    return {"ok": ok, "detail": detail}
