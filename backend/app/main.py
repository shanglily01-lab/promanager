from __future__ import annotations

import asyncio
import json
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from datetime import date, datetime, time, timedelta, timezone

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse, StreamingResponse
from sqlalchemy import delete, func, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.codecommit_client import list_codecommit_repository_catalog
from app.config import settings
from app.database import SessionLocal, get_db, init_db
from app.models import CommitRecord, Contributor, ContributorAlias, SyncLog, TrackedRepository
from app.schemas import (
    CodeCommitRepoListResponse,
    CodeCommitRepositoryItem,
    CommitItem,
    ContributorAliasOut,
    ContributorCreate,
    ContributorOut,
    HabitChangeReport,
    HabitsSummary,
    RepoBulkCreate,
    RepoBulkResult,
    RepoMirrorCenterResponse,
    RepoMirrorItemOut,
    RepoMirrorScanRequest,
    RepoMirrorScanStarted,
    SyncLogItem,
    SyncRequest,
    SyncResponse,
    TrackedRepoCreate,
    TrackedRepoOut,
    TrackedRepoPatch,
)
from app.services.identity_service import (
    commit_filter_for_employee_key,
    normalize_email,
    suggested_employee_key_options,
    suggested_employee_keys,
)
from app.services.report_service import (
    build_daily_report,
    build_weekly_report,
    compute_habits,
    markdown_daily,
    markdown_weekly,
)
from app.services.background_sync import run_background_sync_loop
from app.services.repo_list_service import (
    merged_sync_repos,
    normalize_repo_full_name,
    repos_from_database,
)
from app.services.repo_mirror_service import (
    build_center_payload,
    end_scan,
    run_mirror_scan_db,
    try_begin_scan,
)
from app.services.sync_service import run_sync
from app.services.habit_change_service import analyze_habit_changes


def _mirror_scan_background(repos: list[str] | None) -> None:
    """在独立线程中执行；任何未捕获异常都会污染 uvicorn ASGI 日志，故整体包一层。"""
    try:
        db = SessionLocal()
        try:
            run_mirror_scan_db(db, repos_filter=repos)
        except Exception:  # noqa: BLE001
            logging.exception("仓库中心后台扫描失败（已回滚当前会话）")
            try:
                db.rollback()
            except Exception:  # noqa: BLE001
                pass
        finally:
            db.close()
    finally:
        end_scan()


@asynccontextmanager
async def _lifespan(app: FastAPI):
    """建表失败时不阻塞进程启动，便于 /api/health 返回明确原因（如 MySQL 连不上）。"""
    app.state.db_init_error = None
    app.state.last_background_sync_at = None
    app.state.last_background_sync_ok = None
    app.state.last_background_sync_detail = None
    try:
        init_db()
    except Exception as e:  # noqa: BLE001
        msg = f"{type(e).__name__}: {e}"
        app.state.db_init_error = msg[:1200]
        logging.exception("init_db 失败: %s", msg)
    bg_task: asyncio.Task[None] | None = None
    if settings.background_sync_enabled:
        bg_task = asyncio.create_task(run_background_sync_loop(app))
    try:
        yield
    finally:
        if bg_task is not None:
            bg_task.cancel()
            try:
                await bg_task
            except asyncio.CancelledError:
                pass


