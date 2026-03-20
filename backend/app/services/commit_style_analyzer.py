"""从 GitHub 单条 commit API 的 files/stats/patch 抽取轻量「代码改动画像」，用于汇总个人标签。"""
from __future__ import annotations

import json
import re
import statistics
from collections import Counter, defaultdict
from pathlib import PurePosixPath
from typing import Any

from app.models import CommitRecord

# 路径片段：测试/规格相关（启发式，非语义分析）
_TESTISH = re.compile(
    r"(^|/)(__tests__|tests?|testing|spec|mocks?|fixtures?)(/|$)|"
    r"(\.|/)(test|spec)[_./]|_test\.py$|\.test\.|\.spec\.|\.pytest\.|/e2e/|/integration/",
    re.IGNORECASE,
)

_CONVENTIONAL = re.compile(
    r"^(feat|fix|docs|style|refactor|test|chore|perf|ci|build|revert)(\([^\)]+\))?!?:\s",
    re.IGNORECASE,
)

_EXT_LANG = {
    ".py": "Python",
    ".ts": "TypeScript",
    ".tsx": "TSX",
    ".js": "JavaScript",
    ".jsx": "JSX",
    ".vue": "Vue",
    ".go": "Go",
    ".rs": "Rust",
    ".java": "Java",
    ".kt": "Kotlin",
    ".swift": "Swift",
    ".rb": "Ruby",
    ".php": "PHP",
    ".cs": "C#",
    ".cpp": "C++",
    ".c": "C",
    ".h": "C/C++ 头文件",
    ".sql": "SQL",
    ".md": "Markdown",
    ".yml": "YAML",
    ".yaml": "YAML",
    ".json": "JSON",
    ".html": "HTML",
    ".css": "CSS",
    ".scss": "SCSS",
    ".less": "Less",
    ".sh": "Shell",
    ".ps1": "PowerShell",
}


def _file_suffix(path: str) -> str:
    p = (path or "").strip().replace("\\", "/")
    if not p or p.endswith("/"):
        return ""
    suf = PurePosixPath(p).suffix.lower()
    return suf if suf else ""


def testish_path(path: str) -> bool:
    return bool(_TESTISH.search(path.replace("\\", "/")))


def _indent_from_patches(patches: list[str], max_scan_lines: int = 500) -> str | None:
    """从 unified diff 的 + 行推断 tab / 2·4·8 空格（样本不足时返回 None。"""
    tab_n = sp2 = sp4 = sp8 = mixed = 0
    scanned = 0
    for blob in patches:
        for line in blob.splitlines():
            if scanned >= max_scan_lines:
                break
            if not line.startswith("+") or line.startswith("+++"):
                continue
            body = line[1:]
            if not body.strip():
                continue
            if body.startswith("\\"):  # \ No newline at end of file
                continue
            lead_len = len(body) - len(body.lstrip(" \t"))
            prefix = body[:lead_len]
            if "\t" in prefix:
                tab_n += 1
            elif prefix == "":
                pass
            elif prefix.strip() == "":
                n = len(prefix)
                if n >= 8 and n % 8 == 0:
                    sp8 += 1
                elif n >= 4 and n % 4 == 0:
                    sp4 += 1
                elif n >= 2 and n % 2 == 0:
                    sp2 += 1
                else:
                    mixed += 1
            scanned += 1
        if scanned >= max_scan_lines:
            break
    total = tab_n + sp2 + sp4 + sp8 + mixed
    if total < 8:
        return None
    if mixed > total * 0.2:
        return "mixed"
    if tab_n >= max(sp2, sp4, sp8) and tab_n >= total * 0.35:
        return "tabs"
    if sp4 >= sp8 and sp4 >= sp2 and sp4 >= total * 0.35:
        return "4_spaces"
    if sp2 >= sp4 and sp2 >= sp8 and sp2 >= total * 0.35:
        return "2_spaces"
    if sp8 >= total * 0.35:
        return "8_spaces"
    return "mixed"


