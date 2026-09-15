"""
离线 mock 模型：不联网，按任务类型返回结构合理的假回复。
用途：没有 API Key 时演示、单元测试、前端联调。
注意：mock 的“识别结果”与图片内容无关，界面上会明确提示。
"""
import json
import random
from typing import Any, Dict, List

_MOCK_MEALS = [
    {
        "items": [
            {"name": "番茄炒蛋", "category": "蛋白质", "portion": "中", "tags": ["egg", "vegetable", "homemade"], "confidence": 0.82},
            {"name": "白米饭", "category": "主食", "portion": "中", "tags": ["refined_staple"], "confidence": 0.9},
            {"name": "清炒西兰花", "category": "蔬菜", "portion": "中", "tags": ["vegetable", "light"], "confidence": 0.78},
        ],
        "meal_type_guess": "午餐",
        "overall_note": "一份常见的家常套餐，荤素搭配较均衡。",
        "uncertainty": "米饭份量根据碗的大小估计，可能偏差较大。",
    },
    {
        "items": [
            {"name": "珍珠奶茶", "category": "饮品", "portion": "多", "tags": ["sugary_drink"], "confidence": 0.9},
            {"name": "炸鸡块", "category": "蛋白质", "portion": "中", "tags": ["fried", "poultry", "takeout"], "confidence": 0.85},
        ],
        "meal_type_guess": "加餐",
        "overall_note": "含糖饮料 + 油炸食品组合。",
        "uncertainty": "无法判断奶茶是否为无糖，默认按含糖处理。",
    },
    {
        "items": [
            {"name": "燕麦粥", "category": "主食", "portion": "中", "tags": ["whole_grain", "soup"], "confidence": 0.8},
            {"name": "水煮蛋", "category": "蛋白质", "portion": "少", "tags": ["egg", "high_protein"], "confidence": 0.92},
            {"name": "香蕉", "category": "水果", "portion": "少", "tags": ["fruit"], "confidence": 0.88},
        ],
        "meal_type_guess": "早餐",
        "overall_note": "轻食早餐，含全谷物与水果。",
        "uncertainty": "",
    },
]


def _mock_vision() -> str:
    return "```json\n" + json.dumps(random.choice(_MOCK_MEALS), ensure_ascii=False) + "\n```"


def _mock_plan(question: str) -> str:
    q = question
    plan: Dict[str, Any] = {"metric": "count_meals", "time_range": {"preset": "this_week"},
                            "filters": {}, "group_by": "none", "limit": 10}
    # 不属于“查询历史记录”的问题：营养 / 医疗 / 建议类，直接拒答
    for w in ("减肥", "应该吃", "建议", "推荐", "健康吗", "卡路里", "热量", "营养", "能不能吃", "会不会", "怎么办"):
        if w in q:
            plan["unsupported"] = True
            plan["unsupported_reason"] = "这类问题需要营养或医疗判断，超出了饮食记录统计的范围"
            return json.dumps(plan, ensure_ascii=False)
    # 时间
    if "上周" in q:
        plan["time_range"] = {"preset": "last_week"}
    elif "本月" in q or "这个月" in q:
        plan["time_range"] = {"preset": "this_month"}
    elif "上个月" in q or "上月" in q:
        plan["time_range"] = {"preset": "last_month"}
    elif "30天" in q or "一个月" in q:
        plan["time_range"] = {"preset": "last_30d"}
    elif "今天" in q:
        plan["time_range"] = {"preset": "today"}
    elif "昨天" in q:
        plan["time_range"] = {"preset": "yesterday"}
    elif "所有" in q or "一共" in q or "总共" in q:
        plan["time_range"] = {"preset": "all"}
    # 指标
    tag_words = {"含糖饮料": "sugary_drink", "奶茶": "sugary_drink", "可乐": "sugary_drink", "油炸": "fried",
                 "炸": "fried", "外卖": "takeout", "酒": "alcohol", "夜宵": "late_night", "甜": "sweet",
                 "水果": "fruit", "蔬菜": "vegetable", "青菜": "leafy_veg", "奶": "dairy", "豆": "soy"}
    for w, code in tag_words.items():
        if w in q:
            plan["metric"] = "count_tag"
            plan["filters"] = {"tags": [code]}
            break
    if "占比" in q or "结构" in q or "比例" in q:
        plan["metric"] = "ratio_category"
        plan["filters"] = {}
        plan["group_by"] = "category"
    elif "最常" in q or "最多" in q or "常吃" in q:
        plan["metric"] = "top_items"
        plan["filters"] = {}
    elif "平均" in q:
        plan["metric"] = "avg_meals_per_day"
    elif "列出" in q or "有哪些" in q or "吃了什么" in q:
        plan["metric"] = "list_meals"
    if "早餐" in q:
        plan.setdefault("filters", {})["meal_types"] = ["早餐"]
    if "每天" in q and plan["metric"] in ("count_meals", "count_tag"):
        plan["group_by"] = "day"
    return json.dumps(plan, ensure_ascii=False)


