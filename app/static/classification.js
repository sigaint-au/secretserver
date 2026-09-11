/* Classification banner color picker (server settings + team override).
   Shared helper, loaded from base.html. applyPreset/syncColor/
   updatePreview stay global: the swatch delegator in dialogs.js and the
   Alpine @input hooks in the banner forms call them on window. The preview
   element is found via [data-classification-preview] so both banner forms
   (server "banner-preview", team "team-banner-preview") share this file.
   Re-runs after HTMX swaps. */
"use strict";

(function () {
  function previewEl() {
    return document.querySelector("[data-classification-preview]");
  }

  function val(id) {
    var el = document.getElementById(id);
    return el ? el.value : "";
  }

  function setVal(id, v) {
    var el = document.getElementById(id);
    if (el) el.value = v;
  }

  window.applyPreset = function (bg, fg) {
    setVal("classification_color", bg);
    setVal("classification_color_picker", bg);
    setVal("classification_fg", fg);
    setVal("classification_fg_picker", fg);
    window.updatePreview();
  };

  window.syncColor = function (id) {
    var v = val(id);
    if (/^#[0-9A-Fa-f]{6}$/.test(v)) {
      setVal(id + "_picker", v);
    }
  };

  window.updatePreview = function () {
    var el = previewEl();
    if (!el) return;
    var inp = document.querySelector("[name=classification_text]");
    el.textContent = (inp && inp.value) || "Preview";
    el.style.background = val("classification_color");
    el.style.color = val("classification_fg");
    var cb = document.getElementById("classification_enabled");
    if (cb) el.style.opacity = cb.checked ? "1" : "0.45";
  };

  function wire(scope) {
    var text =
      scope && scope.querySelector
        ? scope.querySelector("[name=classification_text]")
        : document.querySelector("[name=classification_text]");
    if (text && !text.__classificationWired) {
      text.__classificationWired = true;
      text.addEventListener("input", function () {
        window.updatePreview();
      });
    }
    window.updatePreview();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", function () {
      wire(document);
    });
  } else {
    wire(document);
  }
  document.addEventListener("htmx:after:swap", function (evt) {
    wire(evt.target && evt.target.querySelector ? evt.target : document);
  });
})();
