/** Requested download language is independent of provider capabilities and UI locale. */
export function seriesEpisodeProvider(series) {
  return series?.provider || String(series?.base_slug || "").split(":")[0];
}

export function needsEpisodeLanguageProof(series) {
  return Boolean(series && (["huhu", "serienstream"].includes(seriesEpisodeProvider(series))
    || (series.provider_content_languages || []).filter(Boolean).length > 1));
}

export function seriesDownloadLanguages(series, fallback = []) {
  return [...new Set(series?.enabled_content_languages?.length
    ? series.enabled_content_languages : fallback)].sort();
}

export function episodeLanguageChecked(episode, series, fallback = []) {
  if (episode?.language_checked !== true && episode?.huhu_language_checked !== true) return false;
  const desired = seriesDownloadLanguages(series, fallback);
  const checkedFor = episode?.language_profile;
  return !checkedFor?.length || !desired.length
    || [...new Set(checkedFor)].sort().join(",") === desired.join(",");
}
