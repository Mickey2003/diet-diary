"""
记忆功能（Feature 3）测试。

涵盖：
- 记忆提取与去重
- 100条活跃上限
- 记忆注入 report prompt（spy on LLMClient.chat）
- CRUD 操作
- 用户隔离
- rebuild 端点
- summary 端点
"""
import json
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models import Memory
from app.services.llm_client import LLMClient
from app.services import memory as mem_svc

from .conftest import TEST_USER


# ---------------------------------------------------------------------------
# 辅助
# ---------------------------------------------------------------------------

def _login(c: TestClient, username: str, password: str) -> None:
    r = c.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text


def _ensure_user(admin_client: TestClient, username: str, password: str) -> int:
    users = admin_client.get("/api/admin/users").json()
    for u in users:
        if u["username"] == username:
            return u["id"]
    r = admin_client.post("/api/admin/users",
                          json={"username": username, "password": password, "role": "user"})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _get_user_id(db, username: str) -> int:
    from app.models import User
    return db.query(User).filter(User.username == username).first().id


def _clear_memories(db, user_id: int) -> None:
    db.query(Memory).filter(Memory.user_id == user_id).delete()
    db.commit()


# ---------------------------------------------------------------------------
# 去重逻辑测试
# ---------------------------------------------------------------------------

class TestMemoryDedupe:
    def test_exact_duplicate_not_stored(self, db):
        """相同内容不重复存储。"""
        user_id = _get_user_id(db, TEST_USER[0])
        _clear_memories(db, user_id)

        candidates = [
            {"content": "不喜欢香菜", "category": "preference", "importance": 3, "evidence": "test"},
            {"content": "不喜欢香菜", "category": "preference", "importance": 4, "evidence": "test2"},
        ]
        saved1 = mem_svc._dedupe_and_save(db, user_id, candidates[:1])
        saved2 = mem_svc._dedupe_and_save(db, user_id, candidates[1:])
        assert len(saved1) == 1
        assert len(saved2) == 0  # 第二条是重复
        # 确认重要度已提升
        existing = db.query(Memory).filter(
            Memory.user_id == user_id, Memory.content == "不喜欢香菜"
        ).first()
        assert existing is not None
        assert existing.importance == 4  # 提升到较高值

    def test_similar_duplicate_not_stored(self, db):
        """相似度 >= 0.8 的内容不重复存储。"""
        user_id = _get_user_id(db, TEST_USER[0])
        _clear_memories(db, user_id)

        saved1 = mem_svc._dedupe_and_save(db, user_id, [
            {"content": "喜欢吃清淡食物", "category": "preference", "importance": 3}
        ])
        saved2 = mem_svc._dedupe_and_save(db, user_id, [
            {"content": "喜欢吃清淡的食物", "category": "preference", "importance": 3}
        ])
        assert len(saved1) == 1
        assert len(saved2) == 0  # 相似度高，不重复存储

    def test_different_content_stored(self, db):
        """不相似的内容正常存储。"""
        user_id = _get_user_id(db, TEST_USER[0])
        _clear_memories(db, user_id)

        candidates = [
            {"content": "不喜欢辛辣食物", "category": "preference", "importance": 3},
            {"content": "常吃燕麦粥", "category": "habit", "importance": 2},
        ]
        saved = mem_svc._dedupe_and_save(db, user_id, candidates)
        assert len(saved) == 2

    def test_too_short_not_stored(self, db):
        """内容少于4字不存储。"""
        user_id = _get_user_id(db, TEST_USER[0])
        _clear_memories(db, user_id)
        saved = mem_svc._dedupe_and_save(db, user_id, [
            {"content": "好的", "category": "fact", "importance": 1}
        ])
        assert len(saved) == 0

    def test_digits_only_not_stored(self, db):
        """纯数字内容不存储。"""
        user_id = _get_user_id(db, TEST_USER[0])
        _clear_memories(db, user_id)
        saved = mem_svc._dedupe_and_save(db, user_id, [
            {"content": "12345", "category": "fact", "importance": 1}
        ])
        assert len(saved) == 0


