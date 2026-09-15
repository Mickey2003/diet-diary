"""
v0.8.4 测试：
- 菜品图片服务端本地化（不再把外站 URL 发给客户端）
- AI 生图开关默认关闭
- 条码多源评分 / 未收录提示
- 全局任务忙状态接口
- 分享卡片历史图片保存
"""
import base64
import os

from app.services import barcode as barcode_svc
from app.services import dish_image


# ---------- 菜品图片本地化 ----------

def test_save_image_locally_returns_local_url():
    data = b"\x89PNG\r\n\x1a\n" + b"0" * 2048  # 伪造的 PNG 头 + 填充
    url = dish_image.save_image_locally(data, "番茄炒蛋", "image/png")
    assert url is not None
    assert url.startswith("/uploads/dish_images/")
    fname = url.rsplit("/", 1)[-1]
    assert os.path.isfile(os.path.join(dish_image.LOCAL_DIR, fname))


def test_ai_images_disabled_by_default(db):
    """未设置 dish_ai_images 时，AI 生图应关闭。"""
    assert dish_image.ai_images_enabled(db) is False


def test_image_cache_records_local_path():
    plan = {"days": [{"date": "2026-09-13", "meals": [
        {"meal_type": "午餐", "time": "12:00",
         "dishes": [{"name": "缓存测试菜", "category": "主食", "portion": "中"}]}]}]}
    # 关闭网络与 AI，直接写入缓存后应命中并填 image_url
    # 注：v0.8.6 起 enrich_plan_images 的第二个参数由 client 改为 db
    dish_image._cache_set(dish_image._normalize("缓存测试菜"), "/uploads/dish_images/x.png")
    dish_image.enrich_plan_images(plan, db=None, web_enabled=False, ai_enabled=False)
    # 缓存文件不存在 → 视为过期，不会填充（保持 emoji 兜底）
    assert plan["days"][0]["meals"][0]["dishes"][0].get("image_url") is None
    # 但 emoji 兜底字段必须已补上，保证前端永不空白
    assert plan["days"][0]["meals"][0]["dishes"][0].get("image_emoji")


# ---------- 条码 ----------

def test_barcode_score_prefers_richer_result():
    poor = {"name": "某食品", "brand": None, "nutriments_dict": {}, "image_url": None, "quantity": None}
    rich = {"name": "某食品", "brand": "某品牌", "nutriments_dict": {"energy_kcal_100g": 100},
            "image_url": "https://x/y.jpg", "quantity": "100g"}
    assert barcode_svc._score_parsed(rich) > barcode_svc._score_parsed(poor)


def test_barcode_not_found_message(client, db):
    """测试环境（关闭远程源）下，未收录的条码应给出明确提示。"""
    code = "12345670"
    from app.models import PackagedFood
    if db.get(PackagedFood, code):
        db.delete(db.get(PackagedFood, code))
        db.commit()
    r = client.get(f"/api/barcode/{code}")
    assert r.status_code == 200
    data = r.json()
    assert data["found"] is False
    assert "未收录" in (data.get("message") or "")


def test_barcode_sources_default_all(db):
    """未配置时默认启用全部数据源。"""
    enabled = barcode_svc._enabled_sources(db)
    assert "openfoodfacts" in enabled and "vvhan" in enabled


# ---------- 任务忙状态 ----------

def test_tasks_pending_endpoint(client):
    r = client.get("/api/tasks/pending")
    assert r.status_code == 200
    data = r.json()
    for k in ("plan", "slot", "report", "query", "share", "vision"):
        assert k in data


def test_query_concurrent_409(client, db):
    from app.models import User
    from app.services import task_state
    uid = db.query(User).filter(User.username == "tester").first().id
    task_state.begin("query", uid)
    try:
        r = client.post("/api/query", json={"question": "这周记录了几餐"})
        assert r.status_code == 409
    finally:
        task_state.end("query", uid)


# ---------- 分享卡片历史图片 ----------

def test_attach_share_history_image(client):
    # 先生成一张卡片，产生历史记录
    r = client.post("/api/share/card", json={"kind": "weekly", "tone": "轻松"})
    assert r.status_code == 200
    created_at = r.json().get("created_at")
    assert created_at

    png = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"0" * 1024).decode()
    r2 = client.post("/api/share/history/image",
                     json={"created_at": created_at, "data_url": "data:image/png;base64," + png})
    assert r2.status_code == 200
    assert r2.json()["image_url"].startswith("/uploads/share/")

    hist = client.get("/api/share/history").json()
    assert any(h.get("image_url") for h in hist)
