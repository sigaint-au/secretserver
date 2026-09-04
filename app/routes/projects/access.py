"""Project member, group-role, and access-binding routes."""

from __future__ import annotations

from flask import (
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

import audit
from auth import authz, rbac_sync
from core import config, db
from lib.users import lookup_user_id
from ui import paging


def _project_access_url(project_id):
    return url_for("project_detail", project_id=project_id, tab="access")


def load_project_access_tab(cur, conn, project_id, team_id, *, can_admin, page=1, q=""):
    """Load access-tab rows (bindings, effective access, groups, role metadata).

    Shared by the full project page and the HTMX access partial so the two
    cannot drift apart.

    Args:
        cur: Open DB cursor (user RLS).
        conn: Open DB connection (rolled back when the effective-access
            lookup fails, matching the detail route).
        project_id: UUID of the project.
        team_id: UUID of the owning team (for the group dropdown).
        can_admin: Whether the viewer passed the project-admin gate.
        page: Effective-access page number.
        q: Effective-access search filter.

    Returns:
        Dict of template vars for ``partials/project_access.html``.
    """
    from auth import rbac_sync
    from auth.roles import roles_for_scope

    cur.execute(
        "SELECT api.can_manage_rbac('project', %s::uuid) AS ok",
        (str(project_id),),
    )
    can_edit_access = bool((cur.fetchone() or {}).get("ok")) or bool(can_admin)
    access_bindings = rbac_sync.list_scope_bindings(cur, "project", project_id)
    try:
        cur.execute(
            "SELECT * FROM api.effective_access_rows('project', %s::uuid)",
            (str(project_id),),
        )
        effective_access = list(cur.fetchall() or [])
    except Exception:
        conn.rollback()
        effective_access = []
    effective_access_q = (q or "").strip()
    if effective_access_q:
        needle = effective_access_q.casefold()
        effective_access = [
            row
            for row in effective_access
            if needle
            in " ".join(
                str(row.get(key) or "")
                for key in (
                    "subject_email",
                    "subject_name",
                    "subject_kind",
                    "role_name",
                    "scope_label",
                    "scope_kind",
                    "grant_kind",
                    "grant_subject",
                )
            ).casefold()
        ]
    effective_access_pager = paging.page_window(len(effective_access), page)
    effective_access_pager.update(
        endpoint="project_detail",
        project_id=project_id,
        tab="access",
        q=effective_access_q or None,
    )
    start = (page - 1) * effective_access_pager["per_page"]
    effective_access = effective_access[start : start + effective_access_pager["per_page"]]
    try:
        cur.execute(
            """
            SELECT id, name FROM api.groups
            WHERE team_id = %s ORDER BY name
            """,
            (str(team_id),),
        )
        access_groups = list(cur.fetchall() or [])
    except Exception:
        access_groups = []
    try:
        cur.execute("SELECT name, description FROM rbac.roles")
        role_descriptions = {
            r["name"]: (r.get("description") or "") for r in (cur.fetchall() or [])
        }
    except Exception:
        role_descriptions = {}
    project_role_dropdown = roles_for_scope(cur, "project")
    return {
        "access_bindings": access_bindings,
        "access_groups": access_groups,
        "effective_access": effective_access,
        "effective_access_pager": effective_access_pager,
        "effective_access_q": effective_access_q,
        "can_edit_access": can_edit_access,
        "project_role_dropdown": project_role_dropdown,
        "role_descriptions": role_descriptions,
    }


def project_access_partial(project_id):
    """Render the access-tab partial for HTMX swaps.

    Args:
        project_id: UUID of the project.

    Returns:
        Rendered ``partials/project_content.html`` for the access tab,
        or 404 when invisible.
    """
    page = paging.page_arg("page")
    q = (request.args.get("q") or "").strip()
    with db.as_user(session["user_id"]) as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT p.*, t.name AS team_name, t.id AS team_id,
                   t.default_token_days
            FROM api.projects p JOIN api.teams t ON t.id = p.team_id
            WHERE p.id = %s
            """,
            (str(project_id),),
        )
        project = cur.fetchone()
        if not project:
            return "Not found", 404
        cur.execute("SELECT api.can_admin_project(%s) AS a", (str(project_id),))
        can_admin = cur.fetchone()["a"]
        if not can_admin:
            return "Not found", 404
        access_ctx = load_project_access_tab(
            cur,
            conn,
            project_id,
            project["team_id"],
            can_admin=can_admin,
            page=page,
            q=q,
        )
    rbac_sync.enrich_binding_emails(access_ctx["access_bindings"])
    pname = (project or {}).get("name") or "Project"
    return render_template(
        "partials/project_content.html",
        oob_title=f"Access - {pname}",
        project=project,
        project_id=project_id,
        can_admin=can_admin,
        active_tab="access",
        subject_kinds=config.RBAC_SUBJECT_KINDS,
        **access_ctx,
    )


def project_access_response(project_id):
    """Return the access-tab partial for HTMX, else redirect to the access tab."""
    if authz.htmx():
        return project_access_partial(project_id)
    return redirect(_project_access_url(project_id))


@authz.login_required
def add_project_binding(project_id):
    """Add or update a project member via RBAC binding (User + project-* role).

    Body: email + role (admin|write|read). Writes ``rbac.bindings`` only.
    """
    email = (request.form.get("email") or "").strip().lower()
    raw_role = (request.form.get("role") or "").strip()
    dest = _project_access_url(project_id)
    if not email:
        flash("Enter an email address.", "error")
        return redirect(dest)
    with db.as_user(session["user_id"]) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT api.can_manage_rbac('project', %s::uuid) AS ok",
            (str(project_id),),
        )
        if not (cur.fetchone() or {}).get("ok"):
            flash("You do not have permission to perform this action", "error")
            return redirect(dest)
        from auth.roles import default_role_for_scope, role_names_for_scope

        role = (
            raw_role
            if raw_role in role_names_for_scope(cur, "project")
            else default_role_for_scope(cur, "project")
        )
        uid = lookup_user_id(cur, email)
        if not uid:
            flash(
                "No account found for that email address.",
                "error",
            )
            return redirect(dest)
        cur.execute(
            "SELECT team_id FROM api.projects WHERE id = %s", (str(project_id),)
        )
        proj = cur.fetchone()
        try:
            from auth import rbac_sync

            rbac_sync.sync_user_project_binding(
                cur,
                user_id=uid,
                project_id=project_id,
                role=role,
                created_by=session["user_id"],
            )
            audit.log_org(
                cur,
                team_id=proj["team_id"] if proj else None,
                project_id=project_id,
                action=audit.ORG_PROJECT_MEMBER_ADD,
                detail=f"{email} → {role} (rbac)",
            )
            conn.commit()
            flash(f"Bound {email} as project-{role}", "ok")
        except Exception:
            conn.rollback()
            flash("Could not update project access. Try again.", "error")
    return redirect(dest)


@authz.login_required
def remove_project_binding(project_id, user_id):
    """Remove a user project-scope RBAC binding."""
    dest = _project_access_url(project_id)
    with db.as_user(session["user_id"]) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT api.can_manage_rbac('project', %s::uuid) AS ok",
            (str(project_id),),
        )
        if not (cur.fetchone() or {}).get("ok"):
            flash("You do not have permission to perform this action", "error")
            return redirect(dest)
        cur.execute(
            "SELECT team_id FROM api.projects WHERE id = %s", (str(project_id),)
        )
        proj = cur.fetchone()
        try:
            from auth import rbac_sync

            rbac_sync.sync_user_project_binding(
                cur, user_id=user_id, project_id=project_id, role=None
            )
            audit.log_org(
                cur,
                team_id=proj["team_id"] if proj else None,
                project_id=project_id,
                action=audit.ORG_PROJECT_MEMBER_REMOVE,
                detail=str(user_id),
            )
            conn.commit()
            flash("Project binding removed", "ok")
        except Exception:
            conn.rollback()
            flash("Could not update project access. Try again.", "error")
    return redirect(dest)


@authz.login_required
def add_project_group_role(project_id):
    """Grant a team group a project role via RBAC binding only."""
    group_id = (request.form.get("group_id") or "").strip()
    raw_role = (request.form.get("role") or "").strip()
    dest = _project_access_url(project_id)
    if not group_id:
        flash("Select a group..", "error")
        return redirect(dest)
    with db.as_user(session["user_id"]) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT api.can_manage_rbac('project', %s::uuid) AS ok",
            (str(project_id),),
        )
        if not (cur.fetchone() or {}).get("ok"):
            flash("You do not have permission to perform this action", "error")
            return redirect(dest)
        from auth.roles import default_role_for_scope, role_names_for_scope

        role = (
            raw_role
            if raw_role in role_names_for_scope(cur, "project")
            else default_role_for_scope(cur, "project")
        )
        cur.execute(
            """
            SELECT p.team_id, g.name
            FROM api.projects p
            JOIN api.groups g ON g.team_id = p.team_id AND g.id = %s
            WHERE p.id = %s
            """,
            (group_id, str(project_id)),
        )
        row = cur.fetchone()
        if not row:
            flash("Group not found in this team", "error")
            return redirect(dest)
        try:
            from auth import rbac_sync

            rbac_sync.sync_group_project_binding(
                cur,
                group_id=group_id,
                project_id=project_id,
                role=role,
                created_by=session["user_id"],
            )
            audit.log_org(
                cur,
                team_id=row["team_id"],
                project_id=project_id,
                action="project_group_role",
                detail=f"{row['name']} → {role} (rbac)",
            )
            conn.commit()
            flash(f"Bound group “{row['name']}” as project-{role}", "ok")
        except Exception:
            conn.rollback()
            flash("Could not update project access. Try again.", "error")
    return redirect(dest)


@authz.login_required
def remove_project_group_role(project_id, group_id):
    """Remove a group project-scope RBAC binding."""
    dest = _project_access_url(project_id)
    with db.as_user(session["user_id"]) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT api.can_manage_rbac('project', %s::uuid) AS ok",
            (str(project_id),),
        )
        if not (cur.fetchone() or {}).get("ok"):
            flash("You do not have permission to perform this action", "error")
            return redirect(dest)
        cur.execute(
            "SELECT team_id FROM api.projects WHERE id = %s", (str(project_id),)
        )
        proj = cur.fetchone()
        try:
            from auth import rbac_sync

            rbac_sync.sync_group_project_binding(
                cur,
                group_id=group_id,
                project_id=project_id,
                role=None,
                created_by=session.get("user_id"),
            )
            audit.log_org(
                cur,
                team_id=proj["team_id"] if proj else None,
                project_id=project_id,
                action="project_group_role_remove",
                detail=str(group_id),
            )
            conn.commit()
            flash("Group project binding removed", "ok")
        except Exception:
            conn.rollback()
            flash("Could not update project access. Try again.", "error")
    return redirect(dest)


@authz.login_required
def project_access_binding_create(project_id):
    """Create a project-scope role binding (User / Group / ServiceAccount)."""
    role_name = (request.form.get("role_name") or "").strip()
    subject_kind = (request.form.get("subject_kind") or "User").strip()
    subject_email = (request.form.get("subject_email") or "").strip().lower()
    subject_group = (request.form.get("subject_group") or "").strip()
    subject_sa = (request.form.get("subject_sa") or "").strip()
    with db.as_user(session["user_id"]) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT api.can_manage_rbac('project', %s::uuid) AS ok",
            (str(project_id),),
        )
        if not (cur.fetchone() or {}).get("ok"):
            flash("Only project admins can manage role bindings", "error")
            return project_access_response(project_id)
        cur.execute(
            "SELECT team_id FROM api.projects WHERE id = %s", (str(project_id),)
        )
        proj = cur.fetchone()
        if not proj:
            flash("Project not found.", "error")
            if authz.htmx():
                return project_access_partial(project_id)
            return redirect(url_for("projects"))
        try:
            from auth.roles import role_names_for_scope

            if role_name not in role_names_for_scope(cur, "project"):
                flash("Unknown role.", "error")
                return project_access_response(project_id)

            subject_id = None
            detail_who = None
            if subject_kind == "User":
                subject_id = lookup_user_id(cur, subject_email)
                if not subject_id:
                    flash("No account found for that email address.", "error")
                    return project_access_response(project_id)
                detail_who = subject_email
                rbac_sync.sync_user_project_binding(
                    cur,
                    user_id=subject_id,
                    project_id=project_id,
                    role=role_name,
                    created_by=session["user_id"],
                )
            elif subject_kind == "Group":
                if not subject_group:
                    flash("Select a group.", "error")
                    return project_access_response(project_id)
                cur.execute(
                    """
                    SELECT id, name FROM api.groups
                    WHERE id = %s AND team_id = %s
                    """,
                    (subject_group, str(proj["team_id"])),
                )
                g = cur.fetchone()
                if not g:
                    flash("Group not found in this team", "error")
                    return project_access_response(project_id)
                subject_id = str(g["id"])
                detail_who = f"group {g['name']}"
                rbac_sync.sync_group_project_binding(
                    cur,
                    group_id=subject_group,
                    project_id=project_id,
                    role=role_name,
                    created_by=session["user_id"],
                )
            elif subject_kind == "ServiceAccount":
                subject_id = subject_sa
                detail_who = f"sa {subject_sa}"
                if not subject_id:
                    flash("Enter a machine account ID.", "error")
                    return project_access_response(project_id)
                rid = rbac_sync.role_id(cur, role_name)
                if not rid:
                    flash("Unknown role.", "error")
                    return project_access_response(project_id)
                cur.execute(
                    """
                    INSERT INTO rbac.bindings
                      (role_id, subject_kind, subject_id, scope_kind, scope_id, created_by)
                    VALUES (%s::uuid, 'ServiceAccount', %s::uuid, 'project', %s::uuid, %s::uuid)
                    ON CONFLICT DO NOTHING
                    """,
                    (
                        rid,
                        subject_id,
                        str(project_id),
                        session["user_id"],
                    ),
                )
            else:
                flash("Invalid subject kind.", "error")
                return project_access_response(project_id)

            audit.log_org(
                cur,
                team_id=proj["team_id"],
                project_id=project_id,
                action=audit.ORG_PROJECT_MEMBER_ADD,
                detail=f"{detail_who} → {role_name}",
            )
            conn.commit()
            flash("Binding created", "ok")
        except Exception:
            conn.rollback()
            flash("Could not update project access. Try again.", "error")
    return project_access_response(project_id)


@authz.login_required
def project_access_binding_delete(project_id, binding_id):
    """Remove a project-scope role binding."""
    with db.as_user(session["user_id"]) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT api.can_manage_rbac('project', %s::uuid) AS ok",
            (str(project_id),),
        )
        if not (cur.fetchone() or {}).get("ok"):
            flash("Only project admins can manage role bindings", "error")
            return project_access_response(project_id)
        cur.execute(
            "SELECT team_id FROM api.projects WHERE id = %s", (str(project_id),)
        )
        proj = cur.fetchone()
        try:
            cur.execute(
                """
                DELETE FROM rbac.bindings
                WHERE id = %s::uuid
                  AND scope_kind = 'project'
                  AND scope_id = %s::uuid
                RETURNING subject_kind, subject_id
                """,
                (str(binding_id), str(project_id)),
            )
            row = cur.fetchone()
            if not row:
                flash("Binding not found. or not permitted.", "error")
                conn.rollback()
            else:
                audit.log_org(
                    cur,
                    team_id=proj["team_id"] if proj else None,
                    project_id=project_id,
                    action=audit.ORG_PROJECT_MEMBER_REMOVE,
                    detail=f"{row['subject_kind']}:{row['subject_id']}",
                )
                conn.commit()
                flash("Binding removed", "ok")
        except Exception:
            conn.rollback()
            flash("Could not update project access. Try again.", "error")
    return project_access_response(project_id)
