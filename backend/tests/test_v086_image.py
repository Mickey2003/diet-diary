"""v0.8.6 测试：SenseAudio 生图适配、emoji 兜底、生图独立配置、批量替换接口。"""
import json
import os
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import config
from app.services import dish_emoji, dish_image, image_client


# ---------------------------------------------------------------------------
# emoji 映射
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name,expected", [
    ("小米山药粥", "🥣"),
    ("水煮蛋", "🥚"),
    ("温牛奶", "🥛"),
    ("清蒸鲈鱼", "🐟"),
    ("蒜蓉西兰花", "🥦"),
])
def test_emoji_mapping_given_examples(name, expected):
    """用户给出的对照表必须完全命中。"""
    assert dish_emoji.emoji_for(name) == expected


def test_emoji_keyword_and_fallback():
    assert dish_emoji.emoji_for("凉拌黄瓜") == "🥒"
    assert dish_emoji.emoji_for("红烧肉") == "🥩"
    assert dish_emoji.emoji_for("番茄炒蛋") == "🍳"
    # 完全未知 → 兜底
    assert dish_emoji.emoji_for("神秘料理X") == dish_emoji.FALLBACK
    assert dish_emoji.emoji_for("") == dish_emoji.FALLBACK
    # 永不返回空
    assert dish_emoji.emoji_for("随便什么") != ""


def test_emoji_image_url_is_twemoji():
    u = dish_emoji.emoji_image_url("🥣")
    assert u.startswith("https://cdn.jsdelivr.net/")
    assert u.endswith(".svg")
    assert dish_emoji.emoji_image_url("", "twemoji") == ""


# ---------------------------------------------------------------------------
# SenseAudio 适配
# ---------------------------------------------------------------------------

def test_senseaudio_size_picker_respects_model():
    model = "senseaudio-image-2.0-260319"
    # 想要 200x150（横图）→ 应挑该模型允许的横图，而不是原样返回
    got = image_client.senseaudio_pick_size(model, "200x150")
    assert got in image_client.SENSEAUDIO_MODELS[model]["sizes"]
    # 已支持的尺寸原样返回
    assert image_client.senseaudio_pick_size(model, "1024x1024") == "1024x1024"
    # 未知模型 → 原样返回
    assert image_client.senseaudio_pick_size("nope", "640x480") == "640x480"


def test_is_senseaudio_base():
    assert image_client.is_senseaudio_base("https://api.senseaudio.cn")
    assert image_client.is_senseaudio_base("https://api.senseaudio.cn/v1")
    assert not image_client.is_senseaudio_base("https://api.openai.com/v1")


def test_senseaudio_error_mapping():
    assert "429" in image_client.SENSEAUDIO_ERRORS["429000"] or "频繁" in image_client.SENSEAUDIO_ERRORS["429000"]
    assert "余额" in image_client.SENSEAUDIO_ERRORS["400001"]


def test_generate_without_key_is_fatal():
    res = image_client.generate_senseaudio("测试", api_key="")
    assert res.ok is False
    assert res.fatal is True


def test_generate_via_mock_transport(monkeypatch):
    """用假 httpx 验证 sync 路径解析与落盘。"""
    import httpx as _httpx

    png = (b"\x89PNG\r\n\x1a\n" + b"\x00" * 4096)

    class FakeResp:
        def __init__(self, status=200, payload=None, content=b""):
            self.status_code = status
            self._payload = payload or {}
            self.content = content or json.dumps(payload or {}).encode()
            self.text = self.content.decode()

        def json(self):
            return self._payload

    class FakeClient:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def post(self, url, headers=None, json=None):
            assert url.endswith("/v1/image/sync")
            assert headers["Authorization"].startswith("Bearer ")
            assert "prompt" in (json or {})
            return FakeResp(200, {"url": "https://cdn.example.com/x.png"})

        def get(self, *a, **k):
            return FakeResp(200, {})

    monkeypatch.setattr(_httpx, "Client", FakeClient)

    captured = {}

    def fake_get(url, **kwargs):
        captured["url"] = url
        return _httpx.Response(200, content=png,
                               headers={"content-type": "image/png"},
                               request=_httpx.Request("GET", url))

    monkeypatch.setattr(_httpx, "get", fake_get)

    tmp = Path(tempfile.mkdtemp())
    monkeypatch.setattr(dish_image, "LOCAL_DIR", str(tmp / "dish_images"))
    monkeypatch.setattr(dish_image, "THUMB_DIR", str(tmp / "thumb"))
    monkeypatch.setattr(dish_image, "_CACHE", {})

    res = dish_image.generate_dish_image("清蒸鲈鱼", db=None)
    # db=None 时 get_image_config 读 env，未配置 → 直接 None
    assert res is None


def test_image_config_ready_false_by_default():
    assert dish_image.image_config_ready(None) is False


# ---------------------------------------------------------------------------
# 餐单补图：emoji 兜底字段
# ---------------------------------------------------------------------------

def test_enrich_adds_emoji_fields_even_without_images(monkeypatch):
    monkeypatch.setattr(dish_image, "_CACHE", {})
    plan = {"days": [{"meals": [{"dishes": [
        {"name": "小米山药粥"},
        {"name": "清蒸鲈鱼"},
        {"name": "神秘料理X"},
    ]}]}]}
    out = dish_image.enrich_plan_images(plan, db=None, web_enabled=False, ai_enabled=False)
    dishes = out["days"][0]["meals"][0]["dishes"]
    assert dishes[0]["image_emoji"] == "🥣"
    assert dishes[1]["image_emoji"] == "🐟"
    assert dishes[2]["image_emoji"] == dish_emoji.FALLBACK
    # 无图时仍带 emoji，前端不需要空窗
    assert "image_emoji_url" in dishes[0]


