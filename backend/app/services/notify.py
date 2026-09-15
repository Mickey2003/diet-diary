"""
通知服务（v0.3 按用户隔离）：配置读写（密钥掩码）、消息生成、发送、定时任务、App 收件箱。

- 每个用户有自己的通知配置（user_settings.key = notify_config）与发送日志。
- "inbox" 是内置渠道：写入 inbox_messages，移动 App 轮询后显示系统通知；默认启用。
- 定时任务在 FastAPI lifespan 中以后台线程运行，每 30 秒遍历所有启用用户：
    daily_reminder / daily_summary / weekly_report，每种每天最多触发一次（以 notify_logs 为准）。
"""
import copy
import json
import re
import threading
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import InboxMessage, Meal, NotifyLog, User, UserSetting
from . import notify_channels as ch
from .notify_channels import Message
from .timeutil import now_local, today_local, week_bounds

CONFIG_KEY = "notify_config"
MASK = "••••••••"

SCHEDULE_DEFAULTS: Dict[str, Dict[str, Any]] = {
    "daily_reminder": {"enabled": False, "time": "20:30", "only_if_no_meals": True},
    "daily_summary": {"enabled": False, "time": "21:30"},
    "weekly_report": {"enabled": False, "weekday": 1, "time": "09:00"},  # weekday: 1=周一 … 7=周日
}

KIND_LABELS = {"daily_reminder": "每日记录提醒", "daily_summary": "每日小结", "weekly_report": "周报推送",
               "test": "测试消息", "manual": "手动发送"}

INBOX_META = {
    "key": "inbox", "label": "App 通知（系统消息栏）",
    "help": "安装 Android App 并登录后，App 会定期拉取这里的消息并显示到系统通知栏，无需任何第三方推送服务。",
    "fields": [],
}


# ---------- 配置 ----------
def default_config() -> Dict[str, Any]:
    channels = copy.deepcopy(ch.CHANNEL_DEFAULTS)
    channels["inbox"] = {"enabled": True}
    return {"channels": channels, "schedules": copy.deepcopy(SCHEDULE_DEFAULTS)}


