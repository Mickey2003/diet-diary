"""
统计服务：全部由程序（SQL / Python）计算，不经过模型。
输出既给前端画图，也作为周报 / 月报的“事实基础”。
"""
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import Meal, MealItem, Tag, meal_item_tags
from .tags import CATEGORIES, MEAL_TYPES
from .timeutil import day_range, month_bounds, today_local, week_bounds


def _period(range_type: str, anchor: Optional[str]):
    d = date.fromisoformat(anchor) if anchor else today_local()
    if range_type == "month":
        s, e = month_bounds(d)
        prev_s, prev_e = month_bounds(s - timedelta(days=1))
        label = f"{s.year} 年 {s.month} 月"
    else:
        s, e = week_bounds(d)
        prev_s, prev_e = week_bounds(s - timedelta(days=7))
        label = f"{s.isoformat()} ~ {e.isoformat()} 这一周"
    return s, e, prev_s, prev_e, label


def _load_meals(db: Session, s: date, e: date, user_id: Optional[int] = None) -> List[Meal]:
    start_dt, end_dt = day_range(s, e)
    stmt = select(Meal).where(Meal.eaten_at >= start_dt, Meal.eaten_at < end_dt)
    if user_id is not None:
        stmt = stmt.where(Meal.user_id == user_id)
    return list(db.scalars(stmt.order_by(Meal.eaten_at)).all())


def _aggregate(meals: List[Meal], s: date, e: date, tags_by_code: Dict[str, Tag]) -> Dict[str, Any]:
    days_total = (e - s).days + 1
    all_days = [s + timedelta(days=i) for i in range(days_total)]

    meals_per_day: Counter = Counter()
    meal_type_counts: Counter = Counter()
    category_counts: Counter = Counter()
    tag_counts: Counter = Counter()
    watch_per_day: Dict[str, Counter] = defaultdict(Counter)  # tag_code -> {day: n}
    item_names: Counter = Counter()
    ai_items = user_items = edited_items = 0
    late_night = 0
    kcal_per_day: Counter = Counter()        # 估算热量（千卡）按天
    kcal_by_meal_type: Counter = Counter()
    kcal_total = 0

    for m in meals:
        dkey = m.eaten_at.date().isoformat()
        meals_per_day[dkey] += 1
        meal_type_counts[m.meal_type] += 1
        if m.eaten_at.hour >= 22 or m.eaten_at.hour < 5:
            late_night += 1
        for it in m.items:
            category_counts[it.category] += 1
            item_names[it.name] += 1
            if it.kcal is not None:
                kcal_per_day[dkey] += it.kcal
                kcal_by_meal_type[m.meal_type] += it.kcal
                kcal_total += it.kcal
            if it.source == "ai":
                ai_items += 1
            elif it.source == "ai_edited":
                edited_items += 1
            else:
                user_items += 1
            for t in it.tags:
                tag_counts[t.code] += 1
                if t.is_watch:
                    watch_per_day[t.code][dkey] += 1

    total_items = sum(category_counts.values())
    category_share = [
        {"category": c, "count": category_counts.get(c, 0),
         "ratio": round(category_counts.get(c, 0) * 100 / total_items, 1) if total_items else 0.0}
        for c in CATEGORIES
    ]
    category_share.sort(key=lambda x: -x["count"])

    watch_tags = []
    for code, t in tags_by_code.items():
        if t.is_watch:
            watch_tags.append({"code": code, "name": t.name_zh, "count": tag_counts.get(code, 0)})
    watch_tags.sort(key=lambda x: -x["count"])

    structure_tags = [
        {"code": code, "name": t.name_zh, "count": tag_counts.get(code, 0)}
        for code, t in tags_by_code.items() if not t.is_watch and tag_counts.get(code, 0) > 0
    ]
    structure_tags.sort(key=lambda x: -x["count"])

    daily = []
    for d in all_days:
        k = d.isoformat()
        row: Dict[str, Any] = {"date": k, "weekday": "一二三四五六日"[d.weekday()], "meals": meals_per_day.get(k, 0),
                               "kcal": kcal_per_day.get(k, 0)}
        for wt in watch_tags:
            row[wt["code"]] = watch_per_day[wt["code"]].get(k, 0)
        daily.append(row)

    return {
        "days_total": days_total,
        "days_with_records": len(meals_per_day),
        "missing_days": [d.isoformat() for d in all_days if d.isoformat() not in meals_per_day and d <= today_local()],
        "meal_count": len(meals),
        "item_count": total_items,
        "avg_meals_per_day": round(len(meals) / days_total, 2) if days_total else 0,
        "meal_type_counts": [{"meal_type": mt, "count": meal_type_counts.get(mt, 0)} for mt in MEAL_TYPES],
        "category_share": category_share,
        "watch_tags": watch_tags,
        "structure_tags": structure_tags,
        "top_items": [{"name": n, "count": c} for n, c in item_names.most_common(8)],
        "daily": daily,
        "late_night_meals": late_night,
        "item_sources": {"ai": ai_items, "ai_edited": edited_items, "user": user_items},
        # 热量均为粗略估算
        "kcal_total": kcal_total,
        "kcal_avg_per_day": round(kcal_total / len(meals_per_day)) if meals_per_day else 0,
        "kcal_by_meal_type": [{"meal_type": mt, "kcal": kcal_by_meal_type.get(mt, 0)} for mt in MEAL_TYPES],
        "kcal_note": "热量为按菜品与份量的粗略估算，仅供观察趋势，不作为营养或医疗依据",
    }


def compute_stats(db: Session, range_type: str = "week", anchor: Optional[str] = None,
                  user_id: Optional[int] = None) -> Dict[str, Any]:
    s, e, prev_s, prev_e, label = _period(range_type, anchor)
    tags_by_code = {t.code: t for t in db.query(Tag).all()}
    cur = _aggregate(_load_meals(db, s, e, user_id), s, e, tags_by_code)
    prev = _aggregate(_load_meals(db, prev_s, prev_e, user_id), prev_s, prev_e, tags_by_code)

    # 环比
    prev_cat = {c["category"]: c for c in prev["category_share"]}
    for c in cur["category_share"]:
        p = prev_cat.get(c["category"], {"ratio": 0.0, "count": 0})
        c["prev_ratio"] = p["ratio"]
        c["delta_ratio"] = round(c["ratio"] - p["ratio"], 1)
    prev_watch = {w["code"]: w["count"] for w in prev["watch_tags"]}
    for w in cur["watch_tags"]:
        w["prev_count"] = prev_watch.get(w["code"], 0)
        w["delta_vs_prev"] = w["count"] - w["prev_count"]

    return {
        "period": {"type": range_type, "start": s.isoformat(), "end": e.isoformat(), "label": label,
                   "prev_start": prev_s.isoformat(), "prev_end": prev_e.isoformat()},
        **cur,
        "prev": {"meal_count": prev["meal_count"], "item_count": prev["item_count"],
                 "days_with_records": prev["days_with_records"], "avg_meals_per_day": prev["avg_meals_per_day"],
                 "kcal_total": prev["kcal_total"], "kcal_avg_per_day": prev["kcal_avg_per_day"]},
    }
