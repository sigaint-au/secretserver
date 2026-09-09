/* Secret views: clipboard copy, reveal countdowns, auto-hide, bulk toolbar.
   Timers and delegated listeners only; all swap-aware via onContent. */
'use strict';

/* Copy-button handler. Hook: .copy-btn with data-copy-target/text and
   optional data-clear-seconds (clipboard auto-clear, default 30s). */
(function () {
  let clearTimer = null;
  let lastCopied = null;
  /* Resolve copyable text: explicit attr, form value, or text content. */
  function readCopyText(el, attrText) {
    if (attrText) return attrText;
    if (!el) return '';
    /* Prefer form value for inputs/textareas; PRE/DIV use text content. */
    const tag = (el.tagName || '').toUpperCase();
    if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') {
      return el.value || '';
    }
    return (el.innerText != null ? el.innerText : el.textContent) || '';
  }
  /* Legacy copy path for non-secure contexts without the Clipboard API.
     Input/textarea can select in place; PRE/structured views need a temp field. */
  function fallbackCopy(text, el) {
    if (el && typeof el.select === 'function' && (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA')) {
      try {
        el.focus();
        el.select();
        if (el.setSelectionRange) el.setSelectionRange(0, (el.value || '').length);
        if (document.execCommand('copy')) return true;
      } catch (err) { /* fall through */ }
    }
    const ta = document.createElement('textarea');
    ta.value = text;
    ta.setAttribute('readonly', '');
    ta.style.cssText = 'position:fixed;left:-9999px;top:0';
    document.body.appendChild(ta);
    ta.focus();
    ta.select();
    let ok = false;
    try { ok = document.execCommand('copy'); } catch (err) { ok = false; }
    document.body.removeChild(ta);
    return ok;
  }
  /* Handle copy-button clicks anywhere on the page. */
  document.addEventListener('click', function (e) {
    const btn = e.target.closest('.copy-btn');
    if (!btn) return;
    e.preventDefault();
    const id = btn.getAttribute('data-copy-target');
    const el = id ? document.getElementById(id) : null;
    const text = readCopyText(el, btn.getAttribute('data-copy-text') || '');
    if (!text) return;
    const secs = parseInt(btn.getAttribute('data-clear-seconds') || '30', 10);
    /* Toast success and arm clipboard auto-clear for the copied value. */
    function done() {
      window.ssToast('Copied to clipboard');
      lastCopied = text;
      if (clearTimer) clearTimeout(clearTimer);
      if (secs > 0 && navigator.clipboard && navigator.clipboard.writeText) {
        /* Clear the clipboard after the delay if our value is still there. */
        clearTimer = setTimeout(function () {
          /* Blank the clipboard only if the user hasn't copied since. */
          navigator.clipboard.readText().then(function (cur) {
            if (cur === lastCopied) {
              return navigator.clipboard.writeText('');
            }
          }).catch(function () {}); /* Clipboard read denied: leave as-is. */
          clearTimer = null;
        }, secs * 1000);
      }
    }
    /* Clipboard API often unavailable on HTTP / non-secure contexts; always
       fall back so certificate/ssh PRE blocks still copy. */
    if (navigator.clipboard && navigator.clipboard.writeText) {
      /* Clipboard API failed (e.g. non-secure context): try legacy copy. */
      navigator.clipboard.writeText(text).then(done).catch(function () {
        if (fallbackCopy(text, el)) done();
      });
    } else if (fallbackCopy(text, el)) {
      done();
    }
  });
})();

/* Grant window countdown on Reveal controls. Hooks: [data-grant-until]
   labels and [data-hide-until] auto-hide notes; one shared 1s ticker. */
