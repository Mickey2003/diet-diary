"""
个性化餐单服务：基于用户档案、记忆、近期饮食统计，通过 LLM 生成个性化餐单。

设计要点：
1. 提示词包含：档案(BMI/能量/体质/注意事项)、用户记忆、近14天统计、用餐时间
2. LLM 输出经 Pydantic 校验（枚举容错、每餐最多6道菜、天数截断）
3. 过敏原过滤：发现菜名含过敏原 → 删除该菜并记录警告
4. 剥离 mg/卡路里等字眼（正则兜底）
5. 失败最多重试一次，然后返回 502
6. 注意事项存储在 cautions_json 并附在响应中
"""
import json
import os
import re
import threading
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from ..models import MealPlan, PlanVersion, Profile
from .llm_client import LLMError, get_client, parse_json
from .dish_image import enrich_plan_images
from .mock_llm import register as _mock_register
from .task_state import begin as _task_begin, end as _task_end, is_busy as _task_busy

PLAN_DISCLAIMER = (
    "以下内容为一般性饮食参考，不构成医疗诊断或用药建议；有疾病或用药请遵医嘱。"
)

# 替换建议回退快照目录（位于 backend/data/snapshots）
_BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SNAPSHOT_DIR = os.path.join(_BASE_DIR, "data", "snapshots")
try:
    os.makedirs(SNAPSHOT_DIR, exist_ok=True)
except Exception:  # noqa: BLE001
    pass

# 菜品分类白名单
DISH_CATEGORIES = {"主食", "蛋白质", "蔬菜", "水果", "饮品", "甜点零食", "汤", "其他"}
DISH_PORTIONS = {"少", "中", "多"}

# 正则：剥离禁止出现的计量/医疗数字
_FORBIDDEN_RE = re.compile(r"[^\n]*\b(\d+\s*mg|\d+\s*卡路里|\d+\s*千卡|\d+\s*kcal)[^\n]*", re.IGNORECASE)

# ---------------------------------------------------------------------------
# Mock 数据（确保离线测试可用）
# ---------------------------------------------------------------------------

# Day 0 早餐含"花生酱"，用于测试过敏原过滤逻辑
_BREAKFAST_POOL: List[List[Dict[str, str]]] = [
    [  # day 0 — 含花生（测试过敏原过滤用）
        {"name": "花生酱全麦土司", "category": "主食", "portion": "中"},
        {"name": "水煮蛋", "category": "蛋白质", "portion": "少"},
        {"name": "牛奶", "category": "饮品", "portion": "中"},
    ],
    [
        {"name": "燕麦粥", "category": "主食", "portion": "中"},
        {"name": "水煮蛋", "category": "蛋白质", "portion": "少"},
        {"name": "香蕉", "category": "水果", "portion": "少"},
    ],
    [
        {"name": "全麦面包", "category": "主食", "portion": "中"},
        {"name": "豆浆", "category": "饮品", "portion": "中"},
        {"name": "苹果", "category": "水果", "portion": "少"},
    ],
    [
        {"name": "小米粥", "category": "主食", "portion": "中"},
        {"name": "拌豆腐", "category": "蛋白质", "portion": "少"},
        {"name": "橙子", "category": "水果", "portion": "少"},
    ],
    [
        {"name": "杂粮馒头", "category": "主食", "portion": "中"},
        {"name": "煎蛋", "category": "蛋白质", "portion": "少"},
        {"name": "猕猴桃", "category": "水果", "portion": "少"},
    ],
    [
        {"name": "紫薯粥", "category": "主食", "portion": "中"},
        {"name": "酱豆腐", "category": "蛋白质", "portion": "少"},
        {"name": "梨", "category": "水果", "portion": "少"},
    ],
    [
        {"name": "荞麦面", "category": "主食", "portion": "中"},
        {"name": "茶叶蛋", "category": "蛋白质", "portion": "少"},
        {"name": "葡萄", "category": "水果", "portion": "少"},
    ],
]

_LUNCH_POOL: List[List[Dict[str, str]]] = [
    [
        {"name": "米饭", "category": "主食", "portion": "中"},
        {"name": "番茄炒蛋", "category": "蛋白质", "portion": "中"},
        {"name": "清炒西兰花", "category": "蔬菜", "portion": "中"},
        {"name": "紫菜蛋花汤", "category": "汤", "portion": "中"},
    ],
    [
        {"name": "荞麦面", "category": "主食", "portion": "中"},
        {"name": "肉末豆腐", "category": "蛋白质", "portion": "中"},
        {"name": "凉拌黄瓜", "category": "蔬菜", "portion": "中"},
    ],
    [
        {"name": "糙米饭", "category": "主食", "portion": "中"},
        {"name": "清蒸鱼", "category": "蛋白质", "portion": "中"},
        {"name": "炒青菜", "category": "蔬菜", "portion": "中"},
    ],
    [
        {"name": "杂粮饭", "category": "主食", "portion": "中"},
        {"name": "红烧豆腐", "category": "蛋白质", "portion": "中"},
        {"name": "炒白菜", "category": "蔬菜", "portion": "中"},
    ],
    [
        {"name": "米饭", "category": "主食", "portion": "中"},
        {"name": "鸡胸肉炒时蔬", "category": "蛋白质", "portion": "中"},
        {"name": "冬瓜汤", "category": "汤", "portion": "中"},
    ],
    [
        {"name": "手工面条", "category": "主食", "portion": "中"},
        {"name": "卤蛋", "category": "蛋白质", "portion": "少"},
        {"name": "煮花椰菜", "category": "蔬菜", "portion": "中"},
    ],
    [
        {"name": "燕麦饭", "category": "主食", "portion": "中"},
        {"name": "煎三文鱼", "category": "蛋白质", "portion": "中"},
        {"name": "清炒菠菜", "category": "蔬菜", "portion": "中"},
    ],
]

