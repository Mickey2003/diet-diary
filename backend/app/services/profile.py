"""
健康档案服务：人设预设、档案计算（BMI/能量估算/注意事项）、中医体质问卷。

重要声明：
- BMI、能量估算均为粗略参考，不作为医疗诊断依据。
- 注意事项为关键词匹配的一般性提示，不代替医嘱。
- 中医体质自测为参考性自测，非临床诊断。
"""
import json
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from ..models import Profile

HEALTH_DISCLAIMER = (
    "以下内容为一般性饮食参考，不构成医疗诊断或用药建议；有疾病或用药请遵医嘱。"
)

# ---------------------------------------------------------------------------
# 人设预设
# ---------------------------------------------------------------------------

PERSONAS: Dict[str, Dict[str, Any]] = {
    "student": {
        "label": "学生",
        "description": "在校学生，学习压力较大，三餐可能不规律",
        "default_activity_level": "中",
        "default_meal_times": {"早餐": "07:30", "午餐": "12:00", "晚餐": "18:30", "加餐": "15:30"},
        "typical_goals": "保持精力充沛、营养均衡，避免久坐",
        "typical_preferences_hint": "偏好方便快捷的食物，外卖频率较高",
    },
    "office": {
        "label": "上班族",
        "description": "朝九晚五的办公室工作者，久坐多，外卖/工作餐多",
        "default_activity_level": "低",
        "default_meal_times": {"早餐": "08:00", "午餐": "12:00", "晚餐": "19:00", "加餐": "15:30"},
        "typical_goals": "控制久坐带来的代谢问题，减少外卖依赖",
        "typical_preferences_hint": "午餐多为外卖或工作餐，晚餐偏好家常菜",
    },
    "homemaker": {
        "label": "宝妈/居家",
        "description": "居家照料家庭，有充裕时间烹饪，活动量适中",
        "default_activity_level": "中",
        "default_meal_times": {"早餐": "07:30", "午餐": "11:30", "晚餐": "17:30", "加餐": "15:00"},
        "typical_goals": "为家人提供营养均衡的饮食，注重食材安全",
        "typical_preferences_hint": "喜欢自己烹饪，注重食材新鲜度",
    },
    "senior": {
        "label": "长辈",
        "description": "65岁以上老人，消化功能可能下降，活动量较低",
        "default_activity_level": "低",
        "default_meal_times": {"早餐": "07:00", "午餐": "11:30", "晚餐": "17:00", "加餐": "15:00"},
        "typical_goals": "保持骨骼健康、预防营养不良，控制慢性病",
        "typical_preferences_hint": "偏好清淡易消化食物，少油少盐",
    },
    "fitness": {
        "label": "健身增肌",
        "description": "有规律健身习惯，目标为增肌或提升运动表现",
        "default_activity_level": "高",
        "default_meal_times": {"早餐": "07:00", "午餐": "12:00", "晚餐": "18:00", "加餐": "15:30"},
        "typical_goals": "增加肌肉量，保证训练后恢复",
        "typical_preferences_hint": "重视蛋白质摄入，关注运动前后营养补充",
    },
    "weightloss": {
        "label": "控重",
        "description": "希望通过调整饮食控制体重，减少高热量食物",
        "default_activity_level": "中",
        "default_meal_times": {"早餐": "08:00", "午餐": "12:00", "晚餐": "18:00", "加餐": "15:30"},
        "typical_goals": "减少高糖高脂食物，增加蔬菜和优质蛋白质",
        "typical_preferences_hint": "偏好低脂、低糖、高纤维的食物",
    },
    "custom": {
        "label": "自定义",
        "description": "根据自身情况自定义饮食偏好和目标",
        "default_activity_level": "中",
        "default_meal_times": {"早餐": "07:30", "午餐": "12:00", "晚餐": "18:30"},
        "typical_goals": "根据个人需求自定义",
        "typical_preferences_hint": "根据个人喜好自定义",
    },
}

VALID_PERSONAS = set(PERSONAS.keys())

# ---------------------------------------------------------------------------
# 注意事项关键词规则（非医疗建议，仅为一般性参考）
# ---------------------------------------------------------------------------

