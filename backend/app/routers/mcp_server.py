"""
MCP（Model Context Protocol）服务器 —— Streamable HTTP 传输，纯 JSON-RPC 实现，无额外依赖。

让 Claude Desktop / Cursor / 其他 Agent 通过个人访问令牌（Bearer ddt_...）直接操作饮食日记：
记一餐、查记录、看统计、问问题、生成报告、读取今日小结。

端点：POST /mcp（JSON-RPC 2.0，单条或批量）；GET /mcp → 405（不提供 SSE 长连接，属协议允许）；DELETE /mcp → 200。
支持的协议版本：2025-06-18、2025-03-26、2024-11-05（按客户端请求回显，默认最新）。
"""
import json
import secrets
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import config
from ..db import get_db
from ..deps import resolve_user
from ..models import Meal, Tag, User
from ..schemas import MealCreate, MealItemIn
from ..services import nl_query, report as report_service
from ..services.stats import compute_stats
from ..services.tags import CATEGORIES, MEAL_TYPES, PORTIONS
from ..services.timeutil import now_local, today_local
from .meals import _apply_items

router = APIRouter(tags=["mcp"])

SUPPORTED_VERSIONS = ["2025-06-18", "2025-03-26", "2024-11-05"]
SERVER_INFO = {"name": "diet-diary", "title": "今天吃得怎么样 · 饮食日记", "version": "0.3.0"}
INSTRUCTIONS = ("这是用户的个人饮食日记。识别与估算可能有误，不提供医疗诊断或精确营养数据。"
                "记录一餐时 items 至少一条；分类、餐次、份量、标签必须使用 list_tags 返回的取值。")

# ---------- 工具定义 ----------
TOOLS: List[Dict[str, Any]] = [
    {
        "name": "log_meal",
        "title": "记录一餐",
        "description": "把一顿饭写入饮食日记。items 每项含 name（菜名，必填）、category、portion、tags（标签 code 列表）。"
                       "eaten_at 缺省为当前时间（本地时区），格式 YYYY-MM-DDTHH:MM。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "meal_type": {"type": "string", "enum": MEAL_TYPES, "description": "餐次"},
                "eaten_at": {"type": "string", "description": "用餐时间 YYYY-MM-DDTHH:MM，可省略"},
                "note": {"type": "string", "description": "备注，可省略"},
                "items": {
                    "type": "array", "minItems": 1,
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "category": {"type": "string", "enum": CATEGORIES},
                            "portion": {"type": "string", "enum": PORTIONS},
                            "tags": {"type": "array", "items": {"type": "string"}},
                        },
                        "required": ["name"],
                    },
                },
            },
            "required": ["meal_type", "items"],
        },
    },
    {
        "name": "list_meals",
        "title": "查看记录",
        "description": "按日期范围列出饮食记录（默认最近 7 天，最多 100 条）。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "from_date": {"type": "string", "description": "起始日期 YYYY-MM-DD"},
                "to_date": {"type": "string", "description": "结束日期 YYYY-MM-DD"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 100},
            },
        },
    },
    {
        "name": "get_stats",
        "title": "统计概览",
        "description": "获取某周或某月的饮食结构统计（程序计算，不经模型）：餐数、分类占比、关注标签次数及环比、常吃菜品。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "range": {"type": "string", "enum": ["week", "month"], "default": "week"},
                "anchor": {"type": "string", "description": "所在周/月内任意日期 YYYY-MM-DD，缺省今天"},
            },
        },
    },
    {
        "name": "ask_diet_question",
        "title": "自然语言查询",
        "description": "用中文提问关于历史记录的统计问题，例如“这周喝过几次含糖饮料”。返回查询计划、数据行与解释。",
        "inputSchema": {"type": "object", "properties": {"question": {"type": "string"}}, "required": ["question"]},
    },
    {
        "name": "generate_report",
        "title": "生成阶段总结",
        "description": "生成并保存一份周报或月报（Markdown）。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "period_type": {"type": "string", "enum": ["week", "month"], "default": "week"},
                "anchor": {"type": "string", "description": "所在周/月内任意日期 YYYY-MM-DD"},
            },
        },
    },
    {
        "name": "get_today_summary",
        "title": "今日小结",
        "description": "返回今天已记录的每一餐与菜品。",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "list_tags",
        "title": "标签与分类字典",
        "description": "返回可用的分类、餐次、份量与标签 code（含中文名与说明）。",
        "inputSchema": {"type": "object", "properties": {}},
    },
]


def _text(obj: Any) -> Dict[str, Any]:
    text = obj if isinstance(obj, str) else json.dumps(obj, ensure_ascii=False, indent=2, default=str)
    return {"content": [{"type": "text", "text": text}]}


def _error_result(msg: str) -> Dict[str, Any]:
    return {"content": [{"type": "text", "text": msg}], "isError": True}


