/** Combined clone zones cover one viewport plus two card strides of reserve.
 * All originals remain in the DOM; copies only bridge the circular seam. */
export function carouselBuffer(count, width, stride) {
  if (count < 2 || !(stride > 0) || !(width > 0)) return 0;
  return Math.ceil((Math.ceil(width / stride) + 2) / 2);
}

export function carouselPhase(position, leading, stride, count) {
  if (!(stride > 0) || !count) return 0;
  return (((position / stride - leading) % count) + count) % count;
}

export function carouselPosition(phase, leading, stride, count, maximum) {
  const size = stride * count;
  if (!(size > 0)) return 0;
  let position = (leading + phase) * stride;
  if (position > maximum) position -= Math.ceil((position - maximum) / size) * size;
  if (position < 0) position += Math.ceil(-position / size) * size;
  return Math.max(0, Math.min(position, maximum));
}

/** An equivalent position must fit in the physical scroll range in its entirety. */
export function carouselWrap(position, size, maximum) {
  const overlap = maximum - size;
  if (!(size > 0) || overlap <= 2) return position;
  const guard = Math.min(32, overlap / 3);
  if (position < guard) return position + size;
  if (position > maximum - guard) return position - size;
  return position;
}