_DINNER_POOL: List[List[Dict[str, str]]] = [
    [
        {"name": "小米粥", "category": "主食", "portion": "中"},
        {"name": "清蒸豆腐", "category": "蛋白质", "portion": "中"},
        {"name": "凉拌海带", "category": "蔬菜", "portion": "中"},
    ],
    [
        {"name": "薏仁粥", "category": "主食", "portion": "中"},
        {"name": "白灼虾", "category": "蛋白质", "portion": "中"},
        {"name": "炒芥蓝", "category": "蔬菜", "portion": "中"},
    ],
    [
        {"name": "米饭", "category": "主食", "portion": "少"},
        {"name": "清炖排骨", "category": "蛋白质", "portion": "中"},
        {"name": "炒时蔬", "category": "蔬菜", "portion": "中"},
    ],
    [
        {"name": "全麦馒头", "category": "主食", "portion": "少"},
        {"name": "豆腐白菜汤", "category": "汤", "portion": "多"},
        {"name": "拌黄瓜", "category": "蔬菜", "portion": "中"},
    ],
    [
        {"name": "杂粮粥", "category": "主食", "portion": "中"},
        {"name": "蒸蛋羹", "category": "蛋白质", "portion": "中"},
        {"name": "清炒山药", "category": "蔬菜", "portion": "中"},
    ],
    [
        {"name": "红薯粥", "category": "主食", "portion": "中"},
        {"name": "番茄豆腐汤", "category": "汤", "portion": "中"},
        {"name": "炒西葫芦", "category": "蔬菜", "portion": "中"},
    ],
    [
        {"name": "南瓜粥", "category": "主食", "portion": "中"},
        {"name": "水煮鱼片", "category": "蛋白质", "portion": "中"},
        {"name": "清炒莴笋", "category": "蔬菜", "portion": "中"},
    ],
]

_SNACK_DISHES: List[Dict[str, str]] = [
    {"name": "核桃", "category": "蛋白质", "portion": "少"},
    {"name": "无糖酸奶", "category": "蛋白质", "portion": "少"},
    {"name": "苹果", "category": "水果", "portion": "少"},
]


def _build_mock_plan(days: int, start_date_str: str, meal_times: Dict[str, str]) -> Dict:
    """构建 mock 7 天餐单（day 0 早餐含花生，用于测试过滤逻辑）。"""
    start = date.fromisoformat(start_date_str)
    days_data = []

    for i in range(days):
        d = start + timedelta(days=i)
        idx = i % 7
        meals = []

        if "早餐" in meal_times:
            meals.append({
                "meal_type": "早餐",
                "time": meal_times.get("早餐", "07:30"),
                "dishes": _BREAKFAST_POOL[idx],
                "tip": "早餐保证优质蛋白质和全谷物，为上午提供持续能量。",
            })

        if "午餐" in meal_times:
            meals.append({
                "meal_type": "午餐",
                "time": meal_times.get("午餐", "12:00"),
                "dishes": _LUNCH_POOL[idx],
                "tip": "午餐荤素搭配，主食适量，下午精力更好。",
            })

        if "加餐" in meal_times:
            meals.append({
                "meal_type": "加餐",
                "time": meal_times.get("加餐", "15:30"),
                "dishes": _SNACK_DISHES[:1],
                "tip": "少量健康零食，避免正餐过度饥饿。",
            })

        if "晚餐" in meal_times:
            meals.append({
                "meal_type": "晚餐",
                "time": meal_times.get("晚餐", "18:30"),
                "dishes": _DINNER_POOL[idx],
                "tip": "晚餐以清淡为主，减少精制主食。",
            })

        days_data.append({"date": d.isoformat(), "meals": meals})

    return {
        "title": f"{days}天个性化饮食计划（离线演示）",
        "days": days_data,
        "rationale": {
            "nutrition": "以全谷物为主食基础，蛋白质来源多样（豆类、蛋类、鱼类），蔬菜丰富，减少精制糖和油脂。",
            "tcm": "饮食整体偏温和平性，早餐以粥类养胃，晚餐清淡助眠，顺应脾胃运化节律。",
            "swaps": ["白米饭可换为糙米或杂粮饭", "肉类可换为同等分量的豆腐或豆类", "含糖饮料可换为温热清茶"],
        },
        "shopping_list": [
            "燕麦", "全麦面包", "糙米", "小米",
            "鸡蛋（7个）", "豆腐", "鱼类（按需）",
            "西兰花", "黄瓜", "青菜", "番茄",
            "苹果", "香蕉", "橙子",
            "牛奶/豆浆",
        ],
    }


def _mock_meal_plan(messages: List[Dict], ctx: Dict) -> str:
    days = int(ctx.get("days", 7))
    start_date_str = ctx.get("start_date") or date.today().isoformat()
    meal_times = ctx.get("meal_times") or {"早餐": "07:30", "午餐": "12:00", "晚餐": "18:30"}
    plan = _build_mock_plan(days, start_date_str, meal_times)
    return json.dumps(plan, ensure_ascii=False)


def _mock_meal_plan_slot(messages: List[Dict], ctx: Dict) -> str:
    meal_type = ctx.get("meal_type", "午餐")
    time_str = ctx.get("time", "12:00")
    idx = int(ctx.get("day_index", 0)) % 7

    pool_map = {
        "早餐": _BREAKFAST_POOL,
        "午餐": _LUNCH_POOL,
        "晚餐": _DINNER_POOL,
        "加餐": [_SNACK_DISHES],
    }
    pool = pool_map.get(meal_type, _LUNCH_POOL)
    dishes = pool[idx % len(pool)]

    slot = {
        "meal_type": meal_type,
        "time": time_str,
        "dishes": dishes,
        "tip": "调整后的菜单，均衡营养。",
    }
    return json.dumps(slot, ensure_ascii=False)


