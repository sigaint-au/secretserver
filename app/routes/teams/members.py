"""Team member and access-binding routes."""

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
from auth.roles import (
    MANAGE_TIER,
    OWNER_TIER,
    default_team_role,
    highest_team_role,
    role_names_for_scope,
    roles_for_scope,
    team_role_at_least,
    team_tier_role,
)
from core import config, db
from lib.users import lookup_user_id


def load_members_tab(cur, team_id, is_admin):
    """Load members-tab rows (bindings, invites, pending requests).

    Shared by the full team page and the HTMX members partial so the two
    cannot drift apart.

    Args:
        cur: Open DB cursor (user RLS).
        team_id: UUID of the team.
        is_admin: Whether invite/request rows are visible.

    Returns:
        Tuple ``(members, invites, join_requests)``.
    """
    all_b = rbac_sync.list_scope_bindings(cur, "team", team_id)
    rbac_sync.enrich_binding_emails(all_b)
    team_roles = set(role_names_for_scope(cur, "team"))
    members = [
        b
        for b in all_b
        if b.get("subject_kind") == "User" and str(b.get("role_name") or "") in team_roles
    ]
    invites, join_requests = [], []
    if is_admin:
        cur.execute(
            """
            SELECT id, role, expires_at, created_at, revoked_at
            FROM api.team_invites
            WHERE team_id = %s
            ORDER BY created_at DESC
            LIMIT 20
            """,
            (str(team_id),),
        )
        invites = cur.fetchall()
        cur.execute(
            """
            SELECT r.id, r.role, r.user_id, r.created_at
            FROM api.team_join_requests r
            WHERE r.team_id = %s AND r.status = 'pending'
            ORDER BY r.created_at
            """,
            (str(team_id),),
        )
        join_requests = cur.fetchall() or []
    return members, invites, join_requests


def enrich_join_request_emails(join_requests):
    """Fill email/name on pending join requests (admin lookup)."""
    if not join_requests:
        return
    try:
        with db.connect_admin() as aconn, aconn.cursor() as acur:
            for jr in join_requests:
                acur.execute(
                    "SELECT email, name FROM private.users WHERE id = %s",
                    (str(jr["user_id"]),),
                )
                u = acur.fetchone() or {}
                jr["email"] = u.get("email") or str(jr["user_id"])
                jr["name"] = u.get("name") or ""
    except Exception:
        for jr in join_requests:
            jr.setdefault("email", str(jr.get("user_id")))
            jr.setdefault("name", "")


def members_partial(team_id, *, form_email="", form_role=None):
    """Render the members-tab partial for HTMX swaps.

    Args:
        team_id: UUID of the team.
        form_email: Previously typed email to preserve after a failed add.
        form_role: Previously selected role to preserve after a failed add.

    Returns:
        Rendered ``partials/team_members.html``, or 404 when invisible.
    """
    with db.as_user(session["user_id"]) as conn, conn.cursor() as cur:
        team = db.team(cur, team_id)
        if not team:
            return "Not found", 404
        cur.execute("SELECT api.team_role(%s) AS r", (str(team_id),))
        my_role = (cur.fetchone() or {}).get("r")
        cur.execute(
            "SELECT api.can_manage_rbac('team', %s::uuid) AS ok",
            (str(team_id),),
        )
        can_edit_access = bool((cur.fetchone() or {}).get("ok"))
        is_admin = (
            team_role_at_least(cur, my_role, MANAGE_TIER)
            or bool(session.get("is_global_admin"))
            or can_edit_access
        )
        members, invites, join_requests = load_members_tab(cur, team_id, is_admin)
        top_role = highest_team_role(cur) or OWNER_TIER
        dropdown = roles_for_scope(cur, "team")
        default_role = default_team_role(cur)
        if not form_role:
            form_role = default_role
    enrich_join_request_emails(join_requests)
    return render_template(
        "partials/team_members.html",
        team=team,
        members=members,
        invites=invites,
        join_requests=join_requests,
        my_role=my_role,
        is_admin=is_admin,
        active_tab="members",
        team_role_dropdown=dropdown,
        form_email=form_email,
        form_role=form_role,
        top_role=top_role,
        default_role=default_role,
        new_invite_url=session.pop("new_invite_url", None),
    )


