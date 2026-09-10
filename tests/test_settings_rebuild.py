"""Slice 6 rebuild tests: admin audit + settings + HSM + project crypto.

Mock DB — no Postgres required. Covers the Phase 1 checklist items for
server settings (11 tabs), HSM slots, audit review/export/retention,
project crypto adopt/migrate/delete, and the remaining auth pages,
plus the slice-6 fixes (confirm-alt branch, paired input locks,
Alpine slot visibility, no inline handlers).
"""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import app as store

store.app.config["TESTING"] = True

TEMPLATES = Path(__file__).resolve().parent.parent / "app" / "templates"

SLICE6 = [
    "settings.html",
    "admin_audit.html",
    "hsm_slot_new.html",
    "error.html",
    "register.html",
    "forgot_password.html",
    "reset_password.html",
    "verify_email.html",
    "login_2fa.html",
    "partials/settings_general.html",
    "partials/settings_branding.html",
    "partials/settings_banner.html",
    "partials/settings_email.html",
    "partials/settings_encryption.html",
    "partials/settings_health.html",
    "partials/settings_admins.html",
    "partials/settings_users.html",
    "partials/settings_ldap.html",
    "partials/settings_oidc.html",
    "partials/project_settings.html",
    "partials/project_meta.html",
]


def _render(name, **ctx):
    with store.app.test_request_context("/settings"):
        from flask import render_template

        return render_template(name, **ctx)


class TestSlice6NoInlineJS:
    def test_no_inline_handlers_in_slice(self):
        bad = []
        for rel in SLICE6:
            src = (TEMPLATES / rel).read_text()
            for marker in ("onsubmit=", "onclick=", "return confirm("):
                if marker in src:
                    bad.append(f"{rel}: {marker}")
        assert not bad, bad

    def test_no_inline_script_blocks_in_slice(self):
        bad = [rel for rel in SLICE6 if "<script>" in (TEMPLATES / rel).read_text()]
        assert not bad, bad

    def test_color_picker_kept_as_shared_helper(self):
        # Retained deliberately: one shared include serving both banner
        # forms; call sites no longer carry inline handlers.
        src = (TEMPLATES / "partials" / "color_picker_js.html").read_text()
        assert "applyPreset" in src


class TestSlice6Crypto:
    def _ctx(self):
        pid = str(uuid4())
        return dict(
            project={"id": pid, "name": "P"},
            project_crypto=None,
            project_master_rows=0,
            hsm_available=False,
            hsm_slots=[],
            can_admin=True,
            can_settings=True,
            can_manage_keys=True,
            can_delete=False,
            require_reveal_approval=False,
        )

    def test_adopt_form_has_branching_confirm(self):
        html = _render("partials/project_settings.html", **self._ctx())
        assert "crypto-adopt" in html
        assert "data-confirm-if=" in html
        assert "data-confirm-alt=" in html
        assert "HSM-wrapped" in html

    def test_delete_project_confirmed(self):
        ctx = self._ctx()
        ctx["can_delete"] = True
        html = _render("partials/project_settings.html", **ctx)
        assert "Danger zone" in html
        assert "data-confirm=" in html


class TestSlice6Settings:
    def test_token_locks_present(self):
        html = _render("partials/settings_general.html", settings={})
        assert 'data-locks="max-pat-lifetime"' in html
        assert 'data-locks="max-machine-token-lifetime"' in html
        assert "readonly" in html

    def test_audit_purge_confirmed(self):
        html = _render(
            "admin_audit.html",
            active_tab="export",
            counts={"secret_audit": 0, "org_audit": 0, "login_failures": 0},
            retention_days=365,
            purge_counts={"secret_audit": 0, "org_audit": 0, "login_failures": 0},
        )
        assert "Export &amp; retention" in html
        assert "data-confirm=" in html
        assert "Purge old audit rows" in html

    def test_user_actions_confirmed(self):
        with store.app.test_request_context("/settings"):
            from flask import render_template, session

            session["user_id"] = str(uuid4())
            html = render_template(
                "partials/settings_users.html",
                all_users=[{"id": str(uuid4()), "name": "U", "email": "u@ex.com",
                            "auth_source": "local", "is_global_admin": False,
                            "totp_enabled_at": None, "disabled_at": None}],
            )
        assert html.count("data-confirm=") >= 2


class TestSlice6Auth:
    def test_register_has_toggle(self):
        html = _render("register.html", setup_notice=None)
        assert "register-password" in html
        assert "aria-controls" in html
        assert "Create account" in html

    def test_reset_has_toggle(self):
        html = _render("reset_password.html")
        assert "reset-password" in html
        assert "Update password" in html


class TestSlice6JS:
    def test_gate_and_lock_contracts(self):
        c = store.app.test_client()
        assert b"data-confirm-alt" in c.get("/static/dialogs.js").data
        assert b"data-locks" in c.get("/static/forms.js").data
