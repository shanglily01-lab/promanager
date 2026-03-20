from __future__ import annotations

import re
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.codecommit_client import is_codecommit_repo, parse_codecommit_ref
from app.config import settings
from app.models import TrackedRepository

# GitHub owner/name：宽松校验（含 . - _）
_REPO_RE = re.compile(r"^[\w.-]+/[\w.-]+$")
_GITHUB_HTTPS = re.compile(
    r"^(?:https?://)?(?:www\.)?github\.com/([\w.-]+)/([\w.-]+?)(?:\.git)?/?$",
    re.I,
)
_GITHUB_SSH = re.compile(r"^git@github\.com:([\w.-]+)/([\w.-]+?)(?:\.git)?$", re.I)


def _strip_github_url_to_owner_repo(s: str) -> str | None:
    """若为 GitHub 网页/clone 地址，返回 owner/repo；否则 None。"""
    t = s.strip().rstrip("/")
    t = re.sub(r"\.git$", "", t, flags=re.I).rstrip("/")
    m = _GITHUB_HTTPS.match(t)
    if m:
        return f"{m.group(1)}/{m.group(2)}"
    m = _GITHUB_SSH.match(t)
    if m:
        return f"{m.group(1)}/{m.group(2)}"
    return None


def normalize_repo_full_name(raw: str) -> str:
    """接受 owner/repo、GitHub 链接，或 CodeCommit：cc:区域/仓库名[@分支]。"""
    s = raw.strip()
    if not s:
        raise ValueError("仓库不能为空")
    if is_codecommit_repo(s):
        p = parse_codecommit_ref(s)
        if not p:
            raise ValueError(
                "CodeCommit 格式应为 cc:区域/仓库名 或 cc:区域/仓库名@分支，"
                "例如 cc:ap-southeast-1/chain-payment-web"
            )
        region, repo, br = p
        base = f"cc:{region}/{repo.strip()}"
        if br:
            return f"{base}@{br.strip()}"
        return base
    coerced = _strip_github_url_to_owner_repo(s)
    if coerced:
        s = coerced
    else:
        s = re.sub(r"\.git$", "", s, flags=re.I).strip()
    if s.count("/") != 1:
        raise ValueError(
            "格式应为 owner/repo，或 GitHub 链接，例如 https://github.com/shanglily01-lab/test2 或 shanglily01-lab/test2"
        )
    owner, name = s.split("/", 1)
    owner, name = owner.strip(), name.strip()
    if not owner or not name:
        raise ValueError("owner 与 repo 名称不能为空")
    combined = f"{owner}/{name}"
    if not _REPO_RE.match(combined):
        raise ValueError("仓库名包含非法字符")
    return f"{owner.lower()}/{name.lower()}"


def repos_from_database(db: Session, *, enabled_only: bool = True) -> list[str]:
    q = select(TrackedRepository.full_name).order_by(TrackedRepository.id)
    if enabled_only:
        q = q.where(TrackedRepository.enabled.is_(True))
    return list(db.execute(q).scalars().all())


def merged_sync_repos(db: Session) -> list[str]:
    """数据库中已启用仓库优先列出，再并入 .env / REPOS_FILE，全局去重（小写）。"""
    seen: set[str] = set()
    out: list[str] = []
    for r in repos_from_database(db):
        k = r.lower()
        if k not in seen:
            seen.add(k)
            out.append(r)
    for r in settings.repo_list:
        k = r.strip().lower()
        if not k:
            continue
        if k not in seen:
            seen.add(k)
            out.append(r.strip())
    return out
