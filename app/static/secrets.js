/* Secret views: clipboard copy with auto-clear, grant countdowns,
   reveal auto-hide, bulk toolbar. Delegated listeners plus one shared
   1s ticker; swap-aware through onContent. */
"use strict";

/* Copy buttons. Hook: .copy-btn with data-copy-target (element id) or
   data-copy-text, plus optional data-clear-seconds (default 30). */
(function copyButtons() {
  var clearTimer = null;
  var lastCopied = null;

  function textOf(el, explicit) {
    if (explicit) return explicit;
    if (!el) return "";
    var raw = el.id ? document.getElementById(el.id + "-raw") : null;
    if (raw) {
      var rtag = (raw.tagName || "").toUpperCase();
      if (rtag === "INPUT" || rtag === "TEXTAREA" || rtag === "SELECT") {
        return raw.value || "";
      }
      return (raw.innerText != null ? raw.innerText : raw.textContent) || "";
    }
    var stored = el.getAttribute("data-secret");
    if (stored) return stored;
    var tag = (el.tagName || "").toUpperCase();
    if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") {
      return el.value || "";
    }
    return (el.innerText != null ? el.innerText : el.textContent) || "";
  }

  /* Legacy path for contexts without the async Clipboard API. */
  function legacyCopy(text, el) {
    if (
      el && typeof el.select === "function" &&
      (el.tagName === "INPUT" || el.tagName === "TEXTAREA")
    ) {
      try {
        el.focus();
        el.select();
        if (el.setSelectionRange) el.setSelectionRange(0, (el.value || "").length);
        if (document.execCommand("copy")) return true;
      } catch (err) {
        /* Fall through to the temp-field path. */
      }
    }
    var field = document.createElement("textarea");
    field.value = text;
    field.setAttribute("readonly", "");
    field.style.cssText = "position:fixed;left:-9999px;top:0";
    document.body.appendChild(field);
    field.focus();
    field.select();
    var ok = false;
    try {
      ok = document.execCommand("copy");
    } catch (err) {
      ok = false;
    }
    document.body.removeChild(field);
    return ok;
  }

  function armClear(secs) {
    if (clearTimer) window.clearTimeout(clearTimer);
    if (!(secs > 0) || !navigator.clipboard || !navigator.clipboard.writeText) {
      return;
    }
    clearTimer = window.setTimeout(function () {
      clearTimer = null;
      navigator.clipboard
        .readText()
        .then(function (cur) {
          if (cur === lastCopied) return navigator.clipboard.writeText("");
        })
        .catch(function () {
          /* Read denied: leave the clipboard alone. */
        });
    }, secs * 1000);
  }

  document.addEventListener("click", function (evt) {
    var btn =
      evt.target && evt.target.closest
        ? evt.target.closest(".copy-btn")
        : null;
    if (!btn) return;
    evt.preventDefault();
    if (evt.stopPropagation) evt.stopPropagation();
    var id = btn.getAttribute("data-copy-target");
    var text = textOf(
      id ? document.getElementById(id) : null,
      btn.getAttribute("data-copy-text") || ""
    );
    if (!text) return;
    var secs = parseInt(btn.getAttribute("data-clear-seconds") || "30", 10);

    function done() {
      if (window.ssToast) window.ssToast("Copied to clipboard");
      lastCopied = text;
      armClear(secs);
    }

    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(done, function () {
        if (legacyCopy(text, id ? document.getElementById(id) : null)) done();
      });
    } else if (legacyCopy(text, id ? document.getElementById(id) : null)) {
      done();
    }
  });
})();

/* Click-to-select for readonly revealed values (replaces inline
   onclick handlers). Delegated; focusing via keyboard is untouched. */
document.addEventListener("click", function (evt) {
  var el =
    evt.target && evt.target.closest
      ? evt.target.closest("input.secret-value[readonly], textarea.secret-value[readonly]")
      : null;
  if (!el || el.getAttribute("data-revealed") === "false") return;
  if (typeof el.select === "function") {
    try {
      el.select();
    } catch (err) {
      /* Selection unsupported: the value stays readable. */
    }
  }
});

