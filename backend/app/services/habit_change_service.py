"""习惯变化检测：对比两个时间段的提交习惯，给出结构化分析与结论。"""
from __future__ import annotations

import math
from datetime import date, datetime, time, timedelta, timezone
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import CommitRecord, TrackedRepository
from app.schemas import HabitChangeItem, HabitChangeReport, HabitsSummary
from app.services.identity_service import commit_filter_for_employee_key
from app.services.report_service import compute_habits

if TYPE_CHECKING:
    pass

# ── 时段划分 ──────────────────────────────────────────────
_TIME_BLOCKS = [
    (0, 6, "深夜(0-6点)"),
    (6, 12, "上午(6-12点)"),
    (12, 18, "下午(12-18点)"),
    (18, 24, "晚上(18-24点)"),
]

WEEKDAY_CN = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]


def _peak_block(by_hour: dict[str, int]) -> str:
    block_totals = []
    for start, end, label in _TIME_BLOCKS:
        total = sum(by_hour.get(str(h), 0) for h in range(start, end))
        block_totals.append((total, label))
    return max(block_totals, key=lambda x: x[0])[1]


def _weekday_ratio(by_weekday: dict[str, int]) -> float:
    """工作日提交占比（周一~周五 / 总数），0~1。"""
    total = sum(by_weekday.values())
    if total == 0:
        return 0.0
    workday = sum(by_weekday.get(d, 0) for d in WEEKDAY_CN[:5])
    return workday / total


def _entropy(dist: dict[str, int]) -> float:
    """Shannon 熵，衡量分布均匀程度（越高越分散，越低越集中）。"""
    total = sum(dist.values())
    if total == 0:
        return 0.0
    ent = 0.0
    for v in dist.values():
        if v > 0:
            p = v / total
            ent -= p * math.log2(p)
    return round(ent, 2)


def _top_language(mix: dict[str, int]) -> str | None:
    if not mix:
        return None
    return max(mix.items(), key=lambda x: x[1])[0]


def _pct_change_desc(before: float, after: float, unit: str = "%") -> str:
    diff = after - before
    sign = "+" if diff >= 0 else ""
    return f"{before:.1f}{unit} → {after:.1f}{unit}（{sign}{diff:.1f}{unit}）"


# ── 单项分析 ──────────────────────────────────────────────

def _analyze_volume(c1: int, c2: int) -> HabitChangeItem:
    if c1 == 0:
        trend = "up" if c2 > 0 else "stable"
        conclusion = f"前期无提交记录，后期有 {c2} 次提交。" if c2 > 0 else "两个时段均无提交。"
    else:
        ratio = (c2 - c1) / c1 * 100
        if ratio > 20:
            trend = "up"
            conclusion = f"提交量显著增加（{c1} → {c2} 次，+{ratio:.0f}%），活跃度明显提升。"
        elif ratio < -20:
            trend = "down"
            conclusion = f"提交量明显减少（{c1} → {c2} 次，{ratio:.0f}%），需关注是否有阻塞因素。"
        else:
            trend = "stable"
            conclusion = f"提交量基本稳定（{c1} → {c2} 次，{ratio:+.0f}%）。"
    return HabitChangeItem(
        dimension="提交量",
        before_desc=f"{c1} 次提交",
        after_desc=f"{c2} 次提交",
        trend=trend,
        conclusion=conclusion,
        significant=trend != "stable",
    )


def _analyze_peak_time(h1: HabitsSummary, h2: HabitsSummary) -> HabitChangeItem:
    block1 = _peak_block(h1.commits_by_hour_utc)
    block2 = _peak_block(h2.commits_by_hour_utc)
    peak1 = f"UTC {h1.most_active_hour_utc} 点" if h1.most_active_hour_utc is not None else "无"
    peak2 = f"UTC {h2.most_active_hour_utc} 点" if h2.most_active_hour_utc is not None else "无"
    if block1 == block2:
        trend = "stable"
        conclusion = f"主要活跃时段稳定在{block1}（{peak1} → {peak2}）。"
        significant = False
    else:
        trend = "shift"
        conclusion = f"活跃时段从{block1}（{peak1}）迁移到{block2}（{peak2}），工作节律发生变化，需确认是否为刻意调整或环境变化。"
        significant = True
    return HabitChangeItem(
        dimension="活跃时段",
        before_desc=f"{block1}（峰值 {peak1}）",
        after_desc=f"{block2}（峰值 {peak2}）",
        trend=trend,
        conclusion=conclusion,
        significant=significant,
    )


