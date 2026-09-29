const assert = require("node:assert/strict");
const { test } = require("node:test");

const model = require("../../web/js/features/notifications/model.js");
const { createNotifications } = require("../../web/js/features/notifications/index.js");
function loadInbox() { return model; }

function plain(value) {
  return JSON.parse(JSON.stringify(value));
}

function subscription(base_slug, fields = {}) {
  return {
    base_slug, title: base_slug, status: "current",
    new_count: 0, queued_count: 0, downloaded_count: 0, failed_count: 0,
    ...fields,
  };
}

function slugs(context, model, filter) {
  return Array.from(context.inboxEntriesForFilter(model, filter), ({ entry }) => entry.base_slug).sort();
}

test("empty subscriptions have no notices or episode totals", () => {
  const inbox = loadInbox();
  const model = inbox.buildSubscriptionInbox([]);
  assert.deepEqual(plain(model.counts), { all: 0, new: 0, queued: 0, downloaded: 0, issue: 0 });
  assert.deepEqual(plain(model.totals), { open: 0, queued: 0, waitingLanguage: 0, downloaded: 0 });
  assert.equal(model.entries.length, 0);
  assert.ok(!model.globalError);
});

test("the four failed Chicago Fire episodes remain visible in the open filter", () => {
  const inbox = loadInbox();
  const model = inbox.buildSubscriptionInbox([
    subscription("chicago-fire", { open_count: 4, new_count: 4, failed_count: 4, status: "failed" }),
    subscription("lanterns", { downloaded_count: 1 }),
    subscription("current-show"),
  ]);
  assert.deepEqual(slugs(inbox, model, "new"), ["chicago-fire"]);
  assert.deepEqual(slugs(inbox, model, "issue"), ["chicago-fire"]);
  assert.deepEqual(slugs(inbox, model, "downloaded"), ["lanterns"]);
  assert.equal(model.totals.open, 4);
  assert.equal(model.counts.new, 1, "filter counters count subscriptions, not episodes");
  assert.equal(model.counts.all, 2);
});

test("orthogonal filters retain all states while the all filter renders each subscription once", () => {
  const inbox = loadInbox();
  const entries = [
    subscription("problem", { open_count: 4, new_count: 4, failed_count: 4, status: "failed" }),
    subscription("download", { downloaded_count: 1 }),
    subscription("queue", { open_count: 0, new_count: 2, queued_count: 2, status: "queued" }),
    subscription("mixed", { open_count: 1, new_count: 3, queued_count: 2, downloaded_count: 1, failed_count: 1 }),
    subscription("current"),
  ];
  const before = JSON.stringify(entries);
  const model = inbox.buildSubscriptionInbox(entries);
  assert.deepEqual(plain(model.counts), { all: 4, new: 2, queued: 2, downloaded: 2, issue: 2 });
  assert.deepEqual(plain(model.totals), { open: 5, queued: 4, waitingLanguage: 0, downloaded: 2 });
  assert.deepEqual(slugs(inbox, model, "all"), ["download", "mixed", "problem", "queue"]);
  assert.deepEqual(slugs(inbox, model, "new"), ["mixed", "problem"]);
  assert.deepEqual(slugs(inbox, model, "queued"), ["mixed", "queue"]);
  assert.deepEqual(slugs(inbox, model, "downloaded"), ["download", "mixed"]);
  assert.deepEqual(slugs(inbox, model, "issue"), ["mixed", "problem"]);
  for (const filter of ["all", "new", "queued", "downloaded", "issue"]) {
    assert.equal(inbox.inboxEntriesForFilter(model, filter).length, model.counts[filter]);
  }
  assert.equal(JSON.stringify(entries), before, "building and sorting the inbox must not mutate watchlist state");
});

test("an explicit zero open count is respected and legacy counts are never guessed by subtraction", () => {
  const inbox = loadInbox();
  const model = inbox.buildSubscriptionInbox([
    subscription("legacy", { new_count: 5, queued_count: 3, failed_count: 2 }),
    subscription("explicit", { open_count: 0, new_count: 7, queued_count: 7 }),
    subscription("string-counts", { open_count: "2", new_count: "3", queued_count: "1", downloaded_count: "1" }),
  ]);
  const bySlug = new Map(Array.from(model.entries, (entry) => [entry.entry.base_slug, entry]));
  assert.equal(bySlug.get("legacy").openCount, 5);
  assert.equal(bySlug.get("explicit").openCount, 0);
  assert.equal(bySlug.get("string-counts").openCount, 2);
  assert.deepEqual(slugs(inbox, model, "new"), ["legacy", "string-counts"]);
});

