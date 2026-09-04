"""Project secret-folder pages and access bindings."""

from __future__ import annotations

from flask import flash, redirect, render_template, request, session, url_for

import audit
from auth import authz, rbac_sync
from core import config, db
from lib.users import lookup_user_id
from auth.roles import role_allowed_at_scope
from secret_svc.folders import delete_empty_folder, materialize_folder_path
from secret_svc.secret_ops import _parse_access_mode
from ui import paging


def _folder_access_url(project_id, folder_id):
    return url_for("folder_view", project_id=project_id, folder_id=folder_id, tab="access")


def load_folder_access(cur, conn, project_id, folder_id, team_id, *, page=1, q=""):
    """Load folder access-tab rows (bindings, effective access, groups).

    Shared by the full folder page and the HTMX access partial so the two
    cannot drift apart.

    Args:
        cur: Open DB cursor (user RLS).
        conn: Open DB connection (rolled back when the effective-access
            lookup fails, matching the folder route).
        project_id: UUID of the owning project (effective-access pager).
        folder_id: UUID of the folder.
        team_id: UUID of the owning team (for the group dropdown).
        page: Effective-access page number.
        q: Effective-access search filter.

    Returns:
        Dict of template vars for the access branch of
        ``partials/folder_panel.html``.
    """
    from auth.roles import roles_for_scope

    role_dropdown = roles_for_scope(cur, "folder")
    access_bindings = rbac_sync.list_scope_bindings(cur, "folder", folder_id)
    rbac_sync.enrich_binding_emails(access_bindings)
    cur.execute(
        "SELECT id, name FROM api.groups WHERE team_id = %s ORDER BY name",
        (str(team_id),),
    )
    access_groups = list(cur.fetchall() or [])
    try:
        cur.execute(
            "SELECT * FROM api.effective_access_rows('folder', %s::uuid)",
            (str(folder_id),),
        )
        effective_access = list(cur.fetchall() or [])
    except Exception:
        conn.rollback()
        effective_access = []
    effective_access = rbac_sync.enrich_effective_access(effective_access)
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
        endpoint="folder_view",
        project_id=project_id,
        folder_id=folder_id,
        tab="access",
        q=effective_access_q or None,
    )
    start = (page - 1) * effective_access_pager["per_page"]
    effective_access = effective_access[start : start + effective_access_pager["per_page"]]
    return {
        "access_bindings": access_bindings,
        "access_groups": access_groups,
        "effective_access": effective_access,
        "effective_access_q": effective_access_q,
        "effective_access_pager": effective_access_pager,
        "role_dropdown": role_dropdown,
    }


