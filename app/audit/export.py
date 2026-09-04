"""Audit export queries (secret and org)."""

from __future__ import annotations

from .queries import _filter_clause, _org_audit_where


def export_secret_audit(
    cur,
    *,
    since: str = "",
    until: str = "",
    limit: int = 50000,
    q: str = "",
    actor: str = "",
    action: str = "",
    ip: str = "",
    hide_reveals: bool = False,
):
    """Export secret_audit rows for filters (compliance/export use).

    Args:
        cur: Database cursor used to run the SELECT.
        since: Inclusive start date as YYYY-MM-DD (UTC start of day).
        until: Inclusive end date as YYYY-MM-DD (UTC end of day).
        limit: Maximum number of rows to return (default 50000).
        q: Free-text filter on secret_key, action, and actor_email.
        actor: Substring filter on actor_email (case-insensitive).
        action: Exact action filter if it is a known ACTIONS value.
        ip: Substring filter on ip_address (case-insensitive).
        hide_reveals: When True, exclude 'revealed' rows (noise filter).

    Returns:
        List of secret_audit row mappings with project/team names joined.

    Example:
        >>> rows = export_secret_audit(cur, since="2026-01-01", until="2026-01-31")
        >>> len(rows) <= 50000
        True
    """
    where, params = _filter_clause(
        q=q, actor=actor, action=action, since=since, until=until,
        ip=ip, hide_reveals=hide_reveals,
    )
    cur.execute(
        f"""
        SELECT a.id::text, a.created_at, a.action, a.secret_key, a.actor_email,
               a.project_id::text, p.name AS project_name,
               t.name AS team_name, a.user_id::text,
               a.ip_address, a.user_agent
        FROM api.secret_audit a
        LEFT JOIN api.projects p ON p.id = a.project_id
        LEFT JOIN api.teams t ON t.id = p.team_id
        {where}
        ORDER BY a.created_at DESC
        LIMIT %s
        """,
        (*params, limit),
    )
    return cur.fetchall() or []


def export_org_audit(
    cur,
    *,
    since: str = "",
    until: str = "",
    limit: int = 50000,
    actions: tuple[str, ...] | None = None,
    q: str = "",
    actor: str = "",
):
    """Export org_audit rows for filters (compliance/export use).

    Args:
        cur: Database cursor used to run the SELECT.
        since: Inclusive start date as YYYY-MM-DD (UTC start of day).
        until: Inclusive end date as YYYY-MM-DD (UTC end of day).
        limit: Maximum number of rows to return (default 50000).
        actions: Optional tuple of action names to restrict results to
            (None means all org actions).
        q: Free-text search across action, detail, actor, team, and project.
        actor: Substring filter on actor_email (case-insensitive).

    Returns:
        List of org_audit row mappings with team/project names joined.

    Example:
        >>> rows = export_org_audit(cur, since="2026-01-01", limit=1000)
        >>> isinstance(rows, list)
        True
    """
    where, params = _org_audit_where(
        actions=actions, q=q, actor=actor, since=since, until=until
    )
    cur.execute(
        f"""
        SELECT a.id::text, a.created_at, a.action, a.detail, a.actor_email,
               a.team_id::text, t.name AS team_name,
               a.project_id::text, p.name AS project_name,
               a.user_id::text, a.ip_address, a.user_agent
        FROM api.org_audit a
        LEFT JOIN api.teams t ON t.id = a.team_id
        LEFT JOIN api.projects p ON p.id = a.project_id
        {where}
        ORDER BY a.created_at DESC
        LIMIT %s
        """,
        (*params, limit),
    )
    return cur.fetchall() or []
