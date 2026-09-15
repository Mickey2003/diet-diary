"""
条形码商品查询服务（Feature 2）。
优先查本地 PackagedFood 缓存；命中 manual 来源的记录优先于 openfoodfacts。
未命中时查询 Open Food Facts v2 API 并缓存结果。
内置几个常见中国商品兜底表，网络不通时使用。
"""
import json
import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List, Optional, Tuple

import httpx
from sqlalchemy.orm import Session

from ..models import PackagedFood
from . import dish_image, net_proxy
from .tags import TAG_DEFS

# 合法的标签 code 集合（从 tags.py 读取，不自造新 code）
VALID_TAG_CODES = {code for code, *_ in TAG_DEFS}

OFF_API_URL = "https://world.openfoodfacts.org/api/v2/product/{code}.json"
OFF_FIELDS = "code,product_name,product_name_zh,brands,categories_tags,nutriments,image_front_small_url,quantity"
OFF_USER_AGENT = "DietDiary/0.8 (diet-diary course project)"
OFF_TIMEOUT = 8.0

# ---------- 补充数据源（在 OFF 未命中时依次尝试） ----------
# UPCitemdb 免费试用接口（无需密钥，有每日额度）
UPC_API_URL = "https://api.upcitemdb.com/prod/trial/lookup"
# USDA FoodData Central（gtinUpc 检索，DEMO_KEY 可直接用，可用 USDA_API_KEY 覆盖）
USDA_API_URL = "https://api.nal.usda.gov/fdc/v1/foods/search"
USDA_API_KEY = os.getenv("USDA_API_KEY", "DEMO_KEY")
# 国内免费条码接口（国内可直连，无需密钥）
VVHAN_API_URL = "https://api.vvhan.com/api/barcode"
OIOWEB_API_URL = "https://api.oioweb.cn/api/common/BarCode"
EXTRA_TIMEOUT = 6.0

# ---------- 内置兜底表（当 OFF 不通或 mock 模式时使用） ----------
_BUILTIN: Dict[str, Dict[str, Any]] = {
    "6921168509256": {
        "name": "农夫山泉饮用天然水 550ml",
        "brand": "农夫山泉",
        "category": "饮品",
        "tags": ["sugar_free_drink"],
        "image_url": None,
        "nutriments": None,
        "quantity": "550ml",
    },
    "6928804011142": {
        "name": "可口可乐 330ml",
        "brand": "可口可乐",
        "category": "饮品",
        "tags": ["sugary_drink"],
        "image_url": None,
        "nutriments": {"sugars_100g": 10.6, "energy_kcal_100g": 42},
        "quantity": "330ml",
    },
    "6902083881405": {
        "name": "娃哈哈AD钙奶 220ml",
        "brand": "娃哈哈",
        "category": "饮品",
        "tags": ["sugary_drink", "dairy"],
        "image_url": None,
        "nutriments": {"sugars_100g": 10.0, "dairy": True},
        "quantity": "220ml",
    },
    "6920152400487": {
        "name": "康师傅红烧牛肉面 100g",
        "brand": "康师傅",
        "category": "主食",
        "tags": ["high_salt", "refined_staple"],
        "image_url": None,
        "nutriments": {"salt_100g": 2.1},
        "quantity": "100g",
    },
    "6901939621608": {
        "name": "奥利奥夹心饼干 97g",
        "brand": "奥利奥",
        "category": "甜点零食",
        "tags": ["sweet"],
        "image_url": None,
        "nutriments": {"sugars_100g": 36.0, "fat_100g": 18.0},
        "quantity": "97g",
    },
}


def validate_barcode(code: str) -> None:
    """校验条形码：8~14 位数字，否则抛出 ValueError。"""
    if not re.match(r"^\d{8,14}$", code):
        raise ValueError(f"条形码格式无效：{code!r}，应为 8~14 位数字")


