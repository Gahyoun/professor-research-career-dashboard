/** Rounded convex display boundary. Membership always comes from the edge IDs. */
export function smoothEnvelope(points: readonly { x: number; y: number }[], padding = 22): string {
  if (!points.length) return '';
  const expanded = points.flatMap(point => Array.from({ length: 8 }, (_, i) => ({
    x: point.x + Math.cos(i * Math.PI / 4) * padding,
    y: point.y + Math.sin(i * Math.PI / 4) * padding,
  }))).sort((a, b) => a.x - b.x || a.y - b.y);
  const cross = (a: typeof expanded[number], b: typeof a, c: typeof a) =>
    (b.x - a.x) * (c.y - a.y) - (b.y - a.y) * (c.x - a.x);
  const lower: typeof expanded = [], upper: typeof expanded = [];
  for (const point of expanded) {
    while (lower.length >= 2 && cross(lower.at(-2)!, lower.at(-1)!, point) <= 0) lower.pop();
    lower.push(point);
  }
  for (const point of expanded.toReversed()) {
    while (upper.length >= 2 && cross(upper.at(-2)!, upper.at(-1)!, point) <= 0) upper.pop();
    upper.push(point);
  }
  const hull = [...lower.slice(0, -1), ...upper.slice(0, -1)];
  const corners = hull.map((point, i) => {
    const previous = hull[(i + hull.length - 1) % hull.length], next = hull[(i + 1) % hull.length];
    const a = Math.hypot(previous.x - point.x, previous.y - point.y);
    const b = Math.hypot(next.x - point.x, next.y - point.y);
    const radius = Math.min(padding * .55, a / 3, b / 3);
    return { point, before: { x: point.x + (previous.x - point.x) * radius / a, y: point.y + (previous.y - point.y) * radius / a },
      after: { x: point.x + (next.x - point.x) * radius / b, y: point.y + (next.y - point.y) * radius / b } };
  });
  const xy = (p: { x: number; y: number }) => `${p.x.toFixed(2)},${p.y.toFixed(2)}`;
  return `M${xy(corners[0].before)}` + corners.map(c => `L${xy(c.before)}Q${xy(c.point)} ${xy(c.after)}`).join('') + 'Z';
}
