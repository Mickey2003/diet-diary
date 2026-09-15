"""
自然语言查库：
  问题 --(模型)--> 受限查询计划 JSON --(程序校验 + SQLAlchemy 执行)--> 结果行 --(模型)--> 中文解释

安全边界：模型永远不产出 SQL；它只能在白名单字段里选值。程序负责把计划翻译成查询并完成所有计数、比例计算。
"""
import json
from collections import Counter
from typing import Any, Dict, List, Optional, Tuple

from pydantic import ValidationError
from sqlalchemy import Integer, Select, cast, func, select
from sqlalchemy.orm import Session

from .. import config
from ..models import Meal, MealItem, QueryLog, Tag, meal_item_tags
from ..schemas import QueryOut, QueryPlan
from . import llm_client
from .tags import CATEGORIES, MEAL_TYPES, TAG_DEFS, normalize_tag_codes, tag_lookup
from .timeutil import day_range, resolve_preset, today_local

PLAN_SYSTEM_PROMPT_TEMPLATE = """你是饮食日记应用的"查询规划器"。用户会用中文提问关于自己饮食记录的问题，你需要把问题翻译成一个 JSON 查询计划。你不能直接回答问题，也不能写 SQL，只能在下列字段和取值范围内选择。

今天的日期是 {today}（星期{weekday}）。一周从周一开始。

JSON 结构（只输出 JSON，不要任何解释）：
{{
  "metric": "count_meals | count_items | count_tag | ratio_category | list_meals | avg_meals_per_day | top_items",
  "time_range": {{"preset": "today | yesterday | this_week | last_week | last_7d | last_30d | this_month | last_month | all | custom", "start": "YYYY-MM-DD 或 null", "end": "YYYY-MM-DD 或 null"}},
  "filters": {{"tags": ["标签code"], "categories": ["分类"], "meal_types": ["餐次"], "name_contains": "菜名关键字或 null", "hour_from": 0-23 或 null, "hour_to": 1-24 或 null}},
  "group_by": "none | day | meal_type | category | tag | weekday",
  "limit": 10,
  "unsupported": false,
  "unsupported_reason": null
}}

metric 含义：
- count_meals：符合条件的"餐"数量（一顿饭算一次）
- count_items：符合条件的"菜品/饮品条目"数量
- count_tag：带有 filters.tags 中任一标签的条目数量（例如"喝过几次含糖饮料"→ count_tag + tags:["sugary_drink"]）
- ratio_category：各分类条目占比（通常配 group_by: category）
- list_meals：列出符合条件的餐（返回时间、餐次、菜品）
- avg_meals_per_day：平均每天记录几餐
- top_items：出现次数最多的菜品

可用标签 code：
{tags}
可用分类：{categories}
可用餐次：{meal_types}

规则：
- 问题里提到的食物特征尽量映射到标签 code；提到"奶茶/可乐/果汁"用 sugary_drink，"炸鸡/薯条"用 fried，"外卖"用 takeout。
- "这周/本周"→this_week，"上周"→last_week，"这个月"→this_month，"最近一个月/30天"→last_30d，未提及时间默认 this_week。
- 涉及"早上/晚上/深夜"等时间段可用 hour_from/hour_to（深夜可用 22~24 或 0~5）。
- 如果问题不是关于饮食记录的统计/查询（例如要营养建议、医疗判断、或与饮食无关），设置 unsupported=true 并在 unsupported_reason 用中文说明。
"""

EXPLAIN_SYSTEM_PROMPT = f"""你是饮食日记应用的"结果解释员"。程序已经完成了查询与统计，你只需要用 2~4 句中文把结果讲清楚。

要求：
- 只根据给你的查询计划和结果数据说话，必须引用数据中的具体数字，不得编造或推算数据中没有的数字。
- 可以指出一个值得注意的现象，但不要做医疗判断、不要给具体营养数值、不要说"你应该"。
- 使用 Markdown，可对关键数字加粗。
- 结尾不必重复免责声明（界面会统一显示）。
"""


def _plan_prompt() -> str:
    t = today_local()
    return PLAN_SYSTEM_PROMPT_TEMPLATE.format(
        today=t.isoformat(), weekday="一二三四五六日"[t.weekday()],
        tags="\n".join(f"- {c}：{n}" for c, n, _g, _w, _d in TAG_DEFS),
        categories="、".join(CATEGORIES), meal_types="、".join(MEAL_TYPES),
    )


def question_to_plan(client: llm_client.LLMClient, question: str) -> Tuple[QueryPlan, Optional[str]]:
    raw = client.chat(
        [{"role": "system", "content": _plan_prompt()}, {"role": "user", "content": question}],
        task="plan", temperature=0, json_mode=True, mock_context={"question": question},
    )
    data = llm_client.parse_json(raw)
    return QueryPlan.model_validate(data), raw


