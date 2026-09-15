"""
数据导入导出服务（Feature 1）。
支持 JSON / CSV / ZIP 三种格式，导入支持合并或替换模式。
所有用户面向字符串使用简体中文。
"""
import csv
import io
import json
import os
import zipfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from .. import config
from ..models import Meal, MealItem, MealPlan, Memory, Profile, Report, User
from ..services.tags import CATEGORIES, normalize_tag_codes, tag_lookup
from ..services.vision import ImageError, save_upload

# CSV 表头（UTF-8 BOM，Excel 兼容）
CSV_HEADERS = ["日期", "时间", "餐次", "菜品", "分类", "份量", "标签", "来源", "备注", "条形码"]

# 示例行（3 行）
CSV_EXAMPLE_ROWS = [
    ["2026-09-01", "08:30", "早餐", "燕麦粥", "主食", "中", "whole_grain,soup", "user", "自制早餐", ""],
    ["2026-09-01", "12:00", "午餐", "白米饭", "主食", "中", "refined_staple", "user", "", ""],
    ["2026-09-01", "12:00", "午餐", "番茄炒蛋", "蛋白质", "中", "egg,vegetable,homemade", "user", "", ""],
]


# ---------- 导出 ----------

def _profile_dict(profile: Optional[Profile]) -> Optional[Dict[str, Any]]:
    """把 Profile ORM 对象转为可序列化的字典（不含用户ID）。"""
    if profile is None:
        return None
    return {
        "persona": profile.persona,
        "gender": profile.gender,
        "birth_year": profile.birth_year,
        "height_cm": profile.height_cm,
        "weight_kg": profile.weight_kg,
        "activity_level": profile.activity_level,
        "conditions": profile.conditions,
        "medications": profile.medications,
        "allergies": profile.allergies,
        "preferences": profile.preferences,
        "tcm_constitution": profile.tcm_constitution,
        "goals": profile.goals,
        "meal_times_json": profile.meal_times_json,
        "budget_level": profile.budget_level,
        "cooking_ability": profile.cooking_ability,
        "updated_at": profile.updated_at.isoformat() if profile.updated_at else None,
    }


def _meal_dict(meal: Meal) -> Dict[str, Any]:
    """把 Meal ORM 对象转为导出字典（含 items）。"""
    items = []
    for it in meal.items:
        items.append({
            "name": it.name,
            "category": it.category,
            "portion": it.portion,
            "confidence": it.confidence,
            "source": it.source,
            "barcode": it.barcode,
            "tags": [t.code for t in it.tags],
        })
    return {
        "eaten_at": meal.eaten_at.isoformat(),
        "meal_type": meal.meal_type,
        "note": meal.note,
        "source": meal.source,
        "image_file": Path(meal.image_path).name if meal.image_path else None,
        "items": items,
    }


def _query_meals(db: Session, user_id: int,
                 from_dt: Optional[datetime], to_dt: Optional[datetime]) -> List[Meal]:
    q = db.query(Meal).filter(Meal.user_id == user_id)
    if from_dt:
        q = q.filter(Meal.eaten_at >= from_dt)
    if to_dt:
        q = q.filter(Meal.eaten_at < to_dt)
    return q.order_by(Meal.eaten_at).all()


def _query_reports(db: Session, user_id: int,
                   from_dt: Optional[datetime], to_dt: Optional[datetime]) -> List[Report]:
    q = db.query(Report).filter(Report.user_id == user_id)
    if from_dt:
        q = q.filter(Report.period_start >= from_dt)
    if to_dt:
        q = q.filter(Report.period_start < to_dt)
    return q.order_by(Report.created_at).all()


