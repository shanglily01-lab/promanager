from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import CommitRecord, Contributor
from app.schemas import CommitItem, DailyReport, EmployeeSummary, HabitsSummary, WeeklyReport
from app.services.commit_style_analyzer import (
    conventional_commit_pct,
    rollup_commit_message_tags,
    rollup_style_from_commits,
)
from app.services.identity_service import (
    configured_member_key,
    load_alias_maps,
    normalize_email,
    resolve_employee_key,
    sort_employee_keys,
)

WEEKDAY_CN = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]


def _day_range_utc(d: date) -> tuple[datetime, datetime]:
    start = datetime.combine(d, time.min, tzinfo=timezone.utc)
    end = start + timedelta(days=1)
    return start, end


def _week_range_utc(week_start: date) -> tuple[datetime, datetime]:
    start = datetime.combine(week_start, time.min, tzinfo=timezone.utc)
    end = start + timedelta(days=7)
    return start, end


def _commits_to_items(rows: Iterable[CommitRecord]) -> list[CommitItem]:
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


def _contributor_for_key(db: Session, key: str) -> Contributor | None:
    if not key.startswith("contrib:"):
        return None
    cid = int(key.split(":", 1)[1])
    return db.get(Contributor, cid)


def _display_for_key(key: str, contrib: Contributor | None, commits: list[CommitRecord]) -> str | None:
    if contrib:
        return contrib.nickname
    if key == "_unknown":
        return "未绑定 GitHub / 邮箱的提交"
    if key.startswith("email:"):
        return key[6:]
    for c in commits:
        if c.author_name and c.author_name.strip():
            return c.author_name.strip()
    return key


def _collect_keys_for_period(
    db: Session,
    rows: list[CommitRecord],
    maps,
) -> list[str]:
    keys: set[str] = set()
    for r in rows:
        k, _ = resolve_employee_key(r, maps)
        keys.add(k)
    for m in settings.member_logins:
        keys.add(configured_member_key(m, maps))
    return sort_employee_keys(keys)


def _build_employees(
    db: Session,
    sorted_keys: list[str],
    by_key: dict[str, list[CommitRecord]],
) -> list[EmployeeSummary]:
    employees: list[EmployeeSummary] = []
    for key in sorted_keys:
        cs = by_key.get(key, [])
        contrib = _contributor_for_key(db, key)
        repos = sorted({c.repo_full_name for c in cs})
        emails = sorted({e for e in (normalize_email(c.author_email) for c in cs) if e})
        gh = None
        for c in cs:
            if c.author_login:
                gh = c.author_login
                break
        employees.append(
            EmployeeSummary(
                login=key,
                display_name=_display_for_key(key, contrib, cs),
                notes=(contrib.notes.strip() or None) if contrib and contrib.notes else None,
                matched_emails=emails,
                github_login=gh,
                total_commits_in_range=len(cs),
                had_submission=len(cs) > 0,
                repos_touched=repos,
            )
        )
    return employees


def compute_habits(commits: list[CommitRecord]) -> HabitsSummary:
    if not commits:
        return HabitsSummary(
            total_commits=0,
            commits_by_hour_utc={str(h): 0 for h in range(24)},
            commits_by_weekday={WEEKDAY_CN[i]: 0 for i in range(7)},
            avg_message_length=0.0,
            pct_messages_with_issue_ref=0.0,
            most_active_hour_utc=None,
            most_active_weekday=None,
            style_tags=[],
            style_language_mix={},
            commits_with_style_sample=0,
            pct_conventional_commits=0.0,
            commit_message_tags=[],
        )

    by_hour: dict[str, int] = {str(h): 0 for h in range(24)}
    by_wd: dict[str, int] = {WEEKDAY_CN[i]: 0 for i in range(7)}
    lengths: list[int] = []
    with_issue = 0

    for c in commits:
        dt = c.committed_at.astimezone(timezone.utc)
        by_hour[str(dt.hour)] += 1
        by_wd[WEEKDAY_CN[dt.weekday()]] += 1
        lengths.append(len(c.message or ""))
        if "#" in (c.message or ""):
            with_issue += 1

    mh = max(range(24), key=lambda h: by_hour[str(h)])
    if by_hour[str(mh)] == 0:
        mh = None  # type: ignore[assignment]
    mw_idx = max(range(7), key=lambda i: by_wd[WEEKDAY_CN[i]])
    if by_wd[WEEKDAY_CN[mw_idx]] == 0:
        mwd = None
    else:
        mwd = WEEKDAY_CN[mw_idx]

    msgs = [c.message or "" for c in commits]
    pct_conv = conventional_commit_pct(msgs)
    style_tags, style_mix, n_style = rollup_style_from_commits(commits)
    msg_tags = rollup_commit_message_tags(commits)

    return HabitsSummary(
        total_commits=len(commits),
        commits_by_hour_utc=by_hour,
        commits_by_weekday=by_wd,
        avg_message_length=round(sum(lengths) / len(lengths), 1),
        pct_messages_with_issue_ref=round(100.0 * with_issue / len(commits), 1),
        most_active_hour_utc=mh,
        most_active_weekday=mwd,
        style_tags=style_tags,
        style_language_mix=style_mix,
        commits_with_style_sample=n_style,
        pct_conventional_commits=pct_conv,
        commit_message_tags=msg_tags,
    )


