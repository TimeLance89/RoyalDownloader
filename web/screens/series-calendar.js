const SERIES_CALENDAR_CACHE_KEY = "royal.series-calendar.v1";
const SERIES_CALENDAR_CACHE_MAX_AGE = 7 * 24 * 60 * 60 * 1_000;

function calendarDate(value) {
  return new Date(`${value}T12:00:00`);
}

function calendarDateKey(date) {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function calendarTodayKey() {
  return calendarDateKey(new Date());
}

function calendarSnapshotEntry(item, date) {
  if (!item || typeof item !== "object") return null;
  const title = String(item.title || "").replace(/\s+/g, " ").trim().slice(0, 240);
  const slugMatch = String(item.base_slug || "").match(/^serienstream:([a-z0-9-]+)$/);
  if (!title || !slugMatch) return null;
  const season = Math.max(0, Math.min(Number(item.season) || 0, 100));
  const episode = Math.max(0, Math.min(Number(item.episode) || 0, 10_000));
  const languageId = Math.max(0, Math.min(Number(item.language_id) || 0, 10));
  const cover = String(item.cover_url || "").trim();
  const coverUrl = /^https:\/\/serienstream\.to\/media\/images\/channel\/desktop\/[A-Za-z0-9_-]+$/.test(cover)
    ? cover : "";
  const baseSlug = `serienstream:${slugMatch[1]}`;
  return {
    date,
    time: /^(?:[01]\d|2[0-3]):[0-5]\d$/.test(String(item.time || "")) ? item.time : "00:00",
    title,
    language: { 1: "Deutsch", 2: "Englisch", 3: "Deutsch (Untertitel)" }[languageId] || "Unbekannt",
    language_id: languageId,
    season,
    episode,
    released: Boolean(item.released),
    cover_url: coverUrl,
    base_slug: baseSlug,
    sample_slug: season > 0 && episode > 0
      ? `${baseSlug}-s${String(season).padStart(2, "0")}e${String(episode).padStart(2, "0")}`
      : baseSlug,
    subscribed: Boolean(item.subscribed)
      || (state.wl?.items || []).some((entry) => entry?.base_slug === baseSlug),
  };
}

function calendarNormalizeSnapshotPayload(payload) {
  if (!payload || typeof payload !== "object" || !Array.isArray(payload.days)) {
    throw new Error("Der Sendeplan enthält keine gültigen Daten.");
  }
  let total = 0;
  const days = payload.days.flatMap((day) => {
    const date = String(day?.date || "");
    if (!/^\d{4}-\d{2}-\d{2}$/.test(date) || !Array.isArray(day.entries)) return [];
    const entries = day.entries
      .map((item) => calendarSnapshotEntry(item, date)).filter(Boolean)
      .sort((left, right) => left.time.localeCompare(right.time) || left.title.localeCompare(right.title, "de"));
    total += entries.length;
    return [{ date, entries }];
  }).sort((left, right) => left.date.localeCompare(right.date));
  if (!days.length) throw new Error("Der Sendeplan enthält keine gültigen Tage.");
  return {
    days,
    total,
    provider: "serienstream",
    stale: Boolean(payload.stale),
    available_from: days[0].date,
    available_to: days.at(-1).date,
  };
}

function calendarStoreSnapshot(payload) {
  try {
    localStorage.setItem(SERIES_CALENDAR_CACHE_KEY, JSON.stringify({
      saved_at: Date.now(),
      payload: { ...payload, stale: false },
    }));
  } catch (_error) { /* Privatmodus oder volles Browser-Limit */ }
}

function calendarRestoreSnapshot() {
  try {
    const cached = JSON.parse(localStorage.getItem(SERIES_CALENDAR_CACHE_KEY) || "null");
    const savedAt = Number(cached?.saved_at || 0);
    if (!savedAt || Date.now() - savedAt > SERIES_CALENDAR_CACHE_MAX_AGE) return false;
    const payload = calendarNormalizeSnapshotPayload(cached.payload);
    state.calendar.days = payload.days;
    state.calendar.total = payload.total;
    state.calendar.loaded = false;
    state.calendar.cached = true;
    state.calendar.stale = true;
    state.calendar.updatedAt = savedAt;
    state.calendar.activeWeek = calendarInitialWeek();
    renderSeriesCalendar();
    return true;
  } catch (_error) {
    try { localStorage.removeItem(SERIES_CALENDAR_CACHE_KEY); } catch (_ignored) { /* nichts */ }
    return false;
  }
}

function calendarWeekKey(value) {
  const date = typeof value === "string" ? calendarDate(value) : new Date(value);
  const day = date.getDay() || 7;
  date.setDate(date.getDate() - day + 1);
  return calendarDateKey(date);
}

function calendarWeekDates(weekKey) {
  const monday = calendarDate(weekKey);
  return Array.from({ length: 7 }, (_, index) => {
    const date = new Date(monday);
    date.setDate(monday.getDate() + index);
    return calendarDateKey(date);
  });
}

function calendarAvailableWeeks() {
  return [...new Set(state.calendar.days.map((day) => calendarWeekKey(day.date)))].sort();
}

function calendarEntryMatches(entry) {
  const query = state.calendar.query.trim().toLocaleLowerCase("de");
  if (query && !entry.title.toLocaleLowerCase("de").includes(query)) return false;
  if (state.calendar.language !== "all"
      && String(entry.language_id) !== state.calendar.language) return false;
  if (state.calendar.subscribedOnly && !entry.subscribed) return false;
  return true;
}

function calendarEntriesForDate(date) {
  const day = state.calendar.days.find((candidate) => candidate.date === date);
  return (day?.entries || []).filter(calendarEntryMatches);
}

function calendarSetStatus(title, copy, { error = false, retry = false, loading = false } = {}) {
  const status = document.getElementById("calendar-status");
  status.classList.toggle("is-error", error);
  status.classList.toggle("is-loading", loading);
  status.hidden = false;
  status.innerHTML = `${loading
    ? '<span class="calendar-loader" aria-hidden="true"></span>'
    : `<span class="calendar-status-mark">${error ? "!" : "·"}</span>`}
    <strong>${escapeHtml(title)}</strong><small>${escapeHtml(copy)}</small>
    ${retry ? '<button type="button" data-calendar-retry>Erneut laden</button>' : ""}`;
  document.getElementById("calendar-days").hidden = true;
}

function calendarInitialWeek() {
  const weeks = calendarAvailableWeeks();
  const todayWeek = calendarWeekKey(calendarTodayKey());
  if (weeks.includes(todayWeek)) return todayWeek;
  return weeks.find((week) => week > todayWeek) || weeks.at(-1) || todayWeek;
}

function calendarProviderEntry(item, date) {
  if (!item || typeof item !== "object") return null;
  const title = String(item.title || "").replace(/\s+/g, " ").trim().slice(0, 240);
  const path = String(item.url || "").trim();
  const match = path.match(/^\/serie\/([a-z0-9-]+)\/staffel-(\d+)(?:\/episode-(\d+))?\/?$/);
  if (!title || !match) return null;
  const season = Math.max(0, Math.min(Number(item.season || match[2]) || 0, 100));
  const episode = Math.max(0, Math.min(Number(item.episode || match[3]) || 0, 10_000));
  const languageId = Number(item.language_id || 0);
  const coverPath = String(item.cover_url || "").trim();
  const coverUrl = /^\/media\/images\/channel\/desktop\/[A-Za-z0-9_-]+$/.test(coverPath)
    ? `https://serienstream.to${coverPath}` : "";
  const baseSlug = `serienstream:${match[1]}`;
  return {
    date,
    time: /^(?:[01]\d|2[0-3]):[0-5]\d$/.test(String(item.time || "")) ? item.time : "00:00",
    title,
    language: { 1: "Deutsch", 2: "Englisch", 3: "Deutsch (Untertitel)" }[languageId] || "Unbekannt",
    language_id: languageId,
    season,
    episode,
    released: Boolean(item.released),
    cover_url: coverUrl,
    base_slug: baseSlug,
    sample_slug: season > 0 && episode > 0
      ? `serienstream:${match[1]}-s${String(season).padStart(2, "0")}e${String(episode).padStart(2, "0")}`
      : baseSlug,
    subscribed: (state.wl?.items || []).some((entry) => entry?.base_slug === baseSlug),
  };
}

function calendarNormalizeProviderPayload(document) {
  if (!document || typeof document !== "object" || Array.isArray(document)) {
    throw new Error("SerienStream hat keinen gültigen Sendeplan geliefert.");
  }
  let total = 0;
  const days = Object.keys(document).sort().flatMap((date) => {
    if (!/^\d{4}-\d{2}-\d{2}$/.test(date) || !Array.isArray(document[date])) return [];
    const entries = document[date]
      .map((item) => calendarProviderEntry(item, date)).filter(Boolean)
      .sort((left, right) => left.time.localeCompare(right.time) || left.title.localeCompare(right.title, "de"));
    total += entries.length;
    return [{ date, entries }];
  });
  return {
    days, total, provider: "serienstream", direct: true,
    available_from: days[0]?.date || "", available_to: days.at(-1)?.date || "",
  };
}

async function calendarDirectProviderLoad() {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 10_000);
  try {
    const response = await fetch("https://serienstream.to/api/calendar", {
      signal: controller.signal, cache: "no-store", credentials: "omit", mode: "cors",
      headers: { Accept: "application/json" },
    });
    if (!response.ok) throw new Error(`SerienStream antwortet mit HTTP ${response.status}.`);
    return calendarNormalizeSnapshotPayload(calendarNormalizeProviderPayload(await response.json()));
  } catch (error) {
    if (error?.name === "AbortError") throw new Error("SerienStream antwortet nicht.");
    throw error;
  } finally {
    clearTimeout(timer);
  }
}

