// Independent of the application module graph: a failed import must not leave
// an endless curtain before even authentication can start.
(() => {
  "use strict";
  let done = false;
  const timer = setTimeout(fail, 20000);
  function finish() {
    done = true;
    clearTimeout(timer);
    window.removeEventListener("error", resourceError, true);
    document.removeEventListener("royal:boot-ready", finish);
    document.removeEventListener("royal:boot-error", fail);
  }
  function fail() {
    if (done) return;
    finish();
    const show = () => {
      document.getElementById("royal-loader")?.remove();
      const panel = document.createElement("section");
      panel.id = "royal-boot-error";
      panel.setAttribute("role", "alert");
      Object.assign(panel.style, { position: "fixed", inset: "0", zIndex: "2147483647",
        display: "flex", flexDirection: "column", justifyContent: "center", alignItems: "center",
        gap: "20px", padding: "28px", background: "#0b0d10", color: "#f3efe4",
        fontFamily: "system-ui, sans-serif", textAlign: "center" });
      const heading = document.createElement("h1");
      heading.textContent = "Royal konnte nicht vollständig geladen werden";
      const message = document.createElement("p");
      message.textContent = "Notwendige Dateien oder der Server sind gerade nicht erreichbar. Bitte versuche es erneut.";
      const retry = document.createElement("button");
      retry.type = "button"; retry.textContent = "Erneut laden";
      Object.assign(retry.style, { padding: "14px 24px", color: "#0b0d10", background: "#d8b766",
        border: "0", borderRadius: "8px", font: "inherit", cursor: "pointer" });
      retry.addEventListener("click", () => location.reload(), { once: true });
      panel.append(heading, message, retry); document.body.append(panel); retry.focus();
    };
    if (document.body) show();
    else document.addEventListener("DOMContentLoaded", show, { once: true });
  }
  function resourceError(event) {
    const target = event.target;
    if (target?.tagName === "SCRIPT" && target.type === "module") fail();
  }
  window.addEventListener("error", resourceError, true);
  document.addEventListener("royal:boot-ready", finish, { once: true });
  document.addEventListener("royal:boot-error", fail, { once: true });
})();
