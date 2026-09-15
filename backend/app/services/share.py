"""
分享文案服务（Feature 3）。
根据饮食统计调用 LLM 生成社交分享卡片文案。
使用 mock 模式时返回基于 facts 的模板文案（不联网）。
"""
import json
import random
from datetime import date, datetime
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from .. import config
from ..models import Meal, MealItem
from ..services import llm_client
from ..services.mock_llm import register
from ..services.stats import compute_stats

# 合法的 tone 值
VALID_TONES = ("轻松", "励志", "文艺", "极简")

# 合法的 kind 值
VALID_KINDS = ("weekly", "monthly", "today", "meal")

# 卡片主题（按餐次/时段分配）
_THEMES = ("warm", "fresh", "night")


# ---------- mock 处理器（在此模块注册） ----------

def _mock_share_copy(messages: List[Dict[str, Any]], ctx: Dict[str, Any]) -> str:
    """
    mock 模式下的分享文案生成器。
    根据 facts 和 tone 返回不同模板的 JSON 字符串。
    """
    facts = ctx.get("facts") or {}
    tone = ctx.get("tone") or "轻松"
    kind = ctx.get("kind") or "weekly"
    meal_count = facts.get("meal_count", 0)
    days_with = facts.get("days_with_records", 0)

    templates = {
        "轻松": {
            "headline": f"本期吃了{meal_count}餐",
            "body": f"坚持记录{days_with}天，饮食生活有模有样，加油保持！",
            "hashtags": ["#饮食日记", "#健康生活", "#打卡"],
            "emoji": "🍱",
        },
        "励志": {
            "headline": "坚持就是胜利",
            "body": f"记录了{days_with}天饮食，{meal_count}餐数据在手，健康由我掌控！",
            "hashtags": ["#健康管理", "#饮食记录", "#自律"],
            "emoji": "💪",
        },
        "文艺": {
            "headline": "食事如诗",
            "body": f"那{days_with}天里的{meal_count}顿饭，是生活最温柔的注脚。",
            "hashtags": ["#饮食美学", "#生活记录", "#食光"],
            "emoji": "✨",
        },
        "极简": {
            "headline": f"{meal_count}餐",
            "body": f"{days_with}天",
            "hashtags": ["#饮食"],
            "emoji": "○",
        },
    }
    chosen = templates.get(tone, templates["轻松"])
    return json.dumps(chosen, ensure_ascii=False)


# 注册 mock 处理器
register("share_copy", _mock_share_copy)


# ---------- facts 计算 ----------

def _compute_today_facts(db: Session, user_id: int,
                         anchor: Optional[str] = None) -> Dict[str, Any]:
    """计算今天（或指定日期）的饮食 facts。"""
    today = date.fromisoformat(anchor) if anchor else date.today()
    from datetime import timedelta
    from sqlalchemy import select as _select
    from ..models import Meal as _Meal
    start = datetime.combine(today, datetime.min.time())
    end = start + timedelta(days=1)
    meals = db.scalars(
        _select(_Meal).where(
            _Meal.user_id == user_id,
            _Meal.eaten_at >= start,
            _Meal.eaten_at < end,
        )
    ).all()
    meal_count = len(meals)
    item_count = sum(len(m.items) for m in meals)
    return {
        "kind": "today",
        "date": today.isoformat(),
        "meal_count": meal_count,
        "item_count": item_count,
        "days_with_records": 1 if meal_count > 0 else 0,
        "days_total": 1,
        "period": {"label": f"{today.isoformat()} 今天"},
    }


def _compute_meal_facts(db: Session, user_id: int, meal_id: int) -> Dict[str, Any]:
    """获取单餐的 facts。"""
    meal = db.get(Meal, meal_id)
    if meal is None or meal.user_id != user_id:
        raise ValueError(f"餐食 {meal_id} 不存在或无权访问")
    items = [{"name": it.name, "category": it.category, "portion": it.portion} for it in meal.items]
    return {
        "kind": "meal",
        "meal_id": meal_id,
        "meal_type": meal.meal_type,
        "eaten_at": meal.eaten_at.isoformat(),
        "item_count": len(items),
        "items": items,
        "days_with_records": 1,
        "meal_count": 1,
        "period": {"label": f"{meal.meal_type} · {meal.eaten_at.strftime('%m月%d日')}"},
    }


def compute_facts(db: Session, user_id: int, kind: str,
                  anchor: Optional[str] = None,
                  meal_id: Optional[int] = None) -> Dict[str, Any]:
    """根据 kind 计算 facts 数据。"""
    if kind == "weekly":
        stats = compute_stats(db, "week", anchor, user_id)
        return {**stats, "kind": "weekly"}
    elif kind == "monthly":
        stats = compute_stats(db, "month", anchor, user_id)
        return {**stats, "kind": "monthly"}
    elif kind == "today":
        return _compute_today_facts(db, user_id, anchor)
    elif kind == "meal":
        if meal_id is None:
            raise ValueError("meal 类型必须提供 meal_id")
        return _compute_meal_facts(db, user_id, meal_id)
    else:
        raise ValueError(f"无效的 kind：{kind!r}")


# ---------- 卡片文案生成 ----------

