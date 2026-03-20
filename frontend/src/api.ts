const base = "";

async function formatApiError(r: Response): Promise<string> {
  const text = await r.text();
  try {
    const j = JSON.parse(text) as { detail?: unknown };
    if (typeof j.detail === "string") return `${r.status} ${j.detail}`;
    if (Array.isArray(j.detail)) {
      const parts = j.detail.map((x: { msg?: string; loc?: unknown }) => x.msg || JSON.stringify(x));
      return `${r.status} ${parts.join("; ")}`;
    }
  } catch {
    /* 非 JSON */
  }
  return `${r.status} ${text.slice(0, 400)}`;
}

export async function getJson<T>(path: string): Promise<T> {
  const r = await fetch(`${base}${path}`);
  if (!r.ok) throw new Error(await formatApiError(r));
  return r.json() as Promise<T>;
}

export async function postJson<T>(path: string, body: unknown): Promise<T> {
  const r = await fetch(`${base}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!r.ok) throw new Error(await formatApiError(r));
  return r.json() as Promise<T>;
}

/** POST + SSE（data: JSON 行），用于同步进度 */
export async function postSyncStream(
  path: string,
  body: unknown,
  onEvent: (ev: Record<string, unknown>) => void
): Promise<void> {
  const r = await fetch(`${base}${path}`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Accept: "text/event-stream",
    },
    body: JSON.stringify(body),
  });
  if (!r.ok) throw new Error(await formatApiError(r));
  const reader = r.body?.getReader();
  if (!reader) throw new Error("响应无 body，无法读取进度流");
  const dec = new TextDecoder();
  let buffer = "";
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += dec.decode(value, { stream: true });
    const blocks = buffer.split("\n\n");
    buffer = blocks.pop() ?? "";
    for (const block of blocks) {
      for (const line of block.split("\n")) {
        if (line.startsWith("data: ")) {
          try {
            onEvent(JSON.parse(line.slice(6)) as Record<string, unknown>);
          } catch {
            /* 单行非 JSON 忽略 */
          }
        }
      }
    }
  }
}

export async function patchJson<T>(path: string, body: unknown): Promise<T> {
  const r = await fetch(`${base}${path}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!r.ok) throw new Error(await formatApiError(r));
  return r.json() as Promise<T>;
}

export async function putJson<T>(path: string, body: unknown): Promise<T> {
  const r = await fetch(`${base}${path}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!r.ok) throw new Error(await formatApiError(r));
  return r.json() as Promise<T>;
}

export async function deleteJson(path: string): Promise<void> {
  const r = await fetch(`${base}${path}`, { method: "DELETE" });
  if (!r.ok) throw new Error(await formatApiError(r));
}

export type EmployeeSummary = {
  login: string;
  display_name: string | null;
  notes: string | null;
  matched_emails: string[];
  github_login: string | null;
  total_commits_in_range: number;
  had_submission: boolean;
  repos_touched: string[];
};

export type CommitItem = {
  sha: string;
  repo_full_name: string;
  author_login: string | null;
  author_email?: string | null;
  committed_at: string;
  message: string;
  html_url: string | null;
};

export type ContributorAliasOut = {
  id: number;
  kind: string;
  value_normalized: string;
};

export type ContributorOut = {
  id: number;
  nickname: string;
  notes: string;
  aliases: ContributorAliasOut[];
};

export type TrackedRepo = {
  id: number;
  full_name: string;
  enabled: boolean;
  notes: string;
  created_at: string;
};

export type HabitsSummary = {
  total_commits: number;
  commits_by_hour_utc: Record<string, number>;
  commits_by_weekday: Record<string, number>;
  avg_message_length: number;
  pct_messages_with_issue_ref: number;
  most_active_hour_utc: number | null;
  most_active_weekday: string | null;
  /** 由 commit 文件级画像 + 提交说明格式启发式生成 */
  style_tags: string[];
  style_language_mix: Record<string, number>;
  commits_with_style_sample: number;
  pct_conventional_commits: number;
  /** 仅根据提交说明汇总的标签 */
  commit_message_tags: string[];
};

export type DailyReport = {
  report_date: string;
  employees: EmployeeSummary[];
  by_employee_commits: Record<string, CommitItem[]>;
};

export type WeeklyReport = {
  week_start: string;
  week_end: string;
  employees: EmployeeSummary[];
  by_employee_commits: Record<string, CommitItem[]>;
  habits: Record<string, HabitsSummary>;
};
