"""多用户隔离、角色权限、管理员用户管理、个人访问令牌。"""
from fastapi.testclient import TestClient

from app.main import app

from .conftest import TEST_USER


def _login(c: TestClient, username: str, password: str) -> None:
    r = c.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text


def _ensure_user(admin_client: TestClient, username: str, password: str, role: str = "user") -> int:
    users = admin_client.get("/api/admin/users").json()
    for u in users:
        if u["username"] == username:
            return u["id"]
    r = admin_client.post("/api/admin/users", json={"username": username, "password": password, "role": role})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def test_admin_role_and_user_management(client):
    me = client.get("/api/auth/me").json()
    assert me["is_admin"] is True and me["role"] == "admin"
    uid = _ensure_user(client, "alice", "alice-pass-123")
    users = client.get("/api/admin/users").json()
    assert any(u["username"] == "alice" and u["role"] == "user" for u in users)
    # 重复用户名
    assert client.post("/api/admin/users", json={"username": "alice", "password": "alice-pass-123"}).status_code == 400
    # 不能删除/降级自己
    assert client.delete(f"/api/admin/users/{me['id']}").status_code == 400
    assert client.patch(f"/api/admin/users/{me['id']}", json={"role": "user"}).status_code == 400
    # 停用后无法登录
    client.patch(f"/api/admin/users/{uid}", json={"is_active": False})
    with TestClient(app) as c2:
        assert c2.post("/api/auth/login", json={"username": "alice", "password": "alice-pass-123"}).status_code == 403
    client.patch(f"/api/admin/users/{uid}", json={"is_active": True})


def test_data_isolation_between_users(client, clean_meals):
    _ensure_user(client, "alice", "alice-pass-123")
    _ensure_user(client, "bob", "bob-pass-12345")
    from app.services.timeutil import today_local
    payload = {"eaten_at": f"{today_local().isoformat()}T12:00:00", "meal_type": "午餐",  # 用今天，避免周一时落到上周范围外
               "items": [{"name": "米饭", "category": "主食", "portion": "中", "tags": [], "source": "user"}]}
    with TestClient(app) as alice, TestClient(app) as bob:
        _login(alice, "alice", "alice-pass-123")
        _login(bob, "bob", "bob-pass-12345")
        r = alice.post("/api/meals", json=payload)
        assert r.status_code == 201
        meal_id = r.json()["id"]
        assert alice.get("/api/meals").json()["total"] == 1
        assert bob.get("/api/meals").json()["total"] == 0
        assert bob.get(f"/api/meals/{meal_id}").status_code == 404
        assert bob.put(f"/api/meals/{meal_id}", json={"note": "hack"}).status_code == 404
        assert bob.delete(f"/api/meals/{meal_id}").status_code == 404
        # 统计 / 查询 / 报告也隔离
        assert alice.get("/api/stats").json()["meal_count"] == 1
        assert bob.get("/api/stats").json()["meal_count"] == 0
        rep = alice.post("/api/reports", json={"period_type": "week"}).json()
        assert bob.get(f"/api/reports/{rep['id']}").status_code == 404
        assert len(bob.get("/api/reports").json()) == 0
        alice.post("/api/query", json={"question": "这周吃了几餐"})
        assert len(bob.get("/api/query/history").json()) == 0
        # 通知配置隔离
        alice.put("/api/notify/settings", json={"config": {"channels": {"pushplus": {"enabled": True, "token": "t1"}}}})
        assert "pushplus" not in bob.get("/api/notify/settings").json()["enabled_channels"]
        alice.put("/api/notify/settings", json={"config": {"channels": {"pushplus": {"enabled": False, "token": "__clear__"}}}})
    # 管理员自己也看不到 alice 的数据
    assert client.get("/api/meals").json()["total"] == 0


