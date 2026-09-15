"""
健康档案（Feature 1）和个性化餐单（Feature 2）测试。

涵盖：
- BMI / BMI分类 / 能量估算数学
- 注意事项关键词映射
- 档案校验错误
- 人设预设填充
- 体质问卷评分
- 餐单生成（结构 + 天数 + 过敏原过滤）
- 单槽重新生成（其余槽不变）
- 激活 / 停用餐单
- 用户隔离
"""
import json

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.profile import (
    HEALTH_DISCLAIMER,
    _bmi,
    _bmi_category,
    _energy_estimate,
    get_cautions,
    score_quiz,
)
from .conftest import TEST_USER


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------

def _login(c: TestClient, username: str, password: str) -> None:
    r = c.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text


def _ensure_user(admin_client: TestClient, username: str, password: str) -> int:
    users = admin_client.get("/api/admin/users").json()
    for u in users:
        if u["username"] == username:
            return u["id"]
    r = admin_client.post("/api/admin/users", json={"username": username, "password": password, "role": "user"})
    assert r.status_code == 201, r.text
    return r.json()["id"]


# ---------------------------------------------------------------------------
# Feature 1: BMI / 能量估算（单元测试，不走 HTTP）
# ---------------------------------------------------------------------------

class TestBmiMath:
    def test_bmi_normal(self):
        """70kg, 175cm → BMI = 22.9，正常"""
        bmi = _bmi(70, 175)
        assert bmi == pytest.approx(22.9, abs=0.05)
        assert _bmi_category(bmi) == "正常"

    def test_bmi_underweight(self):
        bmi = _bmi(50, 175)
        assert bmi < 18.5
        assert _bmi_category(bmi) == "偏瘦"

    def test_bmi_overweight(self):
        bmi = _bmi(80, 175)
        assert 24 <= bmi < 28
        assert _bmi_category(bmi) == "超重"

    def test_bmi_obese(self):
        bmi = _bmi(100, 175)
        assert bmi >= 28
        assert _bmi_category(bmi) == "肥胖"

    def test_bmi_boundary_normal_lower(self):
        """BMI 18.5 → 正常"""
        assert _bmi_category(18.5) == "正常"

    def test_bmi_boundary_overweight(self):
        """BMI 24.0 → 超重"""
        assert _bmi_category(24.0) == "超重"

    def test_bmi_boundary_obese(self):
        """BMI 28.0 → 肥胖"""
        assert _bmi_category(28.0) == "肥胖"

    def test_energy_estimate_male_moderate(self):
        """男，30岁，70kg，175cm，中等活动 → 约 2267kcal"""
        energy = _energy_estimate(70, 175, 1996, "男", "中")
        # BMR = 10*70 + 6.25*175 - 5*30 + 5 = 700+1093.75-150+5 = 1648.75
        # × 1.375 ≈ 2267
        # 年龄用当前年份计算，允许1年误差对应的范围
        assert 2000 < energy < 2600

    def test_energy_estimate_female_low(self):
        """女，低活动量 → 低于男性同样条件"""
        male_energy = _energy_estimate(60, 165, 1990, "男", "低")
        female_energy = _energy_estimate(60, 165, 1990, "女", "低")
        assert female_energy < male_energy

    def test_energy_estimate_high_activity(self):
        """高活动量 > 中活动量"""
        e_high = _energy_estimate(70, 175, 1990, "男", "高")
        e_mid = _energy_estimate(70, 175, 1990, "男", "中")
        assert e_high > e_mid