async function calendarLoadPayload() {
  try {
    const payload = await Promise.race([
      api.seriesCalendar(),
      new Promise((_, reject) => setTimeout(
        () => reject(new Error("Der lokale Kalenderdienst antwortet nicht.")), 4_000,
      )),
    ]);
    return calendarNormalizeSnapshotPayload(payload);
  } catch (backendError) {
    try {
      return await calendarDirectProviderLoad();
    } catch (providerError) {
      throw new Error(`${backendError.message} ${providerError.message}`.trim());
    }
  }
}

async function seriesCalendarLoad(force = false) {
  if (state.calendar.loading || (state.calendar.loaded && !force)) return;
  state.calendar.loading = true;
  state.calendar.error = "";
  const hadSnapshot = state.calendar.days.length > 0;
  document.getElementById("calendar-range").textContent = "Sendeplan wird aktualisiert …";
  if (!hadSnapshot) {
    calendarSetStatus("Sendeplan wird geladen", "Termine werden von SerienStream abgerufen.", { loading: true });
  }
  try {
    const payload = await calendarLoadPayload();
    state.calendar.days = payload.days;
    state.calendar.total = payload.total;
    state.calendar.disabledReason = "";
    state.calendar.stale = !!payload.stale;
    state.calendar.cached = false;
    state.calendar.updatedAt = Date.now();
    state.calendar.loaded = true;
    state.calendar.activeWeek = calendarInitialWeek();
    calendarStoreSnapshot(payload);
    renderSeriesCalendar();
  } catch (error) {
    state.calendar.error = error?.message || "Unbekannter Kalenderfehler";
    if (hadSnapshot) {
      state.calendar.stale = true;
      state.calendar.cached = true;
      state.calendar.loaded = false;
      renderSeriesCalendar();
      document.getElementById("calendar-range").textContent += " · Aktualisierung fehlgeschlagen";
    } else {
      document.getElementById("calendar-range").textContent = "Laden fehlgeschlagen";
      calendarSetStatus("Kalender nicht erreichbar", state.calendar.error, { error: true, retry: true });
    }
  } finally {
    state.calendar.loading = false;
  }
}

