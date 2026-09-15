"""
阶段总结（周报 / 月报）：程序先算事实 → 模型只基于事实写总结 → 程序核对总结里的数字。
"""
import json
import re
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Set

from sqlalchemy.orm import Session

from .. import config
from ..models import Report
from . import llm_client
from .stats import compute_stats

REPORT_SYSTEM_PROMPT = """你是饮食日记应用的“阶段总结撰写者”。程序已经统计好了这一阶段的饮食事实（JSON），请据此写一份中文 Markdown 总结。

结构要求：
1. 一级标题：本期观察（写清是哪一周/哪一月）
2. “记录概况”：记录了多少餐、覆盖多少天、有无空缺
3. “饮食结构”：各分类占比及与上期的变化（用数据里的 ratio / delta_ratio），可顺带提一句估算热量（kcal_avg_per_day）与上期对比
4. “值得留意”：关注标签（含糖饮料、油炸、外卖等）的次数及环比变化，只说数据里有的
5. “最常出现”：Top 菜品
6. “轻量建议”：1~2 条温和、可执行的小建议，不涉及医疗、减重目标、营养素数值

硬性规则：
- 每一条陈述都必须能在 JSON 事实里找到对应数字，禁止编造或估算新的数字。
- 可以引用 JSON 中程序估算的热量（kcal_total / kcal_avg_per_day），但必须写成“估算约 xxx 千卡”，不要自行推算或给出克数、营养素含量。
- 不要下医疗诊断，不要使用“你必须/你应该”这类语气。
- 数据为 0 或为空时如实说明“本期没有记录到”，不要臆测。
"""

_NUM_RE = re.compile(r"\d+(?:\.\d+)?")


def _collect_numbers(obj: Any, out: Set[str]) -> None:
    if isinstance(obj, bool):
        return
    if isinstance(obj, (int, float)):
        out.add(_fmt_num(obj))
        return
    if isinstance(obj, str):
        for n in _NUM_RE.findall(obj):
            out.add(_fmt_num(float(n)))
        return
    if isinstance(obj, dict):
        for v in obj.values():
            _collect_numbers(v, out)
    elif isinstance(obj, list):
        for v in obj:
            _collect_numbers(v, out)


def _fmt_num(x: float) -> str:
    return str(int(x)) if float(x).is_integer() else str(round(float(x), 2))


def find_unverified_numbers(summary: str, facts: Dict[str, Any]) -> List[str]:
    """找出总结里出现、但事实数据里不存在的数字（粗略核对，供人工留意）。"""
    known: Set[str] = set()
    _collect_numbers(facts, known)
    # 允许常见的小数字（序号、章节号）
    for i in range(0, 11):
        known.add(str(i))
    unverified: List[str] = []
    for n in _NUM_RE.findall(summary):
        f = _fmt_num(float(n))
        if f not in known and f not in unverified:
            unverified.append(f)
    return unverified


def is_generating(user_id: Optional[int]) -> bool:
    """该用户是否正在生成报告（供前端刷新后恢复状态）。"""
    from .task_state import is_busy
    return user_id is not None and is_busy("report", user_id)


def _fallback_summary(facts: Dict[str, Any]) -> str:
    """模型返回空正文时的兜底总结（纯事实拼装，避免“看不到正文”）。"""
    p = facts.get("period", {}) or {}
    lines = [f"## {p.get('label', '本期')}饮食观察", ""]
    lines.append(f"- 本期共记录 **{facts.get('meal_count', 0)}** 餐，覆盖 "
                 f"{facts.get('days_with_records', 0)}/{facts.get('days_total', 0)} 天。")
    cs = facts.get("category_share") or []
    if cs:
        lines.append(f"- 食物构成中占比最高的是 **{cs[0].get('category')}**（{cs[0].get('ratio')}%）。")
    for w in (facts.get("watch_tags") or [])[:3]:
        lines.append(f"- {w.get('name')} 出现 **{w.get('count', 0)}** 次。")
    ti = facts.get("top_items") or []
    if ti:
        lines.append("- 最常出现的菜品：" +
                     "、".join(f"{t.get('name')}（{t.get('count', 0)} 次）" for t in ti[:3]) + "。")
    lines.append("")
    lines.append("**轻量建议**：保持规律记录，注意蔬果与优质蛋白的搭配。")
    return "\n".join(lines)


def generate_report(db: Session, period_type: str = "week", anchor: Optional[str] = None,
                    user_id: Optional[int] = None) -> Report:
    from .task_state import begin as _begin, end as _end
    if not _begin("report", user_id):
        from fastapi import HTTPException
        raise HTTPException(status_code=409, detail="报告正在生成中，请稍候（通常需要 10~60 秒）")
    try:
        facts = compute_stats(db, period_type, anchor, user_id)
        client = llm_client.get_client(db)
        # 注入用户记忆（仅在 user_id 已知时）
        system_content = REPORT_SYSTEM_PROMPT
        if user_id is not None:
            try:
                from .memory import render_memories_for_prompt
                memories_text = render_memories_for_prompt(db, user_id)
                if memories_text:
                    system_content = system_content + "\n\n" + memories_text
            except Exception:  # noqa: BLE001
                pass
        summary = client.chat(
            [{"role": "system", "content": system_content},
             {"role": "user", "content": "本期事实数据（JSON）：\n" + json.dumps(facts, ensure_ascii=False)}],
            task="report", temperature=0.4, mock_context={"facts": facts},
        ).strip()
        if not summary:
            # 模型返回空正文 → 用事实拼装兜底，保证页面有正文可看
            summary = _fallback_summary(facts)
        unverified = find_unverified_numbers(summary, facts)
        s = date.fromisoformat(facts["period"]["start"])
        e = date.fromisoformat(facts["period"]["end"])
        start_dt = datetime.combine(s, datetime.min.time())
        end_dt = datetime.combine(e, datetime.max.time().replace(microsecond=0))
        report = Report(user_id=user_id, period_type=period_type, period_start=start_dt, period_end=end_dt,
                        facts_json=json.dumps(facts, ensure_ascii=False), summary_md=summary,
                        unverified_numbers=json.dumps(unverified, ensure_ascii=False), model=client.model_name())
        db.add(report)
        db.commit()
        db.refresh(report)
        return report
    finally:
        _end("report", user_id)


def report_to_dict(r: Report) -> Dict[str, Any]:
    return {
        "id": r.id, "period_type": r.period_type, "period_start": r.period_start, "period_end": r.period_end,
        "facts": json.loads(r.facts_json), "summary_md": r.summary_md,
        "unverified_numbers": json.loads(r.unverified_numbers or "[]"), "model": r.model, "created_at": r.created_at,
    }
