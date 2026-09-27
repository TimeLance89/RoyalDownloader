import { api } from "../../core/api.js";
import { isAbortError } from "../../core/errors.js";
import { createDialog } from "../../shared/components/dialog.js";

export function createSubscriptionRules(root, { subscriptions, getSeries, findEntry, getCleanupDefault, isJellyfinConfigured, refreshQueue, WATCH_MODE_DEFAULT, WATCH_MODE_EXPLANATIONS, WATCH_CLEANUP_DEFAULT, WATCH_CLEANUP_LABELS, client = api }) {
  const byId = id => root.querySelector(`#${id}`);
  let context, scope, busy = false;
  const dialog = createDialog(root, {
    initialFocus: () => root.querySelector('input[name="watch-mode"]:checked'),
    onClose() { context = null; scope = null; busy = false; byId("watch-mode-status").textContent = ""; setBusy(false); },
  });
  function setBusy(value) {
    busy = value;
    byId("watch-mode-save").disabled = value;
    byId("watch-mode-remove").disabled = value;
  }
  function open(entry = null) {
    const series = getSeries();
    const stored = entry || findEntry(series);
    const baseSlug = stored?.base_slug || series?.base_slug;
    if (!baseSlug) return;
    const tracked = Boolean(stored || series?.watchlisted);
    const mode = stored?.download_mode || series?.watch_mode || WATCH_MODE_DEFAULT;
    const cleanupMode = tracked
      ? (stored?.cleanup_mode || series?.cleanup_mode || WATCH_CLEANUP_DEFAULT)
      : getCleanupDefault();
    dialog.close(false);
    const knownSlugs = series?.base_slug === baseSlug
      ? series.seasons.flatMap((season) => season.episodes.map((episode) => episode.slug))
      : (stored?.known_slugs || []);
    context = {
      baseSlug,
      title: stored?.title || series?.title || baseSlug,
      sampleUrl: stored?.sample_url || series?.url || "",
      knownSlugs,
      tmdbId: stored?.tmdb_id || series?.tmdb_id || null,
      aliases: stored?.aliases || series?.aliases || [],
      seasonEpisodeCounts: stored?.season_episode_counts || series?.season_episode_counts || {},
      seasonCountsCheckedAt: stored?.season_counts_checked_at || series?.season_counts_checked_at || 0,
      tracked,
    };

    byId("watch-mode-title").textContent = context.title;
    root.querySelectorAll('input[name="watch-mode"]').forEach((radio) => {
      radio.checked = radio.value === mode;
    });
    root.querySelectorAll('input[name="watch-cleanup"]').forEach((radio) => {
      radio.checked = radio.value === cleanupMode;
    });
    byId("watch-cleanup-description").textContent = tracked
      ? "Diese Löschregel gilt nur für diese Serie und nutzt den Gesehen-Status des gewählten Jellyfin-Profils."
      : `Vorausgewählt aus den Einstellungen: ${WATCH_CLEANUP_LABELS[cleanupMode] || WATCH_CLEANUP_LABELS[WATCH_CLEANUP_DEFAULT]}. Du kannst für diese Serie abweichen.`;
    byId("watch-mode-remove").classList.toggle("hidden", !tracked);
    byId("watch-mode-save").textContent = tracked ? "Regel übernehmen" : "Abo speichern";
    byId("watch-mode-status").textContent = "";
    const current = dialog.open();
    scope = current;
    for (const id of ["watch-mode-close", "watch-mode-cancel"]) current.listen(byId(id), "click", () => dialog.close());
    current.listen(byId("watch-mode-save"), "click", () => { void save(); });
    current.listen(byId("watch-mode-remove"), "click", () => { void remove(); });
    for (const radio of root.querySelectorAll('input[name="watch-mode"], input[name="watch-cleanup"]')) current.listen(radio, "change", updateRequirement);
    updateRequirement();
  }

  function updateRequirement() {
    const selected = root.querySelector('input[name="watch-mode"]:checked')?.value;
    const cleanupSelected = root.querySelector('input[name="watch-cleanup"]:checked')?.value
      || WATCH_CLEANUP_DEFAULT;
    const status = byId("watch-mode-status");
    const explanation = WATCH_MODE_EXPLANATIONS[selected] || WATCH_MODE_EXPLANATIONS[WATCH_MODE_DEFAULT];
    byId("watch-mode-outcome-title").textContent = explanation.title;
    byId("watch-mode-outcome-copy").textContent = explanation.copy;
    if (!isJellyfinConfigured() && (selected === "next_season" || cleanupSelected !== WATCH_CLEANUP_DEFAULT)) {
      const affected = selected === "next_season" && cleanupSelected !== WATCH_CLEANUP_DEFAULT
        ? "Download- und Löschregel warten"
        : (selected === "next_season" ? "Die Downloadregel wartet" : "Die Löschregel wartet");
      status.textContent = `Voraussetzung fehlt: Wähle unter Einstellungen → Jellyfin ein Wiedergabeprofil. ${affected}.`;
    } else if (status.textContent.startsWith("Diese Regel wartet")) {
      status.textContent = "";
    } else if (status.textContent.startsWith("Voraussetzung fehlt")) {
      status.textContent = "";
    }
  }


  async function mutate(path, body, removing = false) {
    const current = scope;
    if (!current?.active || busy) return;
    setBusy(true);
    const version = subscriptions.revision;
    try {
      const data = await client.post(path, body, { signal: current.signal });
      if (!current.active) return;
      if (version === subscriptions.revision) subscriptions.accept(data);
      else await subscriptions.refresh({ signal: current.signal, force: true });
      if (removing && current.active) await refreshQueue();
      if (current.active) dialog.close();
    } catch (error) {
      if (current.active && !isAbortError(error)) byId("watch-mode-status").textContent = error.message;
    } finally { if (current.active) setBusy(false); }
  }
  function save() {
    if (!context || busy) return;
    const selected = root.querySelector('input[name="watch-mode"]:checked')?.value;
    const cleanupSelected = root.querySelector('input[name="watch-cleanup"]:checked')?.value || WATCH_CLEANUP_DEFAULT;
    if (!selected) return;
    const body = { base_slug: context.baseSlug, download_mode: selected, cleanup_mode: cleanupSelected };
    if (context.tracked) return mutate("/api/watchlist/mode", body);
    return mutate("/api/watchlist/add", {
      ...body, title: context.title, sample_url: context.sampleUrl, known_slugs: context.knownSlugs,
      tmdb_id: context.tmdbId, aliases: context.aliases, season_episode_counts: context.seasonEpisodeCounts,
      season_counts_checked_at: context.seasonCountsCheckedAt,
    });
  }
  function remove() {
    if (!context?.tracked || busy || !window.confirm(`Abo für „${context.title}“ wirklich entfernen?`)) return;
    return mutate("/api/watchlist/remove", { base_slugs: [context.baseSlug] }, true);
  }
  return { open, close: dialog.close, unmount: dialog.unmount };
}
