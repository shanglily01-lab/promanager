import { useState } from "react";
import type { WeeklyReport } from "../api";
import { getJson } from "../api";
import { DateInput } from "../components/DateInput";
import { RepoSourceBadge } from "../components/RepoSourceBadge";
import { mondayISO } from "../utils/date";

type Props = { onError: (msg: string | null) => void; team: string };

export function WeeklyTab({ onError, team }: Props) {
  const [weekStart, setWeekStart] = useState(mondayISO);
  const [weekly, setWeekly] = useState<WeeklyReport | null>(null);
  const [weeklyMd, setWeeklyMd] = useState<string | null>(null);

  const loadWeekly = async () => {
    onError(null);
    setWeekly(null);
    setWeeklyMd(null);
    try {
      const [j, md] = await Promise.all([
        getJson<WeeklyReport>(`/api/reports/weekly?week_start=${encodeURIComponent(weekStart)}&team=${encodeURIComponent(team)}`),
        fetch(`/api/reports/weekly.md?week_start=${encodeURIComponent(weekStart)}&team=${encodeURIComponent(team)}`).then((r) => r.text()),
      ]);
      setWeekly(j);
      setWeeklyMd(md);
    } catch (e) {
      onError(String(e));
    }
  };

  return (
    <div>
      <div className="page-header"><h2 className="page-title">周报</h2></div>
      <p className="card-hint" style={{ padding: "0 1rem", marginBottom: "0.75rem" }}>时间范围按 <strong>UTC</strong>；需先同步提交后再点「生成」。</p>
      <div className="row">
        <label>
          周起始（周一）
          <DateInput value={weekStart} onChange={setWeekStart} aria-label="周报周起始日（周一）" />
        </label>
        <button type="button" className="primary" onClick={loadWeekly}>
          生成
        </button>
      </div>
      {weekly && (
        <div className="employee-grid report-grid">
          {weekly.employees.map((e) => {
            const h = weekly.habits[e.login];
            return (
              <div key={e.login} className="employee-card">
                <h3>
                  <span className="emp-name">{e.display_name || e.login}</span>
                  <span className="emp-key">
                    {" "}
                    · <code>{e.login}</code>
                  </span>
                  <span className={`badge ${e.had_submission ? "yes" : "no"}`}>
                    {e.had_submission ? "本周有提交" : "本周无提交"}
                  </span>
                </h3>
                {e.notes && <div className="emp-notes">备注：{e.notes}</div>}
                {h && h.total_commits > 0 && (
                  <div className="habits-mini">
                    主要活跃(UTC)：{h.most_active_hour_utc ?? "—"} 点 · 最常 {h.most_active_weekday ?? "—"} · 平均说明长度{" "}
                    {h.avg_message_length} · 含 # {h.pct_messages_with_issue_ref}% · Conventional {h.pct_conventional_commits ?? 0}%
                    {(h.commits_with_style_sample ?? 0) > 0 ? ` · 画像样本 ${h.commits_with_style_sample} 条` : ""}
                  </div>
                )}
                {h && (h.commit_message_tags ?? []).length > 0 && (
                  <ul className="style-tag-list style-tag-list--compact" title="来自提交说明">
                    {(h.commit_message_tags ?? []).map((t) => (
                      <li key={`m-${t}`} className="style-tag style-tag--msg">
                        {t}
                      </li>
                    ))}
                  </ul>
                )}
                {h && (h.style_tags ?? []).length > 0 && (
                  <ul className="style-tag-list style-tag-list--compact" title="来自文件级画像">
                    {(h.style_tags ?? []).map((t) => (
                      <li key={t} className="style-tag">
                        {t}
                      </li>
                    ))}
                  </ul>
                )}
                <ul className="commit-list">
                  {(weekly.by_employee_commits[e.login] || []).slice(0, 6).map((c) => (
                    <li key={c.sha + c.committed_at}>
                      {c.committed_at.slice(0, 10)}{" "}
                      <span className="badge-inline">
                        <RepoSourceBadge fullName={c.repo_full_name} />
                      </span>
                      <code className="code-inline">{c.repo_full_name}</code> {c.message.split("\n")[0].slice(0, 80)}
                    </li>
                  ))}
                </ul>
              </div>
            );
          })}
        </div>
      )}
      {weeklyMd && (
        <details className="md-details">
          <summary>Markdown 原文</summary>
          <pre className="md">{weeklyMd}</pre>
        </details>
      )}
    </div>
  );
}