def build_export_dict(db: Session, user: User,
                      from_dt: Optional[datetime] = None,
                      to_dt: Optional[datetime] = None) -> Dict[str, Any]:
    """构建完整的 JSON 导出数据（绝不包含密码、Token、API Key）。"""
    meals = _query_meals(db, user.id, from_dt, to_dt)
    reports = _query_reports(db, user.id, from_dt, to_dt)
    profile = db.get(Profile, user.id)
    memories = (db.query(Memory)
                .filter(Memory.user_id == user.id)
                .order_by(Memory.created_at).all())
    plans = (db.query(MealPlan)
             .filter(MealPlan.user_id == user.id)
             .order_by(MealPlan.created_at).all())

    return {
        "version": "0.3",
        "exported_at": datetime.now().isoformat(),
        "user": {
            "username": user.username,
            "display_name": user.display_name,
        },
        "profile": _profile_dict(profile),
        "meals": [_meal_dict(m) for m in meals],
        "reports": [
            {
                "period_type": r.period_type,
                "period_start": r.period_start.isoformat(),
                "period_end": r.period_end.isoformat(),
                "summary_md": r.summary_md,
                "facts_json": r.facts_json,
                "created_at": r.created_at.isoformat(),
            }
            for r in reports
        ],
        "memories": [
            {
                "content": m.content,
                "category": m.category,
                "source": m.source,
                "importance": m.importance,
                "is_active": m.is_active,
                "evidence": m.evidence,
                "created_at": m.created_at.isoformat(),
            }
            for m in memories
        ],
        "meal_plans": [
            {
                "title": p.title,
                "start_date": p.start_date.isoformat(),
                "days": p.days,
                "plan_json": p.plan_json,
                "rationale_md": p.rationale_md,
                "is_active": p.is_active,
                "created_at": p.created_at.isoformat(),
            }
            for p in plans
        ],
    }


def build_csv_bytes(db: Session, user: User,
                    from_dt: Optional[datetime] = None,
                    to_dt: Optional[datetime] = None) -> bytes:
    """生成 CSV 字节流（UTF-8 with BOM，Excel 友好）。"""
    meals = _query_meals(db, user.id, from_dt, to_dt)
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(CSV_HEADERS)
    for meal in meals:
        date_str = meal.eaten_at.strftime("%Y-%m-%d")
        time_str = meal.eaten_at.strftime("%H:%M")
        for it in meal.items:
            tag_str = ",".join(t.code for t in it.tags)
            writer.writerow([
                date_str, time_str, meal.meal_type,
                it.name, it.category, it.portion,
                tag_str, it.source, meal.note or "", it.barcode or "",
            ])
    return b"\xef\xbb\xbf" + buf.getvalue().encode("utf-8")


def build_zip_bytes(db: Session, user: User,
                    from_dt: Optional[datetime] = None,
                    to_dt: Optional[datetime] = None,
                    include_images: bool = True) -> bytes:
    """生成 ZIP 字节流（data.json + images/ + README.txt）。"""
    data = build_export_dict(db, user, from_dt, to_dt)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("data.json", json.dumps(data, ensure_ascii=False, indent=2))
        # README
        readme = (
            "# 饮食日记导出包\n\n"
            "本压缩包由「今天吃得怎么样」AI 饮食观察日记导出。\n\n"
            "## 文件说明\n"
            "- data.json：所有饮食记录、报告、记忆、餐单的结构化数据\n"
            "- images/：餐食照片（仅本账号上传的图片）\n\n"
            "## 如何重新导入\n"
            "1. 登录「今天吃得怎么样」应用\n"
            "2. 进入「设置」→「数据管理」→「导入数据」\n"
            "3. 选择本 ZIP 文件或其中的 data.json 文件\n"
            "4. 选择「合并」（保留现有数据）或「替换」（清空后导入）\n"
            "5. 点击「开始导入」\n\n"
            "## 注意事项\n"
            "- 请妥善保管本文件，其中包含您的个人饮食数据\n"
            "- 本应用不提供医疗诊断，数据仅供个人参考\n"
        )
        zf.writestr("README.txt", readme.encode("utf-8").decode("utf-8"))
        # 图片
        if include_images:
            referenced = set()
            for m in data["meals"]:
                if m.get("image_file"):
                    referenced.add(m["image_file"])
            upload_dir = Path(config.UPLOAD_DIR)
            for fname in referenced:
                fpath = upload_dir / fname
                if fpath.is_file():
                    zf.write(str(fpath), f"images/{fname}")
    return buf.getvalue()


# ---------- 导入 ----------

