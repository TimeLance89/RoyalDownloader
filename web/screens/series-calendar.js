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

function calendarSetStatus(title, copy, isError = false) {
  const status = document.getElementById("calendar-status");
  status.classList.toggle("is-error", isError);
  status.hidden = false;
  status.innerHTML = `${isError ? '<span class="calendar-status-mark">!</span>' : '<span class="calendar-loader" aria-hidden="true"></span>'}
    <strong>${escapeHtml(title)}</strong><small>${escapeHtml(copy)}</small>`;
  document.getElementById("calendar-days").hidden = true;
}

function calendarInitialWeek() {
  const weeks = calendarAvailableWeeks();
  const todayWeek = calendarWeekKey(calendarTodayKey());
  if (weeks.includes(todayWeek)) return todayWeek;
  return weeks.find((week) => week > todayWeek) || weeks.at(-1) || todayWeek;
}

async function seriesCalendarLoad(force = false) {
  if (state.calendar.loading || (state.calendar.loaded && !force)) return;
  state.calendar.loading = true;
  state.calendar.error = "";
  calendarSetStatus("Sendeplan wird geladen", "Termine und Cover werden vorbereitet.");
  try {
    const payload = await api.seriesCalendar();
    state.calendar.days = Array.isArray(payload.days) ? payload.days : [];
    state.calendar.total = Number(payload.total || 0);
    state.calendar.disabledReason = payload.disabled_reason || "";
    state.calendar.stale = !!payload.stale;
    state.calendar.loaded = true;
    state.calendar.activeWeek = calendarInitialWeek();
    renderSeriesCalendar();
  } catch (error) {
    state.calendar.error = error.message;
    calendarSetStatus("Kalender nicht erreichbar", error.message, true);
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
    <span class="calendar-entry-time"><b>${escapeHtml(entry.time)}</b><small>UHR</small></span>
    <span class="calendar-entry-copy">
      <strong translate="no">${escapeHtml(entry.title)}</strong>
      <span><b>${code}</b><i>${escapeHtml(entry.language)}</i>${entry.subscribed ? "<i>★ Abo</i>" : ""}</span>
    </span>
    <span class="calendar-entry-state"><i></i>${stateLabel}</span>
    <span class="calendar-entry-open" aria-hidden="true">→</span>
  </button>`;
}

function renderCalendarDays(dates) {
  const today = calendarTodayKey();
  const fullDate = new Intl.DateTimeFormat(i18n.locale(), {
    weekday: "long", day: "2-digit", month: "long",
  });
  let imageBudget = 10;
  let visible = 0;
  const html = dates.map((date) => {
    const entries = calendarEntriesForDate(date);
    if (!entries.length) return "";
    visible += entries.length;
    const cards = entries.map((entry, index) => {
      const eager = imageBudget-- > 0;
      return calendarCard(entry, date, index, eager);
    }).join("");
    return `<section class="calendar-day ${date === today ? "is-today" : ""}" id="calendar-day-${date}">
      <header><span>${date === today ? "HEUTE" : escapeHtml(fullDate.format(calendarDate(date)))}</span>
        <strong>${entries.length} ${entries.length === 1 ? "Eintrag" : "Einträge"}</strong></header>
      <div>${cards}</div>
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
      !!state.calendar.disabledReason,
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
}
