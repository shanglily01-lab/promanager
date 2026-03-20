import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  type ContributorOut,
  type DailyReport,
  type TrackedRepo,
  type WeeklyReport,
  deleteJson,
  getJson,
  patchJson,
  postJson,
  postSyncStream,
  putJson,
} from "./api";

function formatSyncEvent(ev: Record<string, unknown>): string | null {
  const p = ev.phase;
  if (typeof p !== "string") return null;
  switch (p) {
    case "start":
      return `开始：共 ${ev.total_repos} 个仓库，回溯 ${ev.since_days} 天`;
    case "repo_fetch_start":
      return `[${ev.index}/${ev.total}] 拉取 ${String(ev.repo)}（${ev.kind === "codecommit" ? "CodeCommit" : "GitHub"}）…`;
    case "repo_fetch_done": {
      const raw = typeof ev.raw_commits === "number" ? `（API 返回 ${ev.raw_commits} 条）` : "";
      return `  → 窗口内有效提交 ${ev.commits} 条${raw}`;
    }
    case "fetch_done": {
      const sk = typeof ev.skipped_repos === "number" && ev.skipped_repos > 0 ? `（已跳过 ${ev.skipped_repos} 个失败仓库）` : "";
      return `拉取结束：缓冲 ${ev.commits_buffered} 条，写入数据库…${sk}`;
    }
    case "write_start":
      return `写入：最多扫描 ${ev.total_to_scan} 条记录…`;
    case "write_progress":
      return `  …新增 ${ev.new_commits} 条，已扫描 ${ev.processed}/${ev.of}`;
    case "provision_start":
      return `检查并自动创建成员档案…`;
    case "provision_done":
      return `  → 新建成员档案 ${ev.contributors_created} 人`;
    case "repo_fetch_error":
      return `  ✗ 跳过 ${String(ev.repo)}：${String(ev.message || "").slice(0, 240)}`;
    case "complete":
      return null;
    default:
      return JSON.stringify(ev);
  }
}

type Tab = "sync" | "daily" | "weekly" | "employee" | "contributors";

function todayISO() {
  return new Date().toISOString().slice(0, 10);
}

function mondayISO(d: Date = new Date()) {
  const day = d.getUTCDay();
  const diff = (day + 6) % 7;
  const mon = new Date(Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), d.getUTCDate() - diff));
  return mon.toISOString().slice(0, 10);
}

/** 以 full_name 是否 cc: 前缀区分 CodeCommit / GitHub */
function repoSource(fullName: string): "cc" | "gh" {
  return fullName.trim().toLowerCase().startsWith("cc:") ? "cc" : "gh";
}

function RepoSourceBadge({ fullName }: { fullName: string }) {
  const src = repoSource(fullName);
  return (
    <span
      className={`pill ${src === "cc" ? "warn" : "ok"}`}
      style={{ fontSize: "0.72rem", padding: "0.12rem 0.45rem", fontWeight: 600 }}
      title={src === "cc" ? "AWS CodeCommit（.env 配 AWS 密钥）" : "GitHub（可选 GITHUB_TOKEN）"}
    >
      {src === "cc" ? "CodeCommit" : "GitHub"}
    </span>
  );
}