def analyze_github_commit_detail(detail: dict[str, Any]) -> dict[str, Any] | None:
    """解析 GET /repos/{owner}/{repo}/commits/{sha} 的 JSON。"""
    if not isinstance(detail, dict):
        return None
    stats = detail.get("stats") if isinstance(detail.get("stats"), dict) else {}
    files = detail.get("files")
    if not isinstance(files, list):
        return None

    ext_counts: dict[str, int] = defaultdict(int)
    testish_files = 0
    patch_chunks: list[str] = []
    patch_budget = 0
    max_chars = 100_000

    for item in files:
        if not isinstance(item, dict):
            continue
        fn = str(item.get("filename") or "").strip()
        if not fn:
            continue
        ext = _file_suffix(fn)
        if ext:
            ext_counts[ext] += 1
        if testish_path(fn):
            testish_files += 1
        patch = item.get("patch")
        if isinstance(patch, str) and patch_budget < max_chars:
            take = patch[: max_chars - patch_budget]
            patch_chunks.append(take)
            patch_budget += len(take)

    additions = int(stats.get("additions") or 0)
    deletions = int(stats.get("deletions") or 0)
    indent = _indent_from_patches(patch_chunks)

    top_exts = dict(sorted(ext_counts.items(), key=lambda x: -x[1])[:16])
    return {
        "file_count": len(files),
        "additions": additions,
        "deletions": deletions,
        "ext_counts": top_exts,
        "testish_files": testish_files,
        "indent_hint": indent,
    }


def conventional_commit_pct(messages: list[str]) -> float:
    if not messages:
        return 0.0
    first_lines = [(m or "").strip().split("\n", 1)[0] for m in messages]
    n = sum(1 for line in first_lines if _CONVENTIONAL.match(line))
    return round(100.0 * n / len(messages), 1)


# 提取 Conventional 类型（与 _CONVENTIONAL 一致，用于分布统计）
_CONV_TYPE_HEAD = re.compile(
    r"^(feat|fix|docs|style|refactor|test|chore|perf|ci|build|revert)(\([^\)]+\))?!?:",
    re.IGNORECASE,
)

_TYPE_CN = {
    "feat": "新功能 feat",
    "fix": "修复 fix",
    "docs": "文档 docs",
    "style": "格式 style",
    "refactor": "重构 refactor",
    "test": "测试 test",
    "chore": "杂项 chore",
    "perf": "性能 perf",
    "ci": "CI",
    "build": "构建 build",
    "revert": "回滚 revert",
}


def rollup_commit_message_tags(commits: list[CommitRecord]) -> list[str]:
    """仅根据提交说明文本汇总可读标签（启发式，非 NLP 模型）。"""
    msgs = [c.message or "" for c in commits]
    n = len(msgs)
    if n == 0:
        return []
    first_lines = [m.strip().split("\n", 1)[0] for m in msgs if m.strip()]
    if not first_lines:
        return []
    tags: list[str] = []

    pct_conv = conventional_commit_pct(msgs)
    if pct_conv >= 55.0 and n >= 3:
        tags.append(f"提交说明高度符合 Conventional Commits（约 {pct_conv}%）")
    elif pct_conv <= 12.0 and n >= 6:
        tags.append("提交说明较少使用 Conventional Commits 前缀")

    type_ctr: Counter[str] = Counter()
    for line in first_lines:
        m = _CONV_TYPE_HEAD.match(line.strip())
        if m:
            type_ctr[m.group(1).lower()] += 1
    if type_ctr and n >= 4:
        top, tc = type_ctr.most_common(1)[0]
        if tc >= max(3, int(n * 0.26)):
            pct_t = round(100.0 * tc / n)
            tags.append(f"带类型前缀的提交以「{_TYPE_CN.get(top, top)}」为主（约 {pct_t}%）")

    merge_n = sum(1 for line in first_lines if re.match(r"^merge\s", line, re.IGNORECASE))
    if merge_n >= max(2, int(n * 0.18)):
        tags.append(f"合并类提交（Merge …）约占 {round(100.0 * merge_n / n)}%")

    rev_n = sum(
        1
        for line in first_lines
        if line.lower().startswith("revert ")
        or line.startswith("还原")
        or "回滚" in line[:24]
    )
    if rev_n >= max(2, int(n * 0.08)):
        tags.append(f"含 Revert/回滚语义的首行约 {round(100.0 * rev_n / n)}%")

    wip_n = sum(
        1 for m in msgs if re.search(r"\bwip\b|\btbd\b|\bdraft\b|暂存|草稿|进行中", m, re.IGNORECASE)
    )
    if wip_n >= max(2, int(n * 0.12)):
        tags.append("说明中较常出现 WIP/草稿/暂存类字眼")

    multi = sum(1 for m in msgs if "\n" in m.rstrip())
    if multi >= int(n * 0.32):
        tags.append("经常使用多行提交说明")

    cjk = latin = 0
    for line in first_lines:
        for ch in line:
            if "\u4e00" <= ch <= "\u9fff":
                cjk += 1
            elif "a" <= ch.lower() <= "z":
                latin += 1
    tot_ch = cjk + latin
    if tot_ch >= max(n * 4, 20):
        if cjk >= tot_ch * 0.45:
            tags.append("首行说明偏中文表述")
        elif latin >= tot_ch * 0.55:
            tags.append("首行说明偏英文表述")

    fix_kw = sum(
        1
        for m in msgs
        if re.search(r"\bfix\b|\bbug\b|hotfix|patch|修复|缺陷|bugfix|issue\s*#", m, re.IGNORECASE)
    )
    if fix_kw >= int(n * 0.22):
        tags.append("说明里修复/Bug/Issue 相关措辞较多")

    feat_kw = sum(
        1 for m in msgs if re.search(r"\bfeat\b|\badd\b|\bimplement|新增|实现|功能", m, re.IGNORECASE)
    )
    if feat_kw >= int(n * 0.22) and type_ctr.get("feat", 0) < int(n * 0.15):
        tags.append("说明里新增/实现类措辞较多")

    lens = [len(x) for x in first_lines]
    if lens:
        med = statistics.median(lens)
        if med < 16 and n >= 5:
            tags.append("首行偏好极短说明（简写风）")
        elif med > 80 and n >= 5:
            tags.append("首行说明偏长（单条信息量大）")

    scope_n = sum(1 for line in first_lines if re.match(r"^\[[^\]]+\]\s*", line))
    if scope_n >= max(3, int(n * 0.2)):
        tags.append("常用 [模块名] 式方括号前缀")

    return tags[:12]


