"""
条形码路由（Feature 2）。
前缀：/api/barcode
所有端点需要登录（每个端点声明 Depends(get_current_user)）。
"""
import json
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import get_current_user
from ..models import Meal, MealItem, PackagedFood, User
from ..routers.meals import _apply_items
from ..schemas import MealItemIn
from ..services import barcode as barcode_svc

router = APIRouter(prefix="/api/barcode", tags=["barcode"])


# ---------- 请求 / 响应 schema ----------

class BarcodeManualIn(BaseModel):
    """手动录入/更新商品信息。"""
    name: str = Field(..., min_length=1, max_length=120, description="商品名称（必填）")
    brand: Optional[str] = Field(None, max_length=80)
    category: Optional[str] = Field(None, max_length=20)
    tags: Optional[List[str]] = Field(None, description="标签 code 列表")
    nutriments: Optional[Dict[str, Any]] = Field(None, description="营养数据字典")


class BarcodeLogIn(BaseModel):
    """通过条形码快速记录一餐。"""
    meal_type: str = Field(..., description="餐次（早餐/午餐/晚餐/加餐/饮品）")
    eaten_at: Optional[datetime] = Field(None, description="进食时间，默认当前时间")
    portion: Optional[str] = Field("中", description="份量（少/中/多）")
    note: Optional[str] = Field(None, max_length=500)


# ---------- 端点 ----------

@router.get("/recent")
def recent_barcodes(
    limit: int = 30,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """返回该用户最近扫过的 30 个商品（通过 MealItem.barcode 关联）。"""
    # 找该用户所有有 barcode 的 MealItem，按所属 Meal.eaten_at 倒序
    stmt = (
        select(MealItem.barcode)
        .join(Meal, MealItem.meal_id == Meal.id)
        .where(Meal.user_id == user.id)
        .where(MealItem.barcode.isnot(None))
        .order_by(Meal.eaten_at.desc())
        .limit(limit * 3)  # 多取一些去重
    )
    barcodes_used = list(db.scalars(stmt).all())
    seen = []
    for bc in barcodes_used:
        if bc not in seen:
            seen.append(bc)
        if len(seen) >= limit:
            break

    if not seen:
        return []

    # 查 PackagedFood 缓存
    pf_map = {
        pf.barcode: pf
        for pf in db.query(PackagedFood).filter(PackagedFood.barcode.in_(seen)).all()
    }

    results = []
    for bc in seen:
        pf = pf_map.get(bc)
        if pf:
            results.append(barcode_svc._build_product_dict(pf))
        else:
            results.append({"barcode": bc, "name": bc, "brand": None, "category": "其他",
                            "tags": [], "image_url": None, "nutriments": None})
    return results


@router.get("/{code}")
def lookup_barcode(
    code: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """查询条形码商品信息（本地缓存 → OFF → 内置兜底表）。"""
    try:
        barcode_svc.validate_barcode(code)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    result = barcode_svc.get_barcode_info(db, code)
    return result


@router.put("/{code}")
def upsert_barcode(
    code: str,
    payload: BarcodeManualIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """手动录入或更新商品信息（source=manual，优先于 OFF）。"""
    try:
        barcode_svc.validate_barcode(code)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # 规范化标签
    from ..services.tags import tag_lookup, normalize_tag_codes
    lookup = tag_lookup(db)
    raw_tags = payload.tags or []
    valid_codes, _ = normalize_tag_codes(raw_tags, lookup)

    parsed = {
        "name": payload.name,
        "brand": payload.brand,
        "category": payload.category or "其他",
        "tags": valid_codes,
        "nutriments_dict": payload.nutriments or {},
        "image_url": None,
        "raw_json_str": None,
    }
    pf = barcode_svc.store_in_cache(db, code, parsed, source="manual", created_by=user.id)
    product = barcode_svc._build_product_dict(pf)
    return {
        "found": True,
        "source": "manual",
        "product": product,
        "suggested_item": barcode_svc._make_suggested_item(product),
    }


@router.post("/{code}/log", status_code=201)
def log_barcode_meal(
    code: str,
    payload: BarcodeLogIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """通过条形码快速记录一餐（条形码必须已在缓存中，否则 404）。"""
    try:
        barcode_svc.validate_barcode(code)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    pf = barcode_svc.lookup_cache(db, code)
    if pf is None:
        raise HTTPException(status_code=404, detail=f"未找到条形码 {code} 的商品信息，请先查询或手动录入")

    tags_list: List[str] = []
    if pf.tags:
        try:
            tags_list = json.loads(pf.tags)
        except Exception:
            tags_list = []

    eaten_at = payload.eaten_at or datetime.now()

    meal = Meal(
        user_id=user.id,
        eaten_at=eaten_at,
        meal_type=payload.meal_type,
        note=payload.note,
        source="barcode",
        confirmed=True,
    )
    db.add(meal)
    db.flush()  # 获取 meal.id

    # 有商品图时一并写入餐次（时间线直接显示商品图，而不是占位图）
    if pf.image_url and pf.image_url.startswith("/uploads/"):
        meal.image_path = pf.image_url[len("/uploads/"):]

    item_in = MealItemIn(
        name=pf.name,
        category=pf.category,
        portion=payload.portion or "中",
        tags=tags_list,
        source="barcode",
        barcode=code,
    )
    _apply_items(db, meal, [item_in])

    db.commit()
    db.refresh(meal)

    from ..routers.meals import _to_out
    return _to_out(meal)
