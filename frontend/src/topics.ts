// Topic alluvial: public index contract, layout and query. Pure functions only so
// the same code renders the full chart, thumbnails, and runs under node:test.

export type TopicEra = { label: string; start: number | null; end: number | null };
export type TopicParent = { from: number; sim: number; from_year: number | null; to_year: number | null };
export type TopicTags = { ko: string[]; en: string[] };
export type TopicNode = { id: number; label: string; size: number; birth_year: number | null; parent: TopicParent | null; keywords: string[]; tags: TopicTags; vector: number[] | null };
export type TopicPaper = { year: number; topic: number; era: number | null; cited: number };
export type TopicRecip = { from_topic: number; to_topic: number; from_year: number; to_year: number; x_year: number };
export type TopicCounts = { source_works: number | null; kept_works: number | null; merged_versions: number | null };
/** One measure on a window transition (bits): estimate, bootstrap 95% CI, null mean ± sd, z. */
export type InfoMeasure = { value: number; ci: [number, number] | null; null: [number, number] | null; z: number | null };
export const INFO_KEYS = ['diverge', 'merge', 'continuity', 'diverge_norm', 'merge_norm'] as const;
export type InfoKey = typeof INFO_KEYS[number];
export type InfoWindow = { start: number; end: number; n: number; diversity: number | null; effective_topics: number | null };
export type InfoTransition = {
  from: [number, number]; to: [number, number]; n_from: number; n_to: number;
  measures: Partial<Record<InfoKey, InfoMeasure>>; nmi: number | null; jsd: number | null;
  birth_share: number; ending_share: number; sparse: boolean;
  /** Topic → topic mass; null = ∅ (birth on the source side, ending on the target side). */
  flows: { from: number | null; to: number | null; mass: number }[];
};
export type InfoFlow = {
  estimator: string; width: number; nullKind: string; nullRuns: number;
  windows: InfoWindow[]; transitions: InfoTransition[];
  summary: Partial<Record<InfoKey | 'nmi' | 'jsd' | 'continuity_excess' | 'birth_share', number>>;
};
export type TopicResearcher = {
  id: string; alias: string | null; subject: string; institution: string | null;
  eras: TopicEra[]; topics: TopicNode[]; papers: TopicPaper[]; recip: TopicRecip[];
  counts: TopicCounts | null; fetched_at: string | null; info: InfoFlow | null;
};
/** One LSA space shared by every researcher; int8 unit vectors. */
export type TopicSemantic = { dims: number; terms: Map<string, Float32Array>; glossary: Map<string, string[]> };
export type TopicIndex = {
  schema: string; source: 'demo' | 'release'; generated_at: string;
  method: Record<string, string>; researchers: TopicResearcher[]; semantic: TopicSemantic | null;
  /** Directory (relative to the index) holding <id>.json info-flow blocks when they are not inline. */
  infoPath: string | null;
};
/** Decrypted in memory after unlock only; never part of the public index. */
export type EncryptedPaperTitles = Record<string, { year: number; topic: number; title: string; venue: string | null; doi: string | null }[]>;

