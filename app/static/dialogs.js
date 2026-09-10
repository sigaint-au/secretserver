/* Dialogs, busy buttons, and the styled HTMX confirm.
   Hooks: [data-open-dialog], [data-close-dialog], [data-dismiss],
   [data-submit-form], [commandfor][command], [data-nav], #confirm-dlg.
   Globals for inline callers: openDialog, closeDialog, setAccessBusy,
   restoreAccessBusy. Fully delegated — swapped-in dialogs just work. */
"use strict";

/* Show a <dialog> modally (attribute fallback) and move focus inside. */
function openDialog(dlg) {
  if (!dlg) return;
  if (typeof dlg.showModal === "function") {
    if (!dlg.open) dlg.showModal();
  } else {
    dlg.setAttribute("open", "");
  }
  var focusEl = dlg.querySelector(
    "input:not([type=hidden]), button:not([data-close-dialog])"
  );
  if (focusEl && focusEl.focus) {
    window.setTimeout(function () {
      focusEl.focus();
    }, 20);
  }
}

/* Close a dialog and return focus to whatever opened it, when possible. */
function closeDialog(dlg) {
  if (!dlg) return;
  if (typeof dlg.close === "function") dlg.close();
  else dlg.removeAttribute("open");
  var opener = dlg._opener;
  dlg._opener = null;
  if (opener && opener.isConnected && !opener.disabled) opener.focus();
}

/* Mark an access form's submit button busy (approve/deny live outside
   their form via form=, so plain submit dimming never sees them). */
function setAccessBusy(form, label) {
  var btn =
    form.querySelector('button[type="submit"]') ||
    (form.id && document.querySelector('button[form="' + form.id + '"]'));
  if (!btn) return false;
  if (!btn.dataset.busy) {
    btn.dataset.busy = "1";
    btn.dataset.label = btn.textContent;
  }
  btn.disabled = true;
  btn.textContent = label;
  return true;
}

/* Undo setAccessBusy (styled confirm dismissed after the mark). */
function restoreAccessBusy(form) {
  if (!form || !form.querySelector) return;
  var btn =
    form.querySelector('button[type="submit"]') ||
    (form.id && document.querySelector('button[form="' + form.id + '"]'));
  if (btn && btn.dataset.busy) {
    btn.disabled = false;
    if (btn.dataset.label) btn.textContent = btn.dataset.label;
    delete btn.dataset.busy;
    delete btn.dataset.label;
  }
}

