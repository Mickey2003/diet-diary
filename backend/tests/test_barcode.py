"""
测试条形码功能（Feature 2）。
覆盖：格式校验、缓存命中、OFF API mock（成功+失败+内置兜底）、手动优先、/log 创建餐食。
"""
import json
from datetime import datetime
from typing import Any, Dict, Optional
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models import Meal, PackagedFood
from app.services import barcode
from app.services.barcode import _BUILTIN
from tests.conftest import TEST_USER


# ---------- 辅助 ----------

def _login(c: TestClient, username: str, password: str) -> None:
    r = c.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text


def _ensure_user(admin_client, username, password):
    users = admin_client.get("/api/admin/users").json()
    for u in users:
        if u["username"] == username:
            return u["id"]
    r = admin_client.post("/api/admin/users",
                          json={"username": username, "password": password, "role": "user"})
    assert r.status_code == 201
    return r.json()["id"]


# 可口可乐条形码（内置兜底表中有）
COLA_CODE = "6928804011142"
# 农夫山泉
NONGFU_CODE = "6921168509256"
# 奥利奥
OREO_CODE = "6901939621608"
# 不在内置表中的条形码（用于 OFF mock）
MOCK_CODE = "12345678"

# 模拟 OFF 返回的产品数据
_MOCK_OFF_PRODUCT = {
    "code": MOCK_CODE,
    "product_name": "Test Snack",
    "product_name_zh": "测试零食",
    "brands": "测试品牌",
    "categories_tags": ["en:snacks", "en:biscuits"],
    "nutriments": {
        "sugars_100g": 20.0,
        "salt_100g": 0.5,
        "fat_100g": 10.0,
        "proteins_100g": 5.0,
        "carbohydrates_100g": 60.0,
        "energy-kcal_100g": 450.0,
    },
    "image_front_small_url": "https://example.com/img.jpg",
    "quantity": "100g",
}


# ---------- 格式校验 ----------

def test_barcode_too_short(client):
    r = client.get("/api/barcode/1234567")  # 7位
    assert r.status_code == 400


def test_barcode_too_long(client):
    r = client.get("/api/barcode/123456789012345")  # 15位
    assert r.status_code == 400


def test_barcode_non_digit(client):
    r = client.get("/api/barcode/123abc456")
    assert r.status_code == 400


def test_barcode_valid_format_8_digits(client, db):
    """8 位纯数字是合法条形码（应不返回 400）。"""
    # MOCK_CODE = "12345678"，OFF 会返回 not found → found=false
    with patch("app.services.barcode.fetch_openfoodfacts", return_value=None):
        r = client.get(f"/api/barcode/{MOCK_CODE}")
    assert r.status_code == 200
    assert r.json()["found"] is False


# ---------- 内置兜底表 ----------

def test_builtin_cola(client, db):
    """可口可乐在内置兜底表中，应找到并返回正确分类。"""
    # 先清除缓存（如果存在）
    pf = db.get(PackagedFood, COLA_CODE)
    if pf:
        db.delete(pf)
        db.commit()
    with patch("app.services.barcode.fetch_openfoodfacts", return_value=None):
        r = client.get(f"/api/barcode/{COLA_CODE}")
    assert r.status_code == 200
    data = r.json()
    assert data["found"] is True
    assert data["product"]["category"] == "饮品"
    assert "sugary_drink" in data["product"]["tags"]
    assert data["suggested_item"]["source"] == "barcode"


def test_builtin_noodles_high_salt(client, db):
    """康师傅方便面在内置表中，应有 high_salt 标签。"""
    pf = db.get(PackagedFood, "6920152400487")
    if pf:
        db.delete(pf)
        db.commit()
    with patch("app.services.barcode.fetch_openfoodfacts", return_value=None):
        r = client.get("/api/barcode/6920152400487")
    assert r.status_code == 200
    data = r.json()
    assert data["found"] is True
    assert "high_salt" in data["product"]["tags"]


# ---------- 缓存命中 ----------

