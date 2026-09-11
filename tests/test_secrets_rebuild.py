"""Slice 3 rebuild tests: projects + secrets + trash/shared/folders.

Mock DB — no Postgres required. Covers the Phase 1 checklist items for
the projects area and secret lifecycle, plus the slice-3 fixes (inline
page scripts moved to secret_forms.js, native confirm() replaced by
the styled gate, click-to-select delegated, bulk confirms styled).
"""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import app as store

store.app.config["TESTING"] = True

TEMPLATES = Path(__file__).resolve().parent.parent / "app" / "templates"

SLICE3 = [
    "project.html",
    "secret_new.html",
    "secret_view.html",
    "secret_history.html",
    "folder_view.html",
    "projects.html",
    "secrets.html",
    "shared_secrets.html",
    "trash.html",
    "partials/project_content.html",
    "partials/project_secrets.html",
    "partials/secrets.html",
    "partials/secrets_results.html",
    "partials/secret_panel.html",
    "partials/secret_masked.html",
    "partials/secret_row_menu.html",
    "partials/reveal.html",
    "partials/reveal_toggle.html",
    "partials/reveal_saved.html",
    "partials/reveal_access.html",
    "partials/shared_results.html",
    "partials/trash_results.html",
    "partials/folder_panel.html",
    "partials/pin_button.html",
]


def _render(name, **ctx):
    with store.app.test_request_context("/projects/x"):
        from flask import render_template

        return render_template(name, **ctx)


class TestSlice3ProjectSecretsCard:
    def test_secrets_heading_table_and_controls_share_one_card(self):
        # Project secrets tab: heading, search, bulk toolbar, and table live
        # in one card. The HTMX list fragment has no card chrome so swaps
        # never nest cards (same contract as team-wide list pages).
        src = (TEMPLATES / "partials/project_secrets.html").read_text()
        heading = src.find('<h2 class="card-title">Secrets')
        assert heading != -1
        card_open = src.rfind('<section class="card card-border', 0, heading)
        assert card_open != -1
        card = src[card_open:src.find("</section>", heading)]
        assert "card-body gap-6" in card
        assert 'id="bulk-toolbar"' in card
        assert 'id="secrets-list"' in card
        assert "Add secret" in card
        assert "card card-border" not in (TEMPLATES / "partials/secrets.html").read_text()


class TestSlice3NoInlineJS:
    def test_no_inline_handlers_in_slice(self):
        bad = []
        for rel in SLICE3:
            src = (TEMPLATES / rel).read_text()
            for marker in ("onclick=", "onsubmit=", "return confirm("):
                if marker in src:
                    bad.append(f"{rel}: {marker}")
        assert not bad, bad

    def test_no_inline_script_blocks_in_slice(self):
        bad = [rel for rel in SLICE3 if "<script>" in (TEMPLATES / rel).read_text()]
        assert not bad, bad


class TestSlice3SecretNew:
    def _html(self):
        return _render(
            "secret_new.html",
            project={"id": str(uuid4()), "name": "P"},
            kind="plain",
            key="",
            note="",
            expires_at="",
            access_modes=["inherit"],
            access_mode_labels={},
            require_reveal_approval=False,
        )

    def test_form_carries_tool_urls(self):
        html = self._html()
        assert "data-derive-url=" in html
        assert "data-generate-url=" in html
        assert "advanced-secret-form" in html

    def test_page_loads_secret_forms(self):
        assert "secret_forms.js" in self._html()

    def test_kind_sections_present(self):
        html = self._html()
        for section in ("fields-plain", "fields-database", "fields-certificate",
                        "fields-ssh", "fields-kv"):
            assert section in html


