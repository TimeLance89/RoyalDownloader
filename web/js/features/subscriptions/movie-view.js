import { createScope } from "../../core/lifecycle.js";
import { createViewState } from "../../shared/components/view-state.js";
import { movieSubscriptionStatus } from "./movie-model.js";

export function createMovieSubscriptionView(root, { model, subscriptionMonogram, open: openEntry }) {
  const byId = id => root.querySelector(`#${id}`);
  let rows;
  function render(feedback = "") {
    rows?.dispose(); rows = createScope();
    const container = byId("movie-subscriptions-list");
    if (!container) return;
    const items = model.get().items;
    byId("movie-subscriptions-count").textContent =
      items.length
        ? `${items.length} ${items.length === 1 ? "Film wird" : "Filme werden"} überwacht`
        : "Noch keine Filme überwacht";
    byId("movie-subscriptions-check").disabled = !items.length || model.get().checkRunning;
    byId("movie-subscriptions-check").textContent = model.get().checkRunning ? "Prüfe …" : "↻ Qualitäten prüfen";
    container.innerHTML = "";
    if (model.get().error || feedback) container.append(createViewState({ state: "error", detail: model.get().error || feedback, className: "subscriptions-empty", retry: () => { if (rows?.active) void model.refresh(); } }));
    if (!model.get().loaded && !items.length) {
      if (!model.get().error) container.append(createViewState({ state: "loading", title: "Film-Abos werden geladen …", className: "subscriptions-empty" }));
      return;
    }
    if (!items.length) {
      const empty = document.createElement("div");
      empty.className = "subscriptions-empty";
      const mark = document.createElement("span");
      mark.className = "subscriptions-empty-mark";
      mark.textContent = "＋";
      mark.setAttribute("aria-hidden", "true");
      const copy = document.createElement("span");
      const title = document.createElement("strong");
      title.textContent = "Erstes Film-Abo anlegen";
      const hint = document.createElement("small");
      hint.textContent = "Film öffnen und „Film abonnieren“ wählen.";
      copy.append(title, hint);
      empty.append(mark, copy);
      container.appendChild(empty);
      return;
    }
    for (const entry of items) {
      const card = document.createElement("button");
      card.type = "button";
      card.className = "subscription-card"
        + (["failed", "upgrade"].includes(entry.status) ? " has-new" : "");
      card.dataset.status = entry.status || "current";
      card.setAttribute("aria-label", `${entry.title}: ${movieSubscriptionStatus(entry)}`);
      const monogram = document.createElement("span");
      monogram.className = "subscription-monogram";
      monogram.textContent = subscriptionMonogram(entry.title);
      const copy = document.createElement("span");
      copy.className = "subscription-text";
      const title = document.createElement("span");
      title.className = "subscription-name";
      title.textContent = entry.title;
      title.translate = false;
      const meta = document.createElement("span");
      meta.className = "subscription-meta";
      meta.textContent = movieSubscriptionStatus(entry);
      copy.append(title, meta);
      const signal = document.createElement("span");
      signal.className = "movie-subscription-signal";
      const signalDot = document.createElement("i");
      signalDot.setAttribute("aria-hidden", "true");
      const signalLabel = document.createElement("span");
      signalLabel.textContent = {
        queued: "In Queue",
        failed: "Fehler",
        upgrade: "Upgrade",
        watched_deleted: "Erledigt",
      }[entry.status] || "Aktuell";
      signal.append(signalDot, signalLabel);
      const open = document.createElement("span");
      open.className = "movie-subscription-open";
      open.textContent = "›";
      open.setAttribute("aria-hidden", "true");
      card.append(monogram, copy, signal, open);
      rows.listen(card, "click", () => openEntry(entry.source_slug, null, entry));
      container.appendChild(card);
    }
  }

  return { render, unmount() { rows?.dispose(); rows = null; } };
}
