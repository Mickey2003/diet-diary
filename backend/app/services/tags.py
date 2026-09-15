"""标签字典与分类常量。所有 AI 输出的标签必须落在这里定义的范围内。"""
from typing import Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from ..models import Tag

CATEGORIES: List[str] = ["主食", "蛋白质", "蔬菜", "水果", "饮品", "甜点零食", "汤", "其他"]
MEAL_TYPES: List[str] = ["早餐", "午餐", "晚餐", "加餐", "饮品"]
PORTIONS: List[str] = ["少", "中", "多"]

# code, 中文名, 分组, 是否为“关注项”, 说明
TAG_DEFS = [
    # 关注项（需要留意的饮食特征）
    ("sugary_drink", "含糖饮料", "watch", True, "奶茶、可乐、果汁等含糖饮品"),
    ("fried", "油炸", "watch", True, "炸鸡、薯条、油条等油炸食品"),
    ("high_salt", "高盐", "watch", True, "腌制、重口味、酱料多的食物"),
    ("processed_meat", "加工肉", "watch", True, "香肠、培根、午餐肉等"),
    ("alcohol", "酒精", "watch", True, "啤酒、白酒、鸡尾酒等"),
    ("takeout", "外卖", "watch", True, "外卖或快餐包装明显"),
    ("sweet", "高糖甜食", "watch", True, "蛋糕、奶油、糖果等"),
    ("late_night", "夜宵", "watch", True, "深夜进食"),
    ("refined_staple", "精制主食", "watch", False, "白米饭、白面条、白面包等"),
    # 结构项（帮助观察饮食是否均衡）
    ("whole_grain", "全谷物", "structure", False, "燕麦、糙米、全麦、杂粮"),
    ("leafy_veg", "绿叶菜", "structure", False, "青菜、菠菜、生菜等"),
    ("vegetable", "蔬菜", "structure", False, "各类蔬菜"),
    ("fruit", "水果", "structure", False, "各类水果"),
    ("soy", "豆制品", "structure", False, "豆腐、豆浆、豆干等"),
    ("dairy", "奶制品", "structure", False, "牛奶、酸奶、奶酪"),
    ("egg", "蛋类", "structure", False, "鸡蛋等"),
    ("seafood", "水产", "structure", False, "鱼虾贝类"),
    ("poultry", "禽肉", "structure", False, "鸡肉、鸭肉"),
    ("red_meat", "红肉", "structure", False, "猪肉、牛肉、羊肉"),
    ("nuts", "坚果", "structure", False, "花生、核桃、杏仁等"),
    ("high_protein", "高蛋白", "structure", False, "蛋白质来源明显"),
    ("light", "清淡", "structure", False, "少油少盐"),
    ("spicy", "辛辣", "structure", False, "辣味明显"),
    ("homemade", "自制", "structure", False, "看起来是家里或食堂做的"),
    ("sugar_free_drink", "无糖饮品", "structure", False, "水、茶、黑咖啡、无糖饮料"),
    ("soup", "汤类", "structure", False, "汤、粥等流食"),
]


def ensure_tags(db: Session) -> None:
    existing = {t.code for t in db.query(Tag).all()}
    for code, name, group, is_watch, desc in TAG_DEFS:
        if code not in existing:
            db.add(Tag(code=code, name_zh=name, group=group, is_watch=is_watch, description=desc))


def tag_lookup(db: Session) -> Dict[str, Tag]:
    """返回 code 和中文名都能索引到 Tag 的字典。"""
    lookup: Dict[str, Tag] = {}
    for t in db.query(Tag).all():
        lookup[t.code] = t
        lookup[t.name_zh] = t
    return lookup


def normalize_tag_codes(raw: List[str], lookup: Dict[str, Tag]) -> Tuple[List[str], List[str]]:
    """把模型返回的标签（可能是 code、中文名或杂项）映射为合法 code；返回 (合法 code 列表, 被丢弃的原始值)。"""
    codes: List[str] = []
    dropped: List[str] = []
    for r in raw or []:
        key = (r or "").strip()
        tag: Optional[Tag] = lookup.get(key)
        if tag is None:
            # 模糊匹配：中文名包含关系
            for k, v in lookup.items():
                if key and (key in k or k in key) and len(key) >= 2:
                    tag = v
                    break
        if tag and tag.code not in codes:
            codes.append(tag.code)
        elif tag is None and key:
            dropped.append(key)
    return codes, dropped