def _build_card_layout(facts: Dict[str, Any], tone: str) -> Dict[str, Any]:
    """根据 facts 和 tone 构建前端渲染用的 card 布局规格。"""
    kind = facts.get("kind", "weekly")
    period_info = facts.get("period") or {}
    label = period_info.get("label", "")
    meal_count = facts.get("meal_count", 0)
    days_with = facts.get("days_with_records", 0)
    days_total = facts.get("days_total", 1)

    # 主题
    if tone == "文艺":
        theme = "warm"
    elif tone == "励志":
        theme = "night"
    elif tone == "极简":
        theme = "fresh"
    else:
        theme = "warm"

    # 统计卡格（最多 4 项）
    stats = [
        {"label": "记录餐次", "value": str(meal_count)},
        {"label": "打卡天数", "value": f"{days_with}/{days_total}"},
    ]
    watch_tags = facts.get("watch_tags") or []
    if watch_tags:
        top_watch = watch_tags[0]
        stats.append({"label": top_watch.get("name", "关注项"), "value": str(top_watch.get("count", 0)) + "次"})
    top_items = facts.get("top_items") or []
    if top_items:
        stats.append({"label": "最常出现", "value": top_items[0].get("name", "")})

    highlight = ""
    if watch_tags and watch_tags[0].get("count", 0) > 0:
        highlight = f"本期{watch_tags[0]['name']}出现{watch_tags[0]['count']}次"
    elif meal_count > 0:
        highlight = f"坚持记录，已记{meal_count}餐"

    return {
        "theme": theme,
        "title": label or "饮食观察",
        "subtitle": f"今天吃得怎么样 AI 饮食日记",
        "stats": stats[:4],
        "highlight": highlight,
        "footer": "今天吃得怎么样 · AI 饮食观察日记",
        "date_range": label,
    }


def _validate_llm_copy(raw: str) -> Dict[str, Any]:
    """
    解析并校验 LLM 返回的分享文案 JSON。
    不符合要求时抛出 ValueError。
    """
    try:
        data = llm_client.parse_json(raw)
    except Exception as e:
        raise ValueError(f"JSON 解析失败：{e}") from e
    if not isinstance(data, dict):
        raise ValueError("返回值不是 JSON 对象")
    headline = str(data.get("headline") or "")
    body = str(data.get("body") or "")
    hashtags = data.get("hashtags") or []
    emoji = str(data.get("emoji") or "🍱")
    # 强制截断
    if len(headline) > 16:
        headline = headline[:16]
    if len(body) > 80:
        body = body[:80]
    if not isinstance(hashtags, list):
        hashtags = []
    hashtags = [str(h) for h in hashtags[:5]]
    return {"headline": headline, "body": body, "hashtags": hashtags, "emoji": emoji}


def _fallback_copy(facts: Dict[str, Any], tone: str) -> Dict[str, Any]:
    """模型失败时的兜底文案（基于模板）。"""
    meal_count = facts.get("meal_count", 0)
    days_with = facts.get("days_with_records", 0)
    templates = {
        "轻松": ("记录美食每一天", f"已记录{meal_count}餐，打卡{days_with}天，继续加油！",
                 ["#饮食日记", "#健康生活"], "🍱"),
        "励志": ("健康由我掌控", f"坚持{days_with}天记录，{meal_count}餐数据不说谎！",
                 ["#健康管理", "#自律"], "💪"),
        "文艺": ("食事如诗", f"那{days_with}天的{meal_count}顿饭，是生活温柔的注脚。",
                 ["#饮食美学", "#食光"], "✨"),
        "极简": (f"{meal_count}餐", f"{days_with}天", ["#饮食"], "○"),
    }
    h, b, ht, em = templates.get(tone, templates["轻松"])
    return {"headline": h, "body": b, "hashtags": ht, "emoji": em}


def generate_share_card(
    db: Session,
    user_id: int,
    kind: str,
    anchor: Optional[str] = None,
    meal_id: Optional[int] = None,
    tone: str = "轻松",
) -> Dict[str, Any]:
    """
    生成分享卡片（完整流程）：
    1. 计算 facts
    2. 调用 LLM（task=share_copy）
    3. 验证/强制截断，失败则重试一次，最后用模板兜底
    4. 构建卡片布局
    5. 返回完整响应
    """
    if kind not in VALID_KINDS:
        raise ValueError(f"无效的 kind：{kind!r}")
    if tone not in VALID_TONES:
        tone = "轻松"

    facts = compute_facts(db, user_id, kind, anchor, meal_id)

    period_label = (facts.get("period") or {}).get("label", "")
    prompt = (
        f"请为以下饮食数据生成一段{tone}风格的社交分享文案（严格 JSON）：\n"
        f"时间段：{period_label}\n"
        f"记录餐次：{facts.get('meal_count', 0)}\n"
        f"打卡天数：{facts.get('days_with_records', 0)}/{facts.get('days_total', 7)}\n\n"
        "输出格式（严格 JSON，不要多余文字）：\n"
        '{"headline": "≤16字标题", "body": "≤80字正文", '
        '"hashtags": ["#标签1", "#标签2"], "emoji": "一个emoji"}\n'
        "不得出现卡路里数字、医疗建议。"
    )

    client = llm_client.get_client(db)
    messages = [{"role": "user", "content": prompt}]
    mock_context = {"facts": facts, "tone": tone, "kind": kind}

    copy_data: Optional[Dict[str, Any]] = None
    for attempt in range(2):
        try:
            raw = client.chat(messages, task="share_copy", temperature=0.8,
                              json_mode=True, mock_context=mock_context)
            copy_data = _validate_llm_copy(raw)
            break
        except Exception:  # noqa: BLE001
            if attempt == 1:
                copy_data = _fallback_copy(facts, tone)

    if copy_data is None:
        copy_data = _fallback_copy(facts, tone)

    card = _build_card_layout(facts, tone)

    return {
        "copy": copy_data,
        "facts": facts,
        "card": card,
        "disclaimer": config.DISCLAIMER,
    }
