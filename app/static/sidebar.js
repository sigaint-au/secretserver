/* Sidebar navigation: collapsible section persistence, mobile toggle,
   subnav state. Sections render as daisyUI menu details/summary submenus.
   Hooks: [data-side-group] (<details>), #side-toggle, #side-backdrop,
   #app-sidebar, .page-subnav-link. Binds once; sidebar markup is static. */
'use strict';

/* Persist sidebar <details> open/closed across full page navigations.
   Toggle wins over server-rendered defaults; OOB swaps can replace nodes
   anywhere, so sync always scans the whole document. */
(function () {
  const KEY = 'secretstore.sidebar.groups';
  /* Read persisted group state; corrupt or missing storage reads as empty. */
  function load() {
    try { return JSON.parse(localStorage.getItem(KEY) || '{}') || {}; }
    catch { return {}; }
  }
  /* Write group state; private-mode quota errors are swallowed. */
  function save(state) {
    try { localStorage.setItem(KEY, JSON.stringify(state)); } catch {}
  }
  /* Apply persisted open state to each group (unknown groups untouched). */
  function apply(root) {
    const state = load();
    /* Restore one group's persisted open state. */
    (root || document).querySelectorAll('[data-side-group]').forEach(function (el) {
      const id = el.getAttribute('data-side-group');
      if (!id || !Object.prototype.hasOwnProperty.call(state, id)) return;
      el.open = !!state[id];
    });
  }
  /* Remember sections the server opened so a later page cannot collapse them
     just because its endpoint default is different (toggle still wins). */
  function seedOpen(root) {
    const state = load();
    let changed = false;
    /* Seed state from server-opened groups not yet recorded. */
    (root || document).querySelectorAll('[data-side-group]').forEach(function (el) {
      const id = el.getAttribute('data-side-group');
      if (!id || !el.open || Object.prototype.hasOwnProperty.call(state, id)) return;
      state[id] = true;
      changed = true;
    });
    if (changed) save(state);
  }
  /* Bind each group once (sideBound guard): persist on every toggle. */
  function bind(root) {
    /* Bind one group once; re-scans skip already-bound nodes. */
    (root || document).querySelectorAll('[data-side-group]').forEach(function (el) {
      if (el.dataset.sideBound === '1') return;
      el.dataset.sideBound = '1';
      /* Persist this group's open state whenever the user toggles it. */
      el.addEventListener('toggle', function () {
        const id = el.getAttribute('data-side-group');
        if (!id) return;
        const state = load();
        state[id] = !!el.open;
        save(state);
      });
    });
  }
  /* Apply + seed + bind for the given root. */
  function sync(root) {
    apply(root);
    seedOpen(root);
    bind(root);
  }
  /* OOB swaps may replace nodes outside the swap target: always document. */
  onContent(function () { sync(document); });
})();

/* Mobile sidebar toggle; state is the body.side-open class. */
(function () {
  const btn = document.getElementById('side-toggle');
  const backdrop = document.getElementById('side-backdrop');
  const sidebar = document.getElementById('app-sidebar');
  if (!btn || !sidebar) return;
  /* Close the sidebar and return focus to the toggle button. */
  function close() {
    document.body.classList.remove('side-open');
    btn.setAttribute('aria-expanded', 'false');
    btn.setAttribute('aria-label', 'Open navigation menu');
    btn.focus();
  }
  /* Toggle sidebar open state, keeping aria label/expanded in sync. */
  btn.addEventListener('click', function () {
    const open = document.body.classList.toggle('side-open');
    btn.setAttribute('aria-expanded', open ? 'true' : 'false');
    btn.setAttribute('aria-label', open ? 'Close navigation menu' : 'Open navigation menu');
    if (open) {
      const first = sidebar.querySelector('a, button, input, select, summary');
      if (first) first.focus();
    }
  });
  if (backdrop) backdrop.addEventListener('click', close);
  /* Escape closes the sidebar from anywhere. */
  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape' && document.body.classList.contains('side-open')) close();
  });
  /* On narrow screens, following a nav link closes the sidebar. */
  document.querySelectorAll('#app-sidebar a[data-nav-link]').forEach(function (a) {
    /* Close the sidebar after navigation on mobile widths. */
    a.addEventListener('click', function () {
      if (window.matchMedia('(max-width: 720px)').matches) close();
    });
  });
})();

/* Page subnav menu active state switcher on HTMX navigation. The server
   re-renders panels but not the subnav, so the active highlight is moved
   client-side on hx-get link clicks (cosmetic; server state is canonical). */
document.addEventListener('click', function (e) {
  const link = e.target.closest && e.target.closest('.page-subnav-link');
  if (!link || !link.hasAttribute('hx-get')) return;
  const nav = link.closest('.page-subnav');
  if (!nav) return;
  /* Clear the active highlight from every subnav link. */
  nav.querySelectorAll('.page-subnav-link').forEach(function (el) {
    el.classList.remove('menu-active');
    el.removeAttribute('aria-current');
  });
  link.classList.add('menu-active');
  link.setAttribute('aria-current', 'page');
});