test("EN-only and upcoming episodes remain visible without becoming a problem", () => {
  const inbox = loadInbox();
  const model = inbox.buildSubscriptionInbox([
    subscription("chicago-fire", {
      status: "waiting_for_language", waiting_language_count: 2, upcoming_count: 1,
      open_count: 0, failed_count: 0,
    }),
  ]);
  const item = model.entries[0];
  assert.equal(item.hasIssue, false);
  assert.equal(item.waitingLanguageCount, 2);
  assert.equal(item.upcomingCount, 1);
  assert.deepEqual(slugs(inbox, model, "all"), ["chicago-fire"]);
  assert.deepEqual(slugs(inbox, model, "issue"), []);
});

test("each independent error source creates an issue even if the status is current", () => {
  const inbox = loadInbox();
  for (const fields of [
    { failed_count: 1 }, { failed_count: "2" },
    { last_error: "source unavailable" }, { cleanup_last_error: "permission denied" },
    { status: "blocked" }, { status: "failed" },
  ]) {
    const entry = subscription("issue", fields);
    assert.equal(inbox.notificationHasIssue(entry), true, JSON.stringify(fields));
    const model = inbox.buildSubscriptionInbox([entry]);
    assert.equal(model.counts.issue, 1);
    assert.deepEqual(slugs(inbox, model, "issue"), ["issue"]);
  }
  for (const status of ["current", "queued", "waiting_release", "waiting_window", "missing"]) {
    assert.equal(inbox.notificationHasIssue(subscription("okay", { status })), false);
  }
});

test("a global check error contributes a separate notice alongside existing subscriptions", () => {
  const inbox = loadInbox();
  const model = inbox.buildSubscriptionInbox([
    subscription("download", { downloaded_count: 1 }),
    subscription("problem", { failed_count: 1, open_count: 2 }),
  ], { error: "API unavailable" });
  assert.equal(model.globalError, "API unavailable");
  assert.deepEqual(plain(model.counts), { all: 3, new: 1, queued: 0, downloaded: 1, issue: 2 });
  assert.deepEqual(slugs(inbox, model, "all"), ["download", "problem"]);
  assert.deepEqual(slugs(inbox, model, "issue"), ["problem"]);
  const onlyGlobal = inbox.buildSubscriptionInbox([], { error: "API unavailable" });
  assert.equal(onlyGlobal.counts.all, 1);
  assert.equal(onlyGlobal.counts.issue, 1);
  assert.equal(onlyGlobal.entries.length, 0);
});

test("download labels and ordering use the unread episode instead of newer read history", () => {
  const inbox = loadInbox();
  const readHistory = subscription("older-unread", {
    downloaded_count: 1,
    last_downloaded_episode: { season: 9, episode: 9, downloaded_at: 900 },
    last_unread_downloaded_episode: { season: 1, episode: 4, downloaded_at: 100 },
  });
  const recent = subscription("newer-unread", {
    downloaded_count: 1,
    last_downloaded_episode: { season: 2, episode: 8, downloaded_at: 200 },
  });
  assert.equal(inbox.downloadedEpisodeLabel(readHistory), "S01E04");
  assert.equal(inbox.downloadedEpisodeLabel(recent), "S02E08");
  assert.equal(inbox.downloadedEpisodeLabel(subscription("none")), "");
  const model = inbox.buildSubscriptionInbox([readHistory, recent]);
  const sorted = inbox.inboxEntriesForFilter(model, "downloaded");
  assert.deepEqual(Array.from(sorted, ({ entry }) => entry.base_slug), ["newer-unread", "older-unread"]);
});