def test_cache_hit(client, db):
    """已缓存的商品直接返回，不调用 OFF。"""
    # 手动插入缓存
    pf = db.get(PackagedFood, MOCK_CODE)
    if pf is None:
        pf = PackagedFood(
            barcode=MOCK_CODE, name="缓存零食", category="甜点零食",
            tags=json.dumps(["sweet"]), source="openfoodfacts",
        )
        db.add(pf)
        db.commit()

    call_count = {"n": 0}
    def _no_call(code):
        call_count["n"] += 1
        return None

    with patch("app.services.barcode.fetch_openfoodfacts", side_effect=_no_call):
        r = client.get(f"/api/barcode/{MOCK_CODE}")

    assert r.status_code == 200
    assert r.json()["found"] is True
    assert call_count["n"] == 0  # 缓存命中，未调用 OFF


# ---------- OFF API mock（成功） ----------

def test_off_api_success(client, db, monkeypatch):
    """OFF API 返回产品时，应解析并缓存，返回 found=true。"""
    from app import config
    # 清除缓存
    pf = db.get(PackagedFood, MOCK_CODE)
    if pf:
        db.delete(pf)
        db.commit()

        # 测试默认关闭远程源：这里临时开启，并把数据源限制为 OFF 一个（避免联网、避免设置污染）
        # 注意：用 lambda 延迟查找模块属性，确保下面的 patch 能生效
        monkeypatch.setattr(config, "BARCODE_EXTRA_SOURCES", True)
        monkeypatch.setattr(barcode, "_SOURCES", (
            ("openfoodfacts", lambda code, db=None: barcode.fetch_openfoodfacts(code, db),
             barcode._parse_off_product),
        ))

        with patch("app.services.barcode.fetch_openfoodfacts", return_value=_MOCK_OFF_PRODUCT):
            r = client.get(f"/api/barcode/{MOCK_CODE}")

        assert r.status_code == 200
        data = r.json()
        assert data["found"] is True
        assert data["source"] == "openfoodfacts"
    assert data["product"]["name"] == "测试零食"
    assert data["product"]["category"] == "甜点零食"
    assert "sweet" in data["product"]["tags"]
    assert data["product"]["nutriments"]["sugars_100g"] == 20.0
    assert data["suggested_item"]["category"] == "甜点零食"

    # 应已写入缓存
    db.expire_all()
    pf2 = db.get(PackagedFood, MOCK_CODE)
    assert pf2 is not None
    assert pf2.name == "测试零食"


# ---------- OFF API mock（失败/网络错误 → 兜底） ----------

def test_off_api_failure_falls_back_to_builtin(client, db):
    """OFF API 异常时应使用内置兜底表，不返回 500。"""
    pf = db.get(PackagedFood, COLA_CODE)
    if pf:
        db.delete(pf)
        db.commit()

    def _raise(code):
        raise ConnectionError("网络不通")

    with patch("app.services.barcode.fetch_openfoodfacts", side_effect=_raise):
        r = client.get(f"/api/barcode/{COLA_CODE}")

    assert r.status_code == 200
    data = r.json()
    assert data["found"] is True  # 内置兜底找到


def test_off_api_failure_unknown_barcode(client, db):
    """OFF API 失败且不在内置表中 → found=false，有 error 字段，不 500。"""
    unknown_code = "99999999"
    pf = db.get(PackagedFood, unknown_code)
    if pf:
        db.delete(pf)
        db.commit()

    def _raise(code):
        raise ConnectionError("超时")

    with patch("app.services.barcode.fetch_openfoodfacts", side_effect=_raise):
        r = client.get(f"/api/barcode/{unknown_code}")

    assert r.status_code == 200
    data = r.json()
    assert data["found"] is False
    assert "error" in data


# ---------- 手动录入优先 ----------

