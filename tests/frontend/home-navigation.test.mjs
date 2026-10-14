import { test } from "node:test";
import assert from "node:assert/strict";
import { createHomePresenter } from "../../web/js/features/home/presenter.js";

function fixture(mobile) {
  let day = "2026-10-14", renders = 0;
  const layout = { hero_visible: false, hidden_rails: [], rail_order: ["top"] };
  const presenter = createHomePresenter({ querySelector: () => null,
    ownerDocument: { defaultView: { matchMedia: () => ({ matches: mobile }) } } }, {
    getData: () => ({ loading: false, refreshing: false }), localDateKey: () => day,
    rememberAllHomeRailScroll() {}, loadDiscoveryProfile: () => ({ interactions: 0 }), favoriteDiscoveryGenre: () => "",
    applyHomeLayout() {}, currentHomeLayout: () => layout, renderHomeHero() {}, homeDiscoveryLanes: () => ({ top: [{}] }),
    homeRailDefinition: () => ({ trackId: "top" }), renderHomeRail: () => renders++, scheduleHomeHeroRotation() {}, homeAllEntries: () => [{}],
  });
  return { presenter, renders: () => renders, tomorrow: () => { day = "2026-10-15"; } };
}

test("warm mobile navigation reuses cards while data, forced, day and invalidation updates still render", () => {
  const f = fixture(true);
  f.presenter.render({ navigation: true }); // Cold view must render.
  assert.equal(f.renders(), 1);
  f.presenter.render({ navigation: true });
  assert.equal(f.renders(), 1);
  f.presenter.render(); // Normal catalog/taste/layout notifications.
  assert.equal(f.renders(), 2);
  f.presenter.render({ navigation: true, force: true });
  assert.equal(f.renders(), 3);
  f.tomorrow(); f.presenter.render({ navigation: true });
  assert.equal(f.renders(), 4);
  f.presenter.invalidate(); f.presenter.render({ navigation: true });
  assert.equal(f.renders(), 5);
});

test("desktop navigation keeps its existing home render behavior", () => {
  const f = fixture(false);
  f.presenter.render(); f.presenter.render({ navigation: true });
  assert.equal(f.renders(), 2);
});