// A small DOM fixture keeps rendering/event regressions executable without a browser dependency.
class Element {
  constructor(tagName = "div") {
    this.tagName = tagName;
    this.children = [];
    this.dataset = {};
    this.attributes = {};
    this.listeners = {};
    this.className = "";
    this._text = "";
  }
  get classList() {
    const element = this;
    return {
      contains(name) { return element.className.split(/\s+/).includes(name); },
      add(...names) { names.forEach((name) => this.toggle(name, true)); },
      remove(...names) { names.forEach((name) => this.toggle(name, false)); },
      toggle(name, force) {
        const names = new Set(element.className.split(/\s+/).filter(Boolean));
        const enabled = force ?? !names.has(name);
        if (enabled) names.add(name); else names.delete(name);
        element.className = [...names].join(" ");
        return enabled;
      },
    };
  }
  get textContent() { return this._text + this.children.map((child) => child.textContent).join(""); }
  set textContent(value) { this._text = String(value); this.children = []; }
  set innerHTML(value) { this.children = []; this._text = String(value).replace(/<[^>]*>/g, ""); }
  append(...children) {
    for (const child of children) { child.parentElement = this; this.children.push(child); }
  }
  appendChild(child) { this.append(child); return child; }
  replaceChildren(...children) { this.children = []; this._text = ""; this.append(...children); }
  remove() {
    if (this.parentElement) {
      this.parentElement.children = this.parentElement.children.filter((child) => child !== this);
    }
  }
  setAttribute(name, value) { this.attributes[name] = String(value); }
  getAttribute(name) { return this.attributes[name] ?? null; }
  addEventListener(name, callback) { (this.listeners[name] ??= []).push(callback); }
  removeEventListener(name, callback) { this.listeners[name] = (this.listeners[name] || []).filter(item => item !== callback); }
  contains(target) { return this === target || this.children.some(child => child.contains(target)); }
  focus() {}
  async fire(name) {
    for (const callback of this.listeners[name] || []) {
      await callback({ stopPropagation() {}, preventDefault() {}, target: this });
    }
  }
  matches(selector) {
    if (selector.startsWith(".")) return this.classList.contains(selector.slice(1));
    if (selector.startsWith("#")) return this.id === selector.slice(1);
    const attribute = selector.match(/^(\w+)?\[data-([\w-]+)\]$/);
    if (attribute) {
      const key = attribute[2].replace(/-([a-z])/g, (_, char) => char.toUpperCase());
      return (!attribute[1] || this.tagName === attribute[1]) && key in this.dataset;
    }
    return this.tagName === selector;
  }
  querySelectorAll(selector) {
    return this.children.flatMap((child) => [
      ...(child.matches(selector) ? [child] : []), ...child.querySelectorAll(selector),
    ]);
  }
  querySelector(selector) { return this.querySelectorAll(selector)[0] || null; }
}

function renderFixture(items, health = {}, options = {}) {
  const body = new Element("body");
  const head = new Element("head");
  const document = {
    body, head,
    addEventListener() {}, removeEventListener() {},
    createElement: (tag) => new Element(tag),
    getElementById: (id) => body.querySelector(`#${id}`) || head.querySelector(`#${id}`),
    querySelectorAll: (selector) => [...body.querySelectorAll(selector), ...head.querySelectorAll(selector)],
    querySelector(selector) { return this.querySelectorAll(selector)[0] || null; },
  };
  for (const id of [
    "notif-bell", "notif-badge", "notif-trigger-label", "notif-summary",
    "notif-subscription-count", "notif-list", "notif-refresh", "notif-dropdown", "notif-feedback", "notif-close", "notif-library",
  ]) {
    const element = new Element();
    element.id = id;
    body.append(element);
  }
  for (const filter of ["all", "new", "queued", "downloaded", "issue"]) {
    const button = new Element("button");
    button.dataset.notifFilter = filter;
    const label = new Element("span");
    label.className = "notif-filter-label";
    label.textContent = filter;
    const count = new Element("span");
    count.className = "notif-filter-count";
    button.append(label, count);
    body.append(button);
  }
  const calls = { signals: [], read: [], checks: [], opened: [], applied: [], refreshed: 0 };
  const state = { wl: { items, health, notifFilter: "all", checkRunning: false } };
  body.ownerDocument = document;
  const controller = createNotifications(body, {
    getSnapshot: () => state.wl,
    getSnapshotVersion: options.getSnapshotVersion,
    subscriptionMonogram: title => title.slice(0, 2), libraryCheckedLabel: () => "Gerade geprüft",
    coverUrl: url => url, openLibrary() {}, openEntry: slug => calls.opened.push(slug),
    onSnapshot: data => calls.applied.push(data),
    requests: {
      async acknowledge(entry, signal) {
        calls.signals.push(signal);
        if (options.ackWait) await options.ackWait;
        const receipt = entry.last_unread_downloaded_episode || entry.last_downloaded_episode;
        calls.read.push([entry.base_slug, Number(receipt?.downloaded_at || 0)]);
        if (options.readError) throw options.readError;
        return { watchlist: [], health };
      },
      async snapshot() { calls.refreshed++; options.snapshotStarted?.(); if (options.snapshotWait) await options.snapshotWait; return { watchlist: items, health }; },
    },
    check: async slugs => {
      calls.checks.push(slugs);
      if (options.checkError) throw options.checkError;
      return { watchlist: items, health };
    },
  });
  controller.mount();
  const inbox = { ...model, renderNotifBell() { controller.open(); controller.refresh(); } };
  return { inbox, document, state, calls, controller };
}

