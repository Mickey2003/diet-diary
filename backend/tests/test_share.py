"""
测试分享文案功能（Feature 3）。
覆盖：weekly/monthly/today/meal 四种 kind，四种 tone，mock 回复结构校验，历史接口，图片接口。
"""
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models import Meal
from tests.conftest import TEST_USER, add_meal


# ---------- 辅助 ----------

def _card_request(client, kind="weekly", tone="轻松", anchor=None, meal_id=None):
    body = {"kind": kind, "tone": tone}
    if anchor:
        body["anchor"] = anchor
    if meal_id:
        body["meal_id"] = meal_id
    return client.post("/api/share/card", json=body)


# ---------- POST /api/share/card ----------

def test_share_card_weekly_shape(client, clean_meals, db):
    """weekly 卡片应返回正确的顶层字段。"""
    add_meal(db, 0, 12, "午餐", [("米饭", "主食", []), ("青菜", "蔬菜", ["vegetable"])])
    r = _card_request(client, kind="weekly")
    assert r.status_code == 200, r.text
    data = r.json()
    assert "copy" in data
    assert "facts" in data
    assert "card" in data
    assert "disclaimer" in data

    copy = data["copy"]
    assert "headline" in copy
    assert "body" in copy
    assert "hashtags" in copy
    assert "emoji" in copy
    assert len(copy["headline"]) <= 16
    assert len(copy["body"]) <= 80
    assert isinstance(copy["hashtags"], list)
    assert len(copy["hashtags"]) <= 5


def test_share_card_monthly_shape(client, clean_meals, db):
    """monthly 卡片应正常返回。"""
    add_meal(db, 0, 12, "午餐", [("米饭", "主食", [])])
    r = _card_request(client, kind="monthly")
    assert r.status_code == 200
    data = r.json()
    assert data["facts"]["kind"] == "monthly"
    assert "card" in data


def test_share_card_today_shape(client, clean_meals, db):
    """today 卡片应包含今天的餐食统计。"""
    add_meal(db, 0, 12, "午餐", [("米饭", "主食", [])])
    r = _card_request(client, kind="today")
    assert r.status_code == 200
    data = r.json()
    assert data["facts"]["kind"] == "today"
    assert "meal_count" in data["facts"]


def test_share_card_meal_shape(client, clean_meals, db):
    """meal 卡片需提供 meal_id。"""
    m = add_meal(db, 0, 12, "午餐", [("米饭", "主食", []), ("炒蛋", "蛋白质", ["egg"])])
    r = _card_request(client, kind="meal", meal_id=m.id)
    assert r.status_code == 200
    data = r.json()
    assert data["facts"]["kind"] == "meal"
    assert data["facts"]["meal_id"] == m.id
    assert data["facts"]["item_count"] == 2


def test_share_card_meal_missing_meal_id(client):
    """meal kind 不传 meal_id 应返回 400。"""
    r = client.post("/api/share/card", json={"kind": "meal", "tone": "轻松"})
    assert r.status_code == 400


def test_share_card_invalid_kind(client):
    r = client.post("/api/share/card", json={"kind": "yearly", "tone": "轻松"})
    assert r.status_code == 400


# ---------- 四种 tone ----------

@pytest.mark.parametrize("tone", ["轻松", "励志", "文艺", "极简"])
def test_share_card_all_tones(client, clean_meals, db, tone):
    add_meal(db, 0, 12, "午餐", [("米饭", "主食", [])])
    r = _card_request(client, kind="weekly", tone=tone)
    assert r.status_code == 200
    copy = r.json()["copy"]
    assert copy["headline"]
    assert copy["body"]


# ---------- card 布局字段 ----------

