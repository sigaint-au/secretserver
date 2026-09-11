"""Slice 1 rebuild tests: shell + auth on latest HTMX/Alpine/DaisyUI.

Mock DB — no Postgres required. Covers the Phase 1 checklist items for
the app shell and auth flow: vendor pins, Alpine wiring, theme toggle,
login/register layout contracts.
"""

from __future__ import annotations

import re
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import app as store
from auth import authz
from core import db
from tests.helpers import mock_conn as _conn

store.app.config["TESTING"] = True

VENDOR = Path(__file__).resolve().parent.parent / "app" / "static" / "vendor"


class TestSlice1Vendor:
    def test_versions_pinned(self):
        pins = (VENDOR / "VERSIONS").read_text()
        assert "htmx.org 4.0.0" in pins
        assert "Alpine.js 3.17.2" in pins
        assert "daisyUI 5.7.32" in pins

    def test_vendor_files_serve(self):
        c = store.app.test_client()
        for name in ("htmx.min.js", "alpine.min.js", "daisyui.min.css"):
            r = c.get(f"/static/vendor/{name}")
            assert r.status_code == 200, name
            assert len(r.data) > 1000, name

    def test_daisyui_bundle_has_components(self):
        # Minification drops the version banner; component presence plus
        # the VERSIONS pin is the artifact check.
        c = store.app.test_client()
        r = c.get("/static/vendor/daisyui.min.css")
        for marker in (b".btn", b".drawer", b".modal", b".swap", b".toast"):
            assert marker in r.data, marker

    def test_theme_resyncs_on_htmx_swaps(self):
        # Slice-1 fix: re-rendered nav toggles stay in sync.
        c = store.app.test_client()
        r = c.get("/static/theme.js")
        assert r.status_code == 200
        assert b"htmx:after:swap" in r.data
        assert b"corvus-theme" in r.data

    def test_brand_themes(self):
        # Night vault: daisyUI `lofi` default, `business` dark companion.
        c = store.app.test_client()
        r = c.get("/static/theme.js")
        assert b"lofi" in r.data
        assert b"business" in r.data
        css = c.get("/static/vendor/daisyui.min.css")
        assert b"data-theme=lofi" in css.data
        assert b"data-theme=business" in css.data


class TestSlice1AuthShell:
    def _login(self):
        conn, _ = _conn(fetchall=[])
        with patch.object(db, "connect_admin", return_value=conn):
            return store.app.test_client().get("/login")

    def test_shell_sets_default_theme(self):
        # <html> carries the default theme so first paint is themed.
        r = self._login()
        assert r.status_code == 200
        assert b'<html lang="en" data-theme="lofi">' in r.data

    def test_login_loads_alpine_and_htmx(self):
        r = self._login()
        assert r.status_code == 200
        assert re.search(rb'<script\s+src="[^"]*htmx\.min\.js"[^>]*></script>', r.data)
        assert re.search(rb'<script\s+src="[^"]*alpine\.min\.js"[^>]*></script>', r.data)
        assert b"vendor/daisyui.min.css" in r.data
        assert b"theme-controller" in r.data

    def test_login_keeps_layout_contracts(self):
        r = self._login()
        assert b"app-drawer" not in r.data
        assert b"lg:grid-cols-2" not in r.data
        assert b"card-body" in r.data
        assert b"auth-source" in r.data
        assert b"AGPL-3.0" in r.data
        assert b"brand-logo" in r.data
        assert b"fill=\"currentColor\"" in r.data
        assert b"data-theme-toggle" in r.data

    def test_login_has_password_toggle(self):
        r = self._login()
        assert b"login-password" in r.data
        assert b"aria-controls" in r.data

    def test_login_has_no_inline_styles(self):
        r = self._login()
        assert b"style=" not in r.data

    def test_register_has_no_source_link(self):
        # Registration may be disabled (302 to login); either way the
        # register response itself carries no source link.
        conn, _ = _conn(fetchall=[])
        with patch.object(db, "connect_admin", return_value=conn):
            r = store.app.test_client().get("/register")
        assert r.status_code in (200, 302)
        assert b"auth-source" not in r.data

    def test_authed_shell_keeps_contracts(self):
        c = store.app.test_client()
        with c.session_transaction() as s:
            s["user_id"] = str(uuid4())
            s["email"] = "slice1@example.com"
        conn, _ = _conn(fetchall=[])
        with (
            patch.object(db, "as_user", return_value=conn),
            patch.object(authz, "is_global_admin", return_value=False),
        ):
            r = c.get("/teams")
        assert r.status_code == 200
        assert b"app-drawer" in r.data
        assert b"side-team-select" in r.data
        assert b"text-base-content" in r.data
        sidebar = r.data[r.data.index(b'id="app-sidebar"'):]
        assert b">Go</button>" not in sidebar
        assert b"requestSubmit" in r.data
        assert b"slice1@example.com" in r.data
        assert b"Log out" in r.data
        assert b"alpine.min.js" in r.data
        assert b"data-theme-toggle" in r.data
        assert b"theme-controller" in r.data
        assert b"Account menu" in r.data
        assert b"Copy login command" in r.data
        assert b'data-open-dialog="cli-login-dlg"' in r.data
        assert b'id="cli-login-dlg"' in r.data
        assert b'text-base-content' in r.data
        sidebar = r.data[r.data.index(b'id="app-sidebar"'):]
        assert b'id="cli-login-dlg"' not in sidebar
        assert b"sticky" in r.data
        assert b'<html lang="en" data-theme="lofi">' in r.data
        assert b'id="palette-btn"' in r.data
        assert b"Jump to" in r.data
        assert b'id="search-palette"' in r.data
        assert b'id="palette-q"' in r.data
        assert b"Ctrl K" in r.data
        assert b"search_palette.js" in r.data
        assert b'id="nav-search-q"' not in r.data

    def test_classification_banner_uses_selected_colour(self):
        from ui import nav

        c = store.app.test_client()
        with c.session_transaction() as s:
            s["user_id"] = str(uuid4())
            s["email"] = "slice1@example.com"
        conn, _ = _conn(fetchall=[])
        with (
            patch.object(db, "as_user", return_value=conn),
            patch.object(authz, "is_global_admin", return_value=False),
            patch.object(nav, "classification", return_value={
                "enabled": True, "text": "SECRET", "color": "#c62828", "fg": "#ffffff",
            }),
        ):
            r = c.get("/teams")
        assert r.status_code == 200
        html = r.data
        assert b"SECRET" in html
        assert b"background-color: #c62828" in html
        assert b"color: #ffffff" in html
        assert b"text-center" in html
        assert b"justify-center" in html
        assert b"alert-warning" not in html
        # Profile and logout live in the top-right account menu, not the sidebar.
        sidebar = r.data[r.data.index(b'id="app-sidebar"'):]
        assert b"Log out" not in sidebar
        assert b"My profile" not in sidebar
        assert b'data-side-group="profile"' not in r.data
