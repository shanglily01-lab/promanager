export function formatSyncEvent(ev: Record<string, unknown>): string | null {
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
      const sk =
        typeof ev.skipped_repos === "number" && ev.skipped_repos > 0
          ? `（已跳过 ${ev.skipped_repos} 个失败仓库）`
          : "";
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
