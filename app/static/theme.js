/* Explicit light/dark theme toggle. Runs synchronously in <head> so
   data-theme is set before first paint (no FOUC).
   Hook: input[data-theme-toggle] (checkbox = dark). Choice persists in
   localStorage ("corvus-theme"); empty/missing falls back to
   prefers-color-scheme. No cookies, no server involvement. */
(function () {
  var KEY = 'corvus-theme';
  /* Read the stored choice; private-mode failures read as empty. */
  function stored() {
    try { return localStorage.getItem(KEY); }
    catch (e) { return null; }
  }
  /* Resolve the effective theme: stored choice, else OS preference. */
  function preferred() {
    var s = stored();
    if (s === 'light' || s === 'dark') return s;
    try {
      return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
    } catch (e) { return 'light'; }
  }
  /* Apply the theme and sync every toggle checkbox. */
  function apply(t) {
    document.documentElement.setAttribute('data-theme', t);
    document.querySelectorAll('input[data-theme-toggle]').forEach(function (el) {
      el.checked = (t === 'dark');
    });
  }
  apply(preferred());
  /* Bind each toggle once; re-scans skip already-bound nodes. */
  function bind(root) {
    (root || document).querySelectorAll('input[data-theme-toggle]').forEach(function (el) {
      if (el.dataset.themeBound === '1') return;
      el.dataset.themeBound = '1';
      el.checked = document.documentElement.getAttribute('data-theme') === 'dark';
      /* Persist the new choice, then apply it everywhere. */
      el.addEventListener('change', function () {
        var t = el.checked ? 'dark' : 'light';
        try { localStorage.setItem(KEY, t); } catch (e) {}
        apply(t);
      });
    });
  }
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function () { bind(document); });
  } else {
    bind(document);
  }
})();
