/* Secret create/edit page behaviors: kind switching with type
   suggestion, password generation, SSH derive/generate, KV rows,
   edit-mode toggle, downloads. Page-specific URLs ride on form
   data-attributes (data-derive-url, data-generate-url); CSRF comes
   from the meta tag. Swap-aware through onContent. */
"use strict";

/* Suggest a secret kind from pasted content (only until the user
   picks a kind explicitly). */
function corvusSuggestKind(value) {
  var v = value || "";
  if (/BEGIN CERTIFICATE/.test(v)) return "certificate";
  if (/BEGIN (?:OPENSSH |RSA |EC |DSA |ED25519 )?PRIVATE KEY/.test(v)) {
    return "ssh";
  }
  if (
    /^(postgresql|postgres|mysql|mongodb|redis|amqp|https?):\/\//i.test(
      v.trim()
    ) &&
    v.indexOf("\n") < 0
  ) {
    return "database";
  }
  var kv = 0;
  var lines = v
    .split(/\n/)
    .map(function (l) {
      return l.trim();
    })
    .filter(function (l) {
      return l && l.charAt(0) !== "#";
    });
  for (var i = 0; i < lines.length; i += 1) {
    if (/^[A-Za-z_][A-Za-z0-9_.-]*=/.test(lines[i])) kv += 1;
  }
  if (lines.length >= 2 && kv >= 2) return "kv";
  return "plain";
}

(function kindSwitch() {
  var KINDS = ["plain", "database", "certificate", "ssh", "kv"];

  function boot(scope) {
    var root = scope && scope.querySelectorAll ? scope : document;
    var sel = root.querySelector
      ? root.querySelector("#secret-kind")
      : null;
    if (!sel || sel.__corvusKind) return;
    sel.__corvusKind = true;

    function show(kind) {
      KINDS.forEach(function (k) {
        var panel = document.getElementById("fields-" + k);
        if (panel) panel.hidden = k !== kind;
      });
    }

    var touched = false;
    sel.addEventListener("change", function () {
      touched = true;
      show(sel.value);
    });
    show(sel.value);

    var plain = document.getElementById("adv-value");
    function suggest(fromEl) {
      if (touched || !fromEl) return;
      var next = corvusSuggestKind(fromEl.value);
      if (next && next !== sel.value) {
        sel.value = next;
        show(next);
      }
    }
    if (plain) {
      plain.addEventListener("input", function () {
        suggest(plain);
      });
      plain.addEventListener("paste", function () {
        window.setTimeout(function () {
          suggest(plain);
        }, 0);
      });
    }
  }

  if (typeof window.onContent === "function") window.onContent(boot);
  else boot(document);
})();

/* Random password generator for the plain value field. */
(function passwordGen() {
  function boot(scope) {
    var root = scope && scope.querySelectorAll ? scope : document;
    var btn = root.querySelector ? root.querySelector("#adv-gen") : null;
    if (!btn || btn.__corvusGen) return;
    btn.__corvusGen = true;
    btn.addEventListener("click", function () {
      var inp = document.getElementById("adv-value");
      if (!inp) return;
      var chars =
        "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789!@#$%^&*_-+=";
      var buf = new Uint8Array(32);
      window.crypto.getRandomValues(buf);
      var out = "";
      for (var i = 0; i < 32; i += 1) out += chars[buf[i] % chars.length];
      inp.type = "text";
      inp.value = out;
      inp.focus();
    });
  }
  if (typeof window.onContent === "function") window.onContent(boot);
  else boot(document);
})();

/* SSH public-key derive (debounced) and key generation (new + edit
   forms share one controller; elements are looked up per form). */
