import test from 'node:test';
import assert from 'node:assert/strict';
import { carouselBuffer, carouselPhase, carouselWrap } from '../../web/js/shared/components/carousel-geometry.js';

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