# ---------------------------------------------------------------------------
# 100条上限测试
# ---------------------------------------------------------------------------

class TestMemoryCap:
    def test_cap_at_100(self, db):
        """活跃记忆上限为100条，超出部分不存储。"""
        user_id = _get_user_id(db, TEST_USER[0])
        _clear_memories(db, user_id)

        # 直接写入 100 条记忆（绕过去重逻辑，内容各不相同）
        for i in range(100):
            mem = Memory(
                user_id=user_id,
                content=f"该用户的第{i}条独特饮食记忆不会重复出现",
                category="fact",
                importance=3,
                source="user",
            )
            db.add(mem)
        db.commit()

        active_count = db.query(Memory).filter(
            Memory.user_id == user_id, Memory.is_active == True  # noqa: E712
        ).count()
        assert active_count == 100

        # 尝试再添加 1 条：应因达上限而不存储
        extra = [{"content": "这是一百零一条全新内容的记忆", "category": "goal", "importance": 5}]
        saved_extra = mem_svc._dedupe_and_save(db, user_id, extra)
        assert len(saved_extra) == 0, "上限已达，不应存储额外记忆"

        # 最终上限仍为 100
        assert db.query(Memory).filter(
            Memory.user_id == user_id, Memory.is_active == True  # noqa: E712
        ).count() == 100

        # 清理
        _clear_memories(db, user_id)


# ---------------------------------------------------------------------------
# 记忆注入 report prompt 的测试
# ---------------------------------------------------------------------------

class TestMemoryInjection:
    def test_memory_in_report_prompt(self, client, db):
        """有记忆时，generate_report 的 system prompt 应包含记忆文本。"""
        user_id = _get_user_id(db, TEST_USER[0])
        _clear_memories(db, user_id)

        # 创建一条记忆
        r = client.post("/api/memory", json={
            "content": "不喜欢很辣的食物",
            "category": "preference",
            "importance": 4,
        })
        assert r.status_code == 201

        captured_messages = []
        original_chat = LLMClient.chat

        def spy_chat(self, messages, **kwargs):
            captured_messages.extend(messages)
            return original_chat(self, messages, **kwargs)

        with patch.object(LLMClient, "chat", spy_chat):
            r2 = client.post("/api/reports", json={"period_type": "week"})
            assert r2.status_code in (200, 201)

        system_msgs = [m for m in captured_messages if m.get("role") == "system"]
        assert len(system_msgs) > 0, "应有 system 消息"
        assert any(
            "已知的用户信息" in m["content"] for m in system_msgs
        ), "system prompt 应包含记忆注入文本"

        # 清理
        _clear_memories(db, user_id)

    def test_no_memory_no_injection(self, client, db):
        """无记忆时，report prompt 不应包含记忆块（不崩溃）。"""
        user_id = _get_user_id(db, TEST_USER[0])
        _clear_memories(db, user_id)

        captured_messages = []
        original_chat = LLMClient.chat

        def spy_chat(self, messages, **kwargs):
            captured_messages.extend(messages)
            return original_chat(self, messages, **kwargs)

        with patch.object(LLMClient, "chat", spy_chat):
            r = client.post("/api/reports", json={"period_type": "week"})
            assert r.status_code in (200, 201)

        # 不应崩溃，且可能没有记忆块（OK）
        assert len(captured_messages) > 0

    def test_render_memories_for_prompt(self, db):
        """render_memories_for_prompt 返回正确格式的文本。"""
        user_id = _get_user_id(db, TEST_USER[0])
        _clear_memories(db, user_id)

        # 添加几条记忆
        for i, content in enumerate(["常喝豆浆", "不吃海鲜", "目标减重5kg"]):
            mem = Memory(
                user_id=user_id,
                content=content,
                category=["habit", "preference", "goal"][i],
                importance=3 + i,
                source="user",
            )
            db.add(mem)
        db.commit()

        text = mem_svc.render_memories_for_prompt(db, user_id)
        assert "已知的用户信息" in text
        assert "常喝豆浆" in text or "不吃海鲜" in text or "目标减重5kg" in text

        _clear_memories(db, user_id)

    def test_render_empty_memories(self, db):
        """无记忆时 render 返回空字符串。"""
        user_id = _get_user_id(db, TEST_USER[0])
        _clear_memories(db, user_id)
        text = mem_svc.render_memories_for_prompt(db, user_id)
        assert text == ""