# ---------- 工具实现 ----------
def tool_log_meal(db: Session, user: User, args: Dict[str, Any]) -> Dict[str, Any]:
    eaten = args.get("eaten_at")
    try:
        eaten_dt = datetime.fromisoformat(eaten) if eaten else now_local()
    except ValueError:
        return _error_result("eaten_at 格式应为 YYYY-MM-DDTHH:MM")
    try:
        payload = MealCreate(eaten_at=eaten_dt, meal_type=args["meal_type"], note=args.get("note"), source="mcp",
                             items=[MealItemIn(name=i["name"], category=i.get("category", "其他"),
                                               portion=i.get("portion", "中"), tags=i.get("tags", []), source="user")
                                    for i in args.get("items", [])])
    except Exception as e:  # noqa: BLE001
        return _error_result(f"参数不合法：{str(e)[:300]}")
    if not payload.items:
        return _error_result("items 至少需要一条")
    meal = Meal(user_id=user.id, eaten_at=payload.eaten_at, meal_type=payload.meal_type, note=payload.note,
                source="mcp", confirmed=True, ai_model="mcp")
    _apply_items(db, meal, payload.items)
    db.add(meal)
    db.commit()
    db.refresh(meal)
    return _text({"ok": True, "meal_id": meal.id, "eaten_at": meal.eaten_at.strftime("%Y-%m-%d %H:%M"),
                  "meal_type": meal.meal_type,
                  "items": [{"name": i.name, "category": i.category, "portion": i.portion,
                             "tags": [t.code for t in i.tags]} for i in meal.items],
                  "disclaimer": config.DISCLAIMER})


def _meal_row(m: Meal) -> Dict[str, Any]:
    return {"id": m.id, "eaten_at": m.eaten_at.strftime("%Y-%m-%d %H:%M"), "meal_type": m.meal_type,
            "note": m.note, "source": m.source,
            "items": [{"name": i.name, "category": i.category, "portion": i.portion,
                       "tags": [t.name_zh for t in i.tags]} for i in m.items]}


def tool_list_meals(db: Session, user: User, args: Dict[str, Any]) -> Dict[str, Any]:
    today = today_local()
    try:
        f = datetime.fromisoformat(args["from_date"]) if args.get("from_date") else datetime.combine(today - timedelta(days=6), datetime.min.time())
        t = datetime.fromisoformat(args["to_date"]) + timedelta(days=1) if args.get("to_date") else datetime.combine(today + timedelta(days=1), datetime.min.time())
    except ValueError:
        return _error_result("日期格式应为 YYYY-MM-DD")
    limit = int(args.get("limit") or 50)
    rows = db.scalars(select(Meal).where(Meal.user_id == user.id, Meal.eaten_at >= f, Meal.eaten_at < t)
                      .order_by(Meal.eaten_at.desc()).limit(limit)).all()
    return _text({"count": len(rows), "meals": [_meal_row(m) for m in rows]})


def tool_get_stats(db: Session, user: User, args: Dict[str, Any]) -> Dict[str, Any]:
    try:
        s = compute_stats(db, args.get("range") or "week", args.get("anchor"), user.id)
    except ValueError as e:
        return _error_result(f"日期格式错误：{e}")
    slim = {k: s[k] for k in ("period", "meal_count", "item_count", "days_with_records", "days_total",
                              "avg_meals_per_day", "category_share", "watch_tags", "top_items", "late_night_meals",
                              "missing_days", "prev")}
    slim["disclaimer"] = config.DISCLAIMER
    return _text(slim)


def tool_ask(db: Session, user: User, args: Dict[str, Any]) -> Dict[str, Any]:
    q = (args.get("question") or "").strip()
    if not q:
        return _error_result("question 不能为空")
    out = nl_query.run_query(db, q, user.id)
    return _text({"status": out.status, "answer": out.answer, "plan": out.plan.model_dump() if out.plan else None,
                  "rows": out.rows[:50], "warnings": out.warnings})


def tool_report(db: Session, user: User, args: Dict[str, Any]) -> Dict[str, Any]:
    try:
        r = report_service.generate_report(db, args.get("period_type") or "week", args.get("anchor"), user.id)
    except ValueError as e:
        return _error_result(f"日期格式错误：{e}")
    return _text(f"# 报告 #{r.id}（{r.period_type}，{r.period_start.date()} ~ {r.period_end.date()}）\n\n{r.summary_md}"
                 f"\n\n---\n{config.DISCLAIMER}")


def tool_today(db: Session, user: User, _args: Dict[str, Any]) -> Dict[str, Any]:
    t = today_local()
    start = datetime.combine(t, datetime.min.time())
    rows = db.scalars(select(Meal).where(Meal.user_id == user.id, Meal.eaten_at >= start,
                                         Meal.eaten_at < start + timedelta(days=1)).order_by(Meal.eaten_at)).all()
    if not rows:
        return _text(f"{t.isoformat()} 今天还没有任何记录。")
    lines = [f"{t.isoformat()} 今天共记录 {len(rows)} 餐："]
    for m in rows:
        lines.append(f"- {m.eaten_at.strftime('%H:%M')} {m.meal_type}：" + "、".join(i.name for i in m.items))
    return _text("\n".join(lines))