class TestCautions:
    """注意事项关键词映射测试。"""

    def _make_profile(self, **kwargs):
        """构造虚拟 Profile 对象（不入库，使用 SimpleNamespace 避免 ORM 描述符问题）。"""
        from types import SimpleNamespace
        return SimpleNamespace(
            conditions=kwargs.get("conditions"),
            medications=kwargs.get("medications"),
            allergies=kwargs.get("allergies"),
            goals=None,
            preferences=None,
        )

    def test_diabetes_caution(self):
        p = self._make_profile(conditions="糖尿病")
        cautions = get_cautions(p)
        assert any("精制主食" in c or "血糖" in c for c in cautions)

    def test_hypertension_caution(self):
        p = self._make_profile(conditions="高血压")
        cautions = get_cautions(p)
        assert any("盐" in c for c in cautions)

    def test_gout_caution(self):
        p = self._make_profile(conditions="痛风")
        cautions = get_cautions(p)
        assert any("嘌呤" in c or "海鲜" in c for c in cautions)

    def test_warfarin_caution(self):
        p = self._make_profile(medications="华法林")
        cautions = get_cautions(p)
        assert any("维生素K" in c for c in cautions)

    def test_metformin_caution(self):
        p = self._make_profile(medications="二甲双胍")
        cautions = get_cautions(p)
        assert any("随餐" in c for c in cautions)

    def test_pregnancy_caution(self):
        p = self._make_profile(conditions="孕期")
        cautions = get_cautions(p)
        assert any("生食" in c or "酒精" in c for c in cautions)

    def test_allergy_caution(self):
        p = self._make_profile(allergies="花生, 海鲜")
        cautions = get_cautions(p)
        allergen_cautions = [c for c in cautions if "过敏原" in c]
        assert len(allergen_cautions) >= 2
        assert any("花生" in c for c in allergen_cautions)
        assert any("海鲜" in c for c in allergen_cautions)

    def test_no_conditions(self):
        p = self._make_profile()
        assert get_cautions(p) == []

    def test_disclaimer_present(self, client):
        """API 响应中包含免责声明。"""
        r = client.get("/api/health/profile")
        assert r.status_code == 200
        assert r.json()["disclaimer"] == HEALTH_DISCLAIMER


class TestQuizScoring:
    """中医体质问卷评分测试。"""

    def test_all_high_qixu(self):
        """全选4（经常）for 气虚质 问题 → 应建议气虚质"""
        # q1, q2 是气虚质
        answers = [
            {"question_id": "q1", "value": 4},
            {"question_id": "q2", "value": 4},
        ]
        scores, suggested = score_quiz(answers)
        assert scores["气虚质"] == 100
        assert suggested == "气虚质"

    def test_all_one_pinghe(self):
        """q11 全选4（平和质问题高分）且其他全选1 → 建议平和质"""
        answers = [
            {"question_id": f"q{i}", "value": 1} for i in range(1, 11)
        ]
        answers.append({"question_id": "q11", "value": 4})
        scores, suggested = score_quiz(answers)
        assert scores["平和质"] > 0
        assert suggested == "平和质"

    def test_empty_answers(self):
        """空答案 → 返回全0分，建议平和质"""
        scores, suggested = score_quiz([])
        assert all(v == 0 for v in scores.values())
        assert suggested == "平和质"

    def test_api_quiz_get(self, client):
        r = client.get("/api/health/constitution-quiz")
        assert r.status_code == 200
        d = r.json()
        assert "questions" in d
        assert len(d["questions"]) >= 9
        assert "disclaimer" in d

    def test_api_quiz_post(self, client):
        answers = [{"question_id": "q1", "value": 4}, {"question_id": "q2", "value": 4}]
        r = client.post("/api/health/constitution-quiz", json={"answers": answers, "save": False})
        assert r.status_code == 200
        d = r.json()
        assert "scores" in d and "suggested" in d

    def test_api_quiz_save(self, client, db):
        answers = [{"question_id": "q3", "value": 4}, {"question_id": "q4", "value": 4}]
        r = client.post("/api/health/constitution-quiz", json={"answers": answers, "save": True})
        assert r.status_code == 200
        assert r.json()["suggested"] == "阳虚质"
        # 验证已写入档案
        pr = client.get("/api/health/profile")
        assert pr.json()["tcm_constitution"] == "阳虚质"


# ---------------------------------------------------------------------------
# Feature 1: 档案 API 测试
# ---------------------------------------------------------------------------

