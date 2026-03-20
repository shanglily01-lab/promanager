import { useEffect, useMemo, useState } from "react";
import type { CommitItem, HabitsSummary } from "../api";
import { getJson } from "../api";
import { RepoSourceBadge } from "../components/RepoSourceBadge";

type Props = { onError: (msg: string | null) => void };

export function EmployeeTab({ onError }: Props) {
  const [empLogin, setEmpLogin] = useState("");
  const [empFrom, setEmpFrom] = useState("");
  const [empTo, setEmpTo] = useState("");
  const [empCommits, setEmpCommits] = useState<CommitItem[] | null>(null);
  const [empHabits, setEmpHabits] = useState<HabitsSummary | null>(null);
  const [employeeKeyOptions, setEmployeeKeyOptions] = useState<{ key: string; label: string }[]>([]);
  const [empKeySelectNonce, setEmpKeySelectNonce] = useState(0);

  useEffect(() => {
    getJson<{
      employee_key_options?: { key: string; label: string }[];
      employee_keys?: string[];
    }>("/api/employees")
      .then((j) => {
        if (j.employee_key_options?.length) {
          setEmployeeKeyOptions(j.employee_key_options);
        } else {
          setEmployeeKeyOptions((j.employee_keys ?? []).map((k) => ({ key: k, label: k })));
        }
      })
      .catch(() => setEmployeeKeyOptions([]));
  }, []);

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

  const maxHour = useMemo(() => {
    if (!empHabits) return 1;
    return Math.max(1, ...Object.values(empHabits.commits_by_hour_utc));
  }, [empHabits]);

  return (
    <section className="card tab-panel" aria-labelledby="employee-heading">
      <h2 id="employee-heading">单人：提交列表与习惯</h2>
      <p className="card-hint">
        主键与日报一致。下方可先<strong>按成员昵称</strong>选择（实际仍使用内部主键查询）；也可在输入框中直接填写{" "}
        <code>GitHub登录</code>、<code>email:邮箱</code>、<code>contrib:档案ID</code>、<code>_unknown</code>。
      </p>
      <div className="row row--employee-filters">
        <label className="field-key">
          报表主键
          <div className="key-row">
            <select
              key={empKeySelectNonce}
              aria-label="按成员名称选择"
              defaultValue=""
              onChange={(e) => {
                const v = e.target.value;
                if (v) {
                  setEmpLogin(v);
                  setEmpKeySelectNonce((n) => n + 1);
                }
              }}
              className="select-key"
            >
              <option value="">按名称选择…</option>
              {employeeKeyOptions.map((o) => (
                <option key={o.key} value={o.key}>
                  {o.label}
                </option>
              ))}
            </select>
            <input
              className="input-key"
              value={empLogin}
              onChange={(e) => setEmpLogin(e.target.value)}
              placeholder="或输入主键，如 zhangsan / email:a@b.com"
              list="employee-key-hints"
            />
          </div>
        </label>
        <datalist id="employee-key-hints">
          {employeeKeyOptions.map((o) => (
            <option key={o.key} value={o.key} label={o.label} />
          ))}
        </datalist>
        <label>
          从
          <input type="date" value={empFrom} onChange={(e) => setEmpFrom(e.target.value)} />
        </label>
        <label>
          到
          <input type="date" value={empTo} onChange={(e) => setEmpTo(e.target.value)} />
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
                  : " · 尚无文件级画像（需开启同步时的详情拉取并重新同步新提交）"}
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
    </section>
  );
}
