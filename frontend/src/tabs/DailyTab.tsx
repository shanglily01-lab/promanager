import { useState } from "react";
import type { DailyReport } from "../api";
import { getJson } from "../api";
import { DateInput } from "../components/DateInput";
import { RepoSourceBadge } from "../components/RepoSourceBadge";
import { todayISO } from "../utils/date";

type Props = { onError: (msg: string | null) => void; team: string; hideHeader?: boolean };

export function DailyTab({ onError, team, hideHeader }: Props) {
  const [dailyDate, setDailyDate] = useState(todayISO);
  const [daily, setDaily] = useState<DailyReport | null>(null);
  const [dailyMd, setDailyMd] = useState<string | null>(null);

  const loadDaily = async () => {
    onError(null);
    setDaily(null);
    setDailyMd(null);
    try {
      const [j, md] = await Promise.all([
        getJson<DailyReport>(`/api/reports/daily?date=${encodeURIComponent(dailyDate)}&team=${encodeURIComponent(team)}`),
        fetch(`/api/reports/daily.md?date=${encodeURIComponent(dailyDate)}&team=${encodeURIComponent(team)}`).then((r) => r.text()),
      ]);
      setDaily(j);
      setDailyMd(md);
    } catch (e) {
      onError(String(e));
    }
  };

  return (
    <div>
      {!hideHeader && <div className="page-header"><h2 className="page-title">日报</h2></div>}
      <div className="row" style={{ padding: "0 1rem" }}>
        <label>
          日期
          <DateInput value={dailyDate} onChange={setDailyDate} aria-label="日报日期" />
        </label>
        <button type="button" className="primary" onClick={loadDaily}>
          生成
        </button>
      </div>
      {daily && (
        <div className="employee-grid report-grid">
          {daily.employees.map((e) => (
            <div key={e.login} className="employee-card">
              <h3>
                <span className="emp-name">{e.display_name || e.login}</span>
                <span className="emp-key">
                  {" "}
                  · <code>{e.login}</code>
                </span>
                <span className={`badge ${e.had_submission ? "yes" : "no"}`}>
                  {e.had_submission ? "本日有提交" : "本日无提交"}
                </span>
                <span className="emp-meta">{e.total_commits_in_range} 次</span>
              </h3>
              {e.notes && <div className="emp-notes">备注：{e.notes}</div>}
              {(e.matched_emails?.length ?? 0) > 0 && (
                <div className="emp-notes">邮箱：{e.matched_emails.join(", ")}</div>
              )}
              {e.github_login && <div className="emp-notes">GitHub：@{e.github_login}</div>}
              {e.repos_touched.length > 0 && (
                <div className="emp-repos">仓库：{e.repos_touched.join(", ")}</div>
              )}
              <ul className="commit-list">
                {(daily.by_employee_commits[e.login] || []).slice(0, 8).map((c) => (
                  <li key={c.sha + c.repo_full_name}>
                    <a href={c.html_url || "#"} target="_blank" rel="noreferrer">
                      {c.sha.slice(0, 7)}
                    </a>{" "}
                    <span className="badge-inline">
                      <RepoSourceBadge fullName={c.repo_full_name} />
                    </span>
                    <code className="code-inline">{c.repo_full_name}</code> — {c.message.split("\n")[0].slice(0, 100)}
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
      )}
      {dailyMd && (
        <details className="md-details">
          <summary>Markdown 原文</summary>
          <pre className="md">{dailyMd}</pre>
        </details>
      )}
    </div>
  );
}
