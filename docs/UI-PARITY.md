# UI rebuild — parity walk (Phases 1–4)

Rebuild of the Flask + HTMX frontend on pinned self-hosted frameworks
(see `app/static/vendor/VERSIONS`): HTMX 4.0.0, Alpine.js 3.17.2,
DaisyUI 5.7.32 on Tailwind CSS 4.3.3. Backend untouched (no route,
schema, or auth-flow changes). All URLs preserved.

## Checklist walk (Phase 1 → done)

- Auth: login, 2FA, register, verify-email (+resend), logout,
  forgot/reset password, OIDC/LDAP branches — done (slices 1, 6).
- Profile (6 tabs), PATs, sessions, login alerts, TOTP setup/recovery,
  CLI login dialog — done (slice 5).
- Teams (8 tabs), members/bindings, transfer, invites + redeem,
  join-requests, directory maps, groups, team projects — done (slice 2).
- Projects (10 tabs), secrets CRUD, reveal/hide/pin/copy, history +
  rollback, bulk toolbar, shared, trash, folders, SSH keygen — done
  (slice 3).
- Access requests (inbox + project tab), approve/deny with grant
  durations — done (slice 4).
- RBAC roles/bindings/access-review, bindings at team/project/folder/
  secret scopes — done (slice 4).
- Machine tokens (shown-once create → delete), ESO manifests — done
  (slice 5).
- Import preview → commit, export (CSV/JSON/env/plaintext) — done
  (slice 5).
- Webhooks CRUD + deliveries log — done (slice 5).
- Admin audit (5 tabs), retention + purge, settings (11 tabs),
  HSM slot wizard — done (slice 6).
- Project crypto adopt/migrate/re-encrypt, project meta, team meta —
  done (slice 6).
- Shell: drawer/nav, team switcher, search, pins/recent, flashes,
  confirm dialog, theme toggle, classification/login banners — done
  (slice 1).
- Edge states: empty/error/loading/denied covered by existing suites
  (test_error, plus per-area empty-state templates). No offline
  support before or after (server-rendered app).

## Intentional deviations (old → new)

- All native `confirm()` dialogs → one styled `#confirm-dlg`, including
  plain POST forms (new `data-confirm` gate; `data-confirm-if` /
  `data-confirm-alt` for the HSM/local adopt branches; `{field}`
  interpolation for ownership transfer). Webhook delete and bulk
  purge/export, which had native or no confirms, now use it too.
- All inline `onsubmit=`/`onclick=` handlers and per-page `<script>`
  blocks → static files (`secret_forms.js`, `integrations.js`) or
  Alpine state; page URLs travel via `data-*` attributes. Net effect:
  zero inline handlers app-wide except the shared
  `color_picker_js.html` helper (retained deliberately).
- Subnavs for roles, profile, and audit use tab loops; team/project
  subnavs stay explicit (source-literal contract pinned by
  `test_meta.py`).
- Password fields on login/register/reset gain Show/Hide toggles.
- Classification override, subject-kind and scope filters, HSM slot
  visibility render correct pre-JS state (server `hidden`/`disabled`).
- Token-lifetime locks now actually run (old script wired ids from a
  tab that never loaded with it); delete-team starts disabled;
  theme toggles re-sync after HTMX swaps; dirty guard clears on
  intentional submit.
- Reverted, not shipped: profile-account heading class
  (`test_auth.py` pins `<h2>Account</h2>` exactly).

## Verification

- New tests per slice: `test_ui_shell_rebuild`, `test_teams_rebuild`,
  `test_secrets_rebuild`, `test_access_rebuild`,
  `test_profile_rebuild`, `test_settings_rebuild`.
- Area suites run green (mocked DB): auth, nav, error, ui, teams,
  org-access, secrets, lifecycle, folders, rbac, tokens, totp, pats,
  webhooks, settings, hsm, hsm-slots, audit, meta, paging, mailer.
- `node --check` clean on all first-party JS; no `<script>` substrings
  in served static files.
- Bundle (gzip): CSS 22.8KB + HTMX 13.1KB + Alpine 19.9KB + all
  first-party JS ≈ 23KB ≈ 77KB total, well under the 250KB budget.
- No backend gaps found; nothing worked around.
