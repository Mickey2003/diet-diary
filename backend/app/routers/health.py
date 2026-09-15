"""
健康档案 + 个性化餐单 API 路由（/api/health）。

Feature 1: 健康档案（人设预设、档案 CRUD、注意事项、中医体质问卷）
Feature 2: 个性化餐单（生成、增删改查、单槽重生成、今日餐次）

注意：main.py 已有 GET /api/health 返回系统状态（不影响此路由下的子路径）。
所有端点通过 Depends(get_current_user) 声明鉴权。
"""
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import get_current_user
from ..models import User
from ..services import meal_plan as mp_svc
from ..services import memory as mem_svc
from ..services import profile as profile_svc
from ..services import task_state

router = APIRouter(prefix="/api/health", tags=["health"])


# ---------------------------------------------------------------------------
# Pydantic 请求/响应模型
# ---------------------------------------------------------------------------

class SwapApplyIn(BaseModel):
    """替换建议直接应用请求。"""
    swap_instruction: str = Field(..., min_length=1, max_length=500)


class ProfileUpdate(BaseModel):
    """档案局部更新请求。"""
    persona: Optional[str] = None
    gender: Optional[str] = None
    birth_year: Optional[int] = None
    height_cm: Optional[float] = None
    weight_kg: Optional[float] = None
    activity_level: Optional[str] = None
    conditions: Optional[str] = None
    medications: Optional[str] = None
    allergies: Optional[str] = None
    preferences: Optional[str] = None
    tcm_constitution: Optional[str] = None
    goals: Optional[str] = None
    meal_times: Optional[Dict[str, str]] = None
    budget_level: Optional[str] = None
    cooking_ability: Optional[str] = None
    apply_preset_defaults: bool = False


class QuizAnswersRequest(BaseModel):
    answers: List[Dict[str, Any]] = Field(..., description="[{question_id, value}]")
    save: bool = False


class PlanCreate(BaseModel):
    days: int = Field(7, ge=1, le=7)
    start_date: Optional[str] = None
    focus: Optional[str] = None
    regenerate_from: Optional[int] = None


class PlanDaysUpdate(BaseModel):
    days: List[Dict[str, Any]] = Field(..., description="天数据数组（校验与 plan_json 相同结构）")


class SlotUpdate(BaseModel):
    day_index: int = Field(..., ge=0)
    meal_index: int = Field(..., ge=0)
    instruction: Optional[str] = None


# ---------------------------------------------------------------------------
# Feature 1: 人设预设
# ---------------------------------------------------------------------------

