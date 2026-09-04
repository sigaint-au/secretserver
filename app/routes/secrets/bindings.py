"""Secret access-binding routes."""

from __future__ import annotations

from flask import (
    flash,
    redirect,
    request,
    session,
    url_for,
)

import audit
from auth import authz
from core import config, db
from lib.users import lookup_user_id
from secret_svc.secret_ops import (
    _parse_access_mode,
    _parse_requires_approval,
)


@authz.login_required
def update_secret_access(project_id, secret_id):
    """Set per-secret access mode and reveal-approval override (project admin only)."""
    mode = _parse_access_mode(request.form)
    req_appr = _parse_requires_approval(request.form)
    with db.as_user(session["user_id"]) as conn, conn.cursor() as cur:
        cur.execute("SELECT api.can_admin_project(%s) AS a", (str(project_id),))
        if not (cur.fetchone() or {}).get("a"):
            flash("Only project admins can change secret access", "error")
            return secret_access_response(project_id, secret_id)
        cur.execute(
            """
            UPDATE api.secrets
            SET access_mode = %s, requires_approval = %s
            WHERE id = %s AND project_id = %s AND deleted_at IS NULL
            RETURNING key
            """,
            (mode, req_appr, str(secret_id), str(project_id)),
        )
        row = cur.fetchone()
        if not row:
            flash("Secret not found. or not permitted", "error")
            conn.rollback()
        else:
            audit.log_secret(
                cur,
                project_id=project_id,
                secret_id=secret_id,
                secret_key=row["key"],
                action="updated",
            )
            conn.commit()
            label = config.ACCESS_MODE_LABELS.get(mode, mode)
            flash(f"Access settings saved ({label})", "ok")
    return secret_access_response(project_id, secret_id)


def _secret_tab_ctx(cur, conn, project_id, secret_id):
    """Shared data load for the secret access/meta tab partials (no decrypt).

    Mirrors the meta/access branch of ``secret_view`` without touching the
    secret value, so tab mutations can re-render in place.

    Args:
        cur: Open DB cursor (user RLS).
        conn: Open DB connection (rolled back when the effective-access
            lookup fails).
        project_id: UUID of the owning project.
        secret_id: UUID of the secret.

    Returns:
        Dict of tab context, or None when the secret is missing.
    """
    from auth import rbac_sync
    from auth.roles import roles_for_scope
    from lib.users import user_email
    from secret_svc.queries import get_secret_detail

    from .helpers import _reveal_access_state

    secret_role_dropdown = roles_for_scope(cur, "secret")
    row = get_secret_detail(cur, secret_id, project_id)
    if not row:
        return None
    row = dict(row)
    row["shared_access"] = row.get("is_team_member") is False
    row["last_accessed_by_email"] = ""
    if row.get("last_accessed_by"):
        with db.connect_admin() as aconn, aconn.cursor() as acur:
            row["last_accessed_by_email"] = user_email(
                acur, str(row["last_accessed_by"])
            )
    cur.execute("SELECT api.can_admin_project(%s) AS a", (str(project_id),))
    can_admin = bool((cur.fetchone() or {}).get("a"))
    cur.execute(
        "SELECT api.can_access_secret(%s, 'write') AS w",
        (str(secret_id),),
    )
    can_write = bool((cur.fetchone() or {}).get("w"))
    access_state, access_row = _reveal_access_state(
        cur, project_id, secret_id, session["user_id"]
    )
    try:
        cur.execute(
            "SELECT * FROM private.secret_meta_rows(%s::uuid)",
            (str(secret_id),),
        )
        custom_meta = cur.fetchall() or []
    except Exception:
        custom_meta = []
    secret_bindings, team_groups, effective_access = [], [], []
    if can_admin:
        try:
            cur.execute(
                """
                SELECT b.id, b.subject_kind, b.subject_id, b.created_at,
                       r.name AS role_name,
                       g.name AS group_name
                FROM rbac.bindings b
                JOIN rbac.roles r ON r.id = b.role_id
                LEFT JOIN api.groups g
                  ON b.subject_kind = 'Group' AND g.id = b.subject_id
                WHERE b.scope_kind = 'secret' AND b.scope_id = %s::uuid
                ORDER BY b.created_at DESC
                """,
                (str(secret_id),),
            )
            secret_bindings = list(cur.fetchall() or [])
        except Exception:
            secret_bindings = []
        rbac_sync.enrich_binding_emails(secret_bindings)
        try:
            cur.execute(
                """
                SELECT g.id, g.name
                FROM api.groups g
                JOIN api.projects p ON p.team_id = g.team_id
                WHERE p.id = %s
                ORDER BY g.name
                """,
                (str(project_id),),
            )
            team_groups = cur.fetchall() or []
        except Exception:
            team_groups = []
        try:
            cur.execute(
                "SELECT * FROM api.effective_access_rows('secret', %s::uuid)",
                (str(secret_id),),
            )
            effective_access = list(cur.fetchall() or [])
        except Exception:
            conn.rollback()
            effective_access = []
    return {
        "role_dropdown": secret_role_dropdown,
        "row": row,
        "can_write": can_write,
        "can_admin": can_admin,
        "access_state": access_state,
        "access_row": access_row,
        "custom_meta": custom_meta,
        "secret_bindings": secret_bindings,
        "team_groups": team_groups,
        "effective_access": effective_access,
    }