function calendarFormatRange(dates) {
  const formatter = new Intl.DateTimeFormat(i18n.locale(), { day: "2-digit", month: "short" });
  const year = calendarDate(dates[6]).getFullYear();
  return `${formatter.format(calendarDate(dates[0]))} – ${formatter.format(calendarDate(dates[6]))} ${year}`;
}

function renderCalendarHero() {
  const today = new Date();
  document.getElementById("calendar-hero-weekday").textContent = new Intl.DateTimeFormat(
    i18n.locale(), { weekday: "long" },
  ).format(today).toLocaleUpperCase("de");
  document.getElementById("calendar-hero-day").textContent = String(today.getDate()).padStart(2, "0");
  document.getElementById("calendar-hero-month").textContent = new Intl.DateTimeFormat(
    i18n.locale(), { month: "long", year: "numeric" },
  ).format(today);
  const entries = state.calendar.days.flatMap((day) => day.entries || []);
  document.getElementById("calendar-total").textContent = String(entries.length);
  document.getElementById("calendar-today-count").textContent = String(
    state.calendar.days.find((day) => day.date === calendarTodayKey())?.entries?.length || 0,
  );
  document.getElementById("calendar-upcoming-count").textContent = String(
    entries.filter((entry) => !entry.released).length,
  );
}

