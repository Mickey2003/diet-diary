"""
图片识别服务：保存并压缩图片 → 调用多模态模型 → 严格校验 → 重试一次 → 手填兜底。
"""
import base64
import io
import json
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from PIL import Image, ImageOps
from pydantic import ValidationError
from sqlalchemy.orm import Session

from .. import config
from ..schemas import RecognizeOut, VisionResult
from . import llm_client
from .kcal import estimate_kcal
from .tags import CATEGORIES, MEAL_TYPES, TAG_DEFS, normalize_tag_codes, tag_lookup


class ImageError(Exception):
    pass


def save_upload(data: bytes, original_name: str = "") -> str:
    """校正 EXIF 方向、压缩到最长边 MAX_IMAGE_SIDE、转 JPEG 保存。返回相对路径（文件名）。"""
    if len(data) > config.MAX_UPLOAD_MB * 1024 * 1024:
        raise ImageError(f"图片超过 {config.MAX_UPLOAD_MB}MB 限制")
    try:
        img = Image.open(io.BytesIO(data))
        img = ImageOps.exif_transpose(img)
    except Exception as e:  # noqa: BLE001
        raise ImageError(f"无法识别的图片文件：{e}") from e
    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")
    img.thumbnail((config.MAX_IMAGE_SIDE, config.MAX_IMAGE_SIDE))
    name = f"{time.strftime('%Y%m%d')}_{uuid.uuid4().hex[:10]}.jpg"
    path = Path(config.UPLOAD_DIR) / name
    img.save(path, "JPEG", quality=85, optimize=True)
    # 320px 缩略图给时间线列表用，减少手机端流量
    try:
        thumb_dir = Path(config.UPLOAD_DIR) / "thumb"
        thumb_dir.mkdir(parents=True, exist_ok=True)
        t = img.copy()
        t.thumbnail((320, 320))
        t.save(thumb_dir / name, "JPEG", quality=78, optimize=True)
    except Exception:  # noqa: BLE001  缩略图失败不影响主流程
        pass
    return name


def image_to_data_url(rel_path: str) -> str:
    p = Path(config.UPLOAD_DIR) / rel_path
    b64 = base64.b64encode(p.read_bytes()).decode()
    return f"data:image/jpeg;base64,{b64}"


def _tag_doc() -> str:
    return "\n".join(f"- {code}（{name}）：{desc}" for code, name, _g, _w, desc in TAG_DEFS)


SYSTEM_PROMPT = f"""你是一个饮食日记应用里的“餐食观察助手”。用户会上传一张餐食照片，你需要识别照片里的食物并输出结构化 JSON。

严格要求：
1. 只输出一个 JSON 对象，不要输出任何解释文字、不要使用 Markdown 围栏。
2. JSON 结构：
{{
  "items": [
    {{"name": "菜品中文名", "category": "分类", "portion": "少|中|多", "tags": ["标签code", ...], "confidence": 0~1 的小数, "kcal": 该份食物的粗略热量整数（千卡），无法判断填 null}}
  ],
  "meal_type_guess": "早餐|午餐|晚餐|加餐|饮品 或 null",
  "overall_note": "一句话描述这顿饭（中文）",
  "uncertainty": "你不确定的地方（中文，可为空字符串）"
}}
3. category 只能取：{"、".join(CATEGORIES)}。
4. meal_type_guess 只能取：{"、".join(MEAL_TYPES)}，看不出就填 null。
5. tags 只能使用下列 code（可多选，可为空）：
{_tag_doc()}
6. kcal 只需给一个粗略的整数估算（例如一碗米饭约 230、一杯奶茶约 350），不要输出克数或营养素数值，不要给医疗或减肥建议。看不清就降低 confidence 并在 uncertainty 中说明。
7. 如果照片里没有食物，items 返回空数组并在 uncertainty 中说明。
"""


def _validate(raw_text: str, lookup: Dict[str, Any]) -> Tuple[VisionResult, List[str]]:
    data = llm_client.parse_json(raw_text)
    if not isinstance(data, dict):
        raise ValueError("模型输出不是 JSON 对象")
    result = VisionResult.model_validate(data)
    warnings: List[str] = []
    for item in result.items:
        codes, dropped = normalize_tag_codes(item.tags, lookup)
        item.tags = codes
        if dropped:
            warnings.append(f"「{item.name}」的标签 {dropped} 不在标签字典内，已忽略")
        # 热量：模型给了就标 ai，否则用本地菜品表兜底
        if item.kcal is not None:
            item.kcal_source = "ai"
        else:
            item.kcal, item.kcal_source = estimate_kcal(item.name, item.category, item.portion)
    if not result.items:
        warnings.append("模型没有识别出任何食物，请手动填写")
    return result, warnings


def recognize(db: Session, rel_path: str) -> RecognizeOut:
    client = llm_client.get_client(db)
    lookup = tag_lookup(db)
    model_name = client.model_name(vision=True)
    warnings: List[str] = []
    raw_text: Optional[str] = None
    t0 = time.time()

    if client.cfg.is_mock:
        warnings.append("当前为离线演示模式：识别结果为示例数据，与照片内容无关。请在设置页配置模型后重试。")
        messages: List[Dict[str, Any]] = []
    else:
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": [
                {"type": "image_url", "image_url": {"url": image_to_data_url(rel_path)}},
                {"type": "text", "text": "请识别这张餐食照片，按要求只输出 JSON。"},
            ]},
        ]

    last_error: Optional[str] = None
    for attempt in range(2):  # 最多两次：首次 + 带错误反馈的重试
        try:
            raw_text = client.chat(messages, vision=True, task="vision", temperature=0.1)
            result, w = _validate(raw_text, lookup)
            warnings.extend(w)
            return RecognizeOut(
                image_path=rel_path, result=result, fallback=False, warnings=warnings,
                model=model_name, latency_ms=int((time.time() - t0) * 1000), raw=raw_text,
                disclaimer=config.DISCLAIMER,
            )
        except (json.JSONDecodeError, ValidationError, ValueError) as e:
            last_error = f"第 {attempt + 1} 次输出无法解析或不符合结构：{str(e)[:200]}"
            warnings.append(last_error)
            if not client.cfg.is_mock and attempt == 0:
                messages = messages + [
                    {"role": "assistant", "content": raw_text or ""},
                    {"role": "user", "content": f"你的输出不符合要求：{str(e)[:300]}。请重新只输出一个合法 JSON 对象，不要任何多余文字。"},
                ]
        except llm_client.LLMError as e:
            last_error = str(e)
            warnings.append(last_error)
            break

    warnings.append("已切换为手动填写模式。")
    return RecognizeOut(
        image_path=rel_path, result=None, fallback=True, warnings=warnings,
        model=model_name, latency_ms=int((time.time() - t0) * 1000), raw=raw_text,
        disclaimer=config.DISCLAIMER,
    )