def _merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    out = copy.deepcopy(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def _row(db: Session, user_id: int) -> Optional[UserSetting]:
    return db.query(UserSetting).filter(UserSetting.user_id == user_id, UserSetting.key == CONFIG_KEY).first()


def load_config(db: Session, user_id: int) -> Dict[str, Any]:
    row = _row(db, user_id)
    if not row or not row.value:
        return default_config()
    try:
        return _merge(default_config(), json.loads(row.value))
    except json.JSONDecodeError:
        return default_config()


def save_config(db: Session, user_id: int, cfg: Dict[str, Any]) -> None:
    row = _row(db, user_id)
    if row is None:
        db.add(UserSetting(user_id=user_id, key=CONFIG_KEY, value=json.dumps(cfg, ensure_ascii=False)))
    else:
        row.value = json.dumps(cfg, ensure_ascii=False)
    db.commit()


def mask_config(cfg: Dict[str, Any]) -> Dict[str, Any]:
    out = copy.deepcopy(cfg)
    for key, fields in ch.SECRET_FIELDS.items():
        c = out["channels"].get(key, {})
        for f in fields:
            c[f] = MASK if c.get(f) else ""
    return out


def apply_update(db: Session, user_id: int, incoming: Dict[str, Any]) -> Dict[str, Any]:
    """合并前端提交：密文字段为空或为掩码 → 保留旧值；'__clear__' → 清空。"""
    current = load_config(db, user_id)
    merged = _merge(current, incoming or {})
    for key, fields in ch.SECRET_FIELDS.items():
        new_c = (incoming or {}).get("channels", {}).get(key, {})
        for f in fields:
            v = new_c.get(f)
            if v is None or v == "" or v == MASK:
                merged["channels"][key][f] = current["channels"][key].get(f, "")
            elif v == "__clear__":
                merged["channels"][key][f] = ""
    for k, s in merged["schedules"].items():
        t = str(s.get("time", SCHEDULE_DEFAULTS[k]["time"]))
        if not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", t):
            s["time"] = SCHEDULE_DEFAULTS[k]["time"]
    wd = merged["schedules"]["weekly_report"].get("weekday", 1)
    if not isinstance(wd, int) or not 1 <= wd <= 7:
        merged["schedules"]["weekly_report"]["weekday"] = 1
    save_config(db, user_id, merged)
    return merged


def enabled_channels(cfg: Dict[str, Any]) -> List[str]:
    return [k for k, c in cfg["channels"].items() if c.get("enabled")]


def channel_meta() -> List[Dict[str, Any]]:
    return [INBOX_META] + ch.CHANNEL_META


# ---------- 消息内容 ----------
def _md_to_html(md: str) -> str:
    html_lines: List[str] = []
    in_list = False
    for line in md.split("\n"):
        line_html = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", line)
        if line.startswith("- "):
            if not in_list:
                html_lines.append("<ul>")
                in_list = True
            html_lines.append(f"<li>{line_html[2:]}</li>")
            continue
        if in_list:
            html_lines.append("</ul>")
            in_list = False
        if line.startswith("## "):
            html_lines.append(f"<h3>{line_html[3:]}</h3>")
        elif line.startswith("# "):
            html_lines.append(f"<h2>{line_html[2:]}</h2>")
        elif line.strip():
            html_lines.append(f"<p>{line_html}</p>")
    if in_list:
        html_lines.append("</ul>")
    return "\n".join(html_lines)


def _md_to_text(md: str) -> str:
    t = re.sub(r"\*\*(.+?)\*\*", r"\1", md)
    t = re.sub(r"^#+\s*", "", t, flags=re.MULTILINE)
    return t.strip()


def compose_test() -> Message:
    return Message(title="【今天吃得怎么样】测试消息",
                   text=f"通知渠道配置成功！这是一条测试消息。\n发送时间：{now_local().strftime('%Y-%m-%d %H:%M')}",
                   sms_params=[])


def _today_meals(db: Session, user_id: int) -> List[Meal]:
    t = today_local()
    start = datetime.combine(t, datetime.min.time())
    return list(db.scalars(select(Meal).where(Meal.user_id == user_id, Meal.eaten_at >= start,
                                              Meal.eaten_at < start + timedelta(days=1))
                           .order_by(Meal.eaten_at)).all())


def compose_daily_reminder(db: Session, user_id: int) -> Optional[Message]:
    if _today_meals(db, user_id):
        return None  # 调用方按 only_if_no_meals 决定是否仍发送
    return Message(title="【今天吃得怎么样】今天还没有记录", text="今天还没有记录任何一餐，花 10 秒拍张照片吧 📷", sms_params=[])


def compose_daily_summary(db: Session, user_id: int) -> Message:
    meals = _today_meals(db, user_id)
    t = today_local()
    if not meals:
        return Message(title=f"【今天吃得怎么样】{t.month}月{t.day}日小结",
                       text="今天没有记录任何一餐。", sms_params=["0", "0"])
    lines = [f"今天共记录 **{len(meals)}** 餐："]
    watch: Dict[str, int] = {}
    for m in meals:
        names = "、".join(i.name for i in m.items) or "（无菜品）"
        lines.append(f"- {m.eaten_at.strftime('%H:%M')} {m.meal_type}：{names}")
        for i in m.items:
            for tg in i.tags:
                if tg.is_watch:
                    watch[tg.name_zh] = watch.get(tg.name_zh, 0) + 1
    if watch:
        lines.append("")
        lines.append("值得留意：" + "，".join(f"{k} {v} 次" for k, v in sorted(watch.items(), key=lambda x: -x[1])))
    md = "\n".join(lines)
    sugary = watch.get("含糖饮料", 0)
    return Message(title=f"【今天吃得怎么样】{t.month}月{t.day}日小结", text=_md_to_text(md), markdown=md,
                   html=_md_to_html(md), sms_params=[str(len(meals)), str(sugary)])


def compose_weekly_report(db: Session, user_id: int) -> Message:
    from .report import generate_report  # 延迟导入避免循环
    last_week_day = today_local() - timedelta(days=7)
    anchor = week_bounds(last_week_day)[0].isoformat()
    report = generate_report(db, "week", anchor, user_id)
    facts = json.loads(report.facts_json)
    md = report.summary_md
    sugary = next((w["count"] for w in facts.get("watch_tags", []) if w["code"] == "sugary_drink"), 0)
    return Message(title=f"【今天吃得怎么样】{facts['period']['label']} 周报", text=_md_to_text(md), markdown=md,
                   html=_md_to_html(md), sms_params=[str(facts.get("meal_count", 0)), str(sugary)])


def compose(db: Session, user_id: int, kind: str, cfg: Optional[Dict[str, Any]] = None) -> Optional[Message]:
    cfg = cfg or load_config(db, user_id)
    if kind == "test":
        return compose_test()
    if kind == "daily_reminder":
        msg = compose_daily_reminder(db, user_id)
        if msg is None and not cfg["schedules"]["daily_reminder"].get("only_if_no_meals", True):
            return Message(title="【今天吃得怎么样】记录提醒", text="别忘了记录今天的饮食 📷", sms_params=[])
        return msg
    if kind == "daily_summary":
        return compose_daily_summary(db, user_id)
    if kind == "weekly_report":
        return compose_weekly_report(db, user_id)
    raise ValueError(f"未知的消息类型：{kind}")


# ---------- 发送 ----------
KIND_URLS = {"daily_reminder": "/", "daily_summary": "/timeline", "weekly_report": "/reports", "test": "/notify",
             "manual": "/notify", "meal_alert": "/health", "admin_notice": "/admin/users"}
KIND_LABELS["meal_alert"] = "就餐提醒"
KIND_LABELS["admin_notice"] = "管理通知"


# ---------- 就餐音效提醒（基于激活餐单的用餐时间） ----------
def run_meal_alerts_for_user(db: Session, user_id: int, now: datetime) -> List[Dict[str, Any]]:
    """到达（或提前 lead_minutes 到达）餐单里的用餐时间时，向收件箱写入带音效的提醒；每餐每天一次。"""
    from ..models import MealPlan
    from .sounds import get_alert_settings, resolve_sound_url

    cfg = get_alert_settings(db, user_id)
    if not cfg.get("enabled"):
        return []
    plan = db.query(MealPlan).filter(MealPlan.user_id == user_id, MealPlan.is_active == True).first()  # noqa: E712
    if plan is None:
        return []
    try:
        days = json.loads(plan.plan_json).get("days", [])
    except Exception:  # noqa: BLE001
        return []
    today_str = now.date().isoformat()
    today = next((d for d in days if d.get("date") == today_str), None)
    if not today:
        return []
    results: List[Dict[str, Any]] = []
    lead = int(cfg.get("lead_minutes") or 0)
    for meal in today.get("meals", []):
        mt = meal.get("meal_type", "")
        if cfg.get("meal_types") and mt not in cfg["meal_types"]:
            continue
        t = str(meal.get("time") or "")
        if not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", t):
            continue
        hh, mm = int(t[:2]), int(t[3:])
        fire_at = datetime.combine(now.date(), datetime.min.time()).replace(hour=hh, minute=mm) - timedelta(minutes=lead)
        # 在触发时刻起 2 分钟内触发一次（定时器每 30 秒跑一次）
        if not (fire_at <= now < fire_at + timedelta(minutes=2)):
            continue
        marker = f"{today_str}|{mt}|{t}"
        start = datetime.combine(now.date(), datetime.min.time())
        already = db.query(NotifyLog).filter(NotifyLog.user_id == user_id, NotifyLog.kind == "meal_alert",
                                             NotifyLog.created_at >= start, NotifyLog.detail == marker).count() > 0
        if already:
            continue
        dishes = "、".join(d.get("name", "") for d in meal.get("dishes", []) if d.get("name")) or "按餐单安排"
        title = f"到{mt}时间了" if lead == 0 else f"{lead} 分钟后到{mt}时间"
        msg = Message(title=f"【就餐提醒】{title}", text=f"{t} {mt}：{dishes}\n{meal.get('tip', '')}".strip(), sms_params=[])
        extra = {"sound_url": resolve_sound_url(db, user_id, cfg["sound"]), "volume": cfg.get("volume", 0.8),
                 "vibrate": cfg.get("vibrate", True), "meal_type": mt, "time": t}
        ok, detail = send_inbox(db, user_id, msg, "meal_alert", extra=extra)
        db.add(NotifyLog(user_id=user_id, kind="meal_alert", channel="inbox", ok=ok, detail=marker))
        db.commit()
        results.append({"channel": "inbox", "ok": ok, "detail": detail, "meal_type": mt})
    return results


def send_inbox(db: Session, user_id: int, msg: Message, kind: str,
               extra: Optional[Dict[str, Any]] = None) -> Tuple[bool, str]:
    # 优先保存 Markdown 原文（周报等），前端消息详情用 Markdown 渲染
    body = (msg.markdown or msg.text or "")[:6000]
    payload: Dict[str, Any] = {"markdown": bool(msg.markdown)}
    if extra:
        payload.update(extra)
    db.add(InboxMessage(user_id=user_id, kind=kind, title=msg.title, body=body,
                        url=KIND_URLS.get(kind, "/"), extra=json.dumps(payload, ensure_ascii=False)))
    db.commit()
    return True, "已写入 App 收件箱"


def send_to_channel(db: Session, user_id: int, channel: str, msg: Message, kind: str,
                    cfg: Optional[Dict[str, Any]] = None) -> Tuple[bool, str]:
    cfg = cfg or load_config(db, user_id)
    if channel == "inbox":
        ok, detail = send_inbox(db, user_id, msg, kind)
    else:
        sender = ch.SENDERS.get(channel)
        if sender is None:
            return False, f"未知渠道：{channel}"
        ok, detail = sender(cfg["channels"].get(channel, {}), msg)
    db.add(NotifyLog(user_id=user_id, kind=kind, channel=channel, ok=ok, detail=detail[:1000]))
    db.commit()
    return ok, detail


def broadcast(db: Session, user_id: int, kind: str, msg: Message,
              cfg: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    cfg = cfg or load_config(db, user_id)
    results = []
    for channel in enabled_channels(cfg):
        ok, detail = send_to_channel(db, user_id, channel, msg, kind, cfg)
        results.append({"channel": channel, "ok": ok, "detail": detail})
    if not results:
        db.add(NotifyLog(user_id=user_id, kind=kind, channel="-", ok=False, detail="没有启用任何通知渠道"))
        db.commit()
    return results


# ---------- 定时 ----------
def _sent_today(db: Session, user_id: int, kind: str, today: date) -> bool:
    start = datetime.combine(today, datetime.min.time())
    return db.query(NotifyLog).filter(NotifyLog.user_id == user_id, NotifyLog.kind == kind,
                                      NotifyLog.created_at >= start).count() > 0


def due_kinds(cfg: Dict[str, Any], now: datetime, db: Session, user_id: int) -> List[str]:
    """返回此刻应触发、且今天尚未触发过的任务类型（纯逻辑，便于测试）。"""
    due: List[str] = []
    hhmm = now.strftime("%H:%M")
    for kind, s in cfg["schedules"].items():
        if not s.get("enabled"):
            continue
        if s.get("time") != hhmm:
            continue
        if kind == "weekly_report" and now.isoweekday() != int(s.get("weekday", 1)):
            continue
        if _sent_today(db, user_id, kind, now.date()):
            continue
        due.append(kind)
    return due


def run_due_for_user(db: Session, user_id: int, now: datetime) -> List[Dict[str, Any]]:
    cfg = load_config(db, user_id)
    results: List[Dict[str, Any]] = []
    for kind in due_kinds(cfg, now, db, user_id):
        try:
            msg = compose(db, user_id, kind, cfg)
        except Exception as e:  # noqa: BLE001
            db.add(NotifyLog(user_id=user_id, kind=kind, channel="-", ok=False, detail=f"生成消息失败：{e}"))
            db.commit()
            continue
        if msg is None:  # 例如今天已有记录，不需要提醒
            db.add(NotifyLog(user_id=user_id, kind=kind, channel="-", ok=True, detail="条件不满足，跳过（今天已有记录）"))
            db.commit()
            continue
        results.extend(broadcast(db, user_id, kind, msg, cfg))
    return results


def run_due(db: Session, now: Optional[datetime] = None) -> List[Dict[str, Any]]:
    now = now or now_local()
    results: List[Dict[str, Any]] = []
    # 只遍历有通知配置的活跃用户（默认配置全部关闭，无需处理）
    rows = db.query(UserSetting.user_id).filter(UserSetting.key == CONFIG_KEY).all()
    for (uid,) in rows:
        user = db.get(User, uid)
        if user is None or not user.is_active:
            continue
        results.extend(run_due_for_user(db, uid, now))
    # 就餐音效提醒：遍历开启了 meal_alert 的用户
    from .sounds import ALERT_KEY
    for (uid,) in db.query(UserSetting.user_id).filter(UserSetting.key == ALERT_KEY).all():
        user = db.get(User, uid)
        if user is None or not user.is_active:
            continue
        try:
            results.extend(run_meal_alerts_for_user(db, uid, now))
        except Exception as e:  # noqa: BLE001
            print(f"[notify] 就餐提醒异常 user={uid}: {e}", flush=True)
    return results


class Scheduler:
    def __init__(self, session_factory, interval: int = 30):
        self._sf = session_factory
        self._interval = interval
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._loop, name="notify-scheduler", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                with self._sf() as db:
                    run_due(db)
            except Exception as e:  # noqa: BLE001
                print(f"[notify] 定时任务异常：{e}", flush=True)
            self._stop.wait(self._interval)


def recent_logs(db: Session, user_id: int, limit: int = 50) -> List[Dict[str, Any]]:
    rows = db.scalars(select(NotifyLog).where(NotifyLog.user_id == user_id)
                      .order_by(NotifyLog.id.desc()).limit(limit)).all()
    return [{"id": r.id, "kind": r.kind, "kind_label": KIND_LABELS.get(r.kind, r.kind), "channel": r.channel,
             "ok": r.ok, "detail": r.detail, "created_at": r.created_at} for r in rows]