function renderCalendarWeekStrip(dates) {
  const today = calendarTodayKey();
  const weekday = new Intl.DateTimeFormat(i18n.locale(), { weekday: "short" });
  document.getElementById("calendar-week-strip").innerHTML = dates.map((date) => {
    const count = calendarEntriesForDate(date).length;
    const isToday = date === today;
    return `<button type="button" data-calendar-date="${date}" class="${isToday ? "is-today" : ""}">
      <span>${escapeHtml(weekday.format(calendarDate(date)))}</span>
      <strong>${calendarDate(date).getDate()}</strong>
      <small>${count} ${count === 1 ? "Folge" : "Folgen"}</small>
    </button>`;
  }).join("");
}

function calendarCard(entry, date, index, eager) {
  const code = `S${String(entry.season).padStart(2, "0")} · E${String(entry.episode).padStart(2, "0")}`;
  const stateLabel = entry.released ? "Verfügbar" : "Angekündigt";
  return `<button class="calendar-entry ${entry.released ? "is-released" : "is-upcoming"}" type="button"
      data-calendar-entry="${date}:${index}" aria-label="${escapeHtml(entry.title)}, ${code} öffnen">
    <span class="calendar-entry-art">
      ${entry.cover_url ? `<img src="${escapeHtml(entry.cover_url)}" alt="" loading="${eager ? "eager" : "lazy"}"
        decoding="async" referrerpolicy="no-referrer" ${eager ? 'fetchpriority="high"' : ""}>` : ""}
      <i aria-hidden="true">${escapeHtml(entry.title.slice(0, 2).toLocaleUpperCase("de"))}</i>
    </span>
    <span class="calendar-entry-copy">
      <strong translate="no">${escapeHtml(entry.title)}</strong>
      <span><b>${code}</b><i>${escapeHtml(entry.language)}</i>${entry.time !== "00:00" ? `<i>${escapeHtml(entry.time)} Uhr</i>` : ""}${entry.subscribed ? "<i>★ Meine Serie</i>" : ""}</span>
    </span>
    <span class="calendar-entry-state"><i></i>${stateLabel}</span>
    <span class="calendar-entry-open" aria-hidden="true">→</span>
  </button>`;
}

function renderCalendarDays(dates) {
  const today = calendarTodayKey();
  const weekday = new Intl.DateTimeFormat(i18n.locale(), { weekday: "long" });
  const month = new Intl.DateTimeFormat(i18n.locale(), { day: "2-digit", month: "long" });
  let imageBudget = 10;
  let visible = 0;
  const html = dates.map((date) => {
    const entries = calendarEntriesForDate(date);
    visible += entries.length;
    const cards = entries.map((entry, index) => {
      const eager = imageBudget-- > 0;
      return calendarCard(entry, date, index, eager);
    }).join("");
    return `<section class="calendar-day ${date === today ? "is-today" : ""}" id="calendar-day-${date}">
      <header>
        <span class="calendar-day-date"><b>${calendarDate(date).getDate()}</b><span>
          <strong>${date === today ? "Heute" : escapeHtml(weekday.format(calendarDate(date)))}</strong>
          <small>${escapeHtml(month.format(calendarDate(date)))}</small>
        </span></span>
        <em>${entries.length} ${entries.length === 1 ? "Folge" : "Folgen"}</em>
      </header>
      <div>${cards || '<p class="calendar-day-empty">Keine Veröffentlichung</p>'}</div>
    </section>`;
  }).join("");
  const days = document.getElementById("calendar-days");
  const status = document.getElementById("calendar-status");
  days.innerHTML = html;
  days.hidden = visible === 0;
  status.hidden = visible > 0;
  if (!visible) {
    calendarSetStatus(
      state.calendar.disabledReason ? "Kalender pausiert" : "Keine Treffer in dieser Woche",
      state.calendar.disabledReason || "Passe Suche oder Filter an.",
      { error: !!state.calendar.disabledReason },
    );
  }
  days.querySelectorAll("img").forEach((image) => {
    image.addEventListener("load", () => image.closest(".calendar-entry-art")?.classList.add("has-image"), { once: true });
    image.addEventListener("error", () => image.remove(), { once: true });
    if (image.complete && image.naturalWidth) image.closest(".calendar-entry-art")?.classList.add("has-image");
  });
}

