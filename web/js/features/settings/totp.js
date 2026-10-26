import { api } from "../../core/api.js";
import { createScope } from "../../core/lifecycle.js";

export function createTotpSettings(root, { client = api, getUser, onUser }) {
  if (!root) return { mount() {}, unmount() {}, refresh: async () => {} };
  const find = name => root.querySelector('[data-totp="' + name + '"]');
  const action = name => root.querySelector('[data-totp-action="' + name + '"]');
  let scope = null, busy = false, enabled = false, owner = "", timer = null;
  const id = () => String(getUser()?.id || "");
  const valid = current => current?.active && owner && id() === owner;
  function message(text = "", error = false) {
    find("status").textContent = text; find("status").classList.toggle("error", error);
  }
  function clearSetup() {
    clearTimeout(timer); timer = null;
    find("setup").hidden = true; find("secret").value = ""; find("qr").removeAttribute("src");
  }
  function clearRecovery() { find("recovery-list").textContent = ""; find("recovery").hidden = true; }
  function paint(value) {
    enabled = Boolean(value.enabled);
    find("state").textContent = enabled ? `2FA aktiv · ${Number.isInteger(value.recovery_codes_remaining) ? value.recovery_codes_remaining + " Wiederherstellungscodes verfügbar." : "Status der Wiederherstellungscodes nicht verfügbar."}` : "2FA ist noch nicht aktiviert.";
    action("setup").hidden = enabled;
    action("disable").hidden = !enabled;
    action("recovery-codes").hidden = !enabled;
    action("setup").disabled = busy;
    if (find("badge")) {
      find("badge").textContent = enabled ? "Aktiv" : "Nicht aktiviert";
      find("badge").dataset.state = enabled ? "active" : "inactive";
      find("editor-title").textContent = enabled ? "Authenticator verwalten" : "Authenticator einrichten";
      root.querySelector('[data-totp-ui="manage"]').textContent = enabled ? "Verwalten" : "Einrichten";
      root.querySelector('[data-totp-ui="manage"]').disabled = false;
      find("disable-section").hidden = !enabled;
      find("code-field").hidden = !enabled && find("setup").hidden;
    }
  }
  async function refresh() {
    const current = scope;
    if (!valid(current)) return;
    try {
      const value = await client.get("/api/me/totp", { signal: current.signal, headers: { "X-Royal-Profile": owner } });
      if (typeof value?.enabled !== "boolean") throw new Error("Authenticator-Status konnte nicht bestätigt werden.");
      if (valid(current)) paint(value);
    } catch (error) { if (valid(current) && error.name !== "AbortError") message(error.message, true); }
  }
  async function perform(name) {
    if (name === "saved") { clearRecovery(); return; }
    const current = scope;
    if (!valid(current) || busy) return;
    const password = find("password").value, code = find("code").value.trim();
    if (!password) { message("Aktuelles Passwort zur Bestätigung eingeben.", true); find("password").focus(); return; }
    if (name !== "setup" && !code) { message("Authenticator-Code oder Wiederherstellungscode eingeben.", true); find("code").focus(); return; }
    busy = true; message();
    root.querySelectorAll("[data-totp-action]").forEach(button => { button.disabled = true; });
    try {
      const value = await client.post("/api/me/totp/" + name, { current_password: password, otp_code: code }, {
        signal: current.signal, headers: { "X-Royal-Profile": owner },
      });
      if (!valid(current)) return;
      find("code").value = "";
      if (name === "setup") {
        clearSetup(); clearRecovery();
        find("secret").value = value.secret;
        if (!String(value.qr_data_url || "").startsWith("data:image/svg+xml;base64,")) throw new Error("QR-Code konnte nicht geladen werden.");
        find("qr").src = value.qr_data_url;
        find("setup").hidden = false;
        if (find("code-field")) find("code-field").hidden = false;
        timer = setTimeout(() => { if (valid(current)) { clearSetup(); message("Einrichtung abgelaufen. Bitte neu beginnen."); } }, 600_000);
        find("code").focus();
        message("QR-Code scannen und den aktuellen sechsstelligen Code bestätigen.");
      } else {
        clearSetup(); clearRecovery(); find("password").value = "";
        if (find("editor")) find("editor").hidden = true;
        if (value.user) onUser(value.user);
        if (value.recovery_codes) {
          find("recovery-list").textContent = value.recovery_codes.join("\n"); find("recovery").hidden = false;
        }
        message(name === "disable" ? "2FA deaktiviert. Andere Sitzungen wurden beendet."
          : name === "confirm" ? "2FA aktiviert. Andere Sitzungen wurden beendet. Für eine neue Anmeldung den nächsten Code abwarten."
            : "Neue Wiederherstellungscodes erstellt. Die bisherigen Codes sind ungültig.");
        await refresh();
      }
    } catch (error) { if (valid(current) && error.name !== "AbortError") message(error.message, true); }
    finally {
      if (valid(current)) {
        busy = false; root.querySelectorAll("[data-totp-action]").forEach(button => { button.disabled = false; });
      }
    }
  }
  function mount() {
      if (scope) return;
      if (find("editor")) find("editor").hidden = true;
      scope = createScope(); owner = id(); busy = false; clearSetup(); clearRecovery(); message();
      find("state").textContent = "Status wird geladen …";
      if (find("badge")) {
        find("badge").textContent = "Wird geprüft";
        delete find("badge").dataset.state;
        root.querySelector('[data-totp-ui="manage"]').disabled = true;
        find("disable-section").open = false;
      }
      scope.listen(root, "click", event => {
        const button = event.target.closest("[data-totp-action]");
        if (button && root.contains(button)) void perform(button.dataset.totpAction);
        const ui = event.target.closest("[data-totp-ui]");
        if (!ui || !root.contains(ui)) return;
        if (ui.dataset.totpUi === "manage") { find("editor").hidden = false; find("password").focus(); }
        else if (ui.dataset.totpUi === "close") { unmount(); mount(); }
        else if (ui.dataset.totpUi === "download" && valid(scope) && find("recovery-list").textContent) {
          const url = URL.createObjectURL(new Blob([`Royal · Wiederherstellungscodes für ${getUser()?.username || "dein Konto"}\n\n${find("recovery-list").textContent}\n\nJeder Code gilt einmal. Getrennt vom Telefon aufbewahren.`], { type: "text/plain;charset=utf-8" }));
          const link = root.ownerDocument.createElement("a"); link.href = url; link.download = "royal-wiederherstellungscodes.txt";
          root.ownerDocument.body.append(link); link.click(); link.remove();
          scope.timeout(() => URL.revokeObjectURL(url), 1000); scope.add(() => URL.revokeObjectURL(url));
        }
      });
      void refresh();
    }
  function unmount() {
      scope?.dispose(); scope = null; owner = ""; busy = false;
      clearSetup(); clearRecovery(); find("password").value = ""; find("code").value = ""; message();
      if (find("editor")) find("editor").hidden = true;
    }
  return { refresh, mount, unmount, close() { if (scope) { unmount(); mount(); } } };
}
