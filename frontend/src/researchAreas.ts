/** OpenAlex research areas per researcher: domain → field → subfield → topic counts over retained works.
 *  Built by backend/scripts/build_research_areas.py; optional — every page works without it. */
export type AreaLevel = 'field' | 'subfield' | 'topic';
/** ``path`` runs from the OpenAlex domain down to this area, e.g. Physical Sciences › Physics and Astronomy › … */
export type AreaShare = { level: AreaLevel; name: string; path: string[]; works: number; share: number };
export type ResearchProfile = { works: number; fields: AreaShare[]; subfields: AreaShare[]; topics: AreaShare[] };
export type ResearchAreas = { releaseYear: number; profiles: Map<string, ResearchProfile> };

export const RESEARCH_AREA_SCHEMA = 'kstem-research-areas/2';

const pairs = (value: unknown): [number, number][] => Array.isArray(value)
  ? value.filter((p): p is [number, number] => Array.isArray(p) && Number.isInteger(p[0]) && Number.isFinite(p[1]) && p[1] > 0)
  : [];
const named = (rows: unknown): [string, number][] => Array.isArray(rows)
  ? rows.map(row => Array.isArray(row) ? [String(row[0] ?? ''), Number(row[1])] : ['', -1])
  : [];

export function normalizeResearchAreas(raw: unknown): ResearchAreas | null {
  if (!raw || typeof raw !== 'object') return null;
  const root = raw as Record<string, unknown>;
  if (root.schema !== RESEARCH_AREA_SCHEMA || !Array.isArray(root.domains)) return null;
  const domains = root.domains.map(String), fields = named(root.fields), subfields = named(root.subfields), topics = named(root.topics);
  const fieldPath = (i: number) => fields[i]?.[0] ? [domains[fields[i][1]] ?? '', fields[i][0]].filter(Boolean) : [];
  const subPath = (i: number) => subfields[i]?.[0] ? [...fieldPath(subfields[i][1]), subfields[i][0]] : [];
  const topicPath = (i: number) => topics[i]?.[0] ? [...subPath(topics[i][1]), topics[i][0]] : [];
  const profiles = new Map<string, ResearchProfile>();
  for (const [id, value] of Object.entries((root.researchers || {}) as Record<string, unknown>)) {
    if (!/^P-[A-Z2-7]{10}$/.test(id) || !value || typeof value !== 'object') continue;
    const rec = value as Record<string, unknown>;
    const works = Number(rec.n);
    if (!Number.isFinite(works) || works <= 0) continue;
    const areas = (level: AreaLevel, list: unknown, path: (i: number) => string[]) => pairs(list)
      .map(([i, n]) => ({ level, path: path(i), works: n, share: n / works }))
      .filter(a => a.path.length).map(a => ({ ...a, name: a.path[a.path.length - 1] }));
    profiles.set(id, { works, fields: areas('field', rec.f, fieldPath), subfields: areas('subfield', rec.s, subPath), topics: areas('topic', rec.t, topicPath) });
  }
  return { releaseYear: Number(root.release_year) || 0, profiles };
}

/** Lower-cased "field · subfield · topic" names for substring search. */
export function areaSearchText(profile: ResearchProfile | undefined): string {
  if (!profile) return '';
  return [...profile.fields, ...profile.subfields, ...profile.topics].map(a => a.name).join(' · ').normalize('NFKC').toLocaleLowerCase('en');
}

/** Best area (largest share, most specific on ties) whose name holds every term. */
export function bestAreaMatch(profile: ResearchProfile | undefined, terms: string[]): AreaShare | null {
  if (!profile || !terms.length) return null;
  let best: AreaShare | null = null;
  for (const area of [...profile.topics, ...profile.subfields, ...profile.fields]) {
    const name = area.name.normalize('NFKC').toLocaleLowerCase('en');
    if (terms.every(term => name.includes(term)) && (!best || area.share > best.share)) best = area;
  }
  return best;
}

export const formatShare = (share: number) => `${Math.round(share * 100)}%`;