/* Grant-window and auto-hide countdown labels. Hooks: [data-grant-until]
   and [data-hide-until]; refreshed by one shared 1s ticker that stops
   itself when no live node remains. */
(function countdowns() {
  function grantText(ms) {
    if (ms <= 0) return "expired";
    var total = Math.floor(ms / 1000);
    var mins = Math.floor(total / 60);
    var secs = total % 60;
    if (mins >= 60) {
      return Math.floor(mins / 60) + "h " + (mins % 60) + "m";
    }
    return mins + "m " + (secs < 10 ? "0" : "") + secs + "s";
  }

  function refresh(scope) {
    var root = scope && scope.querySelectorAll ? scope : document;
    var live = false;
    Array.prototype.forEach.call(
      root.querySelectorAll("[data-grant-until]"),
      function (el) {
        var stamp = Date.parse(el.getAttribute("data-grant-until"));
        if (isNaN(stamp)) return;
        live = true;
        var label = "(" + grantText(stamp - Date.now()) + ")";
        if (el.classList && el.classList.contains("grant-countdown")) {
          el.textContent = label;
        } else {
          var inner = el.querySelector(".grant-countdown");
          if (inner) inner.textContent = label;
        }
      }
    );
    Array.prototype.forEach.call(
      root.querySelectorAll("[data-hide-until]"),
      function (el) {
        var stamp = Date.parse(el.getAttribute("data-hide-until"));
        if (!el.getAttribute("data-hide-until") || isNaN(stamp)) return;
        live = true;
        var left = Math.max(0, Math.ceil((stamp - Date.now()) / 1000));
        var count = el.querySelector(".auto-hide-count");
        if (count) count.textContent = left + "s";
      }
    );
    return live;
  }

  var ticker = null;
  function ensureTicker() {
    if (ticker) return;
    ticker = window.setInterval(function () {
      if (!refresh(document)) {
        window.clearInterval(ticker);
        ticker = null;
      }
    }, 1000);
  }

  function boot(scope) {
    refresh(scope);
    ensureTicker();
  }
  if (typeof window.onContent === "function") window.onContent(boot);
  else boot(document);
})();

/* Auto-hide for revealed secrets. Hook: .reveal-wrap[data-auto-hide].
   Re-masking goes through the reveal toggle's hx-get so the server
   stays canonical; standalone wraps mask in place (Show next to the field). */
