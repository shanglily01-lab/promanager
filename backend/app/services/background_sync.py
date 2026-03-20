"""进程内定时同步：按配置间隔拉取合并仓库列表（与手动「同步已配置的全部仓库」一致）。"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from fastapi import FastAPI

from app.config import settings
from app.database import SessionLocal
from app.services.repo_list_service import merged_sync_repos
from app.services.sync_service import run_sync

log = logging.getLogger("promanager.background_sync")


def _record_result(app: FastAPI, *, ok: bool, detail: str) -> None:
    app.state.last_background_sync_at = datetime.now(timezone.utc)
    app.state.last_background_sync_ok = ok
    app.state.last_background_sync_detail = detail[:800]


async def run_background_sync_loop(app: FastAPI) -> None:
    if not settings.background_sync_enabled:
        return
    delay = max(0.0, float(settings.background_sync_initial_delay_seconds))
    if delay:
        await asyncio.sleep(delay)
    interval = max(60.0, float(settings.background_sync_interval_hours) * 3600.0)

    while True:
        if getattr(app.state, "db_init_error", None):
            await asyncio.sleep(min(3600.0, interval))
            continue

        db = SessionLocal()
        try:
            repos = merged_sync_repos(db)
            if not repos:
                _record_result(app, ok=True, detail="跳过：合并仓库列表为空")
                log.info("后台同步跳过：无仓库")
            else:
                sid, n, err, nc, warn = await run_sync(db, repos, settings.default_since_days)
                if err:
                    _record_result(app, ok=False, detail=err)
                    log.warning("后台同步失败 sync_id=%s: %s", sid, err)
                elif warn:
                    msg = f"sync_id={sid} 新提交={n} 新成员档案={nc} 部分失败: {warn[:300]}"
                    _record_result(app, ok=True, detail=msg)
                    log.warning("后台同步完成（部分仓库失败）%s", msg)
                else:
                    msg = f"sync_id={sid} 新提交={n} 新成员档案={nc} 仓库数={len(repos)}"
                    _record_result(app, ok=True, detail=msg)
                    log.info("后台同步完成 %s", msg)
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001
            _record_result(app, ok=False, detail=f"{type(e).__name__}: {e}")
            log.exception("后台同步异常")
        finally:
            db.close()

        await asyncio.sleep(interval)