def _map_category(categories_tags: List[str], name: str) -> str:
    """根据 Open Food Facts 分类标签和名称，映射到应用内分类。"""
    cat_str = " ".join(categories_tags).lower()
    name_lower = name.lower()

    # 饮品类（先判断，避免含奶的零食误归饮品）
    beverage_kw = ["beverages", "drinks", "juice", "tea", "coffee", "water", "milk", "yogurt",
                   "beer", "wine", "spirits", "soda", "cola", "饮料", "饮品", "水", "茶", "奶", "酸奶"]
    if any(kw in cat_str or kw in name_lower for kw in beverage_kw):
        # 奶酪单独归蛋白质
        if "cheese" in cat_str or "奶酪" in name_lower:
            return "蛋白质"
        return "饮品"

    # 甜点零食（先于主食判断，避免 biscuit/crackers 误归主食）
    snack_kw = ["snacks", "chocolate", "candy", "biscuit", "cookie", "chips", "crisps",
                "wafer", "cake", "pastry", "甜点", "零食", "巧克力", "糖果", "薯片", "饼干"]
    if any(kw in cat_str or kw in name_lower for kw in snack_kw):
        return "甜点零食"

    # 坚果单独归甜点零食
    nuts_kw = ["nuts", "nut", "peanut", "almond", "walnut", "cashew", "坚果", "花生", "杏仁", "核桃"]
    if any(kw in cat_str or kw in name_lower for kw in nuts_kw):
        return "甜点零食"

    # 主食类（排除已归入甜点的 biscuit/crackers）
    staple_kw = ["noodles", "instant", "bread", "rice", "pasta", "cereal", "flour",
                 "面", "米", "饭", "面包", "方便"]
    if any(kw in cat_str or kw in name_lower for kw in staple_kw):
        return "主食"

    # 蛋白质
    protein_kw = ["meat", "fish", "seafood", "egg", "tofu", "soy", "protein", "chicken", "beef", "pork",
                  "肉", "鱼", "蛋", "豆腐", "蛋白"]
    if any(kw in cat_str or kw in name_lower for kw in protein_kw):
        return "蛋白质"

    return "其他"


def _map_tags(categories_tags: List[str], name: str, nutriments: Dict[str, Any],
              category: str) -> List[str]:
    """根据分类标签、营养数据映射到合法标签 code 列表（只使用 VALID_TAG_CODES 中存在的）。"""
    tags: List[str] = []
    cat_str = " ".join(categories_tags).lower()
    name_lower = name.lower()
    nut = nutriments or {}

    # 营养素
    sugars = nut.get("sugars_100g")
    salt = nut.get("salt_100g")

    if category == "饮品" and sugars is not None and sugars >= 5:
        _add(tags, "sugary_drink")
    if category != "饮品" and sugars is not None and sugars >= 15:
        _add(tags, "sweet")
    if salt is not None and salt >= 1.5:
        _add(tags, "high_salt")

    # 分类特征
    if "fried" in cat_str or "薯片" in name_lower or "炸" in name_lower:
        _add(tags, "fried")

    # 酒精：注意 Open Food Facts 的 "en:non-alcoholic-beverages" 也包含 "alcohol" 字样，需先排除
    cat_no_nonalc = cat_str.replace("non-alcoholic", "").replace("alcohol-free", "").replace("无酒精", "")
    name_no_nonalc = name_lower.replace("无酒精", "").replace("non-alcoholic", "")
    alcohol_kw = ["alcohol", "beer", "wine", "spirits", "liquor", "baijiu", "啤酒", "白酒", "红酒", "葡萄酒", "黄酒", "鸡尾酒", "威士忌"]
    if any(kw in cat_no_nonalc or kw in name_no_nonalc for kw in alcohol_kw):
        _add(tags, "alcohol")

    # 能量饮料通常含糖：按含糖饮料处理（不是酒精）
    energy_kw = ["energy-drink", "energy drink", "功能饮料", "能量饮料"]
    if any(kw in cat_str or kw in name_lower for kw in energy_kw) and category == "饮品":
        _add(tags, "sugary_drink")

    # 奶制品
    dairy_kw = ["dairy", "milk", "yogurt", "cheese", "lactose", "牛奶", "奶", "酸奶", "奶酪"]
    if any(kw in cat_str or kw in name_lower for kw in dairy_kw):
        _add(tags, "dairy")

    # 坚果
    nuts_kw = ["nuts", "peanut", "almond", "walnut", "cashew", "坚果", "花生", "杏仁", "核桃"]
    if any(kw in cat_str or kw in name_lower for kw in nuts_kw):
        _add(tags, "nuts")

    # 无糖饮品
    if category == "饮品" and "sugary_drink" not in tags:
        no_sugar_kw = ["sugar-free", "zero sugar", "无糖", "water", "tea", "green tea"]
        if any(kw in cat_str or kw in name_lower for kw in no_sugar_kw):
            _add(tags, "sugar_free_drink")

    return tags


