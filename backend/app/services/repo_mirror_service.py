"""仓库中心：将合并列表中的仓库 clone / fetch 到本地目录，并记录状态。"""
from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.codecommit_client import is_codecommit_repo, parse_codecommit_ref
from app.config import settings
from app.models import RepoMirrorState
from app.services.git_local_sync_service import is_gitlocal_repo, gitlocal_mirror_path
from app.services.repo_list_service import merged_sync_repos

_GITHUB_NAME_RE = re.compile(r"^[\w.-]+/[\w.-]+$")

_scan_lock = threading.Lock()
_scan_running = False


def is_scan_running() -> bool:
    with _scan_lock:
        return _scan_running


def try_begin_scan() -> bool:
    global _scan_running
    with _scan_lock:
        if _scan_running:
            return False
        _scan_running = True
        return True


def end_scan() -> None:
    global _scan_running
    with _scan_lock:
        _scan_running = False


def git_on_path() -> bool:
    return shutil.which("git") is not None


def aws_cli_executable() -> str | None:
    w = shutil.which("aws")
    if w:
        return w
    parent = Path(sys.executable).resolve().parent
    if os.name == "nt":
        for name in ("aws.exe", "aws.cmd", "aws"):
            p = parent / name
            if p.is_file():
                return str(p)
    else:
        p = parent / "aws"
        return str(p) if p.is_file() else None
    return None


def aws_cli_on_path() -> bool:
    return aws_cli_executable() is not None


def _git_env_for_codecommit() -> dict[str, str]:
    """让 git 子进程能找到与当前 Python 同 venv 下的 aws（pip install awscli）。"""
    scripts = str(Path(sys.executable).resolve().parent)
    return {"PATH": scripts + os.pathsep + os.environ.get("PATH", "")}


def mirror_rel_path(full_name: str) -> str:
    if is_gitlocal_repo(full_name):
        mirror = gitlocal_mirror_path(full_name, settings.repo_mirror_root_path)
        return str(mirror.relative_to(settings.repo_mirror_root_path)).replace("\\", "/")
    if is_codecommit_repo(full_name):
        parsed = parse_codecommit_ref(full_name)
        if not parsed:
            raise ValueError(f"无效的 CodeCommit 标识: {full_name}")
        region, repo, branch = parsed
        safe_repo = re.sub(r"[^\w.\-]", "_", repo)[:180]
        parts = Path("codecommit") / region.lower() / safe_repo
        if branch:
            br = re.sub(r"[^\w.\-/]", "_", branch)[:100].replace("/", "_")
            parts = parts / f"_b_{br}"
        return str(parts).replace("\\", "/")
    fn = full_name.strip()
    if not _GITHUB_NAME_RE.match(fn):
        raise ValueError(f"非法 GitHub 仓库名: {full_name}")
    owner, name = fn.split("/", 1)
    return str(Path("github") / owner / name).replace("\\", "/")


def absolute_mirror_path(full_name: str) -> Path:
    rel = mirror_rel_path(full_name)
    return settings.repo_mirror_root_path / rel


def _github_clone_url(owner: str, repo: str, token: str) -> str:
    tok = quote(token.strip(), safe="")
    return f"https://x-access-token:{tok}@github.com/{owner}/{repo}.git"


def _codecommit_https_url(region: str, repo: str) -> str:
    return f"https://git-codecommit.{region}.amazonaws.com/v1/repos/{repo}"


def _cc_git_prefix(target: Path) -> list[str]:
    return [
        "git",
        "-C",
        str(target),
        "-c",
        "credential.helper=aws codecommit credential-helper",
        "-c",
        "credential.UseHttpPath=true",
    ]


def _run_git(
    args: list[str],
    *,
    cwd: Path | None = None,
    timeout: int = 240,
    extra_env: dict[str, str] | None = None,
) -> tuple[int, str, str]:
    env = None
    if extra_env:
        env = {**os.environ, **extra_env}
    try:
        p = subprocess.run(
            args,
            cwd=str(cwd) if cwd else None,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
            shell=False,
        )
        return p.returncode, (p.stdout or "").strip(), (p.stderr or "").strip()
    except subprocess.TimeoutExpired:
        return 124, "", "git 命令超时"
    except FileNotFoundError:
        return 127, "", "未找到 git 可执行文件"


def _under_mirror_root(target: Path) -> bool:
    try:
        root = settings.repo_mirror_root_path.resolve()
        t = target.resolve()
        return t == root or root in t.parents
    except OSError:
        return False


def _safe_remove_mirror_clone(target: Path) -> None:
    if not target.exists() or not _under_mirror_root(target):
        return
    shutil.rmtree(target, ignore_errors=True)


def _is_checkout_or_path_failure(combined: str) -> bool:
    """Windows 下仓库内文件名含 : 等非法字符时，clone 常报 checkout failed。"""
    low = (combined or "").lower()
    return any(
        s in low
        for s in (
            "unable to checkout",
            "checkout failed",
            "invalid path",
            "filename not valid",
            "could not checkout",
        )
    )