(function autoHide() {
  function rawOf(el) {
    if (!el) return "";
    var raw = el.id ? document.getElementById(el.id + "-raw") : null;
    if (raw) {
      var tag = (raw.tagName || "").toUpperCase();
      if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") {
        return raw.value || "";
      }
      return (raw.innerText != null ? raw.innerText : raw.textContent) || "";
    }
    return el.getAttribute("data-secret") || "";
  }

  function showBtnFor(el) {
    if (!el || !el.id) return null;
    return document.querySelector(
      '.secret-show-btn[aria-controls="' + el.id + '"]'
    );
  }

  function setRevealed(el, on) {
    if (!el) return;
    el.setAttribute("data-revealed", on ? "true" : "false");
    var text = on ? rawOf(el) : "••••••••";
    var tag = (el.tagName || "").toUpperCase();
    if (tag === "INPUT" || tag === "TEXTAREA") el.value = text;
    else el.textContent = text;
    var btn = showBtnFor(el);
    if (btn) {
      btn.textContent = on ? "Hide" : "Show";
      btn.setAttribute("aria-pressed", on ? "true" : "false");
    }
  }

  function wrapIsRevealed(wrap) {
    var nodes = wrap.querySelectorAll(".secret-value[data-revealed]");
    if (!nodes.length) return true;
    for (var i = 0; i < nodes.length; i++) {
      if (nodes[i].getAttribute("data-revealed") === "true") return true;
    }
    return false;
  }

  function maskStandalone(wrap) {
    var local = false;
    Array.prototype.forEach.call(
      wrap.querySelectorAll(".secret-value"),
      function (el) {
        if (el.getAttribute("data-revealed") != null) {
          local = true;
          setRevealed(el, false);
          return;
        }
        if (el.tagName === "INPUT" || el.tagName === "TEXTAREA") {
          el.value = "••••••••";
          el.readOnly = true;
        } else {
          el.textContent = "••••••••";
        }
      }
    );
    if (!local) {
      var hiddenEnv = wrap.querySelector("#kv-all-env");
      if (hiddenEnv) hiddenEnv.textContent = "••••••••";
      Array.prototype.forEach.call(
        wrap.querySelectorAll(".copy-btn, .dl-btn"),
        function (btn) {
          btn.disabled = true;
        }
      );
    }
    var note = wrap.querySelector(".auto-hide-note");
    if (note) {
      note.hidden = true;
      note.removeAttribute("data-hide-until");
    }
    if (!local && !wrap.querySelector(".secret-show-btn") &&
        !wrap.querySelector(".reveal-again-btn")) {
      var again = document.createElement("button");
      again.type = "button";
      again.className = "btn btn-outline btn-sm reveal-again-btn";
      again.textContent = "Show again";
      var head = wrap.querySelector(".reveal-head") || wrap;
      head.appendChild(again);
    }
    if (window.ssToast) {
      window.ssToast(local ? "Secret hidden" : "Secret hidden — reload to reveal again");
    }
  }

  function hideNow(wrap) {
    if (!wrap) return;
    if (wrap.__corvusHideTimer) {
      window.clearTimeout(wrap.__corvusHideTimer);
      wrap.__corvusHideTimer = null;
    }
    maskStandalone(wrap);
  }

  function targetValue(btn) {
    var id = btn.getAttribute("aria-controls");
    if (id) return document.getElementById(id);
    var unit = btn.closest(".join") || btn.closest(".list-row") || btn.parentElement;
    return unit ? unit.querySelector(".secret-value") : null;
  }

  document.addEventListener("click", function (evt) {
    var t = evt.target;
    if (!t || !t.closest) return;
    if (t.closest(".reveal-again-btn")) {
      evt.preventDefault();
      window.location.reload();
      return;
    }
    var hide = t.closest(".reveal-hide-btn");
    if (hide) {
      evt.preventDefault();
      hideNow(hide.closest(".reveal-wrap"));
      return;
    }
    var show = t.closest(".secret-show-btn");
    if (show) {
      evt.preventDefault();
      if (evt.stopPropagation) evt.stopPropagation();
      var el = targetValue(show);
      if (!el) return;
      var on = el.getAttribute("data-revealed") !== "true";
      setRevealed(el, on);
      var wrap = el.closest(".reveal-wrap");
      if (wrap) {
        if (on) arm(wrap);
        else if (!wrapIsRevealed(wrap)) hideNow(wrap);
      }
      return;
    }
    var field = t.closest(".secret-value");
    if (field && field.getAttribute("data-revealed") === "false") {
      evt.preventDefault();
      setRevealed(field, true);
      var wrap = field.closest(".reveal-wrap");
      if (wrap) arm(wrap);
    }
  });

  function fire(wrap) {
    wrap.__corvusHideTimer = null;
    var cell = wrap.closest(".secret-cell");
    if (!cell) {
      maskStandalone(wrap);
      return;
    }
    var toggle =
      document.querySelector('.reveal-toggle[hx-target="#' + cell.id + '"]') ||
      document.getElementById((cell.id || "").replace(/^reveal-/, "reveal-toggle-"));
    if (
      toggle && toggle.getAttribute("hx-get") &&
      toggle.textContent.trim() === "Hide"
    ) {
      if (window.htmx) {
        window.htmx.ajax("GET", toggle.getAttribute("hx-get"), {
          target: "#" + cell.id,
          swap: "innerHTML",
        });
      } else {
        toggle.click();
      }
      if (window.ssToast) window.ssToast("Secret auto-hidden");
    }
  }

  function arm(wrap) {
    if (!wrap || !wrap.getAttribute) return;
    if (!wrapIsRevealed(wrap)) return;
    var secs = parseInt(wrap.getAttribute("data-auto-hide") || "0", 10);
    if (!(secs > 0)) return;
    if (wrap.__corvusHideTimer) window.clearTimeout(wrap.__corvusHideTimer);
    var head = wrap.querySelector(".reveal-head") || wrap;
    var note = head.querySelector(".auto-hide-note");
    if (!note) {
      note = document.createElement("span");
      note.className = "auto-hide-note badge badge-soft";
      note.setAttribute("aria-live", "polite");
      note.innerHTML =
        '<span class="auto-hide-label">Hides in</span> <span class="auto-hide-count"></span>';
      head.appendChild(note);
    }
    note.hidden = false;
    note.innerHTML =
      '<span class="auto-hide-label">Hides in</span> <span class="auto-hide-count"></span>';
    note.setAttribute(
      "data-hide-until",
      new Date(Date.now() + secs * 1000).toISOString()
    );
    var count = note.querySelector(".auto-hide-count");
    if (count) count.textContent = secs + "s";
    wrap.__corvusHideTimer = window.setTimeout(function () {
      fire(wrap);
    }, secs * 1000);
  }

  function boot(scope) {
    if (!scope || !scope.querySelectorAll) return;
    Array.prototype.forEach.call(
      scope.querySelectorAll(".reveal-wrap[data-auto-hide]"),
      arm
    );
    if (scope.classList && scope.classList.contains("reveal-wrap")) arm(scope);
  }
  if (typeof window.onContent === "function") window.onContent(boot);
  else boot(document);
})();

