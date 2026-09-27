import { createScope } from "../../core/lifecycle.js";

export function createHomeLifecycle({ root, shuffle, updateRailNavigation, refresh, dayChanged, stopRotation, dock, carousel, hero, recommendations, search, dailyTop, tasteRanking, layout, railRenderer }) {
  let scope;
  return {
    mount() {
      if (scope) return;
      scope = createScope();
      const refreshRailNavigation = () => root.querySelectorAll(".home-track").forEach(updateRailNavigation);
      scope.listen(root.querySelector("#home-discovery-shuffle"), "click", shuffle);
      scope.listen(root.ownerDocument.defaultView, "resize", refreshRailNavigation);
      refreshRailNavigation();
      dock.mount(); railRenderer.mount(); layout.mount(); tasteRanking.mount(); carousel.mount();
      hero.mount();
      recommendations.mount(); search.mount(); dailyTop.mount();
      // Local midnight has no server event; only the visible Home needs this check.
      scope.interval(() => { if (dayChanged()) refresh(); }, 5 * 60 * 1000);
    },
    refresh,
    unmount() {
      scope?.dispose();
      scope = null;
      railRenderer.unmount(); layout.unmount(); tasteRanking.unmount(); recommendations.unmount(); search.unmount(); dailyTop.unmount();
      carousel.unmount();
      hero.unmount();
      stopRotation();
      dock.unmount();
    },
  };
}
