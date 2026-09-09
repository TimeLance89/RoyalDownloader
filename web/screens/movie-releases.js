/* Regional streaming dates. The server alone decides when RD checks unlock. */
(() => {
  "use strict";
  const root = document.getElementById("tab-releases");
  if (!root) return;
  const style = document.createElement("link");
  style.rel = "stylesheet";
  style.href = "/styles/movie-releases.css?v=royal-20260909-1";
  document.head.append(style);
  document.querySelectorAll('.tab-btn[data-tab="kalender"]').forEach(button => {
    const release = document.createElement("button");
    release.className = "tab-btn";
    release.dataset.tab = "releases";
    release.innerHTML = '<span class="tab-icon" aria-hidden="true">◷</span><span>Releases</span>';
    button.after(release);
  });
  const t = (de, en) => document.documentElement.lang.startsWith("en") ? en : de;
  const esc = value => String(value ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
  let data = null, loading = false, timer = null, pollUntil = 0;
  let platform = "all", period = "upcoming", query = "", message = "";
  const regionNames = {de:"Deutschland",at:"Österreich",ch:"Schweiz",us:"USA",gb:"United Kingdom"};
  const dayKey = stamp => stamp ? new Intl.DateTimeFormat("en-CA", {timeZone:data?.region === "us" ? "America/New_York" : data?.region === "gb" ? "Europe/London" : "Europe/Berlin",year:"numeric",month:"2-digit",day:"2-digit"}).format(new Date(stamp * 1000)) : "unknown";
  const dateLabel = stamp => stamp ? new Intl.DateTimeFormat(document.documentElement.lang || "de", {timeZone: data?.region === "us" ? "America/New_York" : data?.region === "gb" ? "Europe/London" : "Europe/Berlin",day:"numeric",month:"long",weekday:"short"}).format(new Date(stamp * 1000)) : t("Termin folgt", "Date to be announced");

  async function request(path, options = {}) {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 15000);
    try {
      const response = await fetch(path, {...options, signal:controller.signal, headers:{"Content-Type":"application/json"}});
      if (!response.ok) throw new Error(t("Anfrage fehlgeschlagen", "Request failed") + ` (${response.status})`);
      return await response.json();
    } finally { clearTimeout(timeout); }
  }

  function status(entry) {
    if (!entry.can_check) return t("Noch nicht freigegeben", "Not released for checking");
    return ({catalog:t("Im RD-Katalog", "In the RD catalog"),not_found:t("Kein sicherer RD-Treffer", "No confirmed RD match"),
      unknown:t("Prüfung nicht abgeschlossen", "Check inconclusive"),checking:t("RD wird geprüft …", "Checking RD …"),
      unchecked:t("RD noch nicht geprüft", "RD not checked yet")})[entry.rd?.status] || t("RD noch nicht geprüft", "RD not checked yet");
  }

  function card(entry) {
    const image = entry.poster ? `<img src="${esc(entry.poster)}" alt="" loading="lazy" referrerpolicy="no-referrer">` : '<span class="release-no-poster" aria-hidden="true">◷</span>';
    const catalog = entry.rd?.status === "catalog";
    return `<article class="release-card"><div class="release-art">${image}</div><div class="release-copy">
      <span class="release-platform" translate="no">${esc(entry.platform)}</span>
      <h3 data-i18n-ignore>${esc(entry.title)}</h3><small>${esc(entry.year)}</small>
      <p data-i18n-ignore>${esc(entry.overview)}</p>
      <div class="release-card-foot"><span class="release-state ${catalog ? "is-found" : ""}">${status(entry)}</span>
      ${entry.can_check ? `<button type="button" data-check="${esc(entry.id)}" ${entry.rd?.status === "checking" ? "disabled" : ""}>${catalog ? t("Film öffnen", "Open movie") : t("RD prüfen", "Check RD")}</button>` : ""}</div>
      <small class="release-kind">${entry.date_kind === "observed" ? t("Auf der Plattform entdeckt — kein bestätigtes Erstveröffentlichungsdatum", "Observed on the platform — not a confirmed premiere date") : t("Angekündigter Plattformstart", "Announced platform release")}</small>
    </div></article>`;
  }

  function render() {
    const platforms = [...new Map((data?.entries || []).map(e => [e.platform_id,e.platform])).entries()].sort((a,b)=>a[1].localeCompare(b[1]));
    const entries = (data?.entries || []).filter(e => (platform === "all" || e.platform_id === platform)
      && (!query || e.title.toLocaleLowerCase().includes(query.toLocaleLowerCase()))
      && (period === "all" || (period === "upcoming" ? !e.can_check : e.can_check)))
      .sort((a,b)=>(a.timestamp || Infinity)-(b.timestamp || Infinity));
    const groups = new Map();
    entries.forEach(e => { const key=dayKey(e.timestamp); if(!groups.has(key)) groups.set(key,[]); groups.get(key).push(e); });
    root.innerHTML = `<header class="releases-heading"><div><h1>${t("Dem Filmstart voraus.", "Ahead of movie night.")}</h1>
      <p>${t("Was als Nächstes streamt. Und wann du es in Royal findest.", "What streams next. And when you can find it in Royal.")}</p></div>
      <button type="button" data-release-settings>${t("Datenquelle einrichten", "Configure data source")}</button></header>
      <div class="release-toolbar"><div class="release-period" role="group" aria-label="${t("Zeitraum", "Period")}">
      ${[["upcoming",t("Demnächst", "Coming soon")],["past",t("Bereits gestartet", "Already streaming")],["all",t("Alle Termine", "All dates")]].map(([id,label])=>`<button type="button" data-period="${id}" aria-pressed="${period===id}">${label}</button>`).join("")}</div>
      <label>${t("Film suchen", "Find a movie")}<input id="release-search" type="search" value="${esc(query)}" placeholder="${t("Titel eingeben", "Enter a title")}"></label></div>
      <div class="release-platforms" role="group" aria-label="${t("Streamingplattform", "Streaming service")}"><button type="button" data-platform="all" aria-pressed="${platform==='all'}">${t("Alle Plattformen", "All platforms")}</button>
      ${platforms.map(([id,name])=>`<button type="button" translate="no" data-platform="${esc(id)}" aria-pressed="${platform===id}">${esc(name)}</button>`).join("")}</div>
      <div class="release-sync" role="status">${esc(message || (data?.loading ? t("Termine werden im Hintergrund abgeglichen …", "Syncing dates in the background …") : data?.error || ""))}
      ${data?.updated_at ? `<span>${esc(regionNames[data.region] || data.region)} · ${t("Stand", "Updated")} ${esc(new Date(data.updated_at*1000).toLocaleString())}${data.stale ? ` · ${t("Gespeicherter Stand – möglicherweise veraltet", "Cached data — may be outdated")}` : ""}</span>` : ""}
      ${data?.partial ? `<span>${t("Teilansicht: Das Abruflimit wurde erreicht; die Liste ist nicht vollständig.", "Partial coverage: the API page limit was reached.")}</span>` : ""}</div>
      <div class="release-timeline">${entries.length ? [...groups.values()].map(rows=>`<section class="release-day"><h2>${esc(dateLabel(rows[0].timestamp))}</h2><div class="release-day-cards">${rows.map(card).join("")}</div></section>`).join("") : `<div class="release-empty"><span aria-hidden="true">◷</span><h2>${!data?.configured ? t("Dein Release-Kalender beginnt hier", "Your release calendar starts here") : loading || data.loading ? t("Termine werden geladen", "Loading dates") : t("Keine bestätigten Termine in dieser Auswahl", "No confirmed dates in this selection")}</h2><p>${!data?.configured ? t("Hinterlege deinen kostenlosen API-Key in den Einstellungen. Netflix, Disney+, Prime Video und weitere Plattformen werden gemeinsam abgefragt.", "Add your free API key in Settings. Netflix, Disney+, Prime Video and other platforms are queried together.") : t("Die Vorschau umfasst bis zu 31 Tage. Fehlende Termine werden nicht geschätzt.", "The preview covers up to 31 days. Missing dates are never guessed.")}</p></div>`}</div>
      <footer class="release-attribution">Streaming availability provided by <a href="https://www.movieofthenight.com/about/api" target="_blank" rel="noopener noreferrer">Streaming Availability API by Movie of the Night</a></footer>`;
  }

  async function load() {
    if (loading) return;
    loading = true;
    if (!data) render();
    try { data = await request("/api/releases"); message = ""; }
    catch (_) { message = t("Abruf nicht möglich. Erneut öffnen, um es noch einmal zu versuchen.", "Unable to load. Reopen this page to retry."); }
    finally { loading = false; render(); }
    clearTimeout(timer);
    if (data?.loading || data?.entries?.some(e=>e.rd?.status === "checking")) {
      if (!pollUntil) pollUntil = Date.now() + 180000;
      if (Date.now() < pollUntil) timer=setTimeout(()=>{if(root.classList.contains("active")) load();}, 3000);
      else {message=t("Abgleich dauert länger. Später erneut öffnen.", "Sync is taking longer. Reopen this page later."); render();}
    } else pollUntil=0;
  }

  root.addEventListener("click", async event => {
    const button=event.target.closest("button"); if(!button) return;
    if(button.hasAttribute("data-release-settings")) { switchTab("einstellungen"); document.querySelector('[data-settings-target="settings-media"]')?.click(); document.getElementById("release-settings")?.scrollIntoView({block:"center"}); return; }
    if(button.dataset.period) {period=button.dataset.period; render(); return;}
    if(button.dataset.platform) {platform=button.dataset.platform; render(); return;}
    if(button.dataset.check) {
      const entry=data.entries.find(e=>e.id===button.dataset.check);
      if(entry?.rd?.status === "catalog" && entry.rd.matches?.[0]) {const movie=entry.rd.matches[0]; selectFpRow(movie.slug,movie); return;}
      button.disabled=true;
      try { await request("/api/releases/check", {method:"POST",body:JSON.stringify({id:button.dataset.check})}); pollUntil=0; await load(); }
      catch (_) { message=t("Prüfung nicht möglich. Bitte später erneut versuchen.", "Check unavailable. Please try again later."); render(); }
    }
  });
  root.addEventListener("input",event=>{if(event.target.id!=="release-search")return; query=event.target.value; const position=event.target.selectionStart;render();const field=root.querySelector("#release-search");field.focus();try{field.setSelectionRange(position,position);}catch(_){/* search inputs may reject selection */}});

  function mountSettings() {
    const grid=document.querySelector(".settings-service-grid"); if(!grid)return;
    const settings=document.createElement("div"); settings.id="release-settings";settings.className="settings-group settings-card";
    settings.innerHTML=`<h3>${t("Film-Releases", "Movie releases")}</h3><p>${t("Kostenloser Direktzugang von Movie of the Night. Wähle beim Anbieter den Free-Tarif ohne Zahlungsdaten.", "Free direct access from Movie of the Night. Choose the provider’s Free plan without payment details.")}</p>
      <a href="https://developers.movieofthenight.com/" target="_blank" rel="noopener noreferrer">${t("Kostenlosen API-Key erstellen", "Get a free API key")}</a>
      <label for="releases-key">API-Key</label><input id="releases-key" type="password" autocomplete="off" placeholder="${t("API-Key eingeben", "Enter API key")}">
      <label for="releases-region">${t("Release-Region", "Release region")}</label><select id="releases-region">${Object.entries(regionNames).map(([id,name])=>`<option value="${id}">${name}</option>`).join("")}</select>
      <div class="release-settings-actions"><button type="button" id="releases-save" class="btn btn-primary">${t("Speichern & Verbindung prüfen", "Save & test connection")}</button><button type="button" id="releases-remove" class="btn btn-ghost">${t("Key entfernen", "Remove key")}</button></div>
      <p id="releases-config-status" role="status"></p><small>${t("Täglicher Abgleich. Maximal 900 Abrufe in 31 Tagen. Kein kostenpflichtiger Fallback.", "Daily sync. Up to 900 requests in 31 days. No paid fallback.")}</small>`;
    grid.append(settings);
    const status=settings.querySelector("#releases-config-status");
    async function config() {try{const cfg=await request("/api/releases/config");settings.querySelector("#releases-region").value=cfg.region;settings.querySelector("#releases-key").placeholder=cfg.has_api_key?t("Gespeichert — leer lassen zum Beibehalten", "Saved — leave blank to keep"):"API-Key";}catch(_){status.textContent=t("Einstellungen konnten nicht geladen werden.", "Unable to load settings.");}}
    // Settings data is loaded only when opened, after the login barrier.
    const visibility=new MutationObserver(()=>{if(document.body.classList.contains("settings-active")){config();}});
    visibility.observe(document.body,{attributes:true,attributeFilter:["class"]});
    settings.addEventListener("click",async event=>{
      if(!["releases-save","releases-remove"].includes(event.target.id))return;
      const button=event.target;button.disabled=true;
      try {
        await request("/api/releases/config", {method:"POST", body:JSON.stringify({
          api_key:settings.querySelector("#releases-key").value,
          region:settings.querySelector("#releases-region").value,
          remove_key:button.id === "releases-remove"
        })});
        settings.querySelector("#releases-key").value="";
        await config();
        let result=await request("/api/releases/test", {method:"POST"});
        const deadline=Date.now()+180000;
        status.textContent=t("Gespeichert. Verbindung wird geprüft …", "Saved. Testing connection …");
        while(result.loading && Date.now()<deadline) {
          await new Promise(resolve=>setTimeout(resolve,3000));
          result=await request("/api/releases");
        }
        status.textContent=!result.configured ? t("API-Key entfernt.", "API key removed.")
          : result.loading ? t("Abgleich dauert länger. Ergebnis später unter Releases prüfen.", "Sync is taking longer. Check Releases later.")
          : result.error ? t("Verbindung fehlgeschlagen. API-Key und Gratis-Kontingent prüfen. Erneuter Test nach fünf Minuten möglich.", "Connection failed. Check your API key and free quota. Retry after five minutes.")
          : t("Verbindung bestätigt. Termine gespeichert. Täglicher Abgleich aktiv.", "Connection confirmed. Dates saved. Daily sync enabled.");
        data=result;render();
      } catch(_) {
        status.textContent=t("Speichern oder Verbindungsprüfung fehlgeschlagen.", "Saving or testing the connection failed.");
      } finally {button.disabled=false;}
    });
  }
  mountSettings();render();
  new MutationObserver(()=>render()).observe(document.documentElement,{attributes:true,attributeFilter:["lang"]});
  window.movieReleases={load:()=>{pollUntil=0;return load();}};
})();