class TestProfileAPI:
    def test_get_creates_empty_profile(self, client):
        r = client.get("/api/health/profile")
        assert r.status_code == 200
        d = r.json()
        assert "bmi" in d
        assert "disclaimer" in d

    def test_put_valid_fields(self, client):
        r = client.put("/api/health/profile", json={
            "gender": "男", "birth_year": 1990,
            "height_cm": 175, "weight_kg": 70,
            "activity_level": "中",
        })
        assert r.status_code == 200
        d = r.json()
        assert d["gender"] == "男"
        assert d["bmi"] == pytest.approx(22.9, abs=0.05)
        assert d["bmi_category"] == "正常"
        assert d["estimated_daily_energy_kcal"] is not None

    def test_put_invalid_height(self, client):
        r = client.put("/api/health/profile", json={"height_cm": 50})
        assert r.status_code == 422

    def test_put_invalid_weight(self, client):
        r = client.put("/api/health/profile", json={"weight_kg": 400})
        assert r.status_code == 422

    def test_put_invalid_birth_year(self, client):
        r = client.put("/api/health/profile", json={"birth_year": 1800})
        assert r.status_code == 422

    def test_put_invalid_gender(self, client):
        r = client.put("/api/health/profile", json={"gender": "未知"})
        assert r.status_code == 422

    def test_put_invalid_activity(self, client):
        r = client.put("/api/health/profile", json={"activity_level": "极高"})
        assert r.status_code == 422

    def test_put_invalid_tcm(self, client):
        r = client.put("/api/health/profile", json={"tcm_constitution": "无效体质"})
        assert r.status_code == 422

    def test_put_invalid_persona(self, client):
        r = client.put("/api/health/profile", json={"persona": "xyz"})
        assert r.status_code == 422

    def test_persona_preset_fills_empty_fields(self, client):
        """应用预设仅填充当前为空的字段。"""
        # 先清空 activity_level
        client.put("/api/health/profile", json={"activity_level": None})
        r = client.put("/api/health/profile", json={"persona": "student"})
        assert r.status_code == 200
        d = r.json()
        assert d["persona"] == "student"
        # 预设应填充活动强度
        assert d["activity_level"] is not None

    def test_persona_preset_apply_defaults_override(self, client):
        """apply_preset_defaults=true 时覆盖已有字段。"""
        # 先设置自定义 activity_level
        client.put("/api/health/profile", json={"activity_level": "高"})
        r = client.put("/api/health/profile", json={
            "persona": "office",
            "apply_preset_defaults": True,
        })
        assert r.status_code == 200
        d = r.json()
        # office 预设的 activity_level 是"低"，应覆盖
        assert d["activity_level"] == "低"

    def test_personas_endpoint(self, client):
        r = client.get("/api/health/personas")
        assert r.status_code == 200
        d = r.json()
        assert "personas" in d
        for key in ("student", "office", "homemaker", "senior", "fitness", "weightloss", "custom"):
            assert key in d["personas"]
            assert "label" in d["personas"][key]
            assert "default_meal_times" in d["personas"][key]

    def test_anon_cannot_access(self, anon_client):
        r = anon_client.get("/api/health/profile")
        assert r.status_code == 401


# ---------------------------------------------------------------------------
# Feature 2: 餐单 API 测试
# ---------------------------------------------------------------------------