def _github_git(*extra: str) -> list[str]:
    """禁用全局 credential-manager（URL 已带 token 时避免误调不存在的 helper）。"""
    return ["git", "-c", "credential.helper=", *extra]


def mirror_one(full_name: str) -> tuple[str, str, str]:
    """
    克隆或拉取单个仓库。
    返回 (status, detail, local_rel_path)；status 为 ok | error | skipped。
    """
    fn = full_name.strip()
    rel = ""
    try:
        try:
            rel = mirror_rel_path(fn)
        except ValueError as e:
            return "error", str(e), ""

        root = settings.repo_mirror_root_path
        target = root.joinpath(*rel.split("/")) if rel else root
        root.mkdir(parents=True, exist_ok=True)

        if not git_on_path():
            return "error", "系统未安装 git 或不在 PATH 中", rel

        if is_gitlocal_repo(fn):
            # gitlocal 镜像由同步时自动管理，仓库中心只展示状态
            mirror = gitlocal_mirror_path(fn, settings.repo_mirror_root_path)
            if (mirror / ".git").is_dir():
                return "ok", "gitlocal 镜像已就绪（通过同步管理）", rel
            return "skipped", "gitlocal 镜像尚未创建，请先执行同步", rel

        if is_codecommit_repo(fn):
            parsed = parse_codecommit_ref(fn)
            if not parsed:
                return "error", "无法解析 CodeCommit 标识", rel
            region, repo, branch = parsed
            if not aws_cli_on_path():
                return (
                    "skipped",
                    "未检测到 aws 可执行文件。请在 backend 目录执行: pip install -r requirements.txt（已含 awscli），"
                    "或使用与运行 uvicorn 相同的虚拟环境；无需单独安装系统级 AWS CLI。",
                    rel,
                )
            cc_env = _git_env_for_codecommit()
            url = _codecommit_https_url(region, repo)
            if target.is_dir() and (target / ".git").is_dir():
                code, out, err = _run_git(
                    [*_cc_git_prefix(target), "fetch", "origin"],
                    timeout=300,
                    extra_env=cc_env,
                )
                msg = err or out
                if code == 0:
                    return "ok", "git fetch 成功", rel
                return "error", (msg or f"exit {code}")[:2000], rel

            target.parent.mkdir(parents=True, exist_ok=True)
            clone_cmd = [
                "git",
                "-c",
                "credential.helper=aws codecommit credential-helper",
                "-c",
                "credential.UseHttpPath=true",
                "clone",
                "--depth",
                "1",
            ]
            if branch:
                clone_cmd += ["-b", branch]
            clone_cmd += [url, str(target)]
            code, out, err = _run_git(clone_cmd, timeout=600, extra_env=cc_env)
            msg = err or out
            if code == 0:
                return "ok", "git clone 成功", rel
            if _is_checkout_or_path_failure(msg) or _is_checkout_or_path_failure(out):
                _safe_remove_mirror_clone(target)
                target.parent.mkdir(parents=True, exist_ok=True)
                clone_cmd2 = [
                    "git",
                    "-c",
                    "credential.helper=aws codecommit credential-helper",
                    "-c",
                    "credential.UseHttpPath=true",
                    "clone",
                    "--depth",
                    "1",
                    "--no-checkout",
                ]
                if branch:
                    clone_cmd2 += ["-b", branch]
                clone_cmd2 += [url, str(target)]
                c2, o2, e2 = _run_git(clone_cmd2, timeout=600, extra_env=cc_env)
                msg2 = (e2 or o2).strip()
                if c2 == 0:
                    return (
                        "ok",
                        "git clone 成功（--no-checkout，未检出工作区；原因多为 Windows 无法创建含非法字符的文件名）",
                        rel,
                    )
                msg = f"首次: {msg[:800]}；--no-checkout: {msg2 or c2}"
            return "error", (msg or f"exit {code}")[:2000], rel

        # GitHub：有 Token 用 x-access-token；无则尝试公开克隆
        owner, repo = fn.split("/", 1)
        token = (settings.github_token_for_repo(fn) or "").strip()
        if token:
            url = _github_clone_url(owner, repo, token)
        else:
            url = f"https://github.com/{owner}/{repo}.git"

        if target.is_dir() and (target / ".git").is_dir():
            code, out, err = _run_git(
                _github_git("-C", str(target), "fetch", "origin"),
                timeout=300,
            )
            msg = err or out
            if code == 0:
                return "ok", "git fetch 成功", rel
            return "error", (msg or f"exit {code}")[:2000], rel

        target.parent.mkdir(parents=True, exist_ok=True)
        clone_cmd = _github_git("clone", "--depth", "1", url, str(target))
        code, out, err = _run_git(clone_cmd, timeout=600)
        msg = err or out
        if code == 0:
            return "ok", "git clone 成功", rel

        if _is_checkout_or_path_failure(msg) or _is_checkout_or_path_failure(out):
            _safe_remove_mirror_clone(target)
            target.parent.mkdir(parents=True, exist_ok=True)
            cmd2 = _github_git("clone", "--depth", "1", "--no-checkout", url, str(target))
            c2, o2, e2 = _run_git(cmd2, timeout=600)
            msg2 = (e2 or o2).strip()
            if c2 == 0:
                return (
                    "ok",
                    "git clone 成功（--no-checkout：仅拉取对象未检出工作区。"
                    "Windows 下若仓库含文件名非法字符如冒号 : 会导致正常检出失败，可用 WSL 或改名后全量检出）",
                    rel,
                )
            msg = f"首次 clone: {msg[:900]}；重试 --no-checkout: {msg2 or c2}"

        hint = ""
        if not token and (
            "Authentication failed" in msg or "could not read Username" in msg or "403" in msg
        ):
            hint = "（提示：私有库需在 .env 配置 GITHUB_TOKEN 或 GITHUB_TOKEN_REPO_MAP）"
        return "error", ((msg or f"exit {code}") + hint)[:2000], rel

    except OSError as e:
        return "error", f"文件系统或路径错误: {e}"[:2000], rel
    except Exception as e:  # noqa: BLE001
        logging.exception("mirror_one 未预期异常: %s", fn)
        return "error", f"{type(e).__name__}: {e}"[:2000], rel


