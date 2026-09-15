"""标签字典、统计、自然语言查询、报告（按当前用户隔离）。"""
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import config
from ..db import get_db
from ..deps import get_current_user
from ..models import QueryLog, Report, Tag, User
from ..schemas import QueryIn, QueryOut, ReportCreate, ReportOut, TagOut
from ..services import nl_query, report as report_service
from ..services.stats import compute_stats
from ..services.tags import CATEGORIES, MEAL_TYPES, PORTIONS
from ..services.task_state import pending as _tasks_pending, task_guard

router = APIRouter(prefix="/api", tags=["misc"])


@router.get("/tasks/pending")
def tasks_pending(user: User = Depends(get_current_user)):
    """当前用户正在进行的任务（前端刷新后据此恢复加载态，避免重复触发）。"""
    return _tasks_pending(user.id)


@router.get("/meta")
def meta():
    return {"categories": CATEGORIES, "meal_types": MEAL_TYPES, "portions": PORTIONS,
            "disclaimer": config.DISCLAIMER}


@router.get("/tags", response_model=List[TagOut])
def list_tags(db: Session = Depends(get_db)):
    return db.scalars(select(Tag).order_by(Tag.is_watch.desc(), Tag.code)).all()


@router.get("/stats")
def stats(range: str = Query("week", pattern="^(week|month)$"), anchor: Optional[str] = None,
          db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    try:
        return compute_stats(db, range, anchor, user.id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"日期格式错误：{e}")


@router.post("/query", response_model=QueryOut)
def query(payload: QueryIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    with task_guard("query", user.id):  # 同一用户并发查询 → 409
        return nl_query.run_query(db, payload.question.strip(), user.id)


@router.get("/query/history")
def query_history(limit: int = Query(20, ge=1, le=100), db: Session = Depends(get_db),
                  user: User = Depends(get_current_user)):
    rows = db.scalars(select(QueryLog).where(QueryLog.user_id == user.id)
                      .order_by(QueryLog.id.desc()).limit(limit)).all()
    return [{"id": r.id, "question": r.question, "status": r.status, "answer": r.answer_md,
             "created_at": r.created_at, "model": r.model} for r in rows]


def _own_report(db: Session, report_id: int, user: User) -> Report:
    r = db.get(Report, report_id)
    if not r or r.user_id != user.id:
        raise HTTPException(status_code=404, detail="报告不存在")
    return r


@router.post("/reports", response_model=ReportOut, status_code=201)
def create_report(payload: ReportCreate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    try:
        r = report_service.generate_report(db, payload.period_type, payload.anchor, user.id)
    except HTTPException:
        raise  # 409 正在生成中 等业务状态码原样返回
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"日期格式错误：{e}")
    except nl_query.llm_client.LLMError as e:
        raise HTTPException(status_code=502, detail=str(e))
    return report_service.report_to_dict(r)


@router.get("/reports", response_model=List[ReportOut])
def list_reports(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    rows = db.scalars(select(Report).where(Report.user_id == user.id).order_by(Report.id.desc())).all()
    return [report_service.report_to_dict(r) for r in rows]


@router.get("/reports/generating")
def report_generating(user: User = Depends(get_current_user)):
    """该用户是否正在生成报告（前端刷新后据此恢复“生成中”状态，避免重复点击）。"""
    return {"generating": report_service.is_generating(user.id)}


@router.get("/reports/{report_id}", response_model=ReportOut)
def get_report(report_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return report_service.report_to_dict(_own_report(db, report_id, user))


@router.delete("/reports/{report_id}", status_code=204)
def delete_report(report_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    r = _own_report(db, report_id, user)
    db.delete(r)
    db.commit()
    return None
