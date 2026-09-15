"""
模型用量统计与余额查询。

- 用量：每次模型调用（含 mock 与失败）都会写入 llm_usage 表，可按天/月/任务/用户汇总，并按管理员设置的单价估算费用。
- 余额：只有部分供应商提供余额接口（DeepSeek、硅基流动、Moonshot）；OpenAI、通义千问、智谱等没有公开余额 API，
  界面会提示到官网控制台查看，并用本地用量作为参考。
"""
import json
import time
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import httpx
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import LlmUsage, Setting, User
from .llm_client import LLMConfig, get_llm_config
from .timeutil import today_local

PRICE_KEY = "llm_price"  # JSON: {"input_per_1k": 0.002, "output_per_1k": 0.008, "currency": "CNY"}
DEFAULT_PRICE = {"input_per_1k": 0.0, "output_per_1k": 0.0, "currency": "CNY"}


def record_usage(db: Session, *, user_id: Optional[int], provider: str, model: str, task: str,
                 prompt_tokens: int, completion_tokens: int, latency_ms: int, ok: bool, error: Optional[str]) -> None:
    try:
        db.add(LlmUsage(user_id=user_id, provider=provider, model=model or "", task=task,
                        prompt_tokens=int(prompt_tokens or 0), completion_tokens=int(completion_tokens or 0),
                        latency_ms=int(latency_ms or 0), ok=ok, error=(error or "")[:300] or None))
        db.commit()
    except Exception:  # noqa: BLE001  用量记录失败不应影响业务
        db.rollback()


def get_price(db: Session) -> Dict[str, Any]:
    row = db.get(Setting, PRICE_KEY)
    if row and row.value:
        try:
            return {**DEFAULT_PRICE, **json.loads(row.value)}
        except json.JSONDecodeError:
            pass
    return dict(DEFAULT_PRICE)


def set_price(db: Session, price: Dict[str, Any]) -> Dict[str, Any]:
    merged = {**get_price(db), **{k: v for k, v in price.items() if k in DEFAULT_PRICE}}
    row = db.get(Setting, PRICE_KEY)
    if row is None:
        db.add(Setting(key=PRICE_KEY, value=json.dumps(merged)))
    else:
        row.value = json.dumps(merged)
    db.commit()
    return merged


def _cost(price: Dict[str, Any], p: int, c: int) -> float:
    return round(p / 1000 * float(price.get("input_per_1k", 0)) + c / 1000 * float(price.get("output_per_1k", 0)), 4)


def summary(db: Session, user_id: Optional[int], is_admin: bool) -> Dict[str, Any]:
    """用户看自己的用量；管理员额外看到全站汇总与按用户分布。"""
    price = get_price(db)
    today = today_local()
    start_today = datetime.combine(today, datetime.min.time())
    start_month = datetime.combine(today.replace(day=1), datetime.min.time())
    start_30d = start_today - timedelta(days=29)

    def agg(where_user: Optional[int], since: Optional[datetime]) -> Dict[str, Any]:
        q = select(func.count(LlmUsage.id), func.coalesce(func.sum(LlmUsage.prompt_tokens), 0),
                   func.coalesce(func.sum(LlmUsage.completion_tokens), 0))
        if where_user is not None:
            q = q.where(LlmUsage.user_id == where_user)
        if since is not None:
            q = q.where(LlmUsage.created_at >= since)
        calls, p, c = db.execute(q).one()
        fails_q = select(func.count(LlmUsage.id)).where(LlmUsage.ok == False)  # noqa: E712
        if where_user is not None:
            fails_q = fails_q.where(LlmUsage.user_id == where_user)
        if since is not None:
            fails_q = fails_q.where(LlmUsage.created_at >= since)
        fails = db.scalar(fails_q) or 0
        return {"calls": int(calls or 0), "prompt_tokens": int(p or 0), "completion_tokens": int(c or 0),
                "total_tokens": int((p or 0) + (c or 0)), "failed": int(fails), "est_cost": _cost(price, int(p or 0), int(c or 0))}

    scope_user = None if is_admin else user_id
    out: Dict[str, Any] = {
        "scope": "all" if is_admin else "self",
        "price": price,
        "today": agg(scope_user, start_today),
        "month": agg(scope_user, start_month),
        "total": agg(scope_user, None),
        "mine_month": agg(user_id, start_month) if user_id is not None else None,
    }
    # 最近 30 天按天
    rows = db.execute(
        select(func.date(LlmUsage.created_at), func.count(LlmUsage.id),
               func.coalesce(func.sum(LlmUsage.prompt_tokens + LlmUsage.completion_tokens), 0))
        .where(LlmUsage.created_at >= start_30d, *( [LlmUsage.user_id == scope_user] if scope_user is not None else []))
        .group_by(func.date(LlmUsage.created_at)).order_by(func.date(LlmUsage.created_at))
    ).all()
    out["daily"] = [{"date": str(d), "calls": int(n), "tokens": int(t)} for d, n, t in rows]
    # 按任务
    rows = db.execute(
        select(LlmUsage.task, func.count(LlmUsage.id),
               func.coalesce(func.sum(LlmUsage.prompt_tokens + LlmUsage.completion_tokens), 0))
        .where(LlmUsage.created_at >= start_month, *( [LlmUsage.user_id == scope_user] if scope_user is not None else []))
        .group_by(LlmUsage.task).order_by(func.count(LlmUsage.id).desc())
    ).all()
    out["by_task"] = [{"task": t, "calls": int(n), "tokens": int(tk)} for t, n, tk in rows]
    # 管理员：按用户
    if is_admin:
        rows = db.execute(
            select(User.username, func.count(LlmUsage.id),
                   func.coalesce(func.sum(LlmUsage.prompt_tokens + LlmUsage.completion_tokens), 0))
            .join(User, User.id == LlmUsage.user_id, isouter=True)
            .where(LlmUsage.created_at >= start_month)
            .group_by(User.username).order_by(func.count(LlmUsage.id).desc())
        ).all()
        out["by_user"] = [{"username": u or "（系统/定时任务）", "calls": int(n), "tokens": int(tk)} for u, n, tk in rows]
    # 最近记录
    recent = db.scalars(select(LlmUsage).where(*( [LlmUsage.user_id == scope_user] if scope_user is not None else []))
                        .order_by(LlmUsage.id.desc()).limit(20)).all()
    out["recent"] = [{"id": r.id, "task": r.task, "model": r.model, "provider": r.provider, "prompt_tokens": r.prompt_tokens,
                      "completion_tokens": r.completion_tokens, "latency_ms": r.latency_ms, "ok": r.ok, "error": r.error,
                      "created_at": r.created_at} for r in recent]
    return out