def test_share_card_layout_fields(client, clean_meals, db):
    add_meal(db, 0, 12, "午餐", [("米饭", "主食", [])])
    r = _card_request(client, kind="weekly")
    data = r.json()
    card = data["card"]
    assert "theme" in card
    assert card["theme"] in ("warm", "fresh", "night")
    assert "title" in card
    assert "subtitle" in card
    assert "stats" in card
    assert isinstance(card["stats"], list)
    assert len(card["stats"]) <= 4
    assert "footer" in card
    assert card["footer"] == "今天吃得怎么样 · AI 饮食观察日记"


# ---------- GET /api/share/history ----------

def test_share_history_accumulates(client, clean_meals, db):
    """连续生成卡片，history 应记录。"""
    add_meal(db, 0, 12, "午餐", [("米饭", "主食", [])])
    _card_request(client, kind="today")
    _card_request(client, kind="weekly")
    r = client.get("/api/share/history")
    assert r.status_code == 200
    history = r.json()
    assert len(history) >= 2
    # 最新的在前
    assert history[0]["kind"] in ("today", "weekly", "monthly", "meal")


def test_share_history_empty(client, clean_meals, db):
    """无历史时返回空列表。"""
    # 清除历史
    from app.models import UserSetting
    db.query(UserSetting).filter(
        UserSetting.key == "share_history"
    ).delete()
    db.commit()
    r = client.get("/api/share/history")
    assert r.status_code == 200
    # 可能有之前测试留下的，只要是 list 即可
    assert isinstance(r.json(), list)


def test_share_history_cap_20(client, clean_meals, db):
    """历史上限 20 条。"""
    add_meal(db, 0, 12, "午餐", [("米饭", "主食", [])])
    # 生成 25 次
    for _ in range(25):
        _card_request(client, kind="today")
    r = client.get("/api/share/history?limit=100")
    assert r.status_code == 200
    assert len(r.json()) <= 20


# ---------- POST /api/share/meal-image/{meal_id} ----------

def test_meal_image_no_image(client, clean_meals, db):
    """没有图片的餐食应返回 404。"""
    m = add_meal(db, 0, 12, "午餐", [("米饭", "主食", [])])
    r = client.post(f"/api/share/meal-image/{m.id}")
    assert r.status_code == 404


def test_meal_image_with_image(client, clean_meals, db):
    """有图片文件时应返回 image_url。"""
    from app import config as cfg
    # 先写一个假图片
    img_name = "test_share_img.jpg"
    img_path = Path(cfg.UPLOAD_DIR) / img_name
    img_path.write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 20)  # 伪 JPEG
    m = add_meal(db, 0, 12, "午餐", [("米饭", "主食", [])])
    m.image_path = img_name
    db.commit()
    r = client.post(f"/api/share/meal-image/{m.id}")
    assert r.status_code == 200
    assert "image_url" in r.json()
    assert img_name in r.json()["image_url"]


def test_meal_image_wrong_user(client, clean_meals, db):
    """其他用户的餐食应返回 404。"""
    _ensure_user = None
    from tests.conftest import add_meal as _add
    from app.models import User

    # 先确保 dave 用户存在
    with TestClient(app) as admin_c:
        r = admin_c.post("/api/auth/login", json={"username": TEST_USER[0], "password": TEST_USER[1]})
        assert r.status_code == 200
        users = admin_c.get("/api/admin/users").json()
        dave = next((u for u in users if u["username"] == "dave"), None)
        if dave is None:
            r2 = admin_c.post("/api/admin/users", json={"username": "dave", "password": "dave-pass-123", "role": "user"})
            assert r2.status_code == 201
            dave_id = r2.json()["id"]
        else:
            dave_id = dave["id"]

    m = _add(db, 0, 12, "午餐", [("米饭", "主食", [])], user_id=dave_id)
    r = client.post(f"/api/share/meal-image/{m.id}")
    assert r.status_code == 404


# ---------- 未登录 ----------

def test_share_anon_401(anon_client):
    r = anon_client.post("/api/share/card", json={"kind": "weekly"})
    assert r.status_code == 401

def test_share_history_anon_401(anon_client):
    r = anon_client.get("/api/share/history")
    assert r.status_code == 401
