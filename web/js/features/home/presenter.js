export function createHomePresenter(root, {
  getData, rememberAllHomeRailScroll, localDateKey, loadDiscoveryProfile, favoriteDiscoveryGenre,
  applyHomeLayout, currentHomeLayout, renderHomeHero, homeDiscoveryLanes, homeRailDefinition,
  renderHomeRail, scheduleHomeHeroRotation, homeAllEntries, beforeShuffle, animateShuffle, resetHero,
}) {
  const data = { discoveryDay: "", discoveryShuffle: 0, rendered: false };
  const byId = id => root.querySelector(`#${id}`);
  function shuffleHomeDiscovery() {
    beforeShuffle();
    data.discoveryShuffle = Number(data.discoveryShuffle || 0) + 1;
    resetHero();
    renderHome();
    animateShuffle();
  }

  function renderHome({ force = false } = {}) {
    rememberAllHomeRailScroll();
    data.discoveryDay = localDateKey();
    const profile = loadDiscoveryProfile();
    const favoriteGenre = favoriteDiscoveryGenre(profile);
    const personalTitle = byId("home-movies-title");
    const genreTitle = byId("home-genre-title");
    const genreEyebrow = byId("home-genre-eyebrow");
    if (personalTitle) {
      personalTitle.textContent = profile.interactions >= 2 ? "Für dich ausgewählt" : "Heute für dich";
    }
    if (genreTitle) {
      genreTitle.textContent = favoriteGenre ? `Weil dir ${favoriteGenre} gefällt` : "Genres zum Entdecken";
    }
    if (genreEyebrow) {
      genreEyebrow.textContent = favoriteGenre ? "Aus deinen Klicks und Downloads" : "Zum Kennenlernen";
    }
    const programNote = byId("home-program-note");
    if (programNote) {
      programNote.textContent = favoriteGenre
        ? `Neue Blickwinkel rund um ${favoriteGenre} – ohne dieselben Titel in jeder Reihe.`
        : "Filme und Serien aus verschiedenen Richtungen – ohne dieselben Titel in jeder Reihe.";
    }
    applyHomeLayout();
    if (getData().refreshing && data.rendered && !force) return;
    if (currentHomeLayout().hero_visible) renderHomeHero();
    const lanes = homeDiscoveryLanes();
    const hidden = new Set(currentHomeLayout().hidden_rails);
    currentHomeLayout().rail_order.forEach((railId) => {
      if (hidden.has(railId)) return;
      const definition = homeRailDefinition(railId);
      if (!definition) return;
      renderHomeRail(definition.trackId, lanes[railId] || [], {
        ranked: Boolean(definition.ranked), layout: definition.layout || "rail",
        wallpaperOnly: Boolean(definition.wallpaperOnly),
      });
    });
    if (currentHomeLayout().hero_visible) scheduleHomeHeroRotation();
    if (!getData().loading && homeAllEntries().length) data.rendered = true;
  }
  return { get: () => data, render: renderHome, shuffle: shuffleHomeDiscovery, invalidate() { data.rendered = false; } };
}
