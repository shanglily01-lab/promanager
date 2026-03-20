import type { HealthState } from "../types/health";

export function AppHeader({ health }: { health: HealthState | null }) {
  return (
    <header className="app-header">
      <div>
        <h1>ProManager</h1>
        <p>
          从 <strong>GitHub</strong> 与 <strong>AWS CodeCommit</strong> 同步提交，生成日报 / 周报；支持按邮箱 /
          GitHub 登录绑定昵称与备注，合并同一人多条身份。
        </p>
      </div>
      {health && (
        <div className="header-pills">
          <span className={`pill ${health.has_token ? "ok" : "warn"}`}>
            {health.has_token ? "已配置 Token" : "未配置 GITHUB_TOKEN（仅公开库可匿名拉取，速率低）"}
          </span>
          {health.commit_count != null && (
            <span className="pill ok" title="数据库中的提交条数（导入仓库不会增加此项，需同步后才有）">
              已入库提交 {health.commit_count} 条
            </span>
          )}
          {health.background_sync?.enabled && (
            <span
              className="pill ok"
              title={
                health.background_sync.last_detail
                  ? `上次：${health.background_sync.last_detail}`
                  : "进程内定时任务，与「同步已配置的全部仓库」相同"
              }
            >
              后台每 {health.background_sync.interval_hours}h 同步 · 回溯 {health.background_sync.since_days} 天
              {health.background_sync.last_run_at
                ? ` · 上次 ${health.background_sync.last_ok === false ? "失败" : "完成"}`
                : ""}
            </span>
          )}
          {health.database_ready === false && (
            <span className="pill warn" title={health.database_error || "请打开 /api/health 查看详情"}>
              数据库未就绪（MySQL 连不上或建表失败）
            </span>
          )}
        </div>
      )}
    </header>
  );
}