def _render_secret_tab(project_id, secret_id, ctx, *, tab):
    """Render ``partials/secret_panel.html`` for the access or meta tab."""
    from secret_svc.secret_kinds import normalize_kind

    from .helpers import _render_secret_view

    row = ctx["row"]
    access_state = ctx["access_state"]
    body, _code = _render_secret_view(
        role_dropdown=ctx["role_dropdown"],
        project_id=project_id,
        secret_id=secret_id,
        row=row,
        plaintext="",
        kind=normalize_kind(row.get("kind")),
        can_write=ctx["can_write"],
        is_version=False,
        can_admin=ctx["can_admin"],
        secret_bindings=ctx["secret_bindings"],
        can_reveal=access_state == "allowed",
        team_groups=ctx["team_groups"],
        effective_access=ctx["effective_access"],
        active_tab=tab,
        access_blocked=access_state in ("pending", "need_request"),
        access_state=access_state,
        access_request=ctx["access_row"],
        custom_meta=ctx["custom_meta"],
    )
    return body


def secret_access_partial(project_id, secret_id):
    """Render the secret access-tab partial for HTMX swaps (no decrypt).

    Args:
        project_id: UUID of the owning project.
        secret_id: UUID of the secret.

    Returns:
        Rendered ``partials/secret_panel.html`` for the access tab,
        or 404 when invisible.
    """
    with db.as_user(session["user_id"]) as conn, conn.cursor() as cur:
        ctx = _secret_tab_ctx(cur, conn, project_id, secret_id)
        if ctx is None:
            return "Not found", 404
        if not ctx["can_admin"]:
            return "Not found", 404
    return _render_secret_tab(project_id, secret_id, ctx, tab="access")


def secret_meta_partial(project_id, secret_id):
    """Render the secret metadata-tab partial for HTMX swaps (no decrypt).

    Args:
        project_id: UUID of the owning project.
        secret_id: UUID of the secret.

    Returns:
        Rendered ``partials/secret_panel.html`` for the meta tab,
        or 404 when missing.
    """
    with db.as_user(session["user_id"]) as conn, conn.cursor() as cur:
        ctx = _secret_tab_ctx(cur, conn, project_id, secret_id)
        if ctx is None:
            return "Not found", 404
    return _render_secret_tab(project_id, secret_id, ctx, tab="meta")


def secret_meta_response(project_id, secret_id):
    """Return the secret metadata-tab partial for HTMX, else redirect to it."""
    if authz.htmx():
        return secret_meta_partial(project_id, secret_id)
    return redirect(
        url_for(
            "secret_view",
            project_id=project_id,
            secret_id=secret_id,
            tab="meta",
        )
    )



