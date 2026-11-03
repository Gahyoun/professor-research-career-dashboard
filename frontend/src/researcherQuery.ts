import { areaSearchText, bestAreaMatch, formatShare, type AreaShare, type ResearchProfile } from './researchAreas';
import { institutionDisplayName, institutionSearchText } from './schoolIdentity';

/** Researcher search over name (only after unlock), anonymous ID, current/bachelor/PhD institution, roster
 *  field (계열) and OpenAlex research area (field/subfield/topic of the researcher's retained works).
 *  Free words match any of these; `학부:서울대 박사:KAIST 계열:물리 연구:spin` restricts each value to one.
 *  A value is one word or a quoted phrase (`박사:"seoul national"`); `학부: 서울대` takes the next word. */
export type ResearcherField = 'name' | 'id' | 'current' | 'bachelor' | 'phd' | 'subject' | 'area';
export type ResearcherTexts = Record<ResearcherField, string>;
export type ResearcherQuery = { free: string[]; scoped: { field: ResearcherField; terms: string[] }[] };
export type QueryPerson = {
  id: string; subject: string; current_institution: string | null; department?: string | null;
  bachelor_institution?: string | null; phd_institution?: string | null;
  bachelor_institution_canonical?: string | null; phd_institution_canonical?: string | null;
};

export const RESEARCHER_FIELD_LABELS: Record<ResearcherField, string> = { name: '이름', id: '익명 ID', current: '재직', bachelor: '학부', phd: '박사', subject: '계열', area: '연구분야' };
export const SUBJECT_TERMS: Record<string, string[]> = {
  physics: ['physics', 'phys', '물리학', '물리'],
  chemistry: ['chemistry', 'chem', '화학'],
  biology: ['biology', 'bio', 'life', '생물학', '생물', '생명'],
  mathematics: ['mathematics', 'math', 'maths', '수학'],
};
const PREFIXES: Record<string, ResearcherField> = {
  재직: 'current', 현직: 'current', 소속: 'current', 기관: 'current', inst: 'current', current: 'current',
  학부: 'bachelor', 학사: 'bachelor', bs: 'bachelor', ba: 'bachelor', bachelor: 'bachelor',
  박사: 'phd', phd: 'phd',
  계열: 'subject', 분야: 'subject', field: 'subject', subject: 'subject',
  연구: 'area', 연구분야: 'area', 주제: 'area', 토픽: 'area', area: 'area', topic: 'area', openalex: 'area', oa: 'area',
  이름: 'name', name: 'name', id: 'id',
};

export const normalizeQuery = (value: string) => value.normalize('NFKC').toLocaleLowerCase('ko-KR');
const words = (value: string) => normalizeQuery(value).split(/\s+/).filter(Boolean);