def _add(tags: List[str], code: str) -> None:
    """安全地添加标签（仅合法 code，不重复）。"""
    if code in VALID_TAG_CODES and code not in tags:
        tags.append(code)


def _nutriments_from_raw(raw_nut: Dict[str, Any]) -> Dict[str, Any]:
    """从 OFF nutriments 字典提取我们关心的字段（允许 null）。"""
    def _f(key: str) -> Optional[float]:
        v = raw_nut.get(key)
        try:
            return float(v) if v is not None else None
        except (TypeError, ValueError):
            return None

    return {
        "energy_kcal_100g": _f("energy-kcal_100g") or _f("energy_kcal_100g"),
        "sugars_100g": _f("sugars_100g"),
        "salt_100g": _f("salt_100g"),
        "fat_100g": _f("fat_100g"),
        "proteins_100g": _f("proteins_100g"),
        "carbohydrates_100g": _f("carbohydrates_100g"),
    }


def _build_product_dict(pf: PackagedFood) -> Dict[str, Any]:
    """把 PackagedFood ORM 对象转为响应用的 product 字典。"""
    nutriments = None
    if pf.nutriments_json:
        try:
            nutriments = json.loads(pf.nutriments_json)
        except Exception:
            nutriments = None
    tags_list: List[str] = []
    if pf.tags:
        try:
            tags_list = json.loads(pf.tags)
        except Exception:
            tags_list = []
    return {
        "barcode": pf.barcode,
        "name": pf.name,
        "brand": pf.brand,
        "category": pf.category,
        "tags": tags_list,
        "image_url": pf.image_url,
        "nutriments": nutriments,
        "quantity": None,  # PackagedFood 模型无 quantity 列，忽略
    }


def _make_suggested_item(product: Dict[str, Any]) -> Dict[str, Any]:
    """根据商品信息生成建议录入条目（含按营养成分表换算的估算热量）。"""
    from .kcal import estimate_kcal, kcal_from_nutriments
    nutr = product.get("nutriments") or {}
    kcal = kcal_from_nutriments(nutr.get("energy_kcal_100g"), product.get("quantity") or nutr.get("quantity"))
    kcal_source = "barcode"
    if kcal is None:
        kcal, kcal_source = estimate_kcal(product["name"], product["category"], "中")
    return {
        "name": product["name"],
        "category": product["category"],
        "portion": "中",
        "tags": product.get("tags") or [],
        "source": "barcode",
        "barcode": product["barcode"],
        "kcal": kcal,
        "kcal_source": kcal_source,
    }


def lookup_cache(db: Session, code: str) -> Optional[PackagedFood]:
    """
    查本地缓存：manual 来源优先于 openfoodfacts。
    """
    rows = db.query(PackagedFood).filter(PackagedFood.barcode == code).all()
    if not rows:
        return None
    # manual 优先
    for r in rows:
        if r.source == "manual":
            return r
    return rows[0]


def fetch_openfoodfacts(code: str, db=None) -> Optional[Dict[str, Any]]:
    """
    查询 Open Food Facts v2 API。
    返回解析好的产品字典，或 None（未找到或网络错误时）。
    网络/超时异常不向上抛，由调用方捕获 error 字段。
    """
    url = net_proxy.wrap(OFF_API_URL.format(code=code), db)
    try:
        resp = httpx.get(
            url,
            params={"fields": OFF_FIELDS},
            headers={"User-Agent": OFF_USER_AGENT},
            timeout=OFF_TIMEOUT,
            follow_redirects=True,
        )
        if resp.status_code != 200:
            return None
        data = resp.json()
        if data.get("status") != 1:
            return None
        return data.get("product") or {}
    except Exception:  # noqa: BLE001
        raise  # 由调用方处理


