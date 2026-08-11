/* Floating Cinema Dock for Home recommendation cards. */

const HOME_CARD_DOCK_INTENT_MS = 260;
const HOME_CARD_DOCK_FADE_MS = 170;
const HOME_CARD_DOCK_HANDOFF_MS = 110;
const HOME_CARD_DOCK_LEAVE_MS = 180;
const HOME_CARD_DOCK_MIN_VISIBLE_MS = 360;
const HOME_CARD_DOCK_SCROLL_COOLDOWN_MS = 420;
let homeCardDock = null;
let homeCardDockOwner = null;
let homeCardDockCandidate = null;
let homeCardDockShowTimer = null;
let homeCardDockHideTimer = null;
let homeCardDockTransition = 0;
let homeCardDockSuppressFocus = false;
let homeCardDockShownAt = 0;
let homeCardDockScrollBlockedUntil = 0;

function homeCardDockRuntime(value) {
  const text = String(value || "").trim();
  if (!text) return "";
  if (/^\d+(?:[.,]\d+)?$/.test(text)) return `${Math.round(Number(text.replace(",", ".")))} Min.`;
  return text.replace(/\bmin\b/i, "Min.");
}

function homeCardDockButton(className, icon, label, text = "") {
  const button = document.createElement("button");
  button.type = "button";
  button.className = `home-card-dock-action ${className}`;
  button.setAttribute("aria-label", label);
  button.title = label;
  const mark = document.createElement("span");
  mark.className = "home-card-dock-action-icon";
  mark.setAttribute("aria-hidden", "true");
  mark.textContent = icon;
  button.appendChild(mark);
  if (text) {
    const copy = document.createElement("span");
    copy.textContent = text;
    button.appendChild(copy);
  }
  return button;
}

function cancelHomeCardDockTimers() {
  if (homeCardDockShowTimer) clearTimeout(homeCardDockShowTimer);
  if (homeCardDockHideTimer) clearTimeout(homeCardDockHideTimer);
  homeCardDockShowTimer = null;
  homeCardDockHideTimer = null;
}

function homeCardDockPointerEntered() {
  cancelHomeCardDockTimers();
  homeCardDockCandidate = homeCardDockOwner;
}

function relayHomeCardDockWheel(event) {
  const owner = homeCardDockOwner;
  const homeScroller = owner?.closest(".tab-content") || document.getElementById("tab-home");
  if (!owner || !homeScroller) return;
  const lineFactor = event.deltaMode === WheelEvent.DOM_DELTA_LINE
    ? 24
    : event.deltaMode === WheelEvent.DOM_DELTA_PAGE ? homeScroller.clientHeight : 1;
  const track = owner.closest(".home-track");
  const horizontal = Boolean(track) && (event.shiftKey || Math.abs(event.deltaX) > Math.abs(event.deltaY));
  event.preventDefault();
  homeCardDockScrollBlockedUntil = Date.now() + HOME_CARD_DOCK_SCROLL_COOLDOWN_MS;
  hideHomeCardDock({ immediate: true });
  if (horizontal) {
    track.scrollLeft += (event.deltaX || event.deltaY) * lineFactor;
  } else {
    homeScroller.scrollTop += event.deltaY * lineFactor;
  }
}

function handleHomeCardDockScroll() {
  homeCardDockScrollBlockedUntil = Date.now() + HOME_CARD_DOCK_SCROLL_COOLDOWN_MS;
  homeCardDockCandidate = null;
  hideHomeCardDock({ immediate: true });
}

function positionHomeCardDock(card) {
  if (!homeCardDock || !card?.isConnected || homeCardDock.hidden) return;
  const rect = card.querySelector(".home-card-art")?.getBoundingClientRect() || card.getBoundingClientRect();
  const gutter = 12;
  const width = Math.min(460, Math.max(302, rect.width * 1.12));
  homeCardDock.style.width = `${width}px`;
  const estimatedHeight = homeCardDock.offsetHeight || width * 9 / 16 + 126;
  let left = rect.left + (rect.width - width) / 2;
  left = Math.max(gutter, Math.min(left, window.innerWidth - width - gutter));
  let top = rect.top - Math.min(14, (width - rect.width) * .16);
  if (top + estimatedHeight > window.innerHeight - gutter) {
    top = Math.max(gutter, window.innerHeight - estimatedHeight - gutter);
  }
  homeCardDock.style.left = `${Math.round(left)}px`;
  homeCardDock.style.top = `${Math.round(top)}px`;
}