# (keywords_list, caution_text)
_CONDITION_CAUTIONS = [
    (["糖尿病", "血糖高", "高血糖"],
     "控制精制主食与含糖饮料，注意餐后血糖，具体请遵医嘱"),
    (["高血压"],
     "建议低盐饮食，每日食盐摄入不超过5g"),
    (["痛风"],
     "限制高嘌呤食物（海鲜、动物内脏、啤酒等），多饮水"),
    (["心脏病", "冠心病", "心衰"],
     "低盐低脂，避免暴饮暴食，具体请遵医嘱"),
    (["肾病", "肾功能不全"],
     "可能需要控制蛋白质和钾磷摄入，请严格遵医嘱"),
    (["高血脂", "高胆固醇"],
     "减少饱和脂肪酸和胆固醇摄入，多吃蔬菜和全谷物"),
    (["孕期", "怀孕", "妊娠"],
     "避免生食、酒精及高汞鱼类，保证叶酸和铁的摄入"),
    (["哺乳", "母乳"],
     "避免生食和酒精，保证蛋白质、钙和碘的摄入"),
]

_MEDICATION_CAUTIONS = [
    (["华法林", "抗凝药"],
     "维生素K摄入需稳定，绿叶菜不要忽多忽少，请咨询医生"),
    (["二甲双胍"],
     "建议随餐服用，相关注意事项请遵医嘱"),
]

# ---------------------------------------------------------------------------
# 中医体质问卷
# ---------------------------------------------------------------------------

CONSTITUTIONS = [
    "平和质", "气虚质", "阳虚质", "阴虚质",
    "痰湿质", "湿热质", "血瘀质", "气郁质", "特禀质",
]

QUIZ_QUESTIONS: List[Dict[str, Any]] = [
    {
        "id": "q1",
        "text": "您容易感到疲乏、气短懒言、说话声音低弱？",
        "constitution": "气虚质",
        "options": [
            {"value": 1, "label": "从不/没有"},
            {"value": 2, "label": "偶尔"},
            {"value": 3, "label": "有时"},
            {"value": 4, "label": "经常/总是"},
        ],
    },
    {
        "id": "q2",
        "text": "您容易出汗、稍微活动就汗流浃背？",
        "constitution": "气虚质",
        "options": [
            {"value": 1, "label": "从不/没有"},
            {"value": 2, "label": "偶尔"},
            {"value": 3, "label": "有时"},
            {"value": 4, "label": "经常/总是"},
        ],
    },
    {
        "id": "q3",
        "text": "您怕冷、手足偏凉、喜热饮食？",
        "constitution": "阳虚质",
        "options": [
            {"value": 1, "label": "从不/没有"},
            {"value": 2, "label": "偶尔"},
            {"value": 3, "label": "有时"},
            {"value": 4, "label": "经常/总是"},
        ],
    },
    {
        "id": "q4",
        "text": "您容易腹泻、大便稀溏，不耐受寒凉食物？",
        "constitution": "阳虚质",
        "options": [
            {"value": 1, "label": "从不/没有"},
            {"value": 2, "label": "偶尔"},
            {"value": 3, "label": "有时"},
            {"value": 4, "label": "经常/总是"},
        ],
    },
    {
        "id": "q5",
        "text": "您感觉手脚心发热、口干咽燥、睡眠不实多梦？",
        "constitution": "阴虚质",
        "options": [
            {"value": 1, "label": "从不/没有"},
            {"value": 2, "label": "偶尔"},
            {"value": 3, "label": "有时"},
            {"value": 4, "label": "经常/总是"},
        ],
    },
    {
        "id": "q6",
        "text": "您体型偏胖、腹部肥满松软、身体沉重不爽快？",
        "constitution": "痰湿质",
        "options": [
            {"value": 1, "label": "从不/没有"},
            {"value": 2, "label": "偶尔"},
            {"value": 3, "label": "有时"},
            {"value": 4, "label": "经常/总是"},
        ],
    },
    {
        "id": "q7",
        "text": "您面部油脂分泌多、容易生粉刺痤疮、口苦口臭？",
        "constitution": "湿热质",
        "options": [
            {"value": 1, "label": "从不/没有"},
            {"value": 2, "label": "偶尔"},
            {"value": 3, "label": "有时"},
            {"value": 4, "label": "经常/总是"},
        ],
    },
    {
        "id": "q8",
        "text": "您皮肤容易出现青紫瘀斑、面色晦暗无光泽？",
        "constitution": "血瘀质",
        "options": [
            {"value": 1, "label": "从不/没有"},
            {"value": 2, "label": "偶尔"},
            {"value": 3, "label": "有时"},
            {"value": 4, "label": "经常/总是"},
        ],
    },
    {
        "id": "q9",
        "text": "您常常闷闷不乐、多愁善感、容易烦躁焦虑、情绪波动大？",
        "constitution": "气郁质",
        "options": [
            {"value": 1, "label": "从不/没有"},
            {"value": 2, "label": "偶尔"},
            {"value": 3, "label": "有时"},
            {"value": 4, "label": "经常/总是"},
        ],
    },
    {
        "id": "q10",
        "text": "您对花粉、食物、药物等容易出现过敏反应（如皮疹、哮喘等）？",
        "constitution": "特禀质",
        "options": [
            {"value": 1, "label": "从不/没有"},
            {"value": 2, "label": "偶尔"},
            {"value": 3, "label": "有时"},
            {"value": 4, "label": "经常/总是"},
        ],
    },
    {
        "id": "q11",
        "text": "您精力充沛、体重适中、适应能力强、心情平稳愉快？",
        "constitution": "平和质",
        "options": [
            {"value": 1, "label": "从不/没有"},
            {"value": 2, "label": "偶尔"},
            {"value": 3, "label": "有时"},
            {"value": 4, "label": "经常/总是"},
        ],
    },
]

