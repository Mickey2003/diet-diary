"""v0.8.5 回归：/uploads 支持多级子目录（餐单配图、分享卡片图）。

根因：旧实现只声明 GET /uploads/{name}（单层），导致
  /uploads/dish_images/x.jpg 与 /uploads/share/x.png 全部 404，
表现为「餐单图片无法显示」「历史分享卡片图片无法加载、下载得到损坏文件」。
"""
import os
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import config
from app.db import SessionLocal
from app.main import app
from app.models import User
from app.services import auth as auth_svc


@pytest.fixture()
def client(tmp_path, monkeypatch):
    up = tmp_path / "uploads"
    (up / "dish_images").mkdir(parents=True)
    (up / "share").mkdir(parents=True)
    (up / "dish_images" / "dish.jpg").write_bytes(b"\xff\xd8\xff" + b"0" * 2048)
    (up / "share" / "card.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 2048)
    (up / "top.jpg").write_bytes(b"\xff\xd8\xff" + b"0" * 2048)
    monkeypatch.setattr(config, "UPLOAD_DIR", up)

    with TestClient(app) as c:
        yield c


def _login(c: TestClient) -> None:
    db = SessionLocal()
    try:
        u = db.query(User).filter(User.username == "up_tester").first()
        if u is None:
            u = User(username="up_tester", password_hash=auth_svc.hash_password("pw123456"),
                     role="user", is_active=True)
            db.add(u)
            db.commit()
    finally:
        db.close()
    r = c.post("/api/auth/login", json={"username": "up_tester", "password": "pw123456"})
    assert r.status_code == 200, r.text


def test_single_level_upload(client: TestClient):
    _login(client)
    r = client.get("/uploads/top.jpg")
    assert r.status_code == 200 and len(r.content) > 1024


def test_dish_images_subdir(client: TestClient):
    _login(client)
    r = client.get("/uploads/dish_images/dish.jpg")
    assert r.status_code == 200 and len(r.content) > 1024


def test_share_subdir(client: TestClient):
    _login(client)
    r = client.get("/uploads/share/card.png")
    assert r.status_code == 200 and len(r.content) > 1024


def test_path_traversal_blocked(client: TestClient):
    _login(client)
    # 用 %2e%2e 规避 httpx 的路径规范化，真正把 ".." 交给后端处理
    for bad in ("/uploads/%2e%2e/config.py",
                "/uploads/dish_images/%2e%2e/%2e%2e/config.py"):
        r = client.get(bad)
        assert r.status_code == 404, f"{bad} -> {r.status_code}"


def test_missing_subdir_file_404(client: TestClient):
    _login(client)
    r = client.get("/uploads/dish_images/not-there.jpg")
    assert r.status_code == 404


def test_uploads_requires_login(client: TestClient):
    r = client.get("/uploads/dish_images/dish.jpg")
    assert r.status_code in (401, 403)
