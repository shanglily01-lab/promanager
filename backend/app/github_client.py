from __future__ import annotations

import asyncio
import re
import time
from datetime import datetime, timezone
from typing import Any

import httpx

from app.config import settings


def _parse_link_header(link: str | None) -> dict[str, str]:
    if not link:
        return {}
    out: dict[str, str] = {}
    for part in link.split(","):
        m = re.search(r'<([^>]+)>;\s*rel="(\w+)"', part.strip())
        if m:
            out[m.group(2)] = m.group(1)
    return out


def _is_github_rate_limit_403(response: httpx.Response) -> bool:
    if response.status_code != 403:
        return False
    t = (response.text or "").lower()
    if "rate limit" in t or "too many requests" in t:
        return True
    rem = response.headers.get("x-ratelimit-remaining")
    if rem is not None and rem.isdigit() and int(rem) == 0:
        return True
    return False


def _github_rate_limit_wait_seconds(headers: httpx.Headers) -> float:
    ra = headers.get("retry-after")
    if ra and str(ra).isdigit():
        return min(int(ra), 120)
    reset = headers.get("x-ratelimit-reset")
    if reset and str(reset).isdigit():
        delta = int(reset) - int(time.time()) + 1
        return max(0.5, min(float(delta), 120))
    return min(3.0, 30.0)


def _github_rate_limit_user_message(response: httpx.Response, has_token: bool) -> str:
    parts = ["GitHub API 速率限制 (403)，本次同步已中止。"]
    reset = response.headers.get("x-ratelimit-reset")
    if reset and str(reset).isdigit():
        dt = datetime.fromtimestamp(int(reset), tz=timezone.utc)
        parts.append(f"额度约在 UTC {dt.strftime('%Y-%m-%d %H:%M:%S')} 刷新。")
    if not has_token:
        parts.append(
            "当前未配置 GITHUB_TOKEN：匿名访问约 60 次请求/小时，多仓库/多页拉取极易触发限制；"
            "请在 backend/.env 配置 Token 后重试（认证后约 5000 次/小时）。"
        )
    else:
        parts.append(
            "已配置 Token 仍触发限制时：可缩短回溯天数、减少单次同步仓库数量，或等待额度刷新后再试。"
        )
    return " ".join(parts)


class GitHubClient:
    def __init__(self, token: str | None = None):
        self.token = (token or settings.github_token or "").strip()
        self.base = "https://api.github.com"

    def _headers(self) -> dict[str, str]:
        h = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
        if self.token:
            h["Authorization"] = f"Bearer {self.token}"
        return h

    async def _get_page(
        self,
        client: httpx.AsyncClient,
        url: str,
        params: dict[str, str] | None,
    ) -> httpx.Response:
        has_token = bool(self.token)
        for attempt in range(8):
            r = await client.get(url, params=params if url.startswith(self.base) else None)
            if r.status_code == 403 and _is_github_rate_limit_403(r):
                if attempt < 7:
                    wait = _github_rate_limit_wait_seconds(r.headers)
                    await asyncio.sleep(wait)
                    continue
                raise RuntimeError(_github_rate_limit_user_message(r, has_token))
            r.raise_for_status()
            return r
        raise RuntimeError("GitHub 请求重试次数用尽")

    async def fetch_commits_for_repo(
        self,
        repo_full_name: str,
        since: datetime,
        until: datetime | None = None,
    ) -> list[dict[str, Any]]:
        """Return raw commit dicts from GitHub REST API."""
        params: dict[str, str] = {
            "since": since.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "per_page": "100",
        }
        if until:
            params["until"] = until.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        url = f"{self.base}/repos/{repo_full_name}/commits"
        commits: list[dict[str, Any]] = []

        async with httpx.AsyncClient(headers=self._headers(), timeout=60.0) as client:
            while url:
                r = await self._get_page(
                    client,
                    url,
                    params if url.startswith(self.base) else None,
                )
                batch = r.json()
                if isinstance(batch, list):
                    commits.extend(batch)
                rem = r.headers.get("x-ratelimit-remaining")
                if rem is not None and rem.isdigit() and int(rem) < 8:
                    await asyncio.sleep(0.35)
                link = _parse_link_header(r.headers.get("link"))
                url = link.get("next") or ""
                params = {}

        return commits

    @staticmethod
    def normalize_commit(repo_full_name: str, raw: dict[str, Any]) -> dict[str, Any] | None:
        sha = raw.get("sha")
        if not sha:
            return None
        c = raw.get("commit") or {}
        author_block = c.get("author") or {}
        committed_str = author_block.get("date")
        if not committed_str:
            return None
        committed_at = datetime.fromisoformat(committed_str.replace("Z", "+00:00"))
        gh_author = raw.get("author") or {}
        login = gh_author.get("login")
        email = (author_block.get("email") or "").strip() or None
        name = (author_block.get("name") or "").strip() or None
        msg = (c.get("message") or "").strip()
        html_url = raw.get("html_url")
        return {
            "sha": sha,
            "repo_full_name": repo_full_name,
            "author_login": login,
            "author_email": email,
            "author_name": name,
            "committed_at": committed_at,
            "message": msg,
            "html_url": html_url,
        }