QUIZ_NOTE = "本问卷为参考性自测，每道题选择最符合自身状况的选项（1=从不/没有，4=经常/总是）。结果仅供参考，不作临床诊断依据。"


# ---------------------------------------------------------------------------
# 计算辅助函数
# ---------------------------------------------------------------------------

def _bmi(weight_kg: float, height_cm: float) -> float:
    """计算 BMI（保留一位小数）。"""
    h_m = height_cm / 100.0
    return round(weight_kg / (h_m * h_m), 1)


def _bmi_category(bmi: float) -> str:
    """中国成人 BMI 分类。"""
    if bmi < 18.5:
        return "偏瘦"
    if bmi < 24.0:
        return "正常"
    if bmi < 28.0:
        return "超重"
    return "肥胖"


def _energy_estimate(
    weight_kg: float,
    height_cm: float,
    birth_year: int,
    gender: Optional[str],
    activity_level: Optional[str],
) -> int:
    """
    用 Mifflin-St Jeor 公式估算每日能量需求（kcal）。
    注意：粗略估算，仅供参考。
    """
    age = datetime.now().year - birth_year
    bmr_male = 10 * weight_kg + 6.25 * height_cm - 5 * age + 5
    bmr_female = 10 * weight_kg + 6.25 * height_cm - 5 * age - 161

    if gender == "男":
        bmr = bmr_male
    elif gender == "女":
        bmr = bmr_female
    else:
        bmr = (bmr_male + bmr_female) / 2

    factors = {"低": 1.2, "中": 1.375, "高": 1.55}
    factor = factors.get(activity_level or "中", 1.375)
    return round(bmr * factor)


def get_cautions(profile: Profile) -> List[str]:
    """
    根据档案的疾病/用药/过敏关键词生成注意事项列表。
    内容为一般性参考，非医疗建议。
    """
    cautions: List[str] = []
    combined_text = " ".join(filter(None, [
        profile.conditions or "",
        profile.medications or "",
    ]))

    for keywords, caution in _CONDITION_CAUTIONS:
        if any(kw in combined_text for kw in keywords):
            if caution not in cautions:
                cautions.append(caution)

    for keywords, caution in _MEDICATION_CAUTIONS:
        if any(kw in (profile.medications or "") for kw in keywords):
            if caution not in cautions:
                cautions.append(caution)

    # 过敏原提示
    if profile.allergies:
        allergens = [
            a.strip()
            for a in profile.allergies.replace("，", ",").replace("、", ",").split(",")
            if a.strip()
        ]
        for allergen in allergens:
            if allergen:
                cautions.append(f"严格避开过敏原：{allergen}")

    return cautions


