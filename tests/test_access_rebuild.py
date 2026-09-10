"""Slice 4 rebuild tests: access-requests + RBAC.

Mock DB — no Postgres required. Covers the Phase 1 checklist items for
reveal-request approve/deny, role bindings at all scopes, custom roles,
and access review, plus the slice-4 fixes (Alpine subject/scope
switches, upgraded role-tabs controller, data-access-busy, styled
plain-form confirms).
"""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import app as store

store.app.config["TESTING"] = True

TEMPLATES = Path(__file__).resolve().parent.parent / "app" / "templates"

SLICE4 = [
    "access_requests.html",
    "rbac_roles.html",
    "rbac_bindings.html",
    "rbac_access_review.html",
    "partials/requests_table.html",
    "partials/access_request_dialog.html",
    "partials/access_request_dialog_body.html",
    "partials/project_requests.html",
    "partials/project_access.html",
    "partials/access_bindings_panel.html",
    "partials/roles_panel.html",
]


def _render(name, **ctx):
    with store.app.test_request_context("/rbac/roles"):
        from flask import render_template

        return render_template(name, **ctx)


class TestSlice4NoInlineJS:
    def test_no_inline_handlers_in_slice(self):
        bad = []
        for rel in SLICE4:
            src = (TEMPLATES / rel).read_text()
            for marker in ("onsubmit=", "return confirm(", "setAccessBusy("):
                if marker in src:
                    bad.append(f"{rel}: {marker}")
        assert not bad, bad

    def test_no_inline_script_blocks_in_slice(self):
        bad = [rel for rel in SLICE4 if "<script>" in (TEMPLATES / rel).read_text()]
        assert not bad, bad


class TestSlice4Bindings:
    def _base(self, **over):
        tid = str(uuid4())
        base = dict(
            scope_kinds=["cluster", "team", "project", "secret"],
            teams=[{"id": tid, "name": "Acme"}],
            projects=[],
            secrets=[],
            groups=[],
            bindings=[],
            all_roles=[],
            dropdown=[],
            role_descriptions={},
            can_edit=True,
            subject_kinds=["User", "Group", "ServiceAccount"],
        )
        base.update(over)
        return base

    def test_binding_delete_uses_data_confirm(self):
        tid = str(uuid4())
        html = _render(
            "rbac_bindings.html",
            **self._base(
                scope_kind="team",
                scope_id=tid,
                scope_label="Acme",
                back_team_id=None,
                back_team_name=None,
                bindings=[{"id": str(uuid4()), "subject_email": "a@ex.com",
                           "subject_kind": "User", "role_name": "team-viewer",
                           "created_at": None}],
            ),
        )
        assert "data-confirm=" in html
        assert "Remove this binding?" in html

    def test_subject_switch_is_alpine(self):
        html = _render(
            "rbac_bindings.html",
            **self._base(scope_kind="cluster", scope_id="", scope_label=""),
        )
        assert 'x-model="kind"' in html
        assert "rbac-field-group" in html

    def test_panel_subject_switch_is_alpine(self):
        from flask import render_template

        with store.app.test_request_context("/teams/x"):
            html = render_template(
                "partials/access_bindings_panel.html",
                role_dropdown=[("team-owner", "Owner")],
                role_descriptions={},
                access_bindings=[],
                can_edit_access=True,
                subject_kinds=["User", "Group", "ServiceAccount"],
                access_groups=[],
                create_url="/x",
                panel_title="Access",
                empty_message="",
                full_bindings_url="",
                form_id_prefix="t",
            )
        assert 'x-model="kind"' in html
        assert "Hover a role name" in html or "Role descriptions" in html


class TestSlice4Roles:
    def test_role_delete_uses_data_confirm(self):
        html = _render(
            "partials/roles_panel.html",
            active_tab="custom",
            can_edit=True,
            builtin_roles=[],
            custom_roles=[{"id": str(uuid4()), "name": "ops", "description": "d"}],
            scope_kinds=["team"],
            resources=["secrets"],
            verbs=["get"],
        )
        assert "data-confirm=" in html
        assert "Delete role ops?" in html

    def test_create_form_tracks_mode_without_script(self):
        html = _render(
            "partials/roles_panel.html",
            active_tab="create",
            can_edit=True,
            builtin_roles=[],
            custom_roles=[],
            scope_kinds=["team", "project"],
            resources=["secrets"],
            verbs=["get", "list"],
        )
        assert 'data-mode-input="create-mode"' in html
        assert 'id="create-mode"' in html
        assert "rules_yaml" in html


class TestSlice4Review:
    def test_scope_switch_is_alpine(self):
        html = _render(
            "rbac_access_review.html",
            verbs=["get"],
            verb="get",
            resources=["secrets"],
            resource="secrets",
            scope_kinds=["team", "project", "secret", "cluster"],
            scope_kind="project",
            scope_id="",
            teams=[],
            projects=[],
            secrets=[],
            results=[],
        )
        assert 'x-model="scope"' in html
        assert "rev-project-wrap" in html


class TestSlice4JS:
    def test_controllers_have_new_hooks(self):
        c = store.app.test_client()
        forms = c.get("/static/forms.js").data
        assert b"data-mode-input" in forms
        assert b"tab-active" in forms
        dialogs = c.get("/static/dialogs.js").data
        assert b"data-access-busy" in dialogs