def sanitize_plan(plan: QueryPlan, db: Session) -> Tuple[QueryPlan, List[str]]:
    """白名单校验：不合法的值直接丢弃并记录 warning。"""
    warnings: List[str] = []
    lookup = tag_lookup(db)
    codes, dropped = normalize_tag_codes(plan.filters.tags, lookup)
    if dropped:
        warnings.append(f"忽略未知标签：{dropped}")
    plan.filters.tags = codes
    bad_cat = [c for c in plan.filters.categories if c not in CATEGORIES]
    if bad_cat:
        warnings.append(f"忽略未知分类：{bad_cat}")
    plan.filters.categories = [c for c in plan.filters.categories if c in CATEGORIES]
    bad_mt = [m for m in plan.filters.meal_types if m not in MEAL_TYPES]
    if bad_mt:
        warnings.append(f"忽略未知餐次：{bad_mt}")
    plan.filters.meal_types = [m for m in plan.filters.meal_types if m in MEAL_TYPES]
    if plan.metric == "count_tag" and not plan.filters.tags:
        warnings.append("count_tag 需要至少一个标签，已改为统计条目数")
        plan.metric = "count_items"
    if plan.metric == "ratio_category":
        plan.group_by = "category"
    if plan.time_range.preset == "custom" and not plan.time_range.start:
        warnings.append("自定义时间缺少起止日期，已改为本周")
        plan.time_range.preset = "this_week"
    return plan, warnings


# ---------- 执行 ----------
def _base_item_query(plan: QueryPlan, user_id: Optional[int] = None) -> Select:
    """返回选出 MealItem（连接 Meal）的基础查询，已应用全部过滤条件（含用户隔离）。"""
    s, e, _ = resolve_preset(plan.time_range.preset, plan.time_range.start, plan.time_range.end)
    start_dt, end_dt = day_range(s, e)
    q = select(MealItem, Meal).join(Meal, MealItem.meal_id == Meal.id)
    if user_id is not None:
        q = q.where(Meal.user_id == user_id)
    if start_dt is not None:
        q = q.where(Meal.eaten_at >= start_dt, Meal.eaten_at < end_dt)
    if plan.filters.meal_types:
        q = q.where(Meal.meal_type.in_(plan.filters.meal_types))
    if plan.filters.categories:
        q = q.where(MealItem.category.in_(plan.filters.categories))
    if plan.filters.name_contains:
        q = q.where(MealItem.name.like(f"%{plan.filters.name_contains}%"))
    if plan.filters.tags:
        sub = select(meal_item_tags.c.item_id).where(meal_item_tags.c.tag_code.in_(plan.filters.tags))
        q = q.where(MealItem.id.in_(sub))
    if plan.filters.hour_from is not None or plan.filters.hour_to is not None:
        hf = plan.filters.hour_from if plan.filters.hour_from is not None else 0
        ht = plan.filters.hour_to if plan.filters.hour_to is not None else 24
        hour_expr = cast(func.strftime("%H", Meal.eaten_at), Integer)
        if hf <= ht:
            q = q.where(hour_expr >= hf, hour_expr < ht)
        else:  # 跨夜，如 22 ~ 5
            q = q.where((hour_expr >= hf) | (hour_expr < ht))
    return q.order_by(Meal.eaten_at)


def _group_key(plan: QueryPlan, item: MealItem, meal: Meal) -> List[str]:
    g = plan.group_by
    if g == "day":
        return [meal.eaten_at.date().isoformat()]
    if g == "weekday":
        return ["周" + "一二三四五六日"[meal.eaten_at.weekday()]]
    if g == "meal_type":
        return [meal.meal_type]
    if g == "category":
        return [item.category]
    if g == "tag":
        return [t.name_zh for t in item.tags] or ["（无标签）"]
    return ["全部"]


