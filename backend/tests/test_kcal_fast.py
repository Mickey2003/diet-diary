"""v0.6：热量估算（模型 / 菜品表 / 用户 / 条形码）、统计中的热量汇总、快慢模型分流与 max_tokens。"""
from app.services import llm_client
from app.services.kcal import estimate_kcal, kcal_from_nutriments
from app.services.llm_client import LLMConfig, LLMClient


def test_estimate_kcal_table_and_portion():
    assert estimate_kcal("白米饭", "主食", "中") == (230, "table")
    assert estimate_kcal("一大碗白米饭", "主食", "多") == (322, "table")
    assert estimate_kcal("珍珠奶茶", "饮品", "少") == (315, "table")
    assert estimate_kcal("某种不认识的菜", "蔬菜", "中") == (60, "category")
    assert kcal_from_nutriments(42, "330ml") == 139
    assert kcal_from_nutriments(500, None) == 500
    assert kcal_from_nutriments(None, "100g") is None


def test_meal_items_get_kcal_and_total(client, clean_meals):
    payload = {"eaten_at": "2026-09-06T12:00:00", "meal_type": "午餐", "items": [
        {"name": "白米饭", "category": "主食", "portion": "中", "tags": [], "source": "user"},
        {"name": "番茄炒蛋", "category": "蛋白质", "portion": "中", "tags": [], "source": "ai", "kcal": 180, "kcal_source": "ai"},
        {"name": "神秘小菜", "category": "蔬菜", "portion": "多", "tags": [], "source": "user", "kcal": 99},
    ]}
    m = client.post("/api/meals", json=payload).json()
    by = {i["name"]: i for i in m["items"]}
    assert by["白米饭"]["kcal"] == 230 and by["白米饭"]["kcal_source"] == "table"
    assert by["番茄炒蛋"]["kcal"] == 180 and by["番茄炒蛋"]["kcal_source"] == "ai"
    assert by["神秘小菜"]["kcal"] == 99 and by["神秘小菜"]["kcal_source"] == "user"
    assert m["kcal_total"] == 230 + 180 + 99
    # 统计
    s = client.get("/api/stats", params={"range": "week", "anchor": "2026-09-06"}).json()
    assert s["kcal_total"] == 509 and s["kcal_avg_per_day"] == 509
    assert any(r["date"] == "2026-09-06" and r["kcal"] == 509 for r in s["daily"])
    assert {x["meal_type"]: x["kcal"] for x in s["kcal_by_meal_type"]}["午餐"] == 509
    assert "估算" in s["kcal_note"]


def test_vision_mock_fills_kcal(client):
    import io
    from PIL import Image
    buf = io.BytesIO(); Image.new("RGB", (400, 300), (120, 200, 90)).save(buf, "JPEG")
    r = client.post("/api/meals/recognize", files={"file": ("a.jpg", buf.getvalue(), "image/jpeg")}).json()
    assert r["result"]["items"], r
    for it in r["result"]["items"]:
        assert it["kcal"] is not None and it["kcal_source"] in ("ai", "table", "category")


def test_barcode_suggested_item_has_kcal(client):
    b = client.get("/api/barcode/6928804011142").json()  # 内置可口可乐：42 kcal/100ml × 330ml
    # 若缓存行是旧版本写入（不含净含量），则按每 100ml 计（42）；新写入的缓存带净含量则为 139
    assert b["found"] and b["suggested_item"]["kcal"] in (42, 139) and b["suggested_item"]["kcal_source"] == "barcode"
    assert kcal_from_nutriments(42, "330ml") == 139


def test_fast_model_routing_and_settings(client):
    cfg = LLMConfig(provider="dashscope", base_url="", api_key="k", text_model="qwen-plus", vision_model="qwen-vl-plus",
                    source="db", fast_model="qwen-turbo")
    c = LLMClient(cfg)
    assert c.pick_model("plan") == "qwen-turbo"
    assert c.pick_model("explain") == "qwen-turbo"
    assert c.pick_model("report") == "qwen-plus"
    assert c.pick_model("meal_plan") == "qwen-plus"
    assert c.pick_model("meal_plan_slot") == "qwen-turbo"
    assert c.pick_model("vision", vision=True) == "qwen-vl-plus"
    assert llm_client.TASK_MAX_TOKENS["plan"] < llm_client.TASK_MAX_TOKENS["report"] < llm_client.TASK_MAX_TOKENS["meal_plan"]
    # 未配置 fast_model 时回退 text_model
    cfg2 = LLMConfig(provider="openai", base_url="", api_key="k", text_model="gpt-4o", vision_model="gpt-4o", source="db", fast_model="")
    assert LLMClient(cfg2).pick_model("plan") == "gpt-4o"
    # 设置接口
    r = client.put("/api/settings", json={"provider": "dashscope", "fast_model": "qwen-turbo"}).json()
    assert r["fast_model"] == "qwen-turbo" and r["presets"]["dashscope"]["fast_model"] == "qwen-turbo"
    client.put("/api/settings", json={"provider": "mock", "fast_model": "", "api_key": "__clear__"})
