"""登录、会话、两步验证、密码修改、限速、受保护资源。"""
import pyotp

from app.services import auth as auth_service

from .conftest import TEST_USER


def test_protected_endpoints_require_login(anon_client):
    assert anon_client.get("/api/meals").status_code == 401
    assert anon_client.get("/api/settings").status_code == 401
    assert anon_client.get("/api/stats").status_code == 401
    assert anon_client.get("/uploads/whatever.jpg").status_code == 401
    assert anon_client.get("/api/health").status_code == 200
    s = anon_client.get("/api/auth/status").json()
    assert s["authenticated"] is False and s["users_exist"] is True


def test_login_wrong_password(anon_client):
    r = anon_client.post("/api/auth/login", json={"username": TEST_USER[0], "password": "nope"})
    assert r.status_code == 401
    auth_service.clear_fails("testclient", TEST_USER[0])


def test_login_sets_cookie_and_me(client):
    assert auth_service.SESSION_COOKIE in client.cookies
    me = client.get("/api/auth/me").json()
    assert me["username"] == TEST_USER[0]
    assert me["totp_enabled"] is False
    assert client.get("/api/meals").status_code == 200
    # 退出后失效
    client.post("/api/auth/logout")
    client.cookies.clear()
    assert client.get("/api/meals").status_code == 401


def test_path_traversal_blocked(client):
    # /uploads 只接受单段文件名
    assert client.get("/uploads/.env").status_code == 404
    assert client.get("/uploads/nonexistent.jpg").status_code == 404
    # 前端静态托管的 catch-all 不能借 ../ 读到 dist 之外的文件（如 backend/.env.example）
    r = client.get("/..%2F..%2Fbackend%2F.env.example")
    assert "LLM_PROVIDER" not in r.text
    r = client.get("/uploads/..%2F..%2F..%2Fbackend%2F.env.example")
    assert "LLM_PROVIDER" not in r.text


def test_rate_limit_after_five_failures(anon_client):
    user = "ratelimit-user"
    for _ in range(5):
        anon_client.post("/api/auth/login", json={"username": user, "password": "x"})
    r = anon_client.post("/api/auth/login", json={"username": user, "password": "x"})
    assert r.status_code == 429
    auth_service.clear_fails("testclient", user)


def test_totp_full_flow(client):
    # 1. 生成密钥
    r = client.post("/api/auth/totp/setup", json={"password": "wrong"})
    assert r.status_code == 400
    r = client.post("/api/auth/totp/setup", json={"password": TEST_USER[1]})
    assert r.status_code == 200
    secret = r.json()["secret"]
    assert r.json()["qr_data_url"].startswith("data:image/png;base64,")
    # 2. 错误验证码不能开启
    assert client.post("/api/auth/totp/enable", json={"code": "000000"}).status_code == 400
    # 3. 正确验证码开启，拿到备用码
    code = pyotp.TOTP(secret).now()
    r = client.post("/api/auth/totp/enable", json={"code": code})
    assert r.status_code == 200
    backup = r.json()["backup_codes"]
    assert len(backup) == 10
    assert client.get("/api/auth/me").json()["totp_enabled"] is True

    # 4. 重新登录需要两步
    client.post("/api/auth/logout")
    client.cookies.clear()
    r = client.post("/api/auth/login", json={"username": TEST_USER[0], "password": TEST_USER[1]})
    body = r.json()
    assert body["need_totp"] is True
    pending = body["pending_token"]
    assert client.get("/api/meals").status_code == 401  # 尚未完成验证
    r = client.post("/api/auth/login/totp", json={"pending_token": pending, "code": "123456"})
    assert r.status_code == 401
    r = client.post("/api/auth/login/totp", json={"pending_token": pending, "code": pyotp.TOTP(secret).now()})
    assert r.status_code == 200
    assert client.get("/api/meals").status_code == 200

    # 5. 备用码只能用一次
    client.post("/api/auth/logout")
    client.cookies.clear()
    pending = client.post("/api/auth/login", json={"username": TEST_USER[0], "password": TEST_USER[1]}).json()["pending_token"]
    assert client.post("/api/auth/login/totp", json={"pending_token": pending, "code": backup[0]}).status_code == 200
    assert client.get("/api/auth/me").json()["backup_codes_left"] == 9
    client.post("/api/auth/logout")
    client.cookies.clear()
    pending = client.post("/api/auth/login", json={"username": TEST_USER[0], "password": TEST_USER[1]}).json()["pending_token"]
    assert client.post("/api/auth/login/totp", json={"pending_token": pending, "code": backup[0]}).status_code == 401
    auth_service.clear_fails("testclient", f"totp:{TEST_USER[0]}")
    assert client.post("/api/auth/login/totp", json={"pending_token": pending, "code": pyotp.TOTP(secret).now()}).status_code == 200

    # 6. 关闭两步验证
    r = client.post("/api/auth/totp/disable", json={"password": TEST_USER[1], "code": pyotp.TOTP(secret).now()})
    assert r.status_code == 200
    assert client.get("/api/auth/me").json()["totp_enabled"] is False


def test_change_password_revokes_other_sessions(client, anon_client):
    # 另一个设备也登录
    r = anon_client.post("/api/auth/login", json={"username": TEST_USER[0], "password": TEST_USER[1]})
    assert r.status_code == 200
    assert anon_client.get("/api/meals").status_code == 200
    # 当前设备改密码
    r = client.post("/api/auth/password", json={"current_password": "bad", "new_password": "new-pass-456"})
    assert r.status_code == 400
    r = client.post("/api/auth/password", json={"current_password": TEST_USER[1], "new_password": "new-pass-456"})
    assert r.status_code == 200
    assert client.get("/api/meals").status_code == 200       # 当前设备重新签发
    assert anon_client.get("/api/meals").status_code == 401  # 其他设备下线
    # 还原密码，避免影响其他测试
    r = client.post("/api/auth/password", json={"current_password": "new-pass-456", "new_password": TEST_USER[1]})
    assert r.status_code == 200


def test_password_hash_roundtrip():
    h = auth_service.hash_password("秘密 password")
    assert h.startswith("pbkdf2_sha256$")
    assert auth_service.verify_password("秘密 password", h)
    assert not auth_service.verify_password("秘密 passwor", h)
    assert not auth_service.verify_password("x", "garbage")
