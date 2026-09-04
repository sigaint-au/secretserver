-- Additive migration: track last use of multi-use CLI session tokens.
--
-- auth/cli_sessions.py resolve() updates private.cli_session_tokens.last_used_at
-- on every successful token validation (generated `corvus login` commands).
-- The squashed 0001 baseline predates that column, so CLI auth 500s with
-- "column last_used_at of relation cli_session_tokens does not exist".
-- Idempotent: safe to re-run.
ALTER TABLE private.cli_session_tokens
  ADD COLUMN IF NOT EXISTS last_used_at timestamptz;
