"""
演示数据：生成最近 N 天的模拟餐食记录与占位图片。
用法：
    python -m app.seed            # 追加约 14 天数据（若已有数据则跳过）
    python -m app.seed --reset    # 清空 meals 后重新生成
    python -m app.seed --days 30
"""
import argparse
import random
from datetime import datetime, timedelta
from pathlib import Path

from PIL import Image, ImageDraw

from . import config
from .db import SessionLocal, init_db
from .models import Meal, MealItem, QueryLog, Report, meal_item_tags
from .services.tags import tag_lookup
from .services.timeutil import today_local

# (菜名, 分类, 份量, 标签)
MENU = {
    "早餐": [
        [("燕麦粥", "主食", "中", ["whole_grain", "soup"]), ("水煮蛋", "蛋白质", "少", ["egg", "high_protein"]), ("香蕉", "水果", "少", ["fruit"])],
        [("肉包子", "主食", "中", ["refined_staple", "red_meat"]), ("豆浆", "饮品", "中", ["soy", "sugar_free_drink"])],
        [("油条", "主食", "中", ["fried", "refined_staple"]), ("甜豆浆", "饮品", "中", ["soy", "sugary_drink"])],
        [("全麦面包", "主食", "中", ["whole_grain"]), ("牛奶", "饮品", "中", ["dairy"]), ("煎蛋", "蛋白质", "少", ["egg"])],
        [("小笼包", "主食", "中", ["refined_staple", "red_meat"]), ("紫菜蛋花汤", "汤", "中", ["soup", "egg", "light"])],
    ],
    "午餐": [
        [("番茄炒蛋", "蛋白质", "中", ["egg", "vegetable", "homemade"]), ("白米饭", "主食", "中", ["refined_staple"]), ("清炒西兰花", "蔬菜", "中", ["vegetable", "light"])],
        [("黄焖鸡米饭", "蛋白质", "多", ["poultry", "takeout", "high_salt"]), ("白米饭", "主食", "中", ["refined_staple"])],
        [("麻辣香锅", "其他", "多", ["spicy", "high_salt", "takeout"]), ("可乐", "饮品", "中", ["sugary_drink"])],
        [("红烧肉", "蛋白质", "中", ["red_meat", "high_salt"]), ("蒜蓉青菜", "蔬菜", "中", ["leafy_veg", "vegetable"]), ("米饭", "主食", "中", ["refined_staple"])],
        [("清蒸鱼", "蛋白质", "中", ["seafood", "light", "high_protein"]), ("凉拌黄瓜", "蔬菜", "少", ["vegetable", "light"]), ("杂粮饭", "主食", "中", ["whole_grain"])],
        [("牛肉面", "主食", "多", ["refined_staple", "red_meat", "soup"])],
    ],
    "晚餐": [
        [("鸡胸肉沙拉", "蛋白质", "中", ["poultry", "leafy_veg", "light", "high_protein"])],
        [("炸鸡", "蛋白质", "中", ["fried", "poultry", "takeout"]), ("薯条", "主食", "中", ["fried"]), ("珍珠奶茶", "饮品", "多", ["sugary_drink"])],
        [("麻婆豆腐", "蛋白质", "中", ["soy", "spicy"]), ("米饭", "主食", "中", ["refined_staple"]), ("炒空心菜", "蔬菜", "中", ["leafy_veg", "vegetable"])],
        [("水饺", "主食", "多", ["refined_staple", "red_meat"]), ("醋", "其他", "少", [])],
        [("烤肉", "蛋白质", "多", ["red_meat", "high_salt"]), ("啤酒", "饮品", "中", ["alcohol"])],
        [("番茄牛腩汤", "汤", "中", ["soup", "red_meat", "vegetable"]), ("馒头", "主食", "中", ["refined_staple"])],
    ],
    "加餐": [
        [("奶茶", "饮品", "中", ["sugary_drink"])],
        [("苹果", "水果", "少", ["fruit"])],
        [("薯片", "甜点零食", "少", ["high_salt"])],
        [("酸奶", "饮品", "少", ["dairy"])],
        [("蛋糕", "甜点零食", "少", ["sweet"])],
        [("烧烤", "蛋白质", "中", ["red_meat", "high_salt", "late_night", "takeout"]), ("啤酒", "饮品", "中", ["alcohol", "late_night"])],
        [("坚果", "甜点零食", "少", ["nuts"])],
    ],
}

