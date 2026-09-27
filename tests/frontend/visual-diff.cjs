// Symmetric one-CSS-pixel neighbourhood for fractional raster/antialias edges.
function edgeResidual(a, b, mask, radius) {
  const near = (source, target, x, y) => {
    const at = (y * a.width + x) * 4;
    for (let dy = -radius; dy <= radius; dy++) for (let dx = -radius; dx <= radius; dx++) {
      if (x + dx < 0 || x + dx >= a.width || y + dy < 0 || y + dy >= a.height) continue;
      const other = ((y + dy) * a.width + x + dx) * 4;
      if ([0, 1, 2, 3].every(c => Math.abs(source[at + c] - target[other + c]) <= 40)) return true;
    }
    return false;
  };
  let residual = 0;
  for (let y = 0; y < a.height; y++) for (let x = 0; x < a.width; x++) {
    if (!mask.data[(y * a.width + x) * 4 + 3]) continue;
    if (!near(a.data, b.data, x, y) || !near(b.data, a.data, x, y)) residual++;
  }
  return residual / (a.width * a.height);
}
module.exports = { edgeResidual };
