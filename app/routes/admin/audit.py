"""Global admin audit and access-review routes."""

from __future__ import annotations

from datetime import (
    datetime,
    timezone,
)

from flask import (
    flash,
    redirect,
    render_template,
    request,
    url_for,
)

import audit
from auth import authz
from core import db, settings_svc
from ui import paging

from .helpers import (
    _csv_response,
    _json_response,
)


@authz.global_admin_required
def admin_audit():
    """Render audit/access-review UI or handle retention/purge POSTs.

    Args:
        None (reads query/form ``tab``, filters, and POST ``action``).

    Returns:
        HTML audit template, or redirect after settings/purge actions.

    Example:
        GET/POST /admin/audit?tab=access
    """
    tab = (request.args.get("tab") or request.form.get("tab") or "access").strip().lower()
    if tab not in ("access", "roles", "activity", "logins", "export"):
        tab = "access"

    if request.method == "POST":
        action = (request.form.get("action") or "").strip()
        if action == "retention":
            raw = (request.form.get("audit_retention_days") or "").strip()
            try:
                days = int(raw)
                if days < 0 or days > 36500:
                    raise ValueError("out of range")
            except ValueError:
                flash("Retention must be a number from 0 (keep forever) to 36500 days", "error")
            else:
                settings_svc.set_setting("audit_retention_days", str(days))
                flash(
                    "Audit retention saved"
                    if days > 0
                    else "Audit retention set to forever (no automatic purge)",
                    "ok",
                )
            return redirect(url_for("admin_audit", tab="export"))
        if action == "purge":
            settings = settings_svc.get_settings()
            try:
                days = int(settings.get("audit_retention_days") or "365")
            except ValueError:
                days = 365
            if days <= 0:
                flash("Retention is set to forever. Set a positive day count before purging.", "error")
                return redirect(url_for("admin_audit", tab="export"))
            with db.connect_admin() as conn, conn.cursor() as cur:
                result = audit.purge_old_audit(cur, days)
                if not conn.autocommit:
                    conn.commit()
            flash(
                f"Purged {result['secret_audit']} secret audit, "
                f"{result['org_audit']} org audit, and "
                f"{result.get('login_failures', 0)} login failures "
                f"older than {days} days",
                "ok",
            )
            return redirect(url_for("admin_audit", tab="export"))
        return redirect(url_for("admin_audit", tab=tab))

    settings = settings_svc.get_settings()
    retention_days = settings.get("audit_retention_days") or "365"
    access_rows = []
    access_pager = None
    access_scope = ""
    role_rows = []
    role_total = 0
    role_pager = None
    secret_rows = []
    secret_total = 0
    secret_pager = None
    login_rows = []
    login_total = 0
    login_pager = None
    counts = {
        "secret_audit": 0,
        "org_audit": 0,
        "login_failures": 0,
        "oldest": None,
        "newest": None,
    }
    purge_counts = {"secret_audit": 0, "org_audit": 0, "login_failures": 0}
    q = (request.args.get("q") or "").strip()
    actor = (request.args.get("actor") or "").strip()
    since = (request.args.get("since") or "").strip()
    until = (request.args.get("until") or "").strip()
    secret_action = (request.args.get("action") or "").strip()
    secret_ip = (request.args.get("ip") or "").strip()
    hide_reveals = (request.args.get("hide_reveals") or "").strip().lower() in (
        "1", "on", "true",
    )
    # ponytail: pager.html has a fixed filter-key set; "action" aliases
    # role_actions there so the view survives pagination. Drop the alias if
    # pager.html ever grows a role_actions key.
    role_actions = (
        request.args.get("role_actions")
        or request.args.get("action")
        or request.form.get("role_actions")
        or "roles"
    ).strip().lower()
    if role_actions not in ("all", "roles", "encryption"):
        role_actions = "roles"
    active_actions = (
        None
        if role_actions == "all"
        else (
            audit.ENC_CHANGE_ACTIONS
            if role_actions == "encryption"
            else audit.ROLE_CHANGE_ACTIONS
        )
    )

    with db.connect_admin() as conn, conn.cursor() as cur:
        if tab == "access":
            access_scope = (request.args.get("scope") or "").strip().lower()
            if access_scope not in ("global", "team", "project"):
                access_scope = ""
            access_rows = audit.filter_access_rows(
                audit.access_review_rows(cur), q=q, scope=access_scope
            )
            access_pager = paging.page_window(
                len(access_rows), paging.page_arg(), per_page=25
            )
            access_pager.update(
                endpoint="admin_audit",
                tab="access",
                q=q or None,
                scope=access_scope or None,
            )
            access_rows = access_rows[
                access_pager["offset"] : access_pager["offset"]
                + access_pager["limit"]
            ]
        elif tab == "roles":
            role_total = audit.count_org_audit(
                cur,
                actions=active_actions,
                q=q,
                actor=actor,
                since=since,
                until=until,
            )
            role_pager = paging.page_window(
                role_total, paging.page_arg(), per_page=25
            )
            role_pager.update(
                endpoint="admin_audit",
                tab="roles",
                q=q or None,
                actor=actor or None,
                since=since or None,
                until=until or None,
                action=role_actions,
            )
            role_rows = audit.list_org_audit(
                cur,
                actions=active_actions,
                q=q,
                actor=actor,
                since=since,
                until=until,
                limit=role_pager["limit"],
                offset=role_pager["offset"],
            )
        elif tab == "activity":
            secret_total = audit.count_secret_audit(
                cur,
                q=q,
                actor=actor,
                action=secret_action,
                since=since,
                until=until,
                ip=secret_ip,
                hide_reveals=hide_reveals,
            )
            secret_pager = paging.page_window(
                secret_total, paging.page_arg(), per_page=25
            )
            secret_pager.update(
                endpoint="admin_audit",
                tab="activity",
                q=q or None,
                actor=actor or None,
                action=secret_action or None,
                ip=secret_ip or None,
                since=since or None,
                until=until or None,
                hide_reveals="1" if hide_reveals else None,
            )
            secret_rows = audit.list_secret_audit(
                cur,
                q=q,
                actor=actor,
                action=secret_action,
                since=since,
                until=until,
                ip=secret_ip,
                hide_reveals=hide_reveals,
                limit=secret_pager["limit"],
                offset=secret_pager["offset"],
            )
        elif tab == "logins":
            login_total = audit.count_login_failures(
                cur, q=q, since=since, until=until
            )
            login_pager = paging.page_window(
                login_total, paging.page_arg(), per_page=25
            )
            login_pager.update(
                endpoint="admin_audit",
                tab="logins",
                q=q or None,
                since=since or None,
                until=until or None,
            )
            login_rows = audit.list_login_failures(
                cur,
                q=q,
                since=since,
                until=until,
                limit=login_pager["limit"],
                offset=login_pager["offset"],
            )
        elif tab == "export":
            counts = audit.audit_counts(cur)
            try:
                retention_int = int(retention_days)
            except ValueError:
                retention_int = 365
            purge_counts = audit.purge_preview(cur, retention_int)

    return render_template(
        "admin_audit.html",
        active_tab=tab,
        access_rows=access_rows,
        access_pager=access_pager,
        access_scope=access_scope,
        role_rows=role_rows,
        role_total=role_total,
        role_pager=role_pager,
        role_actions=role_actions,
        secret_rows=secret_rows,
        secret_total=secret_total,
        secret_pager=secret_pager,
        secret_actions=audit.ACTIONS,
        login_rows=login_rows,
        login_total=login_total,
        login_pager=login_pager,
        counts=counts,
        purge_counts=purge_counts,
        retention_days=retention_days,
        search_q=q,
        audit_actor=actor,
        audit_action=secret_action,
        audit_ip=secret_ip,
        hide_reveals=hide_reveals,
        audit_since=since,
        audit_until=until,
    )