function setHomeCardDockMessage(message) {
  const status = homeCardDock?.querySelector(".home-card-dock-status");
  if (status) status.textContent = message;
}

async function openHomeCardTrailer(entry, trigger) {
  const media = homeEntryMedia(entry);
  let trailerMedia = {
    ...media,
    ...(entry.kind === "movie" ? (state.fp.moviesCache[entry.item.slug] || {}) : {}),
  };
  let key = typeof fpTrailerYoutubeKey === "function" ? fpTrailerYoutubeKey(trailerMedia) : "";
  trigger.disabled = true;
  trigger.setAttribute("aria-busy", "true");
  setHomeCardDockMessage("Trailer wird vorbereitet …");
  try {
    if (!key && entry.kind === "movie") {
      const response = await api.tmdbMovie({
        slug: entry.item.slug,
        title: media.title || entry.item.title,
        year: media.year || entry.item.year || "",
        tmdb_id: media.tmdb_id || entry.item.tmdb_id || null,
      });
      if (response.movie) {
        trailerMedia = { ...media, ...response.movie };
        state.fp.metadataCache[entry.item.slug] = {
          ...(state.fp.metadataCache[entry.item.slug] || {}),
          ...response.movie,
        };
        key = typeof fpTrailerYoutubeKey === "function" ? fpTrailerYoutubeKey(trailerMedia) : "";
      }
    }
    if (!key || typeof openFpTrailerModal !== "function") {
      setHomeCardDockMessage("Für diesen Titel ist kein Trailer hinterlegt.");
      return;
    }
    const focusReturn = homeCardDockOwner?.querySelector(".home-card-primary-action") || trigger;
    hideHomeCardDock({ immediate: true });
    openFpTrailerModal(trailerMedia, focusReturn, entry.kind === "series" ? "series" : "film");
  } catch (error) {
    setHomeCardDockMessage("Trailer konnte nicht geladen werden.");
  } finally {
    trigger.disabled = false;
    trigger.removeAttribute("aria-busy");
  }
}