(function delegation() {
  document.addEventListener("click", function (evt) {
    var near = function (sel) {
      return evt.target && evt.target.closest
        ? evt.target.closest(sel)
        : null;
    };

    var opener = near("[data-open-dialog]");
    if (opener) {
      evt.preventDefault();
      var dlg = document.getElementById(opener.getAttribute("data-open-dialog"));
      if (dlg) {
        dlg._opener = opener;
        openDialog(dlg);
      }
      return;
    }

    var closer = near("[data-close-dialog]");
    if (closer) {
      evt.preventDefault();
      var cid = closer.getAttribute("data-close-dialog");
      var target = cid
        ? document.getElementById(cid)
        : closer.closest("dialog");
      if (target) closeDialog(target);
      return;
    }

    var dismisser = near("[data-dismiss]");
    if (dismisser) {
      evt.preventDefault();
      var scope = dismisser.getAttribute("data-dismiss") || '[role="alert"]';
      var node = dismisser.closest(scope);
      if (node) node.remove();
      return;
    }

    var proxy = near("[data-submit-form]");
    if (proxy) {
      evt.preventDefault();
      var form = document.getElementById(proxy.getAttribute("data-submit-form"));
      if (!form) return;
      var action = form.querySelector("[data-dialog-action]");
      if (action) {
        action.name = "action";
        action.value = proxy.getAttribute("data-submit-action") || "";
      }
      if (form.requestSubmit) form.requestSubmit();
      else form.submit();
      return;
    }

    /* Invoker-command polyfill for browsers without commandfor support. */
    var cmdBtn = near("[commandfor][command]");
    if (cmdBtn) {
      var tel = document.getElementById(cmdBtn.getAttribute("commandfor"));
      if (!tel) return;
      var cmd = cmdBtn.getAttribute("command");
      if (cmd === "show-modal") {
        evt.preventDefault();
        openDialog(tel);
      } else if (cmd === "close") {
        evt.preventDefault();
        closeDialog(tel);
      }
      return;
    }

    var navBtn = near("[data-nav]");
    if (navBtn) {
      evt.preventDefault();
      var href = navBtn.getAttribute("data-nav");
      if (href) window.location.href = href;
      return;
    }

    if (near("#confirm-dlg-ok")) {
      if (
        window.__corvusFormConfirm &&
        window.__corvusFormConfirm()
      ) {
        return;
      }
      settleConfirm(true);
    }
  });

  /* Styled replacement for native hx-confirm: one global dialog fed by
     htmx:confirm (issueRequest/dropRequest). preventDefault suppresses
     htmx's window.confirm fallback. */
  var pending = null;

  function settleConfirm(ok) {
    var cur = pending;
    pending = null;
    var dlg = document.getElementById("confirm-dlg");
    if (dlg && dlg.open) closeDialog(dlg);
    if (!cur) return;
    if (ok) {
      cur.issue();
    } else {
      if (cur.form) restoreAccessBusy(cur.form);
      cur.drop();
    }
  }
  /* Exposed for the dialog's own dismiss path. */
  window.__corvusSettleConfirm = settleConfirm;

  document.addEventListener("htmx:confirm", function (evt) {
    var dlg = document.getElementById("confirm-dlg");
    var src =
      evt.target && evt.target.getAttribute ? evt.target : null;
    var question = src ? src.getAttribute("hx-confirm") : null;
    if (!dlg || !question || !evt.detail || !evt.detail.issueRequest) return;
    evt.preventDefault();
    if (pending) pending.drop();
    pending = {
      issue: evt.detail.issueRequest,
      drop: evt.detail.dropRequest,
      form: src.tagName === "FORM" ? src : src.closest("form"),
    };
    document.getElementById("confirm-dlg-msg").textContent = question;
    dlg._opener = src;
    dlg.onclose = function () {
      if (pending) settleConfirm(false);
    };
    openDialog(dlg);
  });

  /* Keep the styled confirm text in sync with the chosen grant duration. */
  document.addEventListener("change", function (evt) {
    var sel =
      evt.target && evt.target.closest
        ? evt.target.closest('select[id^="grant-minutes-"]')
        : null;
    if (!sel) return;
    var form = sel.closest ? sel.closest("form") : null;
    if (form) {
      form.setAttribute("hx-confirm", "Approve reveal for " + grantLabel(sel.value) + "?");
    }
  });

  function grantLabel(raw) {
    var mins = parseInt(raw, 10) || 0;
    if (mins < 60) return mins + " minutes";
    if (mins === 60) return "1 hour";
    if (mins === 1440) return "1 day";
    return mins / 60 + " hours";
  }

  /* Classification swatches delegate to the color-picker include. */
  document.addEventListener("click", function (evt) {
    var sw =
      evt.target && evt.target.closest
        ? evt.target.closest(".swatch-row .swatch[data-bg]")
        : null;
    if (sw && typeof window.applyPreset === "function") {
      window.applyPreset(sw.getAttribute("data-bg"), sw.getAttribute("data-fg") || "#ffffff");
    }
  });

  /* Styled confirm gate for plain (non-HTMX) POST forms. Hook:
     form[data-confirm], with optional data-confirm-if (gate only when
     the selector matches a checked control) and {field} placeholders
     filled from the form's named fields. Replaces native confirm()
     so plain destructive posts share the app dialog styling.
     Capture phase + stopPropagation: a dismissed gate must not reach
     the duplicate-submit guard (buttons stay usable). */
  var pendingForm = null;

  function formMessage(form) {
    var raw = form.getAttribute("data-confirm") || "Are you sure?";
    return raw.replace(/\{([A-Za-z0-9_-]+)\}/g, function (match, name) {
      var field = form.elements ? form.elements.namedItem(name) : null;
      var val = field && field.value ? String(field.value).trim() : "";
      return val || "this user";
    });
  }

  function gateApplies(form) {
    var sel = form.getAttribute("data-confirm-if");
    if (!sel) return true;
    var node = null;
    try {
      node = form.querySelector(sel);
    } catch (err) {
      node = null;
    }
    return !!(node && node.checked);
  }

  document.addEventListener(
    "submit",
    function (evt) {
      var form = evt.target;
      if (!form || form.tagName !== "FORM" || !form.hasAttribute("data-confirm")) {
        return;
      }
      if (form.__corvusConfirmed) {
        form.__corvusConfirmed = false;
        return;
      }
      if (!gateApplies(form)) return;
      evt.preventDefault();
      evt.stopPropagation();
      var dlg = document.getElementById("confirm-dlg");
      if (!dlg) {
        /* No styled dialog available: fall back to native confirm. */
        if (window.confirm(formMessage(form))) {
          form.__corvusConfirmed = true;
          if (form.requestSubmit) form.requestSubmit();
          else form.submit();
        }
        return;
      }
      pendingForm = form;
      document.getElementById("confirm-dlg-msg").textContent = formMessage(form);
      dlg._opener = form.querySelector('button[type="submit"]');
      dlg.onclose = function () {
        pendingForm = null;
      };
      openDialog(dlg);
    },
    true
  );

  window.__corvusFormConfirm = function () {
    var form = pendingForm;
    if (!form) return false;
    pendingForm = null;
    var dlg = document.getElementById("confirm-dlg");
    if (dlg && dlg.open) closeDialog(dlg);
    form.__corvusConfirmed = true;
    if (form.requestSubmit) form.requestSubmit();
    else form.submit();
    return true;
  };

  /* After an access-request POST re-renders its dialog, keep it open. */
  function keepOpen(node) {
    if (!node || !node.matches) return;
    if (node.matches("dialog") && node.open === false) openDialog(node);
    if (node.id && node.id.indexOf("access-dlg-") === 0 && !node.open) {
      openDialog(node);
    }
  }
  if (typeof window.onContent === "function") window.onContent(keepOpen);
})();
