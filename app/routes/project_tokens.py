"""Project machine tokens and team machine list."""

import logging
import secrets
from datetime import datetime, timedelta, timezone

from flask import flash, redirect, render_template, request, session, url_for

from auth import authz
from core import config, db, settings_svc
from crypto import sha256_hex
from secret_svc.secret_kinds import annotate_token_expiry
from ui import nav, paging

log = logging.getLogger(__name__)


def parse_token_scope_lines(raw: str) -> list[tuple[str, str]]:
    """Parse scope lines into (kind, value) pairs: kind is ``key`` or ``pattern``.

    Empty lines and comments (``#``) are ignored. Lines containing ``*`` or ``?``
    become glob patterns; otherwise exact secret keys.
    """
    out: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for line in (raw or "").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if len(line) > 256:
            continue
        kind = "pattern" if (("*" in line) or ("?" in line)) else "key"
        item = (kind, line)
        if item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out


def insert_token_scopes(cur, token_id: str, scopes: list[tuple[str, str]]) -> None:
    """Insert scope rows. Empty list becomes ``*`` (all non-restricted keys)."""
    if not scopes:
        scopes = [("pattern", "*")]
    for kind, val in scopes:
        if kind == "pattern":
            cur.execute(
                """
                INSERT INTO api.machine_token_scope (token_id, key_pattern)
                VALUES (%s::uuid, %s)
                """,
                (token_id, val),
            )
        else:
            cur.execute(
                """
                INSERT INTO api.machine_token_scope (token_id, secret_key)
                VALUES (%s::uuid, %s)
                """,
                (token_id, val),
            )


def register(app):
    """Register machine-token and project-token routes on the Flask app."""
    app.get("/machines")(machines_list)
    app.post("/projects/<uuid:project_id>/tokens")(create_token)
    app.post("/projects/<uuid:project_id>/tokens/<uuid:token_id>/delete")(delete_token)


def load_tokens_tab(cur, project_id):
    """Load tokens-tab rows (annotated tokens with scopes, key suggestions).

    Shared by the full project page and the HTMX tokens partial so the two
    cannot drift apart.

    Args:
        cur: Open DB cursor (user RLS).
        project_id: UUID of the project.

    Returns:
        Dict with ``tokens`` and ``project_secret_keys`` template vars.
    """
    cur.execute(
        """
        SELECT id, name, description, token_prefix, role, created_at, expires_at, last_used_at
        FROM api.machine_tokens
        WHERE project_id = %s
        ORDER BY created_at DESC
        """,
        (str(project_id),),
    )
    tokens = annotate_token_expiry(cur.fetchall())
    # Attach allow-list (empty = no keys after 0011)
    tids = [str(t["id"]) for t in tokens]
    scope_map: dict = {}
    if tids:
        try:
            cur.execute(
                """
                SELECT token_id, secret_key, key_pattern
                FROM api.machine_token_scope
                WHERE token_id = ANY(%s::uuid[])
                ORDER BY secret_key NULLS LAST, key_pattern NULLS LAST
                """,
                (tids,),
            )
            for sc in cur.fetchall() or []:
                scope_map.setdefault(str(sc["token_id"]), []).append(sc)
        except Exception:
            scope_map = {}
    for t in tokens:
        t["scopes"] = scope_map.get(str(t["id"]), [])
    # Suggest existing keys for the allow-list chip input
    try:
        cur.execute(
            """
            SELECT key FROM api.secrets
            WHERE project_id = %s AND deleted_at IS NULL
            ORDER BY key
            LIMIT 200
            """,
            (str(project_id),),
        )
        project_secret_keys = [r["key"] for r in (cur.fetchall() or [])]
    except Exception:
        project_secret_keys = []
    return {"tokens": tokens, "project_secret_keys": project_secret_keys}


def tokens_partial(project_id):
    """Render the tokens-tab partial for HTMX swaps.

    Args:
        project_id: UUID of the project.

    Returns:
        Rendered ``partials/project_content.html`` for the tokens tab,
        or 404 when missing.
    """
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
        tokens_ctx = load_tokens_tab(cur, project_id)
    pname = (project or {}).get("name") or "Project"
    return render_template(
        "partials/project_content.html",
        oob_title=f"Machine accounts - {pname}",
        project=project,
        project_id=project_id,
        can_admin=can_admin,
        active_tab="tokens",
        default_token_days=project.get("default_token_days"),
        max_expiry_days=config.MAX_EXPIRY_DAYS,
        new_token=session.pop("new_token", None),
        **tokens_ctx,
    )


def tokens_response(project_id):
    """Return the tokens-tab partial for HTMX, else redirect to the tokens tab."""
    if authz.htmx():
        return tokens_partial(project_id)
    return redirect(url_for("project_detail", project_id=project_id, tab="tokens"))


