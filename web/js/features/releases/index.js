import { createScope } from "../../core/lifecycle.js";
import { isAbortError } from "../../core/errors.js";
import { releaseRequest as request } from "./api.js";
import { createReleaseSettings } from "./settings.js";

export function createReleases({ openSettings, openMedia }) {
  let root, scope;
  const t = (de, en) => document.documentElement.lang.startsWith("en") ? en : de;
  const esc = value => String(value ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
  let data = null, loading = false, cancelPoll = null, pollUntil = 0;
  let platform = "all", period = "upcoming", media = "all", query = "", message = "";
  const regionNames = {de:"Deutschland",at:"Österreich",ch:"Schweiz",us:"USA",gb:"United Kingdom"};
  const dayKey = stamp => stamp ? new Intl.DateTimeFormat("en-CA", {timeZone:data?.region === "us" ? "America/New_York" : data?.region === "gb" ? "Europe/London" : "Europe/Berlin",year:"numeric",month:"2-digit",day:"2-digit"}).format(new Date(stamp * 1000)) : "unknown";
  const dateLabel = stamp => stamp ? new Intl.DateTimeFormat(document.documentElement.lang || "de", {timeZone: data?.region === "us" ? "America/New_York" : data?.region === "gb" ? "Europe/London" : "Europe/Berlin",day:"numeric",month:"long",weekday:"short"}).format(new Date(stamp * 1000)) : t("Termin folgt", "Date to be announced");

  function status(entry) {
    if (!entry.can_check) return t("Royal-Prüfung ab Plattformstart", "Royal check opens at release");
    return ({catalog:t("In Royal gefunden", "Found in Royal"),not_found:t("Noch kein sicherer Treffer", "No confirmed match yet"),
      unknown:t("Prüfung ohne Ergebnis", "Check inconclusive"),checking:t("Royal wird geprüft …", "Checking Royal …"),
      unchecked:t("In Royal noch ungeprüft", "Not checked in Royal yet")})[entry.rd?.status] || t("In Royal noch ungeprüft", "Not checked in Royal yet");
  }

  function card(entry) {
    const image = `<span class="release-no-poster" aria-hidden="true">${esc(entry.title?.slice(0, 2).toLocaleUpperCase() || "◷")}</span>${entry.poster ? `<img src="${esc(entry.poster)}" alt="" loading="lazy" decoding="async" referrerpolicy="no-referrer">` : ""}`;
    const catalog = entry.rd?.status === "catalog";
    const isSeries = entry.media_type === "series";
    return `<article class="release-card"><div class="release-art">${image}<span class="release-platform" translate="no">${esc(entry.platform)}</span></div><div class="release-copy">
      <div class="release-card-labels"><span>${isSeries ? t("Serie", "Series") : t("Film", "Movie")}</span>${entry.year ? `<span>${esc(entry.year)}</span>` : ""}</div>
      <h3 data-i18n-ignore translate="no">${esc(entry.title)}</h3>
      <p class="release-overview" data-i18n-ignore>${esc(entry.overview || t("Noch keine Beschreibung vorhanden.", "No description available yet."))}</p>
      <small class="release-kind" title="${entry.date_kind === "observed" ? t("Kein bestätigtes Erstveröffentlichungsdatum", "Not a confirmed premiere date") : t("Angekündigter Start auf dieser Plattform", "Announced release on this platform")}">${entry.date_kind === "observed" ? t("Auf der Plattform entdeckt", "Observed on the platform") : t("Angekündigter Plattformstart", "Announced platform release")}</small>
      <div class="release-card-foot"><span class="release-state ${catalog ? "is-found" : ""}">${status(entry)}</span>
      ${entry.can_check ? `<button type="button" data-check="${esc(entry.id)}" aria-label="${esc(entry.title)}: ${catalog ? t("in Royal öffnen", "open in Royal") : t("in Royal prüfen", "check in Royal")}" ${entry.rd?.status === "checking" ? "disabled" : ""}>${catalog ? (isSeries ? t("Serie öffnen", "Open series") : t("Film öffnen", "Open movie")) : t("In Royal prüfen", "Check in Royal")}</button>` : ""}</div>
    </div></article>`;
  }

  function emptyState() {
    let title, copy, action = "";
    if (loading || data?.loading) {
      title = t("Streamingstarts werden geladen", "Loading streaming releases");
      copy = t("Die Termine erscheinen, sobald der Abgleich abgeschlossen ist.", "Dates will appear when the sync completes.");
    } else if (message || data?.error) {
      title = t("Termine gerade nicht erreichbar", "Release dates are unavailable");
      copy = t("Versuche den Abruf erneut oder prüfe die Datenquelle in den Einstellungen.", "Try again or check the data source in Settings.");
      action = `<button type="button" data-release-retry>${t("Erneut laden", "Try again")}</button>`;
    } else if (data?.configured === false) {
      title = t("Verbinde deinen Release-Kalender", "Connect your release calendar");
      copy = t("Richte die Datenquelle einmal ein, um Film- und Serienstarts deiner Streamingplattformen zu sehen.", "Set up the data source to see movie and series releases on your streaming services.");
      action = `<button type="button" data-release-settings>${t("Datenquelle einrichten", "Set up data source")}</button>`;
    } else if (!data) {
      title = t("Deine Streamingstarts", "Your streaming releases");
      copy = t("Lade die aktuellen Termine deiner Plattformen.", "Load the latest release dates for your services.");
      action = `<button type="button" data-release-retry>${t("Termine laden", "Load release dates")}</button>`;
    } else {
      title = t("Keine Releases in dieser Auswahl", "No releases match this selection");
      copy = t("Wähle einen anderen Zeitraum oder setze die Filter zurück. Fehlende Termine werden nicht geschätzt.", "Choose a different period or reset the filters. Missing dates are never guessed.");
      action = `<button type="button" data-release-reset>${t("Alle Releases anzeigen", "Show all releases")}</button>`;
    }
    return `<div class="release-empty"><span aria-hidden="true">◷</span><h2>${title}</h2><p>${copy}</p>${action}</div>`;
  }

  function render() {
    if (!scope?.active || !root) return;
    const focused = root.contains(document.activeElement) ? document.activeElement : null;
    const focusId = focused?.id;
    const focusData = focused ? Object.entries(focused.dataset).find(([key]) => ["period", "platform", "media", "check", "releaseReset", "releaseRetry", "releaseSettings"].includes(key)) : null;
    const selection = focusId === "release-search" ? focused.selectionStart : null;
    const platforms = [...new Map((data?.entries || []).map(e => [e.platform_id,e.platform])).entries()].sort((a,b)=>a[1].localeCompare(b[1]));
    if (platform !== "all" && !platforms.some(([id]) => id === platform)) platform = "all";
    const matching = (data?.entries || []).filter(e => (platform === "all" || e.platform_id === platform)
      && (media === "all" || e.media_type === media)
      && (!query.trim() || e.title.toLocaleLowerCase().includes(query.trim().toLocaleLowerCase())));
    const entries = matching.filter(e => period === "all" || (period === "upcoming" ? !e.has_started : e.has_started))
      .sort((a,b)=>period === "past" ? (b.timestamp || 0) - (a.timestamp || 0) : (a.timestamp || Infinity) - (b.timestamp || Infinity));
    const groups = new Map();
    entries.forEach(e => { const key=dayKey(e.timestamp); if(!groups.has(key)) groups.set(key,[]); groups.get(key).push(e); });
    root.innerHTML = `<div class="release-workspace"><header class="releases-heading"><div><h1>${t("Streaming-Releases", "Streaming releases")}</h1>
      <p>${t("Neue Filme und Serien. Nach Plattform und Startdatum sortiert.", "New movies and series, organized by service and release date.")}</p></div>
      <button type="button" data-release-settings>${t("Datenquelle & Region", "Data source & region")}</button></header>
      <div class="release-period" role="group" aria-label="${t("Zeitraum", "Period")}">
      ${[["upcoming",t("Demnächst", "Coming soon")],["past",t("Bereits gestartet", "Already streaming")],["all",t("Alle Termine", "All dates")]].map(([id,label])=>`<button type="button" data-period="${id}" aria-pressed="${period===id}">${label}<span>${matching.filter(e => id === "all" || (id === "upcoming" ? !e.has_started : e.has_started)).length}</span></button>`).join("")}</div>
      <section class="release-filters" aria-label="${t("Releases filtern", "Filter releases")}"><div class="release-toolbar">
      <label class="release-search"><span>${t("Titel suchen", "Search titles")}</span><input id="release-search" type="search" value="${esc(query)}" placeholder="${t("Film oder Serie suchen …", "Find a movie or series …")}"></label>
      <div class="release-media-filter" role="group" aria-label="${t("Inhalt", "Content")}">${[["all",t("Alles", "All")],["movie",t("Filme", "Movies")],["series",t("Serien", "Series")]].map(([id,label])=>`<button type="button" data-media="${id}" aria-pressed="${media === id}">${label}</button>`).join("")}</div></div>
      <div class="release-platforms" role="group" aria-label="${t("Streamingplattform", "Streaming service")}"><button type="button" data-platform="all" aria-pressed="${platform==='all'}">${t("Alle Plattformen", "All services")}</button>
      ${platforms.map(([id,name])=>`<button type="button" translate="no" data-platform="${esc(id)}" aria-pressed="${platform===id}">${esc(name)}</button>`).join("")}</div></section>
      <div class="release-results"><p role="status">${entries.length} ${entries.length === 1 ? "Release" : "Releases"}${data?.region ? ` ${t("für", "for")} ${esc(regionNames[data.region] || data.region)}` : ""}</p><span>${period === "past" ? t("Zuletzt gestartet zuerst", "Most recent first") : t("Nächster Termin zuerst", "Earliest date first")}</span></div>
      <div class="release-sync" role="status">${esc(message || (data?.loading ? t("Termine werden im Hintergrund abgeglichen …", "Syncing dates in the background …") : data?.error || ""))}${data?.stale ? `<span>${t("Gespeicherter Stand – möglicherweise veraltet", "Cached data — may be outdated")}</span>` : ""}${data?.partial ? `<span>${t("Einige Plattformen konnten nicht vollständig geladen werden.", "Some services could not be fully loaded.")}</span>` : ""}</div>
      <div class="release-timeline">${entries.length ? [...groups.values()].map(rows=>`<section class="release-day"><header><h2>${esc(dateLabel(rows[0].timestamp))}</h2><span>${rows.length} ${rows.length === 1 ? "Release" : "Releases"}</span></header><div class="release-day-cards">${rows.map(card).join("")}</div></section>`).join("") : emptyState()}</div>
      <footer class="release-attribution"><p>${t("Plattformstarts sind keine Zusage für die Verfügbarkeit in Royal. Entdeckte Titel können schon länger auf der Plattform sein.", "Platform releases do not guarantee availability in Royal. Observed titles may have been on the service for longer.")}</p>${data?.updated_at ? `<p>${t("Letzter Abgleich", "Last synced")}: ${esc(new Date(data.updated_at*1000).toLocaleString(document.documentElement.lang || "de"))}</p>` : ""}Streaming availability provided by <a href="https://www.movieofthenight.com/about/api" target="_blank" rel="noopener noreferrer">Streaming Availability API by Movie of the Night</a></footer></div>`;
    root.querySelectorAll(".release-art img").forEach(image => image.addEventListener("error", () => image.remove(), {once:true}));
    const replacement = focusId ? root.querySelector(`#${CSS.escape(focusId)}`) : focusData
      ? [...root.querySelectorAll("button")].find(button => button.dataset[focusData[0]] === focusData[1]) : null;
    replacement?.focus({preventScroll:true});
    if (focusId === "release-search" && replacement) try { replacement.setSelectionRange(selection, selection); } catch (_) { /* Search inputs may reject selection. */ }
  }

  async function load() {
    if (!scope?.active || loading) return;
    const current = scope;
    loading = true;
    if (!data) render();
    try {
      const result = await request("/api/releases", { signal: current.signal });
      if (!current.active) return;
      data = result; message = "";
    } catch (error) {
      if (!current.active || isAbortError(error)) return;
      message = t("Abruf nicht möglich. Bitte erneut versuchen.", "Unable to load. Please try again.");
    } finally {
      if (current.active) { loading = false; render(); }
    }
    if (!current.active) return;
    cancelPoll?.();
    if (data?.loading || data?.entries?.some(e => e.rd?.status === "checking")) {
      if (!pollUntil) pollUntil = Date.now() + 180000;
      if (Date.now() < pollUntil) cancelPoll = current.timeout(() => void load(), 3000);
      else { message = t("Abgleich dauert länger. Später erneut öffnen.", "Sync is taking longer. Reopen this page later."); render(); }
    } else pollUntil = 0;
  }

  const onClick = async event => {
    const current = scope;
    const button=event.target.closest("button"); if(!button) return;
    if(button.hasAttribute("data-release-retry")) {pollUntil=0; await load(); return;}
    if(button.hasAttribute("data-release-reset")) {platform="all"; media="all"; period="all"; query=""; render(); return;}
    if(button.hasAttribute("data-release-settings")) { openSettings(); return; }
    if(button.dataset.period) {period=button.dataset.period; render(); return;}
    if(button.dataset.media) {media=button.dataset.media; render(); return;}
    if(button.dataset.platform) {platform=button.dataset.platform; render(); return;}
    if(button.dataset.check) {
      const entry=data.entries.find(e=>e.id===button.dataset.check);
      if(entry?.rd?.status === "catalog" && entry.rd.matches?.[0]) {
        const match=entry.rd.matches[0];
        openMedia(entry.media_type, match);
        return;
      }
      button.disabled=true;
      try { await request("/api/releases/check", {method:"POST",body:{id:button.dataset.check}, signal:current.signal}); if (!current.active) return; pollUntil=0; await load(); }
      catch (error) { if (!current.active || isAbortError(error)) return; message=t("Prüfung nicht möglich. Bitte später erneut versuchen.", "Check unavailable. Please try again later."); render(); }
    }
  };
  const onInput = event=>{if(event.target.id!=="release-search")return; query=event.target.value; render();};

  const settings = createReleaseSettings({ request, t, regionNames, onData(result) { data = result; render(); } });
  return {
    settings,
    mount(element, { autoLoad = true } = {}) {
      if (scope) return;
      root = element;
      scope = createScope();
      scope.listen(root, "click", onClick);
      scope.listen(root, "input", onInput);
      const language = new MutationObserver(() => render());
      language.observe(document.documentElement, { attributes: true, attributeFilter: ["lang"] });
      scope.observe(language);
      render();
      if (autoLoad) void load();
    },
    refresh: load,
    unmount() {
      scope?.dispose();
      scope = null;
      loading = false;
      pollUntil = 0;
      cancelPoll = null;
      root = null;
    },
  };
}
