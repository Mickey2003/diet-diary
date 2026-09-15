"""v0.5：用量记录带 user_id（中间件 contextvar）、缩略图、recognize-path、未读数、缓存头、gzip。"""
import io

from PIL import Image


def _jpeg(w=900, h=700) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (w, h), (200, 150, 100)).save(buf, "JPEG")
    return buf.getvalue()


def test_vision_usage_recorded_for_user(client, clean_meals):
    before = client.get("/api/usage/summary").json()["mine_month"]["calls"]
    r = client.post("/api/meals/recognize", files={"file": ("a.jpg", _jpeg(), "image/jpeg")})
    assert r.status_code == 200
    s = client.get("/api/usage/summary").json()
    assert s["mine_month"]["calls"] == before + 1
    assert s["recent"][0]["task"] == "vision"
    # 按用户分布里应归到 tester，而不是“系统”
    assert any(u["username"] == "tester" for u in s["by_user"])


def test_thumbnail_and_recognize_path(client, clean_meals):
    r = client.post("/api/meals/upload-only", files={"file": ("a.jpg", _jpeg(), "image/jpeg")})
    path = r.json()["image_path"]
    t = client.get(f"/uploads/thumb/{path}")
    assert t.status_code == 200
    img = Image.open(io.BytesIO(t.content))
    assert max(img.size) <= 320
    r = client.post("/api/meals/recognize-path", json={"image_path": path})
    assert r.status_code == 200 and r.json()["image_path"] == path
    assert client.post("/api/meals/recognize-path", json={"image_path": "../x.jpg"}).status_code == 400
    assert client.post("/api/meals/recognize-path", json={"image_path": "nope.jpg"}).status_code == 404
    # 保存后 MealOut 带 thumb_url
    payload = {"eaten_at": "2026-09-06T12:00:00", "meal_type": "午餐", "image_path": path,
               "items": [{"name": "米饭", "category": "主食", "portion": "中", "tags": [], "source": "user"}]}
    m = client.post("/api/meals", json=payload).json()
    assert m["thumb_url"] == f"/uploads/thumb/{path}"


def test_unread_and_read_all(client):
    client.post("/api/notify/test", json={"channel": "inbox"})
    u = client.get("/api/notify/unread").json()
    assert u["unread"] >= 1 and u["latest_id"] > 0
    r = client.post("/api/notify/inbox/read-all").json()
    assert r["marked"] >= 1
    assert client.get("/api/notify/unread").json()["unread"] == 0


def test_cache_headers_and_gzip(client):
    r = client.get("/api/health")
    assert "cache-control" not in {k.lower() for k in r.headers.keys()} or "no" in r.headers.get("cache-control", "no")
    # 大 JSON 响应会被 gzip
    r = client.get("/api/tags", headers={"Accept-Encoding": "gzip"})
    assert r.headers.get("content-encoding") == "gzip"
    # SPA 首页与静态资源缓存策略
    r = client.get("/", headers={"Accept-Encoding": "identity"})
    if r.status_code == 200 and "text/html" in r.headers.get("content-type", ""):
        assert r.headers.get("cache-control") == "no-cache"