# ---------------------------------------------------------------------------
# 档案 CRUD
# ---------------------------------------------------------------------------

def get_or_create_profile(db: Session, user_id: int) -> Profile:
    """获取档案，不存在时创建空档案。"""
    p = db.get(Profile, user_id)
    if p is None:
        p = Profile(user_id=user_id)
        db.add(p)
        db.commit()
        db.refresh(p)
    return p


def compute_profile_out(db: Session, user_id: int) -> Dict[str, Any]:
    """
    返回档案数据 + 计算字段（BMI、能量估算、注意事项）。
    """
    profile = get_or_create_profile(db, user_id)
    current_year = datetime.now().year

    # 计算年龄
    age: Optional[int] = None
    if profile.birth_year:
        age = current_year - profile.birth_year

    # 计算 BMI
    bmi: Optional[float] = None
    bmi_category: Optional[str] = None
    if profile.weight_kg and profile.height_cm:
        bmi = _bmi(profile.weight_kg, profile.height_cm)
        bmi_category = _bmi_category(bmi)

    # 能量估算
    energy: Optional[int] = None
    if profile.weight_kg and profile.height_cm and profile.birth_year:
        energy = _energy_estimate(
            profile.weight_kg, profile.height_cm,
            profile.birth_year, profile.gender, profile.activity_level,
        )

    # 解析 meal_times
    meal_times: Optional[Dict] = None
    if profile.meal_times_json:
        try:
            meal_times = json.loads(profile.meal_times_json)
        except Exception:
            meal_times = None

    cautions = get_cautions(profile)

    return {
        "user_id": profile.user_id,
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
        "meal_times": meal_times,
        "budget_level": profile.budget_level,
        "cooking_ability": profile.cooking_ability,
        "updated_at": profile.updated_at,
        # 计算字段
        "age": age,
        "bmi": bmi,
        "bmi_category": bmi_category,
        "estimated_daily_energy_kcal": energy,
        "estimated_daily_energy_note": "粗略估算（Mifflin-St Jeor），供参考" if energy else None,
        "cautions": cautions,
        "disclaimer": HEALTH_DISCLAIMER,
    }


VALID_GENDERS = {"男", "女", "其他"}
VALID_ACTIVITY_LEVELS = {"低", "中", "高"}
VALID_TCM_CONSTITUTIONS = {
    "平和质", "气虚质", "阳虚质", "阴虚质",
    "痰湿质", "湿热质", "血瘀质", "气郁质", "特禀质",
}


def validate_profile_update(data: Dict[str, Any]) -> List[str]:
    """验证档案更新数据，返回错误列表。"""
    errors: List[str] = []
    current_year = datetime.now().year

    height = data.get("height_cm")
    if height is not None:
        try:
            h = float(height)
            if not (100 <= h <= 250):
                errors.append("身高应在100-250cm之间")
        except (TypeError, ValueError):
            errors.append("身高格式无效")

    weight = data.get("weight_kg")
    if weight is not None:
        try:
            w = float(weight)
            if not (25 <= w <= 300):
                errors.append("体重应在25-300kg之间")
        except (TypeError, ValueError):
            errors.append("体重格式无效")

    birth_year = data.get("birth_year")
    if birth_year is not None:
        try:
            by = int(birth_year)
            if not (1900 <= by <= current_year):
                errors.append(f"出生年份应在1900-{current_year}之间")
        except (TypeError, ValueError):
            errors.append("出生年份格式无效")

    gender = data.get("gender")
    if gender is not None and gender not in VALID_GENDERS:
        errors.append(f"性别应为：{'/'.join(VALID_GENDERS)}")

    activity = data.get("activity_level")
    if activity is not None and activity not in VALID_ACTIVITY_LEVELS:
        errors.append(f"活动强度应为：{'/'.join(VALID_ACTIVITY_LEVELS)}")

    persona = data.get("persona")
    if persona is not None and persona not in VALID_PERSONAS:
        errors.append(f"人设应为：{'/'.join(VALID_PERSONAS)}")

    tcm = data.get("tcm_constitution")
    if tcm is not None and tcm not in VALID_TCM_CONSTITUTIONS:
        errors.append(f"中医体质应为9种标准体质之一")

    return errors


