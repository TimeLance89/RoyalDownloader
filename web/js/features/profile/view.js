import { userInitials } from "./identity.js";
import { createScope } from "../../core/lifecycle.js";

export function createProfileView(root, { switchTab, userRoleLabel }) {
  let scope;
  const find = id => root.querySelector(`#${id}`);
  function tasteConfidenceCopy(value, interactions, label = "") {
    if (label === "very_high" || value >= .82) return "Profil sehr sicher";
    if (label === "high" || value >= .62) return "Profil gut etabliert";
    if (label === "medium" || value >= .35) return "Dein Geschmacksprofil nimmt Form an.";
    return interactions ? "Wir lernen dich noch kennen." : "Dein Profil wartet auf erste Signale.";
  }

  function renderProfileSummary(summary) {
    find("profile-title").textContent = summary.user?.display_name || summary.user?.username || "Royal";
    find("profile-avatar").textContent = userInitials(summary.user);
    const taste = summary.taste || {};
    const confidence = Math.max(0, Math.min(1, Number(taste.confidence || 0)));
    const confidenceCopy = tasteConfidenceCopy(confidence, Number(taste.interactions || 0), taste.confidence_label);
    find("profile-confidence").textContent = confidenceCopy;
    find("profile-hero-insight").textContent = confidenceCopy;
    const confidencePercent = Math.round(confidence * 100);
    find("profile-confidence-bar").style.width = `${Math.max(8, confidencePercent)}%`;
    root.querySelector(".profile-confidence")?.setAttribute("aria-valuenow", String(confidencePercent));
    find("profile-confidence-badge").textContent = confidenceCopy.replace("Profil ", "");
    const interactions = Number(taste.interactions || 0);
    const ratings = Number(taste.direct_ratings || 0);
    find("profile-interactions").textContent = String(interactions);
    find("profile-direct-ratings").textContent = String(ratings);
    find("profile-hero-interactions").textContent = String(interactions);
    find("profile-hero-ratings").textContent = String(ratings);
    find("profile-activity-ratings").textContent = String(ratings);
    find("profile-download-count").textContent = String(summary.downloads_requested || 0);
    find("profile-subscription-count").textContent = String(summary.subscriptions || 0);
    const jellyfin = summary.jellyfin || {};
    const jellyfinSelect = find("profile-jellyfin-user");
    const jellyfinStatus = find("profile-jellyfin-status");
    const jellyfinSave = find("profile-jellyfin-save");
    const users = Array.isArray(jellyfin.users) ? jellyfin.users : [];
    const options = [Object.assign(document.createElement("option"), { value: "", textContent: "Nicht verknüpft" })];
    users.forEach(user => {
      const option = document.createElement("option");
      option.value = user.id || "";
      option.textContent = user.name || user.id || "Jellyfin";
      options.push(option);
    });
    jellyfinSelect.replaceChildren(...options);
    if (jellyfin.user_id && !users.some(user => user.id === jellyfin.user_id)) {
      const stale = document.createElement("option");
      stale.value = jellyfin.user_id;
      stale.textContent = jellyfin.user_name || "Bisher verknüpfter Jellyfin-Benutzer";
      jellyfinSelect.append(stale);
    }
    jellyfinSelect.value = jellyfin.user_id || "";
    jellyfinSelect.disabled = !jellyfin.configured || jellyfin.available === false;
    jellyfinSave.disabled = jellyfinSelect.disabled;
    jellyfinStatus.textContent = jellyfin.error
      ? jellyfin.error
      : !jellyfin.configured
        ? "Jellyfin zuerst unter Einstellungen → Dienste einrichten."
        : jellyfin.available === false
          ? "Jellyfin-Benutzer sind gerade nicht erreichbar."
          : jellyfin.user_id
            ? `Verknüpft mit ${jellyfin.user_name || "Jellyfin"}.`
            : "Noch kein Jellyfin-Profil verknüpft.";
    const genres = Object.entries(taste.genres || {}).filter(([, score]) => Number(score) > 0).sort((a, b) => Number(b[1]) - Number(a[1])).slice(0, 5);
    const maximum = Math.max(1, ...genres.map(([, score]) => Math.abs(Number(score) || 0)));
    find("profile-top-genre-count").textContent = String(genres.length);
    find("profile-genres").replaceChildren(...(genres.length ? genres.map(([name, score]) => {
      const row = document.createElement("div");
      const label = document.createElement("span"); label.textContent = name;
      const meter = document.createElement("i");
      const fill = document.createElement("b");
      const relativePercent = Math.round(Math.abs(Number(score)) / maximum * 100);
      fill.style.width = `${Math.max(8, relativePercent)}%`;
      meter.setAttribute("role", "progressbar"); meter.setAttribute("aria-label", `${name}: ${relativePercent} Prozent relative Präferenzstärke`); meter.setAttribute("aria-valuemin", "0"); meter.setAttribute("aria-valuemax", "100"); meter.setAttribute("aria-valuenow", String(relativePercent));
      const value = document.createElement("strong"); value.textContent = `${relativePercent}%`;
      meter.append(fill); row.append(label, meter, value);
      return row;
    }) : [Object.assign(document.createElement("p"), { textContent: "Interessen ergänzen, damit deine Top Genres sichtbar werden." })]));
    const negative = Object.entries(taste.negative_genres || {}).filter(([, score]) => Number(score) < 0).sort((a, b) => Number(a[1]) - Number(b[1])).slice(0, 3).map(([name]) => name);
    const negativeTarget = find("profile-negative-genres");
    negativeTarget.hidden = !negative.length;
    negativeTarget.textContent = negative.length ? `Weniger deins: ${negative.join(", ")}` : "";
    find("profile-intelligence-copy").textContent = `Letzte Aktualisierung: ${taste.updated_at ? new Date(taste.updated_at * 1000).toLocaleDateString("de-DE") : "noch keine Signale"}.`;
    const recent = (summary.recent_downloads || []).slice(0, 10);
    find("profile-recent-downloads").replaceChildren(...(recent.length ? recent.map((download) => {
      const card = document.createElement("article"); card.className = "profile-download";
      if (download.cover_url) { const cover = document.createElement("img"); cover.src = download.cover_url; cover.alt = ""; cover.loading = "lazy"; card.append(cover); }
      else { const art = document.createElement("span"); art.className = "profile-download-art"; art.textContent = String(download.title || "D").trim().slice(0, 1).toUpperCase(); card.append(art); }
      const copy = document.createElement("div"); const title = document.createElement("strong"); title.textContent = download.title;
      const statusLabels = { requested: "Angefordert", queued: "Eingeplant", preparing: "Wird vorbereitet", waiting_provider: "Wartet auf Quelle", downloading: "Lädt", completed: "✓ Geladen", failed: "Fehlgeschlagen", cancelled: "Abgebrochen" };
      const meta = document.createElement("small"); const requested = download.requested_at ? new Date(download.requested_at * 1000).toLocaleDateString("de-DE") : "Angefordert"; meta.textContent = `${requested} · ${statusLabels[download.status] || download.status}`; copy.append(title, meta); card.append(copy); return card;
    }) : [createProfileEmptyState()]));
    const created = summary.user?.created_at ? new Date(summary.user.created_at * 1000).toLocaleDateString("de-DE", { month: "long", year: "numeric" }) : "";
    find("profile-member-since").textContent = created ? `Mitglied seit ${created}` : userRoleLabel(summary.user);
  }

  function createProfileEmptyState() {
    const empty = document.createElement("div"); empty.className = "profile-empty";
    const icon = document.createElement("i"); icon.textContent = "▱";
    const title = document.createElement("strong"); title.textContent = "Du hast noch keine Downloads angefordert.";
    const copy = document.createElement("small"); copy.textContent = "Entdecke Filme und Serien, die zu deinem Geschmack passen.";
    const button = document.createElement("button"); button.type = "button"; button.textContent = "Inhalte entdecken →"; scope.listen(button, "click", () => switchTab("home"));
    empty.append(icon, title, copy, button); return empty;
  }

  return {
    render(summary) { scope?.dispose(); scope = createScope(); renderProfileSummary(summary); },
    unmount() { scope?.dispose(); scope = null; },
  };
}