def test_manual_override_precedence(client, db):
    """手动录入（source=manual）优先于 OFF 缓存。"""
    # 先写入 OFF 缓存
    pf = db.get(PackagedFood, MOCK_CODE)
    if pf is None:
        pf = PackagedFood(
            barcode=MOCK_CODE, name="OFF 名称", category="其他",
            tags=json.dumps([]), source="openfoodfacts",
        )
        db.add(pf)
        db.commit()

    # 手动覆盖
    r = client.put(f"/api/barcode/{MOCK_CODE}", json={
        "name": "手动商品名",
        "category": "甜点零食",
        "tags": ["sweet"],
        "brand": "手动品牌",
    })
    assert r.status_code == 200
    assert r.json()["source"] == "manual"
    assert r.json()["product"]["name"] == "手动商品名"

    # 再次查询应返回 manual 版本（不调用 OFF）
    call_count = {"n": 0}
    def _count(code):
        call_count["n"] += 1
        return None
    with patch("app.services.barcode.fetch_openfoodfacts", side_effect=_count):
        r2 = client.get(f"/api/barcode/{MOCK_CODE}")
    assert r2.json()["source"] == "manual"
    assert r2.json()["product"]["name"] == "手动商品名"
    assert call_count["n"] == 0  # 缓存命中，未调用 OFF


# ---------- PUT /api/barcode/{code} ----------

def test_put_barcode_creates_entry(client, db):
    new_code = "11111111"
    pf = db.get(PackagedFood, new_code)
    if pf:
        db.delete(pf)
        db.commit()
    r = client.put(f"/api/barcode/{new_code}", json={
        "name": "新商品",
        "category": "饮品",
        "tags": ["sugar_free_drink"],
    })
    assert r.status_code == 200
    assert r.json()["product"]["name"] == "新商品"
    db.expire_all()
    assert db.get(PackagedFood, new_code) is not None


# ---------- GET /api/barcode/recent ----------

def test_recent_barcodes(client, clean_meals, db):
    """最近扫过的商品接口：应按使用顺序返回。"""
    # 确保 COLA_CODE 在缓存中
    pf = db.get(PackagedFood, COLA_CODE)
    if pf is None:
        with patch("app.services.barcode.fetch_openfoodfacts", return_value=None):
            client.get(f"/api/barcode/{COLA_CODE}")

    # 用条形码创建一餐
    with patch("app.services.barcode.fetch_openfoodfacts", return_value=None):
        client.get(f"/api/barcode/{COLA_CODE}")
    # 确保有缓存后 log
    pf2 = db.get(PackagedFood, COLA_CODE)
    if pf2 is None:
        pf2 = PackagedFood(
            barcode=COLA_CODE, name="可口可乐", category="饮品",
            tags=json.dumps(["sugary_drink"]), source="openfoodfacts",
        )
        db.add(pf2)
        db.commit()

    r_log = client.post(f"/api/barcode/{COLA_CODE}/log", json={
        "meal_type": "加餐",
        "eaten_at": "2026-09-05T15:00:00",
    })
    assert r_log.status_code == 201

    r = client.get("/api/barcode/recent")
    assert r.status_code == 200
    barcodes = [p["barcode"] for p in r.json()]
    assert COLA_CODE in barcodes


# ---------- POST /api/barcode/{code}/log ----------

def test_log_creates_meal_with_barcode_source(client, clean_meals, db):
    """通过条形码记录餐食应创建 source=barcode 的 Meal。"""
    # 确保商品在缓存中
    pf = db.get(PackagedFood, NONGFU_CODE)
    if pf is None:
        pf = PackagedFood(
            barcode=NONGFU_CODE, name="农夫山泉 550ml", category="饮品",
            tags=json.dumps(["sugar_free_drink"]), source="openfoodfacts",
        )
        db.add(pf)
        db.commit()

    r = client.post(f"/api/barcode/{NONGFU_CODE}/log", json={
        "meal_type": "饮品",
        "eaten_at": "2026-09-05T10:00:00",
        "portion": "中",
        "note": "运动后补水",
    })
    assert r.status_code == 201, r.text
    data = r.json()
    assert data["source"] == "barcode"
    assert data["meal_type"] == "饮品"
    assert len(data["items"]) == 1
    assert data["items"][0]["barcode"] == NONGFU_CODE


def test_log_404_unknown_code(client):
    """未知条形码 /log 应返回 404。"""
    r = client.post("/api/barcode/99999999/log", json={"meal_type": "加餐"})
    assert r.status_code == 404


def test_barcode_anon_401(anon_client):
    r = anon_client.get(f"/api/barcode/{COLA_CODE}")
    assert r.status_code == 401