(function sshTools() {
  function csrfToken(form) {
    var meta = document.querySelector('meta[name="csrf-token"]');
    if (meta && meta.content) return meta.content;
    var hidden =
      form && form.querySelector
        ? form.querySelector("input[name=_csrf]")
        : null;
    return (hidden && hidden.value) || "";
  }

  function postForm(url, fields) {
    var body = new FormData();
    Object.keys(fields).forEach(function (k) {
      body.set(k, fields[k]);
    });
    return fetch(url, { method: "POST", body: body }).then(function (res) {
      return res.json();
    });
  }

  function wireDerive(form, area, pub, fpWrap, fpVal, errBox) {
    if (!area || !pub || area.__corvusDerive) return;
    area.__corvusDerive = true;
    var url = form.getAttribute("data-derive-url");
    if (!url) return;
    var timer = null;
    function showFp(fp) {
      if (fp && fpWrap && fpVal) {
        fpVal.textContent = fp;
        fpWrap.hidden = false;
      } else if (fpWrap) {
        fpWrap.hidden = true;
      }
    }
    function showErr(msg) {
      if (!errBox) return;
      errBox.textContent = msg || "";
      errBox.hidden = !msg;
    }
    function derive() {
      var v = area.value.trim();
      if (!v) {
        pub.value = "";
        showFp("");
        showErr("");
        return;
      }
      if (v.length < 80 || v.indexOf("PRIVATE KEY") < 0) return;
      postForm(url, { _csrf: csrfToken(form), ssh_key: v }).then(
        function (data) {
          if (data.success) {
            pub.value = data.public_key;
            showFp(data.fingerprint || "");
            showErr("");
          } else {
            showErr(data.error || "");
          }
        },
        function () {
          /* Network failure: leave existing values alone. */
        }
      );
    }
    function schedule() {
      window.clearTimeout(timer);
      timer = window.setTimeout(derive, 450);
    }
    area.addEventListener("input", schedule);
    area.addEventListener("paste", function () {
      window.setTimeout(schedule, 0);
    });
  }

  function boot(scope) {
    var root = scope && scope.querySelectorAll ? scope : document;
    /* New-secret form. */
    var created = root.querySelector
      ? root.querySelector("#advanced-secret-form")
      : null;
    if (created && !created.__corvusSsh) {
      created.__corvusSsh = true;
      wireDerive(
        created,
        created.querySelector("#ssh-key-area"),
        created.querySelector("#ssh-pub-area"),
        created.querySelector("#ssh-fp-new"),
        created.querySelector("#ssh-fp-new-val"),
        created.querySelector("#ssh-derive-err-new")
      );
      var genBtn = created.querySelector("#ssh-gen-btn");
      var kindSel = created.querySelector("#secret-kind");
      if (genBtn && !genBtn.__corvusSshGen) {
        genBtn.__corvusSshGen = true;
        genBtn.addEventListener("click", function () {
          var genUrl = created.getAttribute("data-generate-url");
          if (!genUrl) return;
          var typeSel = created.querySelector("#ssh-key-type");
          genBtn.disabled = true;
          genBtn.textContent = "Generating…";
          postForm(genUrl, {
            _csrf: csrfToken(created),
            key_type: typeSel ? typeSel.value : "ed25519",
          }).then(
            function (data) {
              if (data.success) {
                var area = created.querySelector("#ssh-key-area");
                var pub = created.querySelector("#ssh-pub-area");
                if (area) area.value = data.private_key;
                if (pub) pub.value = data.public_key;
                var fpVal = created.querySelector("#ssh-fp-new-val");
                var fpWrap = created.querySelector("#ssh-fp-new");
                if (fpVal && fpWrap) {
                  fpVal.textContent = data.fingerprint || "";
                  fpWrap.hidden = !data.fingerprint;
                }
                if (kindSel) {
                  kindSel.value = "ssh";
                  kindSel.dispatchEvent(new Event("change", { bubbles: true }));
                }
                if (area) area.focus();
              } else {
                var errBox = created.querySelector("#ssh-derive-err-new");
                if (errBox) {
                  errBox.textContent = data.error || "unknown error";
                  errBox.hidden = false;
                }
              }
              genBtn.disabled = false;
              genBtn.textContent = "Generate";
            },
            function () {
              var errBox = created.querySelector("#ssh-derive-err-new");
              if (errBox) {
                errBox.textContent = "Key generation request failed";
                errBox.hidden = false;
              }
              genBtn.disabled = false;
              genBtn.textContent = "Generate";
            }
          );
        });
      }
    }
    /* Edit form on the secret full view. */
    var edit = root.querySelector
      ? root.querySelector("#secret-edit-form")
      : null;
    if (edit && !edit.__corvusSsh) {
      edit.__corvusSsh = true;
      wireDerive(
        edit,
        edit.querySelector("#ssh-key"),
        edit.querySelector("#ssh-pub-edit"),
        edit.querySelector("#ssh-fp-edit"),
        edit.querySelector("#ssh-fp-edit-val"),
        edit.querySelector("#ssh-derive-err")
      );
    }
    /* The swapped root itself may be one of the forms. */
    if (
      root !== document &&
      root.matches &&
      (root.matches("#advanced-secret-form") ||
        root.matches("#secret-edit-form")) &&
      !root.__corvusSsh
    ) {
      boot(document);
    }
  }

  if (typeof window.onContent === "function") window.onContent(boot);
  else boot(document);
})();