export function validatePaperTitles(raw: unknown): EncryptedPaperTitles {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) throw new Error('Invalid title bundle');
  const out: EncryptedPaperTitles = {};
  for (const [id, rows] of Object.entries(raw as Record<string, unknown>)) {
    if (!Array.isArray(rows)) throw new Error('Invalid title bundle');
    out[id] = rows.filter((row): row is Record<string, unknown> => Boolean(row) && typeof row === 'object')
      .filter(row => typeof row.title === 'string' && typeof row.year === 'number' && typeof row.topic === 'number')
      .map(row => ({ year: row.year as number, topic: row.topic as number, title: row.title as string,
        venue: typeof row.venue === 'string' ? row.venue : null, doi: typeof row.doi === 'string' && /^https:\/\/doi\.org\//.test(row.doi) ? row.doi : null }));
  }
  return out;
}

export const TOPIC_SCHEMA = 'kstem-topic-alluvial/1';
export const TOPIC_PALETTE = ['#3366FF', '#12B5A6', '#F59E0B', '#E5484D', '#8E4EC6', '#0EA5E9', '#65A30D', '#D946EF', '#F97316', '#64748B'];
const OTHER_COLOR = '#A3A9B4';

const num = (value: unknown): number | null => typeof value === 'number' && Number.isFinite(value) ? value : null;
const str = (value: unknown): string | null => typeof value === 'string' && value.trim() ? value : null;

/** "기관 C (2012-16)" → 2012–2016, "기관 A (~2010)" → –2010, "예시대학교 (2020-)" → 2020–. */
export function parseEraLabel(label: string): { start: number | null; end: number | null } {
  const match = label.match(/\((~)?\s*(\d{4})?\s*([-–~])?\s*(\d{2,4})?\s*\)\s*$/);
  if (!match) return { start: null, end: null };
  const [, lead, first, dash, second] = match;
  const firstYear = first ? Number(first) : null;
  let secondYear = second ? Number(second) : null;
  if (secondYear !== null && secondYear < 100 && firstYear !== null) secondYear = Math.floor(firstYear / 100) * 100 + secondYear;
  if (lead) return { start: null, end: firstYear ?? secondYear };
  if (dash && !second) return { start: firstYear, end: null };
  return { start: firstYear, end: secondYear ?? firstYear };
}

function normalizeEra(raw: unknown): TopicEra {
  if (typeof raw === 'string') return { label: raw, ...parseEraLabel(raw) };
  const record = (raw || {}) as Record<string, unknown>;
  const label = str(record.label) || '소속 미상';
  const parsed = parseEraLabel(label);
  return { label, start: num(record.start) ?? parsed.start, end: num(record.end) ?? parsed.end };
}

/** Validates the public index. Paper titles are rejected so a mistaken export cannot publish them. */
export function normalizeTopicIndex(raw: unknown): TopicIndex {
  const root = (raw || {}) as Record<string, unknown>;
  if (root.schema !== TOPIC_SCHEMA) throw new Error(`Unsupported topic schema: ${String(root.schema)}`);
  if (!Array.isArray(root.researchers)) throw new Error('Topic index has no researchers');
  const researchers = root.researchers.map((entry): TopicResearcher => {
    const r = (entry || {}) as Record<string, unknown>;
    const id = str(r.id);
    if (!id) throw new Error('Topic researcher without id');
    const topics = (Array.isArray(r.topics) ? r.topics : []).map((value): TopicNode => {
      const t = (value || {}) as Record<string, unknown>;
      const parent = t.parent && typeof t.parent === 'object' ? t.parent as Record<string, unknown> : null;
      const tags = (t.tags || {}) as Record<string, unknown>;
      const strings = (value: unknown) => Array.isArray(value) ? value.filter((x): x is string => typeof x === 'string' && Boolean(x.trim())) : [];
      const vector = Array.isArray(t.vector) && t.vector.every(v => typeof v === 'number') ? t.vector as number[] : null;
      return {
        id: num(t.id) ?? -1, label: str(t.label) || `T${String(t.id)}`, size: num(t.size) ?? 0, birth_year: num(t.birth_year),
        parent: parent && num(parent.from) !== null ? { from: num(parent.from)!, sim: num(parent.sim) ?? 0, from_year: num(parent.from_year), to_year: num(parent.to_year) } : null,
        keywords: strings(t.keywords), tags: { ko: strings(tags.ko), en: strings(tags.en) }, vector,
      };
    }).filter(t => t.id >= 0);
    const topicIds = new Set(topics.map(t => t.id));
    const papers = (Array.isArray(r.papers) ? r.papers : []).map((value): TopicPaper | null => {
      const p = (value || {}) as Record<string, unknown>;
      if ('title' in p || 'doi' in p) throw new Error(`Public topic index for ${id} contains paper titles`);
      const year = num(p.year), topic = num(p.topic);
      return year !== null && topic !== null && topicIds.has(topic) ? { year, topic, era: num(p.era), cited: num(p.cited) ?? 0 } : null;
    }).filter((p): p is TopicPaper => p !== null).sort((a, b) => a.year - b.year);
    const recip = (Array.isArray(r.recip) ? r.recip : []).map((value): TopicRecip | null => {
      const x = (value || {}) as Record<string, unknown>;
      const values = [num(x.from_topic), num(x.to_topic), num(x.from_year), num(x.to_year), num(x.x_year)];
      if (values.some(v => v === null) || !topicIds.has(values[0]!) || !topicIds.has(values[1]!)) return null;
      return { from_topic: values[0]!, to_topic: values[1]!, from_year: values[2]!, to_year: values[3]!, x_year: values[4]! };
    }).filter((x): x is TopicRecip => x !== null);
    const counts = r.counts && typeof r.counts === 'object' ? r.counts as Record<string, unknown> : null;
    return {
      id, alias: str(r.alias), subject: str(r.subject) || 'unknown', institution: str(r.institution),
      eras: (Array.isArray(r.eras) ? r.eras : []).map(normalizeEra), topics, papers, recip,
      counts: counts ? { source_works: num(counts.source_works), kept_works: num(counts.kept_works), merged_versions: num(counts.merged_versions) } : null,
      fetched_at: str(r.fetched_at), info: normalizeInfoFlow(r.info, topicIds),
    };
  });
  return {
    schema: TOPIC_SCHEMA, source: root.source === 'release' ? 'release' : 'demo', generated_at: str(root.generated_at) || '',
    method: Object.fromEntries(Object.entries((root.method || {}) as Record<string, unknown>).filter(([, v]) => typeof v === 'string')) as Record<string, string>,
    researchers, semantic: normalizeSemantic(root.semantic),
    infoPath: typeof root.info_path === 'string' && /^[a-z0-9_-]+$/i.test(root.info_path) ? root.info_path : null,
  };
}

const pair = (value: unknown): [number, number] | null =>
  Array.isArray(value) && value.length === 2 && num(value[0]) !== null && num(value[1]) !== null ? [value[0] as number, value[1] as number] : null;

/** info_flow.py output → typed block; transitions with unknown topics or bad windows are dropped. */
export function normalizeInfoFlow(raw: unknown, topicIds: Set<number>): InfoFlow | null {
  const block = raw && typeof raw === 'object' ? raw as Record<string, unknown> : null;
  if (!block || !Array.isArray(block.transitions)) return null;
  const nullBlock = (block.null || {}) as Record<string, unknown>;
  const windows = (Array.isArray(block.windows) ? block.windows : []).map((value): InfoWindow | null => {
    const w = (value || {}) as Record<string, unknown>;
    const start = num(w.start), end = num(w.end);
    return start !== null && end !== null ? { start, end, n: num(w.n) ?? 0, diversity: num(w.diversity), effective_topics: num(w.effective_topics) } : null;
  }).filter((w): w is InfoWindow => w !== null);
  const known = (t: unknown) => t === null || (num(t) !== null && topicIds.has(t as number));
  const transitions = block.transitions.map((value): InfoTransition | null => {
    const t = (value || {}) as Record<string, unknown>;
    const from = pair(t.from), to = pair(t.to);
    if (!from || !to) return null;
    const measures: Partial<Record<InfoKey, InfoMeasure>> = {};
    for (const key of INFO_KEYS) {
      const v = num(t[key]);
      if (v !== null) measures[key] = { value: v, ci: pair(t[`${key}_ci`]), null: pair(t[`${key}_null`]), z: num(t[`${key}_z`]) };
    }
    const flows = (Array.isArray(t.flows) ? t.flows : [])
      .filter((f): f is [number | null, number | null, number] => Array.isArray(f) && f.length === 3 && known(f[0]) && known(f[1]) && num(f[2]) !== null)
      .map(([a, b, mass]) => ({ from: a, to: b, mass }));
    return { from, to, n_from: num(t.n_from) ?? 0, n_to: num(t.n_to) ?? 0, measures, nmi: num(t.nmi), jsd: num(t.jsd),
      birth_share: num(t.birth_share) ?? 0, ending_share: num(t.ending_share) ?? 0, sparse: t.sparse === true, flows };
  }).filter((t): t is InfoTransition => t !== null);
  const summary: InfoFlow['summary'] = {};
  for (const [key, value] of Object.entries((block.summary || {}) as Record<string, unknown>)) {
    const v = num(value);
    if (v !== null && key !== 'transitions') summary[key as keyof InfoFlow['summary']] = v;
  }
  return { estimator: str(block.estimator) || '', width: num(block.width) ?? 0, nullKind: str(nullBlock.kind) || '', nullRuns: num(nullBlock.n) ?? 0,
    windows, transitions, summary };
}

/** Rows a transition's flows into per-topic branching (by source) or merging (by target) entropies, plug-in bits. */
export function conditionalEntropies(flows: InfoTransition['flows'], by: 'from' | 'to'): { topic: number | null; bits: number; mass: number; partners: number }[] {
  const groups = new Map<number | null, Map<number | null, number>>();
  for (const f of flows) {
    const key = by === 'from' ? f.from : f.to, other = by === 'from' ? f.to : f.from;
    const g = groups.get(key) ?? new Map<number | null, number>();
    g.set(other, (g.get(other) ?? 0) + f.mass);
    groups.set(key, g);
  }
  return [...groups].map(([topic, g]) => {
    const masses = [...g.values()].filter(m => m > 0), total = masses.reduce((a, b) => a + b, 0);
    const bits = total ? -masses.reduce((s, m) => s + m / total * Math.log2(m / total), 0) : 0;
    return { topic, bits: Math.max(0, bits), mass: total, partners: masses.length };
  }).sort((a, b) => b.mass - a.mass);
}

function unit(values: ArrayLike<number>): Float32Array {
  const out = Float32Array.from(values);
  const norm = Math.hypot(...out) || 1;
  for (let i = 0; i < out.length; i++) out[i] /= norm;
  return out;
}

function normalizeSemantic(raw: unknown): TopicSemantic | null {
  const block = raw && typeof raw === 'object' ? raw as Record<string, unknown> : null;
  const dims = num(block?.dims);
  if (!block || !dims || !block.terms || typeof block.terms !== 'object') return null;
  const terms = new Map<string, Float32Array>();
  for (const [term, vector] of Object.entries(block.terms as Record<string, unknown>))
    if (Array.isArray(vector) && vector.length === dims) terms.set(term.toLowerCase(), unit(vector as number[]));
  const glossary = new Map<string, string[]>();
  for (const [ko, ens] of Object.entries((block.glossary || {}) as Record<string, unknown>))
    if (Array.isArray(ens)) glossary.set(ko, ens.filter((e): e is string => typeof e === 'string').map(e => e.toLowerCase()));
  return { dims, terms, glossary };
}

export type AlluvialMode = 'year' | 'era';
export type AlluvialColumn = { key: string; label: string; start: number | null; end: number | null };

const byBirth = (a: TopicNode, b: TopicNode) => (a.birth_year ?? 9999) - (b.birth_year ?? 9999) || b.size - a.size || a.id - b.id;
const isOther = (t: TopicNode) => /^\s*(기타|other)\b/i.test(t.label);

/** Depth of each topic in the parent tree (roots 0); cycles and missing parents count as roots. */
export function topicDepths(r: TopicResearcher): Map<number, number> {
  const ids = new Set(r.topics.map(t => t.id));
  const children = new Map<number, TopicNode[]>();
  const roots: TopicNode[] = [];
  for (const t of r.topics) {
    const from = t.parent?.from;
    if (from === undefined || from === t.id || !ids.has(from) || isOther(t)) roots.push(t);
    else children.set(from, [...(children.get(from) || []), t]);
  }
  const depth = new Map<number, number>();
  const walk = (t: TopicNode, d: number) => {
    if (depth.has(t.id)) return;
    depth.set(t.id, d);
    for (const c of (children.get(t.id) || []).sort(byBirth)) walk(c, d + 1);
  };
  for (const t of roots.sort(byBirth)) walk(t, 0);
  for (const t of [...r.topics].sort(byBirth)) walk(t, 0);   // parent cycles: start a new root
  return depth;
}

/** Topic lanes in time-axis tree order: roots (no parent) by birth year then size, each child
 *  depth-first directly under its parent with siblings by birth year; "Other" last. */
export function orderedTopics(r: TopicResearcher): TopicNode[] {
  const order = [...topicDepths(r).keys()];
  const byId = new Map(r.topics.map(t => [t.id, t]));
  const topics = order.map(id => byId.get(id)!);
  return [...topics.filter(t => !isOther(t)), ...topics.filter(isOther)];
}

export function topicColors(r: TopicResearcher): Map<number, string> {
  const colors = new Map<number, string>();
  let next = 0;
  // Birth order, not lane order: a topic keeps its colour when the tree layout moves its lane.
  for (const topic of [...r.topics].sort(byBirth)) colors.set(topic.id, /기타|other/i.test(topic.label) ? OTHER_COLOR : TOPIC_PALETTE[next++ % TOPIC_PALETTE.length]);
  return colors;
}

export function yearRange(r: TopicResearcher): [number, number] | null {
  if (!r.papers.length) return null;
  return [r.papers[0].year, r.papers[r.papers.length - 1].year];
}

export function buildColumns(r: TopicResearcher, mode: AlluvialMode): AlluvialColumn[] {
  if (mode === 'era') return r.eras.map((era, i) => ({ key: `era-${i}`, label: era.label, start: era.start, end: era.end }));
  const range = yearRange(r);
  if (!range) return [];
  return Array.from({ length: range[1] - range[0] + 1 }, (_, i) => ({ key: String(range[0] + i), label: String(range[0] + i), start: range[0] + i, end: range[0] + i }));
}

/** Era index for a year: the latest era whose span contains it (matches branching.py max(era_idx)). */
export function eraOfYear(r: TopicResearcher, year: number): number | null {
  let found: number | null = null;
  r.eras.forEach((era, i) => { if ((era.start === null || era.start <= year) && (era.end === null || year <= era.end)) found = i; });
  return found;
}

function paperColumn(r: TopicResearcher, mode: AlluvialMode, paper: TopicPaper, first: number): number | null {
  if (mode === 'year') return paper.year - first;
  return paper.era ?? eraOfYear(r, paper.year);
}

export type LaneGeometry = { topic: TopicNode; color: string; y: number; height: number; mid: number; counts: number[]; depth: number };
export type AlluvialDot = { topic: number; column: number; x: number; y: number; r: number; count: number; cited: number };
export type AlluvialLayout = {
  width: number; height: number; left: number; top: number; columnWidth: number;
  columns: AlluvialColumn[]; lanes: LaneGeometry[];
  ribbons: { topic: number; d: string; color: string }[];
  dots: AlluvialDot[];
  branches: { from: number; to: number; d: string; sim: number }[];
  births: { topic: number; x: number; y: number; independent: boolean }[];
  /** ``width`` spans the era's years; ``extent`` is the room reserved for its label in that row; ``text`` is the label cut to fit. */
  bands: { label: string; text: string; x: number; width: number; extent: number; row: number }[];
  bandRows: number;
  ticks: { x: number; label: string; major: boolean }[];
  arcs: { from: number; to: number; d: string }[];
  placed: number; unplaced: number;
};
export type LayoutOptions = { columnWidth?: number; unit?: number; left?: number; laneGap?: number; bandHeight?: number; compact?: boolean };

/** Band label metrics at 11px / 600 (.tp-band text): Hangul and CJK ≈ 1em; other glyphs measure
 *  ≈ 5.1px on average in the page font, so 5.6px leaves a margin for wide capitals. */
const BAND_PAD = 8, BAND_GAP = 4, BAND_LABEL_MAX = 300, BAND_LABEL_MIN = 72;
export function bandTextWidth(text: string): number {
  let width = 0;
  for (const ch of text) width += /[ᄀ-ᇿ⺀-鿿가-힯＀-￯]/.test(ch) ? 11 : 5.6;
  return width;
}
/** ``text`` cut to ``max`` px with a trailing ellipsis; the full label stays in the band's <title>. */
export function fitBandText(text: string, max: number): string {
  if (bandTextWidth(text) <= max) return text;
  let out = '', width = bandTextWidth('…');
  for (const ch of text) {
    const w = bandTextWidth(ch);
    if (width + w > max) break;
    out += ch; width += w;
  }
  return out.trim() ? `${out.trimEnd()}…` : '';
}

function smooth(points: [number, number][], reverse: boolean) {
  const seq = reverse ? [...points].reverse() : points;
  return seq.map(([x, y], i) => {
    if (i === 0) return `${reverse ? 'L' : 'M'}${x.toFixed(1)},${y.toFixed(1)}`;
    const [px, py] = seq[i - 1], mx = (px + x) / 2;
    return `C${mx.toFixed(1)},${py.toFixed(1)} ${mx.toFixed(1)},${y.toFixed(1)} ${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(' ');
}

export function layoutAlluvial(r: TopicResearcher, mode: AlluvialMode, options: LayoutOptions = {}): AlluvialLayout {
  const compact = options.compact === true;
  const columns = buildColumns(r, mode);
  const columnWidth = options.columnWidth ?? (mode === 'year' ? 44 : 132);
  const unit = options.unit ?? (compact ? 2 : 9);
  const left = options.left ?? (compact ? 4 : 228);
  const laneGap = options.laneGap ?? (compact ? 3 : 26);
  const bandHeight = options.bandHeight ?? 24;
  const first = yearRange(r)?.[0] ?? 0;
  const colors = topicColors(r);
  const topics = orderedTopics(r);
  const depths = topicDepths(r);
  const x = (column: number) => left + (column + 0.5) * columnWidth;

  // Institution bands are a year-axis feature; the era axis already labels each column.
  // Each band reserves its own width or BAND_LABEL_MIN, whichever is larger, when rows are packed,
  // so a label never runs into the next band in its row. The label then takes the free room up to
  // that next band (or the chart edge, at most BAND_LABEL_MAX) and is cut with an ellipsis past
  // it; the full label stays in <title> and in the era chips above the chart.
  const bands: AlluvialLayout['bands'] = [];
  if (mode === 'year' && !compact && columns.length) {
    const last = first + columns.length - 1;
    const right = left + columns.length * columnWidth + 24;
    const rows: [number, number][][] = [];
    for (const era of r.eras) {
      const start = Math.max(first, era.start ?? first), end = Math.min(last, era.end ?? last);
      if (end < start) continue;
      const bx = x(start - first) - columnWidth / 2 + 1, width = (end - start + 1) * columnWidth - 2;
      const want = Math.max(width, Math.min(BAND_LABEL_MAX, bandTextWidth(era.label) + 2 * BAND_PAD, right - bx));
      const reserve = Math.max(width, Math.min(want, BAND_LABEL_MIN));
      let row = rows.findIndex(items => items.every(([s, e]) => bx + reserve + BAND_GAP <= s || bx >= e + BAND_GAP));
      if (row < 0) { row = rows.length; rows.push([]); }
      rows[row].push([bx, bx + reserve]);
      bands.push({ label: era.label, text: '', x: bx, width, extent: want, row });
    }
    for (const band of bands) {
      const next = Math.min(...bands.filter(b => b.row === band.row && b.x > band.x).map(b => b.x - BAND_GAP));
      band.extent = Math.max(band.width, Math.min(band.extent, next - band.x));
      band.text = fitBandText(band.label, band.extent - 2 * BAND_PAD);
    }
  }
  const bandRows = bands.length ? Math.max(...bands.map(b => b.row)) + 1 : 0;
  const top = compact ? 4 : 12 + bandRows * (bandHeight + 4) + (mode === 'era' ? 44 : 34);

  const counts = new Map<number, number[]>(topics.map(t => [t.id, columns.map(() => 0)]));
  const cited = new Map<number, number[]>(topics.map(t => [t.id, columns.map(() => 0)]));
  let placed = 0, unplaced = 0;
  for (const paper of r.papers) {
    const column = paperColumn(r, mode, paper, first);
    if (column === null || column < 0 || column >= columns.length) { unplaced++; continue; }
    counts.get(paper.topic)![column]++; cited.get(paper.topic)![column] += paper.cited; placed++;
  }

  const lanes: LaneGeometry[] = [];
  let cursor = top;
  for (const topic of topics) {
    const laneCounts = counts.get(topic.id)!;
    const peak = Math.max(0, ...laneCounts);
    if (!peak) continue;
    const height = Math.max(peak * unit, compact ? 2 : 12) + laneGap;
    lanes.push({ topic, color: colors.get(topic.id)!, y: cursor, height, mid: cursor + height / 2, counts: laneCounts, depth: depths.get(topic.id) ?? 0 });
    cursor += height;
  }

  const ribbons: AlluvialLayout['ribbons'] = [], dots: AlluvialDot[] = [], births: AlluvialLayout['births'] = [];
  const firstColumn = new Map<number, number>();
  for (const lane of lanes) {
    const active = lane.counts.flatMap((n, i) => n > 0 ? [i] : []);
    const a = active[0], b = active[active.length - 1];
    firstColumn.set(lane.topic.id, a);
    // A one-pixel spine marks years without papers: the topic paused, it did not end.
    const half = (n: number) => n > 0 ? Math.max(1, (n * unit) / 2) : 0.75;
    const topEdge: [number, number][] = [[x(a) - columnWidth * 0.42, lane.mid - 0.5]];
    const bottomEdge: [number, number][] = [[x(a) - columnWidth * 0.42, lane.mid + 0.5]];
    for (let i = a; i <= b; i++) { topEdge.push([x(i), lane.mid - half(lane.counts[i])]); bottomEdge.push([x(i), lane.mid + half(lane.counts[i])]); }
    topEdge.push([x(b) + columnWidth * 0.42, lane.mid - 0.5]); bottomEdge.push([x(b) + columnWidth * 0.42, lane.mid + 0.5]);
    ribbons.push({ topic: lane.topic.id, color: lane.color, d: `${smooth(topEdge, false)} ${smooth(bottomEdge, true)} Z` });
    for (const i of active) dots.push({ topic: lane.topic.id, column: i, x: x(i), y: lane.mid, r: compact ? 1 : Math.min(7, 2.5 + Math.sqrt(lane.counts[i]) * 1.6), count: lane.counts[i], cited: cited.get(lane.topic.id)![i] });
    births.push({ topic: lane.topic.id, x: x(a) - columnWidth * 0.42, y: lane.mid, independent: !lane.topic.parent && !isOther(lane.topic) });
  }

  const laneOf = new Map(lanes.map(l => [l.topic.id, l]));
  const branches: AlluvialLayout['branches'] = [];
  for (const lane of lanes) {
    const parent = lane.topic.parent && laneOf.get(lane.topic.parent.from);
    if (!parent) continue;
    const birth = firstColumn.get(lane.topic.id)!;
    let source = -1;
    for (let i = birth - 1; i >= 0; i--) if (parent.counts[i] > 0) { source = i; break; }
    if (source < 0) source = firstColumn.get(parent.topic.id)!;
    const x1 = x(source), y1 = parent.mid, x2 = x(birth) - columnWidth * 0.42, y2 = lane.mid, mx = (x1 + x2) / 2;
    branches.push({ from: parent.topic.id, to: lane.topic.id, sim: lane.topic.parent!.sim, d: `M${x1.toFixed(1)},${y1.toFixed(1)} C${mx.toFixed(1)},${y1.toFixed(1)} ${mx.toFixed(1)},${y2.toFixed(1)} ${x2.toFixed(1)},${y2.toFixed(1)}` });
  }

  const arcs: AlluvialLayout['arcs'] = [];
  if (!compact) for (const pair of r.recip) {
    const from = laneOf.get(pair.from_topic), to = laneOf.get(pair.to_topic);
    const c1 = mode === 'year' ? pair.from_year - first : eraOfYear(r, pair.from_year);
    const c2 = mode === 'year' ? pair.to_year - first : eraOfYear(r, pair.to_year);
    if (!from || !to || c1 === null || c2 === null || c1 < 0 || c2 >= columns.length) continue;
    const x1 = x(c1), x2 = x(c2), lift = Math.max(18, Math.abs(x2 - x1) * 0.28);
    const y1 = from.mid, y2 = to.mid, peak = Math.min(y1, y2) - lift;
    arcs.push({ from: pair.from_topic, to: pair.to_topic, d: `M${x1.toFixed(1)},${y1.toFixed(1)} C${x1.toFixed(1)},${peak.toFixed(1)} ${x2.toFixed(1)},${peak.toFixed(1)} ${x2.toFixed(1)},${y2.toFixed(1)}` });
  }

  const ticks = columns.map((column, i) => ({ x: x(i), label: column.label, major: mode === 'era' || i === 0 || i === columns.length - 1 || Number(column.label) % 5 === 0 }));
  const width = left + columns.length * columnWidth + (compact ? 4 : 24);
  return { width, height: cursor + (compact ? 4 : 16), left, top, columnWidth, columns, lanes, ribbons, dots, branches, births, bands, bandRows, ticks, arcs, placed, unplaced };
}

/** ``otherText``: degree schools, 계열 words and OpenAlex areas — matched after name/ID/current institution. */
export type QueryEntry = { id: string; name: string | null; alias: string | null; subject: string; institution: string | null; institutionText: string; otherText?: string; hasTopics: boolean };
export type QueryResult = { institutions: { key: string; count: number; withTopics: number }[]; researchers: QueryEntry[] };

const fold = (value: string) => value.normalize('NFKC').toLowerCase().replace(/[\s·.,()\-–]/g, '');

/** Name/ID/institution/subject query. Names participate only when the caller passes decrypted names. */
export function queryResearchers(entries: QueryEntry[], query: string, subjectLabels: Record<string, string>, limit = 8): QueryResult {
  const q = fold(query);
  if (!q) return { institutions: [], researchers: [] };
  const institutions = new Map<string, { key: string; count: number; withTopics: number }>();
  const scored: { entry: QueryEntry; score: number }[] = [];
  for (const entry of entries) {
    const name = entry.name ? fold(entry.name) : '', id = fold(entry.id), alias = entry.alias ? fold(entry.alias) : '';
    const institution = fold(entry.institutionText), subject = fold(subjectLabels[entry.subject] || entry.subject);
    let score = 0;
    if (name && name === q) score = 100; else if (name.startsWith(q)) score = 80; else if (name.includes(q)) score = 60;
    if (id === q) score = Math.max(score, 95); else if (id.includes(q)) score = Math.max(score, 50);
    if (alias.includes(q)) score = Math.max(score, 55);
    if (institution.includes(q)) {
      score = Math.max(score, 40);
      if (entry.institution) {
        const bucket = institutions.get(entry.institution) || { key: entry.institution, count: 0, withTopics: 0 };
        bucket.count++; if (entry.hasTopics) bucket.withTopics++;
        institutions.set(entry.institution, bucket);
      }
    }
    if (subject === q) score = Math.max(score, 20);
    if (!score && entry.otherText && fold(entry.otherText).includes(q)) score = 15;
    if (score) scored.push({ entry, score: score + (entry.hasTopics ? 5 : 0) });
  }
  scored.sort((a, b) => b.score - a.score || Number(b.entry.hasTopics) - Number(a.entry.hasTopics) || a.entry.id.localeCompare(b.entry.id));
  return {
    institutions: [...institutions.values()].sort((a, b) => b.withTopics - a.withTopics || b.count - a.count).slice(0, 4),
    researchers: scored.slice(0, limit).map(s => s.entry),
  };
}

// ── Topic search: bilingual tags + LSA ─────────────────────────────────────────

export type TopicHit = { researcher: TopicResearcher; topic: TopicNode; score: number; tagScore: number; semanticScore: number; matched: string[] };
export type TopicSearch = { hits: TopicHit[]; terms: string[]; expanded: string[]; method: 'semantic' | 'tags' | 'none' };

export function tokenizeQuery(query: string): string[] {
  return query.normalize('NFKC').toLowerCase().split(/[\s,·/;|]+/).map(t => t.replace(/^[^\p{L}\p{N}]+|[^\p{L}\p{N}-]+$/gu, '')).filter(t => t.length >= 2);
}

/** Korean words reach the English LSA vocabulary through the glossary: the exact entry when there is
 *  one, otherwise entries containing or contained in the token. Containment alone collides on
 *  Korean compounds ("전자" ⊂ "유전자"), so it is only the fallback. */
export function expandTerms(tokens: string[], semantic: TopicSemantic | null): string[] {
  const out: string[] = [];
  for (const token of tokens) {
    if (!/[가-힣]/.test(token)) { out.push(token); continue; }
    const exact = semantic?.glossary.get(token);
    if (exact) { out.push(...exact); continue; }
    for (const [ko, ens] of semantic?.glossary || []) if (ko.includes(token) || token.includes(ko)) out.push(...ens);
  }
  return [...new Set(out.flatMap(term => [term, ...term.split(/\s+/)]))];
}

/** English plural → singular, word by word ("lithium-ion batteries" → "lithium-ion battery"). */
export function singular(phrase: string): string {
  return phrase.split(/\s+/).map(w => /[^aeiou]ies$/.test(w) && w.length > 4 ? `${w.slice(0, -3)}y`
    : /(ss|us|is)$/.test(w) || w.length <= 3 ? w
    : /(ches|shes|xes|sses)$/.test(w) ? w.slice(0, -2)
    : w.endsWith('s') ? w.slice(0, -1) : w).join(' ');
}

function queryVector(terms: string[], semantic: TopicSemantic): Float32Array | null {
  const sum = new Float32Array(semantic.dims);
  let found = 0;
  for (const term of terms) {
    const one = singular(term);
    const exact = semantic.terms.get(term) ?? semantic.terms.get(one) ?? semantic.terms.get(`${one}s`) ?? semantic.terms.get(one.replace(/y$/, 'ies'));
    const vectors = exact ? [exact] : term.length >= 4 ? [...semantic.terms].filter(([key]) => key.startsWith(term)).slice(0, 3).map(([, v]) => v) : [];
    for (const v of vectors) { for (let i = 0; i < v.length; i++) sum[i] += v[i]; found++; }
  }
  return found ? unit(sum) : null;
}

/** Ranks every researcher's topics. Score = 0.55·cosine(LSA) + 0.45·tag overlap; either part alone still ranks. */
export function searchTopics(index: TopicIndex, query: string, minimum = 0.22): TopicSearch {
  const terms = tokenizeQuery(query).map(singular);
  if (!terms.length) return { hits: [], terms, expanded: [], method: 'none' };
  const expanded = expandTerms(terms, index.semantic).map(singular);
  const q = index.semantic ? queryVector(expanded, index.semantic) : null;
  const hits: TopicHit[] = [];
  for (const researcher of index.researchers) for (const topic of researcher.topics) {
    // Singular forms on both sides, so "battery" meets "lithium-ion batteries".
    const haystack = [topic.label.toLowerCase(), ...topic.tags.ko, ...topic.tags.en, ...topic.keywords].map(t => singular(t.toLowerCase()));
    // Glossary terms match whole words of English phrases ("single-cell" in "single-cell rna").
    const hasWord = (tag: string, word: string) => tag === word || tag.split(/\s+/).includes(word) || (word.includes(' ') && tag.includes(word));
    const matched = haystack.filter(tag => terms.some(t => tag.includes(t) || (t.length >= 3 && t.includes(tag) && tag.length >= 2)) || expanded.some(t => hasWord(tag, t)));
    // Graded per query term: exact tag 1, query inside a tag 0.8 (or via glossary), tag inside the query 0.5
    // — so "단일세포" prefers a 단일세포 topic over one tagged only "세포".
    const tagScore = terms.reduce((sum, t) => sum + (haystack.includes(t) ? 1
      : haystack.some(tag => tag.includes(t)) || expandTerms([t], index.semantic).some(e => haystack.some(tag => hasWord(tag, singular(e)))) ? 0.8
      : haystack.some(tag => t.includes(tag)) ? 0.5 : 0), 0) / terms.length;
    let semanticScore = 0;
    if (q && topic.vector && topic.vector.length === q.length) {
      const v = unit(topic.vector);
      for (let i = 0; i < v.length; i++) semanticScore += v[i] * q[i];
      semanticScore = Math.max(0, semanticScore);
    }
    const score = q ? 0.55 * semanticScore + 0.45 * tagScore : tagScore;
    if (score >= minimum) hits.push({ researcher, topic, score, tagScore, semanticScore, matched: [...new Set(matched)].slice(0, 6) });
  }
  hits.sort((a, b) => b.score - a.score || b.topic.size - a.topic.size);
  return { hits, terms, expanded, method: q ? 'semantic' : 'tags' };
}

export function tagCloud(index: TopicIndex, limit = 24): { tag: string; count: number }[] {
  const counts = new Map<string, number>();
  for (const r of index.researchers) for (const t of r.topics) for (const tag of t.tags.en) counts.set(tag, (counts.get(tag) || 0) + 1);
  return [...counts].map(([tag, count]) => ({ tag, count })).sort((a, b) => b.count - a.count || a.tag.localeCompare(b.tag, 'en')).slice(0, limit);
}

// ── Multi-researcher view: stack (lane per person) or overlay (streams per person) ──

export const PERSON_PALETTE = ['#256ef4', '#e5484d', '#12a150', '#f59e0b', '#8e4ec6', '#0ea5e9', '#d946ef', '#65a30d', '#f97316', '#475569'];
export type MultiSeries = { key: string; label: string; sublabel: string; color: string; counts: Map<number, number> };
export type MultiMode = 'stack' | 'overlay';
export type MultiLayout = {
  width: number; height: number; left: number; top: number; years: number[];
  shapes: { key: string; d: string; color: string }[];
  lanes: { key: string; label: string; sublabel: string; color: string; mid: number; total: number }[];
  ticks: { x: number; label: string; major: boolean }[];
  totals: { x: number; y: number; n: number }[];
};

/** One series per researcher: papers of the selected topics, counted per year. */
export function seriesFromHits(hits: TopicHit[], labelFor: (id: string) => string): MultiSeries[] {
  const byResearcher = new Map<string, { researcher: TopicResearcher; topics: Set<number> }>();
  for (const hit of hits) {
    const entry = byResearcher.get(hit.researcher.id) || { researcher: hit.researcher, topics: new Set<number>() };
    entry.topics.add(hit.topic.id); byResearcher.set(hit.researcher.id, entry);
  }
  return [...byResearcher.values()].map(({ researcher, topics }, i) => {
    const counts = new Map<number, number>();
    for (const p of researcher.papers) if (topics.has(p.topic)) counts.set(p.year, (counts.get(p.year) || 0) + 1);
    return { key: researcher.id, label: labelFor(researcher.id), sublabel: researcher.topics.filter(t => topics.has(t.id)).map(t => t.label).join(' · '), color: PERSON_PALETTE[i % PERSON_PALETTE.length], counts };
  }).filter(s => s.counts.size);
}

export function layoutMulti(series: MultiSeries[], mode: MultiMode, options: { columnWidth?: number; unit?: number; left?: number } = {}): MultiLayout {
  const years = series.flatMap(s => [...s.counts.keys()]);
  const y0 = years.length ? Math.min(...years) : 0, y1 = years.length ? Math.max(...years) : -1;
  const span = Array.from({ length: Math.max(0, y1 - y0 + 1) }, (_, i) => y0 + i);
  const columnWidth = options.columnWidth ?? 40, left = options.left ?? (mode === 'stack' ? 240 : 64), top = 40;
  const x = (i: number) => left + (i + 0.5) * columnWidth;
  const value = (s: MultiSeries, year: number) => s.counts.get(year) || 0;
  const shapes: MultiLayout['shapes'] = [], lanes: MultiLayout['lanes'] = [], totals: MultiLayout['totals'] = [];
  let height = top;
  if (mode === 'stack') {
    const unit = options.unit ?? 8, gap = 22;
    for (const s of series) {
      const peak = Math.max(...span.map(y => value(s, y)));
      const h = Math.max(peak * unit, 10) + gap, mid = height + h / 2;
      const active = span.flatMap((y, i) => value(s, y) ? [i] : []);
      const a = active[0], b = active[active.length - 1];
      const half = (n: number) => n ? Math.max(1, n * unit / 2) : 0.75;
      const topEdge: [number, number][] = [[x(a) - columnWidth * .42, mid - .5]], bottomEdge: [number, number][] = [[x(a) - columnWidth * .42, mid + .5]];
      for (let i = a; i <= b; i++) { topEdge.push([x(i), mid - half(value(s, span[i]))]); bottomEdge.push([x(i), mid + half(value(s, span[i]))]); }
      topEdge.push([x(b) + columnWidth * .42, mid - .5]); bottomEdge.push([x(b) + columnWidth * .42, mid + .5]);
      shapes.push({ key: s.key, color: s.color, d: `${smooth(topEdge, false)} ${smooth(bottomEdge, true)} Z` });
      lanes.push({ key: s.key, label: s.label, sublabel: s.sublabel, color: s.color, mid, total: [...s.counts.values()].reduce((m, n) => m + n, 0) });
      height += h;
    }
  } else {
    // Streamgraph with a centred baseline; layer order = series order.
    const unit = options.unit ?? 10;
    const totalsByYear = span.map(y => series.reduce((sum, s) => sum + value(s, y), 0));
    const peak = Math.max(1, ...totalsByYear), mid = top + 12 + (peak * unit) / 2;
    const base = totalsByYear.map(t => mid - (t * unit) / 2);
    const cursor = [...base];
    for (const s of series) {
      const topEdge: [number, number][] = [], bottomEdge: [number, number][] = [];
      span.forEach((y, i) => { const h = value(s, y) * unit; topEdge.push([x(i), cursor[i]]); bottomEdge.push([x(i), cursor[i] + h]); cursor[i] += h; });
      shapes.push({ key: s.key, color: s.color, d: `${smooth(topEdge, false)} ${smooth(bottomEdge, true)} Z` });
      lanes.push({ key: s.key, label: s.label, sublabel: s.sublabel, color: s.color, mid, total: [...s.counts.values()].reduce((m, n) => m + n, 0) });
    }
    span.forEach((_, i) => { if (totalsByYear[i]) totals.push({ x: x(i), y: base[i] - 6, n: totalsByYear[i] }); });
    height = mid + (peak * unit) / 2 + 12;
  }
  const ticks = span.map((y, i) => ({ x: x(i), label: String(y), major: i === 0 || i === span.length - 1 || y % 5 === 0 }));
  return { width: left + span.length * columnWidth + 24, height: height + 16, left, top, years: span, shapes, lanes, ticks, totals };
}
