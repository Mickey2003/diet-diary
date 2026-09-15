"""统计计算与受限查询计划执行。"""
from app.schemas import QueryPlan
from app.services.nl_query import execute_plan, sanitize_plan
from app.services.stats import compute_stats
from app.services.timeutil import today_local, week_bounds

from .conftest import add_meal


def _seed_week(db):
    # 本周内：3 餐，其中 2 次含糖饮料；上周 1 餐 1 次含糖饮料
    today = today_local()
    ws, _ = week_bounds(today)
    in_week = (today - ws).days  # 本周已过天数
    add_meal(db, 0, 12, "午餐", [("米饭", "主食", ["refined_staple"]), ("奶茶", "饮品", ["sugary_drink"])])
    add_meal(db, 0, 19, "晚餐", [("炸鸡", "蛋白质", ["fried", "poultry"]), ("可乐", "饮品", ["sugary_drink"])])
    add_meal(db, 0, 8, "早餐", [("燕麦粥", "主食", ["whole_grain"])])
    add_meal(db, in_week + 3, 12, "午餐", [("奶茶", "饮品", ["sugary_drink"])])  # 上周


def test_compute_stats_week(db, clean_meals):
    _seed_week(db)
    s = compute_stats(db, "week")
    assert s["meal_count"] == 3
    assert s["item_count"] == 5
    watch = {w["code"]: w for w in s["watch_tags"]}
    assert watch["sugary_drink"]["count"] == 2
    assert watch["sugary_drink"]["prev_count"] == 1
    assert watch["sugary_drink"]["delta_vs_prev"] == 1
    cat = {c["category"]: c for c in s["category_share"]}
    assert cat["饮品"]["count"] == 2
    assert cat["饮品"]["ratio"] == 40.0
    assert s["days_with_records"] == 1


def test_count_tag_plan(db, clean_meals):
    _seed_week(db)
    plan = QueryPlan(metric="count_tag", filters={"tags": ["含糖饮料"]}, time_range={"preset": "this_week"})
    plan, warnings = sanitize_plan(plan, db)
    assert plan.filters.tags == ["sugary_drink"]
    rows, sql, label = execute_plan(db, plan)
    assert rows == [{"count": 2}]
    assert label == "本周"
    assert "meal_item_tags" in sql


def test_count_meals_last_week(db, clean_meals):
    _seed_week(db)
    plan = QueryPlan(metric="count_meals", time_range={"preset": "last_week"})
    rows, _, _ = execute_plan(db, plan)
    assert rows == [{"count": 1}]


def test_ratio_category(db, clean_meals):
    _seed_week(db)
    plan, _ = sanitize_plan(QueryPlan(metric="ratio_category"), db)
    rows, _, _ = execute_plan(db, plan)
    total = sum(r["count"] for r in rows)
    assert total == 5
    assert rows[0]["ratio"] == 40.0


def test_sanitize_drops_unknown_values(db):
    plan = QueryPlan(metric="count_tag", filters={"tags": ["不存在"], "categories": ["外星"], "meal_types": ["下午茶"]})
    plan, warnings = sanitize_plan(plan, db)
    assert plan.metric == "count_items"  # 没有合法标签时退化
    assert plan.filters.categories == []
    assert plan.filters.meal_types == []
    assert len(warnings) >= 3


def test_hour_filter_wraps_midnight(db, clean_meals):
    add_meal(db, 0, 23, "加餐", [("烧烤", "蛋白质", ["late_night"])])
    add_meal(db, 0, 12, "午餐", [("米饭", "主食", [])])
    plan = QueryPlan(metric="count_meals", time_range={"preset": "today"}, filters={"hour_from": 22, "hour_to": 5})
    rows, _, _ = execute_plan(db, plan)
    assert rows == [{"count": 1}]


def test_query_api_mock(client, db, clean_meals):
    _seed_week(db)
    r = client.post("/api/query", json={"question": "这周喝过几次含糖饮料"})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["plan"]["metric"] == "count_tag"
    assert body["rows"] == [{"count": 2}]
    assert "2" in body["answer"]


def test_meal_crud_and_report(client, db, clean_meals):
    payload = {"eaten_at": f"{today_local().isoformat()}T12:30:00", "meal_type": "午餐",
               "items": [{"name": "番茄炒蛋", "category": "蛋白质", "portion": "中", "tags": ["egg", "蔬菜"], "source": "ai_edited"}]}
    r = client.post("/api/meals", json=payload)
    assert r.status_code == 201
    meal = r.json()
    assert [t["code"] for t in meal["items"][0]["tags"]] == ["egg", "vegetable"]
    r = client.get("/api/meals", params={"tag": "egg"})
    assert r.json()["total"] == 1
    r = client.put(f"/api/meals/{meal['id']}", json={"note": "好吃"})
    assert r.json()["note"] == "好吃"
    r = client.post("/api/reports", json={"period_type": "week"})
    assert r.status_code == 201
    rep = r.json()
    assert rep["facts"]["meal_count"] == 1
    assert "番茄炒蛋" in rep["summary_md"] or "1" in rep["summary_md"]
    r = client.delete(f"/api/meals/{meal['id']}")
    assert r.status_code == 204
    assert client.get("/api/meals").json()["total"] == 0


def test_eaten_at_timezone_normalized(client, clean_meals):
    """前端若误传 UTC 时间（带 Z），后端应换算为本地时间保存（Asia/Shanghai = UTC+8）。"""
    payload = {"eaten_at": "2026-09-03T04:30:00Z", "meal_type": "午餐",
               "items": [{"name": "米饭", "category": "主食", "portion": "中", "tags": [], "source": "user"}]}
    r = client.post("/api/meals", json=payload)
    assert r.status_code == 201
    assert r.json()["eaten_at"].startswith("2026-09-03T12:30:00")
    # 不带时区的本地时间原样保存
    payload["eaten_at"] = "2026-09-03T19:05:00"
    r = client.post("/api/meals", json=payload)
    assert r.json()["eaten_at"].startswith("2026-09-03T19:05:00")


def test_settings_mask(client):
    r = client.put("/api/settings", json={"provider": "dashscope", "api_key": "sk-1234567890abcdef"})
    body = r.json()
    assert body["has_api_key"] is True
    assert body["api_key_masked"].startswith("sk-1") and "1234567890" not in body["api_key_masked"]
    assert body["base_url"].startswith("https://dashscope")
    # 还原为 mock，避免影响其他测试
    client.put("/api/settings", json={"provider": "mock", "api_key": "__clear__"})
