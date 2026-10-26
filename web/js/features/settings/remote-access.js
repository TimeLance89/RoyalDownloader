import { api } from "../../core/api.js";
import { createScope } from "../../core/lifecycle.js";

export function createRemoteAccess(root, { getUser, client = api }) {
  const find = name => root.querySelector(`[data-remote="${name}"]`);
  let scope, owner = "", busy = false, config = null;
  const valid = current => current?.active && Boolean(owner) && owner === String(getUser()?.id || "") && getUser()?.role === "admin";
  const body = () => ({ domain: find("domain").value.trim(), service: find("service").value.trim() });
  const options = current => ({ signal: current.signal, headers: { "X-Royal-Profile": owner } });
  function message(text = "", error = false) {
    find("status").textContent = text;
    find("status").classList.toggle("error", error);
  }
  function clearResult() {
    find("result").hidden = true; find("checks").replaceChildren();
    find("qr").removeAttribute("src"); find("url").removeAttribute("href"); find("url").textContent = "";
  }
  function clearSensitive() { find("token").value = ""; }
  function reset() {
    config = null; find("instructions").hidden = true; clearSensitive(); clearResult(); message();
  }
  function paint() {
    root.querySelectorAll("[data-remote-action]").forEach(button => { button.disabled = busy; });
    find("domain").disabled = busy; find("service").disabled = busy;
    find("token").disabled = busy;
  }
  async function act(name) {
    const current = scope;
    if (!valid(current) || busy) return;
    busy = true; paint(); message();
    try {
      if (name === "plan") {
        reset();
        const value = await client.post("/api/remote-access/plan", body(), options(current));
        if (!valid(current)) return;
        config = value;
        find("hostname").textContent = value.hostname; find("origin").textContent = value.origin;
        find("command").textContent = value.command; find("instructions").hidden = false;
        message("Domain vorbereitet. Weiter mit Schritt 2 im Cloudflare-Konto.");
      } else if (name === "bundle") {
        if (!config) return;
        try {
          const archive = await client.post("/api/remote-access/bundle", {
            ...body(), token: find("token").value.trim(),
          }, { ...options(current), responseType: "blob", timeoutMs: 20_000 });
          if (!valid(current)) return;
          const url = URL.createObjectURL(archive);
          const revoke = current.add(() => URL.revokeObjectURL(url));
          const link = document.createElement("a");
          link.href = url; link.download = "royal-remote-access.zip";
          document.body.append(link); link.click(); link.remove(); current.timeout(revoke, 30_000);
          message("ZIP heruntergeladen. README auf dem NAS befolgen, danach Schritt 4 prüfen. Die ZIP enthält deinen geheimen Tunnel-Token.");
        } finally {
          clearSensitive();
        }
      } else if (name === "verify") {
        clearResult(); message("HTTPS, Installation und Anmeldeschutz werden geprüft …");
        const value = await client.post("/api/remote-access/verify", body(), { ...options(current), timeoutMs: 26_000 });
        if (!valid(current)) return;
        if (!value.verified || value.url !== config?.url) throw new Error("Die eigene Installation wurde nicht bestätigt.");
        find("url").href = value.url; find("url").textContent = value.url;
        find("qr").src = value.qr_data_url;
        for (const check of value.checks) {
          const item = document.createElement("li"); item.textContent = check; find("checks").append(item);
        }
        find("result").hidden = false;
        message("Verbindung bestätigt. Melde dich unter deiner eigenen HTTPS-Adresse an.");
      } else if (name === "copy-origin" || name === "copy-command") {
        const text = name === "copy-origin" ? config.origin : config.command;
        let copied = false;
        try {
          if (navigator.clipboard?.writeText) { await navigator.clipboard.writeText(text); copied = true; }
        } catch { /* Local HTTP or denied permission: use the selected-text fallback. */ }
        if (!valid(current)) return;
        if (!copied) {
          const node = find(name === "copy-origin" ? "origin" : "command");
          const range = document.createRange(); range.selectNodeContents(node);
          const selection = window.getSelection(); selection.removeAllRanges(); selection.addRange(range);
          try { copied = document.execCommand("copy"); } catch { copied = false; }
        }
        message(copied ? "Kopiert." : "Text markiert. Mit Kopieren oder Strg+C übernehmen.");
      }
    } catch (error) {
      if (valid(current)) message(error.name === "AbortError" ? "Anfrage abgebrochen. Erneut versuchen." : error.message, true);
    } finally {
      if (scope === current) { busy = false; paint(); }
    }
  }
  return {
    mount() {
      if (scope) return;
      scope = createScope(); owner = String(getUser()?.id || "");
      find("form").hidden = getUser()?.role !== "admin";
      find("admin-note").hidden = getUser()?.role === "admin";
      scope.listen(root, "click", event => {
        const button = event.target.closest("[data-remote-action]");
        if (button && root.contains(button)) void act(button.dataset.remoteAction);
      });
      for (const name of ["domain", "service"]) scope.listen(find(name), "input", reset);
      const observer = new MutationObserver(() => { if (root.hidden) clearSensitive(); });
      observer.observe(root, { attributes: true, attributeFilter: ["hidden"] }); scope.observe(observer);
      reset(); paint();
    },
    refresh() {
      if (owner !== String(getUser()?.id || "") || (getUser()?.role !== "admin" && !find("form").hidden)) { this.unmount(); this.mount(); }
    },
    unmount() { scope?.dispose(); scope = null; owner = ""; busy = false; reset(); paint(); },
  };
}
