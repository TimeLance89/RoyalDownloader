// Share expensive profile/history reads only during one synchronous Home paint.
// No cross-task, cross-window or persistent cache can retain a stale profile.
let values = null;
export function withHomeRender(render) {
  if (values) return render();
  values = new Map();
  try { return render(); } finally { values = null; }
}
export function memoHomeRender(key, read) {
  if (!values) return read();
  if (!values.has(key)) values.set(key, read());
  return values.get(key);
}
export function invalidateHomeRender(key) { values?.delete(key); }
