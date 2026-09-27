const { readFileSync } = require('node:fs');
const assert = require('node:assert/strict');
const [baselineFile, currentFile] = process.argv.slice(2);
if (!baselineFile || !currentFile) throw new Error('Usage: performance-budget.cjs baseline.json current.json');
const baseline = JSON.parse(readFileSync(baselineFile)).results;
const current = JSON.parse(readFileSync(currentFile)).results;
const median = values => [...values].sort((a, b) => a - b)[Math.floor(values.length / 2)];
for (const name of ['desktop', 'desktop-4x', 'desktop-6x', 'mobile-4x']) {
  const before = baseline.filter(r => r.name === name), after = current.filter(r => r.name === name);
  assert.ok(before.length >= 3 && after.length >= 3, name + ': three independent samples required');
  for (const result of after) {
    assert.deepEqual(result.errors, [], name + ': browser errors');
    assert.equal(result.logicalCards, 97, name + ': unchanged fixture content');
    assert.equal(result.logicalCardsRendered, 97, name + ': every logical title actually rendered');
    assert.ok(result.cards <= median(before.map(r => r.cards)) * 0.6, name + ': at least 40% fewer full cards');
    assert.ok(Math.abs(result.swipeEnd - result.swipeStart) > 20, name + ': working interaction');
  }
  // Compare on the SAME worker/browser. Leave headroom for shared-runner noise;
  // absolute milliseconds, LCP, GC-sensitive memory and SVG decode are not gates.
  const ratios = {};
  for (const metric of ['initialRenderMs', 'layoutMs', 'styleMs', 'scriptMs', 'tbtMs']) {
    const old = median(before.map(r => r[metric])), now = median(after.map(r => r[metric]));
    ratios[metric] = Number((now / old).toFixed(3));
    assert.ok(now <= old * 1.25 + 20, `${name} ${metric}: ${now} exceeds paired baseline ${old}`);
  }
  console.log(JSON.stringify({ name, cards: after[0].cards, logicalCards: 97, ratios }));
}
