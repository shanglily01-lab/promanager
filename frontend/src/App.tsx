import { useCallback, useEffect, useState } from "react";
import { getJson } from "./api";
import { AppHeader } from "./components/AppHeader";
import type { HealthState } from "./types/health";
import { ContributorsTab } from "./tabs/ContributorsTab";
import { DailyTab } from "./tabs/DailyTab";
import { EmployeeTab } from "./tabs/EmployeeTab";
import { RepoMirrorsTab } from "./tabs/RepoMirrorsTab";
import { SyncTab } from "./tabs/SyncTab";
import { WeeklyTab } from "./tabs/WeeklyTab";

type TabId = "sync" | "mirrors" | "daily" | "weekly" | "contributors" | "employee";

const TABS: readonly { id: TabId; label: string }[] = [
  { id: "sync", label: "同步仓库" },
  { id: "mirrors", label: "仓库中心" },
  { id: "daily", label: "日报" },
  { id: "weekly", label: "周报" },
  { id: "contributors", label: "成员档案" },
  { id: "employee", label: "成员提交与习惯" },
] as const;

export default function App() {
  const [tab, setTab] = useState<TabId>("sync");
  const [health, setHealth] = useState<HealthState | null>(null);
  const [err, setErr] = useState<string | null>(null);

  const loadHealth = useCallback(() => {
    getJson<HealthState>("/api/health").then(setHealth).catch(() => setHealth(null));
  }, []);

  useEffect(() => {
    loadHealth();
  }, [loadHealth]);

  return (
    <>
      <AppHeader health={health} />

      <nav className="tabs" role="tablist" aria-label="功能分区">
        {TABS.map(({ id, label }) => (
          <button
            key={id}
            type="button"
            role="tab"
            aria-selected={tab === id}
            id={`tab-${id}`}
            aria-controls={`panel-${id}`}
            className={tab === id ? "active" : ""}
            onClick={() => {
              setErr(null);
              setTab(id);
            }}
          >
            {label}
          </button>
        ))}
      </nav>

      {err ? (
        <p className="err" role="alert">
          {err}
        </p>
      ) : null}

      <div
        className="tab-panel-wrap"
        role="tabpanel"
        id={`panel-${tab}`}
        aria-labelledby={`tab-${tab}`}
      >
        {tab === "sync" ? (
          <SyncTab
            onError={setErr}
            onHealthReload={loadHealth}
            awsDefaultRegion={health?.aws_default_region}
          />
        ) : null}
        {tab === "mirrors" ? <RepoMirrorsTab onError={setErr} /> : null}
        {tab === "daily" ? <DailyTab onError={setErr} /> : null}
        {tab === "weekly" ? <WeeklyTab onError={setErr} /> : null}
        {tab === "contributors" ? <ContributorsTab onError={setErr} /> : null}
        {tab === "employee" ? <EmployeeTab onError={setErr} /> : null}
      </div>
    </>
  );
}
