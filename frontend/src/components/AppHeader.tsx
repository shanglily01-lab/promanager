import type { ReactNode } from "react";
import type { HealthState } from "../types/health";

export function AppHeader({
  health,
  children,
}: {
  health: HealthState | null;
  children?: ReactNode;
}) {
  return (
    <header className="app-header">
      <div style={{ display: "flex", alignItems: "center", gap: "0.75rem", flex: 1, minWidth: 0 }}>
        <h1>ProManager</h1>
        {health && (
          <div className="header-pills">
            <span className={`pill ${health.has_token ? "ok" : "warn"}`}>
              {health.has_token ? "Token OK" : "未配置 Token"}
            </span>
            {health.database_ready === false && (
              <span className="pill warn" title={health.database_error || ""}>DB 异常</span>
            )}
            {health.background_sync?.enabled && (
              <span className="pill ok">
                每 {health.background_sync.interval_hours}h 自动同步
              </span>
            )}
          </div>
        )}
      </div>
      {children && <div style={{ flexShrink: 0 }}>{children}</div>}
    </header>
  );
}
