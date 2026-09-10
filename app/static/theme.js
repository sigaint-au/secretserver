/* Theme controller: explicit light/dark choice, applied before first paint.
   Runs synchronously in <head>. Hook: input[data-theme-toggle]
   (checked = dark). Persists in localStorage under "corvus-theme";
   falls back to prefers-color-scheme. No cookies, no server round-trip. */
(function () {
  var STORE_KEY = "corvus-theme";

  function readStored() {
    try {
      return window.localStorage.getItem(STORE_KEY);
    } catch (err) {
      return null;
    }
  }

  function systemTheme() {
    try {
      return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
    } catch (err) {
      return "light";
    }
  }

  function effective() {
    var saved = readStored();
    return saved === "dark" || saved === "light" ? saved : systemTheme();
  }

  function paint(name) {
    document.documentElement.setAttribute("data-theme", name);
    Array.prototype.forEach.call(
      document.querySelectorAll('input[data-theme-toggle]'),
      function (box) {
        box.checked = name === "dark";
      }
    );
  }

  function onToggle(box) {
    var name = box.checked ? "dark" : "light";
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
        box.checked = document.documentElement.getAttribute("data-theme") === "dark";
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
