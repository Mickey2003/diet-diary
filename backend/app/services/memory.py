"""
记忆服务：从餐食、档案、自由文本中提取并维护用户记忆。

设计要点：
1. 所有提取走 LLM（mock 模式有关键词规则兜底）
2. 去重：完全相同 or SequenceMatcher ≥0.8 → 跳过或提升重要度
3. 上限：每用户最多 100 条活跃记忆
4. 不存储密码/凭据等敏感内容
"""
import json
import re
from collections import Counter
from datetime import datetime, timedelta
from difflib import SequenceMatcher
from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Meal, MealItem, Memory
from .llm_client import LLMError, get_client, parse_json
from .mock_llm import register as _mock_register

MAX_MEMORIES = 100
VALID_CATEGORIES = {"preference", "habit", "health", "goal", "fact"}

# 敏感词列表（不存储凭据/密码等）
_SECRET_KEYWORDS = ("密码", "password", "token", "secret", "api_key", "apikey", "private_key", "passwd")

# 类别中文标签
CAT_LABELS = {
    "preference": "偏好",
    "habit": "习惯",
    "health": "健康",
    "goal": "目标",
    "fact": "事实",
}


# ---------------------------------------------------------------------------
# Mock 处理器（在模块加载时注册，永不编辑 mock_llm.py）
# ---------------------------------------------------------------------------

def _mock_memory_extract(messages: List[Dict], ctx: Dict) -> str:
    """离线规则提取：用于无 API Key 的演示/测试环境。"""
    text = ctx.get("text", "")
    items = ctx.get("items", [])
    results: List[Dict] = []

    # 从 text 中根据关键词提取偏好/健康信息
    for kw, prefix, category, importance in [
        ("不吃", "不喜欢", "preference", 3),
        ("不爱吃", "不爱吃", "preference", 3),
        ("不爱", "不爱", "preference", 3),
    ]:
        if kw in text:
            idx = text.find(kw)
            food = text[idx + len(kw): idx + len(kw) + 10].strip()
            food = re.split(r"[，,。.！!？?、\s]", food)[0]
            if food and len(food) >= 1:
                results.append({
                    "content": f"{prefix}{food}",
                    "category": category,
                    "importance": importance,
                    "evidence": text[:60],
                })

    if "过敏" in text:
        idx = text.find("过敏")
        food = text[max(0, idx - 12): idx].strip()
        food = re.split(r"[，,。.！!？?、\s：:]", food)[-1]
        food = re.sub(r"^(我|对|吃|喝)+", "", food)  # 去掉“对花生”里的介词，避免生成“对对花生过敏”
        if food and len(food) >= 1:
            results.append({
                "content": f"对{food}过敏",
                "category": "health",
                "importance": 5,
                "evidence": text[:60],
            })

    for kw in ("高血压", "糖尿病", "痛风", "孕期", "哺乳", "高血脂", "肾病", "冠心病"):
        if kw in text:
            results.append({
                "content": f"有{kw}",
                "category": "health",
                "importance": 5,
                "evidence": text[:60],
            })

    # 从 items 频率统计（≥3 次 → 常吃）
    if items:
        c = Counter(items)
        for name, cnt in c.most_common(5):
            if cnt >= 3 and len(name) >= 2:
                results.append({
                    "content": f"常吃{name}",
                    "category": "habit",
                    "importance": 3,
                    "evidence": f"近期饮食记录中出现{cnt}次",
                })

    return json.dumps(results, ensure_ascii=False)


_mock_register("memory_extract", _mock_memory_extract)


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------

def _sim(a: str, b: str) -> float:
    """计算两字符串相似度（SequenceMatcher）。"""
    return SequenceMatcher(None, a, b).ratio()


def _is_valid(content: str) -> bool:
    """检查内容是否合法（排除过短/纯数字/敏感词）。"""
    c = content.strip()
    if len(c) < 4:
        return False
    if re.fullmatch(r"\d+", c):
        return False
    lc = c.lower()
    for kw in _SECRET_KEYWORDS:
        if kw.lower() in lc:
            return False
    return True


def _dedupe_and_save(db: Session, user_id: int, candidates: List[Dict]) -> List[Memory]:
    """去重后批量保存候选记忆，返回新增的 Memory 列表。"""
    existing: List[Memory] = (
        db.query(Memory)
        .filter(Memory.user_id == user_id, Memory.is_active == True)  # noqa: E712
        .all()
    )
    saved: List[Memory] = []

    for c in candidates:
        content = (c.get("content") or "").strip()
        if not content or not _is_valid(content):
            continue

        category = c.get("category", "fact")
        if category not in VALID_CATEGORIES:
            category = "fact"

        try:
            importance = max(1, min(5, int(c.get("importance", 3))))
        except (TypeError, ValueError):
            importance = 3

        evidence = str(c.get("evidence", ""))[:300]

        # 去重检查
        dup: Optional[Memory] = None
        for m in existing:
            if m.content == content or _sim(m.content, content) >= 0.8:
                dup = m
                break

        if dup is not None:
            # 已存在：更新重要度和最后使用时间
            if importance > dup.importance:
                dup.importance = importance
            dup.last_used_at = datetime.now()
            db.commit()
            continue

        # 检查活跃记忆上限
        active_count = (
            db.query(Memory)
            .filter(Memory.user_id == user_id, Memory.is_active == True)  # noqa: E712
            .count()
        )
        if active_count >= MAX_MEMORIES:
            break  # 已达上限

        mem = Memory(
            user_id=user_id,
            content=content,
            category=category,
            importance=importance,
            evidence=evidence,
            source="auto",
        )
        db.add(mem)
        db.commit()
        db.refresh(mem)
        existing.append(mem)
        saved.append(mem)

    return saved


