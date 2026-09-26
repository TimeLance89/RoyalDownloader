import { jellyfinStatusText, setCatalogJellyfinBadge } from "./status-badge.js";

/** Shared Home/Search/Discovery card. Providers and user state are caller-owned. */
export function renderMediaCard({ media, kind, key, rank = 0, eager = false, variant = "", jellyfinState,
  coverCandidates, initials, setArtwork, setMeta, decorate, onOpen }) {
  const card = document.createElement("article");
  card.className = `home-card home-card-${kind}${rank ? " is-ranked" : ""}`;
  if (variant) card.classList.add(`is-${variant}`);
  card.dataset.kind = kind;
  card.dataset.key = key;
  const kindLabel = kind === "movie" ? "Film" : kind === "anime" ? "Anime" : "Serie";
  const primaryAction = document.createElement("button");
  primaryAction.type = "button";
  primaryAction.className = "home-card-primary-action";
  primaryAction.setAttribute("aria-label", `${rank ? `Platz ${rank}: ` : ""}${media.title}, ${kindLabel}, ${jellyfinStatusText(jellyfinState)}`);
  if (rank) {
    const number = document.createElement("span");
    number.className = "home-card-rank";
    number.textContent = String(rank);
    number.setAttribute("aria-hidden", "true");
    card.appendChild(number);
  }
  const art = document.createElement("span");
  art.className = "home-card-art";
  const fallback = document.createElement("span");
  fallback.className = "home-card-fallback";
  fallback.textContent = initials(media.title);
  art.appendChild(fallback);
  const artworkSources = rank
    ? [{ url: media.cover_url, posterFallback: false }, { url: media.backdrop_url, posterFallback: false }]
    : [{ url: media.backdrop_url, posterFallback: false }, { url: media.cover_url, posterFallback: true }];
  const seenArtworkCandidates = new Set();
  const artworkCandidates = artworkSources.flatMap(({ url, posterFallback }) =>
    coverCandidates(url).map((candidateUrl) => ({ url: candidateUrl, posterFallback })))
    .filter((candidate) => {
      if (!candidate.url || seenArtworkCandidates.has(candidate.url)) return false;
      seenArtworkCandidates.add(candidate.url);
      return true;
    });
  if (artworkCandidates.length) {
    const image = document.createElement("img");
    image.loading = "lazy";
    image.fetchPriority = eager ? "high" : "auto";
    image.decoding = "async";
    image.alt = "";
    setArtwork(image, artworkCandidates);
    art.appendChild(image);
  }
  const type = document.createElement("span");
  type.className = "home-card-type";
  type.textContent = kindLabel.toLocaleUpperCase("de-DE");
  const jellyfin = document.createElement("span");
  setCatalogJellyfinBadge(jellyfin, jellyfinState);
  const overlay = document.createElement("span");
  overlay.className = "home-card-overlay";
  const title = document.createElement("strong");
  title.translate = false;
  title.textContent = media.title;
  const meta = document.createElement("span");
  meta.className = "home-card-meta";
  setMeta(meta, media, kind);
  overlay.append(title, meta);
  art.append(type, jellyfin, overlay);
  card.append(art, primaryAction);
  if (!rank) decorate?.(card, primaryAction);
  primaryAction.addEventListener("click", onOpen);
  return card;
}


/** Selection variant: caller owns delegated actions and image-error handling. */
export function renderSelectableMediaCard(document, item, { selected = false } = {}) {
  const card = document.createElement("button");
  card.type = "button";
  card.className = "taste-onboarding-card";
  card.dataset.key = item.key;
  card.classList.toggle("is-selected", selected);
  card.setAttribute("aria-pressed", String(selected));
  card.setAttribute("aria-label", `${item.title} auswählen`);

  const artwork = document.createElement("span");
  artwork.className = "taste-onboarding-card-art";
  const image = document.createElement("img");
  image.src = item.artwork;
  image.alt = "";
  image.loading = "lazy";
  image.decoding = "async";
  const fallback = document.createElement("span");
  fallback.className = "taste-onboarding-card-fallback";
  fallback.textContent = item.title.slice(0, 1).toUpperCase();

  const check = document.createElement("i");
  check.className = "taste-onboarding-check";
  check.textContent = "✓";
  check.setAttribute("aria-hidden", "true");
  artwork.append(fallback, image, check);

  const copy = document.createElement("span");
  copy.className = "taste-onboarding-card-copy";
  const facts = document.createElement("span");
  facts.className = "taste-onboarding-card-facts";
  [
    item.rating ? `★ ${item.rating.toFixed(1)}` : "",
    item.year,
    item.kindLabel,
    item.runtime,
  ].filter(Boolean).forEach((value, index) => {
    const fact = document.createElement("small");
    fact.textContent = value;
    if (index === 0 && item.rating) fact.className = "is-rating";
    facts.append(fact);
  });
  const title = document.createElement("strong");
  title.textContent = item.title;
  const genres = document.createElement("span");
  genres.className = "taste-onboarding-card-genres";
  genres.textContent = item.genres.slice(0, 3).join(" · ") || "Weitere Details folgen";
  copy.append(facts, title, genres);
  if (item.description) {
    const description = document.createElement("span");
    description.className = "taste-onboarding-card-description";
    description.textContent = item.description;
    copy.append(description);
  }
  card.append(artwork, copy);
  return card;
}


export function setMediaCardMeta(meta, media, kind) {
  const document = meta.ownerDocument;
  meta.replaceChildren();
  if (media.year) {
    const year = document.createElement("span");
    year.className = "home-card-year";
    year.textContent = media.year;
    meta.appendChild(year);
  }
  if (media.rating) {
    const rating = document.createElement("span");
    rating.className = "home-card-rating";
    const star = document.createElement("span");
    star.className = "home-card-star";
    star.textContent = "★";
    star.setAttribute("aria-hidden", "true");
    rating.append(star, document.createTextNode(String(media.rating)));
    rating.setAttribute("aria-label", `Bewertung ${media.rating}`);
    meta.appendChild(rating);
  }
  if (!meta.childNodes.length) meta.textContent = kind === "movie" ? "Film" : "Serie";
}
