import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  deleteJson,
  getJson,
  patchJson,
  postJson,
  postSyncStream,
  type TrackedRepo,
} from "../api";
import { RepoSourceBadge, repoSource } from "../components/RepoSourceBadge";
import { formatSyncEvent } from "../sync/formatSyncEvent";

type Props = {
  onError: (msg: string | null) => void;
  onHealthReload: () => void;
  awsDefaultRegion?: string | null;
  team: string;
};

export function SyncTab({ onError, onHealthReload, awsDefaultRegion, team }: Props) {
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
      >("/api/sync/logs?limit=5");
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

  const ccRegionPrefilled = useRef(false);
  useEffect(() => {
    const r = awsDefaultRegion?.trim();
    if (r && !ccRegionPrefilled.current) {
      setCcRegion(r);
      ccRegionPrefilled.current = true;
    }
  }, [awsDefaultRegion]);

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
        }>(`/api/config/repos?team=${encodeURIComponent(team)}`),
        getJson<TrackedRepo[]>(`/api/repos?team=${encodeURIComponent(team)}`),
      ]);
      setRepoConfig(cfg);
      setTrackedRepos(list);
    } catch {
      setRepoConfig(null);
      setTrackedRepos([]);
    }
  }, [team]);

  useEffect(() => {
    void refreshSyncData();
    void loadSyncHistory();
  }, [refreshSyncData, loadSyncHistory]);

  const runSyncPost = async (repos: string[]) => {
    onError(null);
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
      await postSyncStream("/api/sync/stream", { repos, since_days: sinceDays, team }, (ev) => {
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
      onHealthReload();
      const finalComplete = completeHolder.ev;
      if (!finalComplete) {
        onError("同步未返回结束状态，请查看后端日志或网络");
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
      onError(String(e));
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
      onError("文本框为空：请填写仓库，或使用上方「同步已配置的全部仓库」。");
      return;
    }
    await runSyncPost(repos);
  };

  const doSyncConfigured = async () => {
    await runSyncPost([]);
  };

  const fetchCodeCommitRepoList = async () => {
    onError(null);
    const r = ccRegion.trim();
    if (!r) {
      onError("请填写 AWS 区域（如 ap-southeast-1），或在 .env 中设置 AWS_DEFAULT_REGION 后刷新页面。");
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
      onError(String(e));
    } finally {
      setCcListing(false);
    }
  };

  const importBulkToDb = async () => {
    onError(null);
    const full_names = repoBulkText
      .split(/[\n\r,;]+/)
      .map((s) => s.trim())
      .filter(Boolean);
    if (!full_names.length) {
      onError("请在文本框中输入至少一个 owner/repo（可每行一个）。");
      return;
    }
    try {
      const res = await postJson<{ added: string[]; skipped: string[]; errors: string[] }>(
        "/api/repos/bulk",
        { full_names, team }
      );
      const parts = [`新增 ${res.added.length} 个`, `跳过重复 ${res.skipped.length} 个`];
      if (res.errors.length) parts.push(`校验失败 ${res.errors.length} 条`);
      setSyncMsg(
        `${parts.join("，")}${res.errors.length ? " — " + res.errors.slice(0, 5).join("; ") : ""}。接下来请点击「同步已配置的全部仓库」才会从远端拉取提交记录。`
      );
      setRepoBulkText("");
      await refreshSyncData();
    } catch (e) {
      onError(String(e));
    }
  };

  const toggleTrackedRepo = async (r: TrackedRepo) => {
    onError(null);
    try {
      await patchJson<TrackedRepo>(`/api/repos/${r.id}`, { enabled: !r.enabled });
      await refreshSyncData();
    } catch (e) {
      onError(String(e));
    }
  };

  const removeTrackedRepo = async (id: number) => {
    if (!confirm("从数据库中删除该仓库？（不影响已同步的提交记录）")) return;
    onError(null);
    try {
      await deleteJson(`/api/repos/${id}`);
      await refreshSyncData();
    } catch (e) {
      onError(String(e));
    }
  };

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
    <section className="card tab-panel" aria-labelledby="sync-heading">
      <h2 id="sync-heading">同步仓库提交</h2>
      <p className="card-hint">
        <strong>「导入到数据库」只保存仓库名单，不会拉取任何提交。</strong>
        导入后必须再点<strong>「同步已配置的全部仓库」</strong>（或同步下方列表），才会写入提交记录。
        <strong>GitHub</strong> 用 <code>GITHUB_TOKEN</code>（私有库建议配置）；<strong>AWS CodeCommit</strong> 用{" "}
        <code>.env</code> 中的 <code>AWS_ACCESS_KEY_ID</code> 等，仓库写{" "}
        <code>cc:区域/仓库名</code> 或 <code>cc:区域/仓库名@分支</code>。
        也可配合 <code>DEFAULT_REPOS</code> / <code>REPOS_FILE</code>，<strong>合并去重</strong>。
      </p>

      <h3 className="section-title">数据库中的仓库</h3>
      <p className="card-hint card-hint--tight">
        每行一个：<code>owner/repo</code>、GitHub 链接，或 CodeCommit{" "}
        <code>cc:ap-southeast-1/my-repo</code> / <code>cc:ap-southeast-1/my-repo@prod</code>。
      </p>
      <div className="toolbar-row">
        <label className="toolbar-label">
          CodeCommit 区域
          <input
            type="text"
            value={ccRegion}
            onChange={(e) => setCcRegion(e.target.value)}
            placeholder="ap-southeast-1"
            spellCheck={false}
            className="input-region"
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
        <span className="inline-hint">使用当前 AWS 凭证调用 ListRepositories（及 BatchGetRepositories 补全描述等，无权限时仅有名称）</span>
      </div>
      {ccCatalog && ccCatalog.repositories.length > 0 && (
        <div className="cc-catalog-panel">
          <div className="cc-catalog-title">
            该区域最近一次列出：{ccCatalog.region} · {ccCatalog.repositories.length} 个（大小写与 AWS 一致，同步依赖此名称）
          </div>
          <div className="cc-catalog-scroll">
            <table className="cc-repo-table sync-table">
              <thead>
                <tr>
                  <th>sync_key</th>
                  <th>说明</th>
                </tr>
              </thead>
              <tbody>
                {ccCatalog.repositories.map((row) => (
                  <tr key={row.sync_key}>
                    <td>
                      <code className="code-tight">{row.sync_key}</code>
                    </td>
                    <td className="muted-cell">
                      {row.description?.trim() || "—"}
                      {row.clone_url_http ? (
                        <div className="cc-catalog-link">
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
          className="textarea-short"
        />
      </label>
      <div className="row row--tight">
        <button type="button" className="primary" onClick={importBulkToDb}>
          导入到数据库
        </button>
      </div>
      {trackedRepos.length > 0 ? (
        <ul className="commit-list repo-list-block">
          {trackedRepos.map((r) => (
            <li key={r.id} className="repo-list-item">
              <RepoSourceBadge fullName={r.full_name} />
              <code>{r.full_name}</code>
              <span className={r.enabled ? "status-on" : "status-off"}>{r.enabled ? "已启用" : "已暂停"}</span>
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
        <p className="card-hint">数据库中暂无仓库，可先批量导入；也可仅依赖 .env / 文件配置。</p>
      )}

      {repoConfig !== null && (
        <div className="merged-config-panel">
          <strong className="merged-config-strong">合并后可用于同步：共 {repoConfig.count} 个仓库</strong>
          <div className="merged-config-meta">
            数据库已启用 {repoConfig.database_enabled_count ?? 0} 个 · 配置文件中有 {repoConfig.config_count ?? 0}{" "}
            个（去重后见下方列表）
            <span className="merged-config-breakdown">
              · 合并列表中 <strong>GitHub {mergedRepoBreakdown.gh}</strong> 个、
              <strong>CodeCommit {mergedRepoBreakdown.cc}</strong> 个
            </span>
          </div>
          {repoConfig.repos_file && (
            <>
              {" "}
              · 列表文件 <code>{repoConfig.repos_file}</code>
              {repoConfig.repos_file_exists ? (
                <span className="file-ok">（存在）</span>
              ) : (
                <span className="file-warn">（文件不存在，请创建或检查 REPOS_FILE）</span>
              )}
            </>
          )}
          <div className="row row--merged-actions">
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
          placeholder={"GitHub：org/repo 或链接\nCodeCommit：cc:ap-southeast-1/my-repo 或 cc:region/repo@branch"}
          spellCheck={false}
        />
      </label>
      {(syncing || syncLines.length > 0) && (
        <div className="sync-progress">
          <div className="sync-progress-head">
            {syncing ? <span className="sync-live">正在同步…</span> : <span>上次同步过程</span>}
            <span>已用时 {syncElapsedSec}s</span>
            {syncBar && syncing && syncBar.total > 0 ? (
              <span>
                拉取进度：{syncBar.current}/{syncBar.total} 个仓库
              </span>
            ) : null}
          </div>
          {syncBar && syncing && syncBar.total > 0 ? (
            <div className="sync-progress-bar">
              <div style={{ width: `${Math.min(100, (100 * syncBar.current) / Math.max(1, syncBar.total))}%` }} />
            </div>
          ) : null}
          {syncing ? <p className="sync-wait-hint">单个大库或 GitHub 限流时，某一仓库可能停留较久；下方日志会持续更新，请勿关闭页面。</p> : null}
          {syncLines.length > 0 ? <pre className="sync-progress-log">{syncLines.join("\n")}</pre> : null}
        </div>
      )}
      <div className="row row--actions">
        <button type="button" className="primary" disabled={syncing} onClick={doSync}>
          {syncing ? "同步中…" : "同步下方列表中的仓库"}
        </button>
        {syncMsg && <span className="inline-msg">{syncMsg}</span>}
      </div>

      <h3 className="section-title section-title--spaced">最近同步记录（全站共享）</h3>
      <p className="card-hint card-hint--tight">
        上面的「滚动日志」只在你<strong>当前浏览器</strong>里，通过<strong>单次同步的实时连接</strong>推送，别人看不到。
        下表来自服务器数据库，所有访问<strong>同一套后端</strong>的同事都能看到每次同步的摘要。
      </p>
      <div className="row row--tight">
        <button type="button" className="ghost" disabled={syncing} onClick={() => void loadSyncHistory()}>
          刷新同步记录
        </button>
      </div>
      {syncHistory.length === 0 ? (
        <p className="card-hint">暂无记录；至少完整跑过一次同步后会出现。</p>
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
                        r.status === "ok" ? "pill ok" : r.status === "error" || r.status === "partial" ? "pill warn" : "pill"
                      }
                    >
                      {r.status}
                    </span>
                  </td>
                  <td>{r.repo_count}</td>
                  <td>{r.commits_fetched}</td>
                  <td className="cell-ellipsis" title={r.error_preview || undefined}>
                    {r.error_preview || "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
