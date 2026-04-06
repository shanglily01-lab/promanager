import { useState } from "react";
import { DailyTab } from "./DailyTab";
import { WeeklyTab } from "./WeeklyTab";

type SubTab = "daily" | "weekly";

export function ReportsTab({ onError, team }: { onError: (msg: string | null) => void; team: string }) {
  const [sub, setSub] = useState<SubTab>("daily");

  return (
    <div>
      <div className="page-header">
        <h2 className="page-title">报告</h2>
        <div className="sub-tabs">
          <button
            type="button"
            className={sub === "daily" ? "active" : ""}
            onClick={() => setSub("daily")}
          >
            日报
          </button>
          <button
            type="button"
            className={sub === "weekly" ? "active" : ""}
            onClick={() => setSub("weekly")}
          >
            周报
          </button>
        </div>
      </div>
      {sub === "daily" ? <DailyTab onError={onError} team={team} hideHeader /> : null}
      {sub === "weekly" ? <WeeklyTab onError={onError} team={team} hideHeader /> : null}
    </div>
  );
}