/* Bulk multi-select toolbar. Hooks: input.bulk-secret-cb,
   #bulk-toolbar/#bulk-select-all/#bulk-count/#bulk-apply/#bulk-action,
   #bulk-secrets-form (or #bulk-trash fallback). */
(function bulk() {
  function boxes() {
    return document.querySelectorAll("input.bulk-secret-cb");
  }
  function picked() {
    return document.querySelectorAll("input.bulk-secret-cb:checked");
  }

  function sync() {
    var bar = document.getElementById("bulk-toolbar");
    var all = document.getElementById("bulk-select-all");
    var count = document.getElementById("bulk-count");
    var apply = document.getElementById("bulk-apply");
    var action = document.getElementById("bulk-action");
    var total = boxes().length;
    var n = picked().length;
    if (bar) bar.hidden = total === 0;
    if (count) count.textContent = String(n);
    if (all) {
      all.checked = total > 0 && n === total;
      all.indeterminate = n > 0 && n < total;
    }
    if (apply) apply.disabled = n === 0 || !action || !action.value;
  }

  document.addEventListener("change", function (evt) {
    var el = evt.target;
    if (!el) return;
    if (el.id === "bulk-select-all") {
      var on = el.checked;
      Array.prototype.forEach.call(boxes(), function (cb) {
        cb.checked = on;
      });
      sync();
    } else if (
      (el.classList && el.classList.contains("bulk-secret-cb")) ||
      el.id === "bulk-action"
    ) {
      sync();
    }
  });

  document.addEventListener("click", function (evt) {
    var btn =
      evt.target && evt.target.closest
        ? evt.target.closest("#bulk-apply")
        : null;
    if (!btn) return;
    evt.preventDefault();
    var form =
      document.getElementById("bulk-secrets-form") ||
      document.getElementById("bulk-trash");
    var action = document.getElementById("bulk-action");
    if (!form || !action || !action.value) return;
    var n = picked().length;
    if (!n) {
      if (window.ssToast) window.ssToast("Select at least one secret");
      return;
    }
    var opt = action.options[action.selectedIndex];
    var url = opt && opt.getAttribute("data-url");
    if (!url) return;
    var ask = opt && opt.getAttribute("data-confirm");
    if (ask) ask = String(ask).replace(/\{n\}/g, String(n));
    /* Single irreversible confirm for permanent bulk delete (count-aware). */
    if (action.value === "purge" && !ask) {
      ask =
        "Permanently delete " + n + (n === 1 ? " secret" : " secrets") +
        " forever? This cannot be undone.";
    }
    var stampAndSubmit = function () {
      var field =
        form.querySelector("#bulk-action-field") ||
        document.getElementById("bulk-action-field");
      if (field) field.value = action.value;
      form.setAttribute("action", url);
      form.method = "post";
      form.submit();
    };
    if (ask) {
      confirmBulk(ask, btn, stampAndSubmit);
      return;
    }
    stampAndSubmit();
  });

  /* Styled confirm for bulk actions (replaces native confirm()). The
     dialog OK path drains pendingBulk via __corvusBulkConfirm;
     dismissal drops the action. Native confirm is the fallback when
     the dialog is unavailable. */
  var pendingBulk = null;
  function confirmBulk(message, opener, proceed) {
    var dlg = document.getElementById("confirm-dlg");
    if (!dlg || typeof window.openDialog !== "function") {
      if (window.confirm(message)) proceed();
      return;
    }
    pendingBulk = proceed;
    document.getElementById("confirm-dlg-msg").textContent = message;
    dlg._opener = opener || null;
    dlg.onclose = function () {
      pendingBulk = null;
    };
    window.openDialog(dlg);
  }
  window.__corvusBulkConfirm = function () {
    var fn = pendingBulk;
    if (!fn) return false;
    pendingBulk = null;
    var dlg = document.getElementById("confirm-dlg");
    if (dlg && dlg.open && typeof window.closeDialog === "function") {
      window.closeDialog(dlg);
    }
    fn();
    return true;
  };

  if (typeof window.onContent === "function") window.onContent(sync);
  else sync();
})();

