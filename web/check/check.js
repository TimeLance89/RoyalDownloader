const byId = (id) => document.getElementById(id);
const statusNames = {
  queued: "Eingereiht", preparing: "Quelle wird geprüft", downloading: "Lädt",
  waiting_provider: "Wartet auf Quelle", cancelling: "Wird abgebrochen",
  completed: "Erfolgreich", failed: "Fehlgeschlagen", cancelled: "Abgebrochen",
};
const audioNames = {
  waiting: ["Wartet", "warn"], checking: ["Prüft Tonspur", "warn"],
  confirmed: ["Deutsch bestätigt", "good"], mismatch: ["Fremdsprache erkannt", "bad"],
  unclear: ["Sprache unklar", "warn"], unavailable: ["Prüfung nicht verfügbar", "warn"],
};
const waitNames = { language_unavailable: "Keine passende Sprachquelle", source_unavailable: "Keine nutzbare Quelle" };
const timeFormat = new Intl.DateTimeFormat("de", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
const numberFormat = new Intl.NumberFormat("de", { maximumFractionDigits: 1 });
const jobs = new Map();
let results = [];
let socket = null;
let stopped = false;
let dirty = false;
let fetching = false;
let revision = 0;

function element(tag, value, className = "") {
  const node = document.createElement(tag);
  node.textContent = value;
  if (className) node.className = className;
  return node;
}

function safeDetail(value) {
  return String(value || "").replace(/https?:\/\/\S+/gi, "[Link]").slice(0, 260);
}

function source(job) {
  return [job.provider, job.hoster || job.hoster_label, job.content_language?.toUpperCase()]
    .filter(Boolean).join(" · ") || "Quelle noch offen";
}

function tone(cell, job) {
  const [label, color] = audioNames[job.audio_check_status] || ["—", ""];
  cell.append(element("span", label, color));
  if (job.audio_check_detail) cell.append(element("small", safeDetail(job.audio_check_detail)));
}

function renderQueue() {
  const active = [...jobs.values()];
  const running = active.filter((job) => job.status === "downloading").length;
  byId("counts").textContent = `${running} aktiv · ${active.length - running} in Vorbereitung oder wartend`;
  const rows = active.map((job) => {
    const row = element("tr", "");
    const transfer = element("td", statusNames[job.status] || "Eingereiht");
    if (job.status === "downloading" && job.progress != null) {
      const percent = Math.max(0, Math.min(100, Number(job.progress) || 0));
      const bar = element("progress", "");
      bar.max = 100;
      bar.value = percent;
      bar.setAttribute("aria-label", "Downloadfortschritt");
      const speed = job.speed_bps > 0 ? ` · ${numberFormat.format(job.speed_bps / 1048576)} MiB/s` : "";
      transfer.append(bar, element("small", `${numberFormat.format(percent)} %${speed}`));
    }
    const detail = job.error || waitNames[job.wait_reason];
    if (detail) transfer.append(element("small", safeDetail(detail), "warn"));
    const audio = element("td", "");
    tone(audio, job);
    row.append(element("td", job.title || job.slug), element("td", source(job)), transfer, audio);
    return row;
  });
  if (!rows.length) {
    const row = element("tr", "");
    const cell = element("td", "Die Queue ist leer.", "empty");
    cell.colSpan = 4;
    row.append(cell);
    rows.push(row);
  }
  byId("jobs").replaceChildren(...rows);
}

function renderResults() {
  const filter = byId("result-filter").value;
  const items = results.filter((job) => !filter || job.status === filter).slice(0, 40).map((job) => {
    const item = element("li", "");
    const color = job.status === "completed" ? "good" : job.status === "failed" ? "bad" : "warn";
    const stamp = job.completed_at ? timeFormat.format(job.completed_at * 1000) : "";
    item.append(element("time", stamp), element("span", statusNames[job.status] || job.status, color),
      element("p", job.title || job.slug), element("small", source(job)));
    if (job.audio_check_status) tone(item, job);
    if (job.error) item.append(element("small", safeDetail(job.error), "bad"));
    return item;
  });
  byId("results").replaceChildren(...(items.length ? items : [element("li", "Keine passenden Ergebnisse.", "empty")]));
}

function activity(message, color) {
  const list = byId("events");
  if (list.firstElementChild?.classList.contains("empty")) list.replaceChildren();
  const entry = element("li", "");
  entry.append(element("time", timeFormat.format(Date.now())), element("span", safeDetail(message), color));
  list.prepend(entry);
  if (list.children.length > 80) list.lastElementChild.remove();
}

function connection(text, state = "") {
  byId("connection").textContent = text;
  byId("connection").dataset.state = state;
}

async function refresh() {
  if (fetching || stopped) return;
  fetching = true;
  const startRevision = revision;
  try {
    const responses = await Promise.all(["jobs", "history"].map((part) =>
      fetch(`/api/queue/${part}`, { cache: "no-store", signal: AbortSignal.timeout(8000) })));
    if (responses.some((response) => response.status === 401 || response.status === 403)) {
      stopped = true;
      socket?.close();
      jobs.clear();
      results = [];
      byId("dashboard").hidden = true;
      byId("access").hidden = false;
      connection("Anmeldung erforderlich");
      return;
    }
    if (responses.some((response) => !response.ok)) throw new Error("Queue");
    const [queue, history] = await Promise.all(responses.map((response) => response.json()));
    if (startRevision === revision) {
      jobs.clear();
      for (const job of queue.jobs || []) jobs.set(job.job_id, job);
    }
    results = history.jobs || [];
    byId("dashboard").hidden = false;
    renderQueue();
    renderResults();
    if (socket?.readyState !== WebSocket.OPEN) connection("Abgleich alle 15 Sekunden");
  } catch {
    connection("Queue gerade nicht erreichbar");
  } finally {
    fetching = false;
  }
}

function connect() {
  if (stopped) return;
  socket = new WebSocket(`${location.protocol === "https:" ? "wss:" : "ws:"}//${location.host}/ws`);
  socket.addEventListener("open", () => { connection("Live verbunden", "live"); void refresh(); });
  socket.addEventListener("close", () => {
    if (stopped) return;
    connection("Live-Verbindung getrennt");
    void refresh();
    setTimeout(connect, 5000);
  });
  socket.addEventListener("message", (event) => {
    let data;
    try { data = JSON.parse(event.data); } catch { return; }
    if (data.type === "log" && (["warn", "err"].includes(data.level)
      || /^\s*(?:Versuche Hoster|Stream bereit|Prüfe Hoster|Fertig|Fehler)/.test(data.message || ""))) {
      activity(data.message, data.level === "err" ? "bad" : data.level === "warn" ? "warn" : "");
    } else if ((data.type === "progress" || data.type === "audio_verification") && data.job?.job_id) {
      revision++;
      jobs.set(data.job.job_id, data.job);
      dirty = true;
      if (data.type === "audio_verification") activity(`${data.job.title} · ${data.job.audio_check_detail}`);
    } else if (["job_done", "queue_done", "queue_update", "queue_started"].includes(data.type)) {
      void refresh();
    }
  });
}

byId("result-filter").addEventListener("change", renderResults);
setInterval(() => { if (dirty) { dirty = false; renderQueue(); } }, 300);
setInterval(() => { if (!document.hidden) void refresh(); }, 15000);
await refresh();
connect();