(function () {
  /* Format a millisecond remainder as "expired" / "Xh Ym" / "Mm SSs". */
  function formatGrantRemain(ms) {
    if (ms <= 0) return 'expired';
    let s = Math.floor(ms / 1000);
    let m = Math.floor(s / 60);
    s = s % 60;
    if (m >= 60) {
      const h = Math.floor(m / 60);
      m = m % 60;
      return h + 'h ' + m + 'm';
    }
    return m + 'm ' + (s < 10 ? '0' : '') + s + 's';
  }
  /* Refresh all countdown/auto-hide labels under root. Returns whether
     any live node was found (drives ticker shutdown). */
  function tickGrantCountdowns(root) {
    root = root || document;
    const nodes = root.querySelectorAll
      ? root.querySelectorAll('[data-grant-until]')
      : [];
    let any = nodes.length > 0;
    /* Refresh one grant countdown label. */
    nodes.forEach(function (el) {
      const until = el.getAttribute('data-grant-until');
      if (!until) return;
      const t = Date.parse(until);
      if (isNaN(t)) return;
      const label = formatGrantRemain(t - Date.now());
      if (el.classList && el.classList.contains('grant-countdown')) {
        el.textContent = '(' + label + ')';
      } else {
        const span = el.querySelector('.grant-countdown');
        if (span) span.textContent = '(' + label + ')';
      }
    });
    /* Auto-hide countdown note (revealed secret rows) */
    const hides = root.querySelectorAll ? root.querySelectorAll('[data-hide-until]') : [];
    if (hides.length > 0) any = true;
    /* Refresh one auto-hide countdown note. */
    hides.forEach(function (el) {
      const until = el.getAttribute('data-hide-until');
      if (!until) return;
      const t = Date.parse(until);
      if (isNaN(t)) return;
      const s = Math.max(0, Math.ceil((t - Date.now()) / 1000));
      const count = el.querySelector('.auto-hide-count');
      if (count) count.textContent = s + 's';
    });
    return any;
  }
  let countdownTimer = null;
  /* Start the shared 1s ticker once; it stops itself when no live node remains. */
  function startCountdownTimer() {
    if (countdownTimer) return;
    /* One tick: refresh labels, shut down when nothing is left to count. */
    countdownTimer = setInterval(function () {
      if (!tickGrantCountdowns(document)) {
        clearInterval(countdownTimer);
        countdownTimer = null;
      }
    }, 1000);
  }
  /* Tick immediately for current content, then keep the ticker alive. */
  onContent(function (root) {
    tickGrantCountdowns(root);
    startCountdownTimer();
  });
})();

/* Auto-hide revealed secrets after N seconds. Hook:
   .reveal-wrap[data-auto-hide]; re-mask goes through the reveal toggle's
   hx-get so server state stays canonical. The timer lives on the wrap
   element itself, so re-arming a wrap replaces its own timer. */
(function () {
  /* Arm (or re-arm) the auto-hide timer for one reveal wrap. */
  function scheduleAutoHide(wrap) {
    if (!wrap || !wrap.getAttribute) return;
    const secs = parseInt(wrap.getAttribute('data-auto-hide') || '0', 10);
    if (!(secs > 0)) return;
    if (wrap._hideTimer) clearTimeout(wrap._hideTimer);
    /* Disclose the auto-hide so users aren't surprised when it re-masks. */
    const head = wrap.querySelector('.reveal-head') || wrap;
    let note = head.querySelector('.auto-hide-note');
    if (!note && secs > 0) {
      note = document.createElement('span');
      note.className = 'auto-hide-note';
      note.innerHTML =
        '<span class="auto-hide-label">Auto-hides in</span> <span class="auto-hide-count"></span>';
      head.appendChild(note);
    }
    if (note) {
      note.setAttribute('data-hide-until', new Date(Date.now() + secs * 1000).toISOString());
      const count = note.querySelector('.auto-hide-count');
      if (count) count.textContent = secs + 's';
    }
    /* Fire once: re-mask standalone wraps, re-fetch toggled cells. */
    wrap._hideTimer = setTimeout(function () {
      wrap._hideTimer = null;
      const cell = wrap.closest('.secret-cell');
      if (!cell) {
        /* Standalone wrap (e.g. secret full view): mask in place. */
        /* Mask one revealed value node (inputs keep shape, text nodes blank). */
        wrap.querySelectorAll('.secret-value').forEach(function (el) {
          if (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA') {
            el.value = '••••••••';
            el.readOnly = true;
          } else {
            el.textContent = '••••••••';
          }
        });
        /* The hidden .env copy has no .secret-value class: mask it too. */
        var hiddenEnv = wrap.querySelector('#kv-all-env');
        if (hiddenEnv) hiddenEnv.textContent = '••••••••';
        /* Disabled copy/download buttons cannot leak the masked value. */
        wrap.querySelectorAll('.copy-btn, .dl-btn').forEach(function (b) { b.disabled = true; });
        var hideNote = wrap.querySelector('.auto-hide-note');
        if (hideNote) {
          hideNote.removeAttribute('data-hide-until');
          hideNote.innerHTML = '<span class="auto-hide-label">Hidden</span>';
        }
        /* Offer a way back: reload re-renders the revealed value. */
        if (!wrap.querySelector('.reveal-again-btn')) {
          var again = document.createElement('button');
          again.type = 'button';
          again.className = 'btn btn-outline btn-sm reveal-again-btn';
          again.textContent = 'Show again';
          again.addEventListener('click', function () { window.location.reload(); });
          wrap.insertBefore(again, wrap.firstChild);
        }
        if (window.ssToast) window.ssToast('Secret hidden — reload to reveal again');
        return;
      }
      const toggle = document.querySelector(
        '.reveal-toggle[hx-target="#' + cell.id + '"]'
      ) || document.getElementById((cell.id || '').replace(/^reveal-/, 'reveal-toggle-'));
      if (toggle && toggle.getAttribute('hx-get') && toggle.textContent.trim() === 'Hide') {
        if (window.htmx) {
          window.htmx.ajax('GET', toggle.getAttribute('hx-get'), {
            target: '#' + cell.id,
            swap: 'innerHTML'
          });
        } else {
          toggle.click();
        }
        if (window.ssToast) window.ssToast('Secret auto-hidden');
      }
    }, secs * 1000);
  }
  /* Arm auto-hide for every reveal wrap under root (root itself may be one). */
  function armAutoHide(root) {
    if (!root || !root.querySelectorAll) return;
    root.querySelectorAll('.reveal-wrap[data-auto-hide]').forEach(scheduleAutoHide);
    if (root.classList && root.classList.contains('reveal-wrap')) {
      scheduleAutoHide(root);
    }
  }
  onContent(armAutoHide);
})();