/* Plaintext export gate. Hook: form[data-export-gate] whose format
   <select> options carry download URLs; options with data-plain="1"
   need a styled confirm before navigating. Replaces the per-page
   export script (native confirm + location assign). */
(function exportGate() {
  var pendingNav = null;

  function styledConfirm(message, opener, proceed) {
    var dlg = document.getElementById("confirm-dlg");
    if (!dlg || typeof window.openDialog !== "function") {
      if (window.confirm(message)) proceed();
      return;
    }
    pendingNav = proceed;
    document.getElementById("confirm-dlg-msg").textContent = message;
    dlg._opener = opener || null;
    dlg.onclose = function () {
      pendingNav = null;
    };
    window.openDialog(dlg);
  }

  window.__corvusNavConfirm = function () {
    var fn = pendingNav;
    if (!fn) return false;
    pendingNav = null;
    var dlg = document.getElementById("confirm-dlg");
    if (dlg && dlg.open && typeof window.closeDialog === "function") {
      window.closeDialog(dlg);
    }
    fn();
    return true;
  };

  document.addEventListener("submit", function (evt) {
    var form =
      evt.target && evt.target.closest
        ? evt.target.closest("form[data-export-gate]")
        : null;
    if (!form) return;
    var sel = form.querySelector("select");
    var opt = sel && sel.options[sel.selectedIndex];
    if (!opt || !opt.value) {
      evt.preventDefault();
      return;
    }
    var go = function () {
      window.location.href = opt.value;
    };
    if (opt.getAttribute("data-plain") === "1") {
      evt.preventDefault();
      var btn = form.querySelector('[type="submit"]');
      styledConfirm(
        "Download PLAINTEXT secrets for this project?",
        btn,
        go
      );
    } else {
      evt.preventDefault();
      go();
    }
  });
})();
