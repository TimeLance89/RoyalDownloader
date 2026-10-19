/** Home-only aggregate interpretation, matching features/home_taste.py. */
export function homeTasteContext(profile, kind) {
  const preferences = profile.home_preferences || {};
  const contextual = preferences.by_media_type?.[kind] || {};
  const short = preferences.short_term || {};
  const dimensions = {};
  for (const [axis, values] of Object.entries(profile.dimensions || {})) {
    const local = contextual[axis] || {};
    const recent = short[axis] || {};
    const hasLocal = Object.keys(local).length > 0;
    dimensions[axis] = {};
    for (const name of new Set([...Object.keys(values), ...Object.keys(local), ...Object.keys(recent)])) {
      let base = Number(values[name] || 0);
      if (base >= 0) {
        if (hasLocal) base = 0.25 * base + 0.75 * Number(local[name] || 0);
        if (base >= 0) base += Math.min(3, Math.max(0, Number(recent[name] || 0))) * 0.35;
      }
      dimensions[axis][name] = base;
    }
  }
  return { ...profile, dimensions };
}
