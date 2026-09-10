/* Form behaviors: type-to-confirm gates, user suggest, role mode tabs,
   token scope chips, unsaved-changes guard, submit dimming,
   duplicate-submit guard. Delegated/registry-driven so swapped-in
   forms work without re-init. */
"use strict";

/* Type-to-confirm gates (e.g. team deletion): the submit button stays
   disabled until the input matches the expected value exactly. */
document.addEventListener("input", function (evt) {
  var field =
    evt.target && evt.target.closest
      ? evt.target.closest("[data-confirm-for]")
      : null;
  if (!field) return;
  var btn = document.getElementById(field.getAttribute("data-confirm-for"));
  if (btn) {
    btn.disabled =
      (field.value || "") !== (field.getAttribute("data-confirm-value") || "");
  }
});

/* Member-email autocomplete. Hook: inputs.user-suggest backed by the
   global #user-suggest-list datalist. 200ms debounce, repeats skipped. */
(function suggest() {
  var list = document.getElementById("user-suggest-list");
  if (!list) return;
  var timer = null;
  var lastQuery = "";

  function fill(items) {
    list.innerHTML = "";
    (items || []).forEach(function (item) {
      var opt = document.createElement("option");
      opt.value = item.email;
      opt.label = item.label || item.email;
      list.appendChild(opt);
    });
  }

  document.addEventListener("input", function (evt) {
    var el = evt.target;
    if (!el || !el.classList || !el.classList.contains("user-suggest")) return;
    var q = (el.value || "").trim();
    if (q.length < 1) {
      fill([]);
      return;
    }
    window.clearTimeout(timer);
    timer = window.setTimeout(function () {
      if (q === lastQuery) return;
      lastQuery = q;
      fetch("/api/users/suggest?q=" + encodeURIComponent(q), {
        headers: { Accept: "application/json" },
        credentials: "same-origin",
      })
        .then(function (res) {
          return res.ok ? res.json() : [];
        })
        .then(fill)
        .catch(function () {
          fill([]);
        });
    }, 200);
  });
})();

/* Role editor Form/YAML switch (daisyUI tabs pattern).
   Hook: .role-mode-tabs [role="tab"][data-mode] toggling
   #mode-<mode>-panel siblings, with arrow-key support. */
(function modeTabs() {
  function pick(list, btn) {
    Array.prototype.forEach.call(
      list.querySelectorAll('[role="tab"][data-mode]'),
      function (tab) {
        var on = tab === btn;
        tab.setAttribute("aria-selected", on ? "true" : "false");
        tab.tabIndex = on ? 0 : -1;
        var panelId = tab.getAttribute("aria-controls");
        var panel = panelId && document.getElementById(panelId);
        if (panel) panel.hidden = !on;
      }
    );
  }

  function boot(scope) {
    Array.prototype.forEach.call(
      (scope || document).querySelectorAll(".role-mode-tabs"),
      function (list) {
        if (list.__corvusModes) return;
        list.__corvusModes = true;
        list.addEventListener("click", function (evt) {
          var btn =
            evt.target && evt.target.closest
              ? evt.target.closest('[role="tab"][data-mode]')
              : null;
          if (btn && list.contains(btn)) pick(list, btn);
        });
        list.addEventListener("keydown", function (evt) {
          if (evt.key !== "ArrowLeft" && evt.key !== "ArrowRight") return;
          var tabs = Array.prototype.slice.call(
            list.querySelectorAll('[role="tab"][data-mode]')
          );
          var i = tabs.indexOf(document.activeElement);
          if (i < 0) return;
          evt.preventDefault();
          var next =
            tabs[(i + (evt.key === "ArrowRight" ? 1 : tabs.length - 1)) % tabs.length];
          if (next) {
            pick(list, next);
            next.focus();
          }
        });
      }
    );
  }

  if (typeof window.onContent === "function") window.onContent(boot);
  else boot(document);
})();

/* Machine-token create form: scope chips plus restrict toggle.
   Hook: form[data-scope-form]; the ss-taginput widget is only read,
   never driven. Restricted-but-empty submits are blocked client-side. */
