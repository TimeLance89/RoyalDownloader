/** Browser download tickets stay same-origin and are bound to the active RDM session. */

export async function prepareBrowserDownloads(client, slugs, preferences = {}, options = {}) {
  const unique = [...new Set(
    (slugs || []).map(value => String(value || "").trim()).filter(Boolean),
  )];
  if (!unique.length) throw new Error("Keine herunterladbaren Inhalte ausgewählt.");
  return client.post(
    "/api/browser-download/prepare",
    { slugs: unique, preferences },
    { ...options, timeoutMs: options.timeoutMs ?? 20_000 },
  );
}

export function triggerBrowserDownloads(downloads, documentRef = document) {
  const valid = (downloads || []).filter(item => item?.url);
  valid.forEach((item, index) => {
    window.setTimeout(() => {
      const anchor = documentRef.createElement("a");
      anchor.href = item.url;
      anchor.rel = "nofollow";
      anchor.style.display = "none";
      documentRef.body.appendChild(anchor);
      anchor.click();
      window.setTimeout(() => anchor.remove(), 2_000);
    }, index * 300);
  });
  return valid.length;
}

export function formatDownloadQuota(bytes) {
  const value = Math.max(0, Number(bytes || 0));
  if (value >= 1024 ** 3) {
    return `${(value / 1024 ** 3).toLocaleString("de-DE", { maximumFractionDigits: 1 })} GB`;
  }
  if (value >= 1024 ** 2) {
    return `${(value / 1024 ** 2).toLocaleString("de-DE", { maximumFractionDigits: 1 })} MB`;
  }
  if (value >= 1024) {
    return `${(value / 1024).toLocaleString("de-DE", { maximumFractionDigits: 1 })} KB`;
  }
  return `${value.toLocaleString("de-DE")} B`;
}

export function announceBrowserDownloadStart(detail = {}) {
  window.dispatchEvent(new CustomEvent("royal:browser-download-started", { detail }));
}