def folder_access_partial(project_id, folder_id):
    """Render the folder access-tab partial for HTMX swaps.

    Args:
        project_id: UUID of the owning project.
        folder_id: UUID of the folder.

    Returns:
        Rendered ``partials/folder_panel.html`` for the access tab,
        or 404 when invisible.
    """
    page = int(request.args.get("page") or 1)
    q = (request.args.get("q") or "").strip()
    with db.as_user(session["user_id"]) as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, project_id, name, path, access_mode
            FROM api.folders
            WHERE id = %s::uuid AND project_id = %s::uuid
            """,
            (str(folder_id), str(project_id)),
        )
        folder = cur.fetchone()
        if not folder:
            return "Not found", 404
        cur.execute(
            """
            SELECT p.id, p.name, p.team_id, t.name AS team_name
            FROM api.projects p JOIN api.teams t ON t.id = p.team_id
            WHERE p.id = %s::uuid
            """,
            (str(project_id),),
        )
        project = cur.fetchone()
        if not project:
            return "Not found", 404
        cur.execute("SELECT api.can_admin_project(%s) AS a", (str(project_id),))
        can_admin = bool((cur.fetchone() or {}).get("a"))
        if not can_admin:
            return "Not found", 404
        access_ctx = load_folder_access(
            cur, conn, project_id, folder_id, project["team_id"], page=page, q=q
        )
    path = (folder or {}).get("path") or "Folder"
    return render_template(
        "partials/folder_panel.html",
        oob_title=f"Access - {path}",
        folder=folder,
        project=project,
        project_id=project_id,
        folder_id=folder_id,
        active_tab="access",
        can_admin=can_admin,
        can_edit_access=can_admin,
        subject_kinds=config.RBAC_SUBJECT_KINDS,
        access_modes=config.ACCESS_MODES,
        access_mode_labels=config.ACCESS_MODE_LABELS,
        **access_ctx,
    )


def folder_access_response(project_id, folder_id):
    """Return the folder access-tab partial for HTMX, else redirect to it."""
    if authz.htmx():
        return folder_access_partial(project_id, folder_id)
    return redirect(_folder_access_url(project_id, folder_id))


@authz.login_required
def folder_view(project_id, folder_id):
    """Render a folder's direct contents or project-admin access bindings."""
    active_tab = (request.args.get("tab") or "contents").strip().lower()
    if active_tab not in ("contents", "access"):
        active_tab = "contents"
    page = int(request.args.get("page") or 1)
    folder = None
    project = None
    can_admin = False
    child_folders = []
    secrets = []
    access_bindings = []
    access_groups = []
    effective_access = []
    effective_access_q = ""
    effective_access_pager = None
    with db.as_user(session["user_id"]) as conn, conn.cursor() as cur:
        from auth.roles import roles_for_scope

        folder_role_dropdown = roles_for_scope(cur, "folder")
        cur.execute(
            """
            SELECT id, project_id, name, path, access_mode
            FROM api.folders
            WHERE id = %s::uuid AND project_id = %s::uuid
            """,
            (str(folder_id), str(project_id)),
        )
        folder = cur.fetchone()
        if not folder:
            return "Not found", 404
        cur.execute(
            """
            SELECT p.id, p.name, p.team_id, t.name AS team_name
            FROM api.projects p JOIN api.teams t ON t.id = p.team_id
            WHERE p.id = %s::uuid
            """,
            (str(project_id),),
        )
        project = cur.fetchone()
        if not project:
            return "Not found", 404
        cur.execute("SELECT api.can_admin_project(%s) AS a", (str(project_id),))
        can_admin = bool((cur.fetchone() or {}).get("a"))
        if active_tab == "access" and not can_admin:
            active_tab = "contents"
        if active_tab == "contents":
            cur.execute(
                """
                SELECT id, name, path, access_mode
                FROM api.folders
                WHERE project_id = %s::uuid AND parent_id = %s::uuid
                ORDER BY name
                """,
                (str(project_id), str(folder_id)),
            )
            child_folders = list(cur.fetchall() or [])
            cur.execute(
                """
                SELECT id, key, note, kind, updated_at, access_mode
                FROM api.secrets
                WHERE project_id = %s::uuid AND folder_id = %s::uuid
                  AND deleted_at IS NULL
                ORDER BY key
                """,
                (str(project_id), str(folder_id)),
            )
            secrets = list(cur.fetchall() or [])
        else:
            access_ctx = load_folder_access(
                cur,
                conn,
                project_id,
                folder_id,
                project["team_id"],
                page=page,
                q=request.args.get("q") or "",
            )
            access_bindings = access_ctx["access_bindings"]
            access_groups = access_ctx["access_groups"]
            effective_access = access_ctx["effective_access"]
            effective_access_q = access_ctx["effective_access_q"]
            effective_access_pager = access_ctx["effective_access_pager"]
            folder_role_dropdown = access_ctx["role_dropdown"]
    template = "partials/folder_panel.html" if authz.htmx() else "folder_view.html"
    oob = {}
    if authz.htmx():
        path = (folder or {}).get("path") or "Folder"
        oob["oob_title"] = path if active_tab == "contents" else f"Access - {path}"
    return render_template(
        template,
        **oob,
        folder=folder,
        project=project,
        project_id=project_id,
        folder_id=folder_id,
        active_tab=active_tab,
        can_admin=can_admin,
        can_edit_access=can_admin,
        child_folders=child_folders,
        secrets=secrets,
        access_bindings=access_bindings,
        access_groups=access_groups,
        effective_access=effective_access,
        effective_access_q=effective_access_q,
        effective_access_pager=effective_access_pager,
        role_dropdown=folder_role_dropdown,
        subject_kinds=config.RBAC_SUBJECT_KINDS,
        access_modes=config.ACCESS_MODES,
        access_mode_labels=config.ACCESS_MODE_LABELS,
    )


