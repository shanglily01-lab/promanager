from pathlib import Path
from urllib.parse import quote

from dotenv import load_dotenv
from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(BACKEND_ROOT / ".env")


def _split_repos_blob(text: str) -> list[str]:
    """支持逗号、换行、分号分隔的 owner/repo 列表。"""
    if not text or not text.strip():
        return []
    raw = text.replace(";", ",").replace("\n", ",")
    return [p.strip() for p in raw.split(",") if p.strip()]


def _repos_from_file(path: Path) -> list[str]:
    if not path.is_file():
        return []
    out: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        if "#" in s:
            s = s.split("#", 1)[0].strip()
        if s:
            out.append(s)
    return out


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(BACKEND_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    github_token: str = ""
    # owner/repo，可用逗号、换行、分号分隔（适合 .env 里写多行时用引号包裹）
    default_repos: str = ""
    # 可选：仓库列表文件路径（相对 backend 目录或绝对路径），每行一个 owner/repo，# 为注释
    repos_file: str = ""
    # Optional: comma-separated GitHub logins to treat as employees (otherwise inferred from commits)
    team_members: str = ""
    # 同步后按提交作者自动创建成员档案（邮箱 / GitHub 登录别名）；设为 false 可关闭
    auto_provision_contributors: bool = Field(
        default=True,
        validation_alias=AliasChoices("AUTO_PROVISION_CONTRIBUTORS", "auto_provision_contributors"),
    )
    # SQLite 默认：./data/promanager.db（相对 backend 目录）
    # 或直接写完整连接串：mysql+pymysql://用户:密码@主机:3306/库?charset=utf8mb4（密码含 @# 需 URL 编码）
    database_url: str = "sqlite:///./data/promanager.db"
    # 可选：分项配置 MySQL（与 database_url 二选一；若同时存在 DB_HOST 则优先用下列项拼连接串）
    db_host: str = ""
    db_port: int = Field(default=3306, ge=1, le=65535)
    db_user: str = ""
    db_password: str = ""
    db_name: str = ""
    # AWS 区域（CodeCommit 列举仓库；与 .env 中 AWS_DEFAULT_REGION 一致）
    aws_default_region: str = Field(
        default="",
        validation_alias=AliasChoices("AWS_DEFAULT_REGION", "aws_default_region"),
    )
    # 同步回溯天数：API 默认与后台定时同步共用（前端仍可每次改大/改小）
    default_since_days: int = Field(
        default=15,
        ge=1,
        le=365,
        validation_alias=AliasChoices("DEFAULT_SINCE_DAYS", "default_since_days"),
    )
    # 后台定时同步合并仓库列表（与 POST /api/sync 空 repos 相同）
    background_sync_enabled: bool = Field(
        default=True,
        validation_alias=AliasChoices("BACKGROUND_SYNC_ENABLED", "background_sync_enabled"),
    )
    background_sync_interval_hours: float = Field(
        default=4.0,
        ge=1.0 / 60.0,
        le=168.0,
        validation_alias=AliasChoices("BACKGROUND_SYNC_INTERVAL_HOURS", "background_sync_interval_hours"),
    )
    background_sync_initial_delay_seconds: float = Field(
        default=60.0,
        ge=0.0,
        validation_alias=AliasChoices(
            "BACKGROUND_SYNC_INITIAL_DELAY_SECONDS",
            "background_sync_initial_delay_seconds",
        ),
    )

    @staticmethod
    def _strip_outer_quotes(v: object) -> str:
        if v is None:
            return ""
        s = str(v).strip()
        if len(s) >= 2 and s[0] == s[-1] and s[0] in "\"'":
            return s[1:-1]
        return s

    @field_validator("db_user", "db_password", mode="before")
    @classmethod
    def _env_strip_quotes(cls, v: object) -> str:
        return cls._strip_outer_quotes(v)

    @property
    def effective_database_url(self) -> str:
        if self.db_host.strip() and self.db_user.strip() and self.db_name.strip():
            # RFC 3986 userinfo：用 quote 而非 quote_plus，避免空格变成 + 等歧义
            user = quote(self.db_user.strip(), safe="")
            pw = quote(self.db_password or "", safe="")
            return (
                f"mysql+pymysql://{user}:{pw}@{self.db_host.strip()}:"
                f"{int(self.db_port)}/{self.db_name.strip()}?charset=utf8mb4"
            )
        return self.database_url

    @property
    def repos_file_path(self) -> Path | None:
        p = (self.repos_file or "").strip()
        if not p:
            return None
        path = Path(p)
        if not path.is_absolute():
            path = BACKEND_ROOT / path
        return path

    @property
    def repo_list(self) -> list[str]:
        from app.services.repo_list_service import normalize_repo_full_name

        from_env = _split_repos_blob(self.default_repos)
        path = self.repos_file_path
        from_file = _repos_from_file(path) if path else []
        merged: list[str] = []
        seen_set: set[str] = set()
        for r in from_env + from_file:
            try:
                nr = normalize_repo_full_name(r.strip())
            except ValueError:
                continue
            key = nr.lower()
            if key in seen_set:
                continue
            seen_set.add(key)
            merged.append(nr)
        return merged

    @property
    def member_logins(self) -> list[str]:
        return [m.strip().lower() for m in self.team_members.split(",") if m.strip()]


settings = Settings()
