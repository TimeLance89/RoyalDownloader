import { api } from "../../core/api.js";

/** Progressive, searchable movie-world chooser. The server owns the catalogue. */
export function createMovieWorldExplorer(root, {
  client = api, onSelect, onComplete, getSelected,
}) {
  const document = root.ownerDocument;
  const byId = id => root.querySelector(`#${id}`);
  const select = byId("movie-filter-world");
  const picker = root.querySelector(".movie-world-picker");
  let mounted = false, explorer = null, toggle = null, completion = null;
  let search = null, grid = null, count = null, more = null, tabs = null;
  let worlds = [], groups = [], currentGroup = "all", limit = 24;
  const english = () => document.documentElement.lang.startsWith("en");
  const t = (de, en) => english() ? en : de;
  const label = item => item?.[english() ? "en" : "de"] || item?.de || "";
  const simplify = value => String(value || "").normalize("NFKD")
    .replace(/[\u0300-\u036f]/g, "").toLocaleLowerCase().trim();
  const make = (name, className, text) => {
    const node = document.createElement(name);
    if (className) node.className = className;
    if (text != null) node.textContent = text;
    return node;
  };

  function fromExistingSelect() {
    const backup = [];
    for (const opt of select.querySelectorAll("option[value]")) {
      if (!opt.value) continue;
      backup.push({ id: opt.value, group: opt.parentElement?.tagName === "OPTGROUP"
        ? (opt.closest("optgroup")?.label.includes("Disney") ? "animation" : "heroes")
        : "heroes", type: opt.value === "star-wars" ? "collections" : "discover",
      de: opt.textContent, en: opt.textContent });
    }
    return backup;
  }

  function populateSelect() {
    if (!worlds.length) return;
    const current = getSelected() || select.value;
    const all = make("option", "", t("Alle Filmwelten", "All movie worlds"));
    all.value = "";
    select.replaceChildren(all);
    for (const group of groups) {
      const optgroup = document.createElement("optgroup");
      optgroup.label = label(group);
      for (const world of worlds.filter(world => world.group === group.id)) {
        const option = make("option", "", label(world));
        option.value = world.id;
        optgroup.append(option);
      }
      if (optgroup.childElementCount) select.append(optgroup);
    }
    if (worlds.some(world => world.id === current)) select.value = current;
  }

  function renderTabs(scope) {
    tabs.replaceChildren();
    const available = [{ id: "all", de: "Alle", en: "All" }, ...groups];
    for (const group of available) {
      const button = make("button", currentGroup === group.id ? "is-active" : "",
        label(group));
      button.type = "button";
      button.dataset.group = group.id;
      button.setAttribute("aria-pressed", String(currentGroup === group.id));
      tabs.append(button);
    }
  }

  function render() {
    if (!mounted) return;
    const query = simplify(search.value);
    const visible = worlds.filter(world => (currentGroup === "all" || world.group === currentGroup)
      && (!query || simplify([world.de, world.en, groups.find(g => g.id === world.group)?.de].join(" ")).includes(query)));
    count.textContent = t(`${visible.length} Filmwelten & Studios gefunden`,
      `${visible.length} movie worlds & studios found`);
    const cards = visible.slice(0, limit).map(world => {
      const card = make("button", "movie-world-tile");
      card.type = "button";
      card.dataset.worldId = world.id;
      card.dataset.group = world.group;
      const isActive = getSelected() === world.id;
      if (isActive) card.classList.add("is-active");
      card.setAttribute("aria-pressed", String(isActive));
      const visual = make("span", "movie-world-tile-visual");
      visual.setAttribute("aria-hidden", "true");
      visual.textContent = ({ fantasy: "✦", action: "↗", scifi: "◈", horror: "✝",
        family: "✳", studios: "▣", heroes: "◆", animation: "★" })[world.group] || "✦";
      const text = make("span", "movie-world-tile-copy");
      text.append(make("span", "movie-world-tile-kind", world.type === "discover"
        ? t("STUDIO / UNIVERSUM", "STUDIO / UNIVERSE") : t("FILMREIHE", "FRANCHISE")));
      text.append(make("strong", "", label(world)));
      text.append(make("small", "", label(groups.find(group => group.id === world.group))));
      card.append(visual, text);
      return card;
    });
    grid.replaceChildren(...cards);
    more.hidden = visible.length <= limit;
    more.textContent = t(`Weitere anzeigen (${visible.length - limit})`,
      `Show more (${visible.length - limit})`);
    renderTabs();
  }

  function close(focusToggle = false) {
    if (!explorer) return;
    explorer.hidden = true;
    toggle.setAttribute("aria-expanded", "false");
    if (focusToggle) toggle.focus();
  }

  function setSelected(world) {
    if (worlds.some(item => item.id === world)) select.value = world;
    else if (!world) select.value = "";
    if (explorer && !explorer.hidden) render();
  }

  function setCollections(collections = []) {
    if (!completion) return;
    completion.replaceChildren();
    const unique = new Set();
    for (const entry of collections) {
      const id = Number(entry?.collection_id);
      if (!Number.isSafeInteger(id) || id <= 0 || unique.has(id)) continue;
      unique.add(id);
      const button = make("button", "movie-world-complete-action",
        t("Filmreihe vervollständigen", "Complete franchise")
        + (collections.length > 1 && entry.title ? ` · ${entry.title}` : ""));
      button.type = "button";
      button.dataset.collectionId = String(id);
      completion.append(button);
    }
    completion.hidden = unique.size === 0;
  }

  function refreshLanguage() {
    if (!mounted) return;
    toggle.textContent = t("Alle Filmwelten entdecken", "Explore all movie worlds");
    search.placeholder = t("Filmreihe oder Studio suchen …", "Search franchise or studio …");
    search.setAttribute("aria-label", search.placeholder);
    populateSelect();
    render();
  }

  function mount(scope) {
    if (mounted || !picker || !select || !document?.createElement
        || typeof select.querySelectorAll !== "function"
        || typeof picker.insertBefore !== "function") return;
    mounted = true;
    worlds = fromExistingSelect();
    groups = [
      { id: "animation", de: "Disney & Animation", en: "Disney & animation" },
      { id: "heroes", de: "Helden & Universen", en: "Heroes & universes" },
    ];
    toggle = make("button", "movie-world-explore-toggle", "Alle Filmwelten entdecken");
    toggle.type = "button";
    toggle.setAttribute("aria-controls", "movie-world-explorer");
    toggle.setAttribute("aria-expanded", "false");
    explorer = make("section", "movie-world-explorer");
    explorer.id = "movie-world-explorer";
    explorer.hidden = true;
    explorer.setAttribute("aria-label", "Filmwelten & Studios");
    const top = make("div", "movie-world-explorer-top");
    search = make("input", "movie-world-explorer-search");
    search.type = "search";
    search.autocomplete = "off";
    const closeButton = make("button", "movie-world-explorer-close", "✕");
    closeButton.type = "button";
    closeButton.setAttribute("aria-label", t("Entdecker schließen", "Close explorer"));
    top.append(search, closeButton);
    tabs = make("div", "movie-world-explorer-tabs");
    tabs.setAttribute("aria-label", t("Filmwelten nach Bereich filtern", "Filter movie worlds by category"));
    count = make("p", "movie-world-explorer-count");
    count.setAttribute("aria-live", "polite");
    grid = make("div", "movie-world-explorer-grid");
    more = make("button", "movie-world-explorer-more");
    more.type = "button";
    completion = make("div", "movie-world-completion");
    completion.hidden = true;
    completion.setAttribute("aria-live", "polite");
    explorer.append(top, tabs, count, grid, more);
    const desc = byId("movie-world-description");
    picker.insertBefore(toggle, desc || null);
    if (desc) desc.after(completion);
    else picker.append(completion);
    picker.append(explorer);
    refreshLanguage();
    scope.listen(toggle, "click", () => {
      const willOpen = explorer.hidden;
      explorer.hidden = !willOpen;
      toggle.setAttribute("aria-expanded", String(willOpen));
      if (willOpen) { render(); search.focus(); }
    });
    scope.listen(closeButton, "click", () => close(true));
    scope.listen(search, "input", () => { limit = 24; render(); });
    scope.listen(search, "keydown", event => {
      if (event.key === "Escape") { event.preventDefault(); close(true); }
    });
    scope.listen(tabs, "click", event => {
      const button = event.target.closest("button[data-group]");
      if (!button) return;
      currentGroup = button.dataset.group;
      limit = 24;
      render();
    });
    scope.listen(grid, "click", event => {
      const button = event.target.closest("button[data-world-id]");
      if (!button) return;
      const id = button.dataset.worldId;
      if (!worlds.some(world => world.id === id)) return;
      setSelected(id);
      close(true);
      onSelect(id);
    });
    scope.listen(more, "click", () => { limit += 24; render(); });
    scope.listen(completion, "click", event => {
      const button = event.target.closest("button[data-collection-id]");
      if (button) onComplete(Number(button.dataset.collectionId));
    });
    scope.add(() => {
      mounted = false;
      toggle?.remove();
      explorer?.remove();
      completion?.remove();
      toggle = explorer = completion = null;
    });
    void client.get("/api/movie-worlds/catalog", { signal: scope.signal, timeoutMs: 10_000 })
      .then(payload => {
        if (!mounted || !Array.isArray(payload?.worlds) || !Array.isArray(payload?.groups)) return;
        const ids = new Set();
        worlds = payload.worlds.filter(world => {
          if (typeof world?.id !== "string" || ids.has(world.id)) return false;
          ids.add(world.id);
          return true;
        });
        groups = payload.groups;
        refreshLanguage();
      })
      .catch(() => {
        // The original eight server-side options remain operable during API outages.
        if (mounted) render();
      });
  }

  return { mount, setSelected, setCollections, refreshLanguage, close };
}
