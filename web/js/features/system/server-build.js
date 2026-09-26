import { api } from "../../core/api.js";
import { createScope } from "../../core/lifecycle.js";

/** Public build contract detects in-app upgrades without mixing them with auth. */
export function createServerBuildMonitor({ client = api, document = globalThis.document, location = globalThis.location } = {}) {
  let scope, build = "", reloading = false;
  async function refresh(current = scope) {
    if (!current?.active || reloading) return;
    try {
      const data = await client.get("/api/v1/capabilities", {
        cache: "no-store", signal: current.signal, timeoutMs: 5_000,
      });
      if (!current.active) return;
      const nextBuild = String(data?.build || "").trim();
      if (!nextBuild) return;
      if (build && build !== nextBuild) {
        reloading = true;
        location.reload();
        return;
      }
      build = nextBuild;
    } catch { /* A failed probe is expected while the backend restarts. */ }
  }
  function schedule(current) {
    if (!current.active || reloading) return;
    current.timeout(async () => { await refresh(current); schedule(current); }, document.hidden ? 15_000 : 5_000);
  }
  return {
    mount() {
      if (scope) return;
      const current = scope = createScope();
      scope.listen(document, "visibilitychange", () => { if (!document.hidden) void refresh(current); });
      void refresh(current).finally(() => schedule(current));
    },
    refresh,
    unmount() { scope?.dispose(); scope = null; },
  };
}
