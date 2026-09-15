"""通知：配置掩码、消息生成、定时判定、渠道失败处理、腾讯云签名、App 收件箱。"""
from datetime import datetime

from app.models import NotifyLog, User
from app.services import notify
from app.services import notify_channels as ch
from app.services.timeutil import today_local

from .conftest import TEST_USER, add_meal


def _uid(db) -> int:
    return db.query(User).filter(User.username == TEST_USER[0]).first().id


def _clear_logs(db):
    db.query(NotifyLog).delete()
    db.commit()


def test_settings_roundtrip_masks_secrets(client):
    cfg = {"channels": {"email": {"enabled": True, "smtp_host": "smtp.qq.com", "username": "a@qq.com",
                                  "password": "authcode123", "to_addrs": "b@x.com"},
                        "pushplus": {"enabled": False, "token": "tok-secret"},
                        "inbox": {"enabled": False}},
           "schedules": {"daily_reminder": {"enabled": True, "time": "25:99"}}}
    r = client.put("/api/notify/settings", json={"config": cfg})
    assert r.status_code == 200
    body = r.json()
    email = body["config"]["channels"]["email"]
    assert email["password"] == body["mask"] and email["smtp_host"] == "smtp.qq.com"
    assert body["config"]["channels"]["pushplus"]["token"] == body["mask"]
    assert body["config"]["schedules"]["daily_reminder"]["time"] == "20:30"  # 非法时间回退默认
    assert body["enabled_channels"] == ["email"]
    assert body["channel_meta"][0]["key"] == "inbox"
    # 再次提交掩码 → 保留旧密文；__clear__ → 清空
    r = client.put("/api/notify/settings", json={"config": {"channels": {
        "email": {"password": body["mask"]}, "pushplus": {"token": "__clear__"}}}})
    body2 = r.json()
    assert body2["config"]["channels"]["email"]["password"] == body["mask"]
    assert body2["config"]["channels"]["pushplus"]["token"] == ""
    client.put("/api/notify/settings", json={"config": {"channels": {"email": {"enabled": False}, "inbox": {"enabled": True}}}})


def test_compose_daily_summary_and_reminder(db, clean_meals):
    uid = _uid(db)
    assert notify.compose_daily_reminder(db, uid) is not None  # 今天无记录 → 提醒
    m = notify.compose_daily_summary(db, uid)
    assert "没有记录" in m.text and m.sms_params == ["0", "0"]
    add_meal(db, 0, 12, "午餐", [("米饭", "主食", []), ("奶茶", "饮品", ["sugary_drink"])])
    assert notify.compose_daily_reminder(db, uid) is None  # 有记录 → 不提醒
    m = notify.compose_daily_summary(db, uid)
    assert "1" in m.text and "奶茶" in m.text and "含糖饮料 1 次" in m.text
    assert m.sms_params == ["1", "1"]
    assert "<li>" in m.html


def test_compose_weekly_report(db, clean_meals):
    add_meal(db, 7, 12, "午餐", [("米饭", "主食", [])])
    m = notify.compose_weekly_report(db, _uid(db))
    assert "周报" in m.title and m.sms_params[0] == "1"


def test_due_kinds_dedupe_and_weekday(db):
    uid = _uid(db)
    _clear_logs(db)
    cfg = notify.default_config()
    cfg["schedules"]["daily_summary"] = {"enabled": True, "time": "21:30"}
    cfg["schedules"]["weekly_report"] = {"enabled": True, "weekday": 1, "time": "09:00"}
    today = today_local()
    at_2130 = datetime.combine(today, datetime.min.time()).replace(hour=21, minute=30)
    assert notify.due_kinds(cfg, at_2130, db, uid) == ["daily_summary"]
    assert notify.due_kinds(cfg, at_2130.replace(minute=31), db, uid) == []
    db.add(NotifyLog(user_id=uid, kind="daily_summary", channel="-", ok=True, detail="x"))
    db.commit()
    assert notify.due_kinds(cfg, at_2130, db, uid) == []
    monday = datetime(2026, 8, 31, 9, 0)
    tuesday = datetime(2026, 9, 1, 9, 0)
    _clear_logs(db)
    assert "weekly_report" in notify.due_kinds(cfg, monday, db, uid)
    assert "weekly_report" not in notify.due_kinds(cfg, tuesday, db, uid)
    _clear_logs(db)