def build_daily_report(db: Session, report_date: date) -> DailyReport:
    maps = load_alias_maps(db)
    start, end = _day_range_utc(report_date)
    rows = list(
        db.execute(
            select(CommitRecord).where(CommitRecord.committed_at >= start, CommitRecord.committed_at < end)
        ).scalars().all()
    )

    by_key: dict[str, list[CommitRecord]] = defaultdict(list)
    for r in rows:
        k, _ = resolve_employee_key(r, maps)
        by_key[k].append(r)

    sorted_keys = _collect_keys_for_period(db, rows, maps)
    employees = _build_employees(db, sorted_keys, by_key)
    items_map = {e.login: _commits_to_items(by_key.get(e.login, [])) for e in employees}

    return DailyReport(
        report_date=report_date,
        employees=employees,
        by_employee_commits=items_map,
    )


def build_weekly_report(db: Session, week_start: date) -> WeeklyReport:
    maps = load_alias_maps(db)
    start, end = _week_range_utc(week_start)
    rows = list(
        db.execute(
            select(CommitRecord).where(CommitRecord.committed_at >= start, CommitRecord.committed_at < end)
        ).scalars().all()
    )

    by_key: dict[str, list[CommitRecord]] = defaultdict(list)
    for r in rows:
        k, _ = resolve_employee_key(r, maps)
        by_key[k].append(r)

    sorted_keys = _collect_keys_for_period(db, rows, maps)
    employees = _build_employees(db, sorted_keys, by_key)

    habits: dict[str, HabitsSummary] = {}
    for e in employees:
        habits[e.login] = compute_habits(by_key.get(e.login, []))

    items_map = {e.login: _commits_to_items(by_key.get(e.login, [])) for e in employees}

    return WeeklyReport(
        week_start=week_start,
        week_end=week_start + timedelta(days=6),
        employees=employees,
        by_employee_commits=items_map,
        habits=habits,
    )


def markdown_daily(report: DailyReport) -> str:
    lines = [f"# 日报 {report.report_date.isoformat()}", ""]
    for e in report.employees:
        flag = "是" if e.had_submission else "否"
        title = e.display_name or e.login
        lines.append(f"## {title}（`{e.login}` · 本日是否有提交: **{flag}**，共 {e.total_commits_in_range} 次）")
        if e.notes:
            lines.append(f"- 备注: {e.notes}")
        if e.matched_emails:
            lines.append(f"- 涉及邮箱: {', '.join(e.matched_emails)}")
        if e.github_login:
            lines.append(f"- GitHub 登录: @{e.github_login}")
        if e.repos_touched:
            lines.append(f"- 涉及仓库: {', '.join(e.repos_touched)}")
        cs = report.by_employee_commits.get(e.login, [])
        for c in cs[:20]:
            lines.append(f"- `{c.repo_full_name}` [{c.sha[:7]}]({c.html_url or '#'}) {c.message.splitlines()[0][:120]}")
        if len(cs) > 20:
            lines.append(f"- … 另有 {len(cs) - 20} 条提交")
        lines.append("")
    return "\n".join(lines)


def markdown_weekly(report: WeeklyReport) -> str:
    lines = [
        f"# 周报 {report.week_start.isoformat()} ~ {report.week_end.isoformat()}",
        "",
    ]
    for e in report.employees:
        flag = "是" if e.had_submission else "否"
        title = e.display_name or e.login
        h = report.habits.get(e.login)
        lines.append(f"## {title}（`{e.login}`）")
        lines.append(f"- 周期内是否有提交: **{flag}**，提交次数: {e.total_commits_in_range}")
        if e.notes:
            lines.append(f"- 备注: {e.notes}")
        if e.matched_emails:
            lines.append(f"- 涉及邮箱: {', '.join(e.matched_emails)}")
        if e.github_login:
            lines.append(f"- GitHub: @{e.github_login}")
        if e.repos_touched:
            lines.append(f"- 仓库: {', '.join(e.repos_touched)}")
        if h and h.total_commits > 0:
            lines.append(
                f"- 习惯: 主要活跃时段(UTC) {h.most_active_hour_utc} 点, 最常提交日 {h.most_active_weekday}, "
                f"平均说明长度 {h.avg_message_length}, 含 # 引用 {h.pct_messages_with_issue_ref}%, "
                f"Conventional Commits 占比 {h.pct_conventional_commits}%"
            )
            if h.commit_message_tags:
                lines.append(f"- 提交说明标签: {'；'.join(h.commit_message_tags)}")
            if h.style_tags:
                lines.append(f"- 代码改动画像标签: {'；'.join(h.style_tags)}")
            if h.commits_with_style_sample > 0 and h.style_language_mix:
                top3 = sorted(h.style_language_mix.items(), key=lambda x: -x[1])[:3]
                mix_s = ", ".join(f"{ext}×{n}" for ext, n in top3)
                lines.append(f"- 文件扩展名加权(前项): {mix_s}（基于 {h.commits_with_style_sample} 条含画像的提交）")
        cs = report.by_employee_commits.get(e.login, [])
        for c in cs[:15]:
            lines.append(f"  - `{c.repo_full_name}` {c.committed_at.date()} {c.message.splitlines()[0][:100]}")
        if len(cs) > 15:
            lines.append(f"  - … 另有 {len(cs) - 15} 条")
        lines.append("")
    return "\n".join(lines)
