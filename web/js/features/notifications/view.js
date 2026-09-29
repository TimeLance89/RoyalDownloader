import { createScope } from "../../core/lifecycle.js";
import { buildSubscriptionInbox, inboxEntriesForFilter, inboxIssueDetail, inboxDownloadDetail } from "./model.js";

export function createNotificationView(root, { getSnapshot, ui, coverUrl, subscriptionMonogram, libraryCheckedLabel, inboxCheckBusy, closeNotifDropdown, openWatchlistEntry, runNotificationCheck, markNotificationDownloadsRead }) {
  const document = root.ownerDocument;
  const find = id => root.querySelector(`#${id}`);
  let rows;
  function buildNotificationItem(item) {
    const { entry, openCount, queuedCount, waitingLanguageCount, upcomingCount, waitingSourceCount, downloadedCount, hasIssue } = item;
    const stateName = hasIssue ? "issue" : waitingLanguageCount ? "waiting-language" : upcomingCount ? "upcoming" : openCount ? "new" : queuedCount ? "queued" : "downloaded";
    const row = document.createElement("article");
    row.className = `notif-item is-${stateName}`;
    row.dataset.baseSlug = entry.base_slug;

    const open = document.createElement("button");
    open.type = "button";
    open.className = "notif-item-open";
    open.setAttribute("aria-label", `${entry.title} öffnen`);
    const art = document.createElement("span");
    art.className = "notif-item-art";
    if (entry.backdrop_url) {
      const image = document.createElement("img");
      image.src = coverUrl(entry.backdrop_url);
      image.alt = "";
      image.loading = "lazy";
      rows.listen(image, "error", () => art.classList.add("is-fallback"), { once: true });
      art.appendChild(image);
    } else {
      art.classList.add("is-fallback");
    }
    const monogram = document.createElement("span");
    monogram.className = "notif-item-monogram";
    monogram.textContent = subscriptionMonogram(entry.title);
    art.appendChild(monogram);

    const copy = document.createElement("span");
    copy.className = "notif-item-copy";
    const title = document.createElement("strong");
    title.translate = false;
    title.textContent = entry.title;
    const meta = document.createElement("small");
    meta.className = "notif-item-meta";
    meta.textContent = entry.checking ? "Wird gerade geprüft …" : libraryCheckedLabel(entry);
    const signals = document.createElement("span");
    signals.className = "notif-item-signals";
    const signal = (kind, text) => {
      const pill = document.createElement("span");
      pill.className = `notif-state is-${kind}`;
      pill.textContent = text;
      signals.appendChild(pill);
    };
    if (openCount) signal("new", `${openCount} ${openCount === 1 ? "Folge offen" : "Folgen offen"}`);
    if (queuedCount) signal("queued", `${queuedCount} im Downloadplan`);
    if (waitingLanguageCount) signal("waiting-language", `${waitingLanguageCount} ${waitingLanguageCount === 1 ? "wartet auf Deutsch" : "warten auf Deutsch"}`);
    if (waitingSourceCount) signal("waiting-source", `${waitingSourceCount} ${waitingSourceCount === 1 ? "wartet auf Quelle" : "warten auf Quelle"}`);
    if (upcomingCount) signal("upcoming", `${upcomingCount} ${upcomingCount === 1 ? "demnächst" : "demnächst"}`);
    if (downloadedCount) signal("downloaded", `${downloadedCount} ${downloadedCount === 1 ? "Folge geladen" : "Folgen geladen"}`);
    if (hasIssue) signal("issue", "Problem");
    copy.append(title, meta, signals);
    const arrow = document.createElement("span");
    arrow.className = "notif-item-arrow";
    arrow.textContent = "›";
    open.append(art, copy, arrow);
    rows.listen(open, "click", () => {
      closeNotifDropdown();
      openWatchlistEntry(entry.base_slug);
    });
    row.appendChild(open);

    const detailText = hasIssue ? inboxIssueDetail(entry)
      : waitingLanguageCount ? "Die Episode ist verfügbar, aber noch nicht in deiner gewünschten Sprache."
      : waitingSourceCount ? "Die Episode ist bekannt, aber noch ohne geeignete Quelle."
      : upcomingCount ? "Angekündigte Folgen werden erst nach Veröffentlichung geprüft."
      : entry.status === "waiting_window" && openCount
        ? "Der automatische Download wartet auf das nächste Zeitfenster."
        : openCount ? "Serie öffnen, um die offenen Folgen auszuwählen."
          : queuedCount ? "Diese Folgen stehen im Downloadplan." : "";
    if (detailText) {
      const detail = document.createElement("p");
      detail.className = "notif-item-detail";
      detail.textContent = detailText;
      row.appendChild(detail);
    }
    if (downloadedCount) {
      const receipt = document.createElement("small");
      receipt.className = "notif-item-download";
      receipt.textContent = inboxDownloadDetail(entry);
      row.appendChild(receipt);
    }
    const actions = document.createElement("div");
    actions.className = "notif-item-actions";
    if (openCount || hasIssue) {
      const check = document.createElement("button");
      check.type = "button";
      check.className = "notif-item-check";
      check.textContent = entry.checking ? "Prüft …" : "Erneut prüfen";
      check.disabled = inboxCheckBusy();
      rows.listen(check, "click", async () => {
        check.disabled = true;
        try { await runNotificationCheck([entry.base_slug]); }
        finally { check.disabled = false; }
      });
      actions.appendChild(check);
    }
    if (downloadedCount) {
      const read = document.createElement("button");
      read.type = "button";
      read.className = "notif-item-read";
      read.textContent = ui.reading === entry.base_slug ? "Wird gespeichert …" : "Als gelesen";
      read.disabled = Boolean(ui.reading);
      rows.listen(read, "click", async () => {
        read.disabled = true;
        try { await markNotificationDownloadsRead(entry); }
        finally { read.disabled = false; }
      });
      actions.appendChild(read);
    }
    if (actions.children.length) row.appendChild(actions);
    return row;
  }

  function inboxContext(model, filter) {
    if (filter === "new") return `${model.totals.open} Folgen offen. Fehlgeschlagene Downloads bleiben hier sichtbar.`;
    if (filter === "queued") return `${model.totals.queued} Folgen im Downloadplan.`;
    if (filter === "downloaded") return `${model.totals.downloaded} Downloads sind noch ungelesen.`;
    if (filter === "issue") return "Download-, Prüf- und Bereinigungsfehler.";
    if (model.totals.waitingLanguage) return `${model.totals.waitingLanguage} Folgen warten auf die gewünschte Sprache.`;
    return "Ein Eintrag pro Abo. Ein Abo kann mehrere Zustände haben.";
  }

  function appendInboxEmpty(list, filter) {
    const empty = document.createElement("div");
    empty.className = "notif-empty";
    const seal = document.createElement("span");
    seal.className = "notif-empty-seal";
    const title = document.createElement("strong");
    const detail = document.createElement("small");
    if (!getSnapshot().loaded) {
      seal.textContent = "…";
      title.textContent = "Abonnements werden geladen";
      detail.textContent = "Der Status wird abgerufen.";
    } else if (!getSnapshot().items.length) {
      seal.textContent = "+";
      title.textContent = "Noch keine Abonnements";
      detail.textContent = "Abonniere eine Serie, damit Meldungen hier erscheinen.";
    } else if (inboxCheckBusy()) {
      seal.textContent = "…";
      title.textContent = "Abonnements werden geprüft";
      detail.textContent = "Die Meldungen werden gleich aktualisiert.";
    } else {
      const messages = {
        all: ["Keine aktuellen Meldungen", "Neue Funde, Downloads und Probleme erscheinen hier."],
        new: ["Keine offenen Folgen", "Zurzeit ist keine Folge zur Auswahl offen."],
        queued: ["Keine geplanten Downloads", "Keine Abo-Folge steht im Downloadplan."],
        downloaded: ["Keine ungelesenen Downloads", "Geladene Folgen wurden bereits bestätigt."],
        issue: ["Keine Probleme gemeldet", "Aktuell liegt kein Abo-Fehler vor."],
      }[filter];
      seal.textContent = "✓";
      title.textContent = messages[0];
      detail.textContent = messages[1];
    }
    empty.append(seal, title, detail);
    list.appendChild(empty);
  }

  function renderNotifBell(content = true) {

    const model = buildSubscriptionInbox(getSnapshot().items, { ...getSnapshot().health, error: getSnapshot().error || getSnapshot().health?.error });
    const filter = Object.hasOwn(model.counts, ui.filter) ? ui.filter : "all";
    ui.filter = filter;
    const badge = find("notif-badge");
    const issueBadge = find("notif-issue-badge");
    const bell = find("notif-bell");
    const summary = model.counts.all
      ? `${model.counts.all} ${model.counts.all === 1 ? "Eintrag" : "Einträge"}`
      : getSnapshot().loaded ? "Keine Meldungen" : "Wird geladen …";
    const attention = model.counts.issue;
    const triggerSummary = !getSnapshot().loaded
      ? "Wird geladen …"
      : attention
        ? `${attention} ${attention === 1 ? "Problem" : "Probleme"}`
        : "Alles aktuell";
    // The header badge is an attention signal, not an inbox-size counter.
    // Passive states (language/source waits, upcoming episodes and download
    // receipts) stay visible inside the inbox without making the bell look urgent.
    badge.textContent = String(attention);
    badge.classList.toggle("hidden", attention === 0);
    // Keep the legacy marker node for DOM compatibility; the numeric badge now
    // carries the complete problem signal and avoids duplicate warning markers.
    issueBadge.classList.add("hidden");
    bell.classList.toggle("is-active", attention > 0);
    bell.setAttribute("aria-label", `Abo-Inbox öffnen: ${triggerSummary}`);
    find("notif-trigger-label").textContent = triggerSummary;
    find("notif-summary").textContent = inboxCheckBusy()
      ? "Abonnements werden geprüft …" : summary;
    find("notif-subscription-count").textContent =
      `${getSnapshot().items.length} ${getSnapshot().items.length === 1 ? "Abo" : "Abos"}`;
    const refresh = find("notif-refresh");
    refresh.disabled = inboxCheckBusy() || !getSnapshot().loaded || !getSnapshot().items.length;
    refresh.classList.toggle("is-loading", inboxCheckBusy());
    const feedback = find("notif-feedback");
    if (feedback) {
      feedback.textContent = ui.feedback || "";
      feedback.hidden = !feedback.textContent;
      feedback.classList.toggle("is-error", Boolean(ui.feedbackError));
    }
    root.querySelectorAll("[data-notif-filter]").forEach((button) => {
      const kind = button.dataset.notifFilter;
      const active = kind === filter;
      button.classList.toggle("is-active", active);
      button.setAttribute("aria-pressed", String(active));
      const count = button.querySelector(".notif-filter-count");
      if (count) count.textContent = String(model.counts[kind]);
    });

    if (!content) return;
    rows?.dispose(); rows = createScope();
    const list = find("notif-list");
    list.replaceChildren();
    const visible = inboxEntriesForFilter(model, filter);
    const showGlobalError = Boolean(model.globalError && (filter === "all" || filter === "issue"));
    if (visible.length || showGlobalError) {
      const context = document.createElement("p");
      context.className = "notif-context";
      context.textContent = inboxContext(model, filter);
      list.appendChild(context);
    }
    if (showGlobalError) {
      const problem = document.createElement("div");
      problem.className = "notif-global-issue";
      const title = document.createElement("strong");
      title.textContent = "Abonnements konnten nicht geprüft werden";
      const detail = document.createElement("small");
      detail.textContent = model.globalError;
      problem.append(title, detail);
      list.appendChild(problem);
    }
    visible.forEach((item) => list.appendChild(buildNotificationItem(item)));
    if (!visible.length && !showGlobalError) appendInboxEmpty(list, filter);
  }

  return { refresh: renderNotifBell, unmount() { rows?.dispose(); rows = null; } };
}