test("rendered counters match filter contents and global errors remain visible beside other notices", () => {
  const fixture = renderFixture([
    subscription("mixed", { open_count: 4, new_count: 6, queued_count: 2, downloaded_count: 1, failed_count: 4 }),
    subscription("queue-only", { open_count: 0, queued_count: 1 }),
    subscription("current"),
  ], { error: "Global probe failed" });
  const { inbox, state, document } = fixture;
  const model = inbox.buildSubscriptionInbox(state.wl.items, state.wl.health);
  for (const filter of ["all", "new", "queued", "downloaded", "issue"]) {
    document.querySelectorAll("[data-notif-filter]").find(button => button.dataset.notifFilter === filter).fire("click");
    inbox.renderNotifBell();
    const list = document.getElementById("notif-list");
    assert.equal(list.querySelectorAll(".notif-item").length, inbox.inboxEntriesForFilter(model, filter).length, filter);
    assert.equal(list.textContent.includes("Global probe failed"), filter === "all" || filter === "issue", filter);
    assert.equal(document.getElementById("notif-stats"), null);
    for (const button of document.querySelectorAll("[data-notif-filter]")) {
      assert.equal(button.querySelector(".notif-filter-count").textContent, String(model.counts[button.dataset.notifFilter]));
      assert.equal(button.getAttribute("aria-pressed"), String(filter === button.dataset.notifFilter));
    }
  }
});

test("header badge only signals real problems, not passive inbox entries", () => {
  const passive = renderFixture([
    subscription("language", { waiting_language_count: 8, status: "waiting_for_language" }),
    subscription("source", { waiting_release_count: 2, status: "waiting_release" }),
    subscription("upcoming", { upcoming_count: 3 }),
    subscription("downloaded", { downloaded_count: 5 }),
  ]);
  passive.inbox.renderNotifBell();

  const passiveBell = passive.document.getElementById("notif-bell");
  const passiveBadge = passive.document.getElementById("notif-badge");
  assert.equal(passiveBadge.textContent, "0");
  assert.ok(passiveBadge.classList.contains("hidden"));
  assert.ok(!passiveBell.classList.contains("is-active"));
  assert.equal(passive.document.getElementById("notif-trigger-label").textContent, "Alles aktuell");
  assert.equal(passive.document.getElementById("notif-summary").textContent, "4 Einträge");

  const attention = renderFixture([
    subscription("problem-one", { failed_count: 1, status: "failed" }),
    subscription("problem-two", { cleanup_last_error: "permission denied" }),
    subscription("downloaded", { downloaded_count: 1 }),
  ]);
  attention.inbox.renderNotifBell();

  const attentionBell = attention.document.getElementById("notif-bell");
  const attentionBadge = attention.document.getElementById("notif-badge");
  assert.equal(attentionBadge.textContent, "2");
  assert.ok(!attentionBadge.classList.contains("hidden"));
  assert.ok(attentionBell.classList.contains("is-active"));
  assert.equal(attention.document.getElementById("notif-trigger-label").textContent, "2 Probleme");
  assert.equal(attention.document.getElementById("notif-summary").textContent, "3 Einträge");
  assert.ok(attention.document.getElementById("notif-issue-badge").classList.contains("hidden"));
});


test("opening a mixed-state row navigates without implicitly acknowledging download receipts", async () => {
  const { inbox, document, calls } = renderFixture([
    subscription("mixed", { open_count: 2, new_count: 2, downloaded_count: 1, failed_count: 1 }),
  ]);
  inbox.renderNotifBell();
  const row = document.getElementById("notif-list").querySelector(".notif-item");
  await row.querySelector(".notif-item-open").fire("click");
  assert.deepEqual(calls.opened, ["mixed"]);
  assert.deepEqual(calls.read, []);
});

