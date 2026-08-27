// Startup curtain shared by the authenticated app, login, and setup flows.
(() => {
  const loader = document.getElementById("royal-loader");
  if (!loader) return;

  const startedAt = performance.now();
  const minimumRunTime = matchMedia("(prefers-reduced-motion: reduce)").matches ? 0 : 900;
  let finishing = false;

  function finish() {
    if (finishing) return;
    finishing = true;
    const remaining = Math.max(0, minimumRunTime - (performance.now() - startedAt));
    window.setTimeout(() => {
      loader.classList.add("is-leaving");
      loader.addEventListener("transitionend", () => loader.remove(), { once: true });
      window.setTimeout(() => loader.remove(), 900);
    }, remaining);
  }

  window.royalLoader = { finish };
  window.setTimeout(finish, 12000);
})();

