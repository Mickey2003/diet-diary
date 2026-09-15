"""餐食记录：识别草稿 + CRUD（按当前用户隔离）。"""
from datetime import date, datetime, timedelta
from typing import List, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import get_current_user
from ..models import Meal, MealItem, Tag, User
from ..schemas import MealCreate, MealItemIn, MealOut, MealPage, MealUpdate, RecognizeOut
from ..services import vision
from ..services.kcal import estimate_kcal
from ..services.tags import normalize_tag_codes, tag_lookup

router = APIRouter(prefix="/api/meals", tags=["meals"])


def _to_out(m: Meal) -> MealOut:
    out = MealOut.model_validate(m)
    out.image_url = f"/uploads/{m.image_path}" if m.image_path else None
    out.thumb_url = f"/uploads/thumb/{m.image_path}" if m.image_path else None
    vals = [i.kcal for i in m.items if i.kcal is not None]
    out.kcal_total = sum(vals) if vals else None
    return out


class RecognizePathIn(BaseModel):
    image_path: str = Field(..., min_length=1, max_length=300)


@router.post("/recognize-path", response_model=RecognizeOut)
def recognize_by_path(payload: RecognizePathIn, db: Session = Depends(get_db),
                      _user: User = Depends(get_current_user)):
    """对已上传到服务器的图片做识别（App 原生拍照先上传、页面恢复草稿后再识别时使用）。"""
    name = payload.image_path.strip()
    if "/" in name or "\\" in name or name.startswith("."):
        raise HTTPException(status_code=400, detail="非法的图片路径")
    from pathlib import Path
    from .. import config
    if not (Path(config.UPLOAD_DIR) / name).is_file():
        raise HTTPException(status_code=404, detail="图片不存在或已被清理")
    return vision.recognize(db, name)


def _apply_items(db: Session, meal: Meal, items: List[MealItemIn]) -> None:
    lookup = tag_lookup(db)
    meal.items.clear()
    for i, it in enumerate(items):
        codes, _dropped = normalize_tag_codes(it.tags, lookup)
        # 热量：前端给了值就用（来源 ai/user/barcode），否则按本地菜品表估算
        if it.kcal is not None:
            kcal, kcal_src = it.kcal, (it.kcal_source or "user")
        else:
            kcal, kcal_src = estimate_kcal(it.name, it.category, it.portion)
        mi = MealItem(name=it.name.strip(), category=it.category, portion=it.portion,
                      confidence=it.confidence, source=it.source, sort_order=i, barcode=it.barcode,
                      kcal=kcal, kcal_source=kcal_src)
        mi.tags = [lookup[c] for c in codes]
        meal.items.append(mi)


def _own_meal(db: Session, meal_id: int, user: User) -> Meal:
    m = db.get(Meal, meal_id)
    if not m or m.user_id != user.id:
        raise HTTPException(status_code=404, detail="记录不存在")
    return m


@router.post("/recognize", response_model=RecognizeOut)
async def recognize_meal(file: UploadFile = File(...), db: Session = Depends(get_db),
                         _user: User = Depends(get_current_user)):
    """上传图片 → 保存压缩图 → 模型识别 → 返回可编辑草稿（不落库）。"""
    data = await file.read()
    try:
        rel = vision.save_upload(data, file.filename or "")
    except vision.ImageError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return vision.recognize(db, rel)


@router.post("/upload-only")
async def upload_only(file: UploadFile = File(...), _user: User = Depends(get_current_user)):
    """仅保存图片不识别（用于手动录入）。"""
    data = await file.read()
    try:
        rel = vision.save_upload(data, file.filename or "")
    except vision.ImageError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"image_path": rel, "image_url": f"/uploads/{rel}"}


@router.post("", response_model=MealOut, status_code=201)
def create_meal(payload: MealCreate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    if not payload.items:
        raise HTTPException(status_code=400, detail="至少需要一条菜品记录")
    meal = Meal(user_id=user.id, eaten_at=payload.eaten_at, meal_type=payload.meal_type,
                image_path=payload.image_path, note=payload.note, ai_model=payload.ai_model,
                ai_raw_json=payload.ai_raw_json, ai_latency_ms=payload.ai_latency_ms, confirmed=True,
                source=payload.source or "photo")
    _apply_items(db, meal, payload.items)
    db.add(meal)
    db.commit()
    db.refresh(meal)
    # 记忆提取钩子（fire-and-forget，失败不影响保存）
    try:
        from ..services import memory as _mem
        _mem.on_meal_saved(db, user.id, meal)
    except Exception:  # noqa: BLE001
        pass
    return _to_out(meal)


@router.get("", response_model=MealPage)
def list_meals(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    date_from: Optional[date] = Query(None, alias="from"),
    date_to: Optional[date] = Query(None, alias="to"),
    meal_type: Optional[str] = None,
    tag: Optional[str] = None,
    keyword: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
):
    q = select(Meal).where(Meal.user_id == user.id)
    if date_from:
        q = q.where(Meal.eaten_at >= datetime.combine(date_from, datetime.min.time()))
    if date_to:
        q = q.where(Meal.eaten_at < datetime.combine(date_to + timedelta(days=1), datetime.min.time()))
    if meal_type:
        q = q.where(Meal.meal_type == meal_type)
    if tag or keyword:
        sub = select(MealItem.meal_id)
        if tag:
            sub = sub.join(MealItem.tags).where(Tag.code == tag)
        if keyword:
            sub = sub.where(MealItem.name.like(f"%{keyword}%"))
        q = q.where(Meal.id.in_(sub))
    total = db.scalar(select(func.count()).select_from(q.subquery())) or 0
    rows = db.scalars(q.order_by(Meal.eaten_at.desc()).offset((page - 1) * page_size).limit(page_size)).all()
    return MealPage(total=total, page=page, page_size=page_size, items=[_to_out(m) for m in rows])


@router.get("/{meal_id}", response_model=MealOut)
def get_meal(meal_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return _to_out(_own_meal(db, meal_id, user))


@router.put("/{meal_id}", response_model=MealOut)
def update_meal(meal_id: int, payload: MealUpdate, db: Session = Depends(get_db),
                user: User = Depends(get_current_user)):
    m = _own_meal(db, meal_id, user)
    if payload.eaten_at is not None:
        m.eaten_at = payload.eaten_at
    if payload.meal_type is not None:
        m.meal_type = payload.meal_type
    if payload.note is not None:
        m.note = payload.note
    if payload.items is not None:
        if not payload.items:
            raise HTTPException(status_code=400, detail="至少保留一条菜品记录")
        _apply_items(db, m, payload.items)
    db.commit()
    db.refresh(m)
    # 记忆提取钩子（fire-and-forget）
    try:
        from ..services import memory as _mem
        _mem.on_meal_saved(db, user.id, m)
    except Exception:  # noqa: BLE001
        pass
    return _to_out(m)


@router.delete("/{meal_id}", status_code=204)
def delete_meal(meal_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    m = _own_meal(db, meal_id, user)
    db.delete(m)
    db.commit()
    return None