test("explicitly marking a mixed row read uses its unread timestamp and fetches a fresh snapshot", async () => {
  const { inbox, document, calls } = renderFixture([
    subscription("mixed", {
      open_count: 2, new_count: 2, downloaded_count: 1, failed_count: 1,
      last_downloaded_episode: { season: 1, episode: 5, downloaded_at: 900 },
      last_unread_downloaded_episode: { season: 1, episode: 4, downloaded_at: 123 },
    }),
  ]);
  inbox.renderNotifBell();
  const button = document.getElementById("notif-list").querySelector(".notif-item-read");
  assert.ok(button, "mixed states must retain the explicit read action");
  await button.fire("click");
  assert.deepEqual(calls.read, [["mixed", 123]]);
  assert.equal(calls.refreshed, 1);
  assert.equal(calls.applied.length, 1, "apply only the freshly fetched snapshot");
  assert.equal(calls.applied[0].watchlist[0].base_slug, "mixed");
  assert.equal(button.disabled, false);
});

test("a failed read acknowledgement restores the action and displays the failure", async () => {
  const { inbox, document, calls } = renderFixture([
    subscription("download", { downloaded_count: 1 }),
  ], {}, { readError: new Error("Quittierung fehlgeschlagen") });
  inbox.renderNotifBell();
  const button = document.getElementById("notif-list").querySelector(".notif-item-read");
  await button.fire("click");
  assert.equal(button.disabled, false);
  assert.equal(calls.refreshed, 0);
  assert.equal(calls.applied.length, 0);
  assert.match(document.body.textContent, /Quittierung fehlgeschlagen/);
});

test("a single subscription check uses that row's slug and restores the button", async () => {
  const { inbox, document, calls } = renderFixture([
    subscription("check-me", { failed_count: 1 }),
  ]);
  inbox.renderNotifBell();
  const button = document.getElementById("notif-list").querySelector(".notif-item-check");
  await button.fire("click");
  assert.deepEqual(plain(calls.checks), [["check-me"]]);
  assert.equal(button.disabled, false);
});

test("a failed subscription check displays the error and restores the button", async () => {
  const { inbox, document } = renderFixture([
    subscription("check-me", { failed_count: 1 }),
  ], {}, { checkError: new Error("Quelle nicht erreichbar") });
  inbox.renderNotifBell();
  const button = document.getElementById("notif-list").querySelector(".notif-item-check");
  await button.fire("click");
  assert.equal(button.disabled, false);
  assert.match(document.body.textContent, /Quelle nicht erreichbar/);
});


test("closing the inbox aborts read work and prevents a late follow-up snapshot", async () => {
  let resolve;
  const ackWait = new Promise(done => { resolve = done; });
  const { controller, inbox, document, calls } = renderFixture([subscription("slow", { downloaded_count: 1 })], {}, { ackWait });
  inbox.renderNotifBell();
  const pending = document.getElementById("notif-list").querySelector(".notif-item-read").fire("click");
  controller.close();
  assert.equal(calls.signals[0].aborted, true);
  resolve(); await pending;
  assert.equal(calls.refreshed, 0);
  assert.equal(calls.applied.length, 0);
});

test("repeated shell mounts and unmounts preserve one bell listener", () => {
  const { controller, document } = renderFixture([]);
  for (let i = 0; i < 3; i++) { controller.unmount(); controller.mount(); controller.mount(); }
  assert.equal(document.getElementById("notif-bell").listeners.click.length, 1);
  controller.unmount();
  assert.equal(document.getElementById("notif-bell").listeners.click.length, 0);
});


test("a newer live snapshot wins over a pending acknowledgement refresh", async () => {
  let finish, started, revision = 0;
  const snapshotWait = new Promise(resolve => { finish = resolve; });
  const requested = new Promise(resolve => { started = resolve; });
  const { inbox, document, calls } = renderFixture([subscription("live", { downloaded_count: 1 })], {}, {
    snapshotWait, snapshotStarted: started, getSnapshotVersion: () => revision,
  });
  inbox.renderNotifBell();
  const pending = document.getElementById("notif-list").querySelector(".notif-item-read").fire("click");
  await requested;
  revision++;
  finish(); await pending;
  assert.equal(calls.refreshed, 1);
  assert.equal(calls.applied.length, 0);
});
