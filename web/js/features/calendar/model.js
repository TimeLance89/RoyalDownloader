export function calendarDate(value) {
  return new Date(`${value}T12:00:00`);
}

export function calendarDateKey(date) {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

export function calendarTodayKey() {
  return calendarDateKey(new Date());
}

export function calendarSnapshotEntry(item, date) {
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
    subscribed: Boolean(item.subscribed),
  };
}

export function calendarNormalizeSnapshotPayload(payload) {
  if (!payload || typeof payload !== "object" || !Array.isArray(payload.days)) {
    throw new Error("Der Sendeplan enthält keine gültigen Daten.");
  }
  let total = 0;
  const days = payload.days.flatMap((day) => {
    const date = String(day?.date || "");
    if (!/^\d{4}-\d{2}-\d{2}$/.test(date) || calendarDateKey(calendarDate(date)) !== date || !Array.isArray(day.entries)) return [];
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

export function calendarWeekKey(value) {
  const date = typeof value === "string" ? calendarDate(value) : new Date(value);
  const day = date.getDay() || 7;
  date.setDate(date.getDate() - day + 1);
  return calendarDateKey(date);
}

export function calendarWeekDates(weekKey) {
  const monday = calendarDate(weekKey);
  return Array.from({ length: 7 }, (_, index) => {
    const date = new Date(monday);
    date.setDate(monday.getDate() + index);
    return calendarDateKey(date);
  });
}