@router.get("/personas")
def get_personas(
    _user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """返回所有人设预设信息。"""
    return {
        "personas": profile_svc.PERSONAS,
        "disclaimer": profile_svc.HEALTH_DISCLAIMER,
    }


# ---------------------------------------------------------------------------
# Feature 1: 档案
# ---------------------------------------------------------------------------

@router.get("/profile")
def get_profile(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """
    获取当前用户的健康档案（不存在时自动创建空档案）。
    包含计算字段：年龄、BMI、能量估算、注意事项。
    """
    return profile_svc.compute_profile_out(db, user.id)


@router.put("/profile")
def update_profile(
    payload: ProfileUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """
    局部更新健康档案。
    若设置 persona，将用预设填充空字段；apply_preset_defaults=true 则强制覆盖。
    """
    data = payload.model_dump(exclude_none=True)
    apply_preset = data.pop("apply_preset_defaults", False)

    # 校验
    errors = profile_svc.validate_profile_update(data)
    if errors:
        raise HTTPException(status_code=422, detail={"errors": errors})

    profile = profile_svc.update_profile(db, user.id, data, apply_preset_defaults=apply_preset)

    # 触发记忆提取（fire-and-forget）
    try:
        mem_svc.on_profile_updated(db, user.id, profile)
    except Exception:  # noqa: BLE001
        pass

    return profile_svc.compute_profile_out(db, user.id)


# ---------------------------------------------------------------------------
# Feature 1: 中医体质问卷
# ---------------------------------------------------------------------------

@router.get("/constitution-quiz")
def get_constitution_quiz(
    _user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """获取中医体质自测问卷（参考性自测）。"""
    return profile_svc.get_quiz()


@router.post("/constitution-quiz")
def submit_constitution_quiz(
    payload: QuizAnswersRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """
    提交问卷答案，返回各体质得分和建议体质。
    若 save=true，将建议体质写入档案。
    """
    scores, suggested = profile_svc.score_quiz(payload.answers)

    if payload.save:
        profile_svc.update_profile(db, user.id, {"tcm_constitution": suggested})

    return {
        "scores": scores,
        "suggested": suggested,
        "note": "本结果为参考性自测，非临床诊断。",
        "disclaimer": profile_svc.HEALTH_DISCLAIMER,
    }


# ---------------------------------------------------------------------------
# Feature 2: 餐单
# ---------------------------------------------------------------------------

@router.post("/plans", status_code=201)
def create_plan(
    payload: PlanCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """生成个性化餐单（调用 LLM，mock 模式离线可用）。同一用户并发生成会返回 409。"""
    from fastapi import HTTPException as _HTTPException
    try:
        plan, warnings = mp_svc.generate_plan(
            db=db,
            user_id=user.id,
            days=payload.days,
            start_date=payload.start_date,
            focus=payload.focus,
            regenerate_from=payload.regenerate_from,
        )
    except _HTTPException:
        raise  # 409 正在生成中 等业务状态码原样返回
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"餐单生成失败：{str(e)[:200]}")

    return mp_svc.plan_to_dict(plan, extra_warnings=warnings)


@router.get("/plans")
def list_plans(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> List[Dict[str, Any]]:
    """获取当前用户所有餐单（降序）。"""
    return mp_svc.get_plans(db, user.id)


@router.get("/plans/generating")
def plan_generating(
    user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """该用户正在进行的餐单任务（前端刷新后据此恢复“生成中”状态，避免重复点击）。"""
    return {
        "generating": mp_svc.is_generating(user.id),
        "slot": mp_svc.is_slot_generating(user.id),
    }


@router.post("/plans/{plan_id}/replace-emoji-images")
def replace_emoji_images(
    plan_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """把餐单中仍是 emoji 兜底的菜品，用 AI 生图批量替换。

    需要管理员已开启 AI 生图并配置好「生图专用 API」。
    任务登记为 busy("plan")，重复触发返回 409，避免刷新后重复点击。
    """
    from ..services import dish_image

    if not dish_image.ai_images_enabled(db):
        raise HTTPException(status_code=400, detail="AI 生图未开启，请先在设置中开启并配置生图 API")
    if not dish_image.image_config_ready(db):
        raise HTTPException(status_code=400, detail="生图 API 尚未配置（提供商 / API Key / 模型）")

    # 校验餐单归属
    mp_svc.get_plan(db, user.id, plan_id)

    task_state.begin_check("plan", user.id)  # 冲突时抛 409
    try:
        stats = mp_svc.replace_emoji_with_ai(plan_id, db)
    finally:
        task_state.end("plan", user.id)

    p = mp_svc.get_plan(db, user.id, plan_id)
    out = mp_svc.plan_to_dict(p)
    out["replace_result"] = stats
    return out


@router.get("/plans/{plan_id}/today")
def get_today(
    plan_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """从指定餐单返回今天的餐次（用于提醒/MCP）。"""
    return mp_svc.get_today_meals(db, user.id, plan_id)


@router.get("/plans/{plan_id}")
def get_plan(
    plan_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """获取指定餐单详情。"""
    p = mp_svc.get_plan(db, user.id, plan_id)
    return mp_svc.plan_to_dict(p)


@router.delete("/plans/{plan_id}", status_code=204)
def delete_plan(
    plan_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> None:
    """删除餐单。"""
    mp_svc.delete_plan(db, user.id, plan_id)
    return None


@router.post("/plans/{plan_id}/activate")
def activate_plan(
    plan_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """激活指定餐单（自动停用其他活跃餐单）。"""
    p = mp_svc.activate_plan(db, user.id, plan_id)
    return mp_svc.plan_to_dict(p)


@router.patch("/plans/{plan_id}")
def update_plan(
    plan_id: int,
    payload: PlanDaysUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """用户手动编辑餐单天数据。"""
    p = mp_svc.update_plan_days(db, user.id, plan_id, payload.days)
    return mp_svc.plan_to_dict(p)


@router.patch("/plans/{plan_id}/slot")
def update_slot(
    plan_id: int,
    payload: SlotUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """重新生成餐单中某一天某一餐（其他餐次不变）。"""
    try:
        p, warnings = mp_svc.regenerate_slot(
            db=db,
            user_id=user.id,
            plan_id=plan_id,
            day_index=payload.day_index,
            meal_index=payload.meal_index,
            instruction=payload.instruction,
        )
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"单餐重新生成失败：{str(e)[:200]}")

    return mp_svc.plan_to_dict(p, extra_warnings=warnings)


@router.post("/plans/{plan_id}/apply-swap")
def apply_swap(
    plan_id: int,
    payload: SwapApplyIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """将替换建议快速应用到整个餐单（本地确定性替换，秒级；变更前自动存历史版本）。"""
    try:
        p, result = mp_svc.apply_swap_to_plan(
            db=db,
            user_id=user.id,
            plan_id=plan_id,
            instruction=payload.swap_instruction,
        )
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"应用替换建议失败：{str(e)[:200]}")
    return mp_svc.plan_to_dict(p, extra_warnings=[result])


@router.get("/plans/{plan_id}/versions")
def list_plan_versions(
    plan_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> List[Dict[str, Any]]:
    """列出餐单的历史版本（用于界面化回退）。"""
    return mp_svc.list_versions(db, user.id, plan_id)


@router.post("/plans/{plan_id}/versions/{version_id}/restore")
def restore_plan_version(
    plan_id: int,
    version_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """将餐单恢复到指定历史版本（恢复前自动备份当前状态）。"""
    p = mp_svc.restore_version(db, user.id, plan_id, version_id)
    return mp_svc.plan_to_dict(p)
