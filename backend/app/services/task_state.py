"""
全局任务忙状态：防止“刷新页面后按钮恢复可点 → 重复触发长任务”。

用法：
    with task_guard("plan", user_id):   # 已在运行则抛 409
        ...
前端可用 GET /api/tasks/pending 查询当前用户正在进行的任务，刷新后恢复加载态。
"""
import threading
from typing import Dict, Set

from fastapi import HTTPException

VALID_TASKS = ("plan", "slot", "report", "query", "share", "vision", "memory")

_LOCK = threading.Lock()
_BUSY: Dict[str, Set[int]] = {}

_BUSY_DETAIL = {
    "plan": "餐单正在生成中，请稍候（7 天餐单通常需要 1~3 分钟）",
    "slot": "该餐正在重新生成，请稍候",
    "report": "报告正在生成中，请稍候（通常需要 10~60 秒）",
    "query": "上一个问题正在查询中，请稍候",
    "share": "分享卡片正在生成中，请稍候",
    "vision": "图片正在识别中，请稍候",
    "memory": "记忆正在重建中，请稍候",
}


def begin(task: str, user_id: int) -> bool:
    """登记任务开始；已在进行中返回 False。"""
    if user_id is None:
        return True
    with _LOCK:
        s = _BUSY.setdefault(task, set())
        if user_id in s:
            return False
        s.add(user_id)
        return True


def end(task: str, user_id: int) -> None:
    if user_id is None:
        return
    with _LOCK:
        _BUSY.get(task, set()).discard(user_id)


def is_busy(task: str, user_id: int) -> bool:
    if user_id is None:
        return False
    with _LOCK:
        return user_id in _BUSY.get(task, set())


def pending(user_id: int) -> Dict[str, bool]:
    """返回该用户各任务的进行中状态。"""
    with _LOCK:
        return {t: (user_id in _BUSY.get(t, set())) for t in VALID_TASKS}


class task_guard:  # noqa: N801
    """上下文管理器：进入时登记（冲突则 409），退出时释放。"""

    def __init__(self, task: str, user_id: int):
        self.task = task
        self.user_id = user_id

    def __enter__(self) -> "task_guard":
        begin_check(self.task, self.user_id)
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:  # noqa: ANN001
        end(self.task, self.user_id)
        return False


def begin_check(task: str, user_id: int) -> None:
    """登记任务开始；已在运行则抛 409（供不方便用 with 的场景调用）。"""
    if not begin(task, user_id):
        raise HTTPException(status_code=409,
                            detail=_BUSY_DETAIL.get(task, "任务正在处理中，请稍候"))
