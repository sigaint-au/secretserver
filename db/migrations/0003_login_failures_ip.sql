-- Additive migration: record client IP on login failures.
--
-- lockout.record_failure() stores the client IP alongside the email so the
-- admin sign-in-failures browser can show brute-force patterns per IP.
-- The admin audit purge already deletes private.login_failures rows, so no
-- retention handling is needed here.
-- Idempotent: safe to re-run.
ALTER TABLE private.login_failures
  ADD COLUMN IF NOT EXISTS ip_address text NOT NULL DEFAULT '';
CREATE INDEX IF NOT EXISTS login_failures_created_idx
  ON private.login_failures (created_at DESC);