class TestSlice3SecretView:
    def _html(self, path="/projects/x", **kw):
        pid, sid = str(uuid4()), str(uuid4())
        ctx = dict(
            project_id=pid,
            secret_id=sid,
            secret_key="API_KEY",
            kind="plain",
            project_name="P",
            active_tab="secret",
            can_admin=False,
            can_write=True,
            can_reveal=True,
            access_blocked=False,
            is_version=False,
            value="v",
            access_mode="inherit",
            access_modes=["inherit", "restricted"],
            access_mode_labels={},
            team_groups=[],
            role_dropdown=[],
            role_descriptions={},
            secret_bindings=[],
            effective_access=[],
            custom_meta=[],
            note="",
            expires_at="",
            created_at="",
            updated_at="",
            last_accessed_at=None,
            last_accessed_by_email="",
            clipboard_clear_seconds=30,
        )
        ctx.update(kw)
        with store.app.test_request_context(path):
            from flask import render_template

            return render_template("secret_view.html", **ctx)

    def test_delete_uses_data_confirm(self):
        html = self._html()
        assert "data-confirm=" in html
        assert "Move API_KEY to trash?" in html

    def test_section_tabs_present(self):
        html = self._html()
        assert "secret-panel" in html
        assert "Metadata" in html

    def test_version_view_keeps_section_nav(self):
        # Historical versions hide Metadata/Access, but the section nav
        # itself must stay: Secret tab active, version context preserved.
        vid = str(uuid4())
        html = self._html(f"/projects/x?version_id={vid}",
                          is_version=True, can_admin=True)
        assert 'role="tablist"' in html
        assert "tab tab-active" in html
        assert ">Secret</a>" in html
        assert f"version_id={vid}" in html
        assert ">Metadata</a>" not in html
        assert ">Access</a>" not in html

    def test_current_view_tab_links_carry_no_version(self):
        html = self._html()
        assert 'role="tablist"' in html
        assert "version_id" not in html.split('role="tablist"')[1].split("</div>")[0]

    def test_value_toolbar_joins_copy_and_hide(self):
        from tests.helpers import assert_balanced_html

        html = self._html()
        assert_balanced_html(html)
        page_head, _, panel = html.partition('id="secret-view-panel"')
        assert "toggle-edit-mode" in page_head
        assert "History" in page_head
        assert "secret-show-btn" in panel
        assert ">Show</button>" in panel
        assert 'id="plain-view"' in panel
        assert 'class="input w-full"' in panel
        assert "Last accessed" in panel
        assert "<th>Field</th>" in panel
        assert "Copy key" not in panel
        assert "Copy value" not in panel

    def test_metadata_tab_system_fields_are_a_table(self):
        from tests.helpers import assert_balanced_html

        html = self._html(active_tab="meta")
        assert_balanced_html(html)
        assert "Custom fields" in html
        assert "<th>Field</th>" in html
        assert "Last accessed" in html
        assert "Last accessed by" in html
        assert ">Created</td>" in html


class TestSlice3History:
    def test_rollback_uses_data_confirm(self):
        pid, sid = str(uuid4()), str(uuid4())
        html = _render(
            "secret_history.html",
            project_id=pid,
            project={"id": pid, "team_id": str(uuid4()), "team_name": "T", "name": "P"},
            secret={"id": sid, "key": "K", "note": "", "updated_at": None},
            versions=[{"id": str(uuid4()), "note": "", "created_at": None}],
            can_write=True,
        )
        assert "data-confirm=" in html
        assert "Rollback K to this version?" in html


class TestSlice3JS:
    def test_secret_forms_serves(self):
        c = store.app.test_client()
        r = c.get("/static/secret_forms.js")
        assert r.status_code == 200
        for marker in (b"data-derive-url", b"kv-row-template", b"toggle-edit-mode",
                       b"dl-btn", b"corvusSuggestKind"):
            assert marker in r.data, marker

    def test_bulk_confirm_is_styled(self):
        c = store.app.test_client()
        secrets = c.get("/static/secrets.js").data
        assert b"__corvusBulkConfirm" in secrets
        assert b"textarea.secret-value[readonly]" in secrets
        dialogs = c.get("/static/dialogs.js").data
        assert b"__corvusBulkConfirm" in dialogs
