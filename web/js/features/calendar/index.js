import { createScope } from "../../core/lifecycle.js";
import { createCalendarState } from "./state.js";
import { createCalendarStorage } from "./storage.js";
import { createCalendarView } from "./view.js";
import { calendarWeekKey, calendarTodayKey } from "./model.js";

export function createCalendar(root, { subscriptions, getUserId, locale, loadSeries, storage, client }) {
  const cache = createCalendarStorage(storage);
  const model = createCalendarState({ cache, client });
  const ui = { activeWeek: "", language: "all", status: "all", query: "", subscribedOnly: false, selectedDate: "", view: "day", disabledReason: "" };
  const view = createCalendarView(root, { model, ui, locale, loadSeries, subscriptions });
  const byId = id => root.querySelector(`#${id}`);
  let scope, initialized = false;
  function initialize() {
    if (initialized) return;
    initialized = true;
    Object.assign(ui, cache.restoreFilters(getUserId()));
    const restored = model.restore();
    void model.refresh(restored);
  }
  return {
    initialize,
    refresh() { return model.refresh(true); },
    mount() {
      if (scope?.active) return;
      scope = createScope();
      scope.add(model.subscribe(() => view.refresh()));
      scope.add(subscriptions.subscribe((snapshot, previous) => { if (snapshot.items !== previous.items || snapshot.loaded !== previous.loaded) view.refresh(); }));
      initialize();
      scope.listen(byId("calendar-prev-week"), "click", () => view.moveWeek(-1));
      scope.listen(byId("calendar-next-week"), "click", () => view.moveWeek(1));
      scope.listen(byId("calendar-today"), "click", () => {
        const week = calendarWeekKey(calendarTodayKey());
        ui.activeWeek = week;
        ui.selectedDate = calendarTodayKey();
        ui.view = "day";
        cache.storeFilters(getUserId(), ui);
        view.refresh();
      });
      scope.listen(byId("calendar-search"), "input", (event) => {
        ui.query = event.currentTarget.value;
        cache.storeFilters(getUserId(), ui);
        view.refresh();
      });
      root.querySelectorAll("[data-calendar-language]").forEach((button) => {
        scope.listen(button, "click", () => {
          ui.language = button.dataset.calendarLanguage;
          cache.storeFilters(getUserId(), ui);
          root.querySelectorAll("[data-calendar-language]").forEach((candidate) => {
            const active = candidate === button;
            candidate.classList.toggle("is-active", active);
            candidate.setAttribute("aria-pressed", String(active));
          });
          view.refresh();
        });
      });
      root.querySelectorAll("[data-calendar-status]").forEach((button) => {
        scope.listen(button, "click", () => {
          ui.status = button.dataset.calendarStatus;
          cache.storeFilters(getUserId(), ui);
          root.querySelectorAll("[data-calendar-status]").forEach((candidate) => {
            const active = candidate === button;
            candidate.classList.toggle("is-active", active);
            candidate.setAttribute("aria-pressed", String(active));
          });
          view.refresh();
        });
      });
      scope.listen(byId("calendar-subscribed"), "click", (event) => {
        ui.subscribedOnly = !ui.subscribedOnly;
        cache.storeFilters(getUserId(), ui);
        event.currentTarget.classList.toggle("is-active", ui.subscribedOnly);
        event.currentTarget.setAttribute("aria-pressed", String(ui.subscribedOnly));
        view.refresh();
      });
      scope.listen(byId("calendar-week-strip"), "click", (event) => {
        const button = event.target.closest("[data-calendar-date]");
        if (!button) return;
        ui.selectedDate = button.dataset.calendarDate;
        ui.view = "day";
        cache.storeFilters(getUserId(), ui);
        view.refresh();
        root.querySelector(`[data-calendar-date="${ui.selectedDate}"]`)?.focus({ preventScroll: true });
      });
      root.querySelectorAll("[data-calendar-view]").forEach((button) => {
        scope.listen(button, "click", () => {
          ui.view = button.dataset.calendarView;
          cache.storeFilters(getUserId(), ui);
          view.refresh();
        });
      });
      scope.listen(byId("calendar-days"), "click", (event) => {
        const entry = event.target.closest("[data-calendar-entry]");
        if (entry) view.openEntry(entry.dataset.calendarEntry);
      });
      scope.listen(byId("calendar-status"), "click", (event) => {
        if (event.target.closest("[data-calendar-retry]")) void model.refresh(true);
      });

      view.refresh();
      if (!model.get().loaded) void model.refresh();
    },
    unmount() { scope?.dispose(); scope = null; view.unmount(); model.unmount(); },
  };
}
