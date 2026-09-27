import test from 'node:test';
import assert from 'node:assert/strict';
import { carouselBuffer, carouselPhase, carouselPosition, carouselWrap } from '../../web/js/shared/components/carousel-geometry.js';
import { edgeResidual } from './visual-diff.cjs';

test('bounded clone zones contain an equivalent viewport at both physical edges', () => {
  for (const count of [2, 3, 16, 24, 100]) for (const width of [378, 756, 1370, 2560]) {
    const stride = 233;
    const buffer = carouselBuffer(count, width, stride);
    const size = count * stride;
    const maximum = (count + 2 * buffer) * stride - width;
    for (const position of [0, 1, maximum - 1, maximum]) {
      const wrapped = carouselWrap(position, size, maximum);
      assert.ok(wrapped >= 0 && wrapped <= maximum);
      assert.ok(Math.abs(carouselPhase(position, buffer, stride, count)
        - carouselPhase(wrapped, buffer, stride, count)) < 1e-9);
    }
    assert.equal(carouselWrap(maximum / 2, size, maximum), maximum / 2);
  }
});

test('buffer depends on viewport rather than catalog size', () => {
  assert.equal(carouselBuffer(16, 378, 299), 2);
  assert.equal(carouselBuffer(16, 1370, 233), 4);
  assert.equal(carouselBuffer(100, 1370, 233), 4);
  assert.equal(carouselBuffer(1, 1370, 233), 0);
  assert.equal(carouselBuffer(16, 0, 0), 0);
});

test('resizing represents every phase without clamping away titles at a wide viewport edge', () => {
  for (const count of [2, 3, 16, 100]) for (const width of [378, 1370, 4000]) {
    const stride = 233, leading = carouselBuffer(count, width, stride);
    const maximum = (count + 2 * leading) * stride - width;
    for (let phase = 0; phase < count; phase += 0.25) {
      const position = carouselPosition(phase, leading, stride, count, maximum);
      assert.ok(position >= 0 && position <= maximum);
      assert.ok(Math.abs(carouselPhase(position, leading, stride, count) - phase) < 1e-9);
    }
  }
});

test('visual edge tolerance cannot hide a changed fill or removed component', () => {
  const bitmap = fn => ({ width: 20, height: 20, data: Uint8Array.from({ length: 1600 }, (_, i) => {
    if (i % 4 === 3) return 255;
    return fn(Math.floor(i / 4) % 20, Math.floor(i / 80));
  }) });
  const mask = bitmap(() => 255), dark = bitmap(() => 0), bright = bitmap(() => 255);
  const card = bitmap((x, y) => x >= 4 && x <= 14 && y >= 4 && y <= 14 ? 255 : 0);
  const shifted = bitmap((x, y) => x >= 5 && x <= 15 && y >= 4 && y <= 14 ? 255 : 0);
  assert.equal(edgeResidual(dark, bright, mask, 1), 1, 'changed background fails');
  assert.ok(edgeResidual(card, dark, mask, 1) > 0.2, 'missing component fails');
  assert.equal(edgeResidual(card, shifted, mask, 1), 0, 'one-pixel raster offset is tolerated');
});
