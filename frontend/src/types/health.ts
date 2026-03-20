/** /api/health 响应（与后端字段对齐） */
export type HealthState = {
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
};