def _analyze_weekday(h1: HabitsSummary, h2: HabitsSummary) -> HabitChangeItem:
    r1 = _weekday_ratio(h1.commits_by_weekday) * 100
    r2 = _weekday_ratio(h2.commits_by_weekday) * 100
    diff = r2 - r1
    if abs(diff) < 8:
        trend = "stable"
        conclusion = f"工作日提交占比稳定（{r1:.0f}% → {r2:.0f}%）。"
        significant = False
    elif diff > 0:
        trend = "up"
        conclusion = f"工作日提交比例提升（{r1:.0f}% → {r2:.0f}%），节假日/周末提交减少，工作边界更清晰。"
        significant = True
    else:
        trend = "down"
        conclusion = f"工作日提交比例下降（{r1:.0f}% → {r2:.0f}%），周末提交增多，可能存在加班或个人项目活跃。"
        significant = True
    return HabitChangeItem(
        dimension="工作日节奏",
        before_desc=f"工作日占比 {r1:.0f}%",
        after_desc=f"工作日占比 {r2:.0f}%",
        trend=trend,
        conclusion=conclusion,
        significant=significant,
    )


def _analyze_commit_regularity(h1: HabitsSummary, h2: HabitsSummary) -> HabitChangeItem:
    e1 = _entropy(h1.commits_by_hour_utc)
    e2 = _entropy(h2.commits_by_hour_utc)
    diff = e2 - e1
    if abs(diff) < 0.5:
        trend = "stable"
        conclusion = "提交时间分布规律性基本一致。"
        significant = False
    elif diff > 0:
        trend = "shift"
        conclusion = f"提交时间分散程度增加（熵 {e1} → {e2}），各时段提交更均匀，节奏可能趋于灵活或不规律。"
        significant = True
    else:
        trend = "shift"
        conclusion = f"提交时间更加集中（熵 {e1} → {e2}），工作节律趋于稳定或专注时段更固定。"
        significant = True
    return HabitChangeItem(
        dimension="提交规律性",
        before_desc=f"时间熵 {e1}（{'集中' if e1 < 3 else '分散'}）",
        after_desc=f"时间熵 {e2}（{'集中' if e2 < 3 else '分散'}）",
        trend=trend,
        conclusion=conclusion,
        significant=significant,
    )


def _analyze_conventional(h1: HabitsSummary, h2: HabitsSummary) -> HabitChangeItem:
    p1 = h1.pct_conventional_commits
    p2 = h2.pct_conventional_commits
    diff = p2 - p1
    if abs(diff) < 10:
        trend = "stable"
        conclusion = f"Conventional Commits 规范遵循率稳定（{p1:.0f}% → {p2:.0f}%）。"
        significant = False
    elif diff > 0:
        trend = "up"
        conclusion = f"提交说明规范性提升（{p1:.0f}% → {p2:.0f}%），Conventional Commits 使用更频繁，利于变更追踪。"
        significant = True
    else:
        trend = "down"
        conclusion = f"提交说明规范性下降（{p1:.0f}% → {p2:.0f}%），建议关注提交说明的格式规范。"
        significant = True
    return HabitChangeItem(
        dimension="提交规范性",
        before_desc=f"Conventional Commits {p1:.0f}%",
        after_desc=f"Conventional Commits {p2:.0f}%",
        trend=trend,
        conclusion=conclusion,
        significant=significant,
    )


def _analyze_issue_ref(h1: HabitsSummary, h2: HabitsSummary) -> HabitChangeItem:
    p1 = h1.pct_messages_with_issue_ref
    p2 = h2.pct_messages_with_issue_ref
    diff = p2 - p1
    if abs(diff) < 10:
        trend = "stable"
        conclusion = f"Issue 引用率稳定（{p1:.0f}% → {p2:.0f}%）。"
        significant = False
    elif diff > 0:
        trend = "up"
        conclusion = f"Issue 引用率提升（{p1:.0f}% → {p2:.0f}%），提交与任务追踪关联性更好。"
        significant = True
    else:
        trend = "down"
        conclusion = f"Issue 引用率下降（{p1:.0f}% → {p2:.0f}%），提交说明与工单关联减少。"
        significant = significant if False else True
    return HabitChangeItem(
        dimension="Issue 引用率",
        before_desc=f"{p1:.0f}% 含 # 引用",
        after_desc=f"{p2:.0f}% 含 # 引用",
        trend=trend,
        conclusion=conclusion,
        significant=significant,
    )