HOURS = {"早餐": (7, 9), "午餐": (11, 13), "晚餐": (18, 20), "加餐": (15, 23)}
COLORS = {"早餐": (255, 214, 153), "午餐": (170, 220, 170), "晚餐": (170, 190, 240), "加餐": (240, 180, 200)}


def _placeholder_image(meal_type: str, names: str) -> str:
    Path(config.UPLOAD_DIR).mkdir(parents=True, exist_ok=True)
    fname = f"seed_{meal_type}_{abs(hash(names)) % 10_000_000}.jpg"
    path = Path(config.UPLOAD_DIR) / fname
    if not path.exists():
        img = Image.new("RGB", (640, 480), COLORS.get(meal_type, (200, 200, 200)))
        d = ImageDraw.Draw(img)
        d.ellipse((120, 90, 520, 400), fill=(250, 250, 245), outline=(120, 120, 120), width=4)
        d.ellipse((200, 160, 440, 330), fill=COLORS.get(meal_type), outline=(90, 90, 90), width=2)
        d.text((20, 20), f"seed demo image ({meal_type})", fill=(40, 40, 40))
        img.save(path, "JPEG", quality=80)
    return fname


def seed(days: int = 14, reset: bool = False) -> int:
    init_db()
    random.seed(42)
    created = 0
    with SessionLocal() as db:
        if reset:
            db.execute(meal_item_tags.delete())
            db.query(MealItem).delete()
            db.query(Meal).delete()
            db.query(Report).delete()
            db.query(QueryLog).delete()
            db.commit()
        elif db.query(Meal).count() > 0:
            print("已有餐食数据，跳过生成。若要重建请加 --reset")
            return 0
        lookup = tag_lookup(db)
        today = today_local()
        from .models import User
        admin = db.query(User).filter(User.role == "admin").order_by(User.id).first() or db.query(User).order_by(User.id).first()
        uid = admin.id if admin else None
        for offset in range(days, -1, -1):
            d = today - timedelta(days=offset)
            if random.random() < 0.12:  # 偶尔漏记一天，便于展示“空缺天数”
                continue
            for meal_type in ("早餐", "午餐", "晚餐"):
                if random.random() < 0.1:
                    continue
                items = random.choice(MENU[meal_type])
                h0, h1 = HOURS[meal_type]
                eaten = datetime.combine(d, datetime.min.time()) + timedelta(hours=random.randint(h0, h1), minutes=random.randint(0, 59))
                names = "、".join(i[0] for i in items)
                m = Meal(user_id=uid, eaten_at=eaten, meal_type=meal_type, image_path=_placeholder_image(meal_type, names),
                         note=None, ai_model="seed", confirmed=True)
                for idx, (name, cat, portion, tags) in enumerate(items):
                    src = random.choice(["ai", "ai", "ai_edited", "user"])
                    mi = MealItem(name=name, category=cat, portion=portion, confidence=round(random.uniform(0.6, 0.95), 2),
                                  source=src, sort_order=idx)
                    mi.tags = [lookup[t] for t in tags if t in lookup]
                    m.items.append(mi)
                db.add(m)
                created += 1
            if random.random() < 0.55:
                items = random.choice(MENU["加餐"])
                is_late = any("late_night" in i[3] for i in items)
                hour = random.randint(22, 23) if is_late else random.randint(15, 17)
                eaten = datetime.combine(d, datetime.min.time()) + timedelta(hours=hour, minutes=random.randint(0, 59))
                names = "、".join(i[0] for i in items)
                m = Meal(user_id=uid, eaten_at=eaten, meal_type="加餐", image_path=_placeholder_image("加餐", names), ai_model="seed")
                for idx, (name, cat, portion, tags) in enumerate(items):
                    mi = MealItem(name=name, category=cat, portion=portion, confidence=0.8, source="ai", sort_order=idx)
                    mi.tags = [lookup[t] for t in tags if t in lookup]
                    m.items.append(mi)
                db.add(m)
                created += 1
        db.commit()
    print(f"已生成 {created} 条餐食记录")
    return created


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=14)
    ap.add_argument("--reset", action="store_true")
    a = ap.parse_args()
    seed(a.days, a.reset)