def _parse_off_product(code: str, product: Dict[str, Any]) -> Dict[str, Any]:
    """
    把 OFF 原始 product 字典解析为我们的内部格式：
    {name, brand, category, tags, nutriments_dict, image_url, quantity, raw_json_str}
    """
    name = (
        product.get("product_name_zh")
        or product.get("product_name")
        or product.get("brands")
        or code
    )
    brand = product.get("brands") or None
    categories_tags = product.get("categories_tags") or []
    raw_nut = product.get("nutriments") or {}
    image_url = product.get("image_front_small_url") or None
    quantity = product.get("quantity") or None

    category = _map_category(categories_tags, name)
    nut_dict = _nutriments_from_raw(raw_nut)
    tags = _map_tags(categories_tags, name, nut_dict, category)

    raw_json_str = json.dumps(product, ensure_ascii=False)
    if len(raw_json_str) > 20000:
        raw_json_str = raw_json_str[:20000]

    return {
        "name": name,
        "brand": brand,
        "category": category,
        "tags": tags,
        "nutriments_dict": nut_dict,
        "image_url": image_url,
        "quantity": quantity,
        "raw_json_str": raw_json_str,
    }


# ---------- 补充数据源：UPCitemdb ----------

def fetch_upcitemdb(code: str, db=None) -> Optional[Dict[str, Any]]:
    """查询 UPCitemdb 免费试用接口，返回首个商品 dict 或 None。"""
    resp = httpx.get(
        net_proxy.wrap(UPC_API_URL, db),
        params={"upc": code},
        headers={"User-Agent": OFF_USER_AGENT, "Accept": "application/json"},
        timeout=EXTRA_TIMEOUT,
        follow_redirects=True,
    )
    if resp.status_code != 200:
        return None
    items = resp.json().get("items") or []
    return items[0] if items else None


def _parse_upc_product(code: str, item: Dict[str, Any]) -> Dict[str, Any]:
    """把 UPCitemdb 商品解析为内部格式。"""
    name = item.get("title") or code
    brand = item.get("brand") or None
    cats = [item.get("category") or "", item.get("category") or ""]
    images = item.get("images") or []
    image_url = images[0] if images else None
    category = _map_category(cats, name)
    nut_dict: Dict[str, Any] = {}
    tags = _map_tags(cats, name, nut_dict, category)
    raw_json_str = json.dumps(item, ensure_ascii=False)[:20000]
    return {
        "name": name,
        "brand": brand,
        "category": category,
        "tags": tags,
        "nutriments_dict": nut_dict,
        "image_url": image_url,
        "quantity": None,
        "raw_json_str": raw_json_str,
    }


# ---------- 补充数据源：USDA FoodData Central ----------

def fetch_usda(code: str, db=None) -> Optional[Dict[str, Any]]:
    """在 USDA FoodData Central 按 GTIN/UPC 检索，返回首个 food dict 或 None。"""
    resp = httpx.get(
        net_proxy.wrap(USDA_API_URL, db),
        params={"query": code, "dataType": "Branded", "pageSize": 1, "api_key": USDA_API_KEY},
        headers={"User-Agent": OFF_USER_AGENT},
        timeout=EXTRA_TIMEOUT,
        follow_redirects=True,
    )
    if resp.status_code != 200:
        return None
    foods = resp.json().get("foods") or []
    return foods[0] if foods else None


def _parse_usda_product(code: str, food: Dict[str, Any]) -> Dict[str, Any]:
    """把 USDA food 解析为内部格式（营养按每 100g 尽力换算）。"""
    name = food.get("description") or code
    brand = food.get("brandOwner") or food.get("brandName") or None
    cats = [food.get("foodCategory") or ""]
    image_url = None  # USDA 无稳定图片字段

    nut: Dict[str, Any] = {}
    for fn in food.get("foodNutrients") or []:
        nm = (fn.get("nutrientName") or fn.get("name") or "").lower()
        unit = (fn.get("unitName") or "").upper()
        val = fn.get("value")
        if val is None and isinstance(fn.get("amount"), (int, float)):
            val = fn.get("amount")
        try:
            val = float(val) if val is not None else None
        except (TypeError, ValueError):
            val = None
        if val is None:
            continue
        if "energy" in nm and "kcal" in unit.lower():
            nut.setdefault("energy_kcal_100g", val)
        elif "protein" in nm:
            nut.setdefault("proteins_100g", val)
        elif "carbohydrate" in nm:
            nut.setdefault("carbohydrates_100g", val)
        elif "total lipid" in nm or nm.strip() == "fat":
            nut.setdefault("fat_100g", val)
        elif "sugars" in nm or nm.strip() == "sugars, total":
            nut.setdefault("sugars_100g", val)
        elif "sodium" in nm and unit.startswith("MG"):
            nut.setdefault("salt_100g", round(val * 2.5 / 1000, 3))  # 钠(mg) → 盐(g)/100g

    category = _map_category(cats, name)
    tags = _map_tags(cats, name, nut, category)
    raw_json_str = json.dumps(food, ensure_ascii=False)[:20000]
    return {
        "name": name,
        "brand": brand,
        "category": category,
        "tags": tags,
        "nutriments_dict": nut,
        "image_url": image_url,
        "quantity": food.get("servingSize") and str(food.get("servingSize")),
        "raw_json_str": raw_json_str,
    }


