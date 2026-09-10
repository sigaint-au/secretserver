/* ESO manifest builder (project Integrations tab). Recomputes the
   Secret + SecretStore YAML from the token, base URL, namespace,
   prefix, and store kind on every input. Swap-aware through
   onContent; ids are page-unique so one controller suffices. */
"use strict";

(function eso() {
  function dnsName(raw) {
    var s = String(raw || "app")
      .toLowerCase()
      .replace(/[^a-z0-9-]+/g, "-")
      .replace(/^-+|-+$/g, "");
    if (!s) s = "app";
    if (!/^[a-z]/.test(s)) s = "x-" + s;
    return s.slice(0, 63).replace(/-+$/g, "") || "app";
  }

  function yamlQuote(raw) {
    return String(raw || "")
      .replace(/\\/g, "\\\\")
      .replace(/"/g, '\\"');
  }

  function build(root) {
    var projectId = root.getAttribute("data-project-id") || "";
    var yamlEl = document.getElementById("eso-yaml");
    var panel = document.getElementById("eso-yaml-panel");
    var hint = document.getElementById("eso-yaml-hint");
    var baseEl = document.getElementById("eso-base-url");
    var nsEl = document.getElementById("eso-namespace");
    var prefixEl = document.getElementById("eso-name-prefix");
    var tokenEl = document.getElementById("eso-token");
    var kindEl = document.getElementById("eso-store-kind");
    if (!yamlEl) return;

    var token = tokenEl && tokenEl.value ? tokenEl.value.trim() : "";
    var hasToken = !!token;
    if (panel) panel.hidden = !hasToken;
    if (hint) hint.hidden = hasToken;
    if (!hasToken) {
      yamlEl.value = "";
      return;
    }
    var base = baseEl && baseEl.value ? baseEl.value.replace(/\/+$/, "") : "";
    var ns = (nsEl && nsEl.value ? nsEl.value.trim() : "") || "default";
    var prefix = dnsName(prefixEl && prefixEl.value);
    var storeKind = (kindEl && kindEl.value) || "SecretStore";
    var tokenSecret = prefix + "-machine-token";
    var storeName = prefix + "-webhook";
    var url =
      base + "/eso/v1/projects/" + projectId + "/secrets/{{ .remoteRef.key }}";
    var lines = [
      "# Generated for project " + projectId,
      "# External Secrets Operator - webhook provider (Secret + SecretStore only)",
      "apiVersion: v1",
      "kind: Secret",
      "metadata:",
      "  name: " + tokenSecret,
      "  namespace: " + ns,
      "  labels:",
      "    external-secrets.io/type: webhook",
      "stringData:",
      '  token: "' + yamlQuote(token) + '"',
      "---",
      "apiVersion: external-secrets.io/v1",
      "kind: " + storeKind,
      "metadata:",
      "  name: " + storeName,
    ];
    if (storeKind === "SecretStore") lines.push("  namespace: " + ns);
    lines.push(
      "spec:",
      "  provider:",
      "    webhook:",
      '      url: "' + yamlQuote(url) + '"',
      "      result:",
      '        jsonPath: "$.value"',
      "      headers:",
      '        Authorization: "Bearer {{ .auth.token }}"',
      '        Content-Type: application/json',
      "      secrets:",
      "        - name: auth",
      "          secretRef:",
      "            name: " + tokenSecret
    );
    if (storeKind === "ClusterSecretStore") {
      lines.push("            namespace: " + ns);
    }
    yamlEl.value = lines.join("\n") + "\n";
  }

  function boot(scope) {
    var root =
      scope && scope.querySelectorAll
        ? scope.querySelector("#eso-integration") ||
          (scope.matches && scope.matches("#eso-integration") ? scope : null)
        : document.getElementById("eso-integration");
    if (!root || root.__corvusEso) return;
    root.__corvusEso = true;
    ["input", "change"].forEach(function (ev) {
      root.addEventListener(ev, function () {
        build(root);
      });
    });
    var toggle = document.getElementById("eso-token-toggle");
    var tokenEl = document.getElementById("eso-token");
    if (toggle && tokenEl && !toggle.__corvusEso) {
      toggle.__corvusEso = true;
      toggle.addEventListener("click", function () {
        var show = tokenEl.type === "password";
        tokenEl.type = show ? "text" : "password";
        toggle.textContent = show ? "Hide" : "Show";
      });
    }
    build(root);
  }

  if (typeof window.onContent === "function") window.onContent(boot);
  else boot(document);
})();
