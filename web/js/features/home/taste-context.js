/** Home-only aggregate interpretation, matching features/home_taste.py. */
import { memoHomeRender } from "./render-pass.js";
const contexts = Symbol("home-taste-contexts");
export function homeTasteContext(profile, kind) {
  const cache = memoHomeRender(contexts, () => new WeakMap());
  if (!cache.has(profile)) cache.set(profile, new Map());
  if (cache.get(profile).has(kind)) return cache.get(profile).get(kind);
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
  const result = { ...profile, dimensions };
  cache.get(profile).set(kind, result);
  return result;
}

const lookups = Symbol("home-taste-lookups");
export function homeTasteLookup(profile, dimension) {
  const cache = memoHomeRender(lookups, () => new WeakMap());
  if (!cache.has(profile)) cache.set(profile, new Map());
  const axes = cache.get(profile);
  if (!axes.has(dimension)) {
    const lookup = new Map();
    for (const [name, raw] of Object.entries(profile.dimensions?.[dimension] || {})) {
      const score = Number(raw);
      if (Number.isFinite(score)) lookup.set(name.toLocaleLowerCase(), { name, score });
    }
    axes.set(dimension, lookup);
  }
  return axes.get(dimension);
}
