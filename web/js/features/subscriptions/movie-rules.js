import { api } from "../../core/api.js";
import { isAbortError } from "../../core/errors.js";
import { createDialog } from "../../shared/components/dialog.js";
import { movieSubscriptionFor } from "./movie-model.js";

export function createMovieSubscriptionRules(root, { model, isJellyfinConfigured, client = api }) {
  const byId = id => root.querySelector(`#${id}`);
  let context, scope, busy = false;
  function setBusy(value) {
    busy = value;
    byId("movie-subscription-save").disabled = value;
    byId("movie-subscription-remove").disabled = value;
  }
  const dialog = createDialog(root, {
    initialFocus: () => root.querySelector('input[name="movie-target-quality"]:checked'),
    onClose() { context = null; scope = null; setBusy(false); byId("movie-subscription-status").textContent = ""; },
  });
  function open(slug, movie, stored = null) {
    const entry = stored || movieSubscriptionFor(model.get().items, slug, movie);
    dialog.close(false);
    context = {
      key: entry?.key || "",
      sourceSlug: entry?.source_slug || slug,
      title: entry?.title || movie?.title || "Film",
      year: String(entry?.year || movie?.year || ""),
      tmdbId: entry?.tmdb_id || movie?.tmdb_id || null,
      coverUrl: entry?.cover_url || movie?.cover_url || "",
      tracked: Boolean(entry),
    };
    byId("movie-subscription-title").textContent = context.title;
    root.querySelectorAll('input[name="movie-target-quality"]').forEach((radio) => {
      radio.checked = radio.value === (entry?.target_quality || "best");
    });
    root.querySelectorAll('input[name="movie-cleanup"]').forEach((radio) => {
      radio.checked = radio.value === (entry?.cleanup_mode || "keep");
    });
    byId("movie-upgrade-enabled").checked = entry?.upgrade_enabled !== false;
    byId("movie-subscription-remove").classList.toggle("hidden", !entry);
    byId("movie-subscription-save").textContent =
      entry ? "Regel übernehmen" : "Abo speichern";
    byId("movie-subscription-status").textContent =
      !isJellyfinConfigured()
        && root.querySelector('input[name="movie-cleanup"]:checked')?.value === "watched"
        ? "Für die Gesehen-Löschung muss unter Einstellungen ein Jellyfin-Profil gewählt sein."
        : "";
    scope = dialog.open();
    for (const id of ["movie-subscription-close", "movie-subscription-cancel"]) scope.listen(byId(id), "click", () => dialog.close());
    scope.listen(byId("movie-subscription-save"), "click", () => { void save(); });
    scope.listen(byId("movie-subscription-remove"), "click", () => { if (context?.key) void mutate("/api/movie-subscriptions/remove", { keys: [context.key] }); });
    for (const radio of root.querySelectorAll('input[name="movie-cleanup"]')) scope.listen(radio, "change", () => {
      byId("movie-subscription-status").textContent = !isJellyfinConfigured() && radio.checked && radio.value === "watched"
        ? "Für die Gesehen-Löschung muss unter Einstellungen ein Jellyfin-Profil gewählt sein." : "";
    });
  }


  async function mutate(path, body) {
    const current = scope;
    if (!current?.active || busy) return;
    setBusy(true);
    const version = model.revision;
    try {
      const data = await client.post(path, body, { signal: current.signal });
      if (!current.active) return;
      if (model.revision === version) model.accept(data);
      else await model.refresh({ signal: current.signal, force: true });
      if (current.active) dialog.close();
    } catch (error) {
      if (current.active && !isAbortError(error)) byId("movie-subscription-status").textContent = error.message;
    } finally { if (current.active) setBusy(false); }
  }
  function save() {
    if (!context) return;
    return mutate("/api/movie-subscriptions", {
      source_slug: context.sourceSlug, title: context.title, year: context.year,
      tmdb_id: context.tmdbId, cover_url: context.coverUrl,
      target_quality: root.querySelector('input[name="movie-target-quality"]:checked')?.value || "best",
      cleanup_mode: root.querySelector('input[name="movie-cleanup"]:checked')?.value || "keep",
      upgrade_enabled: byId("movie-upgrade-enabled").checked,
    });
  }
  return { open, close: dialog.close, unmount: dialog.unmount };
}
