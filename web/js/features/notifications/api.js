import { api } from "../../core/api.js";

export const notificationApi = {
  acknowledge(entry, signal) {
    const receipt = entry.last_unread_downloaded_episode || entry.last_downloaded_episode;
    const cutoff = Number(receipt?.downloaded_at || 0);
    return api.post("/api/watchlist/downloads/read", {
      base_slug: entry.base_slug,
      downloaded_before: Number.isFinite(cutoff) && cutoff > 0 ? cutoff : 0,
    }, { signal });
  },
  snapshot: signal => api.get("/api/watchlist", { signal }),
};