# ---------- 余额 ----------
BALANCE_SUPPORT = {
    "deepseek": "GET /user/balance",
    "siliconflow": "GET /v1/user/info",
    "moonshot": "GET /v1/users/me/balance",
}
CONSOLE_URLS = {
    "openai": "https://platform.openai.com/settings/organization/billing/overview",
    "dashscope": "https://billing.console.aliyun.com/",
    "zhipu": "https://open.bigmodel.cn/usercenter/financialoverview",
    "siliconflow": "https://cloud.siliconflow.cn/bills",
    "deepseek": "https://platform.deepseek.com/usage",
    "moonshot": "https://platform.moonshot.cn/console/account",
    "ollama": "",
    "mock": "",
    "custom": "",
}


def fetch_balance(cfg: LLMConfig) -> Dict[str, Any]:
    """查询供应商余额；不支持的供应商返回 supported=False 与控制台链接。"""
    base = {"provider": cfg.provider, "supported": cfg.provider in BALANCE_SUPPORT,
            "console_url": CONSOLE_URLS.get(cfg.provider, ""), "checked_at": datetime.now().isoformat(timespec="seconds")}
    if cfg.provider == "mock":
        return {**base, "supported": False, "message": "离线演示模式没有余额概念"}
    if cfg.provider not in BALANCE_SUPPORT:
        return {**base, "message": "该供应商未提供余额查询接口，请到官网控制台查看；下方本地用量可作参考"}
    if not cfg.api_key:
        return {**base, "ok": False, "message": "未配置 API Key"}
    headers = {"Authorization": f"Bearer {cfg.api_key}"}
    t0 = time.time()
    try:
        if cfg.provider == "deepseek":
            r = httpx.get("https://api.deepseek.com/user/balance", headers=headers, timeout=10)
            data = r.json()
            infos = data.get("balance_infos") or []
            items = [{"currency": i.get("currency"), "total": i.get("total_balance"),
                      "granted": i.get("granted_balance"), "topped_up": i.get("topped_up_balance")} for i in infos]
            return {**base, "ok": r.status_code == 200, "is_available": data.get("is_available"),
                    "balances": items, "raw": data, "latency_ms": int((time.time() - t0) * 1000)}
        if cfg.provider == "siliconflow":
            r = httpx.get("https://api.siliconflow.cn/v1/user/info", headers=headers, timeout=10)
            data = r.json().get("data") or {}
            return {**base, "ok": r.status_code == 200,
                    "balances": [{"currency": "CNY", "total": data.get("totalBalance"),
                                  "granted": data.get("balance"), "topped_up": data.get("chargeBalance")}],
                    "raw": data, "latency_ms": int((time.time() - t0) * 1000)}
        if cfg.provider == "moonshot":
            r = httpx.get("https://api.moonshot.cn/v1/users/me/balance", headers=headers, timeout=10)
            data = r.json().get("data") or {}
            return {**base, "ok": r.status_code == 200,
                    "balances": [{"currency": "CNY", "total": data.get("available_balance"),
                                  "granted": data.get("voucher_balance"), "topped_up": data.get("cash_balance")}],
                    "raw": data, "latency_ms": int((time.time() - t0) * 1000)}
    except Exception as e:  # noqa: BLE001
        return {**base, "ok": False, "message": f"查询失败：{e}"}
    return {**base, "ok": False, "message": "未知供应商"}


def balance(db: Session) -> Dict[str, Any]:
    return fetch_balance(get_llm_config(db))
