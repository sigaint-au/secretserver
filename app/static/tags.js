/* Scope-key tag input: <ss-taginput> wrapping a text input + optional datalist.
   Replaces the former legacy tag input with the same value contract so
   forms.js needs no changes: `.value` reads/writes an array of tag strings.
   Tags render as daisyUI badges; Enter/comma (or a datalist pick) adds one. */
'use strict';
(function () {
  function currentTags(root) {
    return Array.prototype.map.call(
      root.querySelectorAll(':scope > .badge[data-tag]'),
      function (chip) { return chip.getAttribute('data-tag'); }
    ).filter(Boolean);
  }
  function render(root, tags) {
    const input = root.querySelector('input');
    root.querySelectorAll(':scope > .badge[data-tag]').forEach(function (c) { c.remove(); });
    (tags || []).forEach(function (raw) {
      const tag = String(raw).trim();
      if (!tag) return;
      const chip = document.createElement('span');
      chip.className = 'badge badge-neutral';
      chip.setAttribute('data-tag', tag);
      chip.append(document.createTextNode(tag));
      const rm = document.createElement('button');
      rm.type = 'button';
      rm.className = 'tag-remove';
      rm.setAttribute('aria-label', 'Remove ' + tag);
      rm.textContent = '×';
      rm.addEventListener('click', function (e) {
        e.stopPropagation();
        chip.remove();
        root.dispatchEvent(new CustomEvent('input', { bubbles: true }));
        if (input && input.focus) input.focus();
      });
      chip.appendChild(rm);
      root.insertBefore(chip, input);
    });
    if (input) {
      input.value = '';
      const list = input.getAttribute('list');
      if (list) {
        const dl = document.getElementById(list);
        if (dl) dl.replaceChildren();
      }
    }
  }
  function addTag(root, raw) {
    const tag = String(raw == null ? '' : raw).trim().replace(/,+$/, '');
    if (!tag || currentTags(root).indexOf(tag) >= 0) return;
    render(root, currentTags(root).concat([tag]));
    root.dispatchEvent(new CustomEvent('input', { bubbles: true }));
  }
  class SsTagInput extends HTMLElement {
    connectedCallback() {
      if (this._ssBound) return;
      this._ssBound = true;
      const root = this;
      const input = root.querySelector('input');
      if (!input) return;
      input.addEventListener('keydown', function (e) {
        if (e.key === 'Enter' || e.key === ',') {
          e.preventDefault();
          addTag(root, input.value);
        }
      });
      input.addEventListener('input', function () {
        const dl = input.list;
        const val = input.value;
        if (dl && val.length - (input._ssPrev || '').length > 1) {
          const opt = Array.prototype.find.call(dl.options || [], function (o) { return o.value === val; });
          if (opt) addTag(root, val);
        }
        input._ssPrev = val;
      });
      root.addEventListener('click', function (e) {
        if (e.target === root && input.focus) input.focus();
      });
    }
    get value() {
      return currentTags(this);
    }
    set value(v) {
      render(this, Array.isArray(v) ? v : []);
    }
  }
  if (window.customElements && !window.customElements.get('ss-taginput')) {
    window.customElements.define('ss-taginput', SsTagInput);
  }
})();
