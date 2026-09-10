/* Form behaviors: confirm gates, autocomplete, token scope chips,
   unsaved-changes guard, submit dimming, duplicate-submit guard.
   All delegated or registry-driven, so swapped-in forms just work. */
'use strict';

/* Type-to-confirm gates (e.g. team deletion): enable the submit button
   only when the input matches the expected value exactly. */
document.addEventListener('input', function (ev) {
  const el = ev.target && ev.target.closest ? ev.target.closest('[data-confirm-for]') : null;
  if (!el) return;
  const btn = document.getElementById(el.getAttribute('data-confirm-for'));
  if (!btn) return;
  btn.disabled = (el.value || '') !== (el.getAttribute('data-confirm-value') || '');
});

/* User email autocomplete for member fields. Hook: inputs.user-suggest
   paired with the global #user-suggest-list datalist (in base.html).
   Delegated, so swapped-in forms work with no re-init. */
(function () {
  const list = document.getElementById('user-suggest-list');
  if (!list) return;
  let timer = null;
  let lastQ = '';
  /* Replace datalist options with the suggestion payload. */
  function fill(items) {
    list.innerHTML = '';
    /* Append one suggestion as a datalist option. */
    (items || []).forEach(function (it) {
      const o = document.createElement('option');
      o.value = it.email;
      o.label = it.label || it.email;
      list.appendChild(o);
    });
  }
  /* Debounced suggest fetch for .user-suggest inputs (200ms, skips repeats). */
  document.addEventListener('input', function (e) {
    const el = e.target;
    if (!el || !el.classList || !el.classList.contains('user-suggest')) return;
    const q = (el.value || '').trim();
    if (q.length < 1) {
      fill([]);
      return;
    }
    clearTimeout(timer);
    /* Fetch suggestions unless the query is unchanged since the last fetch. */
    timer = setTimeout(function () {
      if (q === lastQ) return;
      lastQ = q;
      fetch('/api/users/suggest?q=' + encodeURIComponent(q), {
        headers: { 'Accept': 'application/json' },
        credentials: 'same-origin'
      })
        .then(function (r) { return r.ok ? r.json() : []; }) /* Non-2xx reads as empty. */
        .then(fill)
        .catch(function () { fill([]); }) /* Network failure reads as empty. */
    }, 200);
  });
})();

/* Role editor Form/YAML switch (daisyUI tabs pattern).
   Hook: .role-mode-tabs [role="tab"][data-mode] with #mode-<mode>-panel
   siblings. Replaces the former legacy tab behavior. */
(function () {
  function selectTab(list, btn) {
    const tabs = Array.prototype.slice.call(list.querySelectorAll('[role="tab"][data-mode]'));
    tabs.forEach(function (t) {
      const on = t === btn;
      t.setAttribute('aria-selected', on ? 'true' : 'false');
      t.tabIndex = on ? 0 : -1;
      const panel = t.getAttribute('aria-controls') && document.getElementById(t.getAttribute('aria-controls'));
      if (panel) panel.hidden = !on;
    });
  }
  function boot(root) {
    (root || document).querySelectorAll('.role-mode-tabs').forEach(function (list) {
      if (list._modeBound) return;
      list._modeBound = true;
      list.addEventListener('click', function (e) {
        const btn = e.target.closest && e.target.closest('[role="tab"][data-mode]');
        if (btn && list.contains(btn)) selectTab(list, btn);
      });
      list.addEventListener('keydown', function (e) {
        if (e.key !== 'ArrowLeft' && e.key !== 'ArrowRight') return;
        const tabs = Array.prototype.slice.call(list.querySelectorAll('[role="tab"][data-mode]'));
        const i = tabs.indexOf(document.activeElement);
        if (i < 0) return;
        e.preventDefault();
        const next = tabs[(i + (e.key === 'ArrowRight' ? 1 : tabs.length - 1)) % tabs.length];
        if (next) {
          selectTab(list, next);
          next.focus();
        }
      });
    });
  }
  onContent(boot);
})();