class TestMealPlanAPI:
    def test_generate_plan_basic(self, client):
        """生成7天餐单（mock），验证结构和天数。"""
        r = client.post("/api/health/plans", json={"days": 7})
        assert r.status_code == 201
        d = r.json()
        assert "plan" in d
        assert len(d["plan"]["days"]) == 7
        assert "disclaimer" in d
        # 每天有至少一个餐次
        for day in d["plan"]["days"]:
            assert len(day["meals"]) >= 1

    def test_generate_plan_3_days(self, client):
        """生成3天餐单，验证天数正确。"""
        r = client.post("/api/health/plans", json={"days": 3})
        assert r.status_code == 201
        assert len(r.json()["plan"]["days"]) == 3

    def test_generate_plan_allergen_removal(self, client):
        """花生过敏时，含花生的菜品应被移除。"""
        # 设置过敏原
        client.put("/api/health/profile", json={"allergies": "花生"})
        r = client.post("/api/health/plans", json={"days": 1})
        assert r.status_code == 201
        d = r.json()
        # 检查所有菜品名称不含"花生"
        for day in d["plan"]["days"]:
            for meal in day["meals"]:
                for dish in meal["dishes"]:
                    assert "花生" not in dish["name"], f"发现含过敏原菜品: {dish['name']}"
        # 清理
        client.put("/api/health/profile", json={"allergies": None})

    def test_plan_has_cautions_when_conditions(self, client):
        """有疾病时，餐单响应应包含注意事项。"""
        client.put("/api/health/profile", json={"conditions": "高血压"})
        r = client.post("/api/health/plans", json={"days": 1})
        assert r.status_code == 201
        d = r.json()
        assert len(d["cautions"]) > 0
        assert any("盐" in c for c in d["cautions"])
        # 清理
        client.put("/api/health/profile", json={"conditions": None})

    def test_list_plans(self, client):
        r = client.get("/api/health/plans")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_get_plan(self, client):
        r = client.post("/api/health/plans", json={"days": 7})
        plan_id = r.json()["id"]
        r2 = client.get(f"/api/health/plans/{plan_id}")
        assert r2.status_code == 200
        assert r2.json()["id"] == plan_id

    def test_delete_plan(self, client):
        r = client.post("/api/health/plans", json={"days": 7})
        plan_id = r.json()["id"]
        r2 = client.delete(f"/api/health/plans/{plan_id}")
        assert r2.status_code == 204
        assert client.get(f"/api/health/plans/{plan_id}").status_code == 404

    def test_activate_deactivate_plan(self, client):
        """激活计划2时，计划1应变为非活跃。"""
        r1 = client.post("/api/health/plans", json={"days": 7})
        plan_id1 = r1.json()["id"]
        r2 = client.post("/api/health/plans", json={"days": 7})
        plan_id2 = r2.json()["id"]
        # plan2 生成时已设为 active，plan1 应已停用
        p1 = client.get(f"/api/health/plans/{plan_id1}").json()
        p2 = client.get(f"/api/health/plans/{plan_id2}").json()
        assert not p1["is_active"]
        assert p2["is_active"]
        # 激活 plan1
        client.post(f"/api/health/plans/{plan_id1}/activate")
        p1_again = client.get(f"/api/health/plans/{plan_id1}").json()
        p2_again = client.get(f"/api/health/plans/{plan_id2}").json()
        assert p1_again["is_active"]
        assert not p2_again["is_active"]

    def test_slot_regeneration_keeps_other_slots(self, client):
        """重新生成 day_index=0, meal_index=0 后，其余槽不变。"""
        r = client.post("/api/health/plans", json={"days": 3})
        plan_id = r.json()["id"]
        original = client.get(f"/api/health/plans/{plan_id}").json()

        # 记录原始 day1 和 day2 的内容
        original_day1 = original["plan"]["days"][1] if len(original["plan"]["days"]) > 1 else None
        original_day2 = original["plan"]["days"][2] if len(original["plan"]["days"]) > 2 else None

        # 重新生成 day 0, meal 0
        r2 = client.patch(f"/api/health/plans/{plan_id}/slot",
                          json={"day_index": 0, "meal_index": 0, "instruction": "少油"})
        assert r2.status_code == 200
        updated = client.get(f"/api/health/plans/{plan_id}").json()

        # day 1 和 day 2 应未改变
        if original_day1:
            assert updated["plan"]["days"][1] == original_day1
        if original_day2:
            assert updated["plan"]["days"][2] == original_day2

    def test_today_endpoint(self, client):
        """今日端点返回正确结构。"""
        from datetime import date
        r = client.post("/api/health/plans", json={
            "days": 7,
            "start_date": date.today().isoformat(),
        })
        plan_id = r.json()["id"]
        r2 = client.get(f"/api/health/plans/{plan_id}/today")
        assert r2.status_code == 200
        d = r2.json()
        assert "plan_id" in d
        assert "date" in d

    def test_user_isolation(self, client):
        """用户A的餐单不能被用户B访问。"""
        _ensure_user(client, "health_user_b", "health_pass_b_123")
        # 生成一个计划（用admin / tester用户）
        r = client.post("/api/health/plans", json={"days": 1})
        plan_id = r.json()["id"]

        with TestClient(app) as c_b:
            _login(c_b, "health_user_b", "health_pass_b_123")
            # B 不能访问 A 的计划
            assert c_b.get(f"/api/health/plans/{plan_id}").status_code == 404
            assert c_b.delete(f"/api/health/plans/{plan_id}").status_code == 404

    def test_no_kcal_in_rationale(self, client):
        """生成的餐单理由中不含卡路里/kcal等字眼（mock不应输出，过滤器兜底）。"""
        r = client.post("/api/health/plans", json={"days": 1})
        assert r.status_code == 201
        rationale = r.json().get("rationale", {})
        for field in ("nutrition", "tcm"):
            text = rationale.get(field, "")
            assert "卡路里" not in text
            # kcal 检查（case insensitive）
            assert "kcal" not in text.lower()
