"""
菜品配图服务（v0.8.6）。

取图优先级：
1. 本地缓存（backend/data/dish_images.json：菜名 -> 本地图片文件名）
2. **AI 生图**（SenseAudio 图片生成，或 OpenAI 兼容接口；需管理员开启 `dish_ai_images`）
   —— 固定提示词模板保证整套图风格统一，最贴合「中餐菜品 / 数量大 / 缩略图小」的场景。
3. 现成网络图库（多源）：维基百科(zh/en) → 维基共享 → 百度百科/搜狗百科/360百科
4. **Emoji 兜底**：以上都拿不到时用菜品 emoji（`dish_emoji.py`）渲染，零成本、跨端一致。

图片落盘 `uploads/dish_images/`，尽量统一转 **WebP**，并生成 **200×150 缩略图**（`uploads/thumb/`）。
不再把外站 URL 直接发给客户端（用户网络可能加载不了维基等外站）。

所有异常一律吞掉：配图是锦上添花，绝不影响餐单生成与展示。
"""
import hashlib
import json
import os
import re
import threading
import time
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote

import httpx

from .. import config
from . import dish_emoji, image_client, net_proxy

_BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CACHE_PATH = os.path.join(_BASE_DIR, "data", "dish_images.json")
LOCAL_SUBDIR = "dish_images"
LOCAL_DIR = os.path.join(str(config.UPLOAD_DIR), LOCAL_SUBDIR)
THUMB_SUBDIR = "thumb"
THUMB_DIR = os.path.join(str(config.UPLOAD_DIR), THUMB_SUBDIR)

# 缩略图尺寸（列表/卡片用；一屏十几张，200×150 足够）
THUMB_W, THUMB_H = 200, 150

_CACHE_LOCK = threading.Lock()
# key(归一化菜名) -> {"file": "xxx.webp", "ts": float, "src": "ai|web"}
_CACHE: Dict[str, Dict[str, Any]] = {}
_POS_TTL = 60 * 24 * 3600   # 命中缓存 60 天
_NEG_TTL = 2 * 24 * 3600    # 未命中缓存 2 天
_MAX_BUDGET_S = 90          # 单次补全总预算（秒）
_MAX_DISHES = 60

_UA = "DietDiary/0.8.6 (diet-diary; dish image lookup)"
_BROWSER_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
               "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")
_TIMEOUT = 6.0

# ---------------------------------------------------------------------------
# AI 生图提示词模板（固定，保证整套图风格统一）
# ---------------------------------------------------------------------------
AI_PROMPT_TEMPLATE = (
    "{dish}，3D 卡通渲染风格，柔和奶油色渐变背景，居中构图，柔光，可爱简约，"
    "写实食物参考，无文字，无水印，无人物，正方形构图"
)

# 国内百科（直连，不走代理）
_CN_BAIKE_TEMPLATES = (
    "https://baike.baidu.com/item/{q}",
    "https://baike.sogou.com/search/?query={q}",
    "https://baike.so.com/search/?q={q}",
)


def _normalize(name: str) -> str:
    return re.sub(r"\s+", "", (name or "").strip()).lower()


def ai_prompt_for(dish_name: str) -> str:
    """按固定模板生成提示词，保证整套图风格统一。"""
    return AI_PROMPT_TEMPLATE.format(dish=(dish_name or "").strip())


# ---------- 本地图片存储 ----------

def _ensure_dir() -> None:
    for d in (LOCAL_DIR, THUMB_DIR):
        try:
            os.makedirs(d, exist_ok=True)
        except Exception:  # noqa: BLE001
            pass


def _ext_from(content_type: str, url: str) -> str:
    ct = (content_type or "").split(";")[0].strip().lower()
    mapping = {
        "image/png": "png", "image/jpeg": "jpg", "image/jpg": "jpg",
        "image/webp": "webp", "image/gif": "gif", "image/svg+xml": "svg",
    }
    if ct in mapping:
        return mapping[ct]
    low = (url or "").lower().split("?")[0]
    for e in ("png", "jpg", "jpeg", "webp", "gif"):
        if low.endswith("." + e):
            return "jpg" if e == "jpeg" else e
    return "jpg"