def update_profile(
    db: Session,
    user_id: int,
    data: Dict[str, Any],
    apply_preset_defaults: bool = False,
) -> Profile:
    """
    更新档案字段。
    若 persona 有效且 apply_preset_defaults=True，则用预设覆盖所有默认字段；
    若 apply_preset_defaults=False（默认），则仅填充当前为空的字段。
    """
    profile = get_or_create_profile(db, user_id)

    # 如果设置了 persona，先应用预设
    persona = data.get("persona")
    if persona and persona in PERSONAS:
        preset = PERSONAS[persona]
        preset_activity = preset["default_activity_level"]
        preset_meal_times = json.dumps(preset["default_meal_times"], ensure_ascii=False)

        if apply_preset_defaults:
            # 强制覆盖
            profile.persona = persona
            profile.activity_level = preset_activity
            profile.meal_times_json = preset_meal_times
        else:
            # 仅填充空字段
            profile.persona = persona
            if not profile.activity_level:
                profile.activity_level = preset_activity
            if not profile.meal_times_json:
                profile.meal_times_json = preset_meal_times

    # 应用其他字段更新
    field_map = {
        "gender": "gender",
        "birth_year": "birth_year",
        "height_cm": "height_cm",
        "weight_kg": "weight_kg",
        "activity_level": "activity_level",
        "conditions": "conditions",
        "medications": "medications",
        "allergies": "allergies",
        "preferences": "preferences",
        "tcm_constitution": "tcm_constitution",
        "goals": "goals",
        "budget_level": "budget_level",
        "cooking_ability": "cooking_ability",
    }
    for key, attr in field_map.items():
        if key in data and data[key] is not None:
            setattr(profile, attr, data[key])

    # meal_times 作为 JSON 存储
    if "meal_times" in data and data["meal_times"] is not None:
        profile.meal_times_json = json.dumps(data["meal_times"], ensure_ascii=False)

    db.commit()
    db.refresh(profile)
    return profile


# ---------------------------------------------------------------------------
# 体质问卷
# ---------------------------------------------------------------------------

def get_quiz() -> Dict[str, Any]:
    """返回问卷数据。"""
    return {
        "questions": QUIZ_QUESTIONS,
        "note": QUIZ_NOTE,
        "disclaimer": HEALTH_DISCLAIMER,
    }


def score_quiz(answers: List[Dict[str, Any]]) -> Tuple[Dict[str, int], str]:
    """
    计算问卷得分并返回 (scores_dict, suggested_constitution)。

    scores: {constitution: 0-100}
    suggested: 得分最高的体质（若平和质高且其他均低则优先返回平和质）
    """
    q_map = {q["id"]: q for q in QUIZ_QUESTIONS}

    # 按体质收集原始得分（答案值 - 1 → 0-3）
    raw: Dict[str, List[int]] = {}
    for a in answers:
        qid = a.get("question_id") or a.get("id")
        value = a.get("value") or a.get("answer", 1)
        q = q_map.get(qid)
        if q is None:
            continue
        try:
            v = max(1, min(4, int(value)))
        except (TypeError, ValueError):
            v = 1
        constitution = q["constitution"]
        raw.setdefault(constitution, []).append(v - 1)

    # 计算各体质平均分并缩放至 0-100
    scores: Dict[str, int] = {}
    for c in CONSTITUTIONS:
        vals = raw.get(c, [])
        if vals:
            avg = sum(vals) / len(vals)
            scores[c] = round(avg * 100 / 3)
        else:
            scores[c] = 0

    # 建议体质：得分最高者
    # 特殊情况：平和质得分 ≥70 且其他均 <40 → 建议平和质
    if not scores:
        return scores, "平和质"

    best_c = max(scores, key=lambda k: scores[k])

    if (
        scores.get("平和质", 0) >= 70
        and all(v < 40 for k, v in scores.items() if k != "平和质")
    ):
        suggested = "平和质"
    elif scores[best_c] > 0:
        suggested = best_c
    else:
        suggested = "平和质"

    return scores, suggested