/* Machine token create: scope chips (ss-taginput) + restrict toggle.
   Hook: form[data-scope-form] with [data-scope-toggle/body/tags/hidden],
   [data-token-role], [data-token-write-warn], [data-scope-preset] buttons.
   The ss-taginput widget itself is untouched; only its value is read. */
(function () {
  /* Read tag list from the tag input (array- or comma-string-valued). */
  function tagsOf(el) {
    if (!el) return [];
    try {
      const v = el.value;
      if (Array.isArray(v)) return v.map(String).filter(Boolean);
      if (typeof v === 'string' && v) {
        /* Split on commas, drop blanks. */
        return v.split(',').map(function (s) { return s.trim(); }).filter(Boolean);
      }
    } catch {}
    return [];
  }
  /* Replace the tag input's value (best effort; widget may reject). */
  function setTags(el, arr) {
    if (!el) return;
    try { el.value = arr; } catch {}
  }
  /* Append one tag unless blank or already present. */
  function addTag(el, tag) {
    tag = (tag || '').trim();
    if (!tag) return;
    const cur = tagsOf(el);
    if (cur.indexOf(tag) >= 0) return;
    cur.push(tag);
    setTags(el, cur);
  }
  /* Wire one scope form once (_scopeBound guard); sync initial state. */
  function bindForm(form) {
    if (!form || form._scopeBound) return;
    form._scopeBound = true;
    const toggle = form.querySelector('[data-scope-toggle]');
    const body = form.querySelector('[data-scope-body]');
    const openMsg = form.querySelector('[data-scope-open-msg]');
    const tags = form.querySelector('[data-scope-tags]');
    const hidden = form.querySelector('[data-scope-hidden]');
    const roleSel = form.querySelector('[data-token-role]');
    const writeWarn = form.querySelector('[data-token-write-warn]');
    const emptyErr = form.querySelector('[data-scope-empty-err]');
    /* Show/hide the scope body per the restrict toggle; clearing tags when off. */
    function syncScope() {
      const on = toggle && toggle.checked;
      if (body) body.hidden = !on;
      if (openMsg) openMsg.hidden = !!on;
      if (emptyErr) emptyErr.hidden = true;
      if (!on && tags) setTags(tags, []);
    }
    /* Show the write-role warning only for service-write. */
    function syncRole() {
      if (!writeWarn || !roleSel) return;
      writeWarn.hidden = roleSel.value !== 'service-write';
    }
    if (toggle) toggle.addEventListener('change', syncScope);
    if (roleSel) roleSel.addEventListener('change', syncRole);
    /* Wire each preset chip button in the form. */
    form.querySelectorAll('[data-scope-preset]').forEach(function (btn) {
      /* Preset chip: force restrict on, then add its key as a tag. */
      btn.addEventListener('click', function () {
        if (toggle && !toggle.checked) {
          toggle.checked = true;
          syncScope();
        }
        addTag(tags, btn.getAttribute('data-scope-preset'));
      });
    });
    /* Serialize tags into the hidden field; block restricted-but-empty submits. */
    form.addEventListener('submit', function (e) {
      if (hidden) {
        const list = (toggle && toggle.checked) ? tagsOf(tags) : ['*'];
        if (toggle && toggle.checked && list.length === 0) {
          e.preventDefault();
          if (emptyErr) emptyErr.hidden = false;
          return;
        }
        hidden.value = list.join('\n');
      }
    });
    syncScope();
    syncRole();
  }
  /* Bind every scope form under root. */
  function boot(root) {
    (root || document).querySelectorAll('form[data-scope-form]').forEach(bindForm);
  }
  onContent(boot);
})();

/* Unsaved-changes guard: warn before leaving a page with dirty forms.
   Hook: form[data-dirty-guard]. Baseline is snapshotted at bind time;
   HTMX swaps re-scan because swapped-in forms are new nodes. */
