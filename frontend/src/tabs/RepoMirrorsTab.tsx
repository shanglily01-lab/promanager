import { useCallback, useEffect, useState } from "react";
import { getJson, postJson } from "../api";
import { RepoSourceBadge } from "../components/RepoSourceBadge";

export type RepoMirrorItem = {
  full_name: string;
  status: string;
  detail: string;
  local_rel_path: string;
  updated_at: string | null;
};

type CenterResponse = {
  mirror_root: string;
  git_available: boolean;
  aws_cli_available: boolean;
  scan_in_progress: boolean;
  items: RepoMirrorItem[];
};

type Props = { onError: (msg: string | null) => void; team: string };

function statusClass(s: string): string {
  if (s === "ok") return "mirror-ok";
  if (s === "error") return "mirror-err";
  if (s === "skipped") return "mirror-skip";
  if (s === "pending") return "mirror-pending";
  return "";
}

export function RepoMirrorsTab({ onError, team }: Props) {
  const [data, setData] = useState<CenterResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [scanning, setScanning] = useState(false);

  const load = useCallback(async () => {
    onError(null);
    setLoading(true);
    try {
      const j = await getJson<CenterResponse>(`/api/repo-mirrors?team=${encodeURIComponent(team)}`);
      setData(j);
      setScanning(j.scan_in_progress);
    } catch (e) {
      setData(null);
      onError(String(e));
    } finally {
      setLoading(false);
    }
  }, [onError, team]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    if (!data?.scan_in_progress) return;
    const t = setInterval(() => void load(), 2500);
    return () => clearInterval(t);
  }, [data?.scan_in_progress, load]);

  const startScan = async (repos?: string[]) => {
    onError(null);
    try {
      await postJson<{ started: boolean }>("/api/repo-mirrors/scan", { repos: repos ?? [], team });
      setScanning(true);
      await load();
    } catch (e) {
      onError(String(e));
    }
  };

  const okCount = data?.items.filter((i) => i.status === "ok").length ?? 0;
  const errCount = data?.items.filter((i) => i.status === "error").length ?? 0;

  return (
    <div>
      <div className="page-header">
        <h2 className="page-title">仓库中心</h2>
      </div>

      <div className="row row--mirror-actions">
        <button type="button" className="primary" disabled={loading || scanning} onClick={() => startScan()}>
          {scanning ? "拉取任务进行中…" : "检测并拉取全部仓库"}
        </button>
        <button type="button" className="ghost" disabled={loading} onClick={() => void load()}>
          刷新列表
        </button>
      </div>

      {data && (
        <div className="mirror-meta">
          <div>
            <strong>镜像根目录</strong> <code className="code-inline">{data.mirror_root}</code>
          </div>
          <div className="mirror-flags">
            <span className={data.git_available ? "yes" : "no"}>git: {data.git_available ? "可用" : "未找到"}</span>
            <span className={data.aws_cli_available ? "yes" : "muted"}>
              aws CLI: {data.aws_cli_available ? "可用" : "未找到"}
            </span>
            <span>
              统计：共 {data.items.length} 个 · <span className="mirror-ok">成功 {okCount}</span> ·{" "}
              <span className="mirror-err">失败 {errCount}</span>
            </span>
          </div>
        </div>
      )}

      {loading && !data ? <p className="card-hint">加载中…</p> : null}

      {data && data.items.length === 0 ? (
        <p className="card-hint">当前合并列表为空。请先在「同步仓库」中导入仓库或配置 DEFAULT_REPOS。</p>
      ) : null}

      {data && data.items.length > 0 ? (
        <div className="table-wrap mirror-table-wrap">
          <table className="mirror-table">
            <thead>
              <tr>
                <th>仓库</th>
                <th>状态</th>
                <th className="mobile-hide">相对路径</th>
                <th className="mobile-hide">说明 / 错误</th>
                <th className="mobile-hide">更新时间</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {data.items.map((row) => (
                <tr key={row.full_name}>
                  <td>
                    <span className="badge-inline">
                      <RepoSourceBadge fullName={row.full_name} />
                    </span>{" "}
                    <code className="code-inline">{row.full_name}</code>
                  </td>
                  <td>
                    <span className={`mirror-status ${statusClass(row.status)}`}>{row.status}</span>
                  </td>
                  <td className="mobile-hide">
                    <code className="code-inline code-tiny">{row.local_rel_path}</code>
                  </td>
                  <td className="mirror-detail mobile-hide">{row.detail || "—"}</td>
                  <td className="mirror-time mobile-hide">{row.updated_at ? row.updated_at.slice(0, 19).replace("T", " ") : "—"}</td>
                  <td>
                    <button
                      type="button"
                      className="linkish"
                      disabled={scanning}
                      onClick={() => startScan([row.full_name])}
                    >
                      仅拉此项
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
    </div>
  );
}