/* Dynamic key/value rows (new-secret and edit forms). */
(function kvRows() {
  function ensureOne(container) {
    if (container && !container.querySelector(".kv-row")) addRow(container);
  }

  function addRow(container) {
    if (!container) return;
    var tpl = document.getElementById("kv-row-template");
    if (!tpl || !tpl.content) return;
    container.appendChild(tpl.content.cloneNode(true));
    var last = container.querySelector(
      '.kv-row:last-child input[name="kv_keys"]'
    );
    if (last) last.focus();
  }

  function boot(scope) {
    var root = scope && scope.querySelectorAll ? scope : document;
    Array.prototype.forEach.call(
      root.querySelectorAll("#kv-rows"),
      function (container) {
        if (container.__corvusKv) return;
        container.__corvusKv = true;
        var form = container.closest("form");
        var addBtn = form
          ? form.querySelector("#kv-add")
          : document.getElementById("kv-add");
        if (addBtn && !addBtn.__corvusKv) {
          addBtn.__corvusKv = true;
          addBtn.addEventListener("click", function (evt) {
            evt.preventDefault();
            addRow(container);
          });
        }
        container.addEventListener("click", function (evt) {
          var btn =
            evt.target && evt.target.closest
              ? evt.target.closest(".kv-remove")
              : null;
          if (!btn) return;
          evt.preventDefault();
          var row = btn.closest(".kv-row");
          if (row) row.remove();
          ensureOne(container);
        });
      }
    );
  }

  if (typeof window.onContent === "function") window.onContent(boot);
  else boot(document);
})();

/* View/edit mode toggle on the secret full view. */
(function editMode() {
  function boot() {
    var btn = document.getElementById("toggle-edit-mode");
    if (!btn || btn.__corvusEdit) return;
    btn.__corvusEdit = true;
    btn.addEventListener("click", function (evt) {
      evt.preventDefault();
      var view = document.getElementById("secret-view-panel");
      var form = document.getElementById("secret-edit-form");
      if (view && form) {
        view.hidden = true;
        form.hidden = false;
        var first = form.querySelector(
          "input:not([type=hidden]):not([readonly]), textarea, select"
        );
        if (first) first.focus();
        return;
      }
      var url = btn.getAttribute("data-secret-tab");
      if (url) window.location.assign(url);
    });
  }

  if (typeof window.onContent === "function") window.onContent(boot);
  else boot();
})();

/* File downloads for SSH key material (.dl-btn). Delegated. */
document.addEventListener("click", function (evt) {
  var btn =
    evt.target && evt.target.closest
      ? evt.target.closest(".dl-btn")
      : null;
  if (!btn) return;
  var el = document.getElementById(btn.getAttribute("data-download-target"));
  if (!el) return;
  var raw = el.id ? document.getElementById(el.id + "-raw") : null;
  var text = raw
    ? (raw.value || raw.textContent || "")
    : (el.textContent || el.value || "");
  var blob = new Blob([text], { type: "text/plain" });
  var link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = btn.getAttribute("data-download-filename") || "key";
  document.body.appendChild(link);
  link.click();
  window.setTimeout(function () {
    URL.revokeObjectURL(link.href);
    link.remove();
  }, 0);
});