(function () {
  /* Capture a form's current values for later comparison. */
  function snapshot(form) {
    return new FormData(form);
  }
  /* Order-insensitive FormData equality (multi-values joined). */
  function same(a, b) {
    if (a.length !== b.length) return false;
    const ak = Array.from(a.keys()).sort().join('|');
    const bk = Array.from(b.keys()).sort().join('|');
    if (ak !== bk) return false;
    for (const k of ak.split('|')) {
      const av = a.getAll(k).join('\u0000');
      const bv = b.getAll(k).join('\u0000');
      if (av !== bv) return false;
    }
    return true;
  }
  /* Snapshot each guarded form once and flag it dirty on any input change. */
  function scan(root) {
    /* Snapshot and track one guarded form. */
    (root || document).querySelectorAll('form[data-dirty-guard]').forEach(function (f) {
      if (!f._clean) f._clean = snapshot(f);
      if (f._dirtyBound) return;
      f._dirtyBound = true;
      /* Recompute dirtiness against the baseline on every input. */
      f.addEventListener('input', function () { f._dirty = !same(f._clean, snapshot(f)); });
    });
  }
  onContent(scan);
  /* Return the first dirty guarded form, or null when everything is clean. */
  function findDirtyForm() {
    let dirty = null;
    /* Keep the first dirty form found. */
    document.querySelectorAll('form[data-dirty-guard]').forEach(function (f) {
      if (!dirty && f._dirty) dirty = f;
    });
    return dirty;
  }
  /* Block page unload while any guarded form is dirty (native prompt). */
  window.addEventListener('beforeunload', function (e) {
    if (findDirtyForm()) { e.preventDefault(); e.returnValue = ''; }
  });
  /* Intercept sidebar subnav links when a guarded form is dirty.
     Capture phase so the confirm runs before HTMX navigation starts. */
  document.addEventListener('click', function (e) {
    const link = e.target.closest && e.target.closest('a[data-nav-link]');
    if (!link) return;
    if (findDirtyForm() && !window.confirm('You have unsaved changes. Leave anyway?')) {
      e.preventDefault();
    }
  }, true);
})();

/* Dim search/filter forms immediately on submit (full-page GET).
   Capture phase; purely visual, never blocks the submit. */
document.addEventListener('submit', function (e) {
  const f = e.target && e.target.closest ? e.target.closest('form[method="get"]') : null;
  if (f) f.classList.add('submitting');
}, true);

/* Duplicate-submit guard for plain POST forms (dialogs and HTMX manage
   their own state). Bubble phase so canceled confirms skip untouched.
   Disabled controls are omitted from the POST, so the clicked submitter is
   copied into a hidden field first (OIDC/LDAP/HSM test vs save). */
document.addEventListener('submit', function (e) {
  const form = e.target;
  if (e.defaultPrevented || !form || form.tagName !== 'FORM') return;
  const method = (form.getAttribute('method') || '').toLowerCase();
  if (method !== 'post') return;
  if (form.closest('dialog')) return;
  const attrs = form.attributes;
  /* HTMX-managed forms opt out via any hx- attribute. */
  for (let i = 0; i < attrs.length; i += 1) {
    if (String(attrs[i].name).indexOf('hx-') === 0) return;
  }
  form.classList.add('submitting');
  const submitter = e.submitter;
  if (submitter && submitter.name) {
    const stamped = document.createElement('input');
    stamped.type = 'hidden';
    stamped.name = submitter.name;
    stamped.value = submitter.value;
    form.appendChild(stamped);
  }
  /* Disable every submit button, showing data-busy labels where set. */
  form.querySelectorAll('button[type="submit"]').forEach(function (btn) {
    if (!btn.disabled) {
      if (btn.dataset.busy) btn.textContent = btn.dataset.busy;
      btn.disabled = true;
    }
  });
});
