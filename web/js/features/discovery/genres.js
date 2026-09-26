import { api } from "../../core/api.js";
import { createScope } from "../../core/lifecycle.js";

export function createGenres(root, { getActive, select, onChange, client = api }) {
  const byId = id => root.querySelector(`#${id}`);
  let values = [], owner = createScope(), pending, resumeRead = false;
  function render() {
    const filter = byId("movie-filter-genre");
    filter.querySelectorAll('option:not([value="Alle Genres"])').forEach(option => option.remove());
    for (const genre of values) {
      const option = root.ownerDocument.createElement("option");
      option.value = genre; option.textContent = genre; filter.appendChild(option);
    }
    const active = getActive();
    select(active !== "Alle Genres" && !values.includes(active) ? "Alle Genres" : active);
    byId("genre-count").textContent = `${values.length} Genres verfügbar`;
    byId("genre-random").disabled = !values.length;
    onChange();
  }
  function refresh() {
    if (pending) return pending;
    const current = owner;
    const request = client.get("/api/genres", { signal: current.signal }).then(value => {
      if (!current.active) return;
      values = Array.isArray(value.genres) ? value.genres.slice() : []; render();
    }).catch(error => {
      if (!current.active) return;
      byId("genre-count").textContent = "Genres nicht verfügbar";
      throw error;
    }).finally(() => { if (pending === request) pending = null; });
    pending = request; return request;
  }
  return {
    get: () => values.slice(), refresh,
    mount() {
      if (owner.active) return;
      owner = createScope();
      if (resumeRead) void refresh().catch(() => {});
      resumeRead = false;
    },
    unmount() { resumeRead = Boolean(pending); owner.dispose(); pending = null; },
  };
}
