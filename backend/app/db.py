"""SQLite + SQLAlchemy 会话管理、初始化与轻量迁移。"""
from typing import Dict, List

from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from .config import DATABASE_URL


class Base(DeclarativeBase):
    pass


connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=connect_args, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)

if DATABASE_URL.startswith("sqlite"):
    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(dbapi_conn, _record):  # noqa: ANN001
        # SQLite 默认不启用外键约束：不打开的话 ON DELETE CASCADE 不会生效，
        # 批量删除 meal_items 会在 meal_item_tags 留下孤儿行。
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.execute("PRAGMA journal_mode=WAL")
        cur.close()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# 旧版本数据库缺少的列：表 -> [(列名, DDL 类型)]
_MIGRATION_COLUMNS: Dict[str, List[tuple]] = {
    "users": [("role", "VARCHAR(10) DEFAULT 'user'"), ("display_name", "VARCHAR(40)"),
              ("is_active", "BOOLEAN DEFAULT 1"), ("is_approved", "BOOLEAN DEFAULT 1")],
    "sound_files": [("is_system", "BOOLEAN DEFAULT 0")],
    "meals": [("user_id", "INTEGER REFERENCES users(id) ON DELETE CASCADE"),
              ("source", "VARCHAR(20) DEFAULT 'photo'")],
    "meal_items": [("barcode", "VARCHAR(32)"), ("kcal", "INTEGER"), ("kcal_source", "VARCHAR(12)")],
    "reports": [("user_id", "INTEGER REFERENCES users(id) ON DELETE CASCADE")],
    "query_logs": [("user_id", "INTEGER REFERENCES users(id) ON DELETE CASCADE")],
    "notify_logs": [("user_id", "INTEGER REFERENCES users(id) ON DELETE CASCADE")],
    "inbox_messages": [("extra", "TEXT")],
}


def migrate() -> List[str]:
    """给旧库补列（SQLite 只支持 ADD COLUMN），并把无主数据回填给第一个管理员。返回执行过的操作描述。"""
    done: List[str] = []
    insp = inspect(engine)
    existing_tables = set(insp.get_table_names())
    with engine.begin() as conn:
        for table, cols in _MIGRATION_COLUMNS.items():
            if table not in existing_tables:
                continue
            have = {c["name"] for c in insp.get_columns(table)}
            for name, ddl in cols:
                if name not in have:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}"))
                    done.append(f"{table}.{name}")
        # 第一个用户升级为管理员（旧库只有一个 admin 用户但没有 role 列）
        first = conn.execute(text("SELECT id FROM users ORDER BY id LIMIT 1")).fetchone()
        if first is not None:
            uid = first[0]
            n = conn.execute(text("SELECT COUNT(*) FROM users WHERE role='admin'")).scalar() or 0
            if n == 0:
                conn.execute(text("UPDATE users SET role='admin' WHERE id=:id"), {"id": uid})
                done.append("users.first->admin")
            for table in ("meals", "reports", "query_logs", "notify_logs"):
                if table in existing_tables:
                    r = conn.execute(text(f"UPDATE {table} SET user_id=:id WHERE user_id IS NULL"), {"id": uid})
                    if r.rowcount:
                        done.append(f"{table}.user_id backfill {r.rowcount}")
        # 旧版全局通知配置迁移到第一个管理员的个人设置
        if "settings" in existing_tables and first is not None:
            row = conn.execute(text("SELECT value FROM settings WHERE key='notify_config'")).fetchone()
            if row is not None and row[0]:
                exists = conn.execute(text("SELECT 1 FROM user_settings WHERE user_id=:u AND key='notify_config'"),
                                      {"u": first[0]}).fetchone()
                if exists is None:
                    conn.execute(text("INSERT INTO user_settings(user_id, key, value) VALUES (:u, 'notify_config', :v)"),
                                 {"u": first[0], "v": row[0]})
                conn.execute(text("DELETE FROM settings WHERE key='notify_config'"))
                done.append("notify_config -> user_settings")
    return done


def init_db():
    """建表 + 迁移 + 标签字典 + 初始管理员。幂等，可重复调用。"""
    from . import models  # noqa: F401  确保模型已注册
    from .services.auth import ensure_admin, purge_expired
    from .services.tags import ensure_tags

    Base.metadata.create_all(bind=engine)
    done = migrate()
    if done:
        print(f"[db] 迁移完成：{', '.join(done)}", flush=True)
    with SessionLocal() as db:
        ensure_tags(db)
        db.commit()
        ensure_admin(db)
        purge_expired(db)