def members_response(team_id, *, form_email="", form_role=None):
    """Return the members partial for HTMX, else redirect to the members tab."""
    if authz.htmx():
        return members_partial(team_id, form_email=form_email, form_role=form_role)
    return redirect(url_for("team_detail", team_id=team_id, tab="members"))


def load_access_tab(cur, team_id):
    """Load access-tab rows (all team-scope bindings, groups, role descriptions).

    Shared by the full team page and the HTMX access partial so the two
    cannot drift apart.

    Args:
        cur: Open DB cursor (user RLS).
        team_id: UUID of the team.

    Returns:
        Tuple ``(access_bindings, access_groups, role_descriptions)``.
    """
    access_bindings = rbac_sync.list_scope_bindings(cur, "team", team_id)
    rbac_sync.enrich_binding_emails(access_bindings)
    cur.execute(
        "SELECT id, name FROM api.groups WHERE team_id = %s ORDER BY name",
        (str(team_id),),
    )
    access_groups = list(cur.fetchall() or [])
    try:
        cur.execute("SELECT name, description FROM rbac.roles")
        role_descriptions = {
            r["name"]: (r.get("description") or "") for r in (cur.fetchall() or [])
        }
    except Exception:
        role_descriptions = {}
    return access_bindings, access_groups, role_descriptions


def access_tab_partial(team_id):
    """Render the access-tab partial for HTMX swaps.

    Args:
        team_id: UUID of the team.

    Returns:
        Rendered ``partials/team_content.html`` for the access tab,
        or 404 when invisible.
    """
    with db.as_user(session["user_id"]) as conn, conn.cursor() as cur:
        team = db.team(cur, team_id)
        if not team:
            return "Not found", 404
        cur.execute("SELECT api.team_role(%s) AS r", (str(team_id),))
        my_role = (cur.fetchone() or {}).get("r")
        cur.execute(
            "SELECT api.can_manage_rbac('team', %s::uuid) AS ok",
            (str(team_id),),
        )
        can_edit_access = bool((cur.fetchone() or {}).get("ok"))
        is_admin = (
            team_role_at_least(cur, my_role, MANAGE_TIER)
            or bool(session.get("is_global_admin"))
            or can_edit_access
        )
        if not is_admin:
            return "Not found", 404
        access_bindings, access_groups, role_descriptions = load_access_tab(cur, team_id)
        team_role_dropdown = roles_for_scope(cur, "team")
    rbac_sync.enrich_binding_emails(access_bindings)
    tname = (team or {}).get("name") or "Team"
    return render_template(
        "partials/team_content.html",
        oob_title=f"Access - {tname}",
        team=team,
        is_admin=is_admin,
        active_tab="access",
        access_bindings=access_bindings,
        access_groups=access_groups,
        can_edit_access=True,
        team_role_dropdown=team_role_dropdown,
        role_descriptions=role_descriptions,
        subject_kinds=config.RBAC_SUBJECT_KINDS,
    )


def access_tab_response(team_id):
    """Return the access-tab partial for HTMX, else redirect to the access tab."""
    if authz.htmx():
        return access_tab_partial(team_id)
    return redirect(url_for("team_detail", team_id=team_id, tab="access"))


def team_meta_partial(team_id):
    """Render the metadata-tab partial for HTMX swaps.

    Args:
        team_id: UUID of the team.

    Returns:
        Rendered ``partials/team_content.html`` for the meta tab,
        or 404 when invisible.
    """
    with db.as_user(session["user_id"]) as conn, conn.cursor() as cur:
        team = db.team(cur, team_id)
        if not team:
            return "Not found", 404
        cur.execute("SELECT api.team_role(%s) AS r", (str(team_id),))
        my_role = (cur.fetchone() or {}).get("r")
        cur.execute(
            "SELECT key, value, updated_at FROM api.team_meta WHERE team_id = %s ORDER BY key",
            (str(team_id),),
        )
        team_meta = cur.fetchall() or []
        is_admin = (
            team_role_at_least(cur, my_role, MANAGE_TIER)
            or bool(session.get("is_global_admin"))
        )
    tname = (team or {}).get("name") or "Team"
    return render_template(
        "partials/team_content.html",
        oob_title=f"Metadata - {tname}",
        team=team,
        is_admin=is_admin,
        active_tab="meta",
        team_meta=team_meta,
    )