def test_settings_admin_only(client):
    _ensure_user(client, "alice", "alice-pass-123")
    with TestClient(app) as alice:
        _login(alice, "alice", "alice-pass-123")
        r = alice.get("/api/settings")
        assert r.status_code == 200 and r.json()["can_edit"] is False
        assert alice.put("/api/settings", json={"provider": "openai"}).status_code == 403
        assert alice.post("/api/settings/test").status_code == 403
        assert alice.get("/api/admin/users").status_code == 403
    assert client.get("/api/settings").json()["can_edit"] is True


def test_api_tokens(client, clean_meals):
    r = client.post("/api/tokens", json={"name": "mcp", "scopes": "mcp"})
    assert r.status_code == 201
    raw = r.json()["token"]
    assert raw.startswith("ddt_")
    tokens = client.get("/api/tokens").json()
    assert tokens[0]["name"] == "mcp" and "token" not in tokens[0]
    with TestClient(app) as c:
        h = {"Authorization": f"Bearer {raw}"}
        assert c.get("/api/meals", headers=h).status_code == 200
        assert c.get("/api/auth/status", headers=h).json()["authenticated"] is True
        assert c.get("/api/meals", headers={"Authorization": "Bearer ddt_wrong"}).status_code == 401
    client.delete(f"/api/tokens/{tokens[0]['id']}")
    with TestClient(app) as c:
        assert c.get("/api/meals", headers={"Authorization": f"Bearer {raw}"}).status_code == 401


def test_legacy_migration_adds_columns(tmp_path):
    """模拟 v0.2 旧库：无 role / user_id 列，迁移后补列并回填。"""
    import sqlite3

    from sqlalchemy import create_engine, inspect, text

    from app import db as dbmod

    path = tmp_path / "legacy.db"
    con = sqlite3.connect(path)
    con.executescript("""
        CREATE TABLE users(id INTEGER PRIMARY KEY, username VARCHAR(40), password_hash VARCHAR(200),
            totp_enabled BOOLEAN, totp_secret VARCHAR(64), totp_pending_secret VARCHAR(64), backup_codes TEXT, created_at DATETIME);
        INSERT INTO users(id, username, password_hash, totp_enabled) VALUES (1, 'old', 'x', 0);
        CREATE TABLE meals(id INTEGER PRIMARY KEY, eaten_at DATETIME, meal_type VARCHAR(10), image_path VARCHAR(300), note TEXT,
            ai_model VARCHAR(100), ai_raw_json TEXT, ai_latency_ms INTEGER, confirmed BOOLEAN, created_at DATETIME, updated_at DATETIME);
        INSERT INTO meals(id, eaten_at, meal_type, confirmed) VALUES (1, '2026-09-01 12:00:00', '午餐', 1);
        CREATE TABLE settings(key VARCHAR(60) PRIMARY KEY, value TEXT);
        INSERT INTO settings(key, value) VALUES ('notify_config', '{"channels": {"pushplus": {"enabled": true, "token": "abc"}}}');
    """)
    con.commit()
    con.close()
    legacy_engine = create_engine(f"sqlite:///{path}", future=True)
    orig_engine = dbmod.engine
    dbmod.engine = legacy_engine
    try:
        dbmod.Base.metadata.create_all(bind=legacy_engine)
        done = dbmod.migrate()
    finally:
        dbmod.engine = orig_engine
    assert "users.role" in done and "meals.user_id" in done and "users.first->admin" in done
    assert any(d.startswith("meals.user_id backfill") for d in done)
    assert "notify_config -> user_settings" in done
    cols = {c["name"] for c in inspect(legacy_engine).get_columns("meals")}
    assert {"user_id", "source"} <= cols
    with legacy_engine.connect() as conn:
        assert conn.execute(text("SELECT role FROM users WHERE id=1")).scalar() == "admin"
        assert conn.execute(text("SELECT user_id FROM meals WHERE id=1")).scalar() == 1
        assert conn.execute(text("SELECT COUNT(*) FROM user_settings WHERE key='notify_config'")).scalar() == 1
