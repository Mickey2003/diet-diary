"""
v0.8.2 测试：替换建议快速应用（确定性）+ 餐单历史版本（列表/恢复）。
"""
from app.services import meal_plan as mp


# ---------- 解析 ----------

def test_parse_swap_pairs_basic():
    pairs = mp._parse_swap_pairs("白米饭可换为糙米或杂粮饭")
    assert pairs == [("白米饭", "糙米")]


def test_parse_swap_pairs_multi_and_arrow():
    pairs = mp._parse_swap_pairs("将可乐换成无糖茶；肉类→豆腐")
    assert ("可乐", "无糖茶") in pairs
    assert ("肉类", "豆腐") in pairs


def test_parse_swap_pairs_strips_filler():
    pairs = mp._parse_swap_pairs("肉类可换为同等分量的豆腐")
    assert pairs == [("肉类", "豆腐")]


# ---------- 应用到餐单结构 ----------

def _plan_with(names):
    dishes = [{"name": n, "category": c, "portion": "中"} for n, c in names]
    return {"days": [{"date": "2026-09-11", "meals": [{"meal_type": "午餐", "dishes": dishes}]}]}


def test_apply_swaps_specific_substring():
    plan = _plan_with([("米饭", "主食"), ("糙米饭", "主食"), ("番茄炒蛋", "蛋白质")])
    changed = mp._apply_swaps_to_dict(plan, [("米饭", "杂粮饭")])
    names = [d["name"] for d in plan["days"][0]["meals"][0]["dishes"]]
    assert changed == 2
    assert "杂粮饭" in names
    assert "番茄炒蛋" in names


def test_apply_swaps_generic_category():
    plan = _plan_with([("红烧肉", "蛋白质"), ("清蒸鱼", "蛋白质"), ("米饭", "主食")])
    changed = mp._apply_swaps_to_dict(plan, [("肉类", "豆腐")])
    dishes = plan["days"][0]["meals"][0]["dishes"]
    # 两条蛋白质菜替换为豆腐，主食不动
    assert changed == 2
    assert dishes[0]["name"] == "豆腐"
    assert dishes[2]["name"] == "米饭"


def test_apply_swaps_specific_name_not_overreplace():
    """具体菜名（非通用类别词）不应触发按类别整体替换。"""
    plan = _plan_with([("米饭", "主食"), ("小米粥", "主食"), ("全麦面包", "主食")])
    changed = mp._apply_swaps_to_dict(plan, [("白米饭", "糙米")])
    # "白米饭" 只与"米饭"构成反向包含（菜名 in 建议词），仅替换米饭
    names = [d["name"] for d in plan["days"][0]["meals"][0]["dishes"]]
    assert changed == 1
    assert names[0] == "糙米"
    assert names[1] == "小米粥"


# ---------- 端到端：应用替换 + 历史版本 ----------

def test_apply_swap_and_versions(client, db):
    # 生成一份 mock 餐单
    r = client.post("/api/health/plans", json={"days": 3})
    assert r.status_code == 201, r.text
    plan = r.json()
    pid = plan["id"]

    # 应用替换
    r2 = client.post(f"/api/health/plans/{pid}/apply-swap",
                     json={"swap_instruction": "米饭换为杂粮饭"})
    assert r2.status_code == 200, r2.text
    assert any("已应用替换" in w for w in r2.json()["warnings"])

    # 版本列表应至少有一条
    r3 = client.get(f"/api/health/plans/{pid}/versions")
    assert r3.status_code == 200, r3.text
    versions = r3.json()
    assert len(versions) >= 1
    vid = versions[0]["id"]

    # 恢复到该版本
    r4 = client.post(f"/api/health/plans/{pid}/versions/{vid}/restore")
    assert r4.status_code == 200, r4.text

    # 恢复本身也会生成一条备份
    r5 = client.get(f"/api/health/plans/{pid}/versions")
    assert len(r5.json()) >= 2


def test_restore_missing_version_404(client):
    r = client.post("/api/health/plans", json={"days": 3})
    pid = r.json()["id"]
    r2 = client.post(f"/api/health/plans/{pid}/versions/999999/restore")
    assert r2.status_code == 404
