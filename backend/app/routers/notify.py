"""通知推送（按用户）：渠道配置、测试发送、立即发送、发送日志、App 收件箱。"""
from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import get_current_user
from ..models import Device, InboxMessage, User
from ..services import notify
from ..services import notify_channels as ch

router = APIRouter(prefix="/api/notify", tags=["notify"])

Kind = Literal["test", "daily_reminder", "daily_summary", "weekly_report"]


class ConfigIn(BaseModel):
    config: Dict[str, Any]


class TestIn(BaseModel):
    channel: str
    kind: Kind = "test"


class SendIn(BaseModel):
    kind: Kind


class DeviceIn(BaseModel):
    device_id: str = Field(..., min_length=4, max_length=80)
    name: Optional[str] = Field(None, max_length=80)
    platform: str = Field("android", max_length=20)
    app_version: Optional[str] = Field(None, max_length=20)


def _response(cfg: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "config": notify.mask_config(cfg),
        "channel_meta": notify.channel_meta(),
        "kinds": [{"key": k, "label": v} for k, v in notify.KIND_LABELS.items() if k != "manual"],
        "mask": notify.MASK,
        "enabled_channels": notify.enabled_channels(cfg),
    }


@router.get("/settings")
def get_settings(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return _response(notify.load_config(db, user.id))


@router.put("/settings")
def put_settings(payload: ConfigIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return _response(notify.apply_update(db, user.id, payload.config))


@router.get("/preview")
def preview(kind: Kind = Query("daily_summary"), db: Session = Depends(get_db),
            user: User = Depends(get_current_user)):
    """预览某类消息的内容（周报预览会真实生成一份报告）。"""
    msg = notify.compose(db, user.id, kind)
    if msg is None:
        return {"kind": kind, "skipped": True, "reason": "今天已有记录，按当前设置不会发送提醒"}
    return {"kind": kind, "skipped": False, "title": msg.title, "text": msg.text, "markdown": msg.md(),
            "sms_params": msg.sms_params}


@router.post("/test")
def test_channel(payload: TestIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """向指定渠道发送一条测试消息（使用当前已保存的配置）。"""
    if payload.channel != "inbox" and payload.channel not in ch.SENDERS:
        raise HTTPException(status_code=400, detail="未知渠道")
    msg = notify.compose(db, user.id, payload.kind) or notify.compose_test()
    ok, detail = notify.send_to_channel(db, user.id, payload.channel, msg, "test")
    return {"channel": payload.channel, "ok": ok, "detail": detail}


@router.post("/send")
def send_now(payload: SendIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """立即向所有启用渠道发送某类消息。"""
    cfg = notify.load_config(db, user.id)
    if not notify.enabled_channels(cfg):
        raise HTTPException(status_code=400, detail="没有启用任何通知渠道")
    msg = notify.compose(db, user.id, payload.kind, cfg)
    if msg is None:
        return {"sent": False, "reason": "今天已有记录，按当前设置不需要提醒", "results": []}
    return {"sent": True, "results": notify.broadcast(db, user.id, "manual", msg, cfg)}


@router.get("/logs")
def logs(limit: int = Query(50, ge=1, le=200), db: Session = Depends(get_db),
         user: User = Depends(get_current_user)):
    return notify.recent_logs(db, user.id, limit)


# ---------- App 收件箱 / 设备 ----------
@router.post("/devices")
def register_device(payload: DeviceIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    d = db.query(Device).filter(Device.user_id == user.id, Device.device_id == payload.device_id).first()
    if d is None:
        d = Device(user_id=user.id, device_id=payload.device_id)
        db.add(d)
    d.name = payload.name or d.name
    d.platform = payload.platform
    d.app_version = payload.app_version
    d.last_seen_at = datetime.now()
    db.commit()
    return {"ok": True, "device_id": d.device_id}


@router.get("/devices")
def list_devices(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    rows = db.scalars(select(Device).where(Device.user_id == user.id).order_by(Device.last_seen_at.desc())).all()
    return [{"id": d.id, "device_id": d.device_id, "name": d.name, "platform": d.platform,
             "app_version": d.app_version, "last_seen_at": d.last_seen_at, "created_at": d.created_at} for d in rows]


@router.delete("/devices/{device_pk}", status_code=204)
def delete_device(device_pk: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    d = db.get(Device, device_pk)
    if not d or d.user_id != user.id:
        raise HTTPException(status_code=404, detail="设备不存在")
    db.delete(d)
    db.commit()
    return None


@router.get("/inbox")
def inbox(since_id: int = Query(0, ge=0), unread_only: bool = Query(False), limit: int = Query(50, ge=1, le=200),
          wait: int = Query(0, ge=0, le=30),
          db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """App 轮询：返回 id > since_id 的消息（按 id 升序），App 记住最大 id 即可增量拉取。
    wait>0 时为长轮询：最多等待 wait 秒，一有新消息立刻返回（App 前台服务用它做到近实时通知）。"""
    import time as _time

    def _query():
        q = select(InboxMessage).where(InboxMessage.user_id == user.id, InboxMessage.id > since_id)
        if unread_only:
            q = q.where(InboxMessage.read_at.is_(None))
        return db.scalars(q.order_by(InboxMessage.id.asc()).limit(limit)).all()

    rows = _query()
    deadline = _time.time() + wait
    while not rows and wait > 0 and _time.time() < deadline:
        _time.sleep(1.5)
        db.expire_all()
        rows = _query()
    unread = db.query(InboxMessage).filter(InboxMessage.user_id == user.id, InboxMessage.read_at.is_(None)).count()
    import json as _json

    def _extra(m):
        try:
            return _json.loads(m.extra) if m.extra else {}
        except Exception:  # noqa: BLE001
            return {}

    return {"messages": [{"id": m.id, "kind": m.kind, "title": m.title, "body": m.body, "url": m.url,
                          "extra": _extra(m), "created_at": m.created_at, "read_at": m.read_at} for m in rows],
            "unread": unread, "server_time": datetime.now()}


@router.get("/unread")
def unread_count(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """轻量接口：未读数（前端铃铛角标 / App 桌面角标）。"""
    n = db.query(InboxMessage).filter(InboxMessage.user_id == user.id, InboxMessage.read_at.is_(None)).count()
    latest = db.scalar(select(InboxMessage.id).where(InboxMessage.user_id == user.id).order_by(InboxMessage.id.desc()).limit(1))
    return {"unread": n, "latest_id": latest or 0}


@router.post("/inbox/read-all")
def mark_all_read(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    n = 0
    for m in db.scalars(select(InboxMessage).where(InboxMessage.user_id == user.id, InboxMessage.read_at.is_(None))).all():
        m.read_at = datetime.now()
        n += 1
    db.commit()
    return {"ok": True, "marked": n}


@router.get("/inbox/{message_id}")
def inbox_detail(message_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    import json as _json
    m = db.get(InboxMessage, message_id)
    if not m or m.user_id != user.id:
        raise HTTPException(status_code=404, detail="消息不存在")
    try:
        extra = _json.loads(m.extra) if m.extra else {}
    except Exception:  # noqa: BLE001
        extra = {}
    return {"id": m.id, "kind": m.kind, "kind_label": notify.KIND_LABELS.get(m.kind, m.kind), "title": m.title,
            "body": m.body, "url": m.url, "extra": extra, "created_at": m.created_at, "read_at": m.read_at}


@router.post("/inbox/read")
def mark_read(ids: List[int], db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    n = 0
    for m in db.scalars(select(InboxMessage).where(InboxMessage.user_id == user.id, InboxMessage.id.in_(ids))).all():
        if m.read_at is None:
            m.read_at = datetime.now()
            n += 1
    db.commit()
    return {"ok": True, "marked": n}
