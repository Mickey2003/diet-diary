"""ORM 模型（v0.3：多用户隔离，所有业务数据挂在 user_id 下）。"""
from datetime import datetime
from typing import List, Optional

from sqlalchemy import (Boolean, Column, DateTime, Float, ForeignKey, Integer,
                        String, Table, Text, UniqueConstraint)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base

# 菜品 <-> 标签 多对多
meal_item_tags = Table(
    "meal_item_tags",
    Base.metadata,
    Column("item_id", Integer, ForeignKey("meal_items.id", ondelete="CASCADE"), primary_key=True),
    Column("tag_code", String(40), ForeignKey("tags.code", ondelete="CASCADE"), primary_key=True),
)


class Tag(Base):
    __tablename__ = "tags"
    code: Mapped[str] = mapped_column(String(40), primary_key=True)
    name_zh: Mapped[str] = mapped_column(String(40), nullable=False)
    group: Mapped[str] = mapped_column(String(20), nullable=False)  # watch / structure
    is_watch: Mapped[bool] = mapped_column(Boolean, default=False)
    description: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)


# ---------- 用户与认证 ----------
class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(40), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(200), nullable=False)
    role: Mapped[str] = mapped_column(String(10), default="user")  # admin / user
    display_name: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_approved: Mapped[bool] = mapped_column(Boolean, default=True)  # 注册审核：False = 待管理员审核
    totp_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    totp_secret: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    totp_pending_secret: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    backup_codes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # JSON: 已哈希的备用码
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"


class AuthSession(Base):
    __tablename__ = "auth_sessions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    ip: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class ApiToken(Base):
    """个人访问令牌：供 MCP 客户端、移动 App、脚本使用（Authorization: Bearer ddt_...）。"""
    __tablename__ = "api_tokens"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(60), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    prefix: Mapped[str] = mapped_column(String(12), nullable=False)  # 便于识别：ddt_xxxx
    scopes: Mapped[str] = mapped_column(String(200), default="all")  # all / read / mcp / app
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    last_used_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


class UserSetting(Base):
    """按用户存放的键值设置（通知配置、界面偏好等）。"""
    __tablename__ = "user_settings"
    __table_args__ = (UniqueConstraint("user_id", "key", name="uq_user_setting"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    key: Mapped[str] = mapped_column(String(60), nullable=False)
    value: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


# ---------- 餐食 ----------
class Meal(Base):
    __tablename__ = "meals"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=True)
    eaten_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    meal_type: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    image_path: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    ai_model: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    ai_raw_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # 模型原始返回
    ai_latency_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    confirmed: Mapped[bool] = mapped_column(Boolean, default=True)
    source: Mapped[str] = mapped_column(String(20), default="photo")  # photo / manual / barcode / import / mcp
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now)

    items: Mapped[List["MealItem"]] = relationship(
        "MealItem", back_populates="meal", cascade="all, delete-orphan",
        order_by="MealItem.sort_order", lazy="selectin",
    )


class MealItem(Base):
    __tablename__ = "meal_items"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    meal_id: Mapped[int] = mapped_column(ForeignKey("meals.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    category: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    portion: Mapped[str] = mapped_column(String(4), default="中")
    confidence: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    source: Mapped[str] = mapped_column(String(12), default="ai")  # ai / ai_edited / user / barcode
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    barcode: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    kcal: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)            # 估算千卡（一份）
    kcal_source: Mapped[Optional[str]] = mapped_column(String(12), nullable=True)  # ai / table / category / user / barcode

    meal: Mapped["Meal"] = relationship("Meal", back_populates="items")
    tags: Mapped[List[Tag]] = relationship("Tag", secondary=meal_item_tags, lazy="selectin")


class PackagedFood(Base):
    """条形码商品缓存（来源 Open Food Facts 或用户手动补录）。"""
    __tablename__ = "packaged_foods"
    barcode: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    brand: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    category: Mapped[str] = mapped_column(String(20), default="其他")
    tags: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)  # JSON list of tag codes
    nutriments_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    image_url: Mapped[Optional[str]] = mapped_column(String(400), nullable=True)
    source: Mapped[str] = mapped_column(String(20), default="openfoodfacts")  # openfoodfacts / manual
    raw_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_by: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now)


# ---------- 全局设置（仅管理员可改：模型 API 等） ----------
class Setting(Base):
    __tablename__ = "settings"
    key: Mapped[str] = mapped_column(String(60), primary_key=True)
    value: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


