-- 100_job_failures.sql — per-job consecutive-failure streaks (ops-hardening #4)
CREATE TABLE IF NOT EXISTS uw_scan.job_failures (
    job_name        text PRIMARY KEY,
    consecutive     integer     NOT NULL DEFAULT 0,
    last_error      text,
    last_failed_at  timestamptz,
    last_success_at timestamptz,
    updated_at      timestamptz NOT NULL DEFAULT now()
);
