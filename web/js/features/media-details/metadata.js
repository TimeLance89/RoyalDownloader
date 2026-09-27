/** Sparse provider/catalog payloads must not erase already known metadata. */
export function mergeDetailMetadata(previous = {}, fresh = {}) {
  const merged = { ...previous };
  for (const [key, value] of Object.entries(fresh || {})) {
    if (value != null && value !== "" && (!Array.isArray(value) || value.length)) merged[key] = value;
  }
  return merged;
}