def _mock_explain(ctx: Dict[str, Any]) -> str:
    rows: List[Dict[str, Any]] = ctx.get("rows") or []
    plan = ctx.get("plan") or {}
    metric = plan.get("metric", "")
    label = ctx.get("range_label", "所选时间段")
    if not rows:
        return f"在{label}内没有找到符合条件的记录。（离线演示模式生成的说明）"
    if metric in ("count_meals", "count_items", "count_tag") and len(rows) == 1 and "count" in rows[0]:
        return f"{label}内符合条件的记录共 **{rows[0]['count']}** 次。（离线演示模式生成的说明）"
    if metric == "ratio_category":
        parts = [f"{r.get('category')} {r.get('count')} 项（{r.get('ratio')}%）" for r in rows[:5]]
        return f"{label}内各类食物构成：" + "，".join(parts) + "。（离线演示模式生成的说明）"
    if metric == "top_items":
        parts = [f"{r.get('name')} {r.get('count')} 次" for r in rows[:5]]
        return f"{label}内最常出现的菜品：" + "，".join(parts) + "。（离线演示模式生成的说明）"
    if metric == "avg_meals_per_day":
        return f"{label}内平均每天记录 **{rows[0].get('avg_per_day')}** 餐。（离线演示模式生成的说明）"
    return f"共查到 {len(rows)} 条结果，详见下方表格。（离线演示模式生成的说明）"


def _mock_report(ctx: Dict[str, Any]) -> str:
    f: Dict[str, Any] = ctx.get("facts") or {}
    p = f.get("period", {})
    lines = [f"## {p.get('label', '本期')}饮食观察（离线演示模式生成）", ""]
    lines.append(f"- 本期共记录 **{f.get('meal_count', 0)}** 餐，覆盖 {f.get('days_with_records', 0)}/{f.get('days_total', 0)} 天。")
    cs = f.get("category_share") or []
    if cs:
        top = cs[0]
        lines.append(f"- 食物构成中占比最高的是 **{top['category']}**（{top['ratio']}%）。")
    wt = f.get("watch_tags") or []
    for w in wt[:3]:
        delta = w.get("delta_vs_prev")
        trend = "" if delta is None else (f"，比上期多 {delta} 次" if delta > 0 else (f"，比上期少 {abs(delta)} 次" if delta < 0 else "，与上期持平"))
        lines.append(f"- {w['name']} 出现 **{w['count']}** 次{trend}。")
    ti = f.get("top_items") or []
    if ti:
        lines.append("- 最常出现的菜品：" + "、".join(f"{t['name']}（{t['count']} 次）" for t in ti[:3]) + "。")
    lines.append("")
    lines.append("**轻量建议**：可以试着把其中一两次含糖饮料换成无糖饮品，并保持蔬菜出现的频率。")
    return "\n".join(lines)


# 其他模块可注册自己的 mock 处理器：mock_llm.register("meal_plan", fn)，fn(messages, ctx) -> str
MOCK_HANDLERS: Dict[str, Any] = {}


def register(task: str, handler) -> None:  # noqa: ANN001
    MOCK_HANDLERS[task] = handler


def mock_reply(task: str, messages: List[Dict[str, Any]], ctx: Dict[str, Any]) -> str:
    if task in MOCK_HANDLERS:
        return MOCK_HANDLERS[task](messages, ctx)
    if task == "vision":
        return _mock_vision()
    if task == "plan":
        return _mock_plan(ctx.get("question", ""))
    if task == "explain":
        return _mock_explain(ctx)
    if task == "report":
        return _mock_report(ctx)
    return "成功"
