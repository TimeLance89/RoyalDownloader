const labels = {
  checking: "Prüft Stream-Sprachen", searching: "Sucht Serie, Episode und Quellen", waiting: "Wartet auf Prüfung",
  found: "Passende Sprache gefunden", checked: "Quellen geprüft",
  no_match: "Noch kein passender Treffer", retry: "Vorübergehend nicht erreichbar",
};

export function createEpisodeProbeProgress(status) {
  const document = status.ownerDocument;
  const panel = document?.querySelector("#series-probe-progress");
  let previous = "";
  const active = new Map();
  function draw({episodes, attempt, providers = [], queued = 0, state = "checking", remaining = 0}) {
    if (!panel) return;
    const key = JSON.stringify({episodes: episodes.map(e => e.slug), attempt, providers, queued, state, remaining});
    if (key === previous) return;
    previous = key;
    panel.hidden = false;
    panel.dataset.state = state;
    const node = (tag, text, className) => {
      const el = document.createElement(tag); el.textContent = text;
      if (className) el.className = className;
      return el;
    };
    const heading = state === "complete" ? "Prüfung abgeschlossen"
      : state === "incomplete" ? "Prüfung noch unvollständig"
      : state === "retry" ? "Prüfung wird automatisch wiederholt" : "Prüfe Sprachen und Verfügbarkeit";
    const header = node("div", "", "series-probe-heading");
    header.append(node("strong", heading), node("span", `Versuch ${attempt + 1} von 3`));
    const range = episodes.length > 4
      ? `${episodes.length} Folgen · S${episodes[0].season} E${episodes[0].episode} bis S${episodes.at(-1).season} E${episodes.at(-1).episode}`
      : episodes.map(ep => `S${ep.season} E${ep.episode}`).join(", ");
    const detail = node("p", `${range}${queued ? ` · ${queued} weitere Folgen warten` : ""}`);
    const list = node("ul", "", "series-probe-providers");
    list.tabIndex = 0; list.setAttribute("aria-label", "Anbieterprüfungen");
    const grouped = new Map();
    for (const row of providers) {
      const group = grouped.get(row.provider) || [];
      group.push(row); grouped.set(row.provider, group);
    }
    for (const [provider, rows] of grouped) {
      const current = rows.find(r => ["checking", "searching"].includes(r.status)) || rows.find(r => r.status === "waiting")
        || rows.find(r => r.status === "retry") || rows.find(r => r.status === "found") || rows.at(-1);
      const item = node("li", ""); item.dataset.state = current.status;
      item.append(node("strong", current.label || provider), node("span", labels[current.status] || "Quellen geprüft"));
      list.append(item);
    }
    const summary = node("p", state === "incomplete"
      ? `${remaining} Folge(n) konnten noch nicht sicher geprüft werden. Erneut auswählen startet eine neue Prüfung.`
      : state === "complete" ? "Bestätigte Folgen können ausgewählt werden." : "Bestätigte Treffer werden sofort freigegeben.", "series-probe-summary");
    const oldList = panel.querySelector(".series-probe-providers");
    const scrollTop = oldList?.scrollTop || 0;
    const focused = oldList && document.activeElement === oldList;
    panel.replaceChildren(header, detail, list, summary);
    list.scrollTop = scrollTop;
    if (focused) list.focus({preventScroll: true});
  }
  function render(data) {
    if (!data.batchKey) { draw(data); return; }
    if (["complete", "incomplete"].includes(data.state)) active.delete(data.batchKey);
    else active.set(data.batchKey, data);
    if (!active.size) { draw(data); return; }
    const batches = [...active.values()];
    const episodes = [...new Map(batches.flatMap(batch => batch.episodes).map(ep => [ep.slug, ep])).values()]
      .sort((a, b) => a.season - b.season || a.episode - b.episode);
    draw({...data, episodes, providers: batches.flatMap(batch => batch.providers || []),
      attempt: Math.max(...batches.map(batch => batch.attempt)),
      state: batches.some(batch => batch.state === "checking") ? "checking" : "retry"});
  }
  return {render, reveal() { if (panel && !panel.hidden) panel.scrollIntoView({block: "nearest"}); }, reset() { if (panel) panel.hidden = true; previous = ""; active.clear(); }};
}
