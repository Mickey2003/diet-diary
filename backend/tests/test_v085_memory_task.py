"""v0.8.5 回归：AI 记忆「从最近记录重建」接入任务忙状态。

根因：重建是同步长任务但无忙状态登记，用户刷新页面后可再次点击，
导致重复触发 LLM 抽取。现纳入 task_state("memory")，并暴露给 /api/tasks/pending。
"""
from app.db import SessionLocal
from app.models import User
from app.services import task_state


def _uid() -> int:
    db = SessionLocal()
    try:
        return db.query(User).filter(User.username == "tester").first().id
    finally:
        db.close()


def test_memory_in_valid_tasks():
    assert "memory" in task_state.VALID_TASKS
    assert "memory" in task_state.pending(0)


def test_rebuild_returns_409_when_busy(client):
    uid = _uid()
    # 直接占用忙状态，模拟"另一次重建正在进行"
    assert task_state.begin("memory", uid) is True
    try:
        r = client.post("/api/memory/rebuild")
        assert r.status_code == 409, r.text
    finally:
        task_state.end("memory", uid)
    # 释放后可正常执行
    r2 = client.post("/api/memory/rebuild")
    assert r2.status_code == 200, r2.text
    assert "new_memories" in r2.json()


def test_pending_exposes_memory(client):
    uid = _uid()
    assert task_state.begin("memory", uid) is True
    try:
        r = client.get("/api/tasks/pending")
        assert r.status_code == 200
        assert r.json().get("memory") is True
    finally:
        task_state.end("memory", uid)


def test_memory_not_busy_after_rebuild(client):
    """重建结束后忙状态必须释放，否则用户会被永久锁死。"""
    uid = _uid()
    r = client.post("/api/memory/rebuild")
    assert r.status_code == 200
    assert task_state.is_busy("memory", uid) is False
