"""
记忆 API 路由（/api/memory）。

用户可查看、管理、手动添加/删除记忆，系统自动提取的记忆也在此管理。
所有操作按当前用户隔离。
"""
from datetime import datetime, timedelta
from collections import Counter
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import get_current_user
from ..models import Meal, MealItem, Memory, Profile, User
from ..services import memory as memory_svc
from ..services.task_state import task_guard

router = APIRouter(prefix="/api/memory", tags=["memory"])

DISCLAIMER = "以下内容为AI辅助提取，仅供参考；请结合实际情况判断。"


# ---------------------------------------------------------------------------
# Pydantic 模型
# ---------------------------------------------------------------------------

class MemoryOut(BaseModel):
    id: int
    content: str
    category: str
    source: str
    importance: int
    is_active: bool
    evidence: Optional[str] = None
    created_at: datetime
    last_used_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class MemoryCreate(BaseModel):
    content: str = Field(..., min_length=4, max_length=300)
    category: str = "preference"
    importance: int = Field(3, ge=1, le=5)
    evidence: Optional[str] = None


class MemoryUpdate(BaseModel):
    content: Optional[str] = Field(None, min_length=4, max_length=300)
    category: Optional[str] = None
    importance: Optional[int] = Field(None, ge=1, le=5)
    is_active: Optional[bool] = None


class ExtractRequest(BaseModel):
    text: str = Field(..., min_length=4, max_length=2000)


class RebuildResponse(BaseModel):
    new_memories: int
    scanned_meals: int
    disclaimer: str = DISCLAIMER


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------

def _own_memory(db: Session, memory_id: int, user: User) -> Memory:
    m = db.get(Memory, memory_id)
    if not m or m.user_id != user.id:
        raise HTTPException(status_code=404, detail="记忆不存在")
    return m


def _validate_category(category: Optional[str]) -> Optional[str]:
    if category is None:
        return None
    if category not in memory_svc.VALID_CATEGORIES:
        raise HTTPException(status_code=422, detail=f"无效类别，可选：{', '.join(memory_svc.VALID_CATEGORIES)}")
    return category


# ---------------------------------------------------------------------------
# 端点
# ---------------------------------------------------------------------------

@router.get("", response_model=List[MemoryOut])
def list_memories(
    category: Optional[str] = Query(None),
    include_inactive: bool = Query(False),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> List[MemoryOut]:
    """获取当前用户的记忆列表（可按类别过滤）。"""
    q = db.query(Memory).filter(Memory.user_id == user.id)
    if not include_inactive:
        q = q.filter(Memory.is_active == True)  # noqa: E712
    if category:
        _validate_category(category)
        q = q.filter(Memory.category == category)
    mems = q.order_by(Memory.importance.desc(), Memory.created_at.desc()).all()
    return [MemoryOut.model_validate(m) for m in mems]


@router.post("", response_model=MemoryOut, status_code=201)
def create_memory(
    payload: MemoryCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> MemoryOut:
    """手动添加一条记忆（source=user）。"""
    _validate_category(payload.category)
    if not memory_svc._is_valid(payload.content):
        raise HTTPException(status_code=422, detail="内容无效（过短、纯数字或含敏感词）")
    # 检查上限
    count = db.query(Memory).filter(Memory.user_id == user.id, Memory.is_active == True).count()  # noqa: E712
    if count >= memory_svc.MAX_MEMORIES:
        raise HTTPException(status_code=422, detail=f"活跃记忆已达上限（{memory_svc.MAX_MEMORIES}条）")
    mem = Memory(
        user_id=user.id,
        content=payload.content.strip(),
        category=payload.category,
        importance=payload.importance,
        evidence=payload.evidence,
        source="user",
    )
    db.add(mem)
    db.commit()
    db.refresh(mem)
    return MemoryOut.model_validate(mem)


@router.patch("/{memory_id}", response_model=MemoryOut)
def update_memory(
    memory_id: int,
    payload: MemoryUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> MemoryOut:
    """编辑一条记忆（内容/类别/重要度/激活状态）。"""
    mem = _own_memory(db, memory_id, user)
    if payload.content is not None:
        if not memory_svc._is_valid(payload.content):
            raise HTTPException(status_code=422, detail="内容无效")
        mem.content = payload.content.strip()
    if payload.category is not None:
        _validate_category(payload.category)
        mem.category = payload.category
    if payload.importance is not None:
        mem.importance = payload.importance
    if payload.is_active is not None:
        mem.is_active = payload.is_active
    db.commit()
    db.refresh(mem)
    return MemoryOut.model_validate(mem)


@router.delete("/{memory_id}", status_code=204)
def delete_memory(
    memory_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> None:
    """删除一条记忆。"""
    mem = _own_memory(db, memory_id, user)
    db.delete(mem)
    db.commit()
    return None


@router.post("/extract", response_model=List[MemoryOut], status_code=201)
def extract_from_text(
    payload: ExtractRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> List[MemoryOut]:
    """手动触发"记住这个"：从自由文本中提取并保存记忆。"""
    saved = memory_svc.extract_memories(db, user.id, "user", payload.text)
    return [MemoryOut.model_validate(m) for m in saved]


@router.post("/rebuild", response_model=RebuildResponse)
def rebuild_memories(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> RebuildResponse:
    """
    重新扫描近30天餐食记录和档案，补充遗漏的记忆（幂等，已有记忆不重复添加）。
    重建期间任务忙状态登记为 "memory"，避免用户刷新页面后重复点击。
    """
    with task_guard("memory", user.id):
        cutoff = datetime.now() - timedelta(days=30)
        meals: List[Meal] = (
            db.query(Meal)
            .filter(Meal.user_id == user.id, Meal.eaten_at >= cutoff)
            .all()
        )

        total_new = 0
        # 一次性汇总近 30 天的菜品名与备注，只调用一次模型（避免逐餐重复抽取）
        try:
            recent_names: List[str] = [item.name for meal in meals for item in meal.items]
            notes = "；".join((m.note or "").strip() for m in meals if (m.note or "").strip())
            text = f"近30天共 {len(meals)} 餐。菜品出现次数：" + "，".join(
                f"{n}×{c}" for n, c in Counter(recent_names).most_common(20)
            ) + (f"。用户备注：{notes[:800]}" if notes else "")
            ctx: Dict = {"text": notes, "items": recent_names, "source_kind": "meal"}
            new = memory_svc.extract_memories(db, user.id, "meal", text, extra_ctx=ctx)
            total_new += len(new)
        except Exception:  # noqa: BLE001
            pass

        # 档案扫描
        try:
            profile = db.get(Profile, user.id)
            if profile:
                new = memory_svc.extract_memories(
                    db, user.id, "profile",
                    "; ".join(filter(None, [
                        profile.conditions, profile.medications, profile.allergies,
                        profile.goals, profile.preferences,
                    ])),
                )
                total_new += len(new)
        except Exception:  # noqa: BLE001
            pass

        return RebuildResponse(new_memories=total_new, scanned_meals=len(meals))


@router.get("/summary")
def memory_summary(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """获取记忆统计摘要及 prompt 预览。"""
    mems: List[Memory] = (
        db.query(Memory)
        .filter(Memory.user_id == user.id, Memory.is_active == True)  # noqa: E712
        .all()
    )
    by_category: Dict[str, int] = {}
    for m in mems:
        by_category[m.category] = by_category.get(m.category, 0) + 1

    prompt_preview = memory_svc.render_memories_for_prompt(db, user.id, limit=5)

    return {
        "count": len(mems),
        "by_category": by_category,
        "prompt_preview": prompt_preview,
        "disclaimer": DISCLAIMER,
    }