/* Bulk multi-select toolbar (secrets list). Hooks: input.bulk-secret-cb,
   #bulk-select-all, #bulk-count, #bulk-apply, #bulk-action, and the
   #bulk-secrets-form / #bulk-trash target form. Document-scoped queries,
   so no swap root is needed. */
(function () {
  /* All bulk checkboxes on the page. */
  function boxes() {
    return document.querySelectorAll('input.bulk-secret-cb');
  }
  /* Checked bulk checkboxes on the page. */
  function selected() {
    return document.querySelectorAll('input.bulk-secret-cb:checked');
  }
  /* Sync toolbar visibility, count, select-all, and apply state. */
  function syncBulkToolbar() {
    const tb = document.getElementById('bulk-toolbar');
    const all = document.getElementById('bulk-select-all');
    const countEl = document.getElementById('bulk-count');
    const apply = document.getElementById('bulk-apply');
    const action = document.getElementById('bulk-action');
    const cbs = boxes();
    const n = selected().length;
    const total = cbs.length;
    if (tb) tb.hidden = total === 0;
    if (countEl) countEl.textContent = String(n);
    if (all) {
      all.checked = total > 0 && n === total;
      all.indeterminate = n > 0 && n < total;
    }
    if (apply) {
      apply.disabled = n === 0 || !action || !action.value;
    }
  }
  /* Track select-all, per-row, and action-select changes. */
  document.addEventListener('change', function (e) {
    const t = e.target;
    if (!t) return;
    if (t.id === 'bulk-select-all') {
      const on = t.checked;
      /* Select-all pushes its state to every row checkbox. */
      boxes().forEach(function (cb) { cb.checked = on; });
      syncBulkToolbar();
      return;
    }
    if (t.classList && t.classList.contains('bulk-secret-cb')) {
      syncBulkToolbar();
      return;
    }
    if (t.id === 'bulk-action') {
      syncBulkToolbar();
    }
  });
  /* Apply the chosen bulk action: confirm, stamp, retarget, submit. */
  document.addEventListener('click', function (e) {
    const btn = e.target && e.target.closest && e.target.closest('#bulk-apply');
    if (!btn) return;
    e.preventDefault();
    const form = document.getElementById('bulk-secrets-form')
      || document.getElementById('bulk-trash');
    const action = document.getElementById('bulk-action');
    if (!form || !action || !action.value) return;
    if (!selected().length) {
      if (window.ssToast) window.ssToast('Select at least one secret');
      return;
    }
    const opt = action.options[action.selectedIndex];
    const url = opt && opt.getAttribute('data-url');
    let confirmMsg = opt && opt.getAttribute('data-confirm');
    const n = selected().length;
    if (!url) return;
    if (confirmMsg) {
      confirmMsg = String(confirmMsg).replace(/\{n\}/g, String(n));
      if (!window.confirm(confirmMsg)) return;
    }
    /* Single irreversible confirm for permanent bulk delete (count-aware). */
    if (action.value === 'purge'
        && !window.confirm(
             'Permanently delete ' + n + (n === 1 ? ' secret' : ' secrets')
             + ' forever? This cannot be undone.')) {
      return;
    }
    const field = form.querySelector('#bulk-action-field')
      || document.getElementById('bulk-action-field');
    if (field) field.value = action.value;
    form.setAttribute('action', url);
    form.method = 'post';
    form.submit();
  });
  onContent(syncBulkToolbar);
})();
