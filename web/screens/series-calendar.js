const SERIES_CALENDAR_CACHE_KEY = "royal.series-calendar.v2";
const SERIES_CALENDAR_CACHE_MAX_AGE = 30 * 24 * 60 * 60 * 1_000;
const SERIES_CALENDAR_WATCHDOG_MS = 16_000;

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
    state.calendar.loaded = true;
    state.calendar.phase = "ready";
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
  const days = document.getElementById("calendar-days");
  if (!status || !days) return;
  status.classList.toggle("is-error", error);
  status.classList.toggle("is-loading", loading);
  status.hidden = false;
  status.innerHTML = `${loading
    ? '<span class="calendar-loader" aria-hidden="true"></span>'
    : `<span class="calendar-status-mark">${error ? "!" : "·"}</span>`}
    <strong>${escapeHtml(title)}</strong><small>${escapeHtml(copy)}</small>
    ${retry ? '<button type="button" data-calendar-retry>Erneut laden</button>' : ""}`;
  days.hidden = true;
}

function calendarInitialWeek() {
  const weeks = calendarAvailableWeeks();
  const todayWeek = calendarWeekKey(calendarTodayKey());
  if (weeks.includes(todayWeek)) return todayWeek;
  return weeks.find((week) => week > todayWeek) || weeks.at(-1) || todayWeek;
}

async function seriesCalendarLoad(force = false) {
  if (state.calendar.loading || (state.calendar.loaded && !force)) return false;
  const requestId = ++state.calendar.requestId;
  const hadSnapshot = state.calendar.days.length > 0;
  let watchdog = 0;
  state.calendar.loading = true;
  state.calendar.phase = "loading";
  state.calendar.error = "";
  try {
    const range = document.getElementById("calendar-range");
    if (range) range.textContent = hadSnapshot ? "Sendeplan wird aktualisiert …" : "Kalender wird vorbereitet …";
    if (!hadSnapshot) {
      calendarSetStatus("Kalender wird vorbereitet", "Der Server übernimmt den Sendeplan von SerienStream.", { loading: true });
    }
    watchdog = window.setTimeout(() => {
      if (state.calendar.requestId !== requestId || !state.calendar.loading) return;
      state.calendar.loading = false;
      state.calendar.phase = hadSnapshot ? "ready" : "error";
      state.calendar.error = "Der Kalenderdienst hat das Zeitlimit überschritten.";
      if (hadSnapshot) renderSeriesCalendar();
      else calendarSetStatus("Kalender nicht erreichbar", state.calendar.error, { error: true, retry: true });
    }, SERIES_CALENDAR_WATCHDOG_MS);
    const response = await api.seriesCalendar(force);
    if (state.calendar.requestId !== requestId || !state.calendar.loading) return false;
    if (!response?.ready && !response?.days?.length) {
      throw new Error(response?.error || "Der Server hat noch keinen gültigen Sendeplan.");
    }
    const payload = calendarNormalizeSnapshotPayload(response);
    if (!payload.total) throw new Error("Der Sendeplan enthält aktuell keine Einträge.");
    state.calendar.days = payload.days;
    state.calendar.total = payload.total;
    state.calendar.disabledReason = "";
    state.calendar.stale = Boolean(response.stale);
    state.calendar.cached = Boolean(response.stale);
    state.calendar.updatedAt = Number(response.updated_at || 0) * 1_000 || Date.now();
    state.calendar.loaded = true;
    state.calendar.phase = "ready";
    state.calendar.activeWeek = calendarInitialWeek();
    calendarStoreSnapshot(payload);
    renderSeriesCalendar();
    return true;
  } catch (error) {
    if (state.calendar.requestId !== requestId) return false;
    state.calendar.error = error?.message || "Unbekannter Kalenderfehler";
    if (hadSnapshot) {
      state.calendar.stale = true;
      state.calendar.cached = true;
      state.calendar.loaded = true;
      state.calendar.phase = "ready";
      renderSeriesCalendar();
      const range = document.getElementById("calendar-range");
      if (range) range.textContent += " · Aktualisierung fehlgeschlagen";
    } else {
      state.calendar.loaded = false;
      state.calendar.phase = "error";
      const range = document.getElementById("calendar-range");
      if (range) range.textContent = "Kalender nicht verfügbar";
      calendarSetStatus("Kalender nicht erreichbar", state.calendar.error, { error: true, retry: true });
    }
    return false;
  } finally {
    window.clearTimeout(watchdog);
    if (state.calendar.requestId === requestId) state.calendar.loading = false;
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

function initSeriesCalendar({ autoLoad = false } = {}) {
  if (state.calendar.initialized) {
    if (autoLoad) void seriesCalendarLoad(state.calendar.loaded);
    return;
  }
  state.calendar.initialized = true;
  const restored = calendarRestoreSnapshot();
  document.getElementById("calendar-prev-week")?.addEventListener("click", () => calendarMoveWeek(-1));
  document.getElementById("calendar-next-week")?.addEventListener("click", () => calendarMoveWeek(1));
  document.getElementById("calendar-today")?.addEventListener("click", () => {
    const week = calendarWeekKey(calendarTodayKey());
    if (calendarAvailableWeeks().includes(week)) state.calendar.activeWeek = week;
    renderSeriesCalendar();
    document.getElementById(`calendar-day-${calendarTodayKey()}`)?.scrollIntoView({ behavior: "smooth", block: "start" });
  });
  document.getElementById("calendar-search")?.addEventListener("input", (event) => {
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
  document.getElementById("calendar-subscribed")?.addEventListener("click", (event) => {
    state.calendar.subscribedOnly = !state.calendar.subscribedOnly;
    event.currentTarget.classList.toggle("is-active", state.calendar.subscribedOnly);
    event.currentTarget.setAttribute("aria-pressed", String(state.calendar.subscribedOnly));
    renderSeriesCalendar();
  });
  document.getElementById("calendar-week-strip")?.addEventListener("click", (event) => {
    const button = event.target.closest("[data-calendar-date]");
    if (!button) return;
    document.getElementById(`calendar-day-${button.dataset.calendarDate}`)?.scrollIntoView({ behavior: "smooth", block: "start" });
  });
  document.getElementById("calendar-days")?.addEventListener("click", (event) => {
    const entry = event.target.closest("[data-calendar-entry]");
    if (entry) calendarOpenEntry(entry.dataset.calendarEntry);
  });
  document.getElementById("calendar-status")?.addEventListener("click", (event) => {
    if (event.target.closest("[data-calendar-retry]")) void seriesCalendarLoad(true);
  });
  if (!restored) {
    state.calendar.phase = "idle";
    calendarSetStatus(
      "Kalender bereit",
      "Der Sendeplan wird direkt nach der Anmeldung automatisch übernommen.",
      { retry: true },
    );
  }
  if (autoLoad) void seriesCalendarLoad(restored);
}

// Die Bedienung wird unabhängig vom großen App-Bootstrap verdrahtet. Selbst
// wenn ein anderes Startmodul ausfällt, bleibt nie ein statischer Loader stehen.
function calendarInstallSafetyNet() {
  window.setTimeout(() => initSeriesCalendar({ autoLoad: false }), 0);
}
if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", calendarInstallSafetyNet, { once: true });
} else {
  calendarInstallSafetyNet();
}
