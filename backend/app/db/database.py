# Personal RAG - SQLAlchemy 数据库引擎与会话管理
"""
数据库连接模块

创建 SQLAlchemy 引擎和会话工厂，管理 SQLite 连接。
所有 ORM 模型共享同一个 Base 元数据对象。
"""

import uuid
from pathlib import Path

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import settings


class Base(DeclarativeBase):
    """SQLAlchemy ORM 基类，所有模型类继承自此。"""
    pass


def _get_database_path() -> Path:
    """获取 SQLite 数据库文件路径，确保父目录存在。"""
    db_path = settings.data_dir / "app.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return db_path


# ── 引擎与会话工厂 ──────────────────────────────────────────────

engine: Engine = create_engine(
    f"sqlite:///{_get_database_path()}",
    echo=settings.debug,
    connect_args={"check_same_thread": False},  # SQLite 多线程支持
)

SessionLocal: sessionmaker[Session] = sessionmaker(
    bind=engine,
    autocommit=False,
    autoflush=False,
)


# ── SQLite PRAGMA 配置 ──────────────────────────────────────────


@event.listens_for(engine, "connect")
def _set_sqlite_pragmas(dbapi_connection, connection_record):
    """在每次连接时启用 WAL 模式和外键约束。"""
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL;")
    cursor.execute("PRAGMA foreign_keys=ON;")
    cursor.close()


def init_db() -> None:
    """
    初始化数据库：创建所有 ORM 表。

    应在应用启动时调用。如果表已存在则跳过（不重复创建）。
    """
    Base.metadata.create_all(bind=engine)


def get_db() -> Session:
    """
    FastAPI 依赖注入：获取数据库会话。

    返回一个 SQLAlchemy Session，在请求结束后自动关闭。

    Yields:
        Session: SQLAlchemy 数据库会话
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
