/* Corvus UI glue: HTMX event wiring, content-init registry, toast bridge.
   Loads first: defines onContent/htmxSwapRoot/ssToast for the components.
   Delegation and HTMX events only; no per-widget code lives here. */
'use strict';

/* CSRF header for HTMX requests (htmx 4: detail carries ctx) */
document.addEventListener('htmx:config:request', function (e) {
  const m = document.querySelector('meta[name="csrf-token"]');
  const headers = (((e.detail || {}).ctx || {}).request || {}).headers;
  if (m && headers) headers['X-CSRF-Token'] = m.content;
});

/* Resolve the swapped content root for htmx 4 events. htmx 4 dispatches on
   the requesting element and carries the hx-target selector on detail.ctx,
   so e.target alone no longer points at fresh content. */
function htmxSwapRoot(e) {
  const ctx = (e && e.detail && e.detail.ctx) || {};
  const t = ctx.target;
  let el = null;
  if (typeof t === 'string' && t.charAt(0) === '#'
      && t.indexOf(' ') < 0 && t.indexOf('.') < 0
      && t.indexOf('[') < 0 && t.indexOf(':') < 0 && t.length > 1) {
    el = document.getElementById(t.slice(1));
  }
  if (!el && e && e.target && e.target !== document && e.target !== document.body
      && e.target.querySelectorAll) {
    el = e.target;
  }
  return el || document;
}

/* Content-init registry: components that touch swapped-in markup register an
   idempotent init(root) here instead of owning private DOMContentLoaded /
   htmx:after:swap wiring. Registration runs the init once for the initial
   page; one global fan-out below re-runs all inits on fresh content. Inits
   must tolerate missing nodes (panels render conditionally). */
const contentInits = [];
/* Register a content init and run it for the initial page. Scripts load
   with defer, so the DOM is already complete at registration time. */
function onContent(fn) {
  contentInits.push(fn);
  fn(document);
}
/* Re-run every content init against freshly swapped markup. */
document.addEventListener('htmx:after:swap', function (e) {
  const root = htmxSwapRoot(e);
  contentInits.forEach(function (fn) { fn(root); }); /* Fan out to all inits. */
});

/* Move focus into tab panels after HTMX swaps, mirroring full page loads
   for keyboard and screen-reader users. Mouse users see no focus ring:
   script focus after a pointer click does not match :focus-visible. */
document.body.addEventListener('htmx:after:swap', function (e) {
  const ctx = (e.detail || {}).ctx || {};
  const t = ctx.target;
  if (typeof t === 'string' && (t === '#project-panel' || t === '#secret-panel' || t === '#folder-panel' || t === '#team-panel' || t === '#profile-panel' || t === '#roles-panel')) {
    const panel = document.getElementById(t.slice(1));
    if (panel && panel.focus) {
      try { panel.focus({ preventScroll: true }); } catch (err) { panel.focus(); }
    }
  }
});

/* Never swap machine-readable error bodies into content panels: the error
   toast below already tells the user what happened. */
document.body.addEventListener('htmx:before:swap', function (e) {
  const ctx = (e.detail || {}).ctx || {};
  let type = '';
  try {
    type = (ctx.response && ctx.response.headers && ctx.response.headers.get('content-type')) || '';
  } catch (err) { type = ''; }
  if (type.indexOf('json') !== -1 && e.preventDefault) e.preventDefault();
});

/* Toast bridge (daisyUI toast + alert). Exposes window.ssToast for inline
   callers (e.g. JWT panel); HTMX failures toast globally so error bodies
   never need swapping in. */
(function () {
  /* Show a toast, falling back to console when the DOM is unavailable. */
  function toast(msg, title, opts) {
    const text = String(msg || '');
    const duration = (opts && opts.duration) || 2200;
    if (!document || !document.body) {
      if (window.console) console.info(text);
      return;
    }
    let host = document.getElementById('ss-toasts');
    if (!host) {
      host = document.createElement('div');
      host.id = 'ss-toasts';
      host.className = 'toast toast-top toast-end';
      host.setAttribute('aria-live', 'polite');
      document.body.appendChild(host);
    }
    const kind = (title === 'Error' || title === 'error') ? 'alert-error' : 'alert-success';
    const el = document.createElement('div');
    el.className = 'alert ' + kind;
    el.setAttribute('role', 'alert');
    if (title) {
      const head = document.createElement('strong');
      head.textContent = title;
      el.appendChild(head);
    }
    const body = document.createElement('span');
    body.textContent = text;
    el.appendChild(body);
    host.appendChild(el);
    let timer = 0;
    const dismiss = function () {
      if (timer) window.clearTimeout(timer);
      if (el.parentNode) el.parentNode.removeChild(el);
    };
    el.addEventListener('click', dismiss);
    el.addEventListener('mouseenter', function () {
      if (timer) window.clearTimeout(timer);
    });
    el.addEventListener('mouseleave', function () {
      timer = window.setTimeout(dismiss, 1500);
    });
    if (duration > 0) timer = window.setTimeout(dismiss, duration);
  }
  window.ssToast = toast;
  /* Toast on failed HTMX responses (the JSON body itself is never swapped). */
  document.body.addEventListener('htmx:response:error', function () {
    toast('The action failed. Please try again.', 'Error', { duration: 5000 });
  });
  /* Toast on HTMX transport errors (server unreachable). */
  document.body.addEventListener('htmx:error', function () {
    toast('The server could not be reached. Please try again.', 'Error', { duration: 5000 });
  });
  /* Toast on explicit opt-in: POST sources with data-toast-success. */
  document.body.addEventListener('htmx:after:request', function (e) {
    const ctx = (e.detail || {}).ctx || {};
    const request = ctx.request || {};
    const status = (ctx.response || {}).status || 0;
    const elt = ctx.sourceElement;
    if (request.method === 'POST' && status >= 200 && status < 400
        && elt && elt.dataset && elt.dataset.toastSuccess) {
      toast(elt.dataset.toastSuccess, 'Done');
    }
  });
})();