def secret_access_response(project_id, secret_id):
    """Return the secret access-tab partial for HTMX, else redirect to it."""
    if authz.htmx():
        return secret_access_partial(project_id, secret_id)
    return redirect(
        url_for(
            "secret_view",
            project_id=project_id,
            secret_id=secret_id,
            tab="access",
        )
    )


@authz.login_required
def add_secret_access_binding(project_id, secret_id):
    """Bind a user, group, or machine account to a secret role (project admin).

    Uses the same subject/role vocabulary as every other binding form:
    ``subject_kind`` + ``subject_email`` / ``subject_group`` / ``subject_sa``
    and a ``role_name`` (``secret-*`` or a custom role).
    """
    subject_kind = (request.form.get("subject_kind") or "User").strip()
    if subject_kind not in ("User", "Group", "ServiceAccount"):
        subject_kind = "User"
    email = (request.form.get("subject_email") or "").strip().lower()
    group_id = (request.form.get("subject_group") or "").strip()
    sa_id = (request.form.get("subject_sa") or "").strip()
    raw_role_name = (request.form.get("role_name") or "").strip()
    if subject_kind == "User" and not email:
        flash("Enter an email address.", "error")
        return secret_access_response(project_id, secret_id)
    if subject_kind == "Group" and not group_id:
        flash("Select a group.", "error")
        return secret_access_response(project_id, secret_id)
    if subject_kind == "ServiceAccount" and not sa_id:
        flash("Enter a machine account ID.", "error")
        return secret_access_response(project_id, secret_id)
    with db.as_user(session["user_id"]) as conn, conn.cursor() as cur:
        from auth.roles import default_role_for_scope, role_names_for_scope

        cur.execute("SELECT api.can_admin_project(%s) AS a", (str(project_id),))
        if not (cur.fetchone() or {}).get("a"):
            flash("Only project admins can manage secret bindings", "error")
            return secret_access_response(project_id, secret_id)
        role_name = (
            raw_role_name
            if raw_role_name in role_names_for_scope(cur, "secret")
            else default_role_for_scope(cur, "secret")
        )
        cur.execute(
            """
            SELECT s.id, s.key, s.access_mode, p.team_id
            FROM api.secrets s
            JOIN api.projects p ON p.id = s.project_id
            WHERE s.id = %s AND s.project_id = %s AND s.deleted_at IS NULL
            """,
            (str(secret_id), str(project_id)),
        )
        sec = cur.fetchone()
        if not sec:
            flash("Secret not found.", "error")
            if authz.htmx():
                return secret_access_partial(project_id, secret_id)
            return redirect(url_for("project_detail", project_id=project_id, tab="secrets"))
        cur.execute("SELECT id FROM rbac.roles WHERE name = %s", (role_name,))
        role = cur.fetchone()
        if not role:
            flash(f"Role {role_name} missing. Run schema ensure.", "error")
            return secret_access_response(project_id, secret_id)
        try:
            if subject_kind == "User":
                subject_id = lookup_user_id(cur, email)
                if not subject_id:
                    flash(
                        "No account found for that email address.",
                        "error",
                    )
                    return secret_access_response(project_id, secret_id)
                who = email
            elif subject_kind == "Group":
                cur.execute(
                    """
                    SELECT id, name FROM api.groups
                    WHERE id = %s AND team_id = %s
                    """,
                    (group_id, str(sec["team_id"])),
                )
                g = cur.fetchone()
                if not g:
                    flash("Group not found in this team", "error")
                    return secret_access_response(project_id, secret_id)
                subject_id, who = str(g["id"]), f"group {g['name']}"
            else:
                cur.execute(
                    """
                    SELECT mt.id
                    FROM api.machine_tokens mt
                    WHERE mt.id = %s::uuid
                      AND mt.project_id = %s
                    """,
                    (sa_id, str(project_id)),
                )
                sa = cur.fetchone()
                if not sa:
                    flash("Machine account not found in this project", "error")
                    return secret_access_response(project_id, secret_id)
                subject_id, who = str(sa["id"]), f"machine account {sa_id[:8]}"
            external_user = False
            if subject_kind == "User":
                cur.execute(
                    """
                    SELECT api.can('list', 'secrets', 'team', %s::uuid, %s::uuid)
                      AS member
                    """,
                    (str(sec["team_id"]), subject_id),
                )
                external_user = not bool((cur.fetchone() or {}).get("member"))
                if external_user:
                    cur.execute(
                        "SELECT api.secret_requires_approval(%s::uuid) AS a",
                        (str(secret_id),),
                    )
                    if bool((cur.fetchone() or {}).get("a")):
                        flash(
                            "Cannot share secrets that require reveal approval "
                            "with users outside the team. Turn off reveal approval "
                            "on this secret (or the project default), or add them "
                            "to the team first.",
                            "error",
                        )
                        return secret_access_response(project_id, secret_id)
            # Replace any existing secret-scope binding for this subject
            cur.execute(
                """
                DELETE FROM rbac.bindings
                WHERE scope_kind = 'secret' AND scope_id = %s::uuid
                  AND subject_kind = %s AND subject_id = %s::uuid
                """,
                (str(secret_id), subject_kind, subject_id),
            )
            cur.execute(
                """
                INSERT INTO rbac.bindings
                  (role_id, subject_kind, subject_id, scope_kind, scope_id, created_by)
                VALUES (%s::uuid, %s, %s::uuid, 'secret', %s::uuid, %s::uuid)
                """,
                (
                    str(role["id"]),
                    subject_kind,
                    subject_id,
                    str(secret_id),
                    session["user_id"],
                ),
            )
            # Restricted mode if not already — bindings only apply as exclusive when restricted
            if (sec.get("access_mode") or "inherit") != "restricted":
                cur.execute(
                    """
                    UPDATE api.secrets SET access_mode = 'restricted'
                    WHERE id = %s AND project_id = %s AND deleted_at IS NULL
                    """,
                    (str(secret_id), str(project_id)),
                )
            audit.log_secret(
                cur,
                project_id=project_id,
                secret_id=secret_id,
                secret_key=sec["key"],
                action="updated",
            )
            conn.commit()
            if external_user:
                flash(
                    f"Bound {who} as {role_name}. They are not on this team. "
                    "They will only see this secret under Workspace in Shared secrets.",
                    "ok",
                )
            else:
                flash(f"Bound {who} as {role_name}", "ok")
        except Exception:
            conn.rollback()
            flash("Could not update secret access. Try again.", "error")
    return secret_access_response(project_id, secret_id)


@authz.login_required
def delete_secret_access_binding(project_id, secret_id, grant_id):
    """Remove a secret-scope role binding (project admin only)."""
    with db.as_user(session["user_id"]) as conn, conn.cursor() as cur:
        cur.execute("SELECT api.can_admin_project(%s) AS a", (str(project_id),))
        if not (cur.fetchone() or {}).get("a"):
            flash("Only project admins can manage secret bindings", "error")
            return secret_access_response(project_id, secret_id)
        cur.execute(
            """
            DELETE FROM rbac.bindings b
            USING api.secrets s
            WHERE b.id = %s::uuid
              AND b.scope_kind = 'secret'
              AND b.scope_id = s.id
              AND s.id = %s::uuid AND s.project_id = %s::uuid
            RETURNING s.key
            """,
            (str(grant_id), str(secret_id), str(project_id)),
        )
        row = cur.fetchone()
        if not row:
            flash("Binding not found.", "error")
            conn.rollback()
        else:
            audit.log_secret(
                cur,
                project_id=project_id,
                secret_id=secret_id,
                secret_key=row["key"],
                action="updated",
            )
            conn.commit()
            flash("Binding removed", "ok")
    return secret_access_response(project_id, secret_id)