def _indent_tag_cn(hint: str) -> str:
    return {
        "tabs": "diff 中更常出现 Tab 缩进",
        "4_spaces": "diff 中更常出现 4 空格缩进",
        "2_spaces": "diff 中更常出现 2 空格缩进",
        "8_spaces": "diff 中更常出现 8 空格缩进",
        "mixed": "diff 中缩进风格较混合",
    }.get(hint, "缩进风格未明")


def _lang_label(ext: str) -> str:
    return _EXT_LANG.get(ext.lower(), ext or "未知扩展名")


def rollup_style_from_commits(commits: list[CommitRecord]) -> tuple[list[str], dict[str, int], int]:
    """从已落库的 commit_style_json 汇总标签与语言混合度。"""
    parsed: list[dict[str, Any]] = []
    for c in commits:
        raw = c.commit_style_json
        if not raw or not str(raw).strip():
            continue
        try:
            d = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(d, dict):
            parsed.append(d)

    if not parsed:
        return [], {}, 0

    mix: dict[str, int] = defaultdict(int)
    indent_votes: Counter[str] = Counter()
    additions_list: list[int] = []
    commits_touching_testish = 0

    for d in parsed:
        ec = d.get("ext_counts")
        if isinstance(ec, dict):
            for k, v in ec.items():
                if isinstance(v, int) and v > 0:
                    mix[str(k).lower()] += v
        ih = d.get("indent_hint")
        if isinstance(ih, str) and ih in ("tabs", "4_spaces", "2_spaces", "8_spaces", "mixed"):
            indent_votes[ih] += 1
        ad = d.get("additions")
        if isinstance(ad, int) and ad >= 0:
            additions_list.append(ad)
        tf = d.get("testish_files")
        if isinstance(tf, int) and tf > 0:
            commits_touching_testish += 1

    tags: list[str] = []
    if mix:
        top_ext, top_n = max(mix.items(), key=lambda x: x[1])
        tot = sum(mix.values())
        if tot > 0 and top_n >= max(4, tot * 0.32):
            tags.append(f"{_lang_label(top_ext)}（{top_ext}）类改动占比较高")

    if indent_votes:
        winner, wn = indent_votes.most_common(1)[0]
        if wn >= max(2, len(parsed) // 4):
            tags.append(_indent_tag_cn(winner))

    tr = commits_touching_testish / len(parsed)
    if tr >= 0.3:
        tags.append("提交经常涉及测试/规格相关路径")
    elif tr <= 0.06 and len(parsed) >= 6:
        tags.append("较少在测试中露面（相对样本）")

    if additions_list:
        med = statistics.median(additions_list)
        if med < 38:
            tags.append("单次提交新增行数中位数偏低（偏细粒度）")
        elif med > 240:
            tags.append("单次提交新增行数中位数偏高（偏大批量）")

    mix_out = dict(sorted(mix.items(), key=lambda x: -x[1])[:24])
    return tags, mix_out, len(parsed)