def _parse_eaten_at(date_str: str, time_str: str) -> datetime:
    """从 日期+时间 字符串解析 datetime，精确到分钟。"""
    dt_str = f"{date_str.strip()} {time_str.strip()}"
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M"):
        try:
            return datetime.strptime(dt_str, fmt)
        except ValueError:
            continue
    raise ValueError(f"无法解析时间：{dt_str!r}")


def _meal_key(eaten_at: datetime, meal_type: str, item_names: List[str]) -> str:
    """合并去重键：精确到分钟的时间 + 餐次 + 排序后的菜名。"""
    ts = eaten_at.strftime("%Y-%m-%dT%H:%M")
    names = ",".join(sorted(item_names))
    return f"{ts}|{meal_type}|{names}"


def _existing_keys(db: Session, user_id: int) -> set:
    """加载已有餐食的去重键集合。"""
    meals = db.query(Meal).filter(Meal.user_id == user_id).all()
    keys = set()
    for m in meals:
        keys.add(_meal_key(m.eaten_at, m.meal_type, [it.name for it in m.items]))
    return keys


def _import_meal_dict(db: Session, user: User, meal_dict: Dict[str, Any],
                      lookup: Any, image_map: Optional[Dict[str, str]] = None,
                      errors: List[str] = []) -> Optional[Meal]:
    """从导出字典导入一条餐食记录，返回 Meal 对象（未 commit）。"""
    try:
        eaten_at = datetime.fromisoformat(meal_dict["eaten_at"])
    except (KeyError, ValueError) as e:
        errors.append(f"eaten_at 解析失败：{e}")
        return None

    meal_type = meal_dict.get("meal_type", "午餐")
    # 图片路径
    image_path = None
    image_file = meal_dict.get("image_file")
    if image_file and image_map:
        image_path = image_map.get(image_file)

    meal = Meal(
        user_id=user.id,
        eaten_at=eaten_at,
        meal_type=meal_type,
        note=meal_dict.get("note"),
        source=meal_dict.get("source") or "import",
        image_path=image_path,
        confirmed=True,
    )

    for it_dict in meal_dict.get("items", []):
        raw_tags = it_dict.get("tags") or []
        codes, _ = normalize_tag_codes(raw_tags, lookup)
        category = it_dict.get("category", "其他")
        if category not in CATEGORIES:
            category = "其他"
        mi = MealItem(
            name=(it_dict.get("name") or "未知").strip(),
            category=category,
            portion=it_dict.get("portion") or "中",
            confidence=it_dict.get("confidence"),
            source=it_dict.get("source") or "user",
            barcode=it_dict.get("barcode"),
        )
        mi.tags = [lookup[c] for c in codes if c in lookup]
        meal.items.append(mi)

    return meal