def tool_tags(db: Session, _user: User, _args: Dict[str, Any]) -> Dict[str, Any]:
    tags = db.scalars(select(Tag).order_by(Tag.is_watch.desc(), Tag.code)).all()
    return _text({"categories": CATEGORIES, "meal_types": MEAL_TYPES, "portions": PORTIONS,
                  "tags": [{"code": t.code, "name": t.name_zh, "watch": t.is_watch, "desc": t.description} for t in tags]})


TOOL_IMPL = {"log_meal": tool_log_meal, "list_meals": tool_list_meals, "get_stats": tool_get_stats,
             "ask_diet_question": tool_ask, "generate_report": tool_report, "get_today_summary": tool_today,
             "list_tags": tool_tags}


# ---------- JSON-RPC 处理 ----------
def _rpc_error(id_: Any, code: int, message: str) -> Dict[str, Any]:
    return {"jsonrpc": "2.0", "id": id_, "error": {"code": code, "message": message}}


def handle_message(db: Session, user: User, msg: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """处理单条 JSON-RPC 消息；通知（无 id）返回 None。"""
    method = msg.get("method")
    id_ = msg.get("id")
    params = msg.get("params") or {}
    is_notification = "id" not in msg
    if method == "initialize":
        requested = params.get("protocolVersion")
        version = requested if requested in SUPPORTED_VERSIONS else SUPPORTED_VERSIONS[0]
        return {"jsonrpc": "2.0", "id": id_, "result": {
            "protocolVersion": version,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": SERVER_INFO,
            "instructions": INSTRUCTIONS,
        }}
    if is_notification:
        return None  # notifications/initialized 等
    if method == "ping":
        return {"jsonrpc": "2.0", "id": id_, "result": {}}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": id_, "result": {"tools": TOOLS}}
    if method == "tools/call":
        name = params.get("name")
        impl = TOOL_IMPL.get(name)
        if impl is None:
            return _rpc_error(id_, -32602, f"未知工具：{name}")
        try:
            result = impl(db, user, params.get("arguments") or {})
        except Exception as e:  # noqa: BLE001
            result = _error_result(f"工具执行失败：{str(e)[:300]}")
        return {"jsonrpc": "2.0", "id": id_, "result": result}
    if method in ("resources/list", "resources/templates/list"):
        return {"jsonrpc": "2.0", "id": id_, "result": {"resources": [] if method == "resources/list" else [],
                                                        **({"resourceTemplates": []} if method != "resources/list" else {})}}
    if method == "prompts/list":
        return {"jsonrpc": "2.0", "id": id_, "result": {"prompts": []}}
    return _rpc_error(id_, -32601, f"不支持的方法：{method}")


@router.post("/mcp")
async def mcp_post(request: Request, db: Session = Depends(get_db)):
    user = resolve_user(request, db)
    if user is None:
        return JSONResponse(status_code=401, content={"error": "需要个人访问令牌：Authorization: Bearer ddt_..."},
                            headers={"WWW-Authenticate": "Bearer"})
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        return JSONResponse(status_code=400, content=_rpc_error(None, -32700, "JSON 解析失败"))
    messages = body if isinstance(body, list) else [body]
    responses = []
    for m in messages:
        if not isinstance(m, dict) or m.get("jsonrpc") != "2.0":
            responses.append(_rpc_error(m.get("id") if isinstance(m, dict) else None, -32600, "无效的 JSON-RPC 请求"))
            continue
        r = handle_message(db, user, m)
        if r is not None:
            responses.append(r)
    headers = {"Mcp-Session-Id": request.headers.get("mcp-session-id") or secrets.token_hex(16)}
    if not responses:
        return Response(status_code=202, headers=headers)
    payload = responses if isinstance(body, list) else responses[0]
    return JSONResponse(content=payload, headers=headers)


@router.get("/mcp")
def mcp_get():
    return JSONResponse(status_code=405, content={"error": "此服务器不提供 SSE 流，请使用 POST"},
                        headers={"Allow": "POST, DELETE"})


@router.delete("/mcp")
def mcp_delete():
    return Response(status_code=200)


@router.get("/api/mcp/info")
def mcp_info(request: Request, db: Session = Depends(get_db)):
    """给前端展示接入说明（需登录）。"""
    user = resolve_user(request, db)
    if user is None:
        return JSONResponse(status_code=401, content={"detail": "未登录"})
    base = str(request.base_url).rstrip("/")
    return {"endpoint": f"{base}/mcp", "transport": "streamable-http", "auth": "Authorization: Bearer <个人访问令牌>",
            "tools": [{"name": t["name"], "title": t.get("title"), "description": t["description"]} for t in TOOLS],
            "claude_desktop_example": {
                "mcpServers": {"diet-diary": {"command": "npx", "args": [
                    "-y", "mcp-remote", f"{base}/mcp", "--header", "Authorization:${DIET_TOKEN}"],
                    "env": {"DIET_TOKEN": "Bearer ddt_替换为你的令牌"}}}},
            "curl_example": f"curl -X POST {base}/mcp -H 'Authorization: Bearer ddt_...' -H 'Content-Type: application/json' "
                            "-d '{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"tools/list\"}'"}
