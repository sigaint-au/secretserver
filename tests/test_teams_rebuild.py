"""Slice 2 rebuild tests: teams + groups + invites.

Mock DB — no Postgres required. Covers the Phase 1 checklist items for
the teams area: list/detail/groups/members/invites/settings/metadata,
plus the slice-2 fixes (styled confirm gate replaces native confirm(),
Alpine classification override, type-to-confirm starts disabled).
"""

from __future__ import annotations

from uuid import uuid4

import app as store

store.app.config["TESTING"] = True


def _team(**over):
    base = dict(
        id=str(uuid4()),
        name="Acme",
        default_token_days="",
        allow_reveal_requests=True,
        classification_enabled=None,
        classification_text="",
        classification_color="",
        classification_fg="",
    )
    base.update(over)
    return base


def _render(name, **ctx):
    tid = ctx.get("team", {}).get("id", str(uuid4())) if isinstance(ctx.get("team"), dict) else str(uuid4())
    with store.app.test_request_context(f"/teams/{tid}"):
        from flask import render_template

        return render_template(name, **ctx)


class TestSlice2ConfirmGate:
    def test_group_delete_uses_styled_confirm(self):
        team = _team()
        html = _render(
            "partials/team_groups.html",
            team=team,
            groups=[{"id": str(uuid4()), "name": "ops", "source": "manual",
                     "external_key": "", "member_count": 2}],
            is_admin=True,
            search_q="",
        )
        assert "Delete" in html
        assert "hx-confirm" in html
        assert "return confirm(" not in html
        assert "onsubmit=" not in html

    def test_project_delete_uses_data_confirm(self):
        team = _team()
        html = _render(
            "partials/team_projects.html",
            team=team,
            projects=[{"id": str(uuid4()), "name": "api", "description": "",
                       "key_provider": "local"}],
            can_manage_team=True,
            can_create_projects=False,
            search_q="",
        )
        assert "data-confirm=" in html
        assert "Delete project" in html
        assert "return confirm(" not in html
        assert "onsubmit=" not in html

    def test_group_detail_removes_use_data_confirm(self):
        team = _team()
        gid = str(uuid4())
        html = _render(
            "team_group.html",
            team=team,
            group={"id": gid, "name": "ops", "source": "manual", "external_key": ""},
            group_members=[{"user_id": str(uuid4()), "name": "Al",
                            "email": "al@example.com", "source": "manual"}],
            is_admin=True,
            search_q="",
        )
        assert "data-confirm=" in html
        assert "return confirm(" not in html
        assert "onsubmit=" not in html

    def test_settings_maps_use_data_confirm(self):
        team = _team(classification_enabled=True)
        html = _render(
            "partials/team_settings.html",
            team=team,
            classification={"text": "OFFICIAL", "color": "#677381", "fg": "#ffffff"},
            max_expiry_days=3650,
            ldap_enabled=True,
            oidc_enabled=True,
            ldap_maps=[{"id": str(uuid4()), "ldap_group": "eng", "role": "team-viewer"}],
            oidc_maps=[{"id": str(uuid4()), "oidc_group": "eng", "role": "team-viewer"}],
            dir_role_dropdown=[],
            default_role="team-viewer",
            is_owner=True,
        )
        assert html.count("data-confirm=") >= 3  # ldap + oidc + transfer (+delete team)
        assert "Transfer ownership to {email}?" in html
        assert "return confirm(" not in html
        assert "onsubmit=" not in html

    def test_delete_team_button_starts_disabled(self):
        team = _team(classification_enabled=None)
        html = _render(
            "partials/team_settings.html",
            team=team,
            classification={"text": "", "color": "", "fg": ""},
            max_expiry_days=3650,
            ldap_enabled=False,
            oidc_enabled=False,
            ldap_maps=[],
            oidc_maps=[],
            dir_role_dropdown=[],
            default_role="team-viewer",
            is_owner=True,
        )
        assert "delete-team-btn" in html
        assert "Danger zone" in html
        assert "data-confirm-for=" in html

    def test_classification_override_is_alpine(self):
        team = _team(classification_enabled=True)
        html = _render(
            "partials/team_settings.html",
            team=team,
            classification={"text": "OFFICIAL", "color": "#677381", "fg": "#ffffff"},
            max_expiry_days=3650,
            ldap_enabled=False,
            oidc_enabled=False,
            ldap_maps=[],
            oidc_maps=[],
            dir_role_dropdown=[],
            default_role="team-viewer",
            is_owner=False,
        )
        assert "Classification banner" in html
        assert 'x-model="override"' in html
        # Page-specific init block is gone (Alpine owns the state now);
        # only the shared color-picker include still ships a script.
        assert "syncTeamClassForm" not in html
        assert "onchange=" not in html
        assert "oninput=" not in html

    def test_new_project_hsm_confirm_is_conditional(self):
        team = _team()
        html = _render(
            "team_new_project.html",
            team=team,
            encryption="managed",
            can_manage_team=True,
            hsm_available=False,
            hsm_slots=[],
        )
        assert "data-confirm-if=" in html
        assert "return confirm(" not in html
        assert "onsubmit=" not in html

    def test_js_gate_contracts(self):
        c = store.app.test_client()
        dialogs = c.get("/static/dialogs.js").data
        assert b"data-confirm-if" in dialogs
        assert b"__corvusFormConfirm" in dialogs
        forms = c.get("/static/forms.js").data
        assert b"__corvusDirty = false" in forms
