import { useEffect, useMemo, useState } from "react";
import type { CommitItem, HabitsSummary } from "../api";
import { getJson } from "../api";
import { DateInput } from "../components/DateInput";
import { RepoSourceBadge } from "../components/RepoSourceBadge";

type Props = { onError: (msg: string | null) => void; team: string };

type HabitChangeItem = {
  dimension: string;
  before_desc: string;
  after_desc: string;
  trend: string;
  conclusion: string;
  significant: boolean;
};

type HabitChangeReport = {
  period1_from: string;
  period1_to: string;
  period2_from: string;
  period2_to: string;
  period1_commits: number;
  period2_commits: number;
  changes: HabitChangeItem[];
  summary: string;
};

export function EmployeeTab({ onError, team }: Props) {
  const [empLogin, setEmpLogin] = useState("");
  const [empFrom, setEmpFrom] = useState("");
  const [empTo, setEmpTo] = useState("");
  const [empCommits, setEmpCommits] = useState<CommitItem[] | null>(null);
  const [empHabits, setEmpHabits] = useState<HabitsSummary | null>(null);
  const [employeeKeyOptions, setEmployeeKeyOptions] = useState<{ key: string; label: string }[]>([]);

  // Habit change detection state
  const [hcP2From, setHcP2From] = useState("");
  const [hcP2To, setHcP2To] = useState("");
  const [hcReport, setHcReport] = useState<HabitChangeReport | null>(null);
  const [hcLoading, setHcLoading] = useState(false);

  // 切换团队时清空已加载数据
  useEffect(() => {
    setEmpLogin("");
    setEmpCommits(null);
    setEmpHabits(null);
    setHcReport(null);
  }, [team]);

  useEffect(() => {
    getJson<{
      employee_key_options?: { key: string; label: string }[];
      employee_keys?: string[];
    }>(`/api/employees?team=${encodeURIComponent(team)}`)
      .then((j) => {
        if (j.employee_key_options?.length) {
          setEmployeeKeyOptions(j.employee_key_options);
        } else {
          setEmployeeKeyOptions((j.employee_keys ?? []).map((k) => ({ key: k, label: k })));
        }
      })
      .catch(() => setEmployeeKeyOptions([]));
  }, [team]);

  const loadEmployee = async () => {
    onError(null);
    setEmpCommits(null);
    setEmpHabits(null);
    if (!empLogin.trim()) {
      onError("填写报表主键：GitHub 登录、email:邮箱、contrib:档案ID 或 _unknown");
      return;
    }
    const q = new URLSearchParams();
    if (empFrom) q.set("from", empFrom);
    if (empTo) q.set("to", empTo);
    q.set("team", team);
    const qs = q.toString();
    const suffix = qs ? `?${qs}` : "";
    const key = empLogin.trim();
    try {
      const [c, h] = await Promise.all([
        getJson<CommitItem[]>(`/api/employees/${encodeURIComponent(key)}/commits${suffix}`),
        getJson<HabitsSummary>(`/api/employees/${encodeURIComponent(key)}/habits${suffix}`),
      ]);
      setEmpCommits(c);
      setEmpHabits(h);
    } catch (e) {
      onError(String(e));
    }
  };

  const loadHabitChange = async () => {
    onError(null);
    setHcReport(null);
    const key = empLogin.trim();
    if (!key) {
      onError("请先选择成员");
      return;
    }
    if (!empFrom || !empTo) {
      onError("请先在上方填写前期日期范围");
      return;
    }
    if (!hcP2From || !hcP2To) {
      onError("请填写后期日期范围");
      return;
    }
    setHcLoading(true);
    try {
      const q = new URLSearchParams({
        p1_from: empFrom,
        p1_to: empTo,
        p2_from: hcP2From,
        p2_to: hcP2To,
        ...(team ? { team } : {}),
      });
      const report = await getJson<HabitChangeReport>(
        `/api/employees/${encodeURIComponent(key)}/habit-changes?${q.toString()}`
      );
      setHcReport(report);
    } catch (e) {
      onError(String(e));
    } finally {
      setHcLoading(false);
    }
  };

  const maxHour = useMemo(() => {
    if (!empHabits) return 1;
    return Math.max(1, ...Object.values(empHabits.commits_by_hour_utc));
  }, [empHabits]);

  const trendIcon = (trend: string) => {
    if (trend === "up") return "↑";
    if (trend === "down") return "↓";
    if (trend === "shift") return "⇄";
    return "—";
  };

  return (
    <div>
      <div className="page-header">
        <h2 className="page-title">员工分析</h2>
      </div>
      <div className="row row--tight" style={{ padding: "0 1rem" }}>
        <label>
          成员
          <select
            aria-label="按成员名称选择"
            value={empLogin}
            onChange={(e) => setEmpLogin(e.target.value)}
            style={{ width: "auto", minWidth: "9rem", maxWidth: "16rem" }}
          >
            <option value="">选择成员…</option>
            {employeeKeyOptions.map((o) => (
              <option key={o.key} value={o.key}>
                {o.label}
              </option>
            ))}
          </select>
        </label>
      </div>
      <div className="row row--tight" style={{ padding: "0 1rem" }}>
        <label>
          前期 从
          <DateInput value={empFrom} onChange={setEmpFrom} aria-label="提交区间开始日期" />
        </label>
        <label>
          到
          <DateInput value={empTo} onChange={setEmpTo} aria-label="提交区间结束日期" />
        </label>
        <button type="button" className="primary" onClick={loadEmployee}>
          查询
        </button>
      </div>
      {empHabits && (
        <div className="habits-block">
          <div className="habits-mini">
            区间内共 <strong className="habits-count">{empHabits.total_commits}</strong> 次提交 · UTC 小时分布：
          </div>
          <div className="hour-bars" title="UTC 0–23 点">
            {Array.from({ length: 24 }, (_, h) => {
              const n = empHabits.commits_by_hour_utc[String(h)] || 0;
              const pct = (n / maxHour) * 100;
              return <span key={h} style={{ height: `${Math.max(pct, 2)}%` }} />;
            })}
          </div>
          {empHabits.total_commits > 0 && (
            <div className="habits-style">
              <div className="habits-mini">
                Conventional Commits 约 <strong>{empHabits.pct_conventional_commits ?? 0}%</strong>
                {(empHabits.commits_with_style_sample ?? 0) > 0
                  ? ` · 含文件画像的提交 ${empHabits.commits_with_style_sample} 条`
                  : <span className="mobile-hide"> · 尚无文件级画像（需开启同步时的详情拉取并重新同步新提交）</span>}
              </div>
              {(empHabits.commit_message_tags ?? []).length > 0 && (
                <>
                  <div className="habits-mini habits-mini--sub">提交说明标签</div>
                  <ul className="style-tag-list">
                    {(empHabits.commit_message_tags ?? []).map((t) => (
                      <li key={`m-${t}`} className="style-tag style-tag--msg">
                        {t}
                      </li>
                    ))}
                  </ul>
                </>
              )}
              {(empHabits.style_tags ?? []).length > 0 && (
                <>
                  <div className="habits-mini habits-mini--sub">代码改动画像</div>
                  <ul className="style-tag-list">
                    {(empHabits.style_tags ?? []).map((t) => (
                      <li key={t} className="style-tag">
                        {t}
                      </li>
                    ))}
                  </ul>
                </>
              )}
            </div>
          )}
        </div>
      )}
      {empCommits && empCommits.length > 0 && (
        <ul className="commit-list commit-list--top">
          {empCommits.slice(0, 40).map((c) => (
            <li key={c.sha}>
              <a href={c.html_url || "#"} target="_blank" rel="noreferrer">
                {c.sha.slice(0, 7)}
              </a>{" "}
              <span className="badge-inline">
                <RepoSourceBadge fullName={c.repo_full_name} />
              </span>
              {c.committed_at} <code className="code-inline">{c.repo_full_name}</code>
            </li>
          ))}
        </ul>
      )}
      {empCommits && empCommits.length === 0 && <p className="card-hint">该条件下无提交记录。</p>}

      {/* ── 习惯变化检测 ─────────────────────────────── */}
      <h2 className="subsection-title">习惯变化检测</h2>
      <div className="row row--tight" style={{ padding: "0 1rem" }}>
        <label>
          后期 从
          <DateInput value={hcP2From} onChange={setHcP2From} aria-label="后期开始日期" />
        </label>
        <label>
          到
          <DateInput value={hcP2To} onChange={setHcP2To} aria-label="后期结束日期" />
        </label>
        <button type="button" className="primary" disabled={hcLoading} onClick={loadHabitChange}>
          {hcLoading ? "分析中…" : "对比"}
        </button>
      </div>

      {hcReport && (
        <div className="hc-result">
          <div className={`hc-summary ${hcReport.changes.some((c) => c.significant) ? "hc-summary--alert" : ""}`}>
            {hcReport.summary}
          </div>
          <div className="hc-meta">
            前期 {hcReport.period1_from} ~ {hcReport.period1_to}（{hcReport.period1_commits} 次提交）
            <span className="hc-vs">vs</span>
            后期 {hcReport.period2_from} ~ {hcReport.period2_to}（{hcReport.period2_commits} 次提交）
          </div>
          <div className="hc-table-wrap">
            <table className="hc-table">
              <thead>
                <tr>
                  <th>维度</th>
                  <th>前期</th>
                  <th>后期</th>
                  <th>趋势</th>
                  <th>结论</th>
                </tr>
              </thead>
              <tbody>
                {hcReport.changes.map((item) => (
                  <tr key={item.dimension} className={item.significant ? "hc-row--significant" : ""}>
                    <td className="hc-dim">{item.dimension}</td>
                    <td className="hc-before">{item.before_desc}</td>
                    <td className="hc-after">{item.after_desc}</td>
                    <td className="hc-trend" data-trend={item.trend}>
                      {trendIcon(item.trend)}
                    </td>
                    <td className="hc-conclusion">{item.conclusion}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