def _to_webp(data: bytes) -> Optional[bytes]:
    """转 WebP（统一格式、体积更小）。失败返回 None（则保留原格式）。"""
    try:
        from io import BytesIO

        from PIL import Image
        im = Image.open(BytesIO(data))
        if im.mode not in ("RGB", "RGBA"):
            im = im.convert("RGBA" if im.mode in ("P", "LA") and "transparency" in im.info else "RGB")
        # 限制最大边，避免超大图占空间（列表缩略图不需要原图精度）
        max_side = max(im.size)
        if max_side > 1280:
            ratio = 1280 / max_side
            im = im.resize((max(1, int(im.width * ratio)), max(1, int(im.height * ratio))),
                           Image.LANCZOS)
        out = BytesIO()
        im.save(out, format="WEBP", quality=82, method=4)
        return out.getvalue()
    except Exception:  # noqa: BLE001
        return None


def _make_thumb(filename: str) -> None:
    """为 uploads/dish_images/<filename> 生成 uploads/thumb/<filename>（200×150 居中裁切）。"""
    try:
        from io import BytesIO

        from PIL import Image
        src = os.path.join(LOCAL_DIR, filename)
        dst = os.path.join(THUMB_DIR, os.path.splitext(filename)[0] + ".webp")
        if os.path.isfile(dst) or not os.path.isfile(src):
            return
        im = Image.open(src)
        if im.mode not in ("RGB", "RGBA"):
            im = im.convert("RGB")
        ratio = max(THUMB_W / im.width, THUMB_H / im.height)
        im = im.resize((max(1, int(im.width * ratio)), max(1, int(im.height * ratio))),
                       Image.LANCZOS)
        left = max(0, (im.width - THUMB_W) // 2)
        top = max(0, (im.height - THUMB_H) // 2)
        im = im.crop((left, top, left + THUMB_W, top + THUMB_H))
        im.save(dst, format="WEBP", quality=80, method=4)
    except Exception:  # noqa: BLE001
        pass


def save_image_locally(data: bytes, dish_name: str,
                       content_type: str = "", src_url: str = "",
                       src: str = "web") -> Optional[str]:
    """把图片字节存到 uploads/dish_images/（尽量转 WebP），返回可给前端的本地 URL。"""
    if not data:
        return None
    _ensure_dir()
    digest = hashlib.sha1(_normalize(dish_name).encode("utf-8")).hexdigest()[:20]

    webp = _to_webp(data)
    if webp:
        filename, blob = f"{digest}.webp", webp
    else:
        filename, blob = f"{digest}.{_ext_from(content_type, src_url)}", data

    try:
        with open(os.path.join(LOCAL_DIR, filename), "wb") as f:
            f.write(blob)
    except Exception:  # noqa: BLE001
        return None

    _make_thumb(filename)
    # 记录来源（ai / web），便于统计"还有多少张是 emoji"以及灰度替换
    with _CACHE_LOCK:
        entry = _CACHE.get(_normalize(dish_name)) or {}
        entry["src"] = src
        _CACHE[_normalize(dish_name)] = entry

    return f"/uploads/{LOCAL_SUBDIR}/{filename}"


def _download(url: str, dish_name: str, src: str = "web") -> Optional[str]:
    """下载远端图片并本地化，返回本地 URL。"""
    try:
        r = httpx.get(net_proxy.wrap(url), headers={"User-Agent": _UA},
                      timeout=_TIMEOUT, follow_redirects=True)
        if r.status_code != 200 or not r.content:
            return None
        if len(r.content) < 1024:  # 太小多半是错误页/占位
            return None
        return save_image_locally(r.content, dish_name,
                                  r.headers.get("content-type", ""), url, src=src)
    except Exception:  # noqa: BLE001
        return None


# ---------- 缓存 ----------

def _load_cache() -> None:
    global _CACHE
    try:
        if os.path.exists(CACHE_PATH):
            with open(CACHE_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                for k, v in data.items():
                    if isinstance(v, str):  # 兼容旧格式（菜名 -> 远端 URL）
                        _CACHE[k] = {"file": None, "ts": 0.0}
                    elif isinstance(v, dict):
                        _CACHE[k] = v
    except Exception:  # noqa: BLE001
        _CACHE = {}


def _save_cache() -> None:
    try:
        os.makedirs(os.path.dirname(CACHE_PATH), exist_ok=True)
        with open(CACHE_PATH, "w", encoding="utf-8") as f:
            json.dump(_CACHE, f, ensure_ascii=False)
    except Exception:  # noqa: BLE001
        pass


def _cache_lookup(key: str) -> Tuple[bool, Optional[str]]:
    """返回 (是否有未过期条目, 本地图片 URL)。"""
    entry = _CACHE.get(key)
    if not entry:
        return False, None
    ts = float(entry.get("ts") or 0)
    path = entry.get("file")
    if time.time() - ts > (_POS_TTL if path else _NEG_TTL):
        return False, None
    if path and not os.path.isfile(os.path.join(LOCAL_DIR, os.path.basename(path))):
        return False, None  # 文件被清理过，重新获取
    return True, path


def _cache_set(key: str, path: Optional[str], src: str = "") -> None:
    _CACHE[key] = {"file": path, "ts": time.time(), "src": src}


def cache_source(key: str) -> str:
    """该菜名当前图片的来源（web / ai）；无图或未命中返回空串。"""
    entry = _CACHE.get(key) or {}
    return str(entry.get("src") or "")


# ---------- 网络图库（多源） ----------

def _wiki_image_url(name: str) -> Optional[str]:
    for lang in ("zh", "en"):
        try:
            r = httpx.get(
                net_proxy.wrap(f"https://{lang}.wikipedia.org/w/api.php"),
                params={"action": "query", "titles": name, "redirects": 1,
                        "prop": "pageimages", "pithumbsize": 600, "format": "json"},
                headers={"User-Agent": _UA}, timeout=_TIMEOUT,
            )
            pages = ((r.json().get("query") or {}).get("pages") or {})
            for _pid, pg in pages.items():
                src = (pg.get("thumbnail") or {}).get("source")
                if src:
                    return src
        except Exception:  # noqa: BLE001
            continue
    return None


def _commons_image_url(name: str) -> Optional[str]:
    try:
        r = httpx.get(
            net_proxy.wrap("https://commons.wikimedia.org/w/api.php"),
            params={"action": "query", "generator": "search",
                    "gsrsearch": f"filetype:bitmap {name} food", "gsrnamespace": 6,
                    "gsrlimit": 1, "prop": "imageinfo", "iiprop": "url",
                    "iiurlwidth": 600, "format": "json"},
            headers={"User-Agent": _UA}, timeout=_TIMEOUT,
        )
        pages = ((r.json().get("query") or {}).get("pages") or {})
        for _pid, pg in pages.items():
            ii = (pg.get("imageinfo") or [{}])[0]
            src = ii.get("thumburl") or ii.get("url")
            if src:
                return src
    except Exception:  # noqa: BLE001
        pass
    return None


def _baike_image_url(name: str) -> Optional[str]:
    """国内百科（百度/搜狗/360）条目页 og:image；best-effort，可能受反爬影响。"""
    for tpl in _CN_BAIKE_TEMPLATES:
        try:
            r = httpx.get(tpl.format(q=quote(name)), headers={"User-Agent": _BROWSER_UA},
                          timeout=_TIMEOUT, follow_redirects=True)
            if r.status_code != 200:
                continue
            html = r.text[:400000]
            m = (re.search(r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)', html)
                 or re.search(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image["\']', html))
            if m and m.group(1).startswith("http"):
                return m.group(1)
            # 360 百科等可能没有 og:image，退而求其次取正文首个图片
            m2 = re.search(r'<img[^>]+src=["\'](https?://[^"\']+\.(?:jpe?g|png|webp))["\']', html, re.I)
            if m2:
                cand = m2.group(1)
                # 过滤 logo/图标等明显无关图
                if not re.search(r"(logo|icon|avatar|blank|spacer|qrcode)", cand, re.I):
                    return cand
        except Exception:  # noqa: BLE001
            continue
    return None


def _web_sources() -> Tuple[Any, ...]:
    """按优先级返回图库源函数（返回远端图片 URL）。"""
    return (_wiki_image_url, _commons_image_url, _baike_image_url)


def fetch_web_image(name: str) -> Optional[str]:
    """从网络图库取图并【下载到本地】，返回本地 URL；失败返回 None。"""
    for src in _web_sources():
        try:
            remote = src(name)
        except Exception:  # noqa: BLE001
            remote = None
        if not remote:
            continue
        local = _download(remote, name)
        if local:
            return local
    return None


# ---------- AI 生图（独立配置） ----------

def ai_images_enabled(db=None) -> bool:
    """管理员开关：是否允许 AI 生图（默认关闭）。"""
    if db is not None:
        try:
            from ..models import Setting
            row = db.get(Setting, "dish_ai_images")
            if row is not None:
                return (row.value or "").strip().lower() in {"1", "true", "yes", "on"}
        except Exception:  # noqa: BLE001
            pass
    return config.DISH_AI_IMAGES


def get_image_config(db) -> Dict[str, str]:
    """读取「生图专用」的一套 API 配置（与文本/识图模型解耦）。

    取值优先级：数据库 settings 表 → 环境变量。
    未配置 provider 时，回退到文本模型配置（兼容旧部署）。
    """
    out = {
        "provider": "",
        "base_url": "",
        "api_key": "",
        "model": "",
        "size": "",
    }
    try:
        from ..models import Setting
        # 注意：生图模型的 DB key 是 "dish_image_model"，不能与旧字段 "image_model"
        # （OpenAI 兼容配图模型）复用，否则两边互相覆盖。
        keys = ("image_provider", "image_base_url", "image_api_key",
                "dish_image_model", "image_model", "image_size")
        rows = db.query(Setting).filter(Setting.key.in_(keys)).all() if db is not None else []
        dbv = {r.key: (r.value or "") for r in rows}
        out["provider"] = dbv.get("image_provider") or config.IMAGE_PROVIDER
        out["base_url"] = dbv.get("image_base_url") or config.IMAGE_BASE_URL
        out["api_key"] = dbv.get("image_api_key") or config.IMAGE_API_KEY
        # 优先新 key；兼容早期已写入 "image_model" 的部署
        out["model"] = dbv.get("dish_image_model") or dbv.get("image_model") or config.IMAGE_MODEL
        out["size"] = dbv.get("image_size") or config.IMAGE_SIZE
    except Exception:  # noqa: BLE001
        out["provider"] = getattr(config, "IMAGE_PROVIDER", "")
        out["base_url"] = getattr(config, "IMAGE_BASE_URL", "")
        out["api_key"] = getattr(config, "IMAGE_API_KEY", "")
        out["model"] = getattr(config, "IMAGE_MODEL", "")
        out["size"] = getattr(config, "IMAGE_SIZE", "")

    # 一点兼容：生图若未单独配置 key/base，但文本模型是 OpenAI 兼容且配了 image_model，则复用
    if not out["api_key"] and db is not None:
        try:
            from .llm_client import get_llm_config
            lc = get_llm_config(db)
            if lc and not lc.is_mock and lc.api_key:
                legacy_model = getattr(lc, "image_model", "")
                if legacy_model:
                    out["provider"] = out["provider"] or lc.provider
                    out["base_url"] = out["base_url"] or lc.base_url
                    out["api_key"] = out["api_key"] or lc.api_key
                    out["model"] = out["model"] or legacy_model
        except Exception:  # noqa: BLE001
            pass
    return out


def image_config_ready(db) -> bool:
    """生图是否已配置可用（provider + key + model 齐备）。"""
    c = get_image_config(db)
    return bool(c["provider"] and c["api_key"] and c["model"])


def generate_dish_image(name: str, db=None) -> Optional[str]:
    """AI 生图：用固定模板生成，结果落盘本地后返回本地 URL；失败返回 None。

    走 `image_client`，支持 SenseAudio（/v1/image/sync）与 OpenAI 兼容（/images/generations）。
    """
    cfg = get_image_config(db)
    if not (cfg["provider"] and cfg["api_key"] and cfg["model"]):
        return None

    want_size = cfg["size"] or "1024x1024"
    res = image_client.generate_image(
        ai_prompt_for(name),
        provider=cfg["provider"],
        api_key=cfg["api_key"],
        model=cfg["model"],
        base_url=cfg["base_url"],
        size=want_size,
        timeout=float(getattr(config, "IMAGE_TIMEOUT", 120)),
    )
    if not res.ok:
        return None

    if res.data:
        return save_image_locally(res.data, name, res.content_type or "image/png", src="ai")
    if res.image_url:
        return _download(res.image_url, name, src="ai")
    return None


# ---------- 对餐单补全配图 ----------

def collect_dish_names(plan_dict: Dict) -> List[str]:
    seen = set()
    names: List[str] = []
    for day in plan_dict.get("days", []) or []:
        for meal in day.get("meals", []) or []:
            for dish in meal.get("dishes", []) or []:
                nm = (dish.get("name") or "").strip()
                if not nm:
                    continue
                key = _normalize(nm)
                if key and key not in seen:
                    seen.add(key)
                    names.append(nm)
    return names[:_MAX_DISHES]


def apply_emoji_to_dish(dish: Dict) -> None:
    """给单个菜品对象补 emoji 字段（前端在无图时用它渲染，避免占位图空窗）。"""
    nm = (dish.get("name") or "").strip()
    cat = (dish.get("category") or "").strip() if isinstance(dish.get("category"), str) else ""
    entry = dish_emoji.build_emoji_entry(nm, cat)
    dish["image_emoji"] = entry["image_emoji"]
    dish["image_emoji_url"] = entry["image_emoji_url"]
    if not dish.get("image_bg"):
        dish["image_bg"] = entry["image_bg"]


def _iter_dishes(plan_dict: Dict):
    for day in plan_dict.get("days", []) or []:
        for meal in day.get("meals", []) or []:
            for dish in meal.get("dishes", []) or []:
                yield dish


def thumb_url_for(image_url: str) -> str:
    """由原图 URL 派生 200×150 缩略图 URL；不是本地图则返回空串。"""
    u = (image_url or "").strip()
    prefix = f"/uploads/{LOCAL_SUBDIR}/"
    if not u.startswith(prefix):
        return ""
    name = os.path.splitext(u[len(prefix):])[0]
    return f"/uploads/{THUMB_SUBDIR}/{name}.webp"


def enrich_plan_images(plan_dict: Dict, db=None,
                       web_enabled: bool = True, ai_enabled: bool = False,
                       concurrency: int = 8, force_ai: bool = False) -> Dict:
    """给餐单中每道菜赋 image_url（本地 /uploads 路径）+ emoji 兜底字段；不会抛异常。

    - `force_ai=True`：只走 AI 生图（用于"把 emoji 图替换成 AI 图"），不再查图库。
    - 并发取图，显著缩短总耗时，使"生成后图片立即可见"成为可能。
    """
    with _CACHE_LOCK:
        if not _CACHE:
            _load_cache()

    names = collect_dish_names(plan_dict)
    # 无论如何先给所有菜品补 emoji 兜底字段（无图时前端直接渲染 emoji）
    for dish in _iter_dishes(plan_dict):
        apply_emoji_to_dish(dish)

    if not names:
        return plan_dict

    url_map: Dict[str, str] = {}

    if force_ai:
        pending = names
        # 强制 AI 时忽略缓存（否则命中旧图库图无法替换）
        with _CACHE_LOCK:
            for nm in pending:
                _CACHE.pop(_normalize(nm), None)
    else:
        pending = []
        for name in names:
            key = _normalize(name)
            with _CACHE_LOCK:
                found, cached = _cache_lookup(key)
            if found:
                if cached:
                    url_map[name] = cached
                continue
            pending.append(name)

    if pending:
        from concurrent.futures import ThreadPoolExecutor, as_completed

        def _one(nm: str) -> Tuple[str, Optional[str], str]:
            local: Optional[str] = None
            used = ""
            # 需求：AI 生图优先（风格统一、中餐更准）；未开启或失败再退回图库
            if ai_enabled and db is not None:
                local = generate_dish_image(nm, db)
                if local:
                    used = "ai"
            if not local and web_enabled and not force_ai:
                local = fetch_web_image(nm)
                if local:
                    used = "web"
            return nm, local, used

        start = time.time()
        dirty = False
        workers = max(1, min(concurrency, len(pending)))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(_one, nm): nm for nm in pending}
            for fut in as_completed(futures):
                if time.time() - start > _MAX_BUDGET_S:
                    for f in futures:
                        f.cancel()
                    break
                try:
                    nm, local, used = fut.result()
                except Exception:  # noqa: BLE001
                    continue
                with _CACHE_LOCK:
                    _cache_set(_normalize(nm), local, src=used)
                    dirty = True
                if local:
                    url_map[nm] = local

        if dirty:
            with _CACHE_LOCK:
                _save_cache()

    if url_map:
        for dish in _iter_dishes(plan_dict):
            nm = (dish.get("name") or "").strip()
            if nm in url_map:
                dish["image_url"] = url_map[nm]
                thumb = thumb_url_for(url_map[nm])
                if thumb:
                    dish["thumb_url"] = thumb
    return plan_dict


def count_emoji_dishes(plan_dict: Dict) -> int:
    """统计餐单中「没有真实图片、只能靠 emoji 兜底」的菜品数量。"""
    n = 0
    for dish in _iter_dishes(plan_dict):
        if not (dish.get("image_url") or "").strip():
            n += 1
    return n