app = FastAPI(title="ProManager", version="0.1.0", lifespan=_lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_allow_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(OperationalError)
async def _handle_db_operational_error(_request: Request, exc: OperationalError):
    """旧库缺表（如 tracked_repos）时自动补建，并提示用户重试。"""
    raw = str(getattr(exc, "orig", exc) or exc).lower()
    if (
        "no such table" in raw
        or "doesn't exist" in raw
        or "1146" in raw
        or "unknown table" in raw
    ):
        try:
            init_db()
        except Exception:  # noqa: BLE001
            pass
        return JSONResponse(
            status_code=503,
            content={
                "detail": "数据库缺少新表，已尝试自动创建。请再点一次「导入」；若仍失败，请完全重启后端（停止 uvicorn 后重新运行）。"
            },
        )
    return JSONResponse(
        status_code=503,
        content={"detail": f"数据库错误: {str(exc)[:300]}"},
    )


@app.get("/api/health")
def health(request: Request):
    token = (settings.github_token or "").strip()
    repo_map = settings.github_token_repo_map
    db_err = getattr(request.app.state, "db_init_error", None)
    commit_count: int | None = None
    if db_err is None:
        try:
            s = SessionLocal()
            try:
                commit_count = s.execute(select(func.count(CommitRecord.id))).scalar_one()
            finally:
                s.close()
        except Exception:  # noqa: BLE001
            commit_count = None
    ar = (settings.aws_default_region or "").strip()
    lat = getattr(request.app.state, "last_background_sync_at", None)
    return {
        "ok": True,
        "has_token": bool(token) or bool(repo_map),
        "github_token_repo_map_entries": len(repo_map),
        "database_ready": db_err is None,
        "database_error": db_err,
        "commit_count": commit_count,
        "aws_default_region": ar or None,
        "github_commit_style_fetch": settings.github_commit_style_fetch_enabled,
        "github_commit_style_max_per_sync": settings.github_commit_style_max_per_sync,
        "repo_mirror_root": str(settings.repo_mirror_root_path),
        "background_sync": {
            "enabled": settings.background_sync_enabled,
            "interval_hours": settings.background_sync_interval_hours,
            "since_days": settings.default_since_days,
            "initial_delay_seconds": settings.background_sync_initial_delay_seconds,
            "last_run_at": lat.isoformat() if isinstance(lat, datetime) else None,
            "last_ok": getattr(request.app.state, "last_background_sync_ok", None),
            "last_detail": getattr(request.app.state, "last_background_sync_detail", None),
        },
    }


@app.get("/api/codecommit/repos", response_model=CodeCommitRepoListResponse)
def api_list_codecommit_repos(
    region: str | None = Query(None, description="AWS 区域，默认使用 .env 的 AWS_DEFAULT_REGION"),
):
    """列出当前凭证在该区域可见的 CodeCommit 仓库，返回可导入的 cc: 标识。"""
    r = (region or settings.aws_default_region or "").strip()
    if not r:
        raise HTTPException(
            status_code=400,
            detail="请传查询参数 region= 或在 backend/.env 设置 AWS_DEFAULT_REGION",
        )
    try:
        rows = list_codecommit_repository_catalog(r)
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    keys = [x["sync_key"] for x in rows]
    items = [CodeCommitRepositoryItem(**x) for x in rows]
    return CodeCommitRepoListResponse(
        region=r.lower(),
        count=len(keys),
        sync_keys=keys,
        repositories=items,
    )


@app.get("/api/repo-mirrors", response_model=RepoMirrorCenterResponse)
def repo_mirrors_center(
    team: str | None = Query(None, description="团队标识（web3 / game）"),
    db: Session = Depends(get_db),
):
    """仓库中心：合并列表中各仓库的本地镜像状态（需先执行扫描/拉取）。"""
    raw = build_center_payload(db, team=team)
    return RepoMirrorCenterResponse(
        mirror_root=raw["mirror_root"],
        git_available=raw["git_available"],
        aws_cli_available=raw["aws_cli_available"],
        scan_in_progress=raw["scan_in_progress"],
        items=[RepoMirrorItemOut(**x) for x in raw["items"]],
    )


@app.post("/api/repo-mirrors/scan", response_model=RepoMirrorScanStarted)
def repo_mirrors_scan(
    body: RepoMirrorScanRequest,
    background_tasks: BackgroundTasks,
):
    """后台依次 git clone / fetch；进行中时返回 409。"""
    if not try_begin_scan():
        raise HTTPException(status_code=409, detail="已有本地拉取任务在执行，请稍后再试")
    repos = body.repos if body.repos else None
    background_tasks.add_task(_mirror_scan_background, repos)
    return RepoMirrorScanStarted()


@app.get("/api/config/repos")
def list_configured_repos(
    team: str | None = Query(None, description="团队标识（web3 / game）"),
    db: Session = Depends(get_db),
):
    """合并：数据库中已启用仓库 + .env / REPOS_FILE（去重）。"""
    merged = merged_sync_repos(db, team=team)
    path = settings.repos_file_path
    return {
        "count": len(merged),
        "repos": merged,
        "database_enabled_count": len(repos_from_database(db, team=team)),
        "config_count": len(settings.repo_list),
        "repos_file": str(path) if path else None,
        "repos_file_exists": path.is_file() if path else False,
    }


@app.get("/api/repos", response_model=list[TrackedRepoOut])
def list_tracked_repos(
    team: str | None = Query(None, description="团队标识（web3 / game）"),
    db: Session = Depends(get_db),
):
    q = select(TrackedRepository).order_by(TrackedRepository.id)
    if team:
        q = q.where(TrackedRepository.team == team)
    return list(db.execute(q).scalars().all())


@app.post("/api/repos", response_model=TrackedRepoOut)
def add_tracked_repo(body: TrackedRepoCreate, db: Session = Depends(get_db)):
    try:
        fn = normalize_repo_full_name(body.full_name)
    except ValueError as e:
        raise HTTPException(400, detail=str(e)) from e
    dup = db.execute(select(TrackedRepository).where(TrackedRepository.full_name == fn)).scalars().first()
    if dup:
        raise HTTPException(409, detail="该仓库已在数据库列表中")
    r = TrackedRepository(full_name=fn, notes=(body.notes or "").strip(), team=body.team, enabled=True)
    db.add(r)
    db.commit()
    db.refresh(r)
    return r


@app.post("/api/repos/bulk", response_model=RepoBulkResult)
def bulk_add_tracked_repos(body: RepoBulkCreate, db: Session = Depends(get_db)):
    added: list[str] = []
    skipped: list[str] = []
    errors: list[str] = []
    existing = {
        row.full_name.lower()
        for row in db.execute(select(TrackedRepository)).scalars().all()
    }
    seen_req: set[str] = set()
    for raw in body.full_names:
        s = raw.strip()
        if not s or s.startswith("#"):
            continue
        try:
            fn = normalize_repo_full_name(s)
        except ValueError as e:
            errors.append(f"{s}: {e}")
            continue
        if fn in seen_req:
            continue
        seen_req.add(fn)
        if fn.lower() in existing:
            skipped.append(fn)
            continue
        db.add(TrackedRepository(full_name=fn, notes="", team=body.team, enabled=True))
        existing.add(fn.lower())
        added.append(fn)
    db.commit()
    return RepoBulkResult(added=added, skipped=skipped, errors=errors)


@app.patch("/api/repos/{repo_id}", response_model=TrackedRepoOut)
def patch_tracked_repo(
    repo_id: int,
    body: TrackedRepoPatch,
    db: Session = Depends(get_db),
):
    r = db.get(TrackedRepository, repo_id)
    if not r:
        raise HTTPException(404, detail="记录不存在")
    if body.enabled is not None:
        r.enabled = body.enabled
    if body.notes is not None:
        r.notes = body.notes.strip()
    if body.team is not None:
        r.team = body.team
    db.commit()
    db.refresh(r)
    return r


@app.delete("/api/repos/{repo_id}")
def delete_tracked_repo(repo_id: int, db: Session = Depends(get_db)):
    r = db.get(TrackedRepository, repo_id)
    if not r:
        raise HTTPException(404, detail="记录不存在")
    db.delete(r)
    db.commit()
    return {"ok": True}


def _sync_log_repo_count(repos_blob: str) -> int:
    try:
        data = json.loads(repos_blob)
        if isinstance(data, list):
            return len(data)
    except (json.JSONDecodeError, TypeError):
        pass
    return 0


@app.get("/api/sync/logs", response_model=list[SyncLogItem])
def list_sync_logs(
    limit: int = Query(30, ge=1, le=100, description="返回最近若干条"),
    db: Session = Depends(get_db),
):
    """所有人可读：最近同步批次摘要（实时进度仍仅发起者 SSE 可见）。"""
    rows = (
        db.execute(select(SyncLog).order_by(SyncLog.id.desc()).limit(limit))
        .scalars()
        .all()
    )
    out: list[SyncLogItem] = []
    for r in rows:
        raw_err = (r.error or "").strip()
        prev = None
        if raw_err:
            prev = raw_err[:400] + ("…" if len(raw_err) > 400 else "")
        out.append(
            SyncLogItem(
                id=r.id,
                started_at=r.started_at,
                finished_at=r.finished_at,
                status=r.status,
                commits_fetched=r.commits_fetched,
                repo_count=_sync_log_repo_count(r.repos),
                error_preview=prev,
            )
        )
    return out


@app.post("/api/sync", response_model=SyncResponse)
async def sync_commits(body: SyncRequest, db: Session = Depends(get_db)):
    raw = [r.strip() for r in body.repos if r.strip()]
    if raw:
        repos = []
        for r in raw:
            try:
                repos.append(normalize_repo_full_name(r))
            except ValueError as e:
                raise HTTPException(400, detail=f"仓库格式无效「{r}」: {e}") from e
    else:
        repos = merged_sync_repos(db, team=body.team)
    sync_id, n, err, contrib_n, warn = await run_sync(db, repos, body.since_days)
    return SyncResponse(
        sync_id=sync_id,
        commits_fetched=n,
        contributors_created=contrib_n,
        status="error" if err else ("partial" if warn else "ok"),
        message=err or warn,
    )


@app.post("/api/sync/stream")
async def sync_commits_stream(body: SyncRequest):
    """与 POST /api/sync 相同逻辑，以 SSE（text/event-stream）推送进度，供前端展示。"""

    async def events():
        db = SessionLocal()
        queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()

        async def push(ev: dict[str, Any]) -> None:
            await queue.put(ev)

        async def worker() -> None:
            try:
                raw = [r.strip() for r in body.repos if r.strip()]
                if raw:
                    repos: list[str] = []
                    for r in raw:
                        try:
                            repos.append(normalize_repo_full_name(r))
                        except ValueError as e:
                            await push(
                                {
                                    "phase": "complete",
                                    "ok": False,
                                    "sync_id": 0,
                                    "commits_fetched": 0,
                                    "contributors_created": 0,
                                    "message": f"仓库格式无效「{r}」: {e}",
                                }
                            )
                            return
                else:
                    repos = merged_sync_repos(db, team=body.team)
                await run_sync(db, repos, body.since_days, on_progress=push)
            except Exception as e:  # noqa: BLE001
                await push(
                    {
                        "phase": "complete",
                        "ok": False,
                        "sync_id": 0,
                        "commits_fetched": 0,
                        "contributors_created": 0,
                        "message": f"{type(e).__name__}: {e}",
                    }
                )
            finally:
                await queue.put(None)

        task = asyncio.create_task(worker())
        try:
            while True:
                item = await queue.get()
                if item is None:
                    break
                yield f"data: {json.dumps(item, default=str)}\n\n"
        finally:
            await task
            db.close()

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


def _parse_date(s: str) -> date:
    try:
        return date.fromisoformat(s)
    except ValueError as e:
        raise HTTPException(400, f"无效日期: {s}") from e


@app.get("/api/reports/daily")
def report_daily(
    d: str = Query(..., alias="date", description="YYYY-MM-DD，UTC 日界"),
    team: str | None = Query(None, description="团队标识（web3 / game）"),
    db: Session = Depends(get_db),
):
    return build_daily_report(db, _parse_date(d), team=team)


@app.get("/api/reports/daily.md", response_class=PlainTextResponse)
def report_daily_md(
    d: str = Query(..., alias="date"),
    team: str | None = Query(None),
    db: Session = Depends(get_db),
):
    return markdown_daily(build_daily_report(db, _parse_date(d), team=team))


@app.get("/api/reports/weekly")
def report_weekly(
    week_start: str = Query(..., description="周起始日 YYYY-MM-DD（周一，UTC）"),
    team: str | None = Query(None, description="团队标识（web3 / game）"),
    db: Session = Depends(get_db),
):
    return build_weekly_report(db, _parse_date(week_start), team=team)


@app.get("/api/reports/weekly.md", response_class=PlainTextResponse)
def report_weekly_md(
    week_start: str = Query(...),
    team: str | None = Query(None),
    db: Session = Depends(get_db),
):
    return markdown_weekly(build_weekly_report(db, _parse_date(week_start), team=team))


def _check_alias_conflicts(
    db: Session,
    emails: list[str],
    logins: list[str],
    *,
    exclude_contributor_id: int | None = None,
) -> None:
    for e in emails:
        vn = normalize_email(e)
        if not vn:
            continue
        row = db.execute(
            select(ContributorAlias).where(
                ContributorAlias.kind == "email",
                ContributorAlias.value_normalized == vn,
            )
        ).scalar_one_or_none()
        if row and (exclude_contributor_id is None or row.contributor_id != exclude_contributor_id):
            raise HTTPException(409, detail=f"邮箱已被其他成员占用: {vn}")
    for raw in logins:
        ln = raw.strip().lower()
        if not ln:
            continue
        row = db.execute(
            select(ContributorAlias).where(
                ContributorAlias.kind == "login",
                ContributorAlias.value_normalized == ln,
            )
        ).scalar_one_or_none()
        if row and (exclude_contributor_id is None or row.contributor_id != exclude_contributor_id):
            raise HTTPException(409, detail=f"GitHub 登录已被其他成员占用: {ln}")


def _contributor_to_out(c: Contributor) -> ContributorOut:
    return ContributorOut(
        id=c.id,
        nickname=c.nickname,
        notes=c.notes or "",
        aliases=[
            ContributorAliasOut(id=a.id, kind=a.kind, value_normalized=a.value_normalized)
            for a in sorted(c.aliases, key=lambda x: (x.kind, x.value_normalized))
        ],
    )


@app.get("/api/contributors", response_model=list[ContributorOut])
def list_contributors(
    team: str | None = Query(None, description="团队标识（web3 / game）"),
    db: Session = Depends(get_db),
):
    q = select(Contributor).order_by(Contributor.id)
    if team:
        q = q.where(Contributor.team == team)
    rows = db.execute(q).scalars().all()
    return [_contributor_to_out(c) for c in rows]


@app.post("/api/contributors", response_model=ContributorOut)
def create_contributor(body: ContributorCreate, db: Session = Depends(get_db)):
    _check_alias_conflicts(db, body.emails, body.github_logins)
    c = Contributor(nickname=body.nickname.strip(), notes=(body.notes or "").strip(), team=body.team)
    db.add(c)
    db.flush()
    for e in body.emails:
        vn = normalize_email(e)
        if vn:
            db.add(ContributorAlias(contributor_id=c.id, kind="email", value_normalized=vn))
    for raw in body.github_logins:
        ln = raw.strip().lower()
        if ln:
            db.add(ContributorAlias(contributor_id=c.id, kind="login", value_normalized=ln))
    db.commit()
    db.refresh(c)
    return _contributor_to_out(c)


@app.put("/api/contributors/{contributor_id}", response_model=ContributorOut)
def put_contributor(
    contributor_id: int,
    body: ContributorCreate,
    db: Session = Depends(get_db),
):
    c = db.get(Contributor, contributor_id)
    if not c:
        raise HTTPException(404, detail="成员不存在")
    _check_alias_conflicts(db, body.emails, body.github_logins, exclude_contributor_id=contributor_id)
    c.nickname = body.nickname.strip()
    c.notes = (body.notes or "").strip()
    db.execute(delete(ContributorAlias).where(ContributorAlias.contributor_id == contributor_id))
    for e in body.emails:
        vn = normalize_email(e)
        if vn:
            db.add(ContributorAlias(contributor_id=c.id, kind="email", value_normalized=vn))
    for raw in body.github_logins:
        ln = raw.strip().lower()
        if ln:
            db.add(ContributorAlias(contributor_id=c.id, kind="login", value_normalized=ln))
    db.commit()
    db.refresh(c)
    return _contributor_to_out(c)


@app.delete("/api/contributors/{contributor_id}")
def delete_contributor(contributor_id: int, db: Session = Depends(get_db)):
    c = db.get(Contributor, contributor_id)
    if not c:
        raise HTTPException(404, detail="成员不存在")
    db.delete(c)
    db.commit()
    return {"ok": True}


@app.get("/api/employees")
def list_employees(
    team: str | None = Query(None, description="团队标识（web3 / game）"),
    db: Session = Depends(get_db),
):
    logins_cfg = settings.member_logins
    employee_keys = suggested_employee_keys(db, team=team)
    employee_key_options = suggested_employee_key_options(db, team=team)
    if logins_cfg:
        return {
            "source": "config",
            "logins": sorted({m.strip().lower() for m in logins_cfg}),
            "employee_keys": employee_keys,
            "employee_key_options": employee_key_options,
        }
    return {
        "source": "commits",
        "logins": [],
        "employee_keys": employee_keys,
        "employee_key_options": employee_key_options,
    }


@app.get("/api/employees/{login}/commits", response_model=list[CommitItem])
def employee_commits(
    login: str,
    from_: str | None = Query(None, alias="from"),
    to: str | None = Query(None, alias="to"),
    team: str | None = Query(None, description="团队标识（web3 / game）"),
    db: Session = Depends(get_db),
):
    cond = commit_filter_for_employee_key(login, db)
    q = select(CommitRecord).where(cond)
    if team:
        team_repos_sq = select(TrackedRepository.full_name).where(
            TrackedRepository.team == team, TrackedRepository.enabled.is_(True)
        )
        q = q.where(CommitRecord.repo_full_name.in_(team_repos_sq))
    if from_:
        start = datetime.combine(_parse_date(from_), time.min, tzinfo=timezone.utc)
        q = q.where(CommitRecord.committed_at >= start)
    if to:
        end = datetime.combine(_parse_date(to), time.max, tzinfo=timezone.utc)
        q = q.where(CommitRecord.committed_at <= end)
    q = q.order_by(CommitRecord.committed_at.desc()).limit(500)
    rows = db.execute(q).scalars().all()
    return [
        CommitItem(
            sha=r.sha,
            repo_full_name=r.repo_full_name,
            author_login=r.author_login,
            author_email=r.author_email,
            committed_at=r.committed_at,
            message=r.message[:500] + ("…" if len(r.message) > 500 else ""),
            html_url=r.html_url,
        )
        for r in rows
    ]


@app.get("/api/employees/{login}/habits", response_model=HabitsSummary)
def employee_habits(
    login: str,
    from_: str | None = Query(None, alias="from"),
    to: str | None = Query(None, alias="to"),
    team: str | None = Query(None, description="团队标识（web3 / game）"),
    db: Session = Depends(get_db),
):
    cond = commit_filter_for_employee_key(login, db)
    q = select(CommitRecord).where(cond)
    if team:
        team_repos_sq = select(TrackedRepository.full_name).where(
            TrackedRepository.team == team, TrackedRepository.enabled.is_(True)
        )
        q = q.where(CommitRecord.repo_full_name.in_(team_repos_sq))
    if from_:
        start = datetime.combine(_parse_date(from_), time.min, tzinfo=timezone.utc)
        q = q.where(CommitRecord.committed_at >= start)
    if to:
        end = datetime.combine(_parse_date(to), time.max, tzinfo=timezone.utc)
        q = q.where(CommitRecord.committed_at <= end)
    rows = list(db.execute(q).scalars().all())
    return compute_habits(rows)


@app.get("/api/employees/{login}/habit-changes", response_model=HabitChangeReport)
def employee_habit_changes(
    login: str,
    p1_from: str = Query(..., alias="p1_from"),
    p1_to: str = Query(..., alias="p1_to"),
    p2_from: str = Query(..., alias="p2_from"),
    p2_to: str = Query(..., alias="p2_to"),
    team: str | None = Query(None),
    db: Session = Depends(get_db),
):
    return analyze_habit_changes(
        db,
        login,
        _parse_date(p1_from),
        _parse_date(p1_to),
        _parse_date(p2_from),
        _parse_date(p2_to),
        team=team,
    )


# 存在 frontend/dist 时，由本进程一并提供静态页（只跑后端即可用 http://127.0.0.1:3020/ 打开界面）
_frontend_dist = Path(__file__).resolve().parents[2] / "frontend" / "dist"
if _frontend_dist.is_dir():
    from fastapi.staticfiles import StaticFiles

    app.mount(
        "/",
        StaticFiles(directory=str(_frontend_dist), html=True),
        name="frontend",
    )