@authz.login_required
def machines_list():
    """List machine tokens for all projects under the session team.

    Supports search (``q``) and pagination (``page``). Renders the full page
    for browser loads and the results partial for HTMX swaps.

    Example:
        GET /machines?q=prod&page=2
    """
    tid = nav.ensure_active_team(session["user_id"])
    q = paging.list_state_q()
    team, tokens = None, []
    machines_pager = None
    if tid:
        with db.as_user(session["user_id"]) as conn, conn.cursor() as cur:
            team = db.team(cur, tid)
            if team:
                where = "p.team_id = %s"
                params: list = [tid]
                if q:
                    like = f"%{q}%"
                    where += (
                        " AND (mt.name ILIKE %s OR p.name ILIKE %s OR mt.token_prefix ILIKE %s"
                        " OR mt.description ILIKE %s)"
                    )
                    params.extend([like, like, like, like])
                tokens, machines_pager = paging.paged_rows(
                    cur,
                    f"""
                    SELECT count(*) AS n
                      FROM api.machine_tokens mt
                      JOIN api.projects p ON p.id = mt.project_id
                     WHERE {where}
                    """,
                    f"""
                    SELECT mt.id, mt.name, mt.description, mt.token_prefix, mt.role,
                           mt.created_at, mt.expires_at, mt.last_used_at,
                           p.id AS project_id, p.name AS project_name
                      FROM api.machine_tokens mt
                      JOIN api.projects p ON p.id = mt.project_id
                     WHERE {where}
                     ORDER BY p.name, mt.name
                     LIMIT %s OFFSET %s
                    """,
                    params,
                    endpoint="machines_list",
                    q=q,
                )
                tokens = annotate_token_expiry(tokens)
    template = "partials/machines_results.html" if authz.htmx() else "machines.html"
    return render_template(template, team=team, tokens=tokens, machines_pager=machines_pager, q=q, search_q=q)


@authz.login_required
def create_token(project_id):
    """Create a project machine token; raw secret is shown once via session.

    Args:
        project_id: UUID of the project that owns the token.

    Returns:
        Redirect to the project detail page (return_tab or tokens).

    Example:
        POST /projects/<project_id>/tokens with name, role, expires_days form fields
    """
    name = request.form.get("name", "machine").strip() or "machine"
    description = (request.form.get("description") or "").strip()[:500]
    role = (request.form.get("role") or "service-read").strip()
    if role not in config.MACHINE_TOKEN_ROLES:
        role = "service-read"
    return_tab = (request.form.get("return_tab") or "tokens").strip().lower()
    if return_tab not in (
        "secrets",
        "audit",
        "tokens",
        "import",
        "integrations",
        "settings",
    ):
        return_tab = "tokens"

    def _token_response():
        """Return the tokens tab for HTMX, else redirect to the return tab.

        HTMX posts only come from the tokens tab (which posts no return_tab),
        so any other return tab keeps the legacy redirect.
        """
        if authz.htmx() and return_tab == "tokens":
            return tokens_response(project_id)
        return redirect(url_for("project_detail", project_id=project_id, tab=return_tab))

    expires_at = None
    days_raw = (request.form.get("expires_days") or "").strip()
    require_expiry, max_days = settings_svc.token_expiry_policy("machine")
    with db.as_user(session["user_id"]) as conn, conn.cursor() as cur:
        # Explicit write gate (read-only can list tokens, not create them)
        cur.execute("SELECT api.can_admin_project(%s) AS w", (str(project_id),))
        if not cur.fetchone()["w"]:
            flash("You do not have permission to perform this action", "error")
            return _token_response()
        if not days_raw:
            cur.execute(
                """
                SELECT t.default_token_days
                FROM api.projects p JOIN api.teams t ON t.id = p.team_id
                WHERE p.id = %s
                """,
                (str(project_id),),
            )
            row = cur.fetchone() or {}
            if row.get("default_token_days"):
                days_raw = str(row["default_token_days"])
        if not days_raw and require_expiry:
            flash("Enter an expiry period.", "error")
            return _token_response()
        if days_raw:
            try:
                days = int(days_raw)
            except ValueError:
                flash("Expiry must be a positive number of days.", "error")
                return _token_response()
            if days < 1 or days > max_days:
                flash(
                    f"Expiry must be between 1 and {max_days} days",
                    "error",
                )
                return _token_response()
            expires_at = datetime.now(timezone.utc) + timedelta(days=days)
        raw = "ss_" + secrets.token_urlsafe(32)
        thash = sha256_hex(raw)
        prefix = raw[:11]
        scopes = parse_token_scope_lines(request.form.get("scope_keys") or "")
        try:
            cur.execute(
                """
                INSERT INTO api.machine_tokens
                  (project_id, name, description, token_hash, token_prefix, role, expires_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                RETURNING id
                """,
                (str(project_id), name, description, thash, prefix, role, expires_at),
            )
            row = cur.fetchone()
            if not row:
                flash("You do not have permission to perform this action", "error")
                conn.rollback()
                return _token_response()
            insert_token_scopes(cur, str(row["id"]), scopes)
            conn.commit()
        except Exception:
            flash("Could not complete the request. Try again.", "error")
            return _token_response()
    session["new_token"] = raw  # shown once
    stored = scopes or [("pattern", "*")]
    scope_note = (
        " for all non-restricted keys"
        if stored == [("pattern", "*")]
        else f" scoped to {len(stored)} key rule{'s' if len(stored) != 1 else ''}"
    )
    flash(
        f"Machine account created{scope_note}. Copy the token now. It is shown only once.",
        "ok",
    )
    return _token_response()


@authz.login_required
def delete_token(project_id, token_id):
    """Delete a project machine token.

    Args:
        project_id: UUID of the project that owns the token.
        token_id: UUID of the machine token to delete.

    Returns:
        Redirect to the project tokens tab.

    Example:
        POST /projects/<project_id>/tokens/<token_id>/delete
    """
    with db.as_user(session["user_id"]) as conn, conn.cursor() as cur:
        cur.execute("SELECT api.can_admin_project(%s) AS w", (str(project_id),))
        if not cur.fetchone()["w"]:
            flash("You do not have permission to perform this action", "error")
            return tokens_response(project_id)
        cur.execute(
            "DELETE FROM api.machine_tokens WHERE id = %s AND project_id = %s",
            (str(token_id), str(project_id)),
        )
        if cur.rowcount == 0:
            flash("You do not have permission to perform this action", "error")
        else:
            flash("Machine account revoked", "ok")
        conn.commit()
    return tokens_response(project_id)