@authz.login_required
def update_folder_access(project_id, folder_id):
    """Set a folder's inherit/restricted access mode."""
    try:
        mode = _parse_access_mode(request.form)
    except ValueError:
        flash("Invalid access mode", "error")
        return folder_access_response(project_id, folder_id)
    with db.as_user(session["user_id"]) as conn, conn.cursor() as cur:
        cur.execute("SELECT api.can_admin_project(%s) AS a", (str(project_id),))
        if not (cur.fetchone() or {}).get("a"):
            flash("Only project admins can change folder access", "error")
            return folder_access_response(project_id, folder_id)
        cur.execute(
            """
            UPDATE api.folders SET access_mode = %s
            WHERE id = %s::uuid AND project_id = %s::uuid
            RETURNING path
            """,
            (mode, str(folder_id), str(project_id)),
        )
        row = cur.fetchone()
        if row:
            audit.log_org(
                cur,
                action="FOLDER_ACCESS_UPDATED",
                detail=f"{row['path']} access mode: {mode}",
                project_id=project_id,
            )
            conn.commit()
            flash("Folder access settings saved", "ok")
        else:
            conn.rollback()
            flash("Folder not found.", "error")
    return folder_access_response(project_id, folder_id)


@authz.login_required
def add_folder_access_binding(project_id, folder_id):
    """Bind a user, group, or machine account to a folder role."""
    subject_kind = (request.form.get("subject_kind") or "User").strip()
    email = (request.form.get("subject_email") or "").strip().lower()
    group_id = (request.form.get("subject_group") or "").strip()
    sa_id = (request.form.get("subject_sa") or "").strip()
    raw_role_name = (request.form.get("role_name") or "").strip()
    if subject_kind not in config.RBAC_SUBJECT_KINDS:
        flash("Invalid subject or role", "error")
        return folder_access_response(project_id, folder_id)
    if subject_kind == "User" and not email:
        flash("Enter an email address.", "error")
        return folder_access_response(project_id, folder_id)
    if subject_kind == "Group" and not group_id:
        flash("Select a group.", "error")
        return folder_access_response(project_id, folder_id)
    if subject_kind == "ServiceAccount" and not sa_id:
        flash("Enter a machine account ID.", "error")
        return folder_access_response(project_id, folder_id)
    with db.as_user(session["user_id"]) as conn, conn.cursor() as cur:
        from auth.roles import default_role_for_scope, role_names_for_scope

        cur.execute("SELECT api.can_admin_project(%s) AS a", (str(project_id),))
        if not (cur.fetchone() or {}).get("a"):
            flash("Only project admins can manage folder bindings", "error")
            return folder_access_response(project_id, folder_id)
        role_name = (
            raw_role_name
            if raw_role_name in role_names_for_scope(cur, "folder")
            else default_role_for_scope(cur, "folder")
        )
        cur.execute(
            """
            SELECT f.path, p.team_id
            FROM api.folders f JOIN api.projects p ON p.id = f.project_id
            WHERE f.id = %s::uuid AND f.project_id = %s::uuid
            """,
            (str(folder_id), str(project_id)),
        )
        folder = cur.fetchone()
        cur.execute("SELECT id FROM rbac.roles WHERE name = %s", (role_name,))
        role = cur.fetchone()
        if not folder or not role:
            flash("Folder or role not found", "error")
            return folder_access_response(project_id, folder_id)
        if not role_allowed_at_scope(cur, role_name, "folder"):
            flash("That role cannot be assigned at folder scope", "error")
            return folder_access_response(project_id, folder_id)
        if subject_kind == "User":
            subject_id = lookup_user_id(cur, email)
            if not subject_id:
                flash("No account found for that email address.", "error")
                return folder_access_response(project_id, folder_id)
        elif subject_kind == "Group":
            cur.execute(
                "SELECT id FROM api.groups WHERE id = %s::uuid AND team_id = %s::uuid",
                (group_id, str(folder["team_id"])),
            )
            group = cur.fetchone()
            if not group:
                flash("Group not found in this team", "error")
                return folder_access_response(project_id, folder_id)
            subject_id = group["id"]
        else:
            cur.execute(
                "SELECT id FROM api.machine_tokens WHERE id = %s::uuid AND project_id = %s::uuid",
                (sa_id, str(project_id)),
            )
            machine = cur.fetchone()
            if not machine:
                flash("Machine account not found in this project", "error")
                return folder_access_response(project_id, folder_id)
            subject_id = machine["id"]
        cur.execute(
            """
            DELETE FROM rbac.bindings
            WHERE scope_kind = 'folder' AND scope_id = %s::uuid
              AND subject_kind = %s AND subject_id = %s::uuid
            """,
            (str(folder_id), subject_kind, str(subject_id)),
        )
        cur.execute(
            """
            INSERT INTO rbac.bindings
              (role_id, subject_kind, subject_id, scope_kind, scope_id, created_by)
            VALUES (%s::uuid, %s, %s::uuid, 'folder', %s::uuid, %s::uuid)
            """,
            (str(role["id"]), subject_kind, str(subject_id), str(folder_id), session["user_id"]),
        )
        audit.log_org(
            cur,
            action="FOLDER_BINDING_UPDATED",
            detail=f"{folder['path']} bound {subject_kind} as {role_name}",
            project_id=project_id,
        )
        conn.commit()
        flash("Folder binding added", "ok")
    return folder_access_response(project_id, folder_id)