# ---------------------------------------------------------------------------
# 公开 API
# ---------------------------------------------------------------------------

def extract_memories(
    db: Session,
    user_id: int,
    source_kind: str,
    text_or_payload: Any,
    extra_ctx: Optional[Dict] = None,
) -> List[Memory]:
    """
    从文本或结构化 payload 中提取记忆并去重存储。

    :param source_kind: 来源类型（meal / profile / user）
    :param text_or_payload: 字符串或可序列化对象
    :param extra_ctx: 传给 mock 的额外上下文（如 items 列表）
    """
    if isinstance(text_or_payload, str):
        text = text_or_payload
    else:
        text = json.dumps(text_or_payload, ensure_ascii=False)

    ctx: Dict = {"text": text, "source_kind": source_kind}
    if extra_ctx:
        ctx.update(extra_ctx)

    client = get_client(db)
    candidates: List[Dict] = []
    try:
        raw = client.chat(
            [
                {
                    "role": "system",
                    "content": (
                        "你是饮食日记记忆提取助手。请从用户饮食信息中提取有意义的"
                        "偏好、习惯、健康状况、目标或事实，以JSON数组格式返回，"
                        "每项格式：{\"content\"(≤60字), \"category\"(preference/habit/health/goal/fact), "
                        "\"importance\"(1-5), \"evidence\"}。"
                        "不得提取密码/凭据等敏感信息。"
                    ),
                },
                {
                    "role": "user",
                    "content": f"来源：{source_kind}\n\n请从以下信息中提取记忆：\n{text}",
                },
            ],
            task="memory_extract",
            json_mode=True,
            temperature=0.1,
            mock_context=ctx,
        )
        data = parse_json(raw)
        if isinstance(data, list):
            candidates = data
        elif isinstance(data, dict):
            for key in ("memories", "items", "results"):
                if key in data and isinstance(data[key], list):
                    candidates = data[key]
                    break
    except (LLMError, Exception):  # noqa: BLE001
        candidates = []

    return _dedupe_and_save(db, user_id, candidates)


def on_meal_saved(db: Session, user_id: int, meal: Meal) -> None:
    """
    餐食保存后触发的记忆提取钩子（fire-and-forget，失败不影响保存流程）。
    """
    try:
        cutoff = datetime.now() - timedelta(days=14)
        recent_names: List[str] = list(
            db.execute(
                select(MealItem.name)
                .join(Meal, MealItem.meal_id == Meal.id)
                .where(Meal.user_id == user_id, Meal.eaten_at >= cutoff)
            ).scalars().all()
        )
        text = meal.note or ""
        ctx: Dict = {
            "text": text,
            "items": recent_names,
            "source_kind": "meal",
        }
        extract_memories(db, user_id, "meal", text, extra_ctx=ctx)
    except Exception:  # noqa: BLE001
        pass


def on_profile_updated(db: Session, user_id: int, profile: Any) -> None:
    """
    档案更新后触发的记忆提取钩子（fire-and-forget）。
    """
    try:
        parts: List[str] = []
        if getattr(profile, "conditions", None):
            parts.append(f"疾病/状况：{profile.conditions}")
        if getattr(profile, "medications", None):
            parts.append(f"用药：{profile.medications}")
        if getattr(profile, "allergies", None):
            parts.append(f"过敏：{profile.allergies}")
        if getattr(profile, "goals", None):
            parts.append(f"目标：{profile.goals}")
        if getattr(profile, "preferences", None):
            parts.append(f"饮食偏好/忌口：{profile.preferences}")
        if parts:
            text = "；".join(parts)
            extract_memories(db, user_id, "profile", text)
    except Exception:  # noqa: BLE001
        pass


def render_memories_for_prompt(db: Session, user_id: int, limit: int = 15) -> str:
    """
    将用户记忆渲染为 prompt 注入文本（同时更新 last_used_at）。
    若无活跃记忆则返回空字符串。
    """
    mems: List[Memory] = (
        db.query(Memory)
        .filter(Memory.user_id == user_id, Memory.is_active == True)  # noqa: E712
        .order_by(Memory.importance.desc(), Memory.created_at.desc())
        .limit(limit)
        .all()
    )
    if not mems:
        return ""

    now = datetime.now()
    for m in mems:
        m.last_used_at = now
    db.commit()

    lines = ["已知的用户信息（记忆）："]
    for m in mems:
        label = CAT_LABELS.get(m.category, m.category)
        lines.append(f"- [{label}] {m.content}")
    return "\n".join(lines)
