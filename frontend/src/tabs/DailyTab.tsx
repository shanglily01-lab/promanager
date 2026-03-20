import { useState } from "react";
import type { DailyReport } from "../api";
import { getJson } from "../api";
import { RepoSourceBadge } from "../components/RepoSourceBadge";
import { todayISO } from "../utils/date";

type Props = { onError: (msg: string | null) => void };

export function DailyTab({ onError }: Props) {
  const [dailyDate, setDailyDate] = useState(todayISO);
  const [daily, setDaily] = useState<DailyReport | null>(null);
  const [dailyMd, setDailyMd] = useState<string | null>(null);

  const loadDaily = async () => {
    onError(null);
    setDaily(null);
    setDailyMd(null);
    try {
      const [j, md] = await Promise.all([
        getJson<DailyReport>(`/api/reports/daily?date=${encodeURIComponent(dailyDate)}`),
        fetch(`/api/reports/daily.md?date=${encodeURIComponent(dailyDate)}`).then((r) => r.text()),
      ]);
      setDaily(j);
      setDailyMd(md);
    } catch (e) {
      onError(String(e));
    }
  };

  return (
    <section className="card tab-panel" aria-labelledby="daily-heading">
      <h2 id="daily-heading">日报（按 UTC 日历日）</h2>
      <p className="card-hint">
        日期为 <strong>UTC</strong> 的 0 点边界（与国内日历可能差一天）。需先在「同步」页拉取提交后，再点「生成」；不会自动刷新。
      </p>
      <div className="row">
        <label>
          日期
          <input type="date" value={dailyDate} onChange={(e) => setDailyDate(e.target.value)} />
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
    </section>
  );
}
