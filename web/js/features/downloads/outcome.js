export function queueAddFailureReason(response, slugs = []) {
  if (Number(response?.added || 0) > 0) return "";
  const requested = Array.isArray(slugs) ? slugs : [slugs];
  const details = response?.skipped_details;
  const reasons = [...new Set(requested.map((slug) => {
    const reason = details && typeof details === "object" ? details[slug] : "";
    return typeof reason === "string" ? reason.trim() : "";
  }).filter(Boolean))];
  if (reasons.length) return reasons.join(" · ");
  return Number(response?.skipped || 0) > 0
    ? "Der Inhalt wurde vom Server nicht eingeplant."
    : "Der Server hat keinen Download eingeplant.";
}