def team_meta_response(team_id):
    """Return the metadata-tab partial for HTMX, else redirect to the meta tab."""
    if authz.htmx():
        return team_meta_partial(team_id)
    return redirect(url_for("team_detail", team_id=team_id, tab="meta"))


def load_groups_tab(cur, team_id, q=""):
    """Load groups-tab rows (team groups filtered by search).

    Shared by the full team page and the HTMX groups partial so the two
    cannot drift apart.

    Args:
        cur: Open DB cursor (user RLS).
        team_id: UUID of the team.
        q: Search filter (name, external key, or source).

    Returns:
        Filtered list of group rows.
    """
    try:
        cur.execute(
            "SELECT * FROM private.team_group_rows(%s::uuid)",
            (str(team_id),),
        )
        groups = list(cur.fetchall() or [])
    except Exception:
        groups = []
    if q:
        ql = q.lower()
        groups = [
            g
            for g in groups
            if ql in (g.get("name") or "").lower()
            or ql in (g.get("external_key") or "").lower()
            or ql in (g.get("source") or "").lower()
        ]
    return groups


def groups_partial(team_id):
    """Render the groups-tab partial for HTMX swaps.

    Args:
        team_id: UUID of the team.

    Returns:
        Rendered ``partials/team_content.html`` for the groups tab,
        or 404 when missing.
    """
    q = (request.args.get("q") or "").strip()
    with db.as_user(session["user_id"]) as conn, conn.cursor() as cur:
        team = db.team(cur, team_id)
        if not team:
            return "Not found", 404
        cur.execute("SELECT api.team_role(%s) AS r", (str(team_id),))
        my_role = (cur.fetchone() or {}).get("r")
        cur.execute(
            "SELECT api.can_manage_rbac('team', %s::uuid) AS ok",
            (str(team_id),),
        )
        can_edit_access = bool((cur.fetchone() or {}).get("ok"))
        is_admin = (
            team_role_at_least(cur, my_role, MANAGE_TIER)
            or bool(session.get("is_global_admin"))
            or can_edit_access
        )
        groups = load_groups_tab(cur, team_id, q)
    tname = (team or {}).get("name") or "Team"
    return render_template(
        "partials/team_content.html",
        oob_title=f"Groups - {tname}",
        team=team,
        is_admin=is_admin,
        active_tab="groups",
        groups=groups,
        search_q=q,
    )


def groups_response(team_id):
    """Return the groups-tab partial for HTMX, else redirect to the groups tab."""
    if authz.htmx():
        return groups_partial(team_id)
    return redirect(url_for("team_detail", team_id=team_id, tab="groups"))


@authz.login_required
def team_access_binding_create(team_id):
    """Create a team-scope role binding (team admin)."""
    role_name = (request.form.get("role_name") or "").strip()
    subject_kind = (request.form.get("subject_kind") or "User").strip()
    subject_email = (request.form.get("subject_email") or "").strip().lower()
    subject_group = (request.form.get("subject_group") or "").strip()
    subject_sa = (request.form.get("subject_sa") or "").strip()
    with db.as_user(session["user_id"]) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT api.can_manage_rbac('team', %s::uuid) AS ok",
            (str(team_id),),
        )
        if not (cur.fetchone() or {}).get("ok"):
            flash("Only team admins can manage role bindings", "error")
            return access_tab_response(team_id)
        try:
            cur.execute("SELECT id FROM rbac.roles WHERE name = %s", (role_name,))
            role = cur.fetchone()
            if not role:
                flash("Unknown role.", "error")
                return access_tab_response(team_id)
            subject_id = None
            if subject_kind == "User":
                subject_id = lookup_user_id(cur, subject_email)
                if not subject_id:
                    flash("No account found for that email address.", "error")
                    return access_tab_response(team_id)
            elif subject_kind == "Group":
                cur.execute(
                    """
                    SELECT id FROM api.groups
                    WHERE id = %s::uuid AND team_id = %s::uuid
                    """,
                    (subject_group, str(team_id)),
                )
                g = cur.fetchone()
                if not g:
                    flash("Group not found in this team", "error")
                    return access_tab_response(team_id)
                subject_id = str(g["id"])
            elif subject_kind == "ServiceAccount":
                subject_id = subject_sa
            else:
                flash("Invalid subject kind.", "error")
                return access_tab_response(team_id)
            if not subject_id:
                flash("Subject required", "error")
                return access_tab_response(team_id)
            cur.execute(
                """
                INSERT INTO rbac.bindings
                  (role_id, subject_kind, subject_id, scope_kind, scope_id, created_by)
                VALUES (%s::uuid, %s, %s::uuid, 'team', %s::uuid, %s::uuid)
                """,
                (
                    str(role["id"]),
                    subject_kind,
                    subject_id,
                    str(team_id),
                    session["user_id"],
                ),
            )
            conn.commit()
            flash("Binding created", "ok")
        except Exception:
            conn.rollback()
            flash("Could not update team membership. Try again.", "error")
    return access_tab_response(team_id)