def execute_plan(db: Session, plan: QueryPlan, user_id: Optional[int] = None) -> Tuple[List[Dict[str, Any]], str, str]:
    """执行计划，返回 (结果行, SQL 文本, 时间范围标签)。"""
    _s, _e, range_label = resolve_preset(plan.time_range.preset, plan.time_range.start, plan.time_range.end)
    q = _base_item_query(plan, user_id)
    sql_text = str(q.compile(compile_kwargs={"literal_binds": True}))
    pairs = db.execute(q).all()  # [(MealItem, Meal), ...]

    if plan.metric in ("count_items", "count_tag"):
        if plan.group_by == "none":
            return [{"count": len(pairs)}], sql_text, range_label
        c: Counter = Counter()
        for it, m in pairs:
            for k in _group_key(plan, it, m):
                c[k] += 1
        return [{"group": k, "count": v} for k, v in sorted(c.items())], sql_text, range_label

    if plan.metric == "count_meals":
        meals = {m.id: m for _it, m in pairs}
        if plan.group_by == "none":
            return [{"count": len(meals)}], sql_text, range_label
        c = Counter()
        for m in meals.values():
            for k in _group_key(plan, m.items[0] if m.items else MealItem(category="其他"), m):
                c[k] += 1
        return [{"group": k, "count": v} for k, v in sorted(c.items())], sql_text, range_label

    if plan.metric == "avg_meals_per_day":
        meals = {m.id: m for _it, m in pairs}
        days = {m.eaten_at.date() for m in meals.values()}
        if _s is not None and _e is not None:
            span = (_e - _s).days + 1
        else:
            span = len(days) or 1
        return [{"meal_count": len(meals), "days_span": span, "days_with_records": len(days),
                 "avg_per_day": round(len(meals) / span, 2)}], sql_text, range_label

    if plan.metric == "ratio_category":
        c = Counter(it.category for it, _m in pairs)
        total = sum(c.values()) or 1
        rows = [{"category": k, "count": v, "ratio": round(v * 100 / total, 1)} for k, v in c.most_common()]
        return rows, sql_text, range_label

    if plan.metric == "top_items":
        c = Counter(it.name for it, _m in pairs)
        return [{"name": k, "count": v} for k, v in c.most_common(plan.limit)], sql_text, range_label

    if plan.metric == "list_meals":
        seen: Dict[int, Dict[str, Any]] = {}
        for it, m in pairs:
            row = seen.setdefault(m.id, {"meal_id": m.id, "eaten_at": m.eaten_at.strftime("%Y-%m-%d %H:%M"),
                                         "meal_type": m.meal_type, "items": []})
            row["items"].append(it.name)
        rows = list(seen.values())[-plan.limit:]
        for r in rows:
            r["items"] = "、".join(r["items"])
        return rows, sql_text, range_label

    return [], sql_text, range_label


def explain(client: llm_client.LLMClient, question: str, plan: QueryPlan,
            rows: List[Dict[str, Any]], range_label: str,
            memories_text: Optional[str] = None) -> str:
    system_content = EXPLAIN_SYSTEM_PROMPT
    if memories_text:
        system_content = system_content + "\n\n" + memories_text
    payload = {"question": question, "plan": plan.model_dump(), "range_label": range_label, "rows": rows[:50]}
    return client.chat(
        [{"role": "system", "content": system_content},
         {"role": "user", "content": "查询计划与结果如下（JSON）：\n" + json.dumps(payload, ensure_ascii=False)}],
        task="explain", temperature=0.3,
        mock_context={"plan": plan.model_dump(), "rows": rows, "range_label": range_label},
    )


def run_query(db: Session, question: str, user_id: Optional[int] = None) -> QueryOut:
    client = llm_client.get_client(db)
    log = QueryLog(user_id=user_id, question=question, model=client.model_name(), status="ok")
    warnings: List[str] = []
    plan: Optional[QueryPlan] = None
    rows: List[Dict[str, Any]] = []
    sql_text: Optional[str] = None
    answer = ""
    if client.cfg.is_mock:
        warnings.append("当前为离线演示模式：查询计划由关键词规则生成，解释为模板文本。")
    # 注入用户记忆（仅在 user_id 已知时）
    memories_text: Optional[str] = None
    if user_id is not None:
        try:
            from .memory import render_memories_for_prompt
            memories_text = render_memories_for_prompt(db, user_id) or None
        except Exception:  # noqa: BLE001
            pass
    try:
        plan, raw_plan = question_to_plan(client, question)
        if plan.unsupported:
            log.status = "unsupported"
            answer = (
                f"这个问题暂时无法用现有记录回答："
                f"{plan.unsupported_reason or '不属于饮食记录统计范围'}。\n\n"
                '可以试试："这周喝过几次含糖饮料""这个月各类食物占比""最近 30 天最常吃的菜"。'
            )
        else:
            plan, w = sanitize_plan(plan, db)
            warnings.extend(w)
            rows, sql_text, range_label = execute_plan(db, plan, user_id)
            answer = explain(client, question, plan, rows, range_label, memories_text=memories_text)
    except (json.JSONDecodeError, ValidationError, ValueError) as e:
        log.status = "error"
        answer = f"模型生成的查询计划无法解析（{str(e)[:120]}）。请换一种问法再试。"
    except llm_client.LLMError as e:
        log.status = "error"
        answer = f"模型调用失败：{e}"

    log.plan_json = plan.model_dump_json() if plan else None
    log.sql_text = sql_text
    log.result_json = json.dumps(rows, ensure_ascii=False)
    log.answer_md = answer
    db.add(log)
    db.commit()
    db.refresh(log)
    return QueryOut(id=log.id, question=question, status=log.status, plan=plan, sql=sql_text,
                    rows=rows, answer=answer, warnings=warnings, model=log.model, disclaimer=config.DISCLAIMER)
