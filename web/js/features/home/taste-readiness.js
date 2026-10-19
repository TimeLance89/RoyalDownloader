/** Home-only cold-start readiness. Profile confidence is not a probability of taste fit. */
export function homeTasteReady(profile) {
  if (Number(profile?.interactions || 0) < 2) return false;
  if (Number(profile?.confidence || 0) >= 0.18) return true;
  // Five onboarding favorites can strongly define a genre even though their
  // low evidence count has not reached the global profile confidence threshold.
  // Only descriptive axes count: "movie" alone is not a learned preference.
  const dimensions = profile?.dimensions || {};
  const positive = ["genres", "directors", "actors", "tags", "franchises"]
    .flatMap((axis) => Object.values(dimensions[axis] || {}))
    .map(Number)
    .filter((score) => Number.isFinite(score) && score >= 1.5);
  return positive.length > 0;
}