def import_data(db: Session, user: User,
                file_bytes: bytes, filename: str,
                mode: str = "merge") -> Dict[str, Any]:
    """
    从上传文件导入数据。
    - mode="merge"：跳过与现有记录重复的餐食
    - mode="replace"：先清除当前用户的全部餐食/报告/记忆/餐单
    返回导入统计。
    """
    errors: List[str] = []
    imported = {"meals": 0, "items": 0, "reports": 0, "memories": 0, "plans": 0, "images": 0}
    skipped = 0

    if len(file_bytes) > 50 * 1024 * 1024:
        raise ValueError("文件超过 50MB 限制")

    fname_lower = filename.lower()
    if fname_lower.endswith(".zip"):
        data, image_map = _extract_zip(file_bytes, user, errors)
        imported["images"] = len(image_map)
    elif fname_lower.endswith(".json"):
        try:
            data = json.loads(file_bytes.decode("utf-8-sig"))
        except Exception as e:
            raise ValueError(f"JSON 解析失败：{e}") from e
        image_map = {}
    elif fname_lower.endswith(".csv"):
        data = _parse_csv(file_bytes, errors)
        image_map = {}
    else:
        raise ValueError("仅支持 .json、.csv、.zip 格式")

    lookup = tag_lookup(db)

    if mode == "replace":
        # 清除当前用户数据（profile 仅当文件含 profile 时才保留/覆盖）
        db.query(MealPlan).filter(MealPlan.user_id == user.id).delete()
        db.query(Memory).filter(Memory.user_id == user.id).delete()
        db.query(Report).filter(Report.user_id == user.id).delete()
        db.query(Meal).filter(Meal.user_id == user.id).delete()
        db.commit()
        existing_keys: set = set()
    else:
        existing_keys = _existing_keys(db, user.id)

    # 导入 profile（replace 或 merge 都覆盖）
    if isinstance(data, dict) and data.get("profile"):
        _import_profile(db, user, data["profile"])

    # 导入餐食
    meals_list = data.get("meals") if isinstance(data, dict) else data.get("meals", [])
    for meal_dict in (meals_list or []):
        item_names = [it.get("name", "") for it in meal_dict.get("items", [])]
        try:
            eaten_at = datetime.fromisoformat(meal_dict["eaten_at"])
        except Exception:
            errors.append(f"跳过：eaten_at 格式无效 {meal_dict.get('eaten_at')!r}")
            skipped += 1
            continue
        key = _meal_key(eaten_at, meal_dict.get("meal_type", ""), item_names)
        if key in existing_keys:
            skipped += 1
            continue
        meal = _import_meal_dict(db, user, meal_dict, lookup, image_map, errors)
        if meal is None:
            skipped += 1
            continue
        db.add(meal)
        existing_keys.add(key)
        imported["meals"] += 1
        imported["items"] += len(meal.items)

    db.commit()

    # 导入报告
    for rep in (data.get("reports") if isinstance(data, dict) else []) or []:
        try:
            r = Report(
                user_id=user.id,
                period_type=rep.get("period_type", "week"),
                period_start=datetime.fromisoformat(rep["period_start"]),
                period_end=datetime.fromisoformat(rep["period_end"]),
                summary_md=rep.get("summary_md", ""),
                facts_json=rep.get("facts_json", "{}"),
                created_at=datetime.fromisoformat(rep["created_at"]) if rep.get("created_at") else datetime.now(),
            )
            db.add(r)
            imported["reports"] += 1
        except Exception as e:
            if len(errors) < 20:
                errors.append(f"报告导入失败：{e}")

    # 导入记忆
    for mem in (data.get("memories") if isinstance(data, dict) else []) or []:
        try:
            m = Memory(
                user_id=user.id,
                content=mem.get("content", ""),
                category=mem.get("category", "preference"),
                source=mem.get("source", "auto"),
                importance=mem.get("importance", 3),
                is_active=mem.get("is_active", True),
                evidence=mem.get("evidence"),
                created_at=datetime.fromisoformat(mem["created_at"]) if mem.get("created_at") else datetime.now(),
            )
            db.add(m)
            imported["memories"] += 1
        except Exception as e:
            if len(errors) < 20:
                errors.append(f"记忆导入失败：{e}")

    # 导入餐单
    for plan in (data.get("meal_plans") if isinstance(data, dict) else []) or []:
        try:
            p = MealPlan(
                user_id=user.id,
                title=plan.get("title", "导入餐单"),
                start_date=datetime.fromisoformat(plan["start_date"]),
                days=plan.get("days", 7),
                plan_json=plan.get("plan_json", "{}"),
                rationale_md=plan.get("rationale_md"),
                is_active=plan.get("is_active", False),
                created_at=datetime.fromisoformat(plan["created_at"]) if plan.get("created_at") else datetime.now(),
            )
            db.add(p)
            imported["plans"] += 1
        except Exception as e:
            if len(errors) < 20:
                errors.append(f"餐单导入失败：{e}")

    db.commit()

    return {"imported": imported, "skipped": skipped, "errors": errors[:20]}


def _import_profile(db: Session, user: User, profile_dict: Dict[str, Any]) -> None:
    """导入/更新用户健康档案。"""
    profile = db.get(Profile, user.id)
    if profile is None:
        profile = Profile(user_id=user.id)
        db.add(profile)
    for field in ("persona", "gender", "birth_year", "height_cm", "weight_kg",
                  "activity_level", "conditions", "medications", "allergies",
                  "preferences", "tcm_constitution", "goals", "meal_times_json",
                  "budget_level", "cooking_ability"):
        if field in profile_dict and profile_dict[field] is not None:
            setattr(profile, field, profile_dict[field])
    db.flush()