@authz.login_required
def delete_folder_access_binding(project_id, folder_id, binding_id):
    """Remove a folder-scope role binding."""
    with db.as_user(session["user_id"]) as conn, conn.cursor() as cur:
        cur.execute("SELECT api.can_admin_project(%s) AS a", (str(project_id),))
        if not (cur.fetchone() or {}).get("a"):
            flash("Only project admins can manage folder bindings", "error")
            return folder_access_response(project_id, folder_id)
        cur.execute(
            """
            DELETE FROM rbac.bindings b
            USING api.folders f
            WHERE b.id = %s::uuid AND b.scope_kind = 'folder'
              AND b.scope_id = f.id AND f.id = %s::uuid
              AND f.project_id = %s::uuid
            RETURNING f.path
            """,
            (str(binding_id), str(folder_id), str(project_id)),
        )
        row = cur.fetchone()
        if row:
            audit.log_org(
                cur,
                action="FOLDER_BINDING_UPDATED",
                detail=f"{row['path']} binding removed",
                project_id=project_id,
            )
            conn.commit()
            flash("Binding removed", "ok")
        else:
            conn.rollback()
            flash("Binding not found.", "error")
    return folder_access_response(project_id, folder_id)


@authz.login_required
def create_folder(project_id):
    """Create an empty folder from a slash-separated path."""
    back_url = url_for("project_detail", project_id=project_id, tab="secrets")
    ret = (request.form.get("back") or "").strip()
    if ret.startswith("/") and not ret.startswith("//"):
        back_url = ret
    path = (request.form.get("path") or "").strip().strip("/")
    if not path:
        flash("Invalid folder path", "error")
        return redirect(back_url)
    parts = path.split("/")
    if any(not p or p in {".", ".."} for p in parts):
        flash("Invalid folder path", "error")
        return redirect(back_url)
    with db.as_user(session["user_id"]) as conn, conn.cursor() as cur:
        cur.execute("SELECT api.can_write_project(%s) AS a", (str(project_id),))
        if not (cur.fetchone() or {}).get("a"):
            flash("Only project writers can create folders", "error")
            return redirect(back_url)
        segments = tuple(path.split("/"))
        folder_id = materialize_folder_path(cur, str(project_id), segments)
        if folder_id:
            audit.log_org(
                cur,
                action="FOLDER_CREATED",
                detail=f"Folder created: {path}",
                project_id=project_id,
            )
            conn.commit()
            flash(f"Folder «{path}» created", "ok")
        else:
            conn.rollback()
            flash("Could not create folder", "error")
    return redirect(back_url)


@authz.login_required
def delete_folder(project_id, folder_id):
    """Delete an empty folder and any empty descendants."""
    back_url = url_for("project_detail", project_id=project_id, tab="secrets")
    with db.as_user(session["user_id"]) as conn, conn.cursor() as cur:
        cur.execute("SELECT api.can_admin_project(%s) AS a", (str(project_id),))
        if not (cur.fetchone() or {}).get("a"):
            flash("Only project admins can delete folders", "error")
            return redirect(back_url)
        try:
            deleted = delete_empty_folder(cur, project_id, folder_id)
        except ValueError:
            conn.rollback()
            flash("Folder contains secrets", "error")
            return redirect(url_for("folder_view", project_id=project_id, folder_id=folder_id))
        if not deleted:
            conn.rollback()
            flash("Folder not found.", "error")
        else:
            conn.commit()
            flash("Folder deleted", "ok")
    return redirect(back_url)
