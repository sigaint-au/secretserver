/* Night-vault theme: explicit silk/business choice, applied before paint.
   Runs synchronously in <head>. Default theme is daisyUI "lofi"
   (also set as data-theme on <html>); "business" is the dark companion,
   reached only through the Alpine theme-controller toggle. Legacy stored
   values ("corvus", "corporate", "silk", "light" -> lofi; "corvus-dark", "dark" ->
   "business") migrate forward. Hook: input[data-theme-toggle]
   (checked = dark, carries the daisyUI theme-controller class so the CSS
   :has() rule agrees). Persists in localStorage under "corvus-theme";
   falls back to prefers-color-scheme. No cookies, no server round-trip.
   Alpine (MutationObserver) auto-inits toggles arriving via HTMX swaps;
   the htmx:after:swap hook below re-syncs their checked state. */
(function () {
  var STORE_KEY = "corvus-theme";
  var LIGHT = "lofi";
  var DARK = "business";

  function readStored() {
    try {
      return window.localStorage.getItem(STORE_KEY);
    } catch (err) {
      return null;
    }
  }

  function systemTheme() {
    try {
      return window.matchMedia("(prefers-color-scheme: dark)").matches ? DARK : LIGHT;
    } catch (err) {
      return LIGHT;
    }
  }

  function normalize(saved) {
    if (saved === DARK || saved === "dark" || saved === "corvus-dark") return DARK;
    if (saved === LIGHT || saved === "light" || saved === "corvus" || saved === "corporate" || saved === "silk") return LIGHT;
    return null;
  }

  function effective() {
    return normalize(readStored()) || systemTheme();
  }

  function paint(name) {
    document.documentElement.setAttribute("data-theme", name);
    Array.prototype.forEach.call(
      document.querySelectorAll('input[data-theme-toggle]'),
      function (box) {
        box.checked = name === DARK;
      }
    );
  }

  function onToggle(box) {
    var name = box.checked ? DARK : LIGHT;
    try {
      window.localStorage.setItem(STORE_KEY, name);
    } catch (err) {
      /* Private mode: apply without persisting. */
    }
    paint(name);
  }

  function wire(scope) {
    Array.prototype.forEach.call(
      (scope || document).querySelectorAll('input[data-theme-toggle]'),
      function (box) {
        if (box.__corvusTheme) return;
        box.__corvusTheme = true;
        box.checked = document.documentElement.getAttribute("data-theme") === DARK;
        box.addEventListener("change", function () {
          onToggle(box);
        });
      }
    );
  }

  paint(effective());

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", function () {
      wire(document);
    });
  } else {
    wire(document);
  }
  /* HTMX swaps can introduce new toggles (e.g. re-rendered nav). */
  document.addEventListener("htmx:after:swap", function (evt) {
    wire(evt.target && evt.target.querySelectorAll ? evt.target : document);
  });
})();