function renderHomeCardDock(card, entry) {
  const media = homeEntryMedia(entry);
  const kindLabel = entry.kind === "movie" ? "Film" : entry.kind === "anime" ? "Anime" : "Serie";
  const jellyfinStatus = mediaJellyfinStatus(media);
  const dock = homeCardDock;
  dock.replaceChildren();
  dock.setAttribute("aria-label", `${media.title}, Schnellaktionen`);

  const visual = document.createElement("div");
  visual.className = "home-card-dock-visual";
  const sourceImage = card.querySelector(".home-card-art img");
  if (sourceImage?.currentSrc || sourceImage?.src) {
    const image = document.createElement("img");
    image.src = sourceImage.currentSrc || sourceImage.src;
    image.alt = "";
    image.decoding = "async";
    visual.appendChild(image);
  } else {
    const fallback = document.createElement("span");
    fallback.className = "home-card-dock-fallback";
    fallback.textContent = mediaCardInitials(media.title);
    visual.appendChild(fallback);
  }
  const visualTop = document.createElement("div");
  visualTop.className = "home-card-dock-visual-top";
  const kind = document.createElement("span");
  kind.className = "home-card-dock-kind";
  kind.textContent = kindLabel.toLocaleUpperCase("de-DE");
  const jellyfin = document.createElement("span");
  setCatalogJellyfinBadge(jellyfin, jellyfinStatus);
  visualTop.append(kind, jellyfin);
  visual.appendChild(visualTop);

  const panel = document.createElement("div");
  panel.className = "home-card-dock-panel";
  const heading = document.createElement("div");
  heading.className = "home-card-dock-heading";
  const title = document.createElement("strong");
  title.translate = false;
  title.textContent = media.title;
  const metadata = document.createElement("span");
  metadata.className = "home-card-dock-meta";
  metadata.textContent = [
    media.rating ? `★ ${media.rating}` : "",
    media.year || "",
    homeCardDockRuntime(media.runtime),
    jellyfinStatus === "owned" ? "In Jellyfin" : "",
  ].filter(Boolean).join(" · ") || kindLabel;
  heading.append(title, metadata);

  const actions = document.createElement("div");
  actions.className = "home-card-dock-actions";
  const details = homeCardDockButton("is-primary", "→", `${media.title}: Details öffnen`, "Details");
  details.addEventListener("click", () => {
    hideHomeCardDock({ immediate: true });
    openHomeEntry(entry.kind, entry.kind === "movie" ? entry.item.slug
      : entry.kind === "anime" ? entry.item.id : entry.item.base_slug);
  });
  actions.appendChild(details);

  const trailerKey = typeof fpTrailerYoutubeKey === "function" ? fpTrailerYoutubeKey(media) : "";
  if (entry.kind === "movie" || trailerKey) {
    const trailer = homeCardDockButton("is-icon", "▷", `${media.title}: Trailer abspielen`);
    trailer.addEventListener("click", () => void openHomeCardTrailer(entry, trailer));
    actions.appendChild(trailer);
  }

  if (entry.kind === "movie" && jellyfinStatus !== "owned" && typeof toggleFpPick === "function") {
    const queued = state.queuedSlugs.has(entry.item.slug);
    const queue = homeCardDockButton(
      "is-icon is-queue" + (queued ? " is-active" : ""),
      queued ? "✓" : "+",
      queued ? `${media.title} aus der Queue entfernen` : `${media.title} zur Download-Queue hinzufügen`,
    );
    queue.setAttribute("aria-pressed", String(queued));
    queue.addEventListener("click", async () => {
      const wasQueued = state.queuedSlugs.has(entry.item.slug);
      queue.disabled = true;
      queue.setAttribute("aria-busy", "true");
      setHomeCardDockMessage(wasQueued ? "Wird aus der Queue entfernt …" : "Wird zur Queue hinzugefügt …");
      try {
        await toggleFpPick(entry.item.slug);
        const active = state.queuedSlugs.has(entry.item.slug);
        queue.classList.toggle("is-active", active);
        queue.querySelector(".home-card-dock-action-icon").textContent = active ? "✓" : "+";
        queue.setAttribute("aria-pressed", String(active));
        const label = active
          ? `${media.title} aus der Queue entfernen`
          : `${media.title} zur Download-Queue hinzufügen`;
        queue.setAttribute("aria-label", label);
        queue.title = label;
        setHomeCardDockMessage(active ? "Zur Download-Queue hinzugefügt." : "Aus der Queue entfernt.");
      } catch (error) {
        setHomeCardDockMessage("Queue konnte nicht geändert werden.");
      } finally {
        queue.disabled = false;
        queue.removeAttribute("aria-busy");
      }
    });
    actions.appendChild(queue);
  }

  const dismissSource = card.querySelector(".taste-v2-dismiss");
  if (dismissSource) {
    const dismiss = homeCardDockButton("is-icon is-dismiss", "⊘", `${media.title}: Nicht für mich`);
    dismiss.addEventListener("click", () => {
      hideHomeCardDock({ immediate: true });
      dismissSource.click();
    });
    actions.appendChild(dismiss);
  }

  const context = document.createElement("div");
  context.className = "home-card-dock-context";
  const genres = document.createElement("span");
  genres.textContent = (media.genres || []).slice(0, 3).join(" · ") || `${kindLabel} entdecken`;
  context.appendChild(genres);
  if (card.dataset.tasteReason) {
    const reason = document.createElement("span");
    reason.className = "home-card-dock-reason";
    reason.textContent = `Passt zu dir: ${card.dataset.tasteReason}`;
    context.appendChild(reason);
  }
  const status = document.createElement("span");
  status.className = "home-card-dock-status";
  status.setAttribute("aria-live", "polite");
  panel.append(heading, actions, context, status);
  dock.append(visual, panel);
}

function ensureHomeCardDock() {
  if (homeCardDock) return homeCardDock;
  homeCardDock = document.createElement("aside");
  homeCardDock.className = "home-card-dock";
  homeCardDock.hidden = true;
  homeCardDock.setAttribute("role", "group");
  homeCardDock.addEventListener("pointerenter", homeCardDockPointerEntered);
  homeCardDock.addEventListener("pointerleave", scheduleHomeCardDockHide);
  homeCardDock.addEventListener("focusin", homeCardDockPointerEntered);
  homeCardDock.addEventListener("focusout", scheduleHomeCardDockHide);
  homeCardDock.addEventListener("wheel", relayHomeCardDockWheel, { passive: false });
  homeCardDock.addEventListener("keydown", (event) => {
    if (event.key !== "Escape") return;
    event.preventDefault();
    const restore = homeCardDockOwner?.querySelector(".home-card-primary-action");
    homeCardDockSuppressFocus = true;
    hideHomeCardDock({ immediate: true });
    restore?.focus();
    requestAnimationFrame(() => { homeCardDockSuppressFocus = false; });
  });
  window.addEventListener("resize", () => positionHomeCardDock(homeCardDockOwner), { passive: true });
  window.addEventListener("scroll", handleHomeCardDockScroll, { passive: true, capture: true });
  document.body.appendChild(homeCardDock);
  return homeCardDock;
}

