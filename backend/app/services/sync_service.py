from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.codecommit_client import (
    fetch_codecommit_commits_normalized,
    is_codecommit_repo,
    parse_codecommit_ref,
)
from app.config import settings
from app.github_client import GitHubClient
from app.models import CommitRecord, SyncLog
from app.services.commit_style_analyzer import analyze_github_commit_detail
from app.services.identity_service import provision_contributors_from_normalized

ProgressEmitter = Callable[[dict[str, Any]], Awaitable[None]]


async def _emit(on_progress: ProgressEmitter | None, phase: str, **kwargs: Any) -> None:
    if on_progress:
        await on_progress({"phase": phase, **kwargs})


async def run_sync(
    db: Session,
    repos: list[str],
    since_days: int,
    *,
    on_progress: ProgressEmitter | None = None,
) -> tuple[int, int, str | None, int, str | None]:
    """
    返回 (sync_log_id, 新写入提交数, 致命错误信息, 新建成员档案数, 非致命提示).
    非致命提示：部分仓库拉取失败但其余已写入时，为人类可读摘要（如 partial 的 message）。
    """
    if not repos:
        msg = "未配置仓库：请在请求中传入 repos 或设置环境变量 DEFAULT_REPOS"
        await _emit(
            on_progress,
            "complete",
            ok=False,
            sync_id=0,
            commits_fetched=0,
            contributors_created=0,
            sync_status="error",
            message=msg,
        )
        return 0, 0, msg, 0, None

    now = datetime.now(timezone.utc)
    since = now - timedelta(days=since_days)

    await _emit(
        on_progress,
        "start",
        total_repos=len(repos),
        since_days=since_days,
        started_at=now.isoformat(),
    )

    normalized: list[dict[str, Any]] = []
    repo_errors: list[str] = []

    n_repos = len(repos)
    for idx, repo in enumerate(repos):
        r = repo.strip()
        kind = "codecommit" if is_codecommit_repo(r) else "github"
        await _emit(
            on_progress,
            "repo_fetch_start",
            index=idx + 1,
            total=n_repos,
            repo=r,
            kind=kind,
        )
        try:
            if is_codecommit_repo(r):
                parsed = parse_codecommit_ref(r)
                if not parsed:
                    raise ValueError(f"无效的 CodeCommit 仓库格式: {r}")
                region, name, br = parsed
                chunk = await asyncio.to_thread(
                    fetch_codecommit_commits_normalized,
                    region,
                    name,
                    br,
                    since,
                )
                normalized.extend(chunk)
                await _emit(
                    on_progress,
                    "repo_fetch_done",
                    repo=r,
                    commits=len(chunk),
                    kind=kind,
                )
            else:
                gh = GitHubClient(token=settings.github_token_for_repo(r))
                raw_list = await gh.fetch_commits_for_repo(r, since=since)
                added = 0
                for raw in raw_list:
                    n = GitHubClient.normalize_commit(r, raw)
                    if n:
                        normalized.append(n)
                        added += 1
                await _emit(
                    on_progress,
                    "repo_fetch_done",
                    repo=r,
                    commits=added,
                    raw_commits=len(raw_list),
                    kind=kind,
                )
        except Exception as ex:  # noqa: BLE001
            one = f"{r}: {ex}"
            repo_errors.append(one)
            await _emit(
                on_progress,
                "repo_fetch_error",
                repo=r,
                message=str(ex)[:800],
                kind=kind,
            )

    log = SyncLog(
        started_at=now,
        repos=json.dumps(repos, ensure_ascii=False),
        status="running",
    )
    db.add(log)
    db.commit()
    db.refresh(log)

    # 全部仓库都拉取失败且没有任何提交缓冲 → 记为 error；否则继续写入已成功拉取的部分
    if not normalized and repo_errors:
        combined = "；".join(repo_errors)[:8000]
        log.finished_at = datetime.now(timezone.utc)
        log.status = "error"
        log.error = combined
        db.add(log)
        db.commit()
        await _emit(
            on_progress,
            "complete",
            ok=False,
            sync_id=log.id,
            commits_fetched=0,
            contributors_created=0,
            sync_status="error",
            message=combined,
        )
        return log.id, 0, combined, 0, None

    fetch_warning: str | None = None
    if repo_errors:
        fetch_warning = ("部分仓库拉取失败（已跳过，其余照常入库）：" + "；".join(repo_errors))[:7900]

    await _emit(
        on_progress,
        "fetch_done",
        commits_buffered=len(normalized),
        skipped_repos=len(repo_errors),
    )

    total = 0
    n_provisioned = 0
    err: str | None = None
    n_norm = len(normalized)
    write_every = 400
    style_fetch_budget = settings.github_commit_style_max_per_sync
    style_fetch_count = 0
    try:
        await _emit(on_progress, "write_start", total_to_scan=n_norm)
        for i, norm in enumerate(normalized):
            exists = (
                db.execute(
                    select(CommitRecord).where(
                        CommitRecord.sha == norm["sha"],
                        CommitRecord.repo_full_name == norm["repo_full_name"],
                    )
                )
                .scalars()
                .first()
            )
            if exists:
                continue
            style_blob: str | None = None
            if (
                settings.github_commit_style_fetch_enabled
                and style_fetch_budget > 0
                and not is_codecommit_repo(norm["repo_full_name"])
            ):
                style_fetch_budget -= 1
                style_fetch_count += 1
                gh_style = GitHubClient(token=settings.github_token_for_repo(norm["repo_full_name"]))
                detail = await gh_style.fetch_commit_detail(norm["repo_full_name"], norm["sha"])
                if detail:
                    snap = analyze_github_commit_detail(detail)
                    if snap:
                        style_blob = json.dumps(snap, ensure_ascii=False)
                if style_fetch_count % 20 == 0:
                    await asyncio.sleep(0.06)
            db.add(
                CommitRecord(
                    sha=norm["sha"],
                    repo_full_name=norm["repo_full_name"],
                    author_login=(norm["author_login"] or "").lower() or None,
                    author_email=norm["author_email"],
                    author_name=norm["author_name"],
                    committed_at=norm["committed_at"],
                    message=norm["message"],
                    html_url=norm["html_url"],
                    commit_style_json=style_blob,
                )
            )
            total += 1
            if on_progress and total > 0 and total % write_every == 0:
                await _emit(
                    on_progress,
                    "write_progress",
                    new_commits=total,
                    processed=i + 1,
                    of=n_norm,
                )
        await _emit(on_progress, "provision_start")
        n_provisioned = provision_contributors_from_normalized(db, normalized)
        await _emit(on_progress, "provision_done", contributors_created=n_provisioned)
        db.commit()
        log.finished_at = datetime.now(timezone.utc)
        log.commits_fetched = total
        log.status = "partial" if fetch_warning else "ok"
        if fetch_warning:
            log.error = fetch_warning[:8000]
        db.add(log)
        db.commit()
        await _emit(
            on_progress,
            "complete",
            ok=True,
            sync_id=log.id,
            commits_fetched=total,
            contributors_created=n_provisioned,
            sync_status="partial" if fetch_warning else "ok",
            message=fetch_warning,
        )
    except Exception as e:  # noqa: BLE001
        err = str(e)
        db.rollback()
        n_provisioned = 0
        log.finished_at = datetime.now(timezone.utc)
        log.status = "error"
        log.error = err[:8000]
        db.add(log)
        db.commit()
        await _emit(
            on_progress,
            "complete",
            ok=False,
            sync_id=log.id,
            commits_fetched=0,
            contributors_created=0,
            sync_status="error",
            message=err,
        )

    return log.id, total, err, n_provisioned, None if err else fetch_warning
