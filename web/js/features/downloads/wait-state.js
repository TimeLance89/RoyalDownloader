function relativeRetryLabel(targetAt, nowSeconds, { longTerm = false, noun = "Versuch" } = {}) {
  const target = Number(targetAt);
  if (!Number.isFinite(target) || target <= 0) return "";
  const remaining = Math.max(0, target - Number(nowSeconds || 0));
  const minutes = Math.max(1, Math.ceil(remaining / 60));

  if (longTerm || minutes >= 24 * 60) {
    const days = Math.max(1, Math.ceil(minutes / (24 * 60)));
    return `Langzeitprüfung in ~${days} ${days === 1 ? "Tag" : "Tagen"}`;
  }
  if (minutes >= 60) {
    const hours = Math.ceil(minutes / 60);
    return `Nächster ${noun} in ~${hours} Std.`;
  }
  return `Nächster ${noun} in ~${minutes} Min.`;
}

export function queueWaitCopy(job, nowSeconds = Date.now() / 1000) {
  const status = String(job?.job_status || job?.status || "");
  if (status !== "waiting_provider") return "";

  if (job?.wait_reason === "source_unavailable") {
    const longTerm = /langzeitprüfung/i.test(String(job?.error || ""));
    const timing = relativeRetryLabel(job?.next_retry_at, nowSeconds, { longTerm });
    return ["Wartet auf Quelle", timing || "Automatische Prüfung vorgemerkt"]
      .filter(Boolean)
      .join(" · ");
  }

  const nextProbe = Number(job?.next_probe_at) || Number(job?.next_retry_at);
  const timing = relativeRetryLabel(nextProbe, nowSeconds, { noun: "Test" });
  return ["Provider vorübergehend pausiert", timing || "Automatischer Test vorgemerkt"]
    .filter(Boolean)
    .join(" · ");
}
