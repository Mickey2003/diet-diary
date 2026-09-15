"""v0.7：餐单完整性校验与生成锁、单餐结构容错、收件箱 Markdown/extra/详情、音效预设与上传、就餐提醒。"""
import io
import json
import wave
from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models import InboxMessage, MealPlan, NotifyLog, User
from app.services import meal_plan as mp
from app.services import notify, sounds
from app.services.notify_channels import Message
from app.services.timeutil import today_local

from .conftest import TEST_USER


def _uid(db) -> int:
    return db.query(User).filter(User.username == TEST_USER[0]).first().id


def test_plan_validation_rejects_incomplete():
    with pytest.raises(ValueError):
        mp._validate_plan_json({"title": "x", "days": []}, 3)
    with pytest.raises(ValueError):
        mp._validate_plan_json({"title": "x", "days": [{"date": "2026-09-06", "meals": [{"meal_type": "早餐", "dishes": []}]}]}, 1)
    ok = mp._validate_plan_json({"title": "x", "days": [{"date": "2026-09-06", "meals": [
        {"meal_type": "早餐", "time": "07:30", "dishes": [{"name": "燕麦粥"}]}]}]}, 1)
    dumped = ok.model_dump()
    # 校验后的结构补全了缺省字段，前端不会再遇到 undefined.map
    assert dumped["rationale"]["swaps"] == [] and dumped["shopping_list"] == []
    assert dumped["days"][0]["meals"][0]["dishes"][0]["category"] == "其他"


def test_generate_plan_lock_returns_409(client, db):
    from app.services import task_state
    uid = _uid(db)
    task_state.begin("plan", uid)
    try:
        r = client.post("/api/health/plans", json={"days": 3})
        assert r.status_code == 409
    finally:
        task_state.end("plan", uid)
    r = client.post("/api/health/plans", json={"days": 3})
    assert r.status_code == 201
    plan = r.json()
    assert len(plan["plan"]["days"]) == 3
    for d in plan["plan"]["days"]:
        for m in d["meals"]:
            assert m["dishes"], m
    # 生成后只应有一个激活餐单
    assert sum(1 for p in client.get("/api/health/plans").json() if p["is_active"]) == 1


def test_slot_regen_tolerates_wrapped_shape(client, db, monkeypatch):
    plan = client.post("/api/health/plans", json={"days": 1}).json()
    from app.services import llm_client as lc

    def fake_chat(self, messages, **kw):
        if kw.get("task") == "meal_plan_slot":
            return json.dumps({"days": [{"date": "x", "meals": [{"meal_type": "午餐", "time": "12:00",
                                                                 "dishes": [{"name": "清蒸鱼"}, {"name": "杂粮饭"}]}]}]})
        return "{}"
    monkeypatch.setattr(lc.LLMClient, "chat", fake_chat)
    r = client.patch(f"/api/health/plans/{plan['id']}/slot", json={"day_index": 0, "meal_index": 0})
    assert r.status_code == 200
    slot = r.json()["plan"]["days"][0]["meals"][0]
    assert [d["name"] for d in slot["dishes"]] == ["清蒸鱼", "杂粮饭"] and slot["dishes"][0]["category"] == "其他"


def test_inbox_markdown_extra_and_detail(client, db):
    uid = _uid(db)
    msg = Message(title="周报", text="纯文本", markdown="## 标题\n- **要点** 1", sms_params=[])
    notify.send_inbox(db, uid, msg, "weekly_report", extra={"sound_url": "/api/sounds/preset/chime"})
    box = client.get("/api/notify/inbox", params={"since_id": 0}).json()
    m = box["messages"][-1]
    assert m["body"].startswith("## 标题") and m["extra"]["markdown"] is True and m["extra"]["sound_url"].endswith("chime")
    d = client.get(f"/api/notify/inbox/{m['id']}").json()
    assert d["kind_label"] == "周报推送" and d["url"] == "/reports"
    assert client.get("/api/notify/inbox/999999").status_code == 404


