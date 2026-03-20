"""AWS CodeCommit：拉取提交并规范为与 GitHub 同步相同的字段结构。"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

_BRANCH_PREFS = ("main", "master", "prod", "develop", "dev")


def is_codecommit_repo(repo_key: str) -> bool:
    return repo_key.strip().lower().startswith("cc:")


def parse_codecommit_ref(repo_key: str) -> tuple[str, str, str | None] | None:
    """
    cc:区域/仓库名 或 cc:区域/仓库名@分支
    分支可含 /（在 @ 之后）。
    """
    t = repo_key.strip()
    if not t.lower().startswith("cc:"):
        return None
    rest = t[3:].strip()
    branch: str | None = None
    if "@" in rest:
        rest, br = rest.rsplit("@", 1)
        branch = br.strip() or None
    if "/" not in rest:
        return None
    region, repo = rest.split("/", 1)
    region, repo = region.strip().lower(), repo.strip()
    if not region or not repo:
        return None
    return region, repo, branch


def _resolve_branch(client: Any, repository_name: str, explicit: str | None) -> str:
    if explicit:
        return explicit
    resp = client.list_branches(repositoryName=repository_name)
    branches = list(resp.get("branches", []))
    if not branches:
        raise RuntimeError(f"CodeCommit 仓库 {repository_name!r} 没有任何分支")
    by_lower = {b.lower(): b for b in branches}
    for pref in _BRANCH_PREFS:
        if pref in by_lower:
            return by_lower[pref]
    return sorted(branches, key=str.lower)[0]


def _parse_commit_date(date_str: str) -> datetime:
    """CodeCommit 可能返回 ISO8601 或 Git 格式「unix +0800」。"""
    s = date_str.strip()
    if not s:
        raise ValueError("empty author date")
    if "T" in s or s.endswith("Z"):
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    parts = s.split()
    if parts and parts[0].isdigit():
        ts = int(parts[0])
        return datetime.fromtimestamp(ts, tz=timezone.utc)
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def _pseudo_login(email: str | None, name: str | None) -> str | None:
    if email and "@" in email:
        local = email.split("@", 1)[0].strip().lower()
        return local or None
    if name:
        s = re.sub(r"[^\w.-]+", "-", name.strip().lower()).strip("-")
        return s[:64] or None
    return None


def _console_commit_url(region: str, repository_name: str, commit_id: str) -> str:
    return (
        f"https://{region}.console.aws.amazon.com/codesuite/codecommit/repositories/"
        f"{repository_name}/commit/{commit_id}?region={region}"
    )


def fetch_codecommit_commits_normalized(
    region: str,
    repository_name: str,
    explicit_branch: str | None,
    since: datetime,
    *,
    max_commits: int = 8000,
) -> list[dict[str, Any]]:
    """
    沿第一父提交回溯，直到遇到 committed_at < since 或无父节点。
    返回与 GitHubClient.normalize_commit 相同键的字典列表。
    """
    try:
        import boto3
        from botocore.exceptions import ClientError, NoCredentialsError
    except ModuleNotFoundError as e:
        raise RuntimeError(
            "未安装 boto3。在 backend 目录执行: .venv\\Scripts\\pip install -r requirements.txt "
            "并用 .venv\\Scripts\\python.exe -m uvicorn 启动（勿用未装依赖的全局 python）。"
        ) from e

    try:
        client = boto3.client("codecommit", region_name=region)
    except NoCredentialsError as e:
        raise RuntimeError("未配置 AWS 凭证（AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY 或默认凭证链）") from e

    branch_name = _resolve_branch(client, repository_name, explicit_branch)
    gb = client.get_branch(repositoryName=repository_name, branchName=branch_name)
    tip = gb["branch"]["commitId"]

    since_utc = since.astimezone(timezone.utc)
    base_key = f"cc:{region}/{repository_name}"
    repo_full = f"{base_key}@{explicit_branch}" if explicit_branch else base_key

    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    current: str | None = tip

    while current and len(out) < max_commits:
        if current in seen:
            break
        seen.add(current)
        try:
            gc = client.get_commit(repositoryName=repository_name, commitId=current)
        except ClientError:
            break
        commit = gc.get("commit") or {}
        author = commit.get("author") or {}
        date_str = author.get("date") or (commit.get("committer") or {}).get("date")
        if not date_str:
            break
        committed_at = _parse_commit_date(date_str)
        if committed_at < since_utc:
            break

        msg = (commit.get("message") or "").strip()
        email = (author.get("email") or "").strip() or None
        name = (author.get("name") or "").strip() or None
        login = _pseudo_login(email, name)

        out.append(
            {
                "sha": current,
                "repo_full_name": repo_full,
                "author_login": login,
                "author_email": email,
                "author_name": name,
                "committed_at": committed_at,
                "message": msg,
                "html_url": _console_commit_url(region, repository_name, current),
            }
        )

        parents = commit.get("parents") or []
        current = parents[0] if parents else None

    return out


def list_codecommit_repository_catalog(region: str) -> list[dict[str, Any]]:
    """
    列举该区域账号可见的 CodeCommit 仓库。

    仓库名保持与 AWS 返回一致（大小写敏感）；勿随意转小写，否则 GetBranch/GetCommit 会报仓库不存在。
    在 ListRepositories 基础上尽量调用 BatchGetRepositories 补充描述、克隆地址等（无权限时仅返回 sync_key）。
    """
    try:
        import boto3
        from botocore.exceptions import ClientError, NoCredentialsError
    except ModuleNotFoundError as e:
        raise RuntimeError(
            "未安装 boto3。请 pip install -r requirements.txt 并用虚拟环境启动 uvicorn。"
        ) from e

    r = region.strip().lower()
    if not r:
        raise ValueError("region 不能为空")
    try:
        client = boto3.client("codecommit", region_name=r)
    except NoCredentialsError as e:
        raise RuntimeError("未配置 AWS 凭证（AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY 等）") from e

    names: list[str] = []
    token: str | None = None
    while True:
        kwargs: dict[str, str] = {}
        if token:
            kwargs["nextToken"] = token
        try:
            resp = client.list_repositories(**kwargs)
        except ClientError as e:
            err = e.response.get("Error", {}) if e.response else {}
            raise RuntimeError(
                err.get("Message", str(e))[:500] or str(e)[:500]
            ) from e
        for m in resp.get("repositories", []) or []:
            n = m.get("repositoryName")
            if n:
                names.append(n)
        token = resp.get("nextToken")
        if not token:
            break

    def _row(name: str, meta: dict[str, Any] | None) -> dict[str, Any]:
        row: dict[str, Any] = {
            "sync_key": f"cc:{r}/{name}",
            "repository_name": name,
            "repository_id": None,
            "description": None,
            "clone_url_http": None,
            "clone_url_ssh": None,
            "last_modified": None,
        }
        if not meta:
            return row
        desc = (meta.get("repositoryDescription") or "").strip()
        row["repository_id"] = meta.get("repositoryId")
        row["description"] = desc or None
        row["clone_url_http"] = meta.get("cloneUrlHttp")
        row["clone_url_ssh"] = meta.get("cloneUrlSsh")
        row["last_modified"] = meta.get("lastModifiedDate")
        return row

    items: list[dict[str, Any]] = []
    chunk_size = 100
    for i in range(0, len(names), chunk_size):
        chunk = names[i : i + chunk_size]
        try:
            bgr = client.batch_get_repositories(repositoryNames=chunk)
        except ClientError as e:
            err = e.response.get("Error", {}) if e.response else {}
            code = err.get("Code", "") or ""
            msg = (err.get("Message") or "").lower()
            if "accessdenied" in code.lower() or "not authorized" in msg or "access denied" in msg:
                for name in chunk:
                    items.append(_row(name, None))
                continue
            raise RuntimeError(
                err.get("Message", str(e))[:500] or str(e)[:500]
            ) from e
        by_name = {x["repositoryName"]: x for x in (bgr.get("repositories") or [])}
        for name in chunk:
            items.append(_row(name, by_name.get(name)))

    items.sort(key=lambda x: (x["repository_name"] or "").lower())
    return items


def list_codecommit_sync_keys(region: str) -> list[str]:
    """兼容旧调用：仅返回 sync_key 列表。"""
    return [x["sync_key"] for x in list_codecommit_repository_catalog(region)]