# ---------- 报告 / 查询 / 通知日志 ----------
class Report(Base):
    __tablename__ = "reports"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=True)
    period_type: Mapped[str] = mapped_column(String(10), nullable=False)  # week / month
    period_start: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    period_end: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    facts_json: Mapped[str] = mapped_column(Text, nullable=False)
    summary_md: Mapped[str] = mapped_column(Text, nullable=False)
    unverified_numbers: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # JSON 数组
    model: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class QueryLog(Base):
    __tablename__ = "query_logs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=True)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    plan_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    sql_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    result_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    answer_md: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="ok")  # ok / unsupported / error
    model: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class NotifyLog(Base):
    __tablename__ = "notify_logs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=True)
    kind: Mapped[str] = mapped_column(String(30), nullable=False, index=True)  # test / daily_reminder / daily_summary / weekly_report / manual
    channel: Mapped[str] = mapped_column(String(30), nullable=False)
    ok: Mapped[bool] = mapped_column(Boolean, default=False)
    detail: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, index=True)


# ---------- 模型调用用量（用于用量统计与费用估算） ----------
class LlmUsage(Base):
    __tablename__ = "llm_usage"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True, nullable=True)
    provider: Mapped[str] = mapped_column(String(30), nullable=False)
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    task: Mapped[str] = mapped_column(String(30), nullable=False, index=True)  # vision / plan / explain / report / meal_plan / memory_extract / share_copy ...
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    ok: Mapped[bool] = mapped_column(Boolean, default=True)
    error: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, index=True)


# ---------- 移动端：设备与收件箱（App 轮询取消息，显示系统通知） ----------
class Device(Base):
    __tablename__ = "devices"
    __table_args__ = (UniqueConstraint("user_id", "device_id", name="uq_user_device"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    device_id: Mapped[str] = mapped_column(String(80), nullable=False)
    name: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    platform: Mapped[str] = mapped_column(String(20), default="android")
    app_version: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class InboxMessage(Base):
    __tablename__ = "inbox_messages"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(30), nullable=False)
    title: Mapped[str] = mapped_column(String(120), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    url: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)  # 点击跳转的站内路径
    extra: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # JSON：如 {"sound_url": "...", "markdown": true}
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, index=True)
    read_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


class SoundFile(Base):
    """用户上传的提醒音效；is_system=True 为管理员上传的系统预设（所有用户可用）。内置合成预设不入库。"""
    __tablename__ = "sound_files"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(60), nullable=False)
    filename: Mapped[str] = mapped_column(String(120), nullable=False)
    mime: Mapped[str] = mapped_column(String(40), default="audio/mpeg")
    size: Mapped[int] = mapped_column(Integer, default=0)
    is_system: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


# ---------- 健康档案 / 餐单 / 记忆 ----------
class Profile(Base):
    __tablename__ = "profiles"
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    persona: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)  # student / office / homemaker / senior / fitness / custom
    gender: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)   # 男 / 女 / 其他
    birth_year: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    height_cm: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    weight_kg: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    activity_level: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)  # 低 / 中 / 高
    conditions: Mapped[Optional[str]] = mapped_column(Text, nullable=True)     # 疾病（自由文本）
    medications: Mapped[Optional[str]] = mapped_column(Text, nullable=True)    # 用药（自由文本）
    allergies: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    preferences: Mapped[Optional[str]] = mapped_column(Text, nullable=True)    # 喜好 / 忌口
    tcm_constitution: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)  # 中医体质（自报或问卷）
    goals: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    meal_times_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # {"早餐":"07:30",...}
    budget_level: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    cooking_ability: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now)


class MealPlan(Base):
    __tablename__ = "meal_plans"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(80), nullable=False)
    start_date: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    days: Mapped[int] = mapped_column(Integer, default=7)
    plan_json: Mapped[str] = mapped_column(Text, nullable=False)       # 每天每餐的菜单、时间、要点
    rationale_md: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # 中医 + 营养视角说明
    cautions_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # 程序生成的注意事项
    profile_snapshot_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    model: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now)


class PlanVersion(Base):
    """餐单历史版本（用于界面化回退：应用替换/编辑/重生成前自动备份）。"""
    __tablename__ = "plan_versions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    plan_id: Mapped[int] = mapped_column(ForeignKey("meal_plans.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    reason: Mapped[str] = mapped_column(String(120), default="")  # 版本产生原因
    plan_json: Mapped[str] = mapped_column(Text, nullable=False)  # 该版本完整餐单快照
    days: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, index=True)


class Memory(Base):
    __tablename__ = "memories"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    content: Mapped[str] = mapped_column(String(300), nullable=False)
    category: Mapped[str] = mapped_column(String(20), default="preference")  # preference / habit / health / goal / fact
    source: Mapped[str] = mapped_column(String(20), default="auto")  # auto / user
    importance: Mapped[int] = mapped_column(Integer, default=3)  # 1-5
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    evidence: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # 抽取依据
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    last_used_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
