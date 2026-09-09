/* Dialogs, busy buttons, and the styled HTMX confirm.
   Hooks: [data-open-dialog], [data-close-dialog], [data-dismiss],
   [data-submit-form], [commandfor][command], [data-nav], #confirm-dlg.
   Exposes window.openDialog/closeDialog/setAccessBusy/restoreAccessBusy
   for inline callers. All delegated: swapped-in dialogs just work. */
'use strict';

/* Dialog open/close + menu navigation (commandfor is not widely available).
   Openers are tracked on dlg._opener so focus returns on close. */
(function () {
  /* Open a <dialog> modally (fallback: open attribute) and focus it. */
  function openDialog(dlg) {
    if (!dlg) return;
    if (typeof dlg.showModal === 'function') {
      if (!dlg.open) dlg.showModal();
    } else {
      dlg.setAttribute('open', '');
    }
    const focusEl = dlg.querySelector('input:not([type=hidden]), button:not([data-close-dialog])');
    /* Focus after paint so the dialog has laid out. */
    if (focusEl && focusEl.focus) setTimeout(function () { focusEl.focus(); }, 20);
  }
  /* Close a dialog and restore focus to its opener when still connected. */
  function closeDialog(dlg) {
    if (!dlg) return;
    if (typeof dlg.close === 'function') dlg.close();
    else dlg.removeAttribute('open');
    const opener = dlg._opener;
    dlg._opener = null;
    if (opener && opener.isConnected && !opener.disabled) opener.focus();
  }
  window.openDialog = openDialog;
  window.closeDialog = closeDialog;

  /* Access approve/deny: disable + relabel the submit button for consistent
     busy feedback (approve buttons live outside their form via form=).
     Original label is stashed on the button for restoreAccessBusy. */
  /* Mark a form's submit button busy with a replacement label. */
  function setAccessBusy(form, label) {
    const btn = form.querySelector('button[type="submit"]')
      || (form.id && document.querySelector('button[form="' + form.id + '"]'));
    if (btn) {
      if (!btn.dataset.busy) {
        btn.dataset.busy = '1';
        btn.dataset.label = btn.textContent;
      }
      btn.disabled = true;
      btn.textContent = label;
    }
    return true;
  }
  /* Undo setAccessBusy (e.g. a styled confirm was dismissed after the
     submit already marked the button busy). */
  /* Restore a form's submit button from its stashed busy state. */
  function restoreAccessBusy(form) {
    if (!form || !form.querySelector) return;
    const btn = form.querySelector('button[type="submit"]')
      || (form.id && document.querySelector('button[form="' + form.id + '"]'));
    if (btn && btn.dataset.busy) {
      btn.disabled = false;
      if (btn.dataset.label) btn.textContent = btn.dataset.label;
      delete btn.dataset.busy;
      delete btn.dataset.label;
    }
  }
  window.setAccessBusy = setAccessBusy;
  window.restoreAccessBusy = restoreAccessBusy;

  /* Global dialog/menu delegation: open, close, dismiss, cross-form submit,
     commandfor polyfill, data-nav, and the styled-confirm OK button. */
  document.addEventListener('click', function (e) {
    const openBtn = e.target.closest && e.target.closest('[data-open-dialog]');
    if (openBtn) {
      e.preventDefault();
      const id = openBtn.getAttribute('data-open-dialog');
      const dlg = id ? document.getElementById(id) : null;
      if (dlg) {
        dlg._opener = openBtn;
        openDialog(dlg);
      }
      return;
    }
    const closeBtn = e.target.closest && e.target.closest('[data-close-dialog]');
    if (closeBtn) {
      e.preventDefault();
      const cid = closeBtn.getAttribute('data-close-dialog');
      const cdlg = cid ? document.getElementById(cid) : closeBtn.closest('dialog');
      if (cdlg) closeDialog(cdlg);
      return;
    }
    const dismissBtn = e.target.closest && e.target.closest('[data-dismiss]');
    if (dismissBtn) {
      e.preventDefault();
      const target = dismissBtn.closest(dismissBtn.getAttribute('data-dismiss') || '[role="alert"]');
      if (target) target.remove();
      return;
    }
    const submitBtn = e.target.closest && e.target.closest('[data-submit-form]');
    if (submitBtn) {
      e.preventDefault();
      const form = document.getElementById(submitBtn.getAttribute('data-submit-form'));
      if (!form) return;
      const action = form.querySelector('[data-dialog-action]');
      if (action) {
        action.name = 'action';
        action.value = submitBtn.getAttribute('data-submit-action') || '';
      }
      if (form.requestSubmit) form.requestSubmit();
      else form.submit();
      return;
    }
    /* commandfor polyfill for browsers without Invoker Commands */
    const cmdBtn = e.target.closest && e.target.closest('[commandfor][command]');
    if (cmdBtn) {
      const tid = cmdBtn.getAttribute('commandfor');
      const cmd = cmdBtn.getAttribute('command');
      const tel = tid ? document.getElementById(tid) : null;
      if (!tel) return;
      if (cmd === 'show-modal') {
        e.preventDefault();
        openDialog(tel);
      } else if (cmd === 'close') {
        e.preventDefault();
        closeDialog(tel);
      }
      return;
    }
    /* History (and other data-nav) from dropdown menus */
    const navBtn = e.target.closest && e.target.closest('[data-nav]');
    if (navBtn) {
      e.preventDefault();
      const href = navBtn.getAttribute('data-nav');
      if (href) window.location.href = href;
      return;
    }
    /* Global styled confirm (confirm-dlg): resolves a pending hx-confirm */
    const confirmOk = e.target.closest && e.target.closest('#confirm-dlg-ok');
    if (confirmOk) {
      settleConfirm(true);
      return;
    }
  });

  /* Styled replacement for native hx-confirm(): one global dialog fed by
     the htmx:confirm event (v4 detail carries issueRequest/dropRequest),
     so destructive HTMX actions share the app's dialog styling. Runs in
     the bubble phase on document; preventDefault suppresses the native
     window.confirm fallback inside htmx. */
  let pendingConfirm = null;
  /* Resolve the pending styled confirm: issue the HTMX request, or drop it
     (restoring busy state) when dismissed. */
  function settleConfirm(confirmed) {
    const p = pendingConfirm;
    pendingConfirm = null;
    const d = document.getElementById('confirm-dlg');
    if (d && d.open) closeDialog(d);
    if (!p) return;
    if (confirmed) p.issue();
    else {
      if (p.form) restoreAccessBusy(p.form);
      p.drop();
    }
  }
  /* Classification banner presets (server + team settings): swatches
     carry data-bg/data-fg; one delegated listener replaces the inline
     onclick handlers (applyPreset lives in the color-picker include). */
  /* Classification banner swatches delegate to the color-picker include. */
  document.addEventListener('click', function (e) {
    const sw = e.target.closest && e.target.closest('.swatch-row .swatch[data-bg]');
    if (!sw || typeof window.applyPreset !== 'function') return;
    window.applyPreset(
      sw.getAttribute('data-bg'),
      sw.getAttribute('data-fg') || '#ffffff'
    );
  });
  /* Reveal-request approve forms: keep the styled confirm text in sync
     with the chosen grant duration (mirrors the server-rendered default). */
  /* Render grant minutes as "N minutes" / "1 hour" / "1 day" / "N hours". */
  function grantDurationLabel(raw) {
    const m = parseInt(raw, 10) || 0;
    if (m < 60) return m + ' minutes';
    if (m === 60) return '1 hour';
    if (m === 1440) return '1 day';
    return (m / 60) + ' hours';
  }
  /* Keep the styled confirm text in sync with the chosen grant duration. */
  document.addEventListener('change', function (e) {
    const sel = e.target.closest && e.target.closest('select[id^="grant-minutes-"]');
    if (!sel) return;
    const form = sel.closest ? sel.closest('form') : null;
    if (form) form.setAttribute('hx-confirm', 'Approve reveal for ' + grantDurationLabel(sel.value) + '?');
  });
  /* Feed hx-confirm prompts into the styled dialog instead of window.confirm.
     preventDefault suppresses htmx's native fallback. */
  document.addEventListener('htmx:confirm', function (e) {
    const d = document.getElementById('confirm-dlg');
    const el = e.target && e.target.getAttribute ? e.target : null;
    const q = el ? el.getAttribute('hx-confirm') : null;
    if (!d || !q || !e.detail || !e.detail.issueRequest) return;
    e.preventDefault();
    if (pendingConfirm) pendingConfirm.drop();
    const srcForm = el.tagName === 'FORM' ? el : (el.closest ? el.closest('form') : null);
    pendingConfirm = { issue: e.detail.issueRequest, drop: e.detail.dropRequest, form: srcForm };
    document.getElementById('confirm-dlg-msg').textContent = q;
    d._opener = el;
    /* Dismissing the dialog drops the pending confirm. */
    d.onclose = function () {
      if (pendingConfirm) settleConfirm(false);
    };
    openDialog(d);
  });
  /* After an access-request POST re-renders a dialog, keep it open. */
  function reopenAccessDialog(t) {
    if (!t) return;
    if (t.matches && t.matches('dialog') && t.open === false) openDialog(t);
    if (t.id && String(t.id).indexOf('access-dlg-') === 0) {
      if (!t.open) openDialog(t);
    }
  }
  onContent(reopenAccessDialog);
})();