def _upsert_state(db: Session, full_name: str, status: str, detail: str, rel: str) -> None:
    row = db.execute(select(RepoMirrorState).where(RepoMirrorState.full_name == full_name)).scalars().first()
    now = datetime.now(timezone.utc)
    if row:
        row.status = status
        row.detail = detail[:8000]
        row.local_rel_path = rel[:500]
        row.updated_at = now
    else:
        db.add(
            RepoMirrorState(
                full_name=full_name,
                status=status,
                detail=detail[:8000],
                local_rel_path=rel[:500],
                updated_at=now,
            )
        )


def _commit_one_mirror(db: Session, full_name: str, status: str, detail: str, rel: str) -> None:
    try:
        _upsert_state(db, full_name, status, detail, rel)
        db.commit()
    except Exception:  # noqa: BLE001
        logging.exception("写入 repo_mirror_states 失败: %s", full_name)
        try:
            db.rollback()
        except Exception:  # noqa: BLE001
            pass


def run_mirror_scan_db(
    db: Session, repos_filter: list[str] | None = None, team: str | None = None
) -> None:
    """顺序扫描并 commit 每条；调用方已持有扫描锁。"""
    if not git_on_path():
        targets = repos_filter if repos_filter else merged_sync_repos(db, team=team)
        for fn in targets:
            try:
                rel = mirror_rel_path(fn)
            except ValueError:
                rel = ""
            _commit_one_mirror(db, fn, "error", "系统未安装 git 或不在 PATH 中", rel)
        return

    targets = repos_filter if repos_filter else merged_sync_repos(db, team=team)
    for fn in targets:
        try:
            status, detail, rel = mirror_one(fn)
            _commit_one_mirror(db, fn, status, detail, rel)
        except Exception as e:  # noqa: BLE001
            logging.exception("扫描单仓异常: %s", fn)
            try:
                db.rollback()
            except Exception:  # noqa: BLE001
                pass
            try:
                rel = mirror_rel_path(fn)
            except ValueError:
                rel = ""
            _commit_one_mirror(db, fn, "error", str(e)[:2000], rel)


def build_center_payload(db: Session, team: str | None = None) -> dict:
    merged = merged_sync_repos(db, team=team)
    by_fn = {r.full_name: r for r in db.execute(select(RepoMirrorState)).scalars().all()}
    # 兼容大小写：合并列表为主键
    by_lower = {k.lower(): v for k, v in by_fn.items()}
    items: list[dict] = []
    for fn in merged:
        st = by_fn.get(fn) or by_lower.get(fn.lower())
        if st:
            items.append(
                {
                    "full_name": fn,
                    "status": st.status,
                    "detail": st.detail or "",
                    "local_rel_path": st.local_rel_path or mirror_rel_path(fn),
                    "updated_at": st.updated_at,
                }
            )
        else:
            try:
                rel = mirror_rel_path(fn)
            except ValueError:
                rel = ""
            items.append(
                {
                    "full_name": fn,
                    "status": "pending",
                    "detail": "尚未执行检测/拉取",
                    "local_rel_path": rel,
                    "updated_at": None,
                }
            )
    return {
        "mirror_root": str(settings.repo_mirror_root_path),
        "git_available": git_on_path(),
        "aws_cli_available": aws_cli_on_path(),
        "scan_in_progress": is_scan_running(),
        "items": items,
    }
