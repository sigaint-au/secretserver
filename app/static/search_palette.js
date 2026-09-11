/* Command palette: Ctrl/Cmd+K and / open #search-palette; arrow keys
   move menu-active on #palette-results a. Hooks: #palette-btn,
   #search-palette, #palette-q, #palette-form, #palette-results. */
"use strict";

(function palette() {
  function dlg() {
    return document.getElementById("search-palette");
  }
  function input() {
    return document.getElementById("palette-q");
  }
  function links() {
    return document.querySelectorAll("#palette-results a");
  }

  function openPalette() {
    var node = dlg();
    if (!node) return;
    if (typeof window.openDialog === "function") window.openDialog(node);
    else if (node.showModal && !node.open) node.showModal();
    var field = input();
    if (field && field.value && window.htmx && typeof window.htmx.trigger === "function") {
      window.htmx.trigger(field, "search");
    }
  }

  function inField(el) {
    if (!el) return false;
    var tag = (el.tagName || "").toUpperCase();
    return tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || el.isContentEditable;
  }

  document.addEventListener("keydown", function (evt) {
    var node = dlg();
    if (!node) return;

    if ((evt.key === "k" || evt.key === "K") && (evt.metaKey || evt.ctrlKey) && !evt.altKey) {
      evt.preventDefault();
      if (node.open && typeof window.closeDialog === "function") window.closeDialog(node);
      else openPalette();
      return;
    }

    if (evt.key === "/" && !evt.metaKey && !evt.ctrlKey && !evt.altKey && !inField(evt.target)) {
      evt.preventDefault();
      openPalette();
      return;
    }

    if (!node.open) return;
    var items = links();
    if (!items.length) return;
    var i = -1;
    for (var n = 0; n < items.length; n++) {
      if (items[n].classList.contains("menu-active")) i = n;
    }
    if (evt.key === "ArrowDown") {
      evt.preventDefault();
      i = i < 0 ? 0 : Math.min(items.length - 1, i + 1);
    } else if (evt.key === "ArrowUp") {
      evt.preventDefault();
      i = i < 0 ? items.length - 1 : Math.max(0, i - 1);
    } else if (evt.key === "Enter" && i >= 0 && evt.target === input()) {
      evt.preventDefault();
      items[i].click();
      return;
    } else {
      return;
    }
    for (var k = 0; k < items.length; k++) items[k].classList.remove("menu-active");
    items[i].classList.add("menu-active");
    if (items[i].scrollIntoView) items[i].scrollIntoView({ block: "nearest" });
  });

  document.body.addEventListener("htmx:after:swap", function (evt) {
    var target = evt && evt.detail && evt.detail.ctx && evt.detail.ctx.target;
    if (target !== "#palette-results") return;
    var first = document.querySelector("#palette-results a");
    if (first) first.classList.add("menu-active");
  });
})();