@authz.global_admin_required
def admin_audit_access_export():
    """Export the access-review report as CSV or JSON download.

    Args:
        None (reads query ``format``: ``csv`` or ``json``; optional
        ``q`` and ``scope`` apply the same filters as the access tab).

    Returns:
        File download Response (CSV or JSON attachment).

    Example:
        GET /admin/audit/access/export?format=csv
    """
    fmt = (request.args.get("format") or "csv").strip().lower()
    if fmt not in ("csv", "json"):
        fmt = "csv"
    q = (request.args.get("q") or "").strip()
    scope = (request.args.get("scope") or "").strip()
    with db.connect_admin() as conn, conn.cursor() as cur:
        rows = audit.filter_access_rows(
            audit.access_review_rows(cur), q=q, scope=scope
        )
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d")
    fields = [
        "email",
        "name",
        "is_global_admin",
        "disabled",
        "scope",
        "team",
        "team_role",
        "project",
        "project_role",
        "access_via",
        "user_id",
    ]
    if fmt == "json":
        return _json_response(
            f"access-review-{stamp}.json",
            {
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "type": "access_review",
                "count": len(rows),
                "rows": rows,
            },
        )
    return _csv_response(f"access-review-{stamp}.csv", fields, rows)


@authz.global_admin_required
def admin_audit_export():
    """Export secret and/or org audit logs as CSV or JSON.

    Args:
        None (reads query ``format``, ``source``, ``since``, ``until``;
        optional ``q``, ``actor``, ``role_actions`` narrow org exports,
        and ``q``, ``actor``, ``action``, ``ip``, ``hide_reveals``
        narrow secret exports — the same filters as the roles and
        secret-activity tabs).

    Returns:
        File download Response with filtered audit rows.

    Example:
        GET /admin/audit/export?format=csv&source=both
    """
    fmt = (request.args.get("format") or "csv").strip().lower()
    source = (request.args.get("source") or "both").strip().lower()
    since = (request.args.get("since") or "").strip()
    until = (request.args.get("until") or "").strip()
    q = (request.args.get("q") or "").strip()
    actor = (request.args.get("actor") or "").strip()
    role_actions = (request.args.get("role_actions") or "").strip().lower()
    secret_action = (request.args.get("action") or "").strip()
    secret_ip = (request.args.get("ip") or "").strip()
    hide_reveals = (request.args.get("hide_reveals") or "").strip().lower() in (
        "1", "on", "true",
    )
    if fmt not in ("csv", "json"):
        fmt = "csv"
    if source not in ("secret", "org", "both"):
        source = "both"
    if role_actions == "encryption":
        export_actions: tuple[str, ...] | None = audit.ENC_CHANGE_ACTIONS
    elif role_actions == "roles":
        export_actions = audit.ROLE_CHANGE_ACTIONS
    else:
        export_actions = None
    secret_rows, org_rows = [], []
    with db.connect_admin() as conn, conn.cursor() as cur:
        if source in ("secret", "both"):
            secret_rows = audit.export_secret_audit(
                cur,
                since=since,
                until=until,
                q=q,
                actor=actor,
                action=secret_action,
                ip=secret_ip,
                hide_reveals=hide_reveals,
            )
        if source in ("org", "both"):
            org_rows = audit.export_org_audit(
                cur,
                since=since,
                until=until,
                actions=export_actions,
                q=q,
                actor=actor,
            )
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d")
    if fmt == "json":
        payload = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "since": since or None,
            "until": until or None,
        }
        if source in ("secret", "both"):
            payload["secret_audit"] = secret_rows
        if source in ("org", "both"):
            payload["org_audit"] = org_rows
        return _json_response(f"audit-export-{stamp}.json", payload)

    # CSV: combined or single stream
    if source == "secret":
        fields = [
            "kind",
            "id",
            "created_at",
            "action",
            "secret_key",
            "actor_email",
            "ip_address",
            "user_agent",
            "team_name",
            "project_name",
            "project_id",
            "user_id",
        ]
        rows = [
            {
                "kind": "secret",
                "id": r.get("id"),
                "created_at": r.get("created_at"),
                "action": r.get("action"),
                "secret_key": r.get("secret_key"),
                "actor_email": r.get("actor_email"),
                "ip_address": r.get("ip_address"),
                "user_agent": r.get("user_agent"),
                "team_name": r.get("team_name"),
                "project_name": r.get("project_name"),
                "project_id": r.get("project_id"),
                "user_id": r.get("user_id"),
            }
            for r in secret_rows
        ]
        return _csv_response(f"secret-audit-{stamp}.csv", fields, rows)
    if source == "org":
        fields = [
            "kind",
            "id",
            "created_at",
            "action",
            "detail",
            "actor_email",
            "ip_address",
            "user_agent",
            "team_name",
            "project_name",
            "team_id",
            "project_id",
            "user_id",
        ]
        rows = [
            {
                "kind": "org",
                "id": r.get("id"),
                "created_at": r.get("created_at"),
                "action": r.get("action"),
                "detail": r.get("detail"),
                "actor_email": r.get("actor_email"),
                "ip_address": r.get("ip_address"),
                "user_agent": r.get("user_agent"),
                "team_name": r.get("team_name"),
                "project_name": r.get("project_name"),
                "team_id": r.get("team_id"),
                "project_id": r.get("project_id"),
                "user_id": r.get("user_id"),
            }
            for r in org_rows
        ]
        return _csv_response(f"org-audit-{stamp}.csv", fields, rows)

    fields = [
        "kind",
        "id",
        "created_at",
        "action",
        "detail",
        "secret_key",
        "actor_email",
        "ip_address",
        "user_agent",
        "team_name",
        "project_name",
        "team_id",
        "project_id",
        "user_id",
    ]
    rows = []
    for r in secret_rows:
        rows.append(
            {
                "kind": "secret",
                "id": r.get("id"),
                "created_at": r.get("created_at"),
                "action": r.get("action"),
                "detail": "",
                "secret_key": r.get("secret_key"),
                "actor_email": r.get("actor_email"),
                "ip_address": r.get("ip_address"),
                "user_agent": r.get("user_agent"),
                "team_name": r.get("team_name"),
                "project_name": r.get("project_name"),
                "team_id": "",
                "project_id": r.get("project_id"),
                "user_id": r.get("user_id"),
            }
        )
    for r in org_rows:
        rows.append(
            {
                "kind": "org",
                "id": r.get("id"),
                "created_at": r.get("created_at"),
                "action": r.get("action"),
                "detail": r.get("detail"),
                "secret_key": "",
                "actor_email": r.get("actor_email"),
                "ip_address": r.get("ip_address"),
                "user_agent": r.get("user_agent"),
                "team_name": r.get("team_name"),
                "project_name": r.get("project_name"),
                "team_id": r.get("team_id"),
                "project_id": r.get("project_id"),
                "user_id": r.get("user_id"),
            }
        )
    rows.sort(key=lambda x: str(x.get("created_at") or ""), reverse=True)
    return _csv_response(f"audit-export-{stamp}.csv", fields, rows)
