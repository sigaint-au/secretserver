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
    def _html(self):
        pid, sid = str(uuid4()), str(uuid4())
        return _render(
            "secret_view.html",
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

    def test_delete_uses_data_confirm(self):
        html = self._html()
        assert "data-confirm=" in html
        assert "Move API_KEY to trash?" in html

    def test_subnav_tabs_present(self):
        html = self._html()
        assert "secret-panel" in html
        assert "Metadata" in html


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
        assert b"input.secret-value[readonly]" in secrets
        dialogs = c.get("/static/dialogs.js").data
        assert b"__corvusBulkConfirm" in dialogs