function activateHomeCardDock(card, entry, focusDock = false) {
  const dock = ensureHomeCardDock();
  const transition = ++homeCardDockTransition;
  const reveal = () => {
    if (
      transition !== homeCardDockTransition
      || homeCardDockCandidate !== card
      || !card.isConnected
    ) return;
    if (homeCardDockOwner) homeCardDockOwner.classList.remove("is-dock-open");
    homeCardDockOwner = card;
    card.classList.add("is-dock-open");
    renderHomeCardDock(card, entry);
    dock.hidden = false;
    dock.classList.remove("is-leaving");
    positionHomeCardDock(card);
    homeCardDockShownAt = Date.now();
    requestAnimationFrame(() => {
      if (transition !== homeCardDockTransition || dock.hidden || homeCardDockOwner !== card) return;
      dock.classList.add("is-visible");
      if (focusDock) dock.querySelector(".home-card-dock-action")?.focus();
    });
  };
  if (!dock.hidden && homeCardDockOwner && homeCardDockOwner !== card) {
    dock.classList.remove("is-visible");
    dock.classList.add("is-leaving");
    window.setTimeout(reveal, HOME_CARD_DOCK_FADE_MS);
  } else {
    reveal();
  }
}

function scheduleHomeCardDock(card, entry, { immediate = false, focusDock = false } = {}) {
  if (card.classList.contains("is-ranked")) return;
  if (!immediate && Date.now() < homeCardDockScrollBlockedUntil) return;
  cancelHomeCardDockTimers();
  homeCardDockCandidate = card;
  if (!homeCardDock?.hidden && homeCardDockOwner === card) return;
  const show = () => {
    homeCardDockShowTimer = null;
    if (homeCardDockCandidate !== card) return;
    if (!card.isConnected || !card.closest("#tab-home")) return;
    if (!immediate && !card.matches(":hover") && !card.contains(document.activeElement)) return;
    activateHomeCardDock(card, entry, focusDock);
  };
  if (immediate) show();
  else {
    const delay = homeCardDock && !homeCardDock.hidden
      ? HOME_CARD_DOCK_HANDOFF_MS
      : HOME_CARD_DOCK_INTENT_MS;
    homeCardDockShowTimer = window.setTimeout(show, delay);
  }
}

function scheduleHomeCardDockHide(event) {
  const related = event?.relatedTarget;
  if (
    related
    && (homeCardDock?.contains(related) || homeCardDockOwner?.contains(related))
  ) return;
  if (homeCardDockHideTimer) clearTimeout(homeCardDockHideTimer);
  const visibleFor = homeCardDockShownAt ? Date.now() - homeCardDockShownAt : HOME_CARD_DOCK_MIN_VISIBLE_MS;
  const delay = Math.max(HOME_CARD_DOCK_LEAVE_MS, HOME_CARD_DOCK_MIN_VISIBLE_MS - visibleFor);
  homeCardDockHideTimer = window.setTimeout(() => {
    homeCardDockHideTimer = null;
    if (
      homeCardDock?.matches(":hover")
      || homeCardDock?.contains(document.activeElement)
      || homeCardDockOwner?.matches(":hover")
      || homeCardDockOwner?.contains(document.activeElement)
    ) return;
    hideHomeCardDock();
  }, delay);
}

function hideHomeCardDock({ immediate = false } = {}) {
  cancelHomeCardDockTimers();
  homeCardDockCandidate = null;
  if (!homeCardDock || homeCardDock.hidden) return;
  const transition = ++homeCardDockTransition;
  homeCardDock.classList.remove("is-visible");
  homeCardDock.classList.add("is-leaving");
  homeCardDockOwner?.classList.remove("is-dock-open");
  homeCardDockOwner = null;
  const finish = () => {
    if (transition !== homeCardDockTransition || !homeCardDock) return;
    homeCardDock.hidden = true;
    homeCardDock.classList.remove("is-leaving");
    homeCardDock.replaceChildren();
    homeCardDockShownAt = 0;
  };
  if (immediate) finish();
  else window.setTimeout(finish, HOME_CARD_DOCK_FADE_MS);
}
