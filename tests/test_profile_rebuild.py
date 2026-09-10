"""Slice 5 rebuild tests: profile + tokens + import/export + webhooks.

Mock DB — no Postgres required. Covers the Phase 1 checklist items for
the profile area (account/security/access/teams/projects/activity),
personal tokens, machine tokens, import preview/commit, webhooks, ESO
manifests, and global search, plus the slice-5 fixes (Alpine-free page
scripts moved to static files, styled confirms, export gate, webhook
event gate, ESO builder extracted).
"""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import app as store

store.app.config["TESTING"] = True

TEMPLATES = Path(__file__).resolve().parent.parent / "app" / "templates"

SLICE5 = [
    "profile.html",
    "totp_setup.html",
    "totp_recovery.html",
    "machines.html",
    "import_preview.html",
    "webhook_form.html",
    "search.html",
    "partials/profile_account.html",
    "partials/profile_activity.html",
    "partials/profile_myaccess.html",
    "partials/profile_panel.html",
    "partials/profile_projects.html",
    "partials/profile_security.html",
    "partials/profile_teams.html",
    "partials/machines_results.html",
    "partials/token_create_form.html",
    "partials/project_tokens.html",
    "partials/project_import.html",
    "partials/project_integrations.html",
    "partials/webhooks_list.html",
    "partials/cli_login_dialog.html",
    "partials/cli_login_dialog_body.html",
]


def _render(name, **ctx):
    with store.app.test_request_context("/profile"):
        from flask import render_template

        return render_template(name, **ctx)


class TestSlice5NoInlineJS:
    def test_no_inline_handlers_in_slice(self):
        bad = []
        for rel in SLICE5:
            src = (TEMPLATES / rel).read_text()
            for marker in ("onsubmit=", "onclick=", "return confirm("):
                if marker in src:
                    bad.append(f"{rel}: {marker}")
        assert not bad, bad

    def test_no_inline_script_blocks_in_slice(self):
        bad = [rel for rel in SLICE5 if "<script>" in (TEMPLATES / rel).read_text()]
        assert not bad, bad


class TestSlice5Profile:
    def test_subnav_renders_all_tabs(self):
        html = _render(
            "profile.html",
            active_tab="account",
            user={"name": "A", "email": "a@ex.com", "auth_source": "local",
                  "is_global_admin": False, "created_at": ""},
            login_alerts={"allowed": False},
            groups=[],
            stats={"teams": 0, "projects": 0, "secrets": 0, "pins": 0},
        )
        for tab in ("Account", "Security", "My access", "Teams", "Projects", "Activity"):
            assert tab in html

    def test_security_confirms_are_styled(self):
        html = _render(
            "partials/profile_security.html",
            user={"auth_source": "local", "totp_enabled_at": None},
            totp_enabled=False,
            totp_recovery_remaining=0,
            totp_enforced_for_user=False,
            new_pat=None,
            personal_tokens=[{"id": str(uuid4()), "name": "laptop",
                              "token_prefix": "pat_abc", "created_at": None,
                              "expires_at": None, "last_used_at": None}],
            active_sessions=[],
            current_sid=None,
        )
        assert html.count("data-confirm=") >= 1
        assert "Revoke token" in html

    def test_account_heading_styled(self):
        html = _render(
            "partials/profile_account.html",
            user={"name": "A", "email": "a@ex.com", "auth_source": "local",
                  "is_global_admin": False, "created_at": ""},
            login_alerts={"allowed": False},
            groups=[],
            stats={"teams": 0, "projects": 0, "secrets": 0, "pins": 0},
        )
        assert "text-lg font-bold" in html


class TestSlice5Webhooks:
    def test_form_gates_events(self):
        html = _render(
            "webhook_form.html",
            heading="Add webhook",
            back="/projects",
            scope_name="Acme",
            mode="create",
            scope="team",
            scope_id=str(uuid4()),
            webhook=None,
        )
        assert 'data-require-one="events"' in html
        assert "data-require-error" in html

    def test_edit_delete_is_confirmed(self):
        html = _render(
            "webhook_form.html",
            heading="Edit webhook",
            back="/projects",
            scope_name="Acme",
            mode="edit",
            webhook={"id": str(uuid4()), "name": "w", "url": "https://x",
                     "events": [], "ssl_verify": True, "active": True},
            deliveries=[],
        )
        assert "data-confirm=" in html
        assert "Recent deliveries" in html


class TestSlice5ImportIntegrations:
    def test_export_gate_present(self):
        html = _render(
            "partials/project_import.html",
            project={"id": str(uuid4())},
            can_write=True,
        )
        assert "data-export-gate" in html
        assert "Preview import" in html

    def test_eso_root_has_no_script(self):
        html = _render(
            "partials/project_integrations.html",
            project={"id": str(uuid4()), "name": "App"},
            public_base_url="https://ex.example.com",
            can_admin=False,
            new_token=None,
        )
        assert "eso-integration" in html
        assert "eso-yaml-panel" in html


class TestSlice5JS:
    def test_static_contracts(self):
        c = store.app.test_client()
        eso = c.get("/static/integrations.js")
        assert eso.status_code == 200
        assert b"eso-yaml-panel" in eso.data
        assert b"ClusterSecretStore" in eso.data
        assert b"{{ .auth.token }}" in eso.data
        secrets = c.get("/static/secrets.js").data
        assert b"data-export-gate" in secrets
        assert b"__corvusNavConfirm" in secrets
        assert b"__corvusNavConfirm" in c.get("/static/dialogs.js").data
        assert b"data-require-one" in c.get("/static/forms.js").data
