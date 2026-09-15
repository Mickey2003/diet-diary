"""测试夹具：使用独立的临时 SQLite 与 mock 模型，不联网；自动以测试管理员登录。"""
import os
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

import pytest

_tmp = tempfile.mkdtemp(prefix="diet_test_")
os.environ["DATABASE_URL"] = f"sqlite:///{Path(_tmp) / 'test.db'}"
os.environ["UPLOAD_DIR"] = str(Path(_tmp) / "uploads")
os.environ["DATA_DIR"] = _tmp
os.environ["LLM_PROVIDER"] = "mock"
os.environ["LLM_API_KEY"] = ""
os.environ["ADMIN_USERNAME"] = "tester"
os.environ["ADMIN_PASSWORD"] = "test-pass-123"
os.environ["ENABLE_SCHEDULER"] = "0"
# 测试不联网：关闭菜品网络配图、条码补充数据源与网络加速探测
os.environ["DISH_IMAGES_WEB"] = "0"
os.environ["BARCODE_EXTRA_SOURCES"] = "0"
os.environ["NET_PROXY_MODE"] = "off"

TEST_USER = ("tester", "test-pass-123")

from fastapi.testclient import TestClient  # noqa: E402

from app.db import SessionLocal, init_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Meal, MealItem, meal_item_tags  # noqa: E402
from app.services.tags import tag_lookup  # noqa: E402
from app.services.timeutil import today_local  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _db():
    init_db()
    yield


@pytest.fixture()
def db():
    s = SessionLocal()
    try:
        yield s
    finally:
        s.close()


@pytest.fixture()
def anon_client():
    """未登录的客户端。"""
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def client():
    """已登录的客户端（Cookie 会话）。"""
    with TestClient(app) as c:
        r = c.post("/api/auth/login", json={"username": TEST_USER[0], "password": TEST_USER[1]})
        assert r.status_code == 200, r.text
        yield c


def add_meal(db, days_ago: int, hour: int, meal_type: str, items, user_id=None):
    """items: [(name, category, tags)]；默认归属测试管理员。"""
    from app.models import User
    if user_id is None:
        user_id = db.query(User).filter(User.username == TEST_USER[0]).first().id
    lookup = tag_lookup(db)
    d = today_local() - timedelta(days=days_ago)
    m = Meal(user_id=user_id, eaten_at=datetime.combine(d, datetime.min.time()) + timedelta(hours=hour),
             meal_type=meal_type)
    for i, (name, cat, tags) in enumerate(items):
        mi = MealItem(name=name, category=cat, portion="中", source="ai", sort_order=i)
        mi.tags = [lookup[t] for t in tags]
        m.items.append(mi)
    db.add(m)
    db.commit()
    db.refresh(m)
    return m


@pytest.fixture()
def clean_meals(db):
    db.execute(meal_item_tags.delete())
    db.query(MealItem).delete()
    db.query(Meal).delete()
    db.commit()
    yield
