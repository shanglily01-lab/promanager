import { useCallback, useEffect, useState } from "react";
import { getJson } from "./api";
import { AppHeader } from "./components/AppHeader";
import type { HealthState } from "./types/health";
import { ContributorsTab } from "./tabs/ContributorsTab";
import { DailyTab } from "./tabs/DailyTab";
import { EmployeeTab } from "./tabs/EmployeeTab";
import { RepoMirrorsTab } from "./tabs/RepoMirrorsTab";
import { ReportsTab } from "./tabs/ReportsTab";
import { SyncTab } from "./tabs/SyncTab";
import { WeeklyTab } from "./tabs/WeeklyTab";

type TabId = "sync" | "mirrors" | "contributors" | "employee" | "daily" | "weekly" | "reports";
type Team = "web3" | "game";

const TEAMS: readonly { id: Team; label: string }[] = [
  { id: "web3", label: "Web3" },
  { id: "game", label: "游戏" },
] as const;

// Bottom nav: 5 main tabs
const BOTTOM_TABS: readonly { id: TabId; label: string; icon: string }[] = [
  {
    id: "sync",
    label: "同步",
    icon: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 2v6h-6"/><path d="M3 12a9 9 0 0 1 15-6.7L21 8"/><path d="M3 22v-6h6"/><path d="M21 12a9 9 0 0 1-15 6.7L3 16"/></svg>`,
  },
  {
    id: "contributors",
    label: "成员",
    icon: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="9" cy="7" r="4"/><path d="M3 21v-2a4 4 0 0 1 4-4h4a4 4 0 0 1 4 4v2"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/><path d="M21 21v-2a4 4 0 0 0-3-3.87"/></svg>`,
  },
  {
    id: "employee",
    label: "分析",
    icon: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="20" x2="18" y2="10"/><line x1="12" y1="20" x2="12" y2="4"/><line x1="6" y1="20" x2="6" y2="14"/></svg>`,
  },
  {
    id: "mirrors",
    label: "仓库",
    icon: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 3h7v7H3z"/><path d="M14 3h7v7h-7z"/><path d="M14 14h7v7h-7z"/><path d="M3 14h7v7H3z"/></svg>`,
  },
  {
    id: "reports",
    label: "报告",
    icon: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/><line x1="10" y1="9" x2="8" y2="9"/></svg>`,
  },
] as const;

// All tabs for desktop top nav
const ALL_TABS: readonly { id: TabId; label: string }[] = [
  { id: "sync",         label: "同步" },
  { id: "mirrors",      label: "仓库中心" },
  { id: "contributors", label: "成员" },
  { id: "employee",     label: "分析" },
  { id: "reports",      label: "报告" },
  { id: "daily",        label: "日报" },
  { id: "weekly",       label: "周报" },
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
      {/* Sticky header */}
      <AppHeader health={health}>
        <div className="team-switcher">
          {TEAMS.map(({ id, label }) => (
            <button
              key={id}
              type="button"
              className={team === id ? "active" : ""}
              onClick={() => { setErr(null); setTeam(id); }}
            >
              {label}
            </button>
          ))}
        </div>
      </AppHeader>

      {/* Desktop top tabs */}
      <nav className="tabs" role="tablist" aria-label="功能分区">
        {ALL_TABS.map(({ id, label }) => (
          <button
            key={id}
            type="button"
            role="tab"
            aria-selected={tab === id}
            id={`tab-${id}`}
            aria-controls={`panel-${id}`}
            className={tab === id ? "active" : ""}
            onClick={() => { setErr(null); setTab(id); }}
          >
            {label}
          </button>
        ))}
      </nav>

      {err ? (
        <p className="err" role="alert">{err}</p>
      ) : null}

      <div
        className="tab-panel-wrap"
        role="tabpanel"
        id={`panel-${tab}`}
        aria-labelledby={`tab-${tab}`}
      >
        {tab === "sync"         ? <SyncTab onError={setErr} onHealthReload={loadHealth} awsDefaultRegion={health?.aws_default_region} team={team} /> : null}
        {tab === "mirrors"      ? <RepoMirrorsTab onError={setErr} team={team} /> : null}
        {tab === "contributors" ? <ContributorsTab onError={setErr} team={team} /> : null}
        {tab === "employee"     ? <EmployeeTab onError={setErr} team={team} /> : null}
        {tab === "reports"      ? <ReportsTab onError={setErr} team={team} /> : null}
        {tab === "daily"        ? <DailyTab onError={setErr} team={team} /> : null}
        {tab === "weekly"       ? <WeeklyTab onError={setErr} team={team} /> : null}
      </div>

      {/* Mobile bottom tab nav */}
      <nav className="bottom-nav" role="tablist" aria-label="主导航">
        {BOTTOM_TABS.map(({ id, label, icon }) => (
          <button
            key={id}
            type="button"
            role="tab"
            aria-selected={tab === id}
            className={tab === id ? "active" : ""}
            onClick={() => { setErr(null); setTab(id); }}
            dangerouslySetInnerHTML={undefined}
          >
            <span dangerouslySetInnerHTML={{ __html: icon }} style={{ display: "flex" }} />
            {label}
          </button>
        ))}
      </nav>
    </>
  );
}
