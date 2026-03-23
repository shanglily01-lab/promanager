from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class SyncRequest(BaseModel):
    repos: list[str] = Field(
        default_factory=list,
        description="owner/repo；空则使用「数据库已启用仓库 + .env / REPOS_FILE」合并去重后的列表",
    )
    since_days: int = Field(15, ge=1, le=365, description="回溯抓取提交的天数")
    team: str | None = Field(None, description="团队标识（web3 / game）；空则不过滤团队")


class SyncResponse(BaseModel):
    sync_id: int
    commits_fetched: int
    contributors_created: int = Field(0, description="本次同步根据提交作者自动新建的成员档案数")
    status: str = Field(description="ok | partial（部分仓库拉取失败但其余已写入）| error")
    message: str | None = None


class SyncLogItem(BaseModel):
    """数据库 sync_logs 摘要，供所有客户端查看最近同步记录。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    started_at: datetime
    finished_at: datetime | None
    status: str
    commits_fetched: int
    repo_count: int = Field(description="本次涉及的仓库个数")
    error_preview: str | None = Field(None, description="失败时错误摘要")


class CodeCommitRepositoryItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    sync_key: str
    repository_name: str
    repository_id: str | None = None
    description: str | None = None
    clone_url_http: str | None = None
    clone_url_ssh: str | None = None
    last_modified: datetime | None = None


class CodeCommitRepoListResponse(BaseModel):
    region: str
    count: int
    sync_keys: list[str] = Field(description="可直接粘贴导入的 cc:区域/仓库名 列表（仓库名与 AWS 大小写一致）")
    repositories: list[CodeCommitRepositoryItem] = Field(
        default_factory=list,
        description="ListRepositories + BatchGetRepositories 合并后的详情（无 BatchGet 权限时仅含 sync_key / repository_name）",
    )


class TrackedRepoOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    full_name: str
    team: str
    enabled: bool
    notes: str
    created_at: datetime


class TrackedRepoCreate(BaseModel):
    full_name: str
    notes: str = ""
    team: str = "web3"


class TrackedRepoPatch(BaseModel):
    enabled: bool | None = None
    notes: str | None = None
    team: str | None = None


class RepoBulkCreate(BaseModel):
    full_names: list[str] = Field(default_factory=list)
    team: str = "web3"


class RepoBulkResult(BaseModel):
    added: list[str]
    skipped: list[str]
    errors: list[str]


class RepoMirrorItemOut(BaseModel):
    full_name: str
    status: str
    detail: str = ""
    local_rel_path: str = ""
    updated_at: datetime | None = None


class RepoMirrorCenterResponse(BaseModel):
    mirror_root: str
    git_available: bool
    aws_cli_available: bool
    scan_in_progress: bool
    items: list[RepoMirrorItemOut]


class RepoMirrorScanRequest(BaseModel):
    repos: list[str] = Field(
        default_factory=list,
        description="要检测的仓库列表；空则使用「数据库已启用 + .env / REPOS_FILE」合并列表",
    )


class RepoMirrorScanStarted(BaseModel):
    started: bool = True


class CommitItem(BaseModel):
    sha: str
    repo_full_name: str
    author_login: str | None
    author_email: str | None = None
    committed_at: datetime
    message: str
    html_url: str | None


class HabitsSummary(BaseModel):
    total_commits: int
    commits_by_hour_utc: dict[str, int]
    commits_by_weekday: dict[str, int]
    avg_message_length: float
    pct_messages_with_issue_ref: float
    most_active_hour_utc: int | None
    most_active_weekday: str | None
    # 来自同步时拉取的 commit 文件级画像 + 提交说明格式启发式（非 AST/语义）
    style_tags: list[str] = Field(default_factory=list)
    style_language_mix: dict[str, int] = Field(default_factory=dict)
    commits_with_style_sample: int = 0
    pct_conventional_commits: float = 0.0
    # 由提交说明文本启发式汇总（类型分布、Merge、中英文、多行等）
    commit_message_tags: list[str] = Field(default_factory=list)


class EmployeeSummary(BaseModel):
    """login 为报表主键：GitHub 登录、email:xxx@、contrib:档案ID 等。"""

    login: str
    display_name: str | None = None
    notes: str | None = None
    matched_emails: list[str] = Field(default_factory=list)
    github_login: str | None = None
    total_commits_in_range: int
    had_submission: bool
    repos_touched: list[str]


class ContributorCreate(BaseModel):
    nickname: str = Field(..., min_length=1, max_length=128)
    notes: str = ""
    emails: list[str] = Field(default_factory=list)
    github_logins: list[str] = Field(default_factory=list)
    team: str = "web3"


class ContributorAliasOut(BaseModel):
    id: int
    kind: str
    value_normalized: str


class ContributorOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    nickname: str
    notes: str
    team: str
    aliases: list[ContributorAliasOut]


class HabitChangeItem(BaseModel):
    dimension: str
    before_desc: str
    after_desc: str
    trend: str  # "up" | "down" | "stable" | "shift"
    conclusion: str
    significant: bool


class HabitChangeReport(BaseModel):
    period1_from: date
    period1_to: date
    period2_from: date
    period2_to: date
    period1_commits: int
    period2_commits: int
    changes: list[HabitChangeItem]
    summary: str


class DailyReport(BaseModel):
    report_date: date
    employees: list[EmployeeSummary]
    by_employee_commits: dict[str, list[CommitItem]]


class WeeklyReport(BaseModel):
    week_start: date
    week_end: date
    employees: list[EmployeeSummary]
    by_employee_commits: dict[str, list[CommitItem]]
    habits: dict[str, HabitsSummary]
