import logging
from pathlib import Path

from fastapi import HTTPException
from sqlalchemy import create_engine, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from starlette.requests import Request

from app.config import settings


class Base(DeclarativeBase):
    pass


BACKEND_ROOT = Path(__file__).resolve().parent.parent


def _resolve_database_url(url: str) -> str:
    if url.startswith("sqlite:///./"):
        rel = url.removeprefix("sqlite:///./")
        path = (BACKEND_ROOT / rel).resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        return f"sqlite:///{path.as_posix()}"
    return url


_url = _resolve_database_url(settings.effective_database_url)
_is_sqlite = _url.lower().startswith("sqlite:")

_engine_connect_args: dict = {"check_same_thread": False} if _is_sqlite else {}
if not _is_sqlite and _url.lower().startswith("mysql"):
    _engine_connect_args = {**_engine_connect_args, "charset": "utf8mb4"}

engine = create_engine(
    _url,
    connect_args=_engine_connect_args,
    pool_pre_ping=not _is_sqlite,
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db(request: Request):
    err = getattr(request.app.state, "db_init_error", None)
    if err:
        raise HTTPException(
            status_code=503,
            detail=(
                "数据库未就绪（启动时建表/连接失败）。请检查 .env 中 DB_* 或 DATABASE_URL、"
                "MySQL 是否允许本机 IP、安全组与账号权限。详情: "
                + err[:800]
            ),
        )
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _mysql_convert_tables_utf8mb4() -> None:
    """已有表若为 latin1/utf8(3字节)，写入中文会 1366；启动时尝试改为 utf8mb4。"""
    if engine.dialect.name != "mysql":
        return
    names = (
        "tracked_repos",
        "contributors",
        "contributor_aliases",
        "commits",
        "sync_logs",
    )
    with engine.begin() as conn:
        for t in names:
            try:
                conn.execute(
                    text(
                        f"ALTER TABLE `{t}` CONVERT TO CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
                    )
                )
            except Exception as e:  # noqa: BLE001
                logging.warning("MySQL 表 %s 转为 utf8mb4 跳过或失败: %s", t, e)


def init_db():
    from app import models  # noqa: F401

    Base.metadata.create_all(bind=engine)
    _mysql_convert_tables_utf8mb4()