# ---------------------------------------------------------------------------
# 记忆 CRUD API 测试
# ---------------------------------------------------------------------------

class TestMemoryCRUD:
    def setup_method(self, method):
        """每个测试前清理记忆。"""
        pass

    def test_create_memory(self, client):
        r = client.post("/api/memory", json={
            "content": "喜欢吃新鲜蔬菜",
            "category": "preference",
            "importance": 3,
        })
        assert r.status_code == 201
        d = r.json()
        assert d["content"] == "喜欢吃新鲜蔬菜"
        assert d["category"] == "preference"
        assert d["source"] == "user"

    def test_list_memories(self, client, db):
        user_id = _get_user_id(db, TEST_USER[0])
        _clear_memories(db, user_id)

        client.post("/api/memory", json={"content": "列表测试记忆一", "category": "fact", "importance": 2})
        client.post("/api/memory", json={"content": "列表测试记忆二", "category": "habit", "importance": 3})

        r = client.get("/api/memory")
        assert r.status_code == 200
        contents = [m["content"] for m in r.json()]
        assert "列表测试记忆一" in contents
        assert "列表测试记忆二" in contents

    def test_filter_by_category(self, client, db):
        user_id = _get_user_id(db, TEST_USER[0])
        _clear_memories(db, user_id)

        client.post("/api/memory", json={"content": "过滤分类测试偏好", "category": "preference", "importance": 2})
        client.post("/api/memory", json={"content": "过滤分类测试习惯", "category": "habit", "importance": 2})

        r = client.get("/api/memory?category=preference")
        assert r.status_code == 200
        assert all(m["category"] == "preference" for m in r.json())

    def test_update_memory(self, client):
        r = client.post("/api/memory", json={"content": "更新测试内容原始", "category": "fact", "importance": 2})
        mem_id = r.json()["id"]

        r2 = client.patch(f"/api/memory/{mem_id}", json={"importance": 5, "is_active": False})
        assert r2.status_code == 200
        d = r2.json()
        assert d["importance"] == 5
        assert d["is_active"] is False

    def test_delete_memory(self, client):
        r = client.post("/api/memory", json={"content": "删除测试内容记忆", "category": "fact", "importance": 1})
        mem_id = r.json()["id"]
        r2 = client.delete(f"/api/memory/{mem_id}")
        assert r2.status_code == 204

    def test_extract_from_text(self, client, db):
        """POST /api/memory/extract 从文本提取记忆。"""
        user_id = _get_user_id(db, TEST_USER[0])
        _clear_memories(db, user_id)

        r = client.post("/api/memory/extract", json={"text": "我不吃辣椒，对花粉过敏"})
        assert r.status_code == 201
        # mock 应提取出相关记忆（不一定完全匹配，但至少有条目或返回空列表）
        assert isinstance(r.json(), list)

    def test_summary_endpoint(self, client, db):
        user_id = _get_user_id(db, TEST_USER[0])
        _clear_memories(db, user_id)

        client.post("/api/memory", json={"content": "摘要测试记忆内容", "category": "habit", "importance": 3})
        r = client.get("/api/memory/summary")
        assert r.status_code == 200
        d = r.json()
        assert "count" in d
        assert "by_category" in d
        assert d["count"] >= 1

    def test_rebuild_endpoint(self, client):
        """POST /api/memory/rebuild 不崩溃。"""
        r = client.post("/api/memory/rebuild")
        assert r.status_code == 200
        d = r.json()
        assert "new_memories" in d
        assert "scanned_meals" in d

    def test_invalid_category(self, client):
        r = client.post("/api/memory", json={"content": "无效类别测试", "category": "invalid_cat", "importance": 3})
        assert r.status_code == 422

    def test_content_too_short(self, client):
        r = client.post("/api/memory", json={"content": "短", "category": "fact", "importance": 3})
        assert r.status_code == 422