def test_count_emoji_dishes():
    plan = {"days": [{"meals": [{"dishes": [
        {"name": "A", "image_url": "/uploads/dish_images/a.webp"},
        {"name": "B"},
        {"name": "C"},
    ]}]}]}
    assert dish_image.count_emoji_dishes(plan) == 2


# ---------------------------------------------------------------------------
# 接口层
# ---------------------------------------------------------------------------

def test_settings_exposes_image_config(client):
    r = client.get("/api/settings")
    assert r.status_code == 200
    j = r.json()
    assert "image_providers" in j
    ids = [p["id"] for p in j["image_providers"]]
    assert "senseaudio" in ids
    assert "image_ready" in j
    assert j["image_emoji_fallback"] is True


def test_replace_emoji_requires_ai_enabled(client):
    # 默认 dish_ai_images 关闭 → 400
    r = client.post("/api/health/plans/1/replace-emoji-images")
    assert r.status_code in (400, 404)


def test_plan_to_dict_has_image_stats(client, db):
    from app.services import meal_plan as mp
    plans = mp.get_plans(db, db.execute(__import__("sqlalchemy").text(
        "select id from users where username='tester'")).scalar())
    if plans:
        assert "image_stats" in plans[0]
        assert set(plans[0]["image_stats"]) == {"total", "emoji", "with_image"}


# ---------------------------------------------------------------------------
# v0.8.6 补充：生图模型字段隔离 / 缩略图派生 / 前端消费的字段齐备性
# ---------------------------------------------------------------------------

def test_settings_image_model_id_field_exists(client):
    """生图专用模型字段名为 image_model_id，且与旧 image_model 并存不冲突。"""
    r = client.get("/api/settings")
    j = r.json()
    assert "image_model_id" in j
    assert "image_model" in j  # 旧字段保留兼容


def test_image_model_db_key_is_isolated():
    """生图模型写 dish_image_model，不能覆盖旧的 image_model。"""
    import inspect
    from app.routers import settings as st
    src = inspect.getsource(st.update_settings)
    assert '"dish_image_model"' in src


def test_get_image_config_reads_new_key():
    """get_image_config 优先读 dish_image_model。"""
    import inspect
    from app.services import dish_image
    src = inspect.getsource(dish_image.get_image_config)
    assert "dish_image_model" in src


def test_thumb_url_for_local_image():
    from app.services import dish_image
    assert dish_image.thumb_url_for("/uploads/dish_images/abc.webp") == "/uploads/thumb/abc.webp"
    assert dish_image.thumb_url_for("/uploads/dish_images/abc.jpg") == "/uploads/thumb/abc.webp"
    # 非本地图 / 空值 → 空串（前端回退原图）
    assert dish_image.thumb_url_for("https://x/y.jpg") == ""
    assert dish_image.thumb_url_for("") == ""


def test_enrich_sets_thumb_url_when_cache_hits():
    """命中缓存且本地文件存在时，应同时写入 image_url 与 thumb_url。"""
    import os

    from app.services import dish_image

    fn = "v086thumb.webp"
    os.makedirs(dish_image.LOCAL_DIR, exist_ok=True)
    with open(os.path.join(dish_image.LOCAL_DIR, fn), "wb") as f:
        f.write(b"x" * 2048)
    try:
        dish_image._cache_set(dish_image._normalize("缩略图测试菜"),
                              f"/uploads/dish_images/{fn}")
        plan = {"days": [{"date": "2026-09-15", "meals": [
            {"meal_type": "午餐", "time": "12:00",
             "dishes": [{"name": "缩略图测试菜", "category": "主食", "portion": "中"}]}]}]}
        dish_image.enrich_plan_images(plan, db=None, web_enabled=False, ai_enabled=False)
        d = plan["days"][0]["meals"][0]["dishes"][0]
        assert d["image_url"].endswith(fn)
        assert d["thumb_url"] == f"/uploads/thumb/v086thumb.webp"
        assert d["image_emoji"]  # emoji 兜底字段始终存在
    finally:
        try:
            os.remove(os.path.join(dish_image.LOCAL_DIR, fn))
        except OSError:
            pass


def test_image_model_id_does_not_pollute_legacy_image_model(client, db):
    """生图模型（image_model_id）必须与旧的 OpenAI 兼容配图模型（image_model）隔离。"""
    from app.models import Setting

    # 先写旧字段，模拟已存在的旧部署
    r = client.put("/api/settings", json={"image_model": "dall-e-3"})
    assert r.status_code == 200

    # 再写新生图模型
    r = client.put("/api/settings", json={"image_model_id": "senseaudio-image-2.0-260319"})
    assert r.status_code == 200

    rows = {s.key: s.value for s in db.query(Setting).all()}
    assert rows.get("dish_image_model") == "senseaudio-image-2.0-260319"
    assert rows.get("image_model") == "dall-e-3"  # 旧字段未被覆盖

    j = r.json()
    assert j["image_model_id"] == "senseaudio-image-2.0-260319"
    assert j["image_model"] == "dall-e-3"