function renderSeriesCalendar() {
  renderCalendarHero();
  const dates = calendarWeekDates(state.calendar.activeWeek || calendarInitialWeek());
  document.getElementById("calendar-range").textContent = `${calendarFormatRange(dates)}${state.calendar.stale ? " · letzter verfügbarer Stand" : ""}`;
  renderCalendarWeekStrip(dates);
  renderCalendarDays(dates);
  const weeks = calendarAvailableWeeks();
  const position = weeks.indexOf(state.calendar.activeWeek);
  document.getElementById("calendar-prev-week").disabled = position <= 0;
  document.getElementById("calendar-next-week").disabled = position < 0 || position >= weeks.length - 1;
}

function calendarMoveWeek(direction) {
  const weeks = calendarAvailableWeeks();
  const position = weeks.indexOf(state.calendar.activeWeek);
  const target = weeks[position + direction];
  if (!target) return;
  state.calendar.activeWeek = target;
  renderSeriesCalendar();
  document.getElementById("calendar-title").focus({ preventScroll: true });
}

function calendarOpenEntry(key) {
  const [date, rawIndex] = key.split(":");
  const entry = calendarEntriesForDate(date)[Number(rawIndex)];
  if (!entry) return;
  switchTab("serien", { autoLoad: false });
  loadSeries({
    title: entry.title,
    base_slug: entry.base_slug,
    sample_slug: entry.sample_slug,
    cover_url: entry.cover_url,
    provider: "serienstream",
    content_language: "de",
  });
}

function initSeriesCalendar() {
  calendarRestoreSnapshot();
  document.getElementById("calendar-prev-week").addEventListener("click", () => calendarMoveWeek(-1));
  document.getElementById("calendar-next-week").addEventListener("click", () => calendarMoveWeek(1));
  document.getElementById("calendar-today").addEventListener("click", () => {
    const week = calendarWeekKey(calendarTodayKey());
    if (calendarAvailableWeeks().includes(week)) state.calendar.activeWeek = week;
    renderSeriesCalendar();
    document.getElementById(`calendar-day-${calendarTodayKey()}`)?.scrollIntoView({ behavior: "smooth", block: "start" });
  });
  document.getElementById("calendar-search").addEventListener("input", (event) => {
    state.calendar.query = event.currentTarget.value;
    renderSeriesCalendar();
  });
  document.querySelectorAll("[data-calendar-language]").forEach((button) => {
    button.addEventListener("click", () => {
      state.calendar.language = button.dataset.calendarLanguage;
      document.querySelectorAll("[data-calendar-language]").forEach((candidate) => {
        const active = candidate === button;
        candidate.classList.toggle("is-active", active);
        candidate.setAttribute("aria-pressed", String(active));
      });
      renderSeriesCalendar();
    });
  });
  document.getElementById("calendar-subscribed").addEventListener("click", (event) => {
    state.calendar.subscribedOnly = !state.calendar.subscribedOnly;
    event.currentTarget.classList.toggle("is-active", state.calendar.subscribedOnly);
    event.currentTarget.setAttribute("aria-pressed", String(state.calendar.subscribedOnly));
    renderSeriesCalendar();
  });
  document.getElementById("calendar-week-strip").addEventListener("click", (event) => {
    const button = event.target.closest("[data-calendar-date]");
    if (!button) return;
    document.getElementById(`calendar-day-${button.dataset.calendarDate}`)?.scrollIntoView({ behavior: "smooth", block: "start" });
  });
  document.getElementById("calendar-days").addEventListener("click", (event) => {
    const entry = event.target.closest("[data-calendar-entry]");
    if (entry) calendarOpenEntry(entry.dataset.calendarEntry);
  });
  document.getElementById("calendar-status").addEventListener("click", (event) => {
    if (event.target.closest("[data-calendar-retry]")) void seriesCalendarLoad(true);
  });
  // Früh laden: Beim ersten Öffnen ist der Sendeplan dadurch meist bereits da.
  // Ein gespeicherter Stand bleibt während der Aktualisierung sichtbar.
  void seriesCalendarLoad();
}