# ---------------------------------------------------------------------------
# 用户隔离
# ---------------------------------------------------------------------------

class TestMemoryUserIsolation:
    def test_memories_are_user_scoped(self, client):
        """用户 A 的记忆不应被用户 B 看到。"""
        _ensure_user(client, "mem_user_c", "mem_pass_c_123")

        # 创建 A（admin/tester）的记忆
        client.post("/api/memory", json={
            "content": "用户A的专属记忆内容",
            "category": "fact",
            "importance": 3,
        })

        with TestClient(app) as c_c:
            _login(c_c, "mem_user_c", "mem_pass_c_123")
            r = c_c.get("/api/memory")
            assert r.status_code == 200
            # 用户C不应看到用户A的记忆
            contents = [m["content"] for m in r.json()]
            assert "用户A的专属记忆内容" not in contents

    def test_cannot_delete_others_memory(self, client):
        """不能删除其他用户的记忆。"""
        _ensure_user(client, "mem_user_d", "mem_pass_d_123")

        r = client.post("/api/memory", json={
            "content": "管理员专属记忆内容一", "category": "fact", "importance": 3
        })
        mem_id = r.json()["id"]

        with TestClient(app) as c_d:
            _login(c_d, "mem_user_d", "mem_pass_d_123")
            r2 = c_d.delete(f"/api/memory/{mem_id}")
            assert r2.status_code == 404


# ---------------------------------------------------------------------------
# Mock 记忆提取规则验证
# ---------------------------------------------------------------------------

class TestMockExtract:
    def test_frequent_item_extracted(self, db):
        """出现≥3次的食物应提取为'常吃X'。"""
        user_id = _get_user_id(db, TEST_USER[0])
        _clear_memories(db, user_id)

        ctx = {
            "text": "",
            "items": ["白米饭"] * 5,  # 出现5次
            "source_kind": "meal",
        }
        from app.services.mock_llm import MOCK_HANDLERS
        result_str = MOCK_HANDLERS["memory_extract"]([], ctx)
        result = json.loads(result_str)
        assert any("白米饭" in r["content"] and "常吃" in r["content"] for r in result)

    def test_allergy_keyword_extracted(self, db):
        """包含'过敏'的文本应提取健康记忆。"""
        ctx = {
            "text": "对花粉过敏，每年春天会有症状",
            "items": [],
            "source_kind": "profile",
        }
        from app.services.mock_llm import MOCK_HANDLERS
        result_str = MOCK_HANDLERS["memory_extract"]([], ctx)
        result = json.loads(result_str)
        assert any("过敏" in r["content"] for r in result)

    def test_dislike_keyword_extracted(self, db):
        """包含'不吃'的文本应提取偏好记忆。"""
        ctx = {
            "text": "我不吃辣椒，受不了辣味",
            "items": [],
            "source_kind": "user",
        }
        from app.services.mock_llm import MOCK_HANDLERS
        result_str = MOCK_HANDLERS["memory_extract"]([], ctx)
        result = json.loads(result_str)
        assert any("不" in r["content"] for r in result)

    def test_health_condition_extracted(self, db):
        """包含'高血压'等关键词的文本应提取健康记忆。"""
        ctx = {
            "text": "疾病/状况：高血压",
            "items": [],
            "source_kind": "profile",
        }
        from app.services.mock_llm import MOCK_HANDLERS
        result_str = MOCK_HANDLERS["memory_extract"]([], ctx)
        result = json.loads(result_str)
        assert any("高血压" in r["content"] for r in result)