@authz.login_required
def team_access_binding_delete(team_id, binding_id):
    """Remove a team-scope role binding (team admin)."""
    with db.as_user(session["user_id"]) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT api.can_manage_rbac('team', %s::uuid) AS ok",
            (str(team_id),),
        )
        if not (cur.fetchone() or {}).get("ok"):
            flash("Only team admins can manage role bindings", "error")
            return access_tab_response(team_id)
        try:
            cur.execute(
                """
                DELETE FROM rbac.bindings
                WHERE id = %s::uuid
                  AND scope_kind = 'team'
                  AND scope_id = %s::uuid
                """,
                (str(binding_id), str(team_id)),
            )
            if cur.rowcount:
                conn.commit()
                flash("Binding removed", "ok")
            else:
                conn.rollback()
                flash("Binding not found. or not permitted.", "error")
        except Exception:
            conn.rollback()
            flash("Could not update team membership. Try again.", "error")
    return access_tab_response(team_id)


@authz.login_required
def add_team_binding(team_id):
    """Add or update a team member by email and role.

    Args:
        team_id: UUID of the team to modify.

    Returns:
        Redirect to the team members tab.

    Example:
        POST /teams/<team_id>/members with email and role form fields
    """
    email = request.form.get("email", "").strip().lower()
    raw_role = (request.form.get("role") or "").strip()
    with db.as_user(session["user_id"]) as conn, conn.cursor() as cur:
        role_names = role_names_for_scope(cur, "team")
        role = raw_role if raw_role in role_names else default_team_role(cur)
        # Only the top tier may grant the top role (admins cannot self-promote)
        top_role = highest_team_role(cur) or OWNER_TIER
        cur.execute("SELECT api.team_role(%s) AS r", (str(team_id),))
        my_role = (cur.fetchone() or {}).get("r")
        if role == top_role and not team_role_at_least(cur, my_role, OWNER_TIER):
            flash("Only a team owner can assign the owner role", "error")
            return members_response(team_id, form_email=email, form_role=role)
        uid = lookup_user_id(cur, email)
        if not uid:
            flash("No account found for that email address.", "error")
            return members_response(team_id, form_email=email, form_role=role)
        try:
            # Check for existing binding to determine add vs update
            rname = role
            cur.execute("SELECT id FROM rbac.roles WHERE name = %s", (rname,))
            role_row = cur.fetchone()
            if not role_row:
                flash(f"Role {rname} missing — run schema ensure", "error")
                return members_response(team_id, form_email=email, form_role=role)
            # Check existing team binding for this user
            cur.execute(
                """
                SELECT b.id, r.name AS role_name
                FROM rbac.bindings b
                JOIN rbac.roles r ON r.id = b.role_id
                WHERE b.subject_kind = 'User' AND b.subject_id = %s::uuid
                  AND b.scope_kind = 'team' AND b.scope_id = %s::uuid
                  AND 'team' = ANY (r.scopes)
                """,
                (uid, str(team_id)),
            )
            prev = cur.fetchone()
            rbac_sync.sync_user_team_binding(
                cur,
                user_id=uid,
                team_id=team_id,
                role=role,
                created_by=session["user_id"],
            )
            action = audit.ORG_MEMBER_ROLE if prev else audit.ORG_MEMBER_ADD
            detail = f"{email} → {role}"
            if prev:
                detail = f"{email}: {prev['role_name']} → {role}"
            audit.log_org(cur, team_id=team_id, action=action, detail=detail)
            conn.commit()
            flash(f"Bound {email} as {role}", "ok")
        except Exception:
            conn.rollback()
            flash("Could not update team membership. Try again.", "error")
            return members_response(team_id, form_email=email, form_role=role)
    return members_response(team_id)


