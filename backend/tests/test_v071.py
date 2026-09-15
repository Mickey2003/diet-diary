"""v0.7.1：注册审核开关、待审核用户不可登录/不可用、管理员审核；系统预设音效的上传 / 重命名 / 隐藏 / 删除。"""
import io
import wave

from fastapi.testclient import TestClient

from app.main import app
from app.models import User


def _wav(seconds=0.1):
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(8000); w.writeframes(b"\x00\x00" * int(8000 * seconds))
    return buf.getvalue()


def _cleanup(db, *names):
    for n in names:
        u = db.query(User).filter(User.username == n).first()
        if u:
            db.delete(u)
    db.commit()


def test_registration_approval_flow(client, anon_client, db):
    _cleanup(db, "newbie", "walkin")
    # 默认：开放注册 + 需要审核（其他测试可能改过开关，这里显式恢复默认值）
    client.put("/api/admin/users/registration", json={"allow_registration": True, "require_approval": True})
    reg = client.get("/api/admin/users/registration").json()
    assert reg["allow_registration"] is True and reg["require_approval"] is True
    assert anon_client.get("/api/auth/status").json()["require_approval"] is True

    with TestClient(app) as c:
        r = c.post("/api/auth/register", json={"username": "newbie", "password": "newbie-pass-123", "display_name": "小新"})
        assert r.status_code == 201 and r.json()["pending_approval"] is True
        assert "dd_session" not in r.cookies  # 未自动登录
        # 待审核不能登录
        r = c.post("/api/auth/login", json={"username": "newbie", "password": "newbie-pass-123"})
        assert r.status_code == 403 and "审核" in r.json()["detail"]
    # 管理员收到通知
    box = client.get("/api/notify/inbox", params={"since_id": 0}).json()["messages"]
    assert any(m["kind"] == "admin_notice" and "newbie" in m["body"] for m in box)
    # 列表可见待审核 + 计数
    users = client.get("/api/admin/users").json()
    nb = next(u for u in users if u["username"] == "newbie")
    assert nb["is_approved"] is False
    assert client.get("/api/admin/users/registration").json()["pending_count"] >= 1
    # 审核通过后可登录
    r = client.post(f"/api/admin/users/{nb['id']}/approve")
    assert r.status_code == 200 and r.json()["is_approved"] is True
    with TestClient(app) as c:
        r = c.post("/api/auth/login", json={"username": "newbie", "password": "newbie-pass-123"})
        assert r.status_code == 200 and r.json()["need_totp"] is False
        assert c.get("/api/auth/me").status_code == 200

    # 关闭审核 → 注册即登录
    assert client.put("/api/admin/users/registration", json={"require_approval": False}).json()["require_approval"] is False
    with TestClient(app) as c:
        r = c.post("/api/auth/register", json={"username": "walkin", "password": "walkin-pass-123"})
        assert r.status_code == 201 and r.json()["pending_approval"] is False
        assert c.get("/api/auth/me").json()["username"] == "walkin"
    client.put("/api/admin/users/registration", json={"require_approval": True})
    # 拒绝 = 删除
    wid = next(u for u in client.get("/api/admin/users").json() if u["username"] == "walkin")["id"]
    assert client.delete(f"/api/admin/users/{wid}").status_code == 204
    _cleanup(db, "newbie", "walkin")


def test_admin_cannot_unapprove_self(client):
    me = client.get("/api/auth/me").json()
    assert client.patch(f"/api/admin/users/{me['id']}", json={"is_approved": False}).status_code == 400


def test_system_presets_admin_management(client, db):
    # 上传系统音效
    r = client.post("/api/sounds/admin/presets", files={"file": ("sys.wav", _wav(), "audio/wav")}, data={"name": "食堂铃"})
    assert r.status_code == 201, r.text
    sid = r.json()["id"]
    assert r.json()["key"] == f"system:{sid}"
    lst = client.get("/api/sounds").json()
    assert lst["can_manage_presets"] is True
    keys = {p["key"] for p in lst["presets"]}
    assert f"system:{sid}" in keys and "preset:chime" in keys
    # 所有用户都能读取系统音效文件（这里用第二个用户验证）
    from app.services import auth as auth_service
    u = auth_service.get_user_by_name(db, "listener") or auth_service.create_user(db, "listener", "listener-pass-1")
    with TestClient(app) as c:
        c.post("/api/auth/login", json={"username": "listener", "password": "listener-pass-1"})
        assert c.get(f"/api/sounds/file/{sid}").status_code == 200
        # 普通用户不能管理系统预设
        assert c.post("/api/sounds/admin/presets", files={"file": ("x.wav", _wav(), "audio/wav")}).status_code == 403
        assert c.patch(f"/api/sounds/{sid}", json={"name": "改名"}).status_code == 404
        assert c.delete(f"/api/sounds/{sid}").status_code == 404
        # 普通用户可选用系统音效
        s = c.put("/api/sounds/alert-settings", json={"sound": f"system:{sid}"}).json()
        assert s["sound_url"] == f"/api/sounds/file/{sid}"
        # 普通用户可重命名自己的音效
        mine = c.post("/api/sounds", files={"file": ("m.wav", _wav(), "audio/wav")}, data={"name": "旧名"}).json()
        assert c.patch(f"/api/sounds/{mine['id']}", json={"name": "新名"}).json()["name"] == "新名"
        assert c.delete(f"/api/sounds/{mine['id']}").status_code == 204
    # 管理员重命名 / 隐藏内置预设
    assert client.patch(f"/api/sounds/{sid}", json={"name": "大食堂铃"}).json()["name"] == "大食堂铃"
    r = client.patch("/api/sounds/admin/presets/builtin/chime", json={"name": "叮咚", "hidden": True})
    assert r.status_code == 200
    chime = next(p for p in r.json()["presets"] if p["key"] == "preset:chime")
    assert chime["hidden"] is True and chime["name"] == "叮咚" and chime["default_name"] == "清脆钟声"
    assert "preset:chime" not in {p["key"] for p in client.get("/api/sounds").json()["presets"]}
    # 隐藏的预设被引用时回退到第一个可见预设
    s = client.put("/api/sounds/alert-settings", json={"sound": "preset:chime"}).json()
    assert s["sound_url"] == "/api/sounds/preset/bell"
    assert client.patch("/api/sounds/admin/presets/builtin/nope", json={"hidden": True}).status_code == 400
    # 恢复
    client.patch("/api/sounds/admin/presets/builtin/chime", json={"name": "", "hidden": False})
    # 删除系统音效后，引用者回退
    assert client.delete(f"/api/sounds/{sid}").status_code == 204
    with TestClient(app) as c:
        c.post("/api/auth/login", json={"username": "listener", "password": "listener-pass-1"})
        assert c.get("/api/sounds/alert-settings").json()["sound_url"] == "/api/sounds/preset/chime"
    _cleanup(db, "listener")