export default function App() {
  const [tab, setTab] = useState<Tab>("sync");
  const [health, setHealth] = useState<{
    ok: boolean;
    has_token: boolean;
    database_ready?: boolean;
    database_error?: string | null;
    commit_count?: number | null;
    aws_default_region?: string | null;
    background_sync?: {
      enabled: boolean;
      interval_hours: number;
      since_days: number;
      initial_delay_seconds?: number;
      last_run_at?: string | null;
      last_ok?: boolean | null;
      last_detail?: string | null;
    };
  } | null>(null);
  const [err, setErr] = useState<string | null>(null);

  const [reposInput, setReposInput] = useState("octocat/Hello-World");
  const [sinceDays, setSinceDays] = useState(15);
  const [syncMsg, setSyncMsg] = useState<string | null>(null);
  const [syncing, setSyncing] = useState(false);
  const [syncLines, setSyncLines] = useState<string[]>([]);
  const [syncElapsedSec, setSyncElapsedSec] = useState(0);
  const [syncBar, setSyncBar] = useState<{ current: number; total: number } | null>(null);
  const [syncHistory, setSyncHistory] = useState<
    {
      id: number;
      started_at: string;
      finished_at: string | null;
      status: string;
      commits_fetched: number;
      repo_count: number;
      error_preview: string | null;
    }[]
  >([]);

  const loadSyncHistory = useCallback(async () => {
    try {
      const rows = await getJson<
        {
          id: number;
          started_at: string;
          finished_at: string | null;
          status: string;
          commits_fetched: number;
          repo_count: number;
          error_preview: string | null;
        }[]
      >("/api/sync/logs?limit=25");
      setSyncHistory(rows);
    } catch {
      setSyncHistory([]);
    }
  }, []);
  const [repoConfig, setRepoConfig] = useState<{
    count: number;
    repos: string[];
    database_enabled_count: number;
    config_count: number;
    repos_file: string | null;
    repos_file_exists: boolean;
  } | null>(null);
  const [trackedRepos, setTrackedRepos] = useState<TrackedRepo[]>([]);
  const [repoBulkText, setRepoBulkText] = useState("");
  const [ccRegion, setCcRegion] = useState("");
  const [ccListing, setCcListing] = useState(false);
  const [ccCatalog, setCcCatalog] = useState<{
    region: string;
    repositories: {
      sync_key: string;
      repository_name: string;
      repository_id?: string | null;
      description?: string | null;
      clone_url_http?: string | null;
      last_modified?: string | null;
    }[];
  } | null>(null);

  const [dailyDate, setDailyDate] = useState(todayISO);
  const [daily, setDaily] = useState<DailyReport | null>(null);
  const [dailyMd, setDailyMd] = useState<string | null>(null);

  const [weekStart, setWeekStart] = useState(mondayISO);
  const [weekly, setWeekly] = useState<WeeklyReport | null>(null);
  const [weeklyMd, setWeeklyMd] = useState<string | null>(null);

  const [empLogin, setEmpLogin] = useState("");
  const [empFrom, setEmpFrom] = useState("");
  const [empTo, setEmpTo] = useState("");
  const [empCommits, setEmpCommits] = useState<import("./api").CommitItem[] | null>(null);
  const [empHabits, setEmpHabits] = useState<import("./api").HabitsSummary | null>(null);
  const [employeeKeyOptions, setEmployeeKeyOptions] = useState<{ key: string; label: string }[]>([]);
  const [empKeySelectNonce, setEmpKeySelectNonce] = useState(0);

  const [contributors, setContributors] = useState<ContributorOut[]>([]);
  const [contribNick, setContribNick] = useState("");
  const [contribNotes, setContribNotes] = useState("");
  const [contribEmails, setContribEmails] = useState("");
  const [contribLogins, setContribLogins] = useState("");
  const [editingContribId, setEditingContribId] = useState<number | null>(null);

  const loadHealth = useCallback(() => {
    getJson<{
      ok: boolean;
      has_token: boolean;
      database_ready?: boolean;
      database_error?: string | null;
      commit_count?: number | null;
      aws_default_region?: string | null;
      background_sync?: {
        enabled: boolean;
        interval_hours: number;
        since_days: number;
        initial_delay_seconds?: number;
        last_run_at?: string | null;
        last_ok?: boolean | null;
        last_detail?: string | null;
      };
    }>("/api/health")
      .then(setHealth)
      .catch(() => setHealth(null));
  }, []);

  useEffect(() => {
    loadHealth();
  }, [loadHealth]);

  const ccRegionPrefilled = useRef(false);
  useEffect(() => {
    const r = health?.aws_default_region?.trim();
    if (r && !ccRegionPrefilled.current) {
      setCcRegion(r);
      ccRegionPrefilled.current = true;
    }
  }, [health?.aws_default_region]);

  useEffect(() => {
    if (tab !== "contributors") return;
    getJson<ContributorOut[]>("/api/contributors")
      .then(setContributors)
      .catch(() => setContributors([]));
  }, [tab]);

  useEffect(() => {
    if (tab !== "employee") return;
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
  }, [tab]);

  const refreshSyncData = useCallback(async () => {
    try {
      const [cfg, list] = await Promise.all([
        getJson<{
          count: number;
          repos: string[];
          database_enabled_count: number;
          config_count: number;
          repos_file: string | null;
          repos_file_exists: boolean;
        }>("/api/config/repos"),
        getJson<TrackedRepo[]>("/api/repos"),
      ]);
      setRepoConfig(cfg);
      setTrackedRepos(list);
    } catch {
      setRepoConfig(null);
      setTrackedRepos([]);
    }
  }, []);

  useEffect(() => {
    if (tab !== "sync") return;
    void refreshSyncData();
    void loadSyncHistory();
  }, [tab, refreshSyncData, loadSyncHistory]);

  const runSyncPost = async (repos: string[]) => {
    setErr(null);
    setSyncMsg(null);
    setSyncLines([]);
    setSyncBar(null);
    setSyncElapsedSec(0);
    setSyncing(true);
    const started = Date.now();
    const tick = window.setInterval(() => {
      setSyncElapsedSec(Math.floor((Date.now() - started) / 1000));
    }, 400);
    const completeHolder: { ev: Record<string, unknown> | null } = { ev: null };
    try {
      await postSyncStream("/api/sync/stream", { repos, since_days: sinceDays }, (ev) => {
        if (ev.phase === "complete") {
          completeHolder.ev = ev;
          const ok = ev.ok === true;
          const st = String(ev.sync_status || (ok ? "ok" : "error"));
          const n = Number(ev.commits_fetched) || 0;
          const nc = Number(ev.contributors_created) || 0;
          const tail = ok
            ? st === "partial"
              ? `新提交 ${n} 条${nc > 0 ? `，新建档案 ${nc} 人` : ""}（部分仓库失败，见上文 ✗ 行）`
              : `新提交 ${n} 条${nc > 0 ? `，新建档案 ${nc} 人` : ""}`
            : `失败：${String(ev.message || "未知错误")}`;
          const label = !ok ? "失败" : st === "partial" ? "部分成功" : "成功";
          setSyncLines((prev) => [...prev.slice(-79), `—— 结束（${label}）${tail} ——`]);
          return;
        }
        if (ev.phase === "repo_fetch_start") {
          setSyncBar({
            current: Number(ev.index) || 0,
            total: Number(ev.total) || 1,
          });
        }
        const line = formatSyncEvent(ev);
        if (line) setSyncLines((prev) => [...prev.slice(-79), line]);
      });
      void loadHealth();
      const finalComplete = completeHolder.ev;
      if (!finalComplete) {
        setErr("同步未返回结束状态，请查看后端日志或网络");
        return;
      }
      const ok = finalComplete.ok === true;
      const syncSt = String(finalComplete.sync_status || (ok ? "ok" : "error"));
      const msg = finalComplete.message != null ? String(finalComplete.message) : null;
      const n = Number(finalComplete.commits_fetched) || 0;
      const nc = Number(finalComplete.contributors_created) || 0;
      const extra = nc > 0 ? `，新建成员档案 ${nc} 人` : "";
      const partialNote = syncSt === "partial" && msg ? ` ${msg}` : "";
      if (!ok) {
        setSyncMsg(msg || "同步失败");
      } else if (n === 0) {
        setSyncMsg(
          `已同步完成，但最近「回溯天数」内没有新的提交可写入（可能都已存在，或该时段无提交）。可加大回溯天数后重试；若从未拉取过，请确认已点「同步」而非仅「导入到数据库」。${extra}${partialNote}`
        );
      } else {
        setSyncMsg(
          syncSt === "partial"
            ? `已写入 ${n} 条新提交${extra}。注意：${msg || "部分仓库未拉取"}`
            : `已写入 ${n} 条新提交${extra}`
        );
      }
      await refreshSyncData();
    } catch (e) {
      setErr(String(e));
    } finally {
      window.clearInterval(tick);
      setSyncing(false);
      setSyncBar(null);
      void loadSyncHistory();
    }
  };

  const doSync = async () => {
    const repos = reposInput
      .split(/[\n,;]+/)
      .map((s) => s.trim())
      .filter(Boolean);
    if (repos.length === 0) {
      setErr("文本框为空：请填写仓库，或使用上方「同步已配置的全部仓库」。");
      return;
    }
    await runSyncPost(repos);
  };

  const doSyncConfigured = async () => {
    await runSyncPost([]);
  };

  const fetchCodeCommitRepoList = async () => {
    setErr(null);
    const r = ccRegion.trim();
    if (!r) {
      setErr("请填写 AWS 区域（如 ap-southeast-1），或在 .env 中设置 AWS_DEFAULT_REGION 后刷新页面。");
      return;
    }
    setCcListing(true);
    try {
      const j = await getJson<{
        region: string;
        count: number;
        sync_keys: string[];
        repositories?: {
          sync_key: string;
          repository_name: string;
          repository_id?: string | null;
          description?: string | null;
          clone_url_http?: string | null;
          last_modified?: string | null;
        }[];
      }>(`/api/codecommit/repos?region=${encodeURIComponent(r)}`);
      const block = j.sync_keys.join("\n");
      setRepoBulkText((prev) => (prev.trim() ? `${prev.trim()}\n${block}` : block));
      setCcCatalog({
        region: j.region,
        repositories: j.repositories ?? [],
      });
      setSyncMsg(
        `已从 CodeCommit 列出 ${j.count} 个仓库并写入下方「批量导入」文本框，可删改后点「导入到数据库」。`
      );
    } catch (e) {
      setErr(String(e));
    } finally {
      setCcListing(false);
    }
  };

  const importBulkToDb = async () => {
    setErr(null);
    const full_names = repoBulkText
      .split(/[\n\r,;]+/)
      .map((s) => s.trim())
      .filter(Boolean);
    if (!full_names.length) {
      setErr("请在文本框中输入至少一个 owner/repo（可每行一个）。");
      return;
    }
    try {
      const res = await postJson<{ added: string[]; skipped: string[]; errors: string[] }>(
        "/api/repos/bulk",
        { full_names }
      );
      const parts = [`新增 ${res.added.length} 个`, `跳过重复 ${res.skipped.length} 个`];
      if (res.errors.length) parts.push(`校验失败 ${res.errors.length} 条`);
      setSyncMsg(
        `${parts.join("，")}${res.errors.length ? " — " + res.errors.slice(0, 5).join("; ") : ""}。接下来请点击「同步已配置的全部仓库」才会从远端拉取提交记录。`
      );
      setRepoBulkText("");
      await refreshSyncData();
    } catch (e) {
      setErr(String(e));
    }
  };

  const toggleTrackedRepo = async (r: TrackedRepo) => {
    setErr(null);
    try {
      await patchJson<TrackedRepo>(`/api/repos/${r.id}`, { enabled: !r.enabled });
      await refreshSyncData();
    } catch (e) {
      setErr(String(e));
    }
  };

  const removeTrackedRepo = async (id: number) => {
    if (!confirm("从数据库中删除该仓库？（不影响已同步的提交记录）")) return;
    setErr(null);
    try {
      await deleteJson(`/api/repos/${id}`);
      await refreshSyncData();
    } catch (e) {
      setErr(String(e));
    }
  };

  const loadDaily = async () => {
    setErr(null);
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
      setErr(String(e));
    }
  };

  const loadWeekly = async () => {
    setErr(null);
    setWeekly(null);
    setWeeklyMd(null);
    try {
      const [j, md] = await Promise.all([
        getJson<WeeklyReport>(
          `/api/reports/weekly?week_start=${encodeURIComponent(weekStart)}`
        ),
        fetch(`/api/reports/weekly.md?week_start=${encodeURIComponent(weekStart)}`).then((r) =>
          r.text()
        ),
      ]);
      setWeekly(j);
      setWeeklyMd(md);
    } catch (e) {
      setErr(String(e));
    }
  };

  const splitLines = (s: string) =>
    s
      .split(/[\n,;]+/)
      .map((x) => x.trim())
      .filter(Boolean);

  const resetContribForm = () => {
    setContribNick("");
    setContribNotes("");
    setContribEmails("");
    setContribLogins("");
    setEditingContribId(null);
  };

  const startEditContributor = (c: ContributorOut) => {
    setEditingContribId(c.id);
    setContribNick(c.nickname);
    setContribNotes(c.notes || "");
    setContribEmails(c.aliases.filter((a) => a.kind === "email").map((a) => a.value_normalized).join("\n"));
    setContribLogins(c.aliases.filter((a) => a.kind === "login").map((a) => a.value_normalized).join("\n"));
  };

  const saveContributor = async () => {
    setErr(null);
    if (!contribNick.trim()) {
      setErr("请填写昵称");
      return;
    }
    const body = {
      nickname: contribNick.trim(),
      notes: contribNotes.trim(),
      emails: splitLines(contribEmails),
      github_logins: splitLines(contribLogins),
    };
    try {
      if (editingContribId != null) {
        await putJson<ContributorOut>(`/api/contributors/${editingContribId}`, body);
      } else {
        await postJson<ContributorOut>("/api/contributors", body);
      }
      const list = await getJson<ContributorOut[]>("/api/contributors");
      setContributors(list);
      resetContribForm();
    } catch (e) {
      setErr(String(e));
    }
  };

  const removeContributor = async (id: number) => {
    if (!confirm("确定删除该成员档案？")) return;
    setErr(null);
    try {
      await deleteJson(`/api/contributors/${id}`);
      setContributors(await getJson<ContributorOut[]>("/api/contributors"));
      if (editingContribId === id) resetContribForm();
    } catch (e) {
      setErr(String(e));
    }
  };

  const loadEmployee = async () => {
    setErr(null);
    setEmpCommits(null);
    setEmpHabits(null);
    if (!empLogin.trim()) {
      setErr("填写报表主键：GitHub 登录、email:邮箱、contrib:档案ID 或 _unknown");
      return;
    }
    const q = new URLSearchParams();
    if (empFrom) q.set("from", empFrom);
    if (empTo) q.set("to", empTo);
    const qs = q.toString();
    const suffix = qs ? `?${qs}` : "";
    try {
      const [c, h] = await Promise.all([
        getJson<import("./api").CommitItem[]>(`/api/employees/${encodeURIComponent(empLogin.trim())}/commits${suffix}`),
        getJson<import("./api").HabitsSummary>(
          `/api/employees/${encodeURIComponent(empLogin.trim())}/habits${suffix}`
        ),
      ]);
      setEmpCommits(c);
      setEmpHabits(h);
    } catch (e) {
      setErr(String(e));
    }
  };

  const maxHour = useMemo(() => {
    if (!empHabits) return 1;
    return Math.max(1, ...Object.values(empHabits.commits_by_hour_utc));
  }, [empHabits]);

  const mergedRepoBreakdown = useMemo(() => {
    if (!repoConfig?.repos?.length) return { gh: 0, cc: 0 };
    let gh = 0;
    let cc = 0;
    for (const r of repoConfig.repos) {
      if (repoSource(r) === "cc") cc += 1;
      else gh += 1;
    }
    return { gh, cc };
  }, [repoConfig]);

  return (
    <>
      <header className="app-header">
        <div>
          <h1>ProManager</h1>
          <p>
            从 <strong>GitHub</strong> 与 <strong>AWS CodeCommit</strong> 同步提交，生成日报 / 周报；支持按邮箱 /
            GitHub 登录绑定昵称与备注，合并同一人多条身份。
          </p>
        </div>
        {health && (
          <div style={{ display: "flex", flexWrap: "wrap", gap: "0.5rem", alignItems: "center" }}>
            <span className={`pill ${health.has_token ? "ok" : "warn"}`}>
              {health.has_token ? "已配置 Token" : "未配置 GITHUB_TOKEN（仅公开库可匿名拉取，速率低）"}
            </span>
            {health.commit_count != null && (
              <span className="pill ok" title="数据库中的提交条数（导入仓库不会增加此项，需同步后才有）">
                已入库提交 {health.commit_count} 条
              </span>
            )}
            {health.background_sync?.enabled && (
              <span
                className="pill ok"
                title={
                  health.background_sync.last_detail
                    ? `上次：${health.background_sync.last_detail}`
                    : "进程内定时任务，与「同步已配置的全部仓库」相同"
                }
              >
                后台每 {health.background_sync.interval_hours}h 同步 · 回溯{" "}
                {health.background_sync.since_days} 天
                {health.background_sync.last_run_at
                  ? ` · 上次 ${health.background_sync.last_ok === false ? "失败" : "完成"}`
                  : ""}
              </span>
            )}
            {health.database_ready === false && (
              <span className="pill warn" title={health.database_error || "请打开 /api/health 查看详情"}>
                数据库未就绪（MySQL 连不上或建表失败）
              </span>
            )}
          </div>
        )}
      </header>

      <nav className="tabs">
        {(
          [
            ["sync", "同步仓库"],
            ["daily", "日报"],
            ["weekly", "周报"],
            ["contributors", "成员档案"],
            ["employee", "成员提交与习惯"],
          ] as const
        ).map(([id, label]) => (
          <button
            key={id}
            type="button"
            className={tab === id ? "active" : ""}
            onClick={() => setTab(id)}
          >
            {label}
          </button>
        ))}
      </nav>

      {err && <p className="err">{err}</p>}

      {tab === "sync" && (
        <section className="card">
          <h2>同步仓库提交</h2>
          <p style={{ color: "var(--muted)", marginTop: 0, fontSize: "0.9rem" }}>
            <strong>「导入到数据库」只保存仓库名单，不会拉取任何提交。</strong>
            导入后必须再点<strong>「同步已配置的全部仓库」</strong>（或同步下方列表），才会写入提交记录。
            <strong>GitHub</strong> 用 <code>GITHUB_TOKEN</code>（私有库建议配置）；<strong>AWS CodeCommit</strong> 用{" "}
            <code>.env</code> 中的 <code>AWS_ACCESS_KEY_ID</code> 等，仓库写{" "}
            <code>cc:区域/仓库名</code> 或 <code>cc:区域/仓库名@分支</code>。
            也可配合 <code>DEFAULT_REPOS</code> / <code>REPOS_FILE</code>，<strong>合并去重</strong>。
          </p>

          <h3 style={{ margin: "1rem 0 0.5rem", fontSize: "1rem" }}>数据库中的仓库</h3>
          <p style={{ color: "var(--muted)", fontSize: "0.85rem", marginTop: 0 }}>
            每行一个：<code>owner/repo</code>、GitHub 链接，或 CodeCommit{" "}
            <code>cc:ap-southeast-1/my-repo</code> / <code>cc:ap-southeast-1/my-repo@prod</code>。
          </p>
          <div
            className="row"
            style={{
              flexWrap: "wrap",
              gap: "0.5rem",
              marginBottom: "0.75rem",
              alignItems: "center",
            }}
          >
            <label style={{ display: "flex", alignItems: "center", gap: "0.35rem", margin: 0 }}>
              CodeCommit 区域
              <input
                type="text"
                value={ccRegion}
                onChange={(e) => setCcRegion(e.target.value)}
                placeholder="ap-southeast-1"
                spellCheck={false}
                style={{ width: "11rem" }}
              />
            </label>
            <button
              type="button"
              className="ghost"
              disabled={ccListing}
              onClick={() => void fetchCodeCommitRepoList()}
            >
              {ccListing ? "拉取中…" : "自动拉取该区域全部仓库"}
            </button>
            <span style={{ color: "var(--muted)", fontSize: "0.82rem" }}>
              使用当前 AWS 凭证调用 ListRepositories（及 BatchGetRepositories 补全描述等，无权限时仅有名称）
            </span>
          </div>
          {ccCatalog && ccCatalog.repositories.length > 0 && (
            <div
              style={{
                marginBottom: "0.75rem",
                padding: "0.6rem 0.75rem",
                background: "var(--surface2)",
                borderRadius: "8px",
                border: "1px solid var(--border)",
                fontSize: "0.82rem",
              }}
            >
              <div style={{ marginBottom: "0.35rem", color: "var(--text)", fontWeight: 600 }}>
                该区域最近一次列出：{ccCatalog.region} · {ccCatalog.repositories.length} 个（大小写与 AWS 一致，同步依赖此名称）
              </div>
              <div style={{ maxHeight: "220px", overflow: "auto" }}>
                <table className="cc-repo-table" style={{ width: "100%", borderCollapse: "collapse" }}>
                  <thead>
                    <tr style={{ textAlign: "left", color: "var(--muted)" }}>
                      <th style={{ padding: "0.2rem 0.4rem" }}>sync_key</th>
                      <th style={{ padding: "0.2rem 0.4rem" }}>说明</th>
                    </tr>
                  </thead>
                  <tbody>
                    {ccCatalog.repositories.map((row) => (
                      <tr key={row.sync_key}>
                        <td style={{ padding: "0.2rem 0.4rem", verticalAlign: "top" }}>
                          <code style={{ fontSize: "0.78rem" }}>{row.sync_key}</code>
                        </td>
                        <td style={{ padding: "0.2rem 0.4rem", color: "var(--muted)", verticalAlign: "top" }}>
                          {row.description?.trim() || "—"}
                          {row.clone_url_http ? (
                            <div style={{ marginTop: "0.2rem" }}>
                              <a href={row.clone_url_http} rel="noreferrer" target="_blank">
                                HTTPS 克隆地址
                              </a>
                            </div>
                          ) : null}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
          <label>
            批量导入到数据库
            <textarea
              value={repoBulkText}
              onChange={(e) => setRepoBulkText(e.target.value)}
              placeholder={
                "每行一个，例如：\nhttps://github.com/org/repo.git\norg/repo\ncc:ap-southeast-1/chain-payment-web\ncc:ap-southeast-1/chain-payment-listener@prod"
              }
              spellCheck={false}
              style={{ minHeight: "100px" }}
            />
          </label>
          <div className="row" style={{ marginBottom: "1rem" }}>
            <button type="button" className="primary" onClick={importBulkToDb}>
              导入到数据库
            </button>
          </div>
          {trackedRepos.length > 0 ? (
            <ul className="commit-list" style={{ marginBottom: "1.25rem" }}>
              {trackedRepos.map((r) => (
                <li
                  key={r.id}
                  style={{
                    display: "flex",
                    flexWrap: "wrap",
                    alignItems: "center",
                    gap: "0.5rem",
                  }}
                >
                  <RepoSourceBadge fullName={r.full_name} />
                  <code>{r.full_name}</code>
                  <span style={{ color: r.enabled ? "var(--success)" : "var(--warn)", fontSize: "0.8rem" }}>
                    {r.enabled ? "已启用" : "已暂停"}
                  </span>
                  <button type="button" className="ghost" onClick={() => void toggleTrackedRepo(r)}>
                    {r.enabled ? "暂停" : "启用"}
                  </button>
                  <button type="button" className="ghost" onClick={() => void removeTrackedRepo(r.id)}>
                    删除
                  </button>
                </li>
              ))}
            </ul>
          ) : (
            <p style={{ color: "var(--muted)", fontSize: "0.9rem", marginBottom: "1.25rem" }}>
              数据库中暂无仓库，可先批量导入；也可仅依赖 .env / 文件配置。
            </p>
          )}

          {repoConfig !== null && (
            <div
              style={{
                marginBottom: "1rem",
                padding: "0.75rem 1rem",
                background: "var(--surface2)",
                borderRadius: "10px",
                border: "1px solid var(--border)",
                fontSize: "0.9rem",
                color: "var(--muted)",
              }}
            >
              <strong style={{ color: "var(--text)" }}>合并后可用于同步：共 {repoConfig.count} 个仓库</strong>
              <div style={{ marginTop: "0.35rem" }}>
                数据库已启用 {repoConfig.database_enabled_count ?? 0} 个 · 配置文件中有{" "}
                {repoConfig.config_count ?? 0} 个（去重后见下方列表）
                <span style={{ marginLeft: "0.35rem" }}>
                  · 合并列表中 <strong>GitHub {mergedRepoBreakdown.gh}</strong> 个、
                  <strong>CodeCommit {mergedRepoBreakdown.cc}</strong> 个
                </span>
              </div>
              {repoConfig.repos_file && (
                <>
                  {" "}
                  · 列表文件 <code>{repoConfig.repos_file}</code>
                  {repoConfig.repos_file_exists ? (
                    <span style={{ color: "var(--success)" }}>（存在）</span>
                  ) : (
                    <span style={{ color: "var(--warn)" }}>（文件不存在，请创建或检查 REPOS_FILE）</span>
                  )}
                </>
              )}
              <div className="row" style={{ marginTop: "0.75rem", marginBottom: 0 }}>
                <button
                  type="button"
                  className="ghost"
                  disabled={syncing || repoConfig.count === 0}
                  onClick={() => setReposInput(repoConfig.repos.join("\n"))}
                >
                  填入下方文本框
                </button>
                <button
                  type="button"
                  className="primary"
                  disabled={syncing || repoConfig.count === 0}
                  onClick={doSyncConfigured}
                >
                  {syncing ? "同步中…" : `同步已配置的全部 ${repoConfig.count} 个仓库`}
                </button>
              </div>
            </div>
          )}
          <div className="row">
            <label>
              回溯天数（默认 15；GitHub 按 API 时间过滤；CodeCommit 沿默认/指定分支第一父链回溯；后台定时同步用 .env
              DEFAULT_SINCE_DAYS）
              <input
                type="number"
                min={1}
                max={365}
                value={sinceDays}
                onChange={(e) => setSinceDays(Number(e.target.value))}
              />
            </label>
          </div>
          <label>
            仓库列表（手动覆盖；留空并点「同步已配置」则用服务器列表）
            <textarea
              value={reposInput}
              onChange={(e) => setReposInput(e.target.value)}
              placeholder={
                "GitHub：org/repo 或链接\nCodeCommit：cc:ap-southeast-1/my-repo 或 cc:region/repo@branch"
              }
              spellCheck={false}
            />
          </label>
          {(syncing || syncLines.length > 0) && (
            <div className="sync-progress">
              <div className="sync-progress-head">
                {syncing ? (
                  <span style={{ color: "var(--accent)", fontWeight: 600 }}>正在同步…</span>
                ) : (
                  <span>上次同步过程</span>
                )}
                <span>已用时 {syncElapsedSec}s</span>
                {syncBar && syncing && syncBar.total > 0 ? (
                  <span>
                    拉取进度：{syncBar.current}/{syncBar.total} 个仓库
                  </span>
                ) : null}
              </div>
              {syncBar && syncing && syncBar.total > 0 ? (
                <div className="sync-progress-bar">
                  <div
                    style={{
                      width: `${Math.min(100, (100 * syncBar.current) / Math.max(1, syncBar.total))}%`,
                    }}
                  />
                </div>
              ) : null}
              {syncing ? (
                <p style={{ margin: "0 0 0.35rem", fontSize: "0.8rem", color: "var(--muted)" }}>
                  单个大库或 GitHub 限流时，某一仓库可能停留较久；下方日志会持续更新，请勿关闭页面。
                </p>
              ) : null}
              {syncLines.length > 0 ? (
                <pre className="sync-progress-log">{syncLines.join("\n")}</pre>
              ) : null}
            </div>
          )}
          <div className="row" style={{ marginTop: "1rem" }}>
            <button type="button" className="primary" disabled={syncing} onClick={doSync}>
              {syncing ? "同步中…" : "同步下方列表中的仓库"}
            </button>
            {syncMsg && <span style={{ color: "var(--muted)" }}>{syncMsg}</span>}
          </div>

          <h3 style={{ marginTop: "1.75rem", fontSize: "1rem" }}>最近同步记录（全站共享）</h3>
          <p style={{ color: "var(--muted)", fontSize: "0.85rem", marginTop: 0 }}>
            上面的「滚动日志」只在你<strong>当前浏览器</strong>里，通过<strong>单次同步的实时连接</strong>推送，别人看不到。
            下表来自服务器数据库，所有访问<strong>同一套后端</strong>的同事都能看到每次同步的摘要。
          </p>
          <div className="row" style={{ marginBottom: "0.5rem" }}>
            <button type="button" className="ghost" disabled={syncing} onClick={() => void loadSyncHistory()}>
              刷新同步记录
            </button>
          </div>
          {syncHistory.length === 0 ? (
            <p style={{ color: "var(--muted)", fontSize: "0.9rem" }}>暂无记录；至少完整跑过一次同步后会出现。</p>
          ) : (
            <div className="sync-history-wrap">
              <table className="sync-history-table">
                <thead>
                  <tr>
                    <th>ID</th>
                    <th>开始时间</th>
                    <th>结束</th>
                    <th>状态</th>
                    <th>仓库数</th>
                    <th>新提交</th>
                    <th>备注</th>
                  </tr>
                </thead>
                <tbody>
                  {syncHistory.map((r) => (
                    <tr key={r.id}>
                      <td>{r.id}</td>
                      <td>{new Date(r.started_at).toLocaleString()}</td>
                      <td>{r.finished_at ? new Date(r.finished_at).toLocaleString() : "—"}</td>
                      <td>
                        <span
                          className={
                            r.status === "ok"
                              ? "pill ok"
                              : r.status === "error" || r.status === "partial"
                                ? "pill warn"
                                : "pill"
                          }
                        >
                          {r.status}
                        </span>
                      </td>
                      <td>{r.repo_count}</td>
                      <td>{r.commits_fetched}</td>
                      <td title={r.error_preview || undefined} style={{ maxWidth: "14rem", wordBreak: "break-word" }}>
                        {r.error_preview || "—"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
      )}

      {tab === "daily" && (
        <section className="card">
          <h2>日报（按 UTC 日历日）</h2>
          <p style={{ color: "var(--muted)", marginTop: 0, fontSize: "0.9rem" }}>
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
            <div className="employee-grid" style={{ marginTop: "1rem" }}>
              {daily.employees.map((e) => (
                <div key={e.login} className="employee-card">
                  <h3>
                    <span style={{ fontWeight: 700 }}>{e.display_name || e.login}</span>
                    <span style={{ color: "var(--muted)", fontSize: "0.8rem", fontWeight: 400 }}>
                      {" "}
                      · <code>{e.login}</code>
                    </span>
                    <span className={`badge ${e.had_submission ? "yes" : "no"}`}>
                      {e.had_submission ? "本日有提交" : "本日无提交"}
                    </span>
                    <span style={{ color: "var(--muted)", fontWeight: 400, fontSize: "0.85rem" }}>
                      {e.total_commits_in_range} 次
                    </span>
                  </h3>
                  {e.notes && (
                    <div style={{ fontSize: "0.82rem", color: "var(--muted)" }}>备注：{e.notes}</div>
                  )}
                  {(e.matched_emails?.length ?? 0) > 0 && (
                    <div style={{ fontSize: "0.82rem", color: "var(--muted)" }}>
                      邮箱：{e.matched_emails.join(", ")}
                    </div>
                  )}
                  {e.github_login && (
                    <div style={{ fontSize: "0.82rem", color: "var(--muted)" }}>
                      GitHub：@{e.github_login}
                    </div>
                  )}
                  {e.repos_touched.length > 0 && (
                    <div style={{ fontSize: "0.85rem", color: "var(--muted)" }}>
                      仓库：{e.repos_touched.join(", ")}
                    </div>
                  )}
                  <ul className="commit-list">
                    {(daily.by_employee_commits[e.login] || []).slice(0, 8).map((c) => (
                      <li key={c.sha + c.repo_full_name}>
                        <a href={c.html_url || "#"} target="_blank" rel="noreferrer">
                          {c.sha.slice(0, 7)}
                        </a>{" "}
                        <span style={{ display: "inline-flex", verticalAlign: "middle", marginRight: "0.25rem" }}>
                          <RepoSourceBadge fullName={c.repo_full_name} />
                        </span>
                        <code style={{ fontSize: "0.85em" }}>{c.repo_full_name}</code> —{" "}
                        {c.message.split("\n")[0].slice(0, 100)}
                      </li>
                    ))}
                  </ul>
                </div>
              ))}
            </div>
          )}
          {dailyMd && (
            <details style={{ marginTop: "1rem" }}>
              <summary style={{ cursor: "pointer", color: "var(--muted)" }}>Markdown 原文</summary>
              <pre className="md">{dailyMd}</pre>
            </details>
          )}
        </section>
      )}

      {tab === "weekly" && (
        <section className="card">
          <h2>周报（周一起算，UTC）</h2>
          <p style={{ color: "var(--muted)", marginTop: 0, fontSize: "0.9rem" }}>
            时间范围按 <strong>UTC</strong>；需先同步提交后再点「生成」。
          </p>
          <div className="row">
            <label>
              周起始（周一）
              <input type="date" value={weekStart} onChange={(e) => setWeekStart(e.target.value)} />
            </label>
            <button type="button" className="primary" onClick={loadWeekly}>
              生成
            </button>
          </div>
          {weekly && (
            <div className="employee-grid" style={{ marginTop: "1rem" }}>
              {weekly.employees.map((e) => {
                const h = weekly.habits[e.login];
                return (
                  <div key={e.login} className="employee-card">
                    <h3>
                      <span style={{ fontWeight: 700 }}>{e.display_name || e.login}</span>
                      <span style={{ color: "var(--muted)", fontSize: "0.8rem", fontWeight: 400 }}>
                        {" "}
                        · <code>{e.login}</code>
                      </span>
                      <span className={`badge ${e.had_submission ? "yes" : "no"}`}>
                        {e.had_submission ? "本周有提交" : "本周无提交"}
                      </span>
                    </h3>
                    {e.notes && (
                      <div style={{ fontSize: "0.82rem", color: "var(--muted)" }}>备注：{e.notes}</div>
                    )}
                    {h && h.total_commits > 0 && (
                      <div className="habits-mini">
                        主要活跃(UTC)：{h.most_active_hour_utc ?? "—"} 点 · 最常{" "}
                        {h.most_active_weekday ?? "—"} · 平均说明长度 {h.avg_message_length} · 含 #{" "}
                        {h.pct_messages_with_issue_ref}%
                      </div>
                    )}
                    <ul className="commit-list">
                      {(weekly.by_employee_commits[e.login] || []).slice(0, 6).map((c) => (
                        <li key={c.sha + c.committed_at}>
                          {c.committed_at.slice(0, 10)}{" "}
                          <span style={{ display: "inline-flex", verticalAlign: "middle", marginRight: "0.25rem" }}>
                            <RepoSourceBadge fullName={c.repo_full_name} />
                          </span>
                          <code style={{ fontSize: "0.85em" }}>{c.repo_full_name}</code>{" "}
                          {c.message.split("\n")[0].slice(0, 80)}
                        </li>
                      ))}
                    </ul>
                  </div>
                );
              })}
            </div>
          )}
          {weeklyMd && (
            <details style={{ marginTop: "1rem" }}>
              <summary style={{ cursor: "pointer", color: "var(--muted)" }}>Markdown 原文</summary>
              <pre className="md">{weeklyMd}</pre>
            </details>
          )}
        </section>
      )}

      {tab === "contributors" && (
        <section className="card">
          <h2>成员档案（昵称 / 备注 / 绑定邮箱与 GitHub）</h2>
          <p style={{ color: "var(--muted)", marginTop: 0, fontSize: "0.9rem" }}>
            同一人可绑定多个邮箱与 GitHub 登录；同步后的提交会按<strong>邮箱优先</strong>匹配到档案，报表主键为{" "}
            <code>contrib:编号</code>。未建档案时，仍按 GitHub 登录或 <code>email:地址</code> 分桶。
          </p>
          <div className="row" style={{ alignItems: "stretch" }}>
            <label style={{ flex: "1 1 140px" }}>
              昵称（展示名）
              <input value={contribNick} onChange={(e) => setContribNick(e.target.value)} />
            </label>
          </div>
          <label>
            备注（可选）
            <input value={contribNotes} onChange={(e) => setContribNotes(e.target.value)} />
          </label>
          <label>
            邮箱（每行一个，或逗号分隔）
            <textarea
              value={contribEmails}
              onChange={(e) => setContribEmails(e.target.value)}
              placeholder="zhang@company.com&#10;zhang@gmail.com"
              spellCheck={false}
              style={{ minHeight: "100px" }}
            />
          </label>
          <label>
            GitHub 登录（每行一个，小写）
            <textarea
              value={contribLogins}
              onChange={(e) => setContribLogins(e.target.value)}
              placeholder="zhangsan"
              spellCheck={false}
              style={{ minHeight: "72px" }}
            />
          </label>
          <div className="row">
            <button type="button" className="primary" onClick={saveContributor}>
              {editingContribId != null ? "保存修改" : "新增成员"}
            </button>
            {editingContribId != null && (
              <button type="button" className="ghost" onClick={resetContribForm}>
                取消编辑
              </button>
            )}
          </div>
          <h2 style={{ marginTop: "1.5rem", fontSize: "1.05rem" }}>已有档案</h2>
          <div className="employee-grid">
            {contributors.map((c) => (
              <div key={c.id} className="employee-card">
                <h3 style={{ marginBottom: "0.35rem" }}>
                  {c.nickname}{" "}
                  <code style={{ fontSize: "0.8rem", color: "var(--muted)" }}>contrib:{c.id}</code>
                </h3>
                {c.notes && (
                  <div style={{ fontSize: "0.85rem", color: "var(--muted)" }}>{c.notes}</div>
                )}
                <ul className="commit-list">
                  {c.aliases.map((a) => (
                    <li key={a.id}>
                      {a.kind === "email" ? "邮箱" : "GitHub"} · {a.value_normalized}
                    </li>
                  ))}
                </ul>
                <div className="row" style={{ marginTop: "0.5rem", marginBottom: 0 }}>
                  <button type="button" className="ghost" onClick={() => startEditContributor(c)}>
                    编辑
                  </button>
                  <button type="button" className="ghost" onClick={() => removeContributor(c.id)}>
                    删除
                  </button>
                </div>
              </div>
            ))}
          </div>
          {contributors.length === 0 && (
            <p style={{ color: "var(--muted)" }}>暂无档案，可在上方新增。</p>
          )}
        </section>
      )}

      {tab === "employee" && (
        <section className="card">
          <h2>单人：提交列表与习惯</h2>
          <p style={{ color: "var(--muted)", marginTop: 0, fontSize: "0.9rem" }}>
            主键与日报一致。下方可先<strong>按成员昵称</strong>选择（实际仍使用内部主键查询）；也可在输入框中直接填写{" "}
            <code>GitHub登录</code>、<code>email:邮箱</code>、<code>contrib:档案ID</code>、<code>_unknown</code>。
          </p>
          <div className="row" style={{ alignItems: "flex-end", flexWrap: "wrap" }}>
            <label style={{ flex: "1 1 16rem", minWidth: "12rem" }}>
              报表主键
              <div style={{ display: "flex", flexWrap: "wrap", gap: "0.45rem", marginTop: "0.25rem" }}>
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
                  style={{ flex: "0 1 14rem", minWidth: "11rem", maxWidth: "100%" }}
                >
                  <option value="">按名称选择…</option>
                  {employeeKeyOptions.map((o) => (
                    <option key={o.key} value={o.key}>
                      {o.label}
                    </option>
                  ))}
                </select>
                <input
                  style={{ flex: "1 1 10rem", minWidth: "8rem" }}
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
            <div style={{ marginTop: "1rem" }}>
              <div className="habits-mini">
                区间内共 <strong style={{ color: "var(--text)" }}>{empHabits.total_commits}</strong>{" "}
                次提交 · UTC 小时分布：
              </div>
              <div className="hour-bars" title="UTC 0–23 点">
                {Array.from({ length: 24 }, (_, h) => {
                  const n = empHabits.commits_by_hour_utc[String(h)] || 0;
                  const pct = (n / maxHour) * 100;
                  return <span key={h} style={{ height: `${Math.max(pct, 2)}%` }} />;
                })}
              </div>
            </div>
          )}
          {empCommits && empCommits.length > 0 && (
            <ul className="commit-list" style={{ marginTop: "1rem" }}>
              {empCommits.slice(0, 40).map((c) => (
                <li key={c.sha}>
                  <a href={c.html_url || "#"} target="_blank" rel="noreferrer">
                    {c.sha.slice(0, 7)}
                  </a>{" "}
                  <span style={{ display: "inline-flex", verticalAlign: "middle", marginRight: "0.25rem" }}>
                    <RepoSourceBadge fullName={c.repo_full_name} />
                  </span>
                  {c.committed_at} <code style={{ fontSize: "0.85em" }}>{c.repo_full_name}</code>
                </li>
              ))}
            </ul>
          )}
          {empCommits && empCommits.length === 0 && (
            <p style={{ color: "var(--muted)" }}>该条件下无提交记录。</p>
          )}
        </section>
      )}
    </>
  );
}
