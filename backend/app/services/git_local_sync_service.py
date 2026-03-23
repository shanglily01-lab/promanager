"""从本地 git 仓库镜像同步提交记录（通过 SSH 隧道访问的自建 Git 服务）。

仓库命名约定：tracked_repos.full_name 使用 "gitlocal:server/dezhou" 格式。
镜像路径：{REPO_MIRROR_ROOT}/{最后一段路径}，如 gitlocal:server/dezhou → {root}/dezhou
"""
from __future__ import annotations

import json
import os
import re
import subprocess
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

_CONVENTIONAL = re.compile(
    r"^(feat|fix|docs|style|refactor|test|chore|perf|ci|build|revert)(\([^\)]+\))?!?:\s",
    re.IGNORECASE,
)
_ISSUE_REF = re.compile(
    r"(#\d+|(close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s+#\d+)", re.IGNORECASE
)

_EXT_LANG: dict[str, str] = {
    ".py": "Python", ".ts": "TypeScript", ".tsx": "TSX",
    ".js": "JavaScript", ".jsx": "JSX", ".vue": "Vue",
    ".go": "Go", ".rs": "Rust", ".java": "Java",
    ".kt": "Kotlin", ".swift": "Swift", ".rb": "Ruby",
    ".php": "PHP", ".cs": "C#", ".cpp": "C++",
    ".c": "C", ".h": "C/C++ Header", ".lua": "Lua",
    ".sql": "SQL", ".md": "Markdown",
    ".yml": "YAML", ".yaml": "YAML", ".json": "JSON",
    ".html": "HTML", ".css": "CSS", ".sh": "Shell",
}


def is_gitlocal_repo(repo: str) -> bool:
    return repo.startswith("gitlocal:")


def gitlocal_mirror_path(repo: str, mirror_root: Path) -> Path:
    """gitlocal:server/dezhou → {mirror_root}/dezhou"""
    name = repo.removeprefix("gitlocal:")
    slug = name.split("/")[-1]
    return mirror_root / slug


def _ssh_env(ssh_key: str | None) -> dict[str, str]:
    env = dict(os.environ)
    if ssh_key:
        env["GIT_SSH_COMMAND"] = (
            f"ssh -i {ssh_key} -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null"
        )
    return env


def _run(cmd: list[str], cwd: Path, env: dict | None = None, timeout: int = 120) -> str:
    result = subprocess.run(
        cmd, cwd=cwd, capture_output=True,
        encoding="utf-8", errors="replace",
        env=env, timeout=timeout,
    )
    if result.returncode != 0:
        stderr = (result.stderr or "").strip()
        raise RuntimeError(stderr or f"命令失败: {' '.join(cmd)}")
    return result.stdout or ""


def _analyze_commit_style(mirror_path: Path, sha: str, message: str) -> str | None:
    """用 git diff-tree 分析文件改动，生成 style blob JSON。"""
    try:
        out = _run(
            ["git", "diff-tree", "--no-commit-id", "-r", "--numstat", sha],
            mirror_path,
        )
        lang_counter: Counter[str] = Counter()
        for line in out.strip().splitlines():
            parts = line.split("\t", 2)
            if len(parts) < 3:
                continue
            filepath = parts[2]
            filename = filepath.split("/")[-1]
            ext = ("." + filename.rsplit(".", 1)[-1]) if "." in filename else ""
            lang = _EXT_LANG.get(ext.lower())
            if lang:
                lang_counter[lang] += 1

        blob: dict[str, Any] = {}
        if lang_counter:
            blob["style_language_mix"] = dict(lang_counter.most_common(10))
        blob["style_conventional"] = bool(_CONVENTIONAL.match(message))
        blob["style_issue_ref"] = bool(_ISSUE_REF.search(message))
        m = _CONVENTIONAL.match(message)
        if m:
            blob["style_msg_tags"] = [m.group(1).lower()]
        return json.dumps(blob, ensure_ascii=False)
    except Exception:  # noqa: BLE001
        return None


def fetch_gitlocal_commits_normalized(
    repo: str,
    mirror_root: Path,
    since: datetime,
    ssh_key: str | None = None,
) -> list[dict[str, Any]]:
    """
    1. git fetch --all（SSH 隧道须已在运行）
    2. git log 解析 → normalized commit dicts
    """
    mirror_path = gitlocal_mirror_path(repo, mirror_root)
    if not mirror_path.is_dir():
        raise RuntimeError(
            f"本地镜像不存在: {mirror_path}，请先执行 git clone（通过 SSH 隧道）"
        )

    env = _ssh_env(ssh_key)
    try:
        _run(["git", "fetch", "--all", "--prune"], mirror_path, env=env, timeout=120)
    except RuntimeError as e:
        raise RuntimeError(f"git fetch 失败（SSH 隧道是否在运行？）: {e}") from e

    since_str = since.strftime("%Y-%m-%dT%H:%M:%S")
    log_out = _run(
        ["git", "log", "--all", f"--after={since_str}", "--format=%H|%an|%ae|%aI|%s"],
        mirror_path,
    )

    commits: list[dict[str, Any]] = []
    for line in log_out.strip().splitlines():
        if not line.strip():
            continue
        parts = line.split("|", 4)
        if len(parts) < 5:
            continue
        sha, author_name, author_email, committed_at_str, subject = parts
        try:
            committed_at = datetime.fromisoformat(committed_at_str)
        except ValueError:
            continue
        style_blob = _analyze_commit_style(mirror_path, sha, subject)
        commits.append({
            "sha": sha,
            "repo_full_name": repo,
            "author_login": None,
            "author_email": author_email.strip() or None,
            "author_name": author_name.strip() or None,
            "committed_at": committed_at,
            "message": subject.strip(),
            "html_url": None,
            "commit_style_json": style_blob,
        })
    return commits