def test_run_due_writes_inbox_once(db, clean_meals):
    uid = _uid(db)
    _clear_logs(db)
    cfg = notify.default_config()  # inbox 默认启用
    cfg["schedules"]["daily_reminder"] = {"enabled": True, "time": "20:30", "only_if_no_meals": True}
    notify.save_config(db, uid, cfg)
    now = datetime.combine(today_local(), datetime.min.time()).replace(hour=20, minute=30)
    results = notify.run_due(db, now)
    assert results and results[0]["channel"] == "inbox" and results[0]["ok"]
    assert db.query(NotifyLog).filter(NotifyLog.user_id == uid, NotifyLog.kind == "daily_reminder").count() == 1
    notify.run_due(db, now)  # 同一天不重复
    assert db.query(NotifyLog).filter(NotifyLog.user_id == uid, NotifyLog.kind == "daily_reminder").count() == 1
    notify.save_config(db, uid, notify.default_config())
    _clear_logs(db)


def test_inbox_polling_and_read(client, db):
    r = client.post("/api/notify/test", json={"channel": "inbox"})
    assert r.status_code == 200 and r.json()["ok"]
    box = client.get("/api/notify/inbox", params={"since_id": 0}).json()
    assert box["unread"] >= 1 and box["messages"][-1]["title"].startswith("【今天吃得怎么样】")
    last_id = box["messages"][-1]["id"]
    assert client.get("/api/notify/inbox", params={"since_id": last_id}).json()["messages"] == []
    r = client.post("/api/notify/inbox/read", json=[last_id]).json()
    assert r["marked"] == 1
    # 设备注册
    r = client.post("/api/notify/devices", json={"device_id": "abcd-1234", "name": "Pixel", "app_version": "1.0"})
    assert r.status_code == 200
    devs = client.get("/api/notify/devices").json()
    assert devs[0]["device_id"] == "abcd-1234"
    client.delete(f"/api/notify/devices/{devs[0]['id']}")


def test_channel_validation_errors():
    ok, detail = ch.send_email({"smtp_host": "", "username": "", "to_addrs": ""}, ch.Message("t", "x"))
    assert not ok and "未填写" in detail
    ok, detail = ch.send_wecom({"webhook_url": "http://evil"}, ch.Message("t", "x"))
    assert not ok
    ok, detail = ch.send_qq({"api_base": "http://x", "target_id": "abc"}, ch.Message("t", "x"))
    assert not ok
    ok, detail = ch.send_serverchan({"sendkey": "sctpbad"}, ch.Message("t", "x"))
    assert not ok
    ok, detail = ch.send_tencent_sms({"secret_id": "a"}, ch.Message("t", "x"))
    assert not ok and "未填写完整" in detail


def test_tencent_tc3_signature_is_deterministic():
    payload = '{"PhoneNumberSet":["+8613800000000"]}'
    h1 = ch.tencent_tc3_headers("AKID", "SECRET", "sms", "sms.tencentcloudapi.com", "SendSms", "2021-01-11",
                                "ap-guangzhou", payload, timestamp=1756900000)
    h2 = ch.tencent_tc3_headers("AKID", "SECRET", "sms", "sms.tencentcloudapi.com", "SendSms", "2021-01-11",
                                "ap-guangzhou", payload, timestamp=1756900000)
    assert h1 == h2
    assert h1["Authorization"].startswith("TC3-HMAC-SHA256 Credential=AKID/2025-09-03/sms/tc3_request, SignedHeaders=content-type;host;x-tc-action, Signature=")
    assert len(h1["Authorization"].split("Signature=")[1]) == 64


def test_test_endpoint_records_log(client, db):
    r = client.post("/api/notify/test", json={"channel": "pushplus"})
    assert r.status_code == 200
    assert r.json()["ok"] is False  # 未配置 token
    assert client.get("/api/notify/logs").json()[0]["channel"] == "pushplus"
    r = client.get("/api/notify/preview", params={"kind": "daily_summary"})
    assert r.status_code == 200 and "title" in r.json()
    assert client.post("/api/notify/test", json={"channel": "nope"}).status_code == 400
