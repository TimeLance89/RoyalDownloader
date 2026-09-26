import { createScope } from "../../core/lifecycle.js";
import { escapeHtml } from "../../shared/utils/escape-html.js";
import { calendarDate, calendarTodayKey, calendarWeekKey, calendarWeekDates } from "./model.js";

export function createCalendarView(root, { model, ui, locale, loadSeries, subscriptions }) {
  const byId = id => root.querySelector(`#${id}`);
  let images, previousDays;
  let visibleDays = [];
  const days = () => visibleDays;
  function calendarAvailableWeeks() {
    return [...new Set(days().map((day) => calendarWeekKey(day.date)))].sort();
  }

  function calendarEntryMatches(entry) {
    const query = ui.query.trim().toLocaleLowerCase("de");
    if (query && !entry.title.toLocaleLowerCase("de").includes(query)) return false;
    if (ui.language !== "all"
        && String(entry.language_id) !== ui.language) return false;
    const status = ui.status || "all";
    if (status === "released" && !entry.released) return false;
    if (status === "upcoming" && entry.released) return false;
    if (ui.subscribedOnly && !entry.subscribed) return false;
    return true;
  }

  function calendarEntriesForDate(date) {
    const day = days().find((candidate) => candidate.date === date);
    return (day?.entries || []).filter(calendarEntryMatches);
  }

  function calendarSetStatus(title, copy, { error = false, retry = false, loading = false } = {}) {
    const status = byId("calendar-status");
    const days = byId("calendar-days");
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

  function calendarFormatRange(dates) {
    const formatter = new Intl.DateTimeFormat(locale(), { day: "2-digit", month: "short" });
    const year = calendarDate(dates[6]).getFullYear();
    return `${formatter.format(calendarDate(dates[0]))} – ${formatter.format(calendarDate(dates[6]))} ${year}`;
  }

  function renderCalendarHero() {
    const today = new Date();
    byId("calendar-hero-weekday").textContent = new Intl.DateTimeFormat(
      locale(), { weekday: "long" },
    ).format(today);
    byId("calendar-hero-day").textContent = String(today.getDate()).padStart(2, "0");
    byId("calendar-hero-month").textContent = new Intl.DateTimeFormat(
      locale(), { month: "long", year: "numeric" },
    ).format(today);
    const activeDates = new Set(calendarWeekDates(ui.activeWeek || calendarInitialWeek()));
    const entries = days()
      .filter((day) => activeDates.has(day.date))
      .flatMap((day) => day.entries || []);
    byId("calendar-total").textContent = String(entries.length);
    byId("calendar-today-count").textContent = String(
      days().find((day) => day.date === calendarTodayKey())?.entries?.length || 0,
    );
    byId("calendar-upcoming-count").textContent = String(
      entries.filter((entry) => entry.subscribed).length,
    );
  }

  function renderCalendarWeekStrip(dates) {
    const today = calendarTodayKey();
    const weekday = new Intl.DateTimeFormat(locale(), { weekday: "short" });
    byId("calendar-week-strip").innerHTML = dates.map((date) => {
      const count = calendarEntriesForDate(date).length;
      const isToday = date === today;
      const selected = ui.view !== "week" && ui.selectedDate === date;
      return `<button type="button" data-calendar-date="${date}" class="${isToday ? "is-today" : ""} ${selected ? "is-selected" : ""}"
          aria-pressed="${selected}" ${isToday ? 'aria-current="date"' : ""} aria-label="${escapeHtml(new Intl.DateTimeFormat(locale(), { dateStyle: "full" }).format(calendarDate(date)))}, ${count} ${count === 1 ? "Folge" : "Folgen"}">
        <span>${escapeHtml(weekday.format(calendarDate(date)))}</span>
        <strong>${String(calendarDate(date).getDate()).padStart(2, "0")}</strong>
        <small>${count} ${count === 1 ? "Folge" : "Folgen"}</small>
        <i aria-hidden="true">${isToday ? "Heute" : ""}</i>
      </button>`;
    }).join("");
  }

  function calendarCard(entry, date, index, eager) {
    const code = `S${String(entry.season).padStart(2, "0")} E${String(entry.episode).padStart(2, "0")}`;
    const stateLabel = entry.released ? "Verfügbar" : "Angekündigt";
    const timeLabel = entry.time !== "00:00" ? `${entry.time} Uhr` : "Zeit offen";
    return `<button class="calendar-entry ${entry.released ? "is-released" : "is-upcoming"}" type="button"
        data-calendar-entry="${date}:${index}" aria-label="${escapeHtml(entry.title)}, ${code} öffnen">
      <span class="calendar-entry-art">
        ${entry.cover_url ? `<img src="${escapeHtml(entry.cover_url)}" alt="" loading="${eager ? "eager" : "lazy"}"
          decoding="async" referrerpolicy="no-referrer" ${eager ? 'fetchpriority="high"' : ""}>` : ""}
        <i aria-hidden="true">${escapeHtml(entry.title.slice(0, 2).toLocaleUpperCase("de"))}</i>
      </span>
      <span class="calendar-entry-copy">
        <span class="calendar-entry-eyebrow"><time>${escapeHtml(timeLabel)}</time><i>${escapeHtml(stateLabel)}</i></span>
        <strong translate="no">${escapeHtml(entry.title)}</strong>
        <span class="calendar-entry-meta"><b>${code}</b><i>${escapeHtml(entry.language)}</i>${entry.subscribed ? '<i class="is-mine">★ Meine Serie</i>' : ""}</span>
      </span>
      <span class="calendar-entry-open" aria-hidden="true"><i></i>→</span>
    </button>`;
  }

  function renderCalendarDays(dates) {
    const today = calendarTodayKey();
    const weekday = new Intl.DateTimeFormat(locale(), { weekday: "long" });
    const month = new Intl.DateTimeFormat(locale(), { day: "2-digit", month: "long" });
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
          <span class="calendar-day-date"><b>${String(calendarDate(date).getDate()).padStart(2, "0")}</b><span>
            <strong>${date === today ? "Heute" : escapeHtml(weekday.format(calendarDate(date)))}</strong>
            <small>${escapeHtml(month.format(calendarDate(date)))}</small>
          </span></span>
          <em><b>${entries.length}</b> ${entries.length === 1 ? "Folge" : "Folgen"}</em>
        </header>
        <div>${cards || '<p class="calendar-day-empty"><span>—</span> Keine Veröffentlichung</p>'}</div>
      </section>`;
    }).join("");
    const days = byId("calendar-days");
    const status = byId("calendar-status");
    days.innerHTML = html;
    days.hidden = visible === 0;
    status.hidden = visible > 0;
    if (!visible) {
      calendarSetStatus(
        ui.disabledReason ? "Kalender pausiert" : dates.length === 1 ? "Keine Folgen an diesem Tag" : "Keine Treffer in dieser Woche",
        ui.disabledReason || "Wähle einen anderen Tag oder passe die Filter an.",
        { error: !!ui.disabledReason },
      );
    }
    days.querySelectorAll("img").forEach((image) => {
      images.listen(image, "load", () => image.closest(".calendar-entry-art")?.classList.add("has-image"), { once: true });
      images.listen(image, "error", () => image.remove(), { once: true });
      if (image.complete && image.naturalWidth) image.closest(".calendar-entry-art")?.classList.add("has-image");
    });
  }

  function renderSeriesCalendar() {
    const currentSubscriptions = subscriptions.get();
    const slugs = new Set(currentSubscriptions.items.map(entry => entry.base_slug));
    visibleDays = model.get().days.map(day => ({ ...day, entries: day.entries.map(entry => ({ ...entry,
      subscribed: currentSubscriptions.loaded ? slugs.has(entry.base_slug) : entry.subscribed,
    })) }));
    images?.dispose(); images = createScope();
    if (previousDays !== model.get().days) {
      previousDays = model.get().days;
      if (!calendarAvailableWeeks().includes(ui.activeWeek)) ui.activeWeek = calendarInitialWeek();
    }
    renderCalendarHero();
    const dates = calendarWeekDates(ui.activeWeek || calendarInitialWeek());
    if (!dates.includes(ui.selectedDate)) {
      ui.selectedDate = dates.includes(calendarTodayKey()) ? calendarTodayKey()
        : dates.find((date) => calendarEntriesForDate(date).length) || dates[0];
    }
    byId("calendar-range").textContent = `${calendarFormatRange(dates)}${model.get().stale ? " · letzter verfügbarer Stand" : ""}`;
    renderCalendarWeekStrip(dates);
    const visibleDates = ui.view === "week" ? dates : [ui.selectedDate];
    renderCalendarDays(visibleDates);
    const count = visibleDates.reduce((sum, date) => sum + calendarEntriesForDate(date).length, 0);
    byId("calendar-results").textContent = `${count} ${count === 1 ? "Folge" : "Folgen"} ${ui.view === "week" ? "in dieser Woche" : "am ausgewählten Tag"}`;
    root.querySelectorAll("[data-calendar-view]").forEach((button) => {
      const active = button.dataset.calendarView === (ui.view || "day");
      button.classList.toggle("is-active", active);
      button.setAttribute("aria-pressed", String(active));
    });
    const search = byId("calendar-search");
    if (search && search.value !== ui.query) search.value = ui.query;
    root.querySelectorAll("[data-calendar-language]").forEach((button) => {
      const active = button.dataset.calendarLanguage === ui.language;
      button.classList.toggle("is-active", active);
      button.setAttribute("aria-pressed", String(active));
    });
    root.querySelectorAll("[data-calendar-status]").forEach((button) => {
      const active = button.dataset.calendarStatus === ui.status;
      button.classList.toggle("is-active", active);
      button.setAttribute("aria-pressed", String(active));
    });
    const subscribed = byId("calendar-subscribed");
    subscribed?.classList.toggle("is-active", ui.subscribedOnly);
    subscribed?.setAttribute("aria-pressed", String(ui.subscribedOnly));
    const weeks = calendarAvailableWeeks();
    byId("calendar-prev-week").disabled = !weeks.some((week) => week < ui.activeWeek);
    byId("calendar-next-week").disabled = !weeks.some((week) => week > ui.activeWeek);
    const snapshot = model.get();
    if (!snapshot.loaded) {
      const failed = snapshot.phase === "error";
      byId("calendar-range").textContent = failed ? "Kalender nicht verfügbar" : "Kalender wird vorbereitet …";
      calendarSetStatus(failed ? "Kalender nicht erreichbar" : "Kalender wird vorbereitet",
        failed ? snapshot.error : "Der Server übernimmt den Sendeplan von SerienStream.",
        { error: failed, retry: failed, loading: !failed });
    } else if (snapshot.loading) byId("calendar-range").textContent = "Sendeplan wird aktualisiert …";
    else if (snapshot.error) byId("calendar-range").textContent += " · Aktualisierung fehlgeschlagen";

  }

  function calendarMoveWeek(direction) {
    const weeks = calendarAvailableWeeks();
    const target = direction < 0 ? weeks.filter((week) => week < ui.activeWeek).at(-1)
      : weeks.find((week) => week > ui.activeWeek);
    if (!target) return;
    ui.activeWeek = target;
    renderSeriesCalendar();
    byId("calendar-title").focus({ preventScroll: true });
  }

  function calendarOpenEntry(key) {
    const [date, rawIndex] = key.split(":");
    const entry = calendarEntriesForDate(date)[Number(rawIndex)];
    if (!entry) return;
    loadSeries({
      title: entry.title,
      base_slug: entry.base_slug,
      sample_slug: entry.sample_slug,
      cover_url: entry.cover_url,
      provider: "serienstream",
      content_language: "de",
    });
  }

  return { refresh: renderSeriesCalendar, moveWeek: calendarMoveWeek, openEntry: calendarOpenEntry, unmount() { images?.dispose(); images = null; } };
}
