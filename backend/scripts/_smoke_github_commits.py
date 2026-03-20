"""Smoke test for GitHub commits client. Run from repo root or backend:
   PYTHONPATH=backend .venv/Scripts/python scripts/_smoke_github_commits.py
"""
from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

BACKEND = Path(__file__).resolve().parent.parent
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

import app.github_client as gh_mod  # noqa: E402
from app.github_client import GitHubClient  # noqa: E402


async def main() -> None:
    # 足够早，保证公开示例仓库里能拿到至少一条 commit
    since = datetime(2000, 1, 1, tzinfo=timezone.utc)
    # 强制匿名，避免本地 .env 里的 Token 状态影响「公开库应能拉取」的验证
    with mock.patch.object(gh_mod.settings, "github_token", ""):
        gh = GitHubClient()
        n = len(await gh.fetch_commits_for_repo("octocat/Hello-World", since=since))
        if n < 1:
            raise SystemExit(f"smoke_fail expected >=1 commit from octocat/Hello-World, got {n}")
        print("smoke_ok anonymous octocat/Hello-World commits:", n)

    with mock.patch.object(gh_mod.settings, "github_token", ""):
        gh = GitHubClient()
        try:
            await gh.fetch_commits_for_repo("this-owner-does-not-exist-xyz123/nope", since=since)
        except RuntimeError as e:
            msg = str(e)
            assert "404" in msg and "GitHub 拉取提交失败" in msg, msg
            print("smoke_ok fake_repo friendly error:", msg[:100], "...")
            return
    print("smoke_fail expected RuntimeError for fake repo", file=sys.stderr)
    sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