# ---------- 补充数据源：国内免费接口（best-effort，字段名不统一，做柔性提取） ----------

def _deep_find(obj: Any, keys: tuple) -> Optional[str]:
    """在任意嵌套 JSON 中查找第一个命中的字符串字段（键名大小写不敏感）。"""
    want = {k.lower() for k in keys}
    stack = [obj]
    while stack:
        cur = stack.pop(0)
        if isinstance(cur, dict):
            for k, v in cur.items():
                if isinstance(v, str) and v.strip() and str(k).lower() in want:
                    return v.strip()
                if isinstance(v, (dict, list)):
                    stack.append(v)
        elif isinstance(cur, list):
            stack.extend([v for v in cur if isinstance(v, (dict, list))])
    return None


_CN_NAME_KEYS = ("goodsname", "goods_name", "name", "title", "productname", "product_name",
                 "商品名称", "goodsinfo", "tradename", "goods")
_CN_BRAND_KEYS = ("brand", "brandname", "brand_name", "品牌", "trademark", "manufacturer")
_CN_IMG_KEYS = ("image", "img", "picture", "pic", "imageurl", "imgurl", "图片", "photo")


def _parse_cn_product(code: str, data: Any) -> Optional[Dict[str, Any]]:
    """把国内接口返回的（字段名不确定的）JSON 尽量解析为内部格式；无可用名称则返回 None。"""
    name = _deep_find(data, _CN_NAME_KEYS)
    if not name:
        return None
    brand = _deep_find(data, _CN_BRAND_KEYS)
    image_url = _deep_find(data, _CN_IMG_KEYS)
    cats = [""]
    category = _map_category(cats, name)
    nut: Dict[str, Any] = {}
    tags = _map_tags(cats, name, nut, category)
    try:
        raw_json_str = json.dumps(data, ensure_ascii=False)[:20000]
    except Exception:  # noqa: BLE001
        raw_json_str = ""
    return {
        "name": name,
        "brand": brand,
        "category": category,
        "tags": tags,
        "nutriments_dict": nut,
        "image_url": image_url,
        "quantity": None,
        "raw_json_str": raw_json_str,
    }


def fetch_vvhan(code: str, db=None) -> Optional[Dict[str, Any]]:
    """vvhan 免费条码接口（国内可直连，无需密钥）。"""
    resp = httpx.get(
        net_proxy.wrap(VVHAN_API_URL, db),
        params={"barcode": code},
        headers={"User-Agent": OFF_USER_AGENT, "Accept": "application/json"},
        timeout=EXTRA_TIMEOUT,
        follow_redirects=True,
    )
    if resp.status_code != 200:
        return None
    return resp.json()


def fetch_oioweb(code: str, db=None) -> Optional[Dict[str, Any]]:
    """oioweb 免费条码接口（国内可直连，无需密钥）。"""
    resp = httpx.get(
        net_proxy.wrap(OIOWEB_API_URL, db),
        params={"barcode": code},
        headers={"User-Agent": OFF_USER_AGENT, "Accept": "application/json"},
        timeout=EXTRA_TIMEOUT,
        follow_redirects=True,
    )
    if resp.status_code != 200:
        return None
    return resp.json()


