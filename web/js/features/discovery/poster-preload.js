import { createScope } from "../../core/lifecycle.js";

/** Preload a bounded set; deadline and navigation settle even stalled images. */
export function createPosterPreloader({ candidates, createImage = () => new Image() }) {
  const pending = new Set();
  async function preload(results, maxWaitMs = 3500, signal) {
    if (signal?.aborted || !results.length) return;
    const scope = createScope();
    pending.add(scope);
    if (signal) scope.listen(signal, "abort", () => scope.dispose(), { once: true });
    scope.timeout(() => scope.dispose(), maxWaitMs);
    let next = 0;
    const warmOne = result => new Promise(resolve => {
      const urls = candidates(result?.cover_url);
      if (!urls.length || !scope.active) return resolve();
      const image = createImage();
      let index = 0;
      let settled = false;
      let release;
      const finish = () => {
        if (settled) return;
        settled = true;
        image.onload = null;
        image.onerror = null;
        image.removeAttribute("src");
        release?.();
        resolve();
      };
      release = scope.add(finish);
      const load = () => {
        if (!scope.active || !urls[index]) return finish();
        image.src = urls[index];
      };
      image.onload = async () => {
        try { await image.decode(); } catch { /* A loaded image can already be cached. */ }
        finish();
      };
      image.onerror = () => { index += 1; load(); };
      load();
    });
    try {
      await Promise.all(Array.from({ length: Math.min(6, results.length) }, async () => {
        while (scope.active && next < results.length) await warmOne(results[next++]);
      }));
    } finally {
      scope.dispose();
      pending.delete(scope);
    }
  }
  return { preload, unmount() { for (const scope of pending) scope.dispose(); pending.clear(); } };
}
