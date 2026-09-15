"""Pydantic 请求 / 响应 / AI 结构化输出 Schema。"""
from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .services.tags import CATEGORIES, MEAL_TYPES, PORTIONS

Category = Literal["主食", "蛋白质", "蔬菜", "水果", "饮品", "甜点零食", "汤", "其他"]
MealType = Literal["早餐", "午餐", "晚餐", "加餐", "饮品"]
Portion = Literal["少", "中", "多"]


# ---------- AI 视觉识别输出（严格校验） ----------
class VisionItem(BaseModel):
    model_config = ConfigDict(extra="ignore")
    name: str = Field(..., min_length=1, max_length=80, description="菜品名，中文")
    category: Category = "其他"
    portion: Portion = "中"
    tags: List[str] = Field(default_factory=list, description="标签 code 或中文名")
    confidence: float = Field(0.5, ge=0, le=1)
    kcal: Optional[int] = Field(None, ge=0, le=5000, description="该份食物的粗略热量估算（千卡）")
    kcal_source: Optional[str] = None

    @field_validator("kcal", mode="before")
    @classmethod
    def _kcal(cls, v: Any) -> Any:
        if v is None or v == "":
            return None
        try:
            f = float(v)
        except (TypeError, ValueError):
            return None
        return int(min(5000, max(0, f)))

    @field_validator("category", mode="before")
    @classmethod
    def _cat(cls, v: Any) -> Any:
        return v if v in CATEGORIES else "其他"

    @field_validator("portion", mode="before")
    @classmethod
    def _portion(cls, v: Any) -> Any:
        return v if v in PORTIONS else "中"

    @field_validator("confidence", mode="before")
    @classmethod
    def _conf(cls, v: Any) -> Any:
        try:
            f = float(v)
        except (TypeError, ValueError):
            return 0.5
        return min(1.0, max(0.0, f))


class VisionResult(BaseModel):
    model_config = ConfigDict(extra="ignore")
    items: List[VisionItem] = Field(default_factory=list, max_length=20)
    meal_type_guess: Optional[MealType] = None
    overall_note: str = ""
    uncertainty: str = Field("", description="模型自述的不确定之处")

    @field_validator("meal_type_guess", mode="before")
    @classmethod
    def _mt(cls, v: Any) -> Any:
        return v if v in MEAL_TYPES else None


class RecognizeOut(BaseModel):
    image_path: str
    result: Optional[VisionResult]
    fallback: bool = False
    warnings: List[str] = Field(default_factory=list)
    model: Optional[str] = None
    latency_ms: Optional[int] = None
    raw: Optional[str] = None
    disclaimer: str


# ---------- 餐食记录 ----------
class TagOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    code: str
    name_zh: str
    group: str
    is_watch: bool
    description: Optional[str] = None


class MealItemIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=80)
    category: Category = "其他"
    portion: Portion = "中"
    tags: List[str] = Field(default_factory=list)
    confidence: Optional[float] = None
    source: Literal["ai", "ai_edited", "user", "barcode"] = "user"
    barcode: Optional[str] = Field(None, max_length=32)
    kcal: Optional[int] = Field(None, ge=0, le=5000)
    kcal_source: Optional[Literal["ai", "table", "category", "user", "barcode"]] = None


class MealItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    category: str
    portion: str
    confidence: Optional[float]
    source: str
    barcode: Optional[str] = None
    kcal: Optional[int] = None
    kcal_source: Optional[str] = None
    tags: List[TagOut]


def _to_local_naive(v: Any) -> Any:
    """前端若传了带时区的时间（如 ...Z），统一换算到本地时区并去掉 tzinfo，避免差 8 小时。"""
    if isinstance(v, datetime) and v.tzinfo is not None:
        from .services.timeutil import to_local_naive
        return to_local_naive(v)
    return v


class MealCreate(BaseModel):
    eaten_at: datetime
    meal_type: MealType

    @field_validator("eaten_at", mode="after")
    @classmethod
    def _eaten_at_local(cls, v: datetime) -> datetime:
        return _to_local_naive(v)
    image_path: Optional[str] = None
    note: Optional[str] = None
    ai_model: Optional[str] = None
    ai_raw_json: Optional[str] = None
    ai_latency_ms: Optional[int] = None
    source: Optional[Literal["photo", "manual", "barcode", "import", "mcp"]] = "photo"
    items: List[MealItemIn] = Field(default_factory=list)


class MealUpdate(BaseModel):
    eaten_at: Optional[datetime] = None
    meal_type: Optional[MealType] = None
    note: Optional[str] = None
    items: Optional[List[MealItemIn]] = None

    @field_validator("eaten_at", mode="after")
    @classmethod
    def _eaten_at_local(cls, v: Optional[datetime]) -> Optional[datetime]:
        return _to_local_naive(v)


class MealOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    eaten_at: datetime
    meal_type: str
    image_path: Optional[str]
    image_url: Optional[str] = None
    thumb_url: Optional[str] = None
    note: Optional[str]
    ai_model: Optional[str]
    ai_raw_json: Optional[str]
    ai_latency_ms: Optional[int]
    confirmed: bool
    source: str = "photo"
    created_at: datetime
    updated_at: datetime
    items: List[MealItemOut]
    kcal_total: Optional[int] = None  # 各菜品估算之和（估算）


