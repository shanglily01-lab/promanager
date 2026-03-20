from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

# MySQL 须 utf8mb4 才能存中文提交说明等；SQLite 会忽略下列键
_MYSQL_UTF8MB4 = {"mysql_charset": "utf8mb4", "mysql_collate": "utf8mb4_unicode_ci"}


class TrackedRepository(Base):
    """在库中维护要同步的 GitHub 仓库（owner/repo），无需只依赖 .env。"""

    __tablename__ = "tracked_repos"
    __table_args__ = (
        UniqueConstraint("full_name", name="uq_tracked_repo_full_name"),
        _MYSQL_UTF8MB4,
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    full_name: Mapped[str] = mapped_column(String(255), index=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )


class Contributor(Base):
    """成员档案：昵称、备注；通过 ContributorAlias 绑定多个邮箱或 GitHub 登录。"""

    __tablename__ = "contributors"
    __table_args__ = _MYSQL_UTF8MB4

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    nickname: Mapped[str] = mapped_column(String(128))
    notes: Mapped[str] = mapped_column(Text, default="")
    aliases: Mapped[list["ContributorAlias"]] = relationship(
        "ContributorAlias", back_populates="contributor", cascade="all, delete-orphan"
    )


class ContributorAlias(Base):
    __tablename__ = "contributor_aliases"
    __table_args__ = (
        UniqueConstraint("kind", "value_normalized", name="uq_contributor_alias_kind_value"),
        _MYSQL_UTF8MB4,
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    contributor_id: Mapped[int] = mapped_column(Integer, ForeignKey("contributors.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(16))  # "email" | "login"
    value_normalized: Mapped[str] = mapped_column(String(255), index=True)

    contributor: Mapped["Contributor"] = relationship("Contributor", back_populates="aliases")


class CommitRecord(Base):
    __tablename__ = "commits"
    __table_args__ = (
        UniqueConstraint("sha", "repo_full_name", name="uq_commit_repo"),
        _MYSQL_UTF8MB4,
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    sha: Mapped[str] = mapped_column(String(40), index=True)
    repo_full_name: Mapped[str] = mapped_column(String(255), index=True)
    author_login: Mapped[str | None] = mapped_column(String(255), index=True, nullable=True)
    author_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    author_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    committed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    message: Mapped[str] = mapped_column(Text, default="")
    html_url: Mapped[str | None] = mapped_column(String(512), nullable=True)


class SyncLog(Base):
    __tablename__ = "sync_logs"
    __table_args__ = _MYSQL_UTF8MB4

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    repos: Mapped[str] = mapped_column(Text)  # JSON or comma-separated
    commits_fetched: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(64), default="running")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
