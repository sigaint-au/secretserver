/* Core UI runtime: HTMX request hardening, content-init fan-out, toast
   bridge. Loads first; exposes onContent/htmxSwapRoot/ssToast.
   Delegated document listeners only — no per-widget code lives here. */
"use strict";

/* Attach the CSRF token to every HTMX request (htmx 4 event shape). */
document.addEventListener("htmx:config:request", function (evt) {
  var meta = document.querySelector('meta[name="csrf-token"]');
  var detail = evt.detail || {};
  var headers = ((detail.ctx || {}).request || {}).headers;
  if (meta && meta.content && headers) headers["X-CSRF-Token"] = meta.content;
});

/* Find the freshly swapped root for an htmx 4 event: prefer the hx-target
   element when it is a plain id selector, else the event target. */
function htmxSwapRoot(evt) {
  var target = evt && evt.detail && evt.detail.ctx && evt.detail.ctx.target;
  if (typeof target === "string" && /^#[A-Za-z0-9_-]+$/.test(target)) {
    var byId = document.getElementById(target.slice(1));
    if (byId) return byId;
  }
  if (evt && evt.target && evt.target !== document && evt.target !== document.body &&
      evt.target.querySelectorAll) {
    return evt.target;
  }
  return document;
}

/* Registry for idempotent init(scope) passes over swapped-in markup.
   Registration runs once for the first paint; every htmx:after:swap
   re-runs all inits. Inits must tolerate absent nodes. */
var corvusInits = [];
function onContent(init) {
  corvusInits.push(init);
  init(document);
}
document.addEventListener("htmx:after:swap", function (evt) {
  var root = htmxSwapRoot(evt);
  corvusInits.forEach(function (init) {
    init(root);
  });
});

/* After a tab/panel swap, move focus into the panel so keyboard and
   screen-reader users land on the new content (no visible ring for
   pointer users: script focus skips :focus-visible). */
var FOCUS_PANELS = [
  "#project-panel",
  "#secret-panel",
  "#folder-panel",
  "#team-panel",
  "#profile-panel",
  "#roles-panel",
];
document.body.addEventListener("htmx:after:swap", function (evt) {
  var target = evt && evt.detail && evt.detail.ctx && evt.detail.ctx.target;
  if (FOCUS_PANELS.indexOf(target) < 0) return;
  var panel = document.getElementById(String(target).slice(1));
  if (panel && panel.focus) {
    try {
      panel.focus({ preventScroll: true });
    } catch (err) {
      panel.focus();
    }
  }
});

/* Never swap machine-readable JSON error bodies into content panels;
   the toast bridge below already reports the failure to the user. */
document.body.addEventListener("htmx:before:swap", function (evt) {
  var type = "";
  try {
    var resp = (evt.detail && evt.detail.ctx && evt.detail.ctx.response) || {};
    type = (resp.headers && resp.headers.get("content-type")) || "";
  } catch (err) {
    type = "";
  }
  if (type.indexOf("json") !== -1 && evt.preventDefault) evt.preventDefault();
});

/* Toast bridge: daisyUI toast + alert stack. window.ssToast(msg, title).
   HTMX failures toast globally; opt-in success toasts via
   data-toast-success on POST sources. */
(function toasts() {
  function show(message, title, opts) {
    var text = String(message == null ? "" : message);
    var ttl = (opts && opts.duration) || 2200;
    if (!document || !document.body) {
      if (window.console) window.console.info(text);
      return;
    }
    var host = document.getElementById("ss-toasts");
    if (!host) {
      host = document.createElement("div");
      host.id = "ss-toasts";
      host.className = "toast toast-top toast-end";
      host.setAttribute("aria-live", "polite");
      document.body.appendChild(host);
    }
    var kind =
      title === "Error" || title === "error" ? "alert-error" : "alert-success";
    var card = document.createElement("div");
    card.className = "alert " + kind;
    card.setAttribute("role", "alert");
    if (title) {
      var head = document.createElement("strong");
      head.textContent = title;
      card.appendChild(head);
    }
    var body = document.createElement("span");
    body.textContent = text;
    card.appendChild(body);
    host.appendChild(card);
    var timer = 0;
    function dismiss() {
      if (timer) window.clearTimeout(timer);
      if (card.parentNode) card.parentNode.removeChild(card);
    }
    card.addEventListener("click", dismiss);
    card.addEventListener("mouseenter", function () {
      if (timer) window.clearTimeout(timer);
    });
    card.addEventListener("mouseleave", function () {
      timer = window.setTimeout(dismiss, 1500);
    });
    if (ttl > 0) timer = window.setTimeout(dismiss, ttl);
  }

  window.ssToast = show;

  document.body.addEventListener("htmx:response:error", function () {
    show("The action failed. Please try again.", "Error", { duration: 5000 });
  });
  document.body.addEventListener("htmx:error", function () {
    show("The server could not be reached. Please try again.", "Error", {
      duration: 5000,
    });
  });
  document.body.addEventListener("htmx:after:request", function (evt) {
    var ctx = (evt.detail || {}).ctx || {};
    var status = ((ctx.response || {}).status) || 0;
    var src = ctx.sourceElement;
    if (
      ((ctx.request || {}).method) === "POST" &&
      status >= 200 && status < 400 &&
      src && src.dataset && src.dataset.toastSuccess
    ) {
      show(src.dataset.toastSuccess, "Done");
    }
  });
})();