export function parseResearcherQuery(text: string): ResearcherQuery {
  const tokens = normalizeQuery(text).match(/[^\s:：="]+[:：=]"[^"]*"?|"[^"]*"?|[^\s"]+/g) || [];
  const out: ResearcherQuery = { free: [], scoped: [] };
  let pending: ResearcherField | null = null;
  for (const token of tokens) {
    const prefixed = token.match(/^([^:：=]+)[:：=](.*)$/);
    const field = prefixed ? PREFIXES[prefixed[1]] : undefined;
    const raw = field ? prefixed![2] : token;
    const terms = words(raw.replace(/"/g, ' '));
    if (field && !terms.length) { pending = field; continue; }
    const target = field || pending;
    pending = null;
    if (!terms.length) continue;
    if (target) out.scoped.push({ field: target, terms }); else out.free.push(...terms);
  }
  return out;
}

export const isEmptyQuery = (query: ResearcherQuery) => !query.free.length && !query.scoped.length;

const schoolText = (raw: string | null | undefined, canonical?: string | null) =>
  normalizeQuery([raw, canonical].filter(Boolean).map(v => `${institutionSearchText(v)} ${institutionDisplayName(v)}`).join(' '));

export function researcherTexts(person: QueryPerson, name?: string | null, profile?: ResearchProfile): ResearcherTexts {
  return {
    name: normalizeQuery(name || ''),
    id: normalizeQuery(person.id),
    current: normalizeQuery(`${schoolText(person.current_institution)} ${person.department || ''}`),
    bachelor: schoolText(person.bachelor_institution, person.bachelor_institution_canonical),
    phd: schoolText(person.phd_institution, person.phd_institution_canonical),
    subject: normalizeQuery([person.subject, ...(SUBJECT_TERMS[person.subject] || [])].join(' ')),
    area: areaSearchText(profile),
  };
}

/** Short Latin tokens (MIT, SNU, bio) must start a word, so "mit" does not hit "Smith". */
export function containsTerm(text: string, term: string): boolean {
  if (!/^[a-z0-9]{1,3}$/.test(term)) return text.includes(term);
  return new RegExp(`(^|[^a-z0-9])${term}`).test(text);
}

const FREE_FIELDS: ResearcherField[] = ['name', 'id', 'current', 'bachelor', 'phd', 'subject', 'area'];

/** Fields that matched, or null. Every free word must hit some field; every scoped value its own field. */
export function matchResearcher(texts: ResearcherTexts, query: ResearcherQuery): ResearcherField[] | null {
  const hit = new Set<ResearcherField>();
  for (const { field, terms } of query.scoped) {
    if (!terms.every(term => containsTerm(texts[field], term))) return null;
    hit.add(field);
  }
  for (const term of query.free) {
    const fields = FREE_FIELDS.filter(field => texts[field] && containsTerm(texts[field], term));
    if (!fields.length) return null;
    fields.forEach(field => hit.add(field));
  }
  return [...hit];
}

export type ResearcherIndex<T extends QueryPerson> = { person: T; texts: ResearcherTexts; profile?: ResearchProfile }[];
export type ResearcherHit<T extends QueryPerson> = { person: T; fields: ResearcherField[]; area: AreaShare | null };

/** Build once per people/names/areas change; searching then costs one substring scan per field. */
export function indexResearchers<T extends QueryPerson>(people: T[], names?: Record<string, string> | null, profiles?: Map<string, ResearchProfile> | null): ResearcherIndex<T> {
  return people.map(person => {
    const profile = profiles?.get(person.id);
    return { person, profile, texts: researcherTexts(person, names?.[person.id], profile) };
  });
}

/** The OpenAlex area that explains an area hit: scoped area terms together, else the best single free term. */
function explainArea(profile: ResearchProfile | undefined, texts: ResearcherTexts, query: ResearcherQuery): AreaShare | null {
  const scoped = query.scoped.filter(s => s.field === 'area').flatMap(s => s.terms);
  if (scoped.length) return bestAreaMatch(profile, scoped);
  const free = query.free.filter(term => containsTerm(texts.area, term));
  if (!free.length) return null;
  return bestAreaMatch(profile, free) ?? free.map(term => bestAreaMatch(profile, [term])).reduce<AreaShare | null>((a, b) => (b && (!a || b.share > a.share) ? b : a), null);
}

/** Matching people with the fields that matched. Index order is kept, except that an OpenAlex area
 *  query ranks people by the share of their works in the matched area. An empty query keeps everyone. */
export function searchResearchers<T extends QueryPerson>(index: ResearcherIndex<T>, text: string): ResearcherHit<T>[] {
  const query = parseResearcherQuery(text);
  if (isEmptyQuery(query)) return index.map(({ person }) => ({ person, fields: [], area: null }));
  const out: ResearcherHit<T>[] = [];
  for (const { person, texts, profile } of index) {
    const fields = matchResearcher(texts, query);
    if (fields) out.push({ person, fields, area: fields.includes('area') ? explainArea(profile, texts, query) : null });
  }
  // Area-only matches rank by share; people matched on name/ID/school/계열 keep their place first.
  const areaOnly = (hit: ResearcherHit<T>) => hit.fields.length === 1 && hit.fields[0] === 'area';
  if (out.some(hit => hit.area)) out.sort((a, b) => Number(areaOnly(a)) - Number(areaOnly(b)) || (b.area?.share ?? 0) - (a.area?.share ?? 0));
  return out;
}

/** "학부 Seoul National University · 박사 KAIST · Condensed Matter Physics 42%" for a result line. */
export function matchContext(hit: ResearcherHit<QueryPerson>): string {
  const parts: string[] = [];
  if (hit.fields.includes('bachelor')) parts.push(`학부 ${institutionDisplayName(hit.person.bachelor_institution)}`);
  if (hit.fields.includes('phd')) parts.push(`박사 ${institutionDisplayName(hit.person.phd_institution)}`);
  if (hit.area) parts.push(`${hit.area.name} ${formatShare(hit.area.share)}`);
  return parts.join(' · ');
}

export const RESEARCHER_QUERY_HINT = '학부:서울대 박사:KAIST 계열:물리 연구:"condensed matter"처럼 항목을 지정할 수 있습니다. 연구분야는 OpenAlex 분류(영문)입니다.';
