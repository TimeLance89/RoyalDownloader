import { api } from "../../core/api.js";
import { createScope } from "../../core/lifecycle.js";
import { appStore } from "../../core/store.js";
import { formatMovieTime } from "../media-details/movie-player-controls.js";

const route = "/api/media-center/continue-watching";
const ticksPerSecond = 10_000_000;

export function createContinueWatching(section, { openItem, updateNavigation, client = api, store = appStore }) {
  const document = section.ownerDocument;
  const track = section.querySelector(".home-track");
  const heading = section.querySelector("h2");
  let scope, request, snapshot = "";
  let cards = new Map();

  function create(tag, className, text) {
    const element = document.createElement(tag);
    element.className = className;
    if (text) element.textContent = text;
    return element;
  }

  function createCard(item) {
    const time = formatMovieTime(item.position_ticks / ticksPerSecond);
    const subtitle = item.kind === "episode"
      ? [item.season != null && item.episode != null ? `S${item.season} E${item.episode}` : "Serienfolge",
        item.episode_title !== item.title && item.episode_title].filter(Boolean).join(" · ")
      : item.year ? String(item.year) : "Film";
    const button = create("button", "continue-card");
    button.type = "button";
    button.dataset.continueItem = item.id;
    button.setAttribute("aria-label", `${item.title}${item.kind === "episode" ? `, ${subtitle}` : ""} bei ${time} weiterschauen`);

    const art = create("span", "continue-card-art");
    if (item.has_image) {
      const image = create("img", "continue-card-image");
      image.alt = "";
      image.loading = "lazy";
      image.decoding = "async";
      image.src = `${route}/${encodeURIComponent(item.id)}/image`;
      image.addEventListener("error", () => image.remove(), { once: true });
      art.append(image);
    }
    const resume = create("span", "continue-card-resume", `▶  ${time}`);
    resume.setAttribute("aria-hidden", "true");
    art.append(resume);
    if (item.duration_ticks > 0) {
      const line = create("span", "continue-card-progress");
      line.style.setProperty("--continue-played", `${Math.min(100, 100 * item.position_ticks / item.duration_ticks)}%`);
      line.setAttribute("aria-hidden", "true");
      art.append(line);
    }
    const title = create("span", "continue-card-title", item.title);
    title.dataset.i18nIgnore = "";
    const details = create("span", "continue-card-subtitle", subtitle);
    if (item.kind === "episode") details.dataset.i18nIgnore = "";
    button.append(art, title, details);
    return button;
  }

  function render(items, context = {}) {
    const signature = JSON.stringify([items, context]);
    if (snapshot === signature) return;
    snapshot = signature;
    const focused = track.contains(document.activeElement) ? document.activeElement.dataset.continueItem : null;
    cards = new Map(items.map(item => [item.id, { ...item, ...context }]));
    track.replaceChildren(...[...cards.values()].map(createCard));
    section.hidden = !cards.size;
    if (focused && cards.size) {
      const next = [...track.children].find(card => card.dataset.continueItem === focused);
      (next || heading).focus({ preventScroll: true });
    }
    updateNavigation(track);
  }

  async function refresh({ replace = false } = {}) {
    if (!scope?.active || document.hidden || store.get().user?.role !== "admin") return;
    if (request && !replace) return;
    request?.abort();
    const current = new AbortController();
    request = current;
    try {
      const data = await client.get(route, { signal: current.signal, timeoutMs: 7_000 });
      if (scope?.active && request === current) render(data?.items || [], {
        generation: data?.generation, profile_id: data?.profile_id,
      });
    } catch {
      // Keep the previous rail on transient Jellyfin failures.
    } finally {
      if (request === current) request = null;
    }
  }

  function reset() {
    request?.abort();
    request = null;
    render([]);
  }

  return {
    mount() {
      if (scope?.active) return;
      scope = createScope();
      scope.listen(track, "click", event => {
        if (event.defaultPrevented) return;
        const button = event.target.closest("[data-continue-item]");
        const item = cards.get(button?.dataset.continueItem);
        if (item) openItem(item, button);
      });
      scope.listen(document, "visibilitychange", refresh);
      scope.listen(document, "royal:playback-closed", () => { void refresh({ replace: true }); });
      scope.listen(document, "royal:media-center-changed", () => { reset(); void refresh(); });
      scope.add(store.subscribe((next, previous) => {
        if (next.user?.id === previous.user?.id && next.user?.role === previous.user?.role) return;
        reset();
        void refresh();
      }));
      scope.interval(refresh, 60_000);
      void refresh();
    },
    unmount() { scope?.dispose(); scope = null; reset(); },
  };
}