(function scopeForm() {
  function tagsOf(el) {
    if (!el) return [];
    try {
      var v = el.value;
      if (Array.isArray(v)) return v.map(String).filter(Boolean);
      if (typeof v === "string" && v) {
        return v
          .split(",")
          .map(function (s) {
            return s.trim();
          })
          .filter(Boolean);
      }
    } catch (err) {
      /* Widget unreadable: treat as empty. */
    }
    return [];
  }

  function writeTags(el, tags) {
    if (!el) return;
    try {
      el.value = tags;
    } catch (err) {
      /* Widget rejected the write; submit guard still applies. */
    }
  }

  function boot(scope) {
    Array.prototype.forEach.call(
      (scope || document).querySelectorAll("form[data-scope-form]"),
      function (form) {
        if (form.__corvusScope) return;
        form.__corvusScope = true;
        var toggle = form.querySelector("[data-scope-toggle]");
        var body = form.querySelector("[data-scope-body]");
        var openMsg = form.querySelector("[data-scope-open-msg]");
        var tags = form.querySelector("[data-scope-tags]");
        var hidden = form.querySelector("[data-scope-hidden]");
        var roleSel = form.querySelector("[data-token-role]");
        var writeWarn = form.querySelector("[data-token-write-warn]");
        var emptyErr = form.querySelector("[data-scope-empty-err]");

        function syncScope() {
          var on = !!(toggle && toggle.checked);
          if (body) body.hidden = !on;
          if (openMsg) openMsg.hidden = on;
          if (emptyErr) emptyErr.hidden = true;
          if (!on && tags) writeTags(tags, []);
        }

        function syncRole() {
          if (writeWarn && roleSel) {
            writeWarn.hidden = roleSel.value !== "service-write";
          }
        }

        if (toggle) toggle.addEventListener("change", syncScope);
        if (roleSel) roleSel.addEventListener("change", syncRole);
        Array.prototype.forEach.call(
          form.querySelectorAll("[data-scope-preset]"),
          function (btn) {
            btn.addEventListener("click", function () {
              if (toggle && !toggle.checked) {
                toggle.checked = true;
                syncScope();
              }
              var want = (btn.getAttribute("data-scope-preset") || "").trim();
              if (!want) return;
              var cur = tagsOf(tags);
              if (cur.indexOf(want) < 0) {
                cur.push(want);
                writeTags(tags, cur);
              }
            });
          }
        );
        form.addEventListener("submit", function (evt) {
          if (!hidden) return;
          var list = toggle && toggle.checked ? tagsOf(tags) : ["*"];
          if (toggle && toggle.checked && list.length === 0) {
            evt.preventDefault();
            if (emptyErr) emptyErr.hidden = false;
            return;
          }
          hidden.value = list.join("\n");
        });
        syncScope();
        syncRole();
      }
    );
  }

  if (typeof window.onContent === "function") window.onContent(boot);
  else boot(document);
})();

/* Unsaved-changes guard for form[data-dirty-guard]: native prompt on
   unload, confirm on sidebar HTMX navigation (capture phase). */
(function dirtyGuard() {
  function snap(form) {
    return new FormData(form);
  }

  function equal(a, b) {
    if (a.length !== b.length) return false;
    var ka = Array.from(a.keys()).sort().join("|");
    var kb = Array.from(b.keys()).sort().join("|");
    if (ka !== kb) return false;
    return ka.split("|").every(function (k) {
      return a.getAll(k).join("\u0000") === b.getAll(k).join("\u0000");
    });
  }

  function scan(scope) {
    Array.prototype.forEach.call(
      (scope || document).querySelectorAll("form[data-dirty-guard]"),
      function (form) {
        if (!form.__corvusClean) form.__corvusClean = snap(form);
        if (form.__corvusDirtyBound) return;
        form.__corvusDirtyBound = true;
        form.addEventListener("input", function () {
          form.__corvusDirty = !equal(form.__corvusClean, snap(form));
        });
      }
    );
  }

  function dirty() {
    var found = null;
    document
      .querySelectorAll("form[data-dirty-guard]")
      .forEach(function (form) {
        if (!found && form.__corvusDirty) found = form;
      });
    return found;
  }

  if (typeof window.onContent === "function") window.onContent(scan);
  else scan(document);

  window.addEventListener("beforeunload", function (evt) {
    if (dirty()) {
      evt.preventDefault();
      evt.returnValue = "";
    }
  });
  document.addEventListener(
    "click",
    function (evt) {
      var link =
        evt.target && evt.target.closest
          ? evt.target.closest("a[data-nav-link]")
          : null;
      if (
        link && dirty() &&
        !window.confirm("You have unsaved changes. Leave anyway?")
      ) {
        evt.preventDefault();
      }
    },
    true
  );
})();

/* Intentional submits are saves, not abandonment: drop the dirty flag
   so the unload prompt never fires for the form's own navigation.
   Capture phase; purely bookkeeping, never blocks the submit. */
document.addEventListener(
  "submit",
  function (evt) {
    var form = evt.target;
    if (form && form.tagName === "FORM") form.__corvusDirty = false;
  }
  /* Bubble phase: a confirm gate that cancels the submit (capture +
     stopPropagation) must leave the dirty flag untouched. */
);

/* Dim full-page GET search/filter forms the moment they submit. */
document.addEventListener(
  "submit",
  function (evt) {
    var form =
      evt.target && evt.target.closest
        ? evt.target.closest('form[method="get"]')
        : null;
    if (form) form.classList.add("submitting");
  },
  true
);

/* Duplicate-submit guard for plain POST forms. Dialogs and HTMX manage
   their own state; hx-* forms opt out. The clicked submitter's name is
   stamped into a hidden field first (disabled controls are dropped
   from the POST, which would lose OIDC/LDAP/HSM test-vs-save). */
document.addEventListener("submit", function (evt) {
  var form = evt.target;
  if (!form || evt.defaultPrevented || form.tagName !== "FORM") return;
  if ((form.getAttribute("method") || "").toLowerCase() !== "post") return;
  if (form.closest("dialog")) return;
  var attrs = form.attributes;
  for (var i = 0; i < attrs.length; i += 1) {
    if (String(attrs[i].name).indexOf("hx-") === 0) return;
  }
  form.classList.add("submitting");
  var who = evt.submitter;
  if (who && who.name) {
    var stamp = document.createElement("input");
    stamp.type = "hidden";
    stamp.name = who.name;
    stamp.value = who.value;
    form.appendChild(stamp);
  }
  Array.prototype.forEach.call(
    form.querySelectorAll('button[type="submit"]'),
    function (btn) {
      if (!btn.disabled) {
        if (btn.dataset.busy) btn.textContent = btn.dataset.busy;
        btn.disabled = true;
      }
    }
  );
});
