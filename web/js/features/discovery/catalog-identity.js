export function cleanMediaCardInitials(title) {
  const words = String(title || "")
    .trim()
    .split(/\s+/)
    .filter((word) => /[\p{L}\p{N}]/u.test(word));
  if (!words.length) return "RD";
  return (words.length === 1
    ? words[0].slice(0, 2)
    : words.slice(0, 2).map((word) => word.match(/[\p{L}\p{N}]/u)?.[0] || "").join(""))
    .toUpperCase();
}

/** Provider identity stays stable while metadata identifies the same media. */
export function createCatalogIdentity({ getMetadata = () => null } = {}) {
  function normalizeCatalogIdentityText(value) {
    return String(value || "")
      .normalize("NFKD")
      .replace(/[\u0300-\u036f]/g, "")
      .toLocaleLowerCase()
      .replace(/&/g, " und ")
      .replace(/[^a-z0-9]+/g, " ")
      .trim()
      .replace(/\s+/g, " ");
  }

  function catalogIdentityView(item) {
    if (!item) return {};
    const slug = String(item.slug || "").trim();
    const metadata = slug ? getMetadata(slug) : null;
    return metadata ? { ...item, ...metadata } : item;
  }

  function catalogMediaYear(item) {
    const identity = catalogIdentityView(item);
    const raw = String(identity?.year || identity?.release_date || identity?.first_air_date || "");
    return raw.match(/\b(?:19|20)\d{2}\b/)?.[0] || "";
  }

  function catalogMediaTitles(item) {
    const identity = catalogIdentityView(item);
    return new Set([
      identity?.title,
      identity?.original_title,
      identity?.original_name,
    ].map(normalizeCatalogIdentityText).filter(Boolean));
  }

  function catalogLogicalMediaMatch(left, right) {
    if (!left || !right) return false;
    const leftIdentity = catalogIdentityView(left);
    const rightIdentity = catalogIdentityView(right);
    const leftTitles = catalogMediaTitles(leftIdentity);
    const rightTitles = catalogMediaTitles(rightIdentity);
    const titleMatches = [...leftTitles].some((title) => rightTitles.has(title));
    const leftSources = new Set([
      ...(leftIdentity.sources || []), ...(leftIdentity.source_providers || []),
    ].map(catalogSourceIdentity).filter(Boolean));
    const sharesSource = [
      ...(rightIdentity.sources || []), ...(rightIdentity.source_providers || []),
    ].map(catalogSourceIdentity).some((source) => leftSources.has(source));
    // Anbieter melden bei Serien teilweise das Jahr der neuesten Staffel statt
    // des Serienstarts. Exakter Titel plus gleiche Quelle ist dennoch eindeutig.
    if (titleMatches && sharesSource) return true;
    const leftTmdb = String(leftIdentity.tmdb_id || "").trim();
    const rightTmdb = String(rightIdentity.tmdb_id || "").trim();
    if (leftTmdb && rightTmdb) return leftTmdb === rightTmdb;

    const leftYear = catalogMediaYear(leftIdentity);
    const rightYear = catalogMediaYear(rightIdentity);
    if (leftYear && rightYear && leftYear !== rightYear) return false;

    if (!titleMatches) return false;

    // With an unknown year, avoid collapsing obvious separate remakes when both
    // records have different explicit TMDB identities. That case was handled
    // above; provider-only records may safely share an exact logical title.
    return true;
  }

  function mergeCatalogArrayValues(left, right, keyFor = (value) => String(value || "")) {
    const merged = [];
    const known = new Set();
    for (const value of [...(Array.isArray(left) ? left : []), ...(Array.isArray(right) ? right : [])]) {
      if (value == null || value === "") continue;
      const key = keyFor(value);
      if (!key || known.has(key)) continue;
      known.add(key);
      merged.push(value);
    }
    return merged;
  }

  function catalogSourceIdentity(source) {
    if (!source || typeof source !== "object") return "";
    return String(source.key || source.provider || source.label || source.url || "").trim().toLocaleLowerCase();
  }

  function mergeCatalogMediaRecord(primary, secondary) {
    const merged = { ...primary };
    const preferSecondaryWhenMissing = [
      "tmdb_id", "original_title", "original_name", "year", "release_date", "first_air_date",
      "cover_url", "backdrop_url", "description", "rating", "vote_count", "content_language",
    ];
    for (const key of preferSecondaryWhenMissing) {
      if ((merged[key] == null || merged[key] === "") && secondary?.[key] != null && secondary[key] !== "") {
        merged[key] = secondary[key];
      }
    }
    if (String(secondary?.description || "").length > String(merged.description || "").length) {
      merged.description = secondary.description;
    }

    merged.genres = mergeCatalogArrayValues(merged.genres, secondary?.genres, (value) => normalizeCatalogIdentityText(value));
    merged.sources = mergeCatalogArrayValues(merged.sources, secondary?.sources, catalogSourceIdentity);
    merged.source_providers = mergeCatalogArrayValues(
      merged.source_providers,
      secondary?.source_providers,
      catalogSourceIdentity,
    );

    const languageValues = [
      ...(Array.isArray(merged.content_languages) ? merged.content_languages : []),
      ...(Array.isArray(secondary?.content_languages) ? secondary.content_languages : []),
      merged.content_language,
      secondary?.content_language,
      ...merged.sources.map((source) => source?.content_language),
      ...merged.source_providers.map((source) => source?.content_language),
    ];
    merged.content_languages = mergeCatalogArrayValues([], languageValues, (value) => String(value || "").toLowerCase());

    if (primary?.in_jellyfin === true || secondary?.in_jellyfin === true) {
      merged.in_jellyfin = true;
      merged.jellyfin_status = "owned";
    } else if (!merged.jellyfin_status && secondary?.jellyfin_status) {
      merged.jellyfin_status = secondary.jellyfin_status;
    }

    // Preserve the first item's slug/base_slug/provider. Provider priority is
    // still meaningful for opening details and fallback order.
    return merged;
  }

  function dedupeCatalogMedia(items) {
    const output = [];
    for (const item of Array.isArray(items) ? items : []) {
      const duplicateIndex = output.findIndex((known) => catalogLogicalMediaMatch(known, item));
      if (duplicateIndex < 0) {
        output.push(item);
        continue;
      }
      output[duplicateIndex] = mergeCatalogMediaRecord(output[duplicateIndex], item);
    }
    return output;
  }

  return { match: catalogLogicalMediaMatch, dedupe: dedupeCatalogMedia };
}