def fetch_custom_cn(code: str, db=None) -> Optional[Dict[str, Any]]:
    """可配置的国内条码接口：在 BARCODE_CN_API_URL 中配置带 {code} 的模板（如聚合数据/天行）。"""
    from .. import config as _c
    template = getattr(_c, "BARCODE_CN_API_URL", "") or ""
    if not template:
        return None
    url = template.replace("{code}", code)
    resp = httpx.get(
        net_proxy.wrap(url, db),
        headers={"User-Agent": OFF_USER_AGENT, "Accept": "application/json"},
        timeout=EXTRA_TIMEOUT,
        follow_redirects=True,
    )
    if resp.status_code != 200:
        return None
    return resp.json()


def store_in_cache(db: Session, code: str, parsed: Dict[str, Any], source: str = "openfoodfacts",
                   created_by: Optional[int] = None) -> PackagedFood:
    """存储或更新本地 PackagedFood 缓存。"""
    pf = db.get(PackagedFood, code)
    if pf is None:
        pf = PackagedFood(barcode=code)
        db.add(pf)
    pf.name = parsed["name"]
    pf.brand = parsed.get("brand")
    pf.category = parsed.get("category", "其他")
    pf.tags = json.dumps(parsed.get("tags") or [], ensure_ascii=False)
    nutr = dict(parsed.get("nutriments_dict") or {})
    if parsed.get("quantity"):
        nutr["quantity"] = parsed["quantity"]  # PackagedFood 没有 quantity 列，随营养成分一起保存以便换算热量
    pf.nutriments_json = json.dumps(nutr, ensure_ascii=False)
    pf.image_url = parsed.get("image_url")
    pf.source = source
    pf.raw_json = parsed.get("raw_json_str")
    if created_by is not None:
        pf.created_by = created_by
    db.commit()
    db.refresh(pf)
    return pf


# ---------- 数据源注册表（管理员可勾选启用哪些源） ----------
_SOURCES: Tuple[Tuple[str, Any, Any], ...] = (
    ("openfoodfacts", fetch_openfoodfacts, _parse_off_product),
    ("vvhan", fetch_vvhan, _parse_cn_product),
    ("oioweb", fetch_oioweb, _parse_cn_product),
    ("cn_custom", fetch_custom_cn, _parse_cn_product),
    ("upcitemdb", fetch_upcitemdb, _parse_upc_product),
    ("usda", fetch_usda, _parse_usda_product),
)
CN_SOURCE_IDS = ("vvhan", "oioweb", "cn_custom", "builtin")
_CN_SOURCES = set(CN_SOURCE_IDS)
SOURCE_LABELS = {
    "openfoodfacts": "Open Food Facts（海外，商品最全）",
    "vvhan": "vvhan 条码库（国内，免费）",
    "oioweb": "oioweb 条码库（国内，免费）",
    "cn_custom": "自定义国内接口（需配置 BARCODE_CN_API_URL）",
    "upcitemdb": "UPCitemdb（海外，免费试用）",
    "usda": "USDA FoodData（海外，营养数据全）",
    "builtin": "内置常见商品表（离线）",
}


def _builtin_parsed(code: str, builtin: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "name": builtin["name"],
        "brand": builtin.get("brand"),
        "category": builtin.get("category", "其他"),
        "tags": builtin.get("tags") or [],
        "nutriments_dict": builtin.get("nutriments") or {},
        "image_url": builtin.get("image_url"),
        "quantity": builtin.get("quantity"),
        "raw_json_str": "",
    }


def _score_parsed(parsed: Dict[str, Any]) -> int:
    """按数据完整度打分，用于多源结果中选最贴切的一个。"""
    s = 0
    if parsed.get("name"):
        s += 3
    if parsed.get("brand"):
        s += 2
    if parsed.get("nutriments_dict"):
        s += 2
    if parsed.get("image_url"):
        s += 1
    if parsed.get("quantity"):
        s += 1
    return s


def _localize_product_image(url: Optional[str], name: str) -> Optional[str]:
    """把商品图片下载到本地 uploads，避免在客户端直连外站加载失败。"""
    if not url:
        return None
    if url.startswith("/uploads/"):
        return url
    try:
        return dish_image._download(url, name or "product")
    except Exception:  # noqa: BLE001
        return url


