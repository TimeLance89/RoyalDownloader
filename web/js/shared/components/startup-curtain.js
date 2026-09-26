import { createScope } from "../../core/lifecycle.js";

/** One boot animation; every exit releases its timers and listeners. */
export function createStartupCurtain(document) {
  const scope = createScope();
  const loader = document.getElementById("royal-loader");
  const window = document.defaultView;
  const startedAt = performance.now();
  const minimumRunTime = window.matchMedia("(prefers-reduced-motion: reduce)").matches ? 0 : 900;
  let finishing = false;
  const remove = () => { loader?.remove(); scope.dispose(); };
  function finish() {
    if (finishing || !scope.active || !loader) return;
    finishing = true;
    scope.timeout(() => {
      loader.classList.add("is-leaving");
      scope.listen(loader, "transitionend", remove, { once: true });
      scope.timeout(remove, 900);
    }, Math.max(0, minimumRunTime - (performance.now() - startedAt)));
  }
  if (loader) {
    scope.timeout(finish, 12000);
    scope.listen(window, "pagehide", remove, { once: true });
  } else scope.dispose();
  return { finish, dispose: remove };
}