def _analyze_language(h1: HabitsSummary, h2: HabitsSummary) -> HabitChangeItem | None:
    if not h1.style_language_mix and not h2.style_language_mix:
        return None
    lang1 = _top_language(h1.style_language_mix)
    lang2 = _top_language(h2.style_language_mix)
    desc1 = lang1 or "无画像数据"
    desc2 = lang2 or "无画像数据"
    if lang1 == lang2:
        trend = "stable"
        conclusion = f"主要编程语言稳定（{desc1}）。"
        significant = False
    else:
        trend = "shift"
        conclusion = f"主要文件类型从 {desc1} 转向 {desc2}，技术栈侧重点发生变化。"
        significant = True
    return HabitChangeItem(
        dimension="主要语言/文件类型",
        before_desc=desc1,
        after_desc=desc2,
        trend=trend,
        conclusion=conclusion,
        significant=significant,
    )


def _analyze_style_tags(h1: HabitsSummary, h2: HabitsSummary) -> HabitChangeItem | None:
    tags1 = set(h1.style_tags or [])
    tags2 = set(h2.style_tags or [])
    if not tags1 and not tags2:
        return None
    appeared = tags2 - tags1
    disappeared = tags1 - tags2
    if not appeared and not disappeared:
        trend = "stable"
        conclusion = "代码改动风格标签无变化。"
        significant = False
    else:
        trend = "shift"
        parts = []
        if appeared:
            parts.append(f"新增：{', '.join(sorted(appeared))}")
        if disappeared:
            parts.append(f"消失：{', '.join(sorted(disappeared))}")
        conclusion = f"代码风格发生变化（{'; '.join(parts)}），可能涉及新领域或重构方向改变。"
        significant = True
    return HabitChangeItem(
        dimension="代码风格标签",
        before_desc=", ".join(sorted(tags1)) or "无",
        after_desc=", ".join(sorted(tags2)) or "无",
        trend=trend,
        conclusion=conclusion,
        significant=significant,
    )


# ── 主入口 ────────────────────────────────────────────────

def _fetch_habits(
    db: Session,
    login: str,
    from_: date,
    to: date,
    team: str | None,
) -> HabitsSummary:
    cond = commit_filter_for_employee_key(login, db)
    start = datetime.combine(from_, time.min, tzinfo=timezone.utc)
    end = datetime.combine(to, time.max, tzinfo=timezone.utc)
    q = select(CommitRecord).where(cond, CommitRecord.committed_at >= start, CommitRecord.committed_at <= end)
    if team:
        team_repos_sq = select(TrackedRepository.full_name).where(
            TrackedRepository.team == team, TrackedRepository.enabled.is_(True)
        )
        q = q.where(CommitRecord.repo_full_name.in_(team_repos_sq))
    rows = list(db.execute(q).scalars().all())
    return compute_habits(rows)


def analyze_habit_changes(
    db: Session,
    login: str,
    period1_from: date,
    period1_to: date,
    period2_from: date,
    period2_to: date,
    team: str | None = None,
) -> HabitChangeReport:
    h1 = _fetch_habits(db, login, period1_from, period1_to, team)
    h2 = _fetch_habits(db, login, period2_from, period2_to, team)

    changes: list[HabitChangeItem] = []
    changes.append(_analyze_volume(h1.total_commits, h2.total_commits))

    if h1.total_commits > 0 or h2.total_commits > 0:
        changes.append(_analyze_peak_time(h1, h2))
        changes.append(_analyze_weekday(h1, h2))
        changes.append(_analyze_commit_regularity(h1, h2))
        changes.append(_analyze_conventional(h1, h2))
        changes.append(_analyze_issue_ref(h1, h2))
        lang_item = _analyze_language(h1, h2)
        if lang_item:
            changes.append(lang_item)
        style_item = _analyze_style_tags(h1, h2)
        if style_item:
            changes.append(style_item)

    significant_changes = [c for c in changes if c.significant]
    if h1.total_commits == 0 and h2.total_commits == 0:
        summary = "两个时段均无提交记录，无法进行有效对比。"
    elif not significant_changes:
        summary = "两个时段的提交习惯整体稳定，未发现显著变化。"
    else:
        dims = "、".join(c.dimension for c in significant_changes)
        summary = f"共检测到 {len(significant_changes)} 项显著变化（{dims}），建议重点关注上述项目。"

    return HabitChangeReport(
        period1_from=period1_from,
        period1_to=period1_to,
        period2_from=period2_from,
        period2_to=period2_to,
        period1_commits=h1.total_commits,
        period2_commits=h2.total_commits,
        changes=changes,
        summary=summary,
    )
