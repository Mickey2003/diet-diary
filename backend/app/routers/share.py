"""
分享文案路由（Feature 3）。
前缀：/api/share
所有端点需要登录（每个端点声明 Depends(get_current_user)）。
"""
import json
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .. import config
from ..db import get_db
from ..deps import get_current_user
from ..models import Meal, User, UserSetting
from ..services import share as share_svc
from ..services.task_state import task_guard

router = APIRouter(prefix="/api/share", tags=["share"])

_HISTORY_KEY = "share_history"
_HISTORY_MAX = 20


# ---------- schema ----------

class ShareCardIn(BaseModel):
    kind: str = Field(..., description="weekly | monthly | today | meal")
    anchor: Optional[str] = Field(None, description="YYYY-MM-DD，用于 weekly/monthly/today")
    meal_id: Optional[int] = Field(None, description="kind=meal 时需要提供")
    tone: Optional[str] = Field("轻松", description="轻松 | 励志 | 文艺 | 极简")


# ---------- 历史记录工具 ----------

def _load_history(db: Session, user_id: int) -> List[dict]:
    row = (db.query(UserSetting)
           .filter(UserSetting.user_id == user_id, UserSetting.key == _HISTORY_KEY)
           .first())
    if row is None or not row.value:
        return []
    try:
        return json.loads(row.value)
    except Exception:
        return []


def _save_history(db: Session, user_id: int, history: List[dict]) -> None:
    history = history[-_HISTORY_MAX:]
    row = (db.query(UserSetting)
           .filter(UserSetting.user_id == user_id, UserSetting.key == _HISTORY_KEY)
           .first())
    value = json.dumps(history, ensure_ascii=False)
    if row is None:
        row = UserSetting(user_id=user_id, key=_HISTORY_KEY, value=value)
        db.add(row)
    else:
        row.value = value
    db.commit()


# ---------- 端点 ----------

@router.post("/card")
def generate_card(
    payload: ShareCardIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """生成分享文案卡片（LLM 生成 + 模板兜底）。"""
    if payload.kind not in share_svc.VALID_KINDS:
        raise HTTPException(status_code=400,
                            detail=f"kind 必须为：{', '.join(share_svc.VALID_KINDS)}")
    tone = payload.tone if payload.tone in share_svc.VALID_TONES else "轻松"

    with task_guard("share", user.id):  # 同一用户并发生成 → 409
        try:
            result = share_svc.generate_share_card(
                db, user.id,
                kind=payload.kind,
                anchor=payload.anchor,
                meal_id=payload.meal_id,
                tone=tone,
            )
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

    # 存入历史（带时间戳，便于前端回传图片绑定）
    created_at = datetime.now().isoformat()
    history = _load_history(db, user.id)
    history.append({
        "created_at": created_at,
        "kind": payload.kind,
        "tone": tone,
        "copy": result.get("copy"),
        "card": result.get("card"),
        "image_url": None,
    })
    _save_history(db, user.id, history)
    result["created_at"] = created_at

    return result


class ShareImageIn(BaseModel):
    """把前端渲染好的卡片图片保存到历史记录（base64 data URL）。"""
    created_at: Optional[str] = None
    data_url: str = Field(..., min_length=32)


@router.post("/history/image")
def attach_history_image(
    payload: ShareImageIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """保存分享卡片图片（服务端落盘），历史记录即可查看/下载之前的卡片图。"""
    import base64
    import hashlib

    data = payload.data_url
    if "," in data:
        data = data.split(",", 1)[1]
    try:
        raw = base64.b64decode(data)
    except Exception:  # noqa: BLE001
        raise HTTPException(status_code=400, detail="图片数据无法解析")
    if len(raw) > 8 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="图片过大")

    subdir = Path(config.UPLOAD_DIR) / "share"
    subdir.mkdir(parents=True, exist_ok=True)
    name = hashlib.sha1(f"{user.id}-{payload.created_at or ''}".encode()).hexdigest()[:16] + ".png"
    (subdir / name).write_bytes(raw)
    image_url = f"/uploads/share/{name}"

    # 绑定到对应历史记录（未传时间戳则绑到最新一条）
    history = _load_history(db, user.id)
    if history:
        target = None
        if payload.created_at:
            for item in history:
                if item.get("created_at") == payload.created_at:
                    target = item
                    break
        if target is None:
            target = history[-1]
        target["image_url"] = image_url
        _save_history(db, user.id, history)

    return {"image_url": image_url}


@router.get("/history")
def share_history(
    limit: int = 20,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """返回最近生成过的分享卡片历史（最多 20 条，存储于 UserSetting）。"""
    history = _load_history(db, user.id)
    history = history[-limit:]
    history.reverse()  # 最新的在前
    return history


@router.post("/meal-image/{meal_id}")
def meal_image(
    meal_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """返回指定餐食的图片 URL（用于分享卡片）。"""
    meal = db.get(Meal, meal_id)
    if meal is None or meal.user_id != user.id:
        raise HTTPException(status_code=404, detail="餐食不存在或无图片")
    if not meal.image_path:
        raise HTTPException(status_code=404, detail="该餐食没有图片")
    # 验证图片文件是否实际存在
    img_path = Path(config.UPLOAD_DIR) / meal.image_path
    if not img_path.is_file():
        raise HTTPException(status_code=404, detail="图片文件不存在")
    return {"image_url": f"/uploads/{meal.image_path}"}