class MealPage(BaseModel):
    total: int
    page: int
    page_size: int
    items: List[MealOut]


# ---------- 自然语言查询：受限查询计划 ----------
Metric = Literal["count_meals", "count_items", "count_tag", "ratio_category",
                 "list_meals", "avg_meals_per_day", "top_items"]
TimePreset = Literal["today", "yesterday", "this_week", "last_week", "last_7d", "last_30d",
                     "this_month", "last_month", "all", "custom"]
GroupBy = Literal["none", "day", "meal_type", "category", "tag", "weekday"]


class TimeRange(BaseModel):
    model_config = ConfigDict(extra="ignore")
    preset: TimePreset = "this_week"
    start: Optional[str] = None  # YYYY-MM-DD，仅 custom 时使用
    end: Optional[str] = None


class QueryFilters(BaseModel):
    model_config = ConfigDict(extra="ignore")
    tags: List[str] = Field(default_factory=list)
    categories: List[str] = Field(default_factory=list)
    meal_types: List[str] = Field(default_factory=list)
    name_contains: Optional[str] = None
    hour_from: Optional[int] = Field(None, ge=0, le=23)
    hour_to: Optional[int] = Field(None, ge=0, le=24)


class QueryPlan(BaseModel):
    model_config = ConfigDict(extra="ignore")
    metric: Metric = "count_meals"
    time_range: TimeRange = Field(default_factory=TimeRange)
    filters: QueryFilters = Field(default_factory=QueryFilters)
    group_by: GroupBy = "none"
    limit: int = Field(10, ge=1, le=100)
    unsupported: bool = False
    unsupported_reason: Optional[str] = None


class QueryIn(BaseModel):
    question: str = Field(..., min_length=1, max_length=300)


class QueryOut(BaseModel):
    id: int
    question: str
    status: str
    plan: Optional[QueryPlan]
    sql: Optional[str]
    rows: List[Dict[str, Any]]
    answer: str
    warnings: List[str] = Field(default_factory=list)
    model: Optional[str] = None
    disclaimer: str


# ---------- 报告 ----------
class ReportCreate(BaseModel):
    period_type: Literal["week", "month"] = "week"
    anchor: Optional[str] = None  # YYYY-MM-DD，所在周/月；默认今天


class ReportOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    period_type: str
    period_start: datetime
    period_end: datetime
    facts: Dict[str, Any]
    summary_md: str
    unverified_numbers: List[str]
    model: Optional[str]
    created_at: datetime


# ---------- 设置 ----------
class SettingsOut(BaseModel):
    provider: str
    base_url: str
    text_model: str
    fast_model: str = ""
    vision_model: str
    image_model: str = ""  # 餐单菜品配图模型（OpenAI 兼容 images.generate），空则不生成配图
    api_key_masked: str
    has_api_key: bool
    source: str  # env / db / mixed
    presets: Dict[str, Dict[str, str]]
    can_edit: bool = False  # 仅管理员可修改模型设置
    vision_async: bool = False  # 默认关闭，避免快速识图时通知冗余
    net_proxy_mode: str = "auto"  # 网络加速模式：auto / on / off
    net_proxy_url: str = ""       # 前缀代理地址
    barcode_sources: str = ""     # 启用的条码数据源（逗号分隔），空表示全部启用
    dish_ai_images: bool = False  # 是否启用 AI 生图（默认关闭，避免 token/限流）
    barcode_source_options: Dict[str, str] = {}  # 数据源 id -> 中文说明

    # ---------- 生图专用配置（v0.8.6，与文本/识图模型解耦） ----------
    image_provider: str = ""           # senseaudio / openai / custom
    image_base_url: str = ""
    image_model_id: str = ""           # 生图专用模型 id（与旧字段 image_model 区分）
    image_key_masked: str = ""         # 掩码后的 key
    has_image_key: bool = False
    image_size: str = "1024x1024"
    image_providers: List[Dict[str, Any]] = []  # 可选提供商与模型能力清单
    image_ready: bool = False          # 生图是否已配置可用
    image_emoji_fallback: bool = True  # 无图时是否用 emoji 兜底（默认开）


class SettingsIn(BaseModel):
    provider: Optional[str] = None
    base_url: Optional[str] = None
    text_model: Optional[str] = None
    fast_model: Optional[str] = None
    vision_model: Optional[str] = None
    image_model: Optional[str] = None
    vision_async: Optional[bool] = None
    net_proxy_mode: Optional[str] = None
    barcode_sources: Optional[str] = None
    dish_ai_images: Optional[bool] = None
    api_key: Optional[str] = None  # 传空字符串表示不修改；传 "__clear__" 表示清空
    # 生图专用配置（image_model_id 与旧字段 image_model 严格区分）
    image_provider: Optional[str] = None
    image_base_url: Optional[str] = None
    image_model_id: Optional[str] = None
    image_size: Optional[str] = None
    image_api_key: Optional[str] = None  # 同上：空串不修改，"__clear__" 清空
    image_emoji_fallback: Optional[bool] = None


class ConnectionTestOut(BaseModel):
    ok: bool
    message: str
    latency_ms: Optional[int] = None
    model: Optional[str] = None
