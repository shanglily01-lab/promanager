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
type Team = "web3" | "game";

const TEAMS: readonly { id: Team; label: string }[] = [
  { id: "web3", label: "Web3 团队" },
  { id: "game", label: "游戏团队" },
] as const;

const TABS: readonly { id: TabId; label: string }[] = [
  { id: "sync", label: "同步仓库" },
  { id: "mirrors", label: "仓库中心" },
  { id: "daily", label: "日报" },
  { id: "weekly", label: "周报" },
  { id: "contributors", label: "成员档案" },
  { id: "employee", label: "成员提交与习惯" },
] as const;

export default function App() {
  const [team, setTeam] = useState<Team>("web3");
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

      <nav className="team-switcher" role="tablist" aria-label="团队切换">
        {TEAMS.map(({ id, label }) => (
          <button
            key={id}
            type="button"
            role="tab"
            aria-selected={team === id}
            className={team === id ? "active" : ""}
            onClick={() => {
              setErr(null);
              setTeam(id);
            }}
          >
            {label}
          </button>
        ))}
      </nav>

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
            team={team}
          />
        ) : null}
        {tab === "mirrors" ? <RepoMirrorsTab onError={setErr} team={team} /> : null}
        {tab === "daily" ? <DailyTab onError={setErr} team={team} /> : null}
        {tab === "weekly" ? <WeeklyTab onError={setErr} team={team} /> : null}
        {tab === "contributors" ? <ContributorsTab onError={setErr} team={team} /> : null}
        {tab === "employee" ? <EmployeeTab onError={setErr} team={team} /> : null}
      </div>
    </>
  );
}
