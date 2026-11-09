import { isPlaybackUser, playbackIdentity, playbackDenied } from "../../shared/playback-access.js";
import { api } from "../../core/api.js";
import { createScope } from "../../core/lifecycle.js";
import { appStore } from "../../core/store.js";
import { formatMovieTime } from "../media-details/movie-player-controls.js";

const route = "/api/media-center/continue-watching";
const ticksPerSecond = 10_000_000;

export function createContinueWatching(section, { openItem, openDetails, updateNavigation, client = api, store = appStore }) {
  const document = section.ownerDocument;
  const track = section.querySelector(".home-track");
  const heading = section.querySelector("h2");
  let scope, request, snapshot = "";
  let cards = new Map();
  let menu, toast, cancelToast, undo, busy, revision = 0;

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
    const card = create("div", "continue-card-shell");
    const more = create("button", "continue-card-more", "⋯");
    more.type = "button";
    more.dataset.continueMore = item.id;
    more.setAttribute("aria-label", `Aktionen für ${item.title}`);
    more.setAttribute("aria-haspopup", "dialog");
    card.append(button, more);
    return card;
  }

  function render(items, context = {}) {
    const signature = JSON.stringify([items, context]);
    if (snapshot === signature) return;
    snapshot = signature;
    const focus = document.activeElement;
    const attribute = focus?.dataset.continueMore ? "data-continue-more" : "data-continue-item";
    const focused = track.contains(focus) ? focus.getAttribute(attribute) : null;
    cards = new Map(items.map(item => [item.id, { ...item, ...context }]));
    track.replaceChildren(...[...cards.values()].map(createCard));
    section.hidden = !cards.size;
    if (focused && cards.size) {
      const next = [...track.querySelectorAll(`[${attribute}]`)].find(button => button.getAttribute(attribute) === focused);
      (next || heading).focus({ preventScroll: true });
    }
    updateNavigation(track);
  }

  function showFeedback(message, nextUndo = null) {
    cancelToast?.();
    toast?.remove();
    undo = nextUndo;
    toast = create("div", "continue-feedback");
    const copy = create("span", "", message);
    copy.setAttribute("role", "status");
    toast.append(copy);
    if (undo) {
      const button = create("button", "", "Rückgängig");
      button.type = "button";
      button.addEventListener("click", () => void act("undo", undo.item, undo.token));
      toast.append(button);
    }
    section.after(toast);
    cancelToast = scope.timeout(() => { toast.remove(); toast = undo = null; }, undo ? 12_000 : 5_000);
  }

  async function act(action, item, token) {
    if (!scope?.active || busy) return;
    const owner = scope, atRevision = revision;
    const current = () => scope === owner && owner.active && revision === atRevision;
    busy = true;
    if (menu?.open) menu.close();
    try {
      const endpoint = `${route}/${encodeURIComponent(item.id)}`;
      if (action === "details") {
        const details = await client.get(`${endpoint}/details`, { signal: owner.signal });
        if (current()) openDetails(item, details);
        return;
      }
      const result = await client.post(`${endpoint}/action`, {
        action, profile_id: item.profile_id, generation: item.generation, undo_token: token,
      }, { signal: owner.signal });
      if (!current()) return;
      if (action !== "undo") {
        const { generation, profile_id } = item;
        render([...cards.values()].filter(card => card.id !== item.id), { generation, profile_id });
      }
      showFeedback(action === "hide" ? "Aus „Weiterschauen“ entfernt."
        : action === "watched" ? "Als gesehen markiert." : "Aktion rückgängig gemacht.",
      result.undo_token ? { item, token: result.undo_token } : null);
      if (action !== "undo") toast.querySelector("button")?.focus({ preventScroll: true });
      void refresh({ replace: true });
    } catch (error) {
      if (current()) {
        if (playbackDenied(error)) reset();
        showFeedback(error.status === 409 ? "Der Eintrag hat sich geändert. Die Liste wird aktualisiert."
          : "Die Aktion ist fehlgeschlagen. Bitte erneut versuchen.");
        if (error.status === 409) void refresh({ replace: true });
      }
    } finally {
      if (current()) busy = false;
    }
  }

  function showMenu(item, trigger) {
    menu?.remove();
    menu = create("dialog", "continue-menu");
    const title = create("h3", "", item.kind === "episode" && item.episode_title
      ? `${item.title} · ${item.episode_title}` : item.title);
    title.id = "continue-menu-title";
    title.dataset.i18nIgnore = "";
    menu.setAttribute("aria-labelledby", title.id);
    menu.append(title);
    for (const [action, label] of [
      ["details", "Details öffnen"], ["hide", "Aus „Weiterschauen“ entfernen"],
      ["watched", "Als gesehen markieren"], ["close", "Schließen"],
    ]) {
      const button = create("button", "", label);
      button.type = "button";
      button.addEventListener("click", () => {
        if (action === "close") menu.close();
        else void act(action, item);
      });
      menu.append(button);
    }
    const dialog = menu;
    dialog.addEventListener("close", () => { dialog.remove(); if (menu === dialog) menu = null; });
    section.after(dialog);
    trigger.focus({ preventScroll: true });
    dialog.showModal();
  }

  async function refresh({ replace = false } = {}) {
    if (!scope?.active || document.hidden || !isPlaybackUser(store.get().user)) return;
    if (request && !replace) return;
    request?.abort();
    const current = new AbortController();
    request = current;
    try {
      const data = await client.get(route, { signal: current.signal, timeoutMs: 7_000 });
      if (scope?.active && request === current) render(data?.items || [], {
        generation: data?.generation, profile_id: data?.profile_id,
      });
    } catch (error) {
      if (request === current && playbackDenied(error)) reset();
      // Keep the previous rail on transient Jellyfin failures.
    } finally {
      if (request === current) request = null;
    }
  }

  function reset() {
    revision++;
    busy = false;
    menu?.close();
    menu?.remove();
    menu = null;
    cancelToast?.();
    toast?.remove();
    toast = undo = null;
    request?.abort();
    request = null;
    render([]);
  }

  return {
    mount() {
      if (scope?.active) return;
      scope = createScope();
      scope.listen(track, "click", event => {
        if (event.defaultPrevented || busy) return;
        const more = event.target.closest("[data-continue-more]");
        if (more) {
          const item = cards.get(more.dataset.continueMore);
          if (item) showMenu(item, more);
          return;
        }
        const button = event.target.closest("[data-continue-item]");
        const item = cards.get(button?.dataset.continueItem);
        if (item) openItem(item, button);
      });
      scope.listen(document, "visibilitychange", refresh);
      scope.listen(document, "royal:playback-closed", () => { void refresh({ replace: true }); });
      scope.listen(document, "royal:media-center-changed", () => { reset(); void refresh(); });
      scope.add(store.subscribe((next, previous) => {
        if (playbackIdentity(next.user) === playbackIdentity(previous.user)) return;
        reset();
        void refresh();
      }));
      scope.interval(refresh, 60_000);
      void refresh();
    },
    unmount() { scope?.dispose(); scope = null; reset(); },
  };
}
