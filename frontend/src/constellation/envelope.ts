/** A lumpy union of member disks and thin minimum-spanning-tree tubes.
 * This is a display envelope, never a test of hyperedge membership.
 */
export type Point = { x: number; y: number };
export function bubbleEnvelope(points: readonly Point[], radius = 17, grid = 5): { path: string; rings: Point[][] } {
  if (!points.length) return { path: '', rings: [] };
  const minX = Math.floor((Math.min(...points.map(p => p.x)) - radius * 2) / grid) * grid;
  const minY = Math.floor((Math.min(...points.map(p => p.y)) - radius * 2) / grid) * grid;
  const cols = Math.ceil((Math.max(...points.map(p => p.x)) + radius * 2 - minX) / grid) + 1;
  const rows = Math.ceil((Math.max(...points.map(p => p.y)) + radius * 2 - minY) / grid) + 1;
  const field = new Uint8Array(cols * rows);
  function disk(x: number, y: number, r: number) {
    const cx = (x - minX) / grid, cy = (y - minY) / grid, gr = r / grid;
    for (let yy = Math.max(0, Math.floor(cy - gr)); yy <= Math.min(rows - 1, Math.ceil(cy + gr)); yy++)
      for (let xx = Math.max(0, Math.floor(cx - gr)); xx <= Math.min(cols - 1, Math.ceil(cx + gr)); xx++)
        if ((xx - cx) ** 2 + (yy - cy) ** 2 <= gr ** 2) field[yy * cols + xx] = 1;
  }
  points.forEach(p => disk(p.x, p.y, radius));
  const visited = new Uint8Array(points.length), distances = new Float64Array(points.length).fill(Infinity), parent = new Int32Array(points.length).fill(-1);
  distances[0] = 0;
  for (let step = 0; step < points.length; step++) {
    let next = -1;
    for (let i = 0; i < points.length; i++) if (!visited[i] && (next < 0 || distances[i] < distances[next])) next = i;
    visited[next] = 1;
    if (parent[next] >= 0) {
      const a = points[next], b = points[parent[next]], samples = Math.max(1, Math.ceil(Math.hypot(a.x - b.x, a.y - b.y) / grid));
      for (let j = 0; j <= samples; j++) disk(a.x + (b.x - a.x) * j / samples, a.y + (b.y - a.y) * j / samples, radius * .55);
    }
    for (let i = 0; i < points.length; i++) if (!visited[i]) {
      const d = (points[next].x - points[i].x) ** 2 + (points[next].y - points[i].y) ** 2;
      if (d < distances[i]) { distances[i] = d; parent[i] = next; }
    }
  }
  // Marching squares. Integer half-grid coordinates give identical shared endpoints.
  const edges = new Map<string, string[]>(), coords = new Map<string, Point>();
  const cases: Record<number, number[][]> = { 1: [[3, 0]], 2: [[0, 1]], 3: [[3, 1]], 4: [[1, 2]], 5: [[3, 0], [1, 2]], 6: [[0, 2]], 7: [[3, 2]], 8: [[2, 3]], 9: [[0, 2]], 10: [[0, 1], [2, 3]], 11: [[1, 2]], 12: [[1, 3]], 13: [[0, 1]], 14: [[0, 3]] };
  for (let y = 0; y < rows - 1; y++) for (let x = 0; x < cols - 1; x++) {
    const mask = field[y * cols + x] + 2 * field[y * cols + x + 1] + 4 * field[(y + 1) * cols + x + 1] + 8 * field[(y + 1) * cols + x];
    const mid = [[x * 2 + 1, y * 2], [x * 2 + 2, y * 2 + 1], [x * 2 + 1, y * 2 + 2], [x * 2, y * 2 + 1]];
    for (const [a, b] of cases[mask] || []) {
      const keys = [a, b].map(i => { const [xx, yy] = mid[i], key = `${xx}:${yy}`; coords.set(key, { x: minX + xx * grid / 2, y: minY + yy * grid / 2 }); return key; });
      for (let i = 0; i < 2; i++) { const list = edges.get(keys[i]) || []; list.push(keys[1 - i]); edges.set(keys[i], list); }
    }
  }
  const seen = new Set<string>(), rings: Point[][] = [];
  for (const first of edges.keys()) {
    if (seen.has(first)) continue;
    const ring: Point[] = []; let current = first, previous = '';
    while (!seen.has(current)) { seen.add(current); ring.push(coords.get(current)!); const next = edges.get(current)?.find(key => key !== previous); if (!next) break; previous = current; current = next; }
    if (ring.length >= 4) rings.push(ring);
  }
  const number = (n: number) => n.toFixed(1);
  const path = rings.map(ring => {
    const mids = ring.map((p, i) => ({ x: (p.x + ring[(i + 1) % ring.length].x) / 2, y: (p.y + ring[(i + 1) % ring.length].y) / 2 }));
    return `M${number(mids.at(-1)!.x)},${number(mids.at(-1)!.y)}` + ring.map((p, i) => `Q${number(p.x)},${number(p.y)} ${number(mids[i].x)},${number(mids[i].y)}`).join('') + 'Z';
  }).join('');
  return { path, rings };
}