def _extract_zip(file_bytes: bytes, user: User,
                 errors: List[str]) -> Tuple[Dict[str, Any], Dict[str, str]]:
    """
    解压 ZIP，提取 data.json，把 images/ 下的图片存到 UPLOAD_DIR。
    返回 (data_dict, {原始文件名: 新存储文件名})。
    """
    image_map: Dict[str, str] = {}
    data: Dict[str, Any] = {}
    try:
        with zipfile.ZipFile(io.BytesIO(file_bytes)) as zf:
            names = zf.namelist()
            # 读 data.json
            if "data.json" in names:
                try:
                    data = json.loads(zf.read("data.json").decode("utf-8-sig"))
                except Exception as e:
                    errors.append(f"ZIP 中 data.json 解析失败：{e}")
            # 处理图片
            for name in names:
                if name.startswith("images/") and not name.endswith("/"):
                    img_bytes = zf.read(name)
                    orig_name = Path(name).name
                    try:
                        new_name = save_upload(img_bytes, orig_name)
                        image_map[orig_name] = new_name
                    except (ImageError, Exception) as e:
                        if len(errors) < 20:
                            errors.append(f"图片 {orig_name} 导入失败：{e}")
    except zipfile.BadZipFile as e:
        raise ValueError(f"无效的 ZIP 文件：{e}") from e
    return data, image_map


def _parse_csv(file_bytes: bytes, errors: List[str]) -> Dict[str, Any]:
    """
    解析 CSV（UTF-8 with or without BOM），按 日期+时间+餐次 分组为餐食。
    返回与 JSON 格式兼容的字典（只含 meals）。
    """
    text = file_bytes.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))

    # 按 (日期, 时间, 餐次) 分组
    groups: Dict[Tuple, List[Dict]] = {}
    row_num = 1
    for row in reader:
        row_num += 1
        date_str = row.get("日期", "").strip()
        time_str = row.get("时间", "").strip()
        meal_type = row.get("餐次", "午餐").strip()
        name = row.get("菜品", "").strip()
        if not name:
            continue
        key_tuple = (date_str, time_str, meal_type)
        if key_tuple not in groups:
            groups[key_tuple] = []
        groups[key_tuple].append({
            "name": name,
            "category": row.get("分类", "其他").strip() or "其他",
            "portion": row.get("份量", "中").strip() or "中",
            "tags": [t.strip() for t in row.get("标签", "").split(",") if t.strip()],
            "source": row.get("来源", "user").strip() or "user",
            "barcode": row.get("条形码", "").strip() or None,
            "_note": row.get("备注", "").strip(),
        })

    meals = []
    for (date_str, time_str, meal_type), items in groups.items():
        try:
            eaten_at = _parse_eaten_at(date_str, time_str)
        except ValueError as e:
            if len(errors) < 20:
                errors.append(str(e))
            continue
        note = items[0].get("_note") if items else None
        clean_items = [{k: v for k, v in it.items() if k != "_note"} for it in items]
        meals.append({
            "eaten_at": eaten_at.isoformat(),
            "meal_type": meal_type,
            "note": note,
            "source": "import",
            "image_file": None,
            "items": clean_items,
        })

    return {"meals": meals, "reports": [], "memories": [], "meal_plans": [], "profile": None}


def user_summary(db: Session, user_id: int) -> Dict[str, int]:
    """各表该用户的数据量（前端信息展示用）。"""
    return {
        "meals": db.query(Meal).filter(Meal.user_id == user_id).count(),
        "reports": db.query(Report).filter(Report.user_id == user_id).count(),
        "memories": db.query(Memory).filter(Memory.user_id == user_id).count(),
        "meal_plans": db.query(MealPlan).filter(MealPlan.user_id == user_id).count(),
        "profile": 1 if db.get(Profile, user_id) else 0,
    }