def test_sounds_presets_upload_and_settings(client, db):
    lst = client.get("/api/sounds").json()
    assert {p["key"] for p in lst["presets"]} >= {"preset:chime", "preset:bell", "preset:ding"}
    r = client.get("/api/sounds/preset/chime")
    assert r.status_code == 200 and r.headers["content-type"].startswith("audio/wav")
    with wave.open(io.BytesIO(r.content)) as w:
        assert w.getnchannels() == 1 and w.getframerate() == 22050 and w.getnframes() > 10000
    assert client.get("/api/sounds/preset/nope").status_code == 404
    # 上传一个小 wav
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(8000); w.writeframes(b"\x00\x00" * 800)
    r = client.post("/api/sounds", files={"file": ("my.wav", buf.getvalue(), "audio/wav")}, data={"name": "我的铃声"})
    assert r.status_code == 201, r.text
    sid = r.json()["id"]
    assert client.get(f"/api/sounds/file/{sid}").status_code == 200
    bad = client.post("/api/sounds", files={"file": ("x.txt", b"hello", "text/plain")})
    assert bad.status_code == 400
    # 设置：选用上传的音效
    s = client.put("/api/sounds/alert-settings", json={"enabled": True, "sound": f"user:{sid}", "lead_minutes": 5,
                                                       "meal_types": ["午餐"], "volume": 0.5}).json()
    assert s["enabled"] and s["sound_url"] == f"/api/sounds/file/{sid}" and s["lead_minutes"] == 5
    # 删除音效后回退到预设
    assert client.delete(f"/api/sounds/{sid}").status_code == 204
    s = client.get("/api/sounds/alert-settings").json()
    assert s["sound"] == "preset:chime"
    # 测试推送写入收件箱且带音效
    r = client.post("/api/sounds/alert-settings/test").json()
    assert r["ok"]
    last = client.get("/api/notify/inbox", params={"since_id": 0}).json()["messages"][-1]
    assert last["kind"] == "meal_alert" and last["extra"]["sound_url"].endswith("/chime")


def test_meal_alert_fires_once_at_meal_time(client, db):
    uid = _uid(db)
    plan = client.post("/api/health/plans", json={"days": 1, "start_date": today_local().isoformat()}).json()
    today = plan["plan"]["days"][0]
    assert today["date"] == today_local().isoformat()
    first = today["meals"][0]
    hh, mm = int(first["time"][:2]), int(first["time"][3:])
    client.put("/api/sounds/alert-settings", json={"enabled": True, "sound": "preset:bell", "lead_minutes": 0,
                                                   "meal_types": [first["meal_type"]]})
    db.query(NotifyLog).filter(NotifyLog.kind == "meal_alert").delete(); db.commit()
    before = db.query(InboxMessage).filter(InboxMessage.user_id == uid, InboxMessage.kind == "meal_alert").count()
    now = datetime.combine(today_local(), datetime.min.time()).replace(hour=hh, minute=mm)
    res = notify.run_meal_alerts_for_user(db, uid, now)
    assert res and res[0]["meal_type"] == first["meal_type"]
    # 同一时刻再跑不重复；一小时后不触发
    assert notify.run_meal_alerts_for_user(db, uid, now) == []
    assert notify.run_meal_alerts_for_user(db, uid, now.replace(hour=(hh + 3) % 24)) == []
    after = db.query(InboxMessage).filter(InboxMessage.user_id == uid, InboxMessage.kind == "meal_alert").count()
    assert after == before + 1
    m = db.query(InboxMessage).filter(InboxMessage.user_id == uid, InboxMessage.kind == "meal_alert").order_by(InboxMessage.id.desc()).first()
    assert json.loads(m.extra)["sound_url"].endswith("/bell")
    client.put("/api/sounds/alert-settings", json={"enabled": False})
