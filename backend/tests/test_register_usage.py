"""用户自主注册、注册开关、模型用量记录与汇总、余额接口、收件箱长轮询。"""
from fastapi.testclient import TestClient

from app.main import app
from app.services import auth as auth_service


def test_register_flow_and_toggle(client, anon_client):
    client.put("/api/admin/users/registration", json={"require_approval": False})  # 本测试验证“注册即登录”，先关闭审核
    assert anon_client.get("/api/auth/status").json()["allow_registration"] is True
    r = anon_client.post("/api/auth/register", json={"username": "newbie", "password": "newbie-pass1", "display_name": "小新"})
    assert r.status_code == 201, r.text
    assert r.json()["role"] == "user"
    # 注册即登录
    me = anon_client.get("/api/auth/me").json()
    assert me["username"] == "newbie" and me["is_admin"] is False
    # 重名
    with TestClient(app) as c2:
        assert c2.post("/api/auth/register", json={"username": "newbie", "password": "newbie-pass1"}).status_code == 400
        assert c2.post("/api/auth/register", json={"username": "x", "password": "short"}).status_code == 422
    # 管理员关闭注册
    assert client.get("/api/admin/users/registration").json()["allow_registration"] is True
    client.put("/api/admin/users/registration", json={"allow_registration": False})
    with TestClient(app) as c3:
        assert c3.get("/api/auth/status").json()["allow_registration"] is False
        assert c3.post("/api/auth/register", json={"username": "another", "password": "another-pass1"}).status_code == 403
    client.put("/api/admin/users/registration", json={"allow_registration": True})
    # 普通用户不能改开关
    assert anon_client.put("/api/admin/users/registration", json={"allow_registration": False}).status_code == 403
    # 清理
    uid = [u["id"] for u in client.get("/api/admin/users").json() if u["username"] == "newbie"][0]
    client.delete(f"/api/admin/users/{uid}")


def test_registration_rate_limit():
    ip = "1.2.3.4"
    auth_service._registrations.pop(ip, None)
    for _ in range(5):
        assert not auth_service.check_registration_limit(ip)
        auth_service.record_registration(ip)
    assert auth_service.check_registration_limit(ip)
    auth_service._registrations.pop(ip, None)


def test_usage_recorded_and_summary(client, clean_meals):
    before = client.get("/api/usage/summary").json()["total"]["calls"]
    client.post("/api/query", json={"question": "这周吃了几餐"})  # mock: plan + explain = 2 次调用
    client.post("/api/reports", json={"period_type": "week"})   # mock: report 1 次（记忆注入不算调用）
    s = client.get("/api/usage/summary").json()
    assert s["scope"] == "all"
    assert s["total"]["calls"] >= before + 3
    tasks = {t["task"] for t in s["by_task"]}
    assert {"plan", "explain", "report"} <= tasks
    assert s["recent"][0]["provider"] == "mock"
    assert s["by_user"][0]["username"] in ("tester", "（系统/定时任务）")
    # 单价设置 → 费用估算字段存在
    r = client.put("/api/usage/price", json={"input_per_1k": 0.002, "output_per_1k": 0.008, "currency": "CNY"})
    assert r.json()["input_per_1k"] == 0.002
    assert "est_cost" in client.get("/api/usage/summary").json()["month"]


def test_balance_mock_and_non_admin(client, anon_client):
    client.put("/api/admin/users/registration", json={"require_approval": False})  # 本测试验证“注册即登录”，先关闭审核
    b = client.get("/api/usage/balance").json()
    assert b["provider"] == "mock" and b["supported"] is False
    assert anon_client.get("/api/usage/balance").status_code == 401
    # 普通用户只能看自己的用量
    from .conftest import TEST_USER
    with TestClient(app) as c:
        c.post("/api/auth/register", json={"username": "usagelow", "password": "usagelow-pass1"})
        s = c.get("/api/usage/summary").json()
        assert s["scope"] == "self" and "by_user" not in s
        assert c.get("/api/usage/balance").status_code == 403
    uid = [u["id"] for u in client.get("/api/admin/users").json() if u["username"] == "usagelow"][0]
    client.delete(f"/api/admin/users/{uid}")
    assert TEST_USER[0] == "tester"


def test_inbox_long_poll_returns_immediately_when_message_exists(client):
    client.post("/api/notify/test", json={"channel": "inbox"})
    import time
    t0 = time.time()
    r = client.get("/api/notify/inbox", params={"since_id": 0, "wait": 10})
    assert r.status_code == 200 and r.json()["messages"]
    assert time.time() - t0 < 5
    last = r.json()["messages"][-1]["id"]
    t0 = time.time()
    r = client.get("/api/notify/inbox", params={"since_id": last, "wait": 2})
    assert r.json()["messages"] == [] and 1.4 <= time.time() - t0 < 6
