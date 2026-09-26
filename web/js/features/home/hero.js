import { createScope } from "../../core/lifecycle.js";

export function createHero(root, { homeHeroCandidates, coverUrl, onRender, onRendered = () => {}, openEntry, openLibrary }) {
  let scope, stopRotation;
  let heroIndex = 0;
  const find = id => root.querySelector(`#${CSS.escape(id)}`);
function stopHomeHeroRotation() {
  stopRotation?.(); stopRotation = null;
}

function scheduleHomeHeroRotation() {
  stopHomeHeroRotation();
  const hero = find("home-hero");
  if (
    !hero
    || !scope?.active
    || hero.classList.contains("home-layout-hidden")
    || document.body.classList.contains("mood-open")
    || homeHeroCandidates().length < 2
    || hero.matches(":hover")
    || hero.contains(document.activeElement)
    || document.hidden
    || window.matchMedia("(prefers-reduced-motion: reduce)").matches
  ) return;
  stopRotation = scope.interval(() => {
    showHomeHero(heroIndex + 1);
  }, 9000);
}
function renderHomeHero() {
  const hero = find("home-hero");
  if (!hero) return;
  const candidates = homeHeroCandidates();
  if (!candidates.length) {
    hero.classList.add("is-loading", "has-no-art");
    find("home-hero-open").disabled = true;
    return;
  }
  heroIndex = ((heroIndex % candidates.length) + candidates.length) % candidates.length;
  const candidate = candidates[heroIndex];
  const media = candidate.media;
  hero.classList.remove("is-loading");
  hero.classList.toggle("is-poster-art", candidate.artworkKind === "poster");
  hero.classList.toggle("has-no-art", candidate.artworkKind === "none");
  hero.setAttribute("aria-label", `${candidate.kind === "movie" ? "Film" : "Serie"}: ${media.title}`);
  find("home-hero-art").style.backgroundImage = candidate.artwork
    ? `url("${coverUrl(candidate.artwork).replace(/"/g, "%22")}")`
    : "";
  find("home-hero-kind").textContent =
    candidate.kind === "movie" ? "ROYAL FILM" : "ROYAL SERIE";
  find("home-hero-title").textContent = media.title || "Royal";
  find("home-hero-meta").textContent = [
    media.year || (media.first_air_date ? String(media.first_air_date).slice(0, 4) : ""),
    media.rating ? `★ ${media.rating}` : "",
    ...(media.genres || []).slice(0, 2),
    candidate.kind === "movie" ? "Film" : "Serie",
  ].filter(Boolean).join(" · ");
  find("home-hero-description").textContent =
    media.description
    || (candidate.kind === "movie"
      ? "Neu und beliebt bei deinen ausgewählten Filmquellen."
      : "Eine aktuell angesagte Serie aus deinen eingerichteten Quellen.");
  const open = find("home-hero-open");
  open.disabled = false;
  open.dataset.kind = candidate.kind;
  open.dataset.key = candidate.kind === "movie" ? media.slug : media.base_slug;
  find("home-hero-position").textContent =
    `${heroIndex + 1} / ${candidates.length}`;
  onRendered(candidate);
}
function showHomeHero(index, userInitiated = false) {
  const count = homeHeroCandidates().length;
  if (!count) return;
  heroIndex = ((index % count) + count) % count;
  const hero = find("home-hero");
  if (!userInitiated && hero) {
    hero.classList.add("is-changing");
    scope?.timeout(() => hero.classList.remove("is-changing"), 380);
  }
  onRender();
}
  return {
    mount() {
      if (scope) return;
      scope = createScope();
      const hero = find("home-hero");
      scope.listen(find("home-hero-open"), "click", event => {
        const { kind, key } = event.currentTarget.dataset;
        if (kind && key) openEntry(kind, key);
      });
      scope.listen(find("home-hero-list"), "click", openLibrary);
      for (const [id, direction] of [["home-hero-prev", -1], ["home-hero-next", 1]]) {
        scope.listen(find(id), "click", () => {
          showHomeHero(heroIndex + direction, true);
          scheduleHomeHeroRotation();
        });
      }
      scope.listen(hero, "pointerenter", stopHomeHeroRotation);
      scope.listen(hero, "pointerleave", scheduleHomeHeroRotation);
      scope.listen(hero, "focusin", stopHomeHeroRotation);
      scope.listen(hero, "focusout", () => scope.timeout(() => {
        if (!hero.contains(document.activeElement)) scheduleHomeHeroRotation();
      }, 0));
      scope.listen(document, "visibilitychange", scheduleHomeHeroRotation);
      scheduleHomeHeroRotation();
    },
    get index() { return heroIndex; },
    reset() { heroIndex = 0; },
    refresh: renderHomeHero,
    show: showHomeHero,
    schedule: scheduleHomeHeroRotation,
    stop: stopHomeHeroRotation,
    unmount() {
      stopHomeHeroRotation(); scope?.dispose(); scope = null;
      find("home-hero")?.classList.remove("is-changing");
    },
  };
}
