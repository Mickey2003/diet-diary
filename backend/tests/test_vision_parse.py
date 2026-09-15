"""视觉输出解析与校验：围栏剥离、非法值兜底、标签归一化。"""
import json

import pytest
from pydantic import ValidationError

from app.schemas import VisionResult
from app.services.llm_client import parse_json, strip_json_fence
from app.services.tags import normalize_tag_codes, tag_lookup


def test_strip_fence_variants():
    assert strip_json_fence('```json\n{"a":1}\n```') == '{"a":1}'
    assert strip_json_fence('```\n{"a":1}\n```') == '{"a":1}'
    assert strip_json_fence('好的，结果如下：{"a":1} 以上。') == '{"a":1}'
    assert parse_json('```json\n{"items": []}\n```') == {"items": []}


def test_parse_json_arrays_and_wrapped_text():
    """模型返回 JSON 数组（记忆抽取）或前后带解释文字时也要能解析。"""
    assert parse_json('[{"a":1},{"b":2}]') == [{"a": 1}, {"b": 2}]
    assert parse_json('```json\n[{"a":1}]\n```') == [{"a": 1}]
    assert parse_json('提取结果如下：[{"content":"常吃米饭"}] 完毕') == [{"content": "常吃米饭"}]
    assert parse_json('结果：{"x":[1,2]} 完') == {"x": [1, 2]}


def test_vision_result_coerces_invalid_enums():
    data = {"items": [{"name": "奶茶", "category": "饮料", "portion": "巨多", "tags": ["sugary_drink"], "confidence": 1.7}],
            "meal_type_guess": "下午茶", "overall_note": "x"}
    r = VisionResult.model_validate(data)
    assert r.items[0].category == "其他"
    assert r.items[0].portion == "中"
    assert r.items[0].confidence == 1.0
    assert r.meal_type_guess is None


def test_vision_result_rejects_missing_name():
    with pytest.raises(ValidationError):
        VisionResult.model_validate({"items": [{"category": "主食"}]})


def test_parse_json_garbage_raises():
    with pytest.raises(json.JSONDecodeError):
        parse_json("这不是 JSON")


def test_normalize_tags(db):
    lookup = tag_lookup(db)
    codes, dropped = normalize_tag_codes(["sugary_drink", "油炸", "外星食物", "含糖饮料"], lookup)
    assert codes == ["sugary_drink", "fried"]
    assert dropped == ["外星食物"]
