# app/

- `app.py` Flask factory
- `routes/` HTTP — one concern per package
- `secret_svc/` secret domain
- `crypto/` `MASTER_KEY` + per-project DEKs (`project_keys.py`)
- `auth/` sessions, PAT, OIDC, LDAP, TOTP
- `core/` migration runner, settings, db pool (`as_user` stays direct for `SET ROLE`)
- `audit/` audit log
- `integrations/` mailer, ESO-adjacent, LDAP/OIDC clients
- `templates/` Night-vault UI: DaisyUI + Tailwind, HTMX, Alpine. Edit the template the route renders
- `ui/` shared UI helpers
- `static/` vendored assets only (`vendor/`); do not dump into context

Night vault in ten lines:
1. Theme `lofi` on `<html>`; dark `business` only via the Alpine `theme-controller` toggle (localStorage).
2. Shell is top `navbar` + `drawer`/`menu`; auth pages use standalone `auth_base.html` (no drawer).
3. Titles `text-2xl`/`text-3xl`, section headers `card-title` (part of the card); `gap-6`, card `p-6`. No dense stacks.
4. Only Daisy controls (`btn`, `input`, `select`, `badge`, `alert`); one radius/height per context.
5. Lists: header (title + count `badge` + `btn-primary`) then `card` + plain `table` (no zebra) or card grid.
6. `?tab=` sections are Daisy `tabs` under the header; HTMX swaps the panel only.
7. Resource pages: 12-col grid, main pane + side pane; danger zone is its own `card` + `btn-error`.
8. HTMX owns network, Alpine owns chrome (survives swaps via MutationObserver + resync hooks).
9. Never hardcode RBAC role names; never add a second brand colour or custom palette.
10. CSS: edit `assets/corvus.css`, rebuild with `make ui-css`; never link a CDN or oat stylesheet.
Reuse `partials/access_bindings_panel.html` for binding forms.

Health: `/healthz` liveness (always 200), `/readyz` readiness (DB). No auth.