@authz.login_required
def remove_team_binding(team_id, user_id):
    """Remove a member from a team.

    Args:
        team_id: UUID of the team.
        user_id: UUID of the user to remove.

    Returns:
        Redirect to the team members tab.

    Example:
        POST /teams/<team_id>/members/<user_id>/remove
    """
    with db.as_user(session["user_id"]) as conn, conn.cursor() as cur:
        try:
            # Find existing team binding for this user
            cur.execute(
                """
                SELECT b.id, r.name AS role_name
                FROM rbac.bindings b
                JOIN rbac.roles r ON r.id = b.role_id
                WHERE b.subject_kind = 'User' AND b.subject_id = %s::uuid
                  AND b.scope_kind = 'team' AND b.scope_id = %s::uuid
                  AND 'team' = ANY (r.scopes)
                """,
                (str(user_id), str(team_id)),
            )
            row = cur.fetchone()
            if not row:
                flash("Member not found", "error")
                return members_response(team_id)
            rbac_sync.sync_user_team_binding(
                cur, user_id=user_id, team_id=team_id, role=None
            )
            audit.log_org(
                cur,
                team_id=team_id,
                action=audit.ORG_MEMBER_REMOVE,
                detail=f"user {user_id} ({row['role_name']})",
            )
            conn.commit()
            flash("Member removed", "ok")
        except Exception:
            conn.rollback()
            flash("Could not update team membership. Try again.", "error")
    return members_response(team_id)


@authz.login_required
def transfer_team_ownership(team_id):
    """Transfer team ownership to another registered user by email.

    Args:
        team_id: UUID of the team whose ownership is transferred.

    Returns:
        Redirect to the team settings tab.

    Example:
        POST /teams/<team_id>/transfer with form field email=newowner@example.com
    """
    email = (request.form.get("email") or "").strip().lower()
    if not email:
        flash("Enter an email address", "error")
        return redirect(url_for("team_detail", team_id=team_id, tab="settings"))
    with db.as_user(session["user_id"]) as conn, conn.cursor() as cur:
        cur.execute("SELECT api.team_role(%s) AS r", (str(team_id),))
        if not team_role_at_least(cur, (cur.fetchone() or {}).get("r"), OWNER_TIER):
            flash("Only owners can transfer ownership", "error")
            return redirect(url_for("team_detail", team_id=team_id, tab="settings"))
        new_uid = lookup_user_id(cur, email)
        if not new_uid:
            flash("No account found for that email address.", "error")
            return redirect(url_for("team_detail", team_id=team_id, tab="settings"))
        if new_uid == session["user_id"]:
            flash("Already owner", "ok")
            return redirect(url_for("team_detail", team_id=team_id, tab="settings"))
        try:
            # Promote new owner first (avoids last-owner guard)
            rbac_sync.sync_user_team_binding(
                cur,
                user_id=new_uid,
                team_id=team_id,
                role=highest_team_role(cur) or OWNER_TIER,
                created_by=session["user_id"],
            )
            rbac_sync.sync_user_team_binding(
                cur,
                user_id=session["user_id"],
                team_id=team_id,
                role=team_tier_role(cur, MANAGE_TIER),
                created_by=session["user_id"],
            )
            audit.log_org(
                cur,
                team_id=team_id,
                action=audit.ORG_OWNERSHIP,
                detail=f"ownership → {email}",
            )
            conn.commit()
            flash(f"Ownership transferred to {email}", "ok")
        except Exception:
            conn.rollback()
            flash("Could not update team membership. Try again.", "error")
    return redirect(url_for("team_detail", team_id=team_id, tab="settings"))