_mock_register("meal_plan", _mock_meal_plan)
_mock_register("meal_plan_slot", _mock_meal_plan_slot)


# ---------------------------------------------------------------------------
# Pydantic 校验模型（定义在此模块，避免污染 schemas.py）
# ---------------------------------------------------------------------------

class DishIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=40)
    category: str = "其他"
    portion: str = "中"
    note: Optional[str] = None
    image_url: Optional[str] = None  # 菜品配图（AI 生图或缓存），缺省时前端回退占位图

    @field_validator("category", mode="before")
    @classmethod
    def _cat(cls, v: Any) -> str:
        return v if v in DISH_CATEGORIES else "其他"

    @field_validator("portion", mode="before")
    @classmethod
    def _portion(cls, v: Any) -> str:
        return v if v in DISH_PORTIONS else "中"


class MealSlotIn(BaseModel):
    meal_type: str
    time: str = "12:00"
    dishes: List[DishIn] = Field(default_factory=list)
    tip: str = ""

    @field_validator("dishes", mode="before")
    @classmethod
    def _cap_dishes(cls, v: Any) -> Any:
        if isinstance(v, list) and len(v) > 6:
            return v[:6]
        return v


class DayPlanIn(BaseModel):
    date: str
    meals: List[MealSlotIn] = Field(default_factory=list)


class RationaleIn(BaseModel):
    nutrition: str = ""
    tcm: str = ""
    swaps: List[str] = Field(default_factory=list)


