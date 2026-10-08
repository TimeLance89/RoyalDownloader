const compareEpisodes = (left, right) => Number(left.season || 0) - Number(right.season || 0)
  || Number(left.episode || 0) - Number(right.episode || 0);

function chunks(episodes, size) {
  const result = [];
  for (let index = 0; index < episodes.length; index += size) result.push(episodes.slice(index, index + size));
  return result;
}

/** Order probes only; source availability and download eligibility remain independent. */
export function episodeLanguageBatches(series, episodes, size = 4) {
  const pending = [...new Map(episodes.map(episode => [episode.slug, episode])).values()].sort(compareEpisodes);
  const owned = (series.seasons || []).flatMap(season => season.episodes || [])
    .filter(episode => episode.downloaded === true || episode.in_jellyfin === true);
  const anchor = Math.max(0, ...owned.map(episode => Number(episode.season || 0)));
  if (!anchor) {
    const unknown = series.availability_pending || (series.jellyfin_configured
      && (series.jellyfin_pending || series.jellyfin_available !== true || series.jellyfin_stale));
    // No positive inventory evidence during an outage is not an empty library.
    if (unknown) pending.sort((left, right) => Number(right.season || 0) - Number(left.season || 0)
      || Number(left.episode || 0) - Number(right.episode || 0));
    return chunks(pending, size);
  }
  const continuation = chunks(pending.filter(episode => Number(episode.season || 0) >= anchor), size);
  const gaps = chunks(pending.filter(episode => Number(episode.season || 0) < anchor), size);
  const result = [];
  let next = 0, gap = 0;
  // Two continuation batches, then one old gap: both lanes make bounded progress.
  while (next < continuation.length || gap < gaps.length) {
    for (let count = 0; count < 2 && next < continuation.length; count++) result.push(continuation[next++]);
    if (gap < gaps.length) result.push(gaps[gap++]);
  }
  return result;
}
