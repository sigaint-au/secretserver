/* Scope-key tag input: <ss-taginput> around a text input plus an
   optional datalist. Value contract: .value reads/writes an array of
   tag strings, so form code needs no changes. Tags render as
   daisyUI badges; Enter/comma (or a datalist pick) adds one. */
"use strict";
(function tagInput() {
  function listed(root) {
    return Array.prototype.map
      .call(root.querySelectorAll(":scope > .badge[data-tag]"), function (chip) {
        return chip.getAttribute("data-tag");
      })
      .filter(Boolean);
  }

  function paint(root, tags) {
    var input = root.querySelector("input");
    Array.prototype.forEach.call(
      root.querySelectorAll(":scope > .badge[data-tag]"),
      function (chip) {
        chip.remove();
      }
    );
    (tags || []).forEach(function (raw) {
      var tag = String(raw).trim();
      if (!tag) return;
      var chip = document.createElement("span");
      chip.className = "badge badge-neutral";
      chip.setAttribute("data-tag", tag);
      chip.append(document.createTextNode(tag));
      var drop = document.createElement("button");
      drop.type = "button";
      drop.className = "tag-remove";
      drop.setAttribute("aria-label", "Remove " + tag);
      drop.textContent = "×";
      drop.addEventListener("click", function (evt) {
        evt.stopPropagation();
        chip.remove();
        root.dispatchEvent(new CustomEvent("input", { bubbles: true }));
        if (input && input.focus) input.focus();
      });
      chip.appendChild(drop);
      root.insertBefore(chip, input);
    });
    if (input) {
      input.value = "";
      var listId = input.getAttribute("list");
      if (listId) {
        var dl = document.getElementById(listId);
        if (dl) dl.replaceChildren();
      }
    }
  }

  function add(root, raw) {
    var tag = String(raw == null ? "" : raw)
      .trim()
      .replace(/,+$/, "");
    if (!tag || listed(root).indexOf(tag) >= 0) return;
    paint(root, listed(root).concat([tag]));
    root.dispatchEvent(new CustomEvent("input", { bubbles: true }));
  }

  function define() {
    class TagBox extends HTMLElement {
      connectedCallback() {
        if (this.__corvusTags) return;
        this.__corvusTags = true;
        var root = this;
        var input = root.querySelector("input");
        if (!input) return;
        input.addEventListener("keydown", function (evt) {
          if (evt.key === "Enter" || evt.key === ",") {
            evt.preventDefault();
            add(root, input.value);
          }
        });
        input.addEventListener("input", function () {
          var dl = input.list;
          var val = input.value;
          if (dl && val.length - (input.__corvusPrev || "").length > 1) {
            var hit = Array.prototype.find.call(dl.options || [], function (o) {
              return o.value === val;
            });
            if (hit) add(root, val);
          }
          input.__corvusPrev = val;
        });
        root.addEventListener("click", function (evt) {
          if (evt.target === root && input.focus) input.focus();
        });
      }
      get value() {
        return listed(this);
      }
      set value(next) {
        paint(this, Array.isArray(next) ? next : []);
      }
    }
    if (window.customElements && !window.customElements.get("ss-taginput")) {
      window.customElements.define("ss-taginput", TagBox);
    }
  }

  define();
})();