class PlanJSONIn(BaseModel):
    title: str
    days: List[DayPlanIn] = Field(default_factory=list)
    rationale: RationaleIn = Field(default_factory=RationaleIn)
    shopping_list: List[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------

def _strip_forbidden_lines(text: str) -> str:
    """删除含 mg/卡路里/千卡/kcal 字样的行（正则兜底）。"""
    return _FORBIDDEN_RE.sub("", text).strip()


def _filter_allergens(
    plan_dict: Dict, allergies: Optional[str]
) -> Tuple[Dict, List[str]]:
    """
    扫描所有菜名，若含过敏原关键词则删除该菜并生成警告。
    返回 (过滤后的 plan_dict, warnings_list)。
    """
    warnings: List[str] = []
    if not allergies:
        return plan_dict, warnings

    allergen_kws = [
        a.strip()
        for a in allergies.replace("，", ",").replace("、", ",").split(",")
        if a.strip()
    ]
    if not allergen_kws:
        return plan_dict, warnings

    for day in plan_dict.get("days", []):
        for meal in day.get("meals", []):
            kept = []
            for dish in meal.get("dishes", []):
                name = dish.get("name", "")
                matched = [kw for kw in allergen_kws if kw in name]
                if matched:
                    warnings.append(
                        f"已移除含过敏原「{'、'.join(matched)}」的菜品：{name}"
                    )
                else:
                    kept.append(dish)
            meal["dishes"] = kept

    return plan_dict, warnings


def _validate_plan_json(raw_dict: Dict, requested_days: int) -> PlanJSONIn:
    """校验 LLM 返回的计划 JSON：截断超出天数、枚举容错，并要求结构完整（否则抛错触发重试）。"""
    if not isinstance(raw_dict, dict):
        raise ValueError("餐单不是 JSON 对象")
    if "days" in raw_dict and isinstance(raw_dict["days"], list):
        raw_dict["days"] = raw_dict["days"][:requested_days]
    plan = PlanJSONIn.model_validate(raw_dict)
    if not plan.days:
        raise ValueError("餐单没有任何一天的内容")
    if len(plan.days) < max(1, min(requested_days, 2)) and requested_days > 1:
        raise ValueError(f"餐单只有 {len(plan.days)} 天，少于要求的 {requested_days} 天")
    for d in plan.days:
        if not d.meals:
            raise ValueError(f"{d.date} 没有任何餐次")
        for m in d.meals:
            if not m.dishes:
                raise ValueError(f"{d.date} {m.meal_type} 没有菜品")
    return plan


# 同一用户同时只允许一次餐单生成（防止超时后重复点击产生多份）
_GENERATING: set = set()


def is_generating(user_id: int) -> bool:
    """该用户是否正在生成餐单（供前端刷新后恢复“生成中”状态）。"""
    return _task_busy("plan", user_id)

# 正在后台补全配图的餐单 id（去重，避免重复生图/重复写库）
_ENRICHING: set = set()

# 正在重新生成“某餐”的用户（防止重复触发同一单餐的模型调用）
_SLOT_GENERATING: set = set()


def is_slot_generating(user_id: int) -> bool:
    """该用户是否有单餐正在重新生成（供前端刷新后恢复状态）。"""
    return _task_busy("slot", user_id)


def _enrich_now(plan: "MealPlan", db, *, sync: bool, force_ai: bool = False) -> None:
    """就地补全某餐单的配图并写回 plan_json。

    这里是纯函数式的一段逻辑，供同步（生成接口内）与后台线程两处复用。
    AI 生图走「生图专用配置」（image_client），与文本/识图模型解耦。
    """
    from .. import config
    web_enabled = config.DISH_IMAGES_WEB
    ai_on = dish_image.ai_images_enabled(db)
    ai_ready = ai_on and dish_image.image_config_ready(db)
    if not web_enabled and not ai_ready and not force_ai:
        return
    if not plan or not plan.plan_json:
        return
    plan_dict = json.loads(plan.plan_json)
    enriched = enrich_plan_images(
        plan_dict, db,
        web_enabled=web_enabled,
        ai_enabled=ai_ready or force_ai,
        force_ai=force_ai,
    )
    plan.plan_json = json.dumps(enriched, ensure_ascii=False)
    db.commit()


def replace_emoji_with_ai(plan_id: int, db) -> Dict[str, int]:
    """把餐单中「还没有真实图片」的菜品用 AI 生图替换掉。

    返回 {"total": 菜品总数, "remaining": 仍无真实图的数量}。
    """
    plan = db.get(MealPlan, plan_id)
    if plan is None or not plan.plan_json:
        return {"total": 0, "remaining": 0}
    plan_dict = json.loads(plan.plan_json)
    _enrich_now(plan, db, sync=True, force_ai=True)
    again = json.loads(plan.plan_json) if plan.plan_json else plan_dict
    return {
        "total": len(list(dish_image._iter_dishes(again))),
        "remaining": dish_image.count_emoji_dishes(again),
    }


def enrich_plan_images_now(plan_id: int, db) -> None:
    """在调用方线程内同步为餐单补图（用于"生成后图片立即一起显示"）。

    失败静默忽略，绝不影响餐单生成结果。
    """
    try:
        plan = db.get(MealPlan, plan_id)
        _enrich_now(plan, db, sync=True)
    except Exception:  # noqa: BLE001
        pass


def _schedule_image_enrichment(plan_id: int) -> None:
    """
    后台线程：为餐单补全菜品配图（best-effort，不阻塞餐单接口、不发通知）。
    使用独立 DB 会话，失败静默忽略，餐单仍保留（前端回退占位图）。
    """
    from .. import config
    web_enabled = config.DISH_IMAGES_WEB
    if plan_id in _ENRICHING:
        return
    # 既不上网抓现成图、也没开 AI 生图 → 无任何配图来源，直接跳过（不产生线程）
    if not web_enabled and not config.LLM_IMAGE_MODEL and not config.DISH_AI_IMAGES:
        return
    _ENRICHING.add(plan_id)

    def _worker() -> None:
        from ..db import SessionLocal
        db = None
        try:
            db = SessionLocal()
            plan = db.get(MealPlan, plan_id)
            _enrich_now(plan, db, sync=False)
        except Exception:  # noqa: BLE001
            pass
        finally:
            if db is not None:
                try:
                    db.close()
                except Exception:  # noqa: BLE001
                    pass
            _ENRICHING.discard(plan_id)

    t = threading.Thread(target=_worker, daemon=True)
    t.start()


def _build_plan_prompt(
    profile_summary: Dict, memories_text: str, stats_summary: str,
    days: int, start_date: str, focus: Optional[str], meal_times: Dict[str, str],
    cautions: List[str],
) -> str:
    """构建生成餐单的 LLM 提示词。"""
    lines = [
        "你是一位专业的中西结合营养师，请根据以下用户信息生成个性化餐单。",
        "",
        "## 用户档案",
    ]
    for k, v in profile_summary.items():
        if v is not None:
            lines.append(f"- {k}: {v}")

    if memories_text:
        lines.append("")
        lines.append("## " + memories_text.split("\n")[0])
        lines.extend(memories_text.split("\n")[1:])

    if stats_summary:
        lines.append("")
        lines.append("## 近14天饮食概况")
        lines.append(stats_summary)

    lines.extend([
        "",
        "## 餐单参数",
        f"- 天数：{days}天（从 {start_date} 开始）",
        f"- 用餐时间：{json.dumps(meal_times, ensure_ascii=False)}",
    ])
    if focus:
        lines.append(f"- 重点关注：{focus}")

    if cautions:
        lines.append("")
        lines.append("## 注意事项（必须遵守，不得与之矛盾）")
        for c in cautions:
            lines.append(f"- {c}")

    lines.extend([
        "",
        "## 硬性规定",
        "1. 禁止输出卡路里、mg、千卡、营养素数值等精确数字",
        "2. 禁止给出用药建议或医疗诊断",
        "3. 每餐菜品不超过6道",
        "4. 严格按照以下 JSON 格式输出，不要有任何解释文字：",
        "",
        '{"title": "...", "days": [{"date": "YYYY-MM-DD", "meals": [{"meal_type": "早餐", '
        '"time": "07:30", "dishes": [{"name": "...", "category": "主食|蛋白质|蔬菜|水果|饮品|甜点零食|汤|其他", '
        '"portion": "少|中|多", "note": "可选"}], "tip": "一句话要点"}]}], '
        '"rationale": {"nutrition": "现代营养视角2-4句", "tcm": "中医体质与食性视角2-4句", "swaps": ["可替换建议"]}, '
        '"shopping_list": ["..."]}',
    ])
    return "\n".join(lines)


def _build_slot_prompt(
    meal_type: str, time_str: str, day_date: str, instruction: Optional[str],
    profile_summary: Dict, cautions: List[str],
) -> str:
    """构建单一餐次重新生成的提示词。"""
    lines = [
        f"请为以下日期和餐次重新生成菜单：{day_date} {meal_type}（{time_str}）",
    ]
    if instruction:
        lines.append(f"用户要求：{instruction}")
    if cautions:
        lines.append("注意事项：" + "；".join(cautions))
    lines.extend([
        "禁止输出卡路里、mg等精确数字。",
        '请以JSON格式返回单个餐次对象（不要数组）：{"meal_type": "...", "time": "...", "dishes": [...], "tip": "..."}',
    ])
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 公开 API
# ---------------------------------------------------------------------------

def generate_plan(
    db: Session,
    user_id: int,
    days: int = 7,
    start_date: Optional[str] = None,
    focus: Optional[str] = None,
    regenerate_from: Optional[int] = None,
) -> Tuple[MealPlan, List[str]]:
    """
    生成餐单并保存，返回 (MealPlan ORM 对象, warnings)。
    """
    from .profile import compute_profile_out, get_cautions, get_or_create_profile
    from .memory import render_memories_for_prompt
    from .stats import compute_stats

    days = max(1, min(7, days))
    start_date_str = start_date or date.today().isoformat()

    if not _task_begin("plan", user_id):
        from fastapi import HTTPException
        raise HTTPException(status_code=409, detail="餐单正在生成中，请稍候（大模型生成 7 天餐单可能需要 1~3 分钟）")
    try:
        return _generate_plan_inner(db, user_id, days, start_date_str, focus, regenerate_from)
    finally:
        _task_end("plan", user_id)


def _generate_plan_inner(db: Session, user_id: int, days: int, start_date_str: str,
                         focus: Optional[str], regenerate_from: Optional[int]) -> Tuple[MealPlan, List[str]]:
    from .profile import compute_profile_out, get_cautions, get_or_create_profile  # noqa: F401
    from .memory import render_memories_for_prompt
    from .stats import compute_stats

    # 获取档案
    profile = get_or_create_profile(db, user_id)
    profile_out = compute_profile_out(db, user_id)
    cautions = profile_out["cautions"]

    # 解析 meal_times
    meal_times: Dict[str, str] = {"早餐": "07:30", "午餐": "12:00", "晚餐": "18:30"}
    if profile.meal_times_json:
        try:
            meal_times = json.loads(profile.meal_times_json)
        except Exception:
            pass

    # 记忆文本
    memories_text = render_memories_for_prompt(db, user_id)

    # 近14天统计摘要
    try:
        stats = compute_stats(db, "week", None, user_id)
        top_items = stats.get("top_items", [])[:5]
        top_str = "; ".join("%s(%s次)" % (it["name"], it["count"]) for it in top_items)
        stats_summary = "最常出现菜品：" + top_str
        stats_summary += f"; 本周记录{stats.get('meal_count', 0)}餐"
    except Exception:
        stats_summary = ""

    # 构建档案摘要（简化）
    profile_summary = {
        "性别": profile.gender,
        "年龄": profile_out.get("age"),
        "身高(cm)": profile.height_cm,
        "体重(kg)": profile.weight_kg,
        "BMI": profile_out.get("bmi"),
        "BMI分类": profile_out.get("bmi_category"),
        "活动强度": profile.activity_level,
        "中医体质": profile.tcm_constitution,
        "疾病/状况": profile.conditions,
        "用药": profile.medications,
        "过敏": profile.allergies,
        "饮食偏好": profile.preferences,
        "目标": profile.goals,
    }
    profile_summary = {k: v for k, v in profile_summary.items() if v is not None}

    prompt = _build_plan_prompt(
        profile_summary, memories_text, stats_summary,
        days, start_date_str, focus, meal_times, cautions,
    )

    client = get_client(db)
    mock_ctx = {
        "days": days,
        "start_date": start_date_str,
        "meal_times": meal_times,
        "allergies": profile.allergies or "",
        "profile": profile_summary,
    }

    warnings: List[str] = []
    raw_dict: Optional[Dict] = None
    last_error: str = ""

    for attempt in range(2):
        try:
            user_content = prompt
            if attempt == 1 and last_error:
                user_content += f"\n\n注意：上次生成的JSON解析失败，请严格按照格式要求重新生成。错误：{last_error}"

            raw = client.chat(
                [
                    {"role": "system", "content": "你是专业的中西结合营养师，严格按照JSON格式输出，不输出任何解释文字。"},
                    {"role": "user", "content": user_content},
                ],
                task="meal_plan",
                temperature=0.4,
                json_mode=True,
                mock_context=mock_ctx,
            )
            raw_dict = parse_json(raw)
            # Pydantic 校验，并以校验后的规范结构入库（补全缺失字段、纠正枚举），避免前端拿到残缺数据
            validated = _validate_plan_json(raw_dict, days)
            raw_dict = validated.model_dump()
            break
        except (LLMError, Exception) as e:  # noqa: BLE001
            last_error = str(e)[:200]
            raw_dict = None
            if attempt == 1:
                raise LLMError(f"餐单生成失败（已重试一次）：{last_error}")

    if raw_dict is None:
        raise LLMError("餐单生成失败：未获得有效响应")

    # 过敏原过滤
    raw_dict, allergen_warnings = _filter_allergens(raw_dict, profile.allergies)
    warnings.extend(allergen_warnings)

    # 剥离禁止字眼（兜底）
    rationale = raw_dict.get("rationale", {})
    for field in ("nutrition", "tcm"):
        if field in rationale and isinstance(rationale[field], str):
            rationale[field] = _strip_forbidden_lines(rationale[field])

    # 截断天数
    if isinstance(raw_dict.get("days"), list):
        raw_dict["days"] = raw_dict["days"][:days]

    # 停用旧的活跃餐单
    db.query(MealPlan).filter(
        MealPlan.user_id == user_id, MealPlan.is_active == True  # noqa: E712
    ).update({"is_active": False})

    # 快照档案
    profile_snapshot = json.dumps({
        "gender": profile.gender,
        "birth_year": profile.birth_year,
        "height_cm": profile.height_cm,
        "weight_kg": profile.weight_kg,
        "bmi": profile_out.get("bmi"),
        "activity_level": profile.activity_level,
        "tcm_constitution": profile.tcm_constitution,
        "conditions": profile.conditions,
        "allergies": profile.allergies,
    }, ensure_ascii=False)

    plan = MealPlan(
        user_id=user_id,
        title=raw_dict.get("title", f"{days}天个性化餐单"),
        start_date=datetime.combine(date.fromisoformat(start_date_str), datetime.min.time()),
        days=days,
        plan_json=json.dumps(raw_dict, ensure_ascii=False),
        rationale_md=json.dumps(rationale, ensure_ascii=False),
        cautions_json=json.dumps(cautions, ensure_ascii=False),
        profile_snapshot_json=profile_snapshot,
        model=client.model_name(),
        is_active=True,
    )
    db.add(plan)
    db.commit()
    db.refresh(plan)
    # 同步补图：让"生成餐单"接口返回时图片就已经随餐单一起显示（并发取图，控制在预算内）。
    # 若同步阶段未覆盖全部菜品，前端展示时机允许再触发一次后台补全（幂等，命中缓存即返回）。
    enrich_plan_images_now(plan.id, db)
    return plan, warnings


# 替换建议解析
_SWAP_SPLIT_RE = re.compile(r"[；;，,\n]+")
_SWAP_PAIR_RE = re.compile(
    r"^(?:将|把|建议|可以|可)?\s*(?P<frm>.+?)\s*"
    r"(?:可)?(?:替换为|替换成|换为|换成|改为|改成|改吃|替换|变成|→|->|=>)\s*"
    r"(?P<to>.+?)\s*$"
)
# 无法精确匹配菜名时，按类别关键词兜底
_CATEGORY_HINTS = [
    (("主食", "米饭", "白饭", "白米饭", "面", "馒头", "粥", "饭"), "主食"),
    (("蛋白质", "肉类", "肉", "鱼", "蛋", "豆腐", "鸡", "牛", "猪", "虾", "蛋白"), "蛋白质"),
    (("蔬菜", "青菜", "菜", "蔬"), "蔬菜"),
    (("水果", "果"), "水果"),
    (("饮品", "饮料", "奶", "豆浆", "茶", "水"), "饮品"),
    (("汤",), "汤"),
]
_FILLER_RE = re.compile(r"^(?:同等分量的|等量的|适量的|一些|少许|更多的|更多|加点|换成|改为|吃)")


def _clean_swap_term(term: str) -> str:
    """清理替换词：去标点/量词前缀，取"或/、"分隔的第一个选项。"""
    t = (term or "").strip().strip("。.!！?？\"'“” ")
    t = _FILLER_RE.sub("", t).strip()
    for sep in ("或", "／", "/", "、"):
        if sep in t:
            t = t.split(sep)[0].strip()
            break
    return t.strip()


def _parse_swap_pairs(instruction: str) -> List[Tuple[str, str]]:
    """从替换建议文本解析出 (原词, 目标词) 列表；支持多组以"；/，"分隔。"""
    pairs: List[Tuple[str, str]] = []
    for seg in _SWAP_SPLIT_RE.split(instruction or ""):
        seg = seg.strip()
        if not seg:
            continue
        m = _SWAP_PAIR_RE.match(seg)
        if not m:
            continue
        frm = _clean_swap_term(m.group("frm"))
        to = _clean_swap_term(m.group("to"))
        if frm and to and frm != to:
            pairs.append((frm, to))
    return pairs


def _category_of_term(term: str) -> Optional[str]:
    for kws, cat in _CATEGORY_HINTS:
        if any(kw in term for kw in kws):
            return cat
    return None


# 通用类别词（按类别整体替换时使用；避免把具体菜名误当类别词而过度替换）
_GENERIC_TERMS = {"主食", "主食类", "蛋白质", "肉类", "肉", "蔬菜", "青菜", "水果",
                  "饮品", "饮料", "奶", "奶制品", "乳制品", "汤", "蛋类", "豆制品", "豆类"}


def _is_generic_term(term: str) -> bool:
    return term in _GENERIC_TERMS or term.endswith("类")


def _apply_swaps_to_dict(plan_dict: Dict, pairs: List[Tuple[str, str]]) -> int:
    """原地按替换对调整餐单菜品名，返回被替换的菜品数（不调用大模型，秒级完成）。"""
    if not pairs:
        return 0
    changed = 0
    for day in plan_dict.get("days", []) or []:
        for meal in day.get("meals", []) or []:
            for dish in meal.get("dishes", []) or []:
                name = dish.get("name", "") or ""
                if not name:
                    continue
                cur_cat = dish.get("category")
                for frm, to in pairs:
                    if not frm:
                        continue
                    if frm in name or (len(name) >= 2 and name in frm):
                        # 命中（任一方向包含）→ 整名替换，避免产生"糙杂粮饭"这类畸形名
                        dish["name"] = to
                        dish["category"] = _category_of_term(to) or cur_cat
                        changed += 1
                        break
                    if _is_generic_term(frm):  # 通用类别词，按类别整体替换
                        cat = _category_of_term(frm)
                        if cat and cur_cat == cat:
                            dish["name"] = to
                            dish["category"] = _category_of_term(to) or cat
                            changed += 1
                            break
    return changed


def _save_version(db: Session, plan: MealPlan, reason: str) -> None:
    """在变更前保存餐单当前状态为一个历史版本（保留最近 30 个）。"""
    try:
        db.add(PlanVersion(plan_id=plan.id, user_id=plan.user_id, reason=(reason or "")[:120],
                           plan_json=plan.plan_json, days=plan.days))
        db.commit()
        rows = (db.query(PlanVersion)
                .filter(PlanVersion.plan_id == plan.id)
                .order_by(PlanVersion.created_at.desc())
                .all())
        if len(rows) > 30:
            for old in rows[30:]:
                db.delete(old)
            db.commit()
    except Exception:  # noqa: BLE001
        db.rollback()


def apply_swap_to_plan(
    db: Session,
    user_id: int,
    plan_id: int,
    instruction: str,
) -> Tuple[MealPlan, str]:
    """
    将替换建议快速应用到餐单（确定性本地替换，不调用大模型，秒级完成）。
    支持"A可换为B""将A换成B"，多组以"；/，"分隔；无法精确匹配时按类别兜底。
    变更前自动保存历史版本，便于在界面回退。返回 (更新后的 MealPlan, 结果说明)。
    """
    p = get_plan(db, user_id, plan_id)
    pairs = _parse_swap_pairs(instruction)
    plan_dict = json.loads(p.plan_json)
    trial = json.loads(json.dumps(plan_dict, ensure_ascii=False))
    changed = _apply_swaps_to_dict(trial, pairs)
    if changed == 0:
        return p, "未匹配到可替换的菜品，可手动编辑"

    _save_version(db, p, f"应用替换建议：{instruction[:40]}")
    p.plan_json = json.dumps(trial, ensure_ascii=False)
    db.commit()
    db.refresh(p)
    _schedule_image_enrichment(p.id)
    return p, f"已应用替换（共调整 {changed} 道菜）"


def list_versions(db: Session, user_id: int, plan_id: int) -> List[Dict[str, Any]]:
    """列出某餐单的历史版本（降序）。"""
    p = get_plan(db, user_id, plan_id)  # 权限校验
    rows = (db.query(PlanVersion)
            .filter(PlanVersion.plan_id == p.id)
            .order_by(PlanVersion.created_at.desc())
            .all())
    out: List[Dict[str, Any]] = []
    for v in rows:
        dish_count = 0
        title = ""
        try:
            d = json.loads(v.plan_json)
            title = d.get("title", "") or ""
            for day in d.get("days", []) or []:
                for meal in day.get("meals", []) or []:
                    dish_count += len(meal.get("dishes", []) or [])
        except Exception:  # noqa: BLE001
            pass
        out.append({
            "id": v.id,
            "reason": v.reason,
            "title": title,
            "days": v.days,
            "dish_count": dish_count,
            "created_at": v.created_at.isoformat(),
        })
    return out


def restore_version(db: Session, user_id: int, plan_id: int, version_id: int) -> MealPlan:
    """将餐单恢复到指定历史版本（恢复前自动备份当前状态）。"""
    from fastapi import HTTPException
    p = get_plan(db, user_id, plan_id)
    v = db.get(PlanVersion, version_id)
    if not v or v.plan_id != p.id:
        raise HTTPException(status_code=404, detail="历史版本不存在")
    _save_version(db, p, "恢复历史版本前的自动备份")
    p.plan_json = v.plan_json
    db.commit()
    db.refresh(p)
    enrich_plan_images_now(p.id, db)
    return p


def _normalize_plan_days(parsed: Dict, prev_days: List[Dict]) -> Dict:
    """将新生成的餐单日期对齐到原餐单，避免日期漂移导致今日餐单丢失。"""
    new_days = parsed.get("days", []) or []
    prev_dates = [d.get("date") for d in prev_days]
    for i, d in enumerate(new_days):
        if i < len(prev_dates) and prev_dates[i]:
            d["date"] = prev_dates[i]
    parsed["days"] = new_days
    return parsed


def plan_to_dict(plan: MealPlan, extra_warnings: Optional[List[str]] = None) -> Dict[str, Any]:
    """将 MealPlan ORM 对象序列化为字典，含注意事项和免责声明。"""
    plan_data = json.loads(plan.plan_json)
    cautions: List[str] = []
    if plan.cautions_json:
        try:
            cautions = json.loads(plan.cautions_json)
        except Exception:
            pass

    rationale: Dict = {}
    if plan.rationale_md:
        try:
            rationale = json.loads(plan.rationale_md)
        except Exception:
            rationale = {"nutrition": plan.rationale_md}

    # 图片统计：前端据此决定是否亮起「把 emoji 图替换成 AI 图」按钮
    total_dishes = 0
    emoji_dishes = 0
    for _d in plan_data.get("days", []) or []:
        for _m in _d.get("meals", []) or []:
            for _dish in _m.get("dishes", []) or []:
                total_dishes += 1
                if not (_dish.get("image_url") or "").strip():
                    emoji_dishes += 1

    return {
        "id": plan.id,
        "user_id": plan.user_id,
        "title": plan.title,
        "start_date": plan.start_date.date().isoformat(),
        "days": plan.days,
        "is_active": plan.is_active,
        "plan": plan_data,
        "rationale": rationale,
        "cautions": cautions,
        "model": plan.model,
        "created_at": plan.created_at.isoformat(),
        "updated_at": plan.updated_at.isoformat(),
        "warnings": extra_warnings or [],
        "disclaimer": PLAN_DISCLAIMER,
        "image_stats": {
            "total": total_dishes,
            "emoji": emoji_dishes,
            "with_image": total_dishes - emoji_dishes,
        },
    }


def get_plans(db: Session, user_id: int) -> List[Dict[str, Any]]:
    """获取用户所有餐单（降序）。"""
    plans = (
        db.query(MealPlan)
        .filter(MealPlan.user_id == user_id)
        .order_by(MealPlan.created_at.desc())
        .all()
    )
    return [plan_to_dict(p) for p in plans]


def get_plan(db: Session, user_id: int, plan_id: int) -> MealPlan:
    """获取指定餐单（含权限校验）。"""
    from fastapi import HTTPException
    p = db.get(MealPlan, plan_id)
    if not p or p.user_id != user_id:
        raise HTTPException(status_code=404, detail="餐单不存在")
    return p


def delete_plan(db: Session, user_id: int, plan_id: int) -> None:
    """删除餐单。"""
    p = get_plan(db, user_id, plan_id)
    db.delete(p)
    db.commit()


def activate_plan(db: Session, user_id: int, plan_id: int) -> MealPlan:
    """激活指定餐单，停用其他活跃餐单。"""
    p = get_plan(db, user_id, plan_id)
    db.query(MealPlan).filter(
        MealPlan.user_id == user_id, MealPlan.is_active == True  # noqa: E712
    ).update({"is_active": False})
    p.is_active = True
    db.commit()
    db.refresh(p)
    return p


def update_plan_days(db: Session, user_id: int, plan_id: int, days_data: List[Dict]) -> MealPlan:
    """用户手动编辑餐单天数据（编辑前自动保存历史版本）。"""
    p = get_plan(db, user_id, plan_id)
    plan_dict = json.loads(p.plan_json)
    _save_version(db, p, "手动编辑餐单")
    plan_dict["days"] = days_data
    p.plan_json = json.dumps(plan_dict, ensure_ascii=False)
    db.commit()
    db.refresh(p)
    return p


def regenerate_slot(
    db: Session,
    user_id: int,
    plan_id: int,
    day_index: int,
    meal_index: int,
    instruction: Optional[str] = None,
) -> Tuple[MealPlan, List[str]]:
    """
    重新生成餐单中某一天某一餐（其他不变）。
    返回 (更新后的 MealPlan, warnings)。
    """
    from .profile import compute_profile_out, get_or_create_profile

    p = get_plan(db, user_id, plan_id)
    plan_dict = json.loads(p.plan_json)
    days_list = plan_dict.get("days", [])

    if day_index < 0 or day_index >= len(days_list):
        from fastapi import HTTPException
        raise HTTPException(status_code=422, detail=f"day_index {day_index} 超出范围")

    day = days_list[day_index]
    meals = day.get("meals", [])

    if meal_index < 0 or meal_index >= len(meals):
        from fastapi import HTTPException
        raise HTTPException(status_code=422, detail=f"meal_index {meal_index} 超出范围")

    slot = meals[meal_index]
    meal_type = slot.get("meal_type", "午餐")
    time_str = slot.get("time", "12:00")
    day_date = day.get("date", date.today().isoformat())

    profile = get_or_create_profile(db, user_id)
    profile_out = compute_profile_out(db, user_id)
    cautions = profile_out["cautions"]

    profile_summary = {"allergies": profile.allergies}
    slot_prompt = _build_slot_prompt(meal_type, time_str, day_date, instruction, profile_summary, cautions)

    client = get_client(db)
    mock_ctx = {
        "meal_type": meal_type,
        "time": time_str,
        "day_index": day_index,
        "instruction": instruction,
    }

    if not _task_begin("slot", user_id):
        from fastapi import HTTPException
        raise HTTPException(status_code=409, detail="该餐正在重新生成，请稍候")

    warnings: List[str] = []
    slot_updated = False
    try:
        raw = client.chat(
            [
                {"role": "system", "content": "你是营养师，严格按照JSON格式输出单个餐次，不输出解释文字。"},
                {"role": "user", "content": slot_prompt},
            ],
            task="meal_plan_slot",
            temperature=0.5,
            json_mode=True,
            mock_context=mock_ctx,
        )
        parsed = parse_json(raw)
        # 模型偶尔会把单餐包在 {"meals":[...]} 或 {"days":[...]} 里，尽量取出第一餐
        if isinstance(parsed, dict) and "dishes" not in parsed:
            if isinstance(parsed.get("meals"), list) and parsed["meals"]:
                parsed = parsed["meals"][0]
            elif isinstance(parsed.get("days"), list) and parsed["days"] and isinstance(parsed["days"][0], dict) \
                    and parsed["days"][0].get("meals"):
                parsed = parsed["days"][0]["meals"][0]
        slot_model = MealSlotIn.model_validate(parsed)
        if not slot_model.dishes:
            raise ValueError("模型没有返回任何菜品")
        new_slot = slot_model.model_dump()
        new_slot["meal_type"] = new_slot.get("meal_type") or meal_type
        new_slot["time"] = new_slot.get("time") or time_str
        # 过敏原过滤
        if profile.allergies:
            allergen_kws = [
                a.strip()
                for a in profile.allergies.replace("，", ",").replace("、", ",").split(",")
                if a.strip()
            ]
            kept_dishes = []
            for dish in new_slot.get("dishes", []):
                name = dish.get("name", "")
                matched = [kw for kw in allergen_kws if kw in name]
                if matched:
                    warnings.append(f"已移除含过敏原的菜品：{name}")
                else:
                    kept_dishes.append(dish)
            new_slot["dishes"] = kept_dishes
        meals[meal_index] = new_slot
        slot_updated = True
    except (LLMError, Exception) as e:  # noqa: BLE001
        warnings.append(f"单餐重新生成失败，保留原菜单：{str(e)[:100]}")
    finally:
        _task_end("slot", user_id)

    if slot_updated:
        _save_version(db, p, "重新生成某餐")
    plan_dict["days"] = days_list
    p.plan_json = json.dumps(plan_dict, ensure_ascii=False)
    db.commit()
    db.refresh(p)
    # 单餐重生成也同步补图：用户点了重生成，期望立刻看到该餐的新图
    enrich_plan_images_now(p.id, db)
    return p, warnings


def get_today_meals(db: Session, user_id: int, plan_id: int) -> Dict[str, Any]:
    """从激活餐单中返回今天的餐次。"""
    from .profile import get_or_create_profile
    p = get_plan(db, user_id, plan_id)
    plan_dict = json.loads(p.plan_json)
    today_str = date.today().isoformat()
    today_meals: Optional[Dict] = None
    for day in plan_dict.get("days", []):
        if day.get("date") == today_str:
            today_meals = day
            break
    # 兼容历史餐单：plan_json 里可能还没有 emoji 兜底字段，就地补齐，
    # 保证「今日餐单」在无图时也不会出现空白卡片。
    if today_meals:
        from . import dish_image
        for dish in dish_image._iter_dishes({"days": [today_meals]}):
            if not dish.get("image_emoji"):
                dish_image.apply_emoji_to_dish(dish)
    return {
        "plan_id": plan_id,
        "date": today_str,
        "today": today_meals,
        "disclaimer": PLAN_DISCLAIMER,
    }