def enabled_sources_value(db: Session) -> str:
    """设置里配置的启用数据源（逗号分隔）；空字符串表示未设置（全部启用）。"""
    try:
        from ..models import Setting
        row = db.get(Setting, "barcode_sources")
        return (row.value or "").strip() if row is not None else ""
    except Exception:  # noqa: BLE001
        return ""


def _enabled_sources(db: Session) -> set:
    """管理员设置启用的数据源；未设置时全部启用。"""
    try:
        from ..models import Setting
        row = db.get(Setting, "barcode_sources")
        if row is not None and (row.value or "").strip():
            return {x.strip() for x in row.value.split(",") if x.strip()}
    except Exception:  # noqa: BLE001
        pass
    return {n for n, _f, _p in _SOURCES}


def get_barcode_info(db: Session, code: str) -> Dict[str, Any]:
    """
    查询条形码信息（完整流程）：
    1. 本地缓存（manual 优先）
    2. 【并行】查询所有管理员启用的数据源 + 内置表，按完整度打分选最贴切的一个
    3. 仅回显真正命中的数据源（sources_found）；全部未命中时给出明确提示
    返回标准响应字典。
    """
    from .. import config as _cfg
    disclaimer = _cfg.DISCLAIMER

    # 本地缓存
    cached = lookup_cache(db, code)
    if cached:
        product = _build_product_dict(cached)
        return {
            "found": True,
            "source": cached.source,
            "product": product,
            "suggested_item": _make_suggested_item(product),
            "disclaimer": disclaimer,
        }

    # 管理员可启用的数据源（settings.barcode_sources，逗号分隔）；未设置则全部启用
    enabled = _enabled_sources(db)
    # BARCODE_EXTRA_SOURCES=0（如测试环境）时只走内置表，避免联网
    active = ([(n, f, p) for n, f, p in _SOURCES if n in enabled]
              if getattr(_cfg, "BARCODE_EXTRA_SOURCES", True) else [])

    # 并行查询所有启用数据源
    raw_results: Dict[str, Any] = {}
    errors: List[str] = []
    if active:
        with ThreadPoolExecutor(max_workers=min(6, max(1, len(active)))) as ex:
            futures = {ex.submit(fetcher, code, db): name for name, fetcher, _p in active}
            for fu in as_completed(futures):
                name = futures[fu]
                try:
                    raw_results[name] = fu.result()
                except Exception as e:  # noqa: BLE001
                    raw_results[name] = None
                    errors.append(f"{name}: {e}")

    # 收集候选（含内置表），并按完整度打分选最贴切的一个
    candidates: List[Tuple[str, Dict[str, Any]]] = []
    builtin = _BUILTIN.get(code)
    if builtin:
        candidates.append(("builtin", _builtin_parsed(code, builtin)))
    for name, _fetcher, parser in active:
        raw = raw_results.get(name)
        if not raw:
            continue
        try:
            parsed = parser(code, raw)
        except Exception:  # noqa: BLE001
            parsed = None
        if parsed:  # 只保留能解析出名称的结果
            candidates.append((name, parsed))

    if candidates:
        best_score, best_name, best_parsed = -1, "", None
        for name, parsed in candidates:
            sc = _score_parsed(parsed) + (1 if name in _CN_SOURCES else 0)
            if sc > best_score:
                best_score, best_name, best_parsed = sc, name, parsed
        # 商品图下载到本地，客户端不再直连外站
        best_parsed["image_url"] = _localize_product_image(
            best_parsed.get("image_url"), best_parsed.get("name") or code)
        pf = store_in_cache(db, code, best_parsed, source=best_name)
        product = _build_product_dict(pf)
        product["quantity"] = best_parsed.get("quantity")
        return {
            "found": True,
            "source": best_name,
            # 仅回显真正查到结果的数据源，未命中的不展示
            "sources_found": sorted({n for n, _ in candidates}),
            "product": product,
            "suggested_item": _make_suggested_item(product),
            "disclaimer": disclaimer,
        }

    return {
        "found": False,
        "source": None,
        "sources_found": [],
        "product": None,
        "suggested_item": None,
        "message": "该食品未收录或您扫描的不是食品",
        "error": "; ".join(errors[:2]) if errors else None,
        "disclaimer": disclaimer,
    }
