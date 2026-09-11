/* Sidebar navigation: collapsible group persistence, mobile drawer a11y,
   tab highlight. Groups render as daisyUI menu <details>/<summary>;
   resource sections render as daisyUI tabs ([role=tablist] > [role=tab]).
   Hooks: [data-side-group], #side-toggle, #side-backdrop, #app-sidebar,
   a[data-nav-link], [role=tablist]. */
"use strict";

/* Remember open/closed sidebar groups across full-page navigation.
   Storage key contract: "secretstore.sidebar.groups". */
(function groups() {
  var KEY = "secretstore.sidebar.groups";

  function read() {
    try {
      return JSON.parse(window.localStorage.getItem(KEY) || "{}") || {};
    } catch (err) {
      return {};
    }
  }

  function write(state) {
    try {
      window.localStorage.setItem(KEY, JSON.stringify(state));
    } catch (err) {
      /* Private mode: persistence skipped silently. */
    }
  }

  function each(scope, fn) {
    Array.prototype.forEach.call(
      (scope || document).querySelectorAll("[data-side-group]"),
      fn
    );
  }

  /* Restore persisted state; adopt server-opened groups seen first. */
  function reconcile(scope) {
    var state = read();
    var dirty = false;
    each(scope, function (node) {
      var id = node.getAttribute("data-side-group");
      if (!id) return;
      if (Object.prototype.hasOwnProperty.call(state, id)) {
        node.open = !!state[id];
      } else if (node.open) {
        state[id] = true;
        dirty = true;
      }
      if (!node.__corvusGroup) {
        node.__corvusGroup = true;
        node.addEventListener("toggle", function () {
          var cur = read();
          cur[id] = !!node.open;
          write(cur);
        });
      }
    });
    if (dirty) write(state);
  }

  if (typeof window.onContent === "function") window.onContent(function () {
    reconcile(document);
  });
  else reconcile(document);
})();

/* Mobile drawer: the DaisyUI checkbox owns visibility; here we keep the
   toggle button's accessible name/state in sync and add Esc/close hooks. */
(function drawer() {
  var btn = document.getElementById("side-toggle");
  var box = document.getElementById("app-drawer");
  var backdrop = document.getElementById("side-backdrop");
  var panel = document.getElementById("app-sidebar");
  if (!btn || !box) return;

  function sync() {
    var open = box.checked;
    btn.setAttribute("aria-expanded", open ? "true" : "false");
    btn.setAttribute(
      "aria-label",
      open ? "Close navigation menu" : "Open navigation menu"
    );
  }

  box.addEventListener("change", function () {
    sync();
    if (box.checked && panel) {
      var first = panel.querySelector("a, button, input, select, summary");
      if (first && first.focus) first.focus();
    }
  });

  function shut(returnFocus) {
    if (!box.checked) return;
    box.checked = false;
    sync();
    if (returnFocus && btn.focus) btn.focus();
  }

  if (backdrop) {
    backdrop.addEventListener("click", function () {
      shut(false);
    });
  }
  document.addEventListener("keydown", function (evt) {
    if (evt.key === "Escape" && box.checked) shut(true);
  });
  Array.prototype.forEach.call(
    document.querySelectorAll("#app-sidebar a[data-nav-link]"),
    function (link) {
      link.addEventListener("click", function () {
        try {
          if (window.matchMedia("(max-width: 720px)").matches) shut(false);
        } catch (err) {
          /* matchMedia unavailable: leave the drawer as-is. */
        }
      });
    }
  );
  sync();
})();

/* Tab highlight follows hx-get navigation; the server re-renders panels
   but not the tablist, so this is cosmetic — server state stays canonical. */
document.addEventListener("click", function (evt) {
  var link =
    evt.target && evt.target.closest
      ? evt.target.closest('[role="tab"][hx-get]')
      : null;
  if (!link) return;
  var nav = link.closest('[role="tablist"]');
  if (!nav) return;
  Array.prototype.forEach.call(
    nav.querySelectorAll('[role="tab"]'),
    function (el) {
      el.classList.remove("tab-active");
      el.removeAttribute("aria-selected");
    }
  );
  link.classList.add("tab-active");
  link.setAttribute("aria-selected", "true");
});
