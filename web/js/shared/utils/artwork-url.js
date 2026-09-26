/** Artwork URL policy is presentation logic; HTTP transport remains in core/api.js. */
export function createArtworkUrls(origin) {
  return {
  _upgradeTmdbImageUrl(url) {
    const parsed = new URL(url, origin);
    if (parsed.protocol !== "https:" || parsed.hostname !== "image.tmdb.org") return parsed;
    parsed.pathname = parsed.pathname
      .replace(/^\/t\/p\/w500\//, "/t/p/w780/")
      .replace(/^\/t\/p\/w1280\//, "/t/p/original/");
    return parsed;
  },

  coverUrl(url) {
    if (!url) return "";
    try {
      const parsed = this._upgradeTmdbImageUrl(url);
      if (parsed.origin === origin) return parsed.href;
      if (parsed.protocol === "https:" && parsed.hostname === "image.tmdb.org") return parsed.href;
      if (parsed.protocol !== "http:" && parsed.protocol !== "https:") return "";
      url = parsed.href;
    } catch (e) { return ""; }
    return "/api/cover?" + new URLSearchParams({ url });
  },

  coverProxyUrl(url) {
    if (!url) return "";
    try {
      const parsed = this._upgradeTmdbImageUrl(url);
      if (parsed.origin === origin) return parsed.href;
      if (parsed.protocol !== "http:" && parsed.protocol !== "https:") return "";
      return "/api/cover?" + new URLSearchParams({ url: parsed.href });
    } catch (e) { return ""; }
  },

  coverCandidates(url) {
    return [...new Set([this.coverUrl(url), this.coverProxyUrl(url)].filter(Boolean))];
  },

  coverThumbnailCandidates(url) {
    if (!url) return [];
    try {
      const parsed = new URL(url, origin);
      if (parsed.protocol === "https:" && parsed.hostname === "image.tmdb.org") {
        parsed.pathname = parsed.pathname.replace(/^\/t\/p\/(?:w\d+|original)\//, "/t/p/w500/");
        const direct = parsed.href;
        return [...new Set([direct, "/api/cover?" + new URLSearchParams({ url: direct })])];
      }
    } catch (e) { return []; }
    return this.coverCandidates(url);
  },
  };
}
