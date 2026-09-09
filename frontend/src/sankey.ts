import { canonicalSchool, institutionDisplayName } from './schoolIdentity';

/** Pure, deterministic aggregation of the public release. No private name data. */
export type SankeyPerson = {
  id: string; subject: string; bachelor_institution: string | null;
  phd_institution: string | null; current_institution: string | null;
  bachelor_country?: string | null; phd_country?: string | null; current_country?: string | null;
};
export type FlowStage = 'bachelor' | 'phd' | 'current';
export type Region = 'domestic' | 'us' | 'europe' | 'japan-china' | 'foreign' | 'unknown';
export type Origin = string;
export const STAGES: FlowStage[] = ['bachelor', 'phd', 'current'];
export const STAGE_LABELS: Record<FlowStage, string> = { bachelor: '학사', phd: '박사', current: '현재 재직' };
/** Stable for each full bachelor identity, independent of filters and ordering. */
export function colorOfOrigin(origin: Origin): string {
  if (origin === 'unresolved') return '#8796a6';
  let hash = 2166136261;
  for (const character of origin) { hash ^= character.codePointAt(0)!; hash = Math.imul(hash, 16777619); }
  const value = hash >>> 0;
  return `hsl(${value % 360} ${48 + (value >>> 8) % 20}% ${37 + (value >>> 16) % 13}%)`;
}
export const SUBJECT_LABELS: Record<string, string> = { mathematics: '수학', physics: '물리학', chemistry: '화학', biology: '생물학' };
const REGION_LABELS: Record<Region, string> = { domestic: '국내', us: '미국', europe: '유럽', 'japan-china': '일본·중국', foreign: '기타 해외', unknown: '국가 미확인' };

const normalize = (s: string) => s.normalize('NFKC').trim().toLowerCase().replace(/[–—]/g, '-').replace(/\s+/g, ' ');
const missingTokens = new Set(['', '-', '--', 'n/a', 'na', 'nan', 'none', 'null', 'unknown', '미상', '미확인', '정보없음', '정보 없음']);
export function isMissingInstitution(value: string | null | undefined): boolean {
  return value == null || missingTokens.has(normalize(String(value)));
}
const ALIASES: Record<string, string> = {};
const ALIAS_LABELS: Record<string, string> = {};
function alias(id: string, label: string, values: string[]) {
  ALIAS_LABELS[id] = institutionDisplayName(label);
  for (const value of [...values, label]) ALIASES[normalize(value)] = id;
}
// Deliberate alias list. Regional campuses remain distinct, including Mirae/Sejong.
alias('snu', '서울대학교', ['Seoul National University', 'Seoul', 'SNU', '서울대']);
alias('kaist', 'KAIST', ['Korea Advanced Institute of Science and Technology', '한국과학기술원']);
alias('postech', 'POSTECH', ['Pohang University of Science and Technology', '포항공과대학교', '포항공대']);
alias('yonsei', '연세대학교', ['Yonsei University', 'Yonsei University (Seoul Campus)', 'Yonsei', '연세대']);
alias('korea', '고려대학교', ['Korea University', 'Korea University (Seoul Campus)', 'Korea', '고려대']);
alias('hanyang', '한양대학교', ['Hanyang University', 'Hanyang University (Seoul Campus)', 'Hanyang', '한양대']);
alias('kyungpook', '경북대학교', ['Kyungpook National University', 'Kyungpook', '경북대']);
alias('pusan', '부산대학교', ['Pusan National University', 'Pusan', '부산대']);
alias('sungkyunkwan', '성균관대학교', ['Sungkyunkwan University', 'Sungkyunkwan', '성균관대']);
alias('kyunghee', '경희대학교', ['Kyung Hee University', 'Kyung-Hee', '경희대']);
alias('chonnam', '전남대학교', ['Chonnam National University', 'Chonnam', '전남대']);
alias('chungnam', '충남대학교', ['Chungnam National University', 'Chungnam', '충남대']);
alias('kangwon', '강원대학교', ['Kangwon National University', 'Kangwon', '강원대', '강원대학교 (통합)']);
alias('chungang', '중앙대학교', ['Chung-Ang University', 'Chung-Ang', '중앙대']);
alias('ewha', '이화여자대학교', ['Ewha Womans University', 'Ewha', '이화여대']);
alias('sogang', '서강대학교', ['Sogang University', 'Sogang', '서강대']);
alias('jeonbuk', '전북대학교', ['Jeonbuk National University', 'Chonbuk National University', 'Jeonbuk', '전북대']);
alias('gist', 'GIST', ['Gwangju Institute of Science and Technology', '광주과학기술원']);
alias('unist', 'UNIST', ['Ulsan National Institute of Science and Technology', '울산과학기술원']);
alias('gachon', '가천대학교', ['Gachon University', 'Gachon', '가천대']);
// Continuing university labels only: predecessor GNTECH and Gangneung-Wonju
// remain separate historical schools; no merger crosswalk is inferred here.
alias('gyeongsang', 'Gyeongsang National University', ['경상국립대학교', '경상대학교']);

export function institutionKey(value: string): string {
  if (/^\d+(?:\.0)?$/.test(normalize(value))) return 'unresolved';
  const raw = normalize(value), canonical = normalize(canonicalSchool(value) ?? value);
  return ALIASES[raw] ?? ALIASES[canonical] ?? `institution:${canonical}`;
}
export function institutionLabel(value: string): string {
  if (/^\d+(?:\.0)?$/.test(normalize(value))) return '기관명 미확인';
  return ALIAS_LABELS[institutionKey(value)] ?? institutionDisplayName(value);
}
export function countryRegion(value?: string | null): Region {
  if (!value || missingTokens.has(normalize(value))) return 'unknown';
  const isoNames: Record<string, string> = { ch: 'switzerland', nl: 'netherlands', it: 'italy', es: 'spain', at: 'austria', se: 'sweden', no: 'norway', dk: 'denmark', fi: 'finland', be: 'belgium', ie: 'ireland', pl: 'poland', pt: 'portugal', gr: 'greece', cz: 'czechia', hu: 'hungary', ro: 'romania', bg: 'bulgaria', hr: 'croatia', si: 'slovenia', sk: 'slovakia', ee: 'estonia', lv: 'latvia', lt: 'lithuania', is: 'iceland', lu: 'luxembourg', mt: 'malta', ca: 'canada', au: 'australia', in: 'india', il: 'israel', nz: 'new zealand', tw: 'taiwan', hk: 'hong kong', sg: 'singapore', ru: 'russia', pk: 'pakistan', bd: 'bangladesh', lk: 'sri lanka', np: 'nepal', vn: 'vietnam', th: 'thailand', my: 'malaysia', id: 'indonesia', ph: 'philippines', br: 'brazil', mx: 'mexico', ar: 'argentina', cl: 'chile', co: 'colombia', pe: 'peru', za: 'south africa', eg: 'egypt', ng: 'nigeria', ke: 'kenya', et: 'ethiopia', ir: 'iran', iq: 'iraq', tr: 'turkey', sa: 'saudi arabia', ae: 'united arab emirates', qa: 'qatar', lb: 'lebanon', jo: 'jordan', kz: 'kazakhstan', uz: 'uzbekistan', mn: 'mongolia', cy: 'cyprus' };
  const raw = normalize(value).replace(/[.]/g, '');
  const c = isoNames[raw] ?? raw;
  if (['korea', 'south korea', 'republic of korea', 'korea, republic of', 'kr', 'kor', '한국', '대한민국'].includes(c)) return 'domestic';
  if (['us', 'usa', 'united states', 'united states of america', '미국'].includes(c)) return 'us';
  if (['japan', 'china', 'jp', 'cn', '일본', '중국', "people's republic of china"].includes(c)) return 'japan-china';
  if (['united kingdom', 'uk', 'gb', 'england', 'scotland', 'wales', 'germany', 'de', 'france', 'fr', 'switzerland', 'netherlands', 'italy', 'spain', 'austria', 'sweden', 'norway', 'denmark', 'finland', 'belgium', 'ireland', 'poland', 'portugal', 'greece', 'czech republic', 'czechia', 'hungary', 'romania', 'bulgaria', 'croatia', 'slovenia', 'slovakia', 'estonia', 'latvia', 'lithuania', 'iceland', 'luxembourg', 'malta', '영국', '독일', '프랑스', '스위스', '네덜란드', '이탈리아', '스웨덴'].includes(c)) return 'europe';
  // Only explicit country values establish foreign status; free-text codes stay unknown.
  if (['australia', 'canada', 'india', 'israel', 'new zealand', 'taiwan', 'hong kong', 'singapore', 'russia', 'russian federation', 'pakistan', 'bangladesh', 'sri lanka', 'nepal', 'vietnam', 'thailand', 'malaysia', 'indonesia', 'philippines', 'brazil', 'mexico', 'argentina', 'chile', 'colombia', 'peru', 'south africa', 'egypt', 'nigeria', 'kenya', 'ethiopia', 'iran', 'iraq', 'turkey', 'türkiye', 'saudi arabia', 'united arab emirates', 'qatar', 'lebanon', 'jordan', 'kazakhstan', 'uzbekistan', 'mongolia', 'cyprus', '호주', '오스트레일리아', '캐나다', '인도', '이스라엘', '뉴질랜드', '대만', '홍콩', '싱가포르', '러시아', '브라질', '기타해외', '기타 해외'].includes(c)) return 'foreign';
  return 'unknown';
}
export function originOf(institution: string): Origin { return institutionKey(institution); }
export type FlowRecord = {
  id: string; origin: Origin; originLabel: string; selfHire: boolean;
  original: Record<FlowStage, string>; keys: Record<FlowStage, string>; labels: Record<FlowStage, string>;
  regions: Record<FlowStage, Region>;
};
export type FlowNode = { id: string; key: string; stage: FlowStage; label: string; region: Region; count: number; personIds: string[] };
export type FlowLink = { id: string; source: string; target: string; origin: Origin; originLabel: string; selfHire: boolean; count: number; personIds: string[] };
export type FlowRoute = { id: string; labels: [string, string, string]; origin: Origin; originLabel: string; selfHire: boolean; count: number; personIds: string[] };
export type InstitutionOption = { key: string; label: string; count: number };
export type SankeyData = {
  nodes: FlowNode[]; links: FlowLink[]; records: FlowRecord[]; routes: FlowRoute[];
  origins: (InstitutionOption & { color: string })[];
  /** Unique subject population before institution/self-hire filters. */
  subjectCount: number;
  /** All active population filters apply before completeness is measured. */
  filterCount: number;
  completeCount: number; missingCount: number; duplicateCount: number;
  missingByStage: Record<FlowStage, number>; count: number; selfHireCount: number; unknownCountryCount: number; unresolvedInstitutionCount: number;
};
export type SankeyOptions = { subject?: string; institutions?: Partial<Record<FlowStage, string>>; groupForeign?: boolean; selfHireOnly?: boolean };
const stageId = (stage: FlowStage, key: string) => JSON.stringify([stage, key]);
const lexical = (a: string, b: string) => a < b ? -1 : a > b ? 1 : 0;
const valuesOf = (person: SankeyPerson): Record<FlowStage, string | null> => ({ bachelor: person.bachelor_institution, phd: person.phd_institution, current: person.current_institution });
const keyOf = (value: string | null | undefined): string | null => isMissingInstitution(value) ? null : institutionKey(value!);
function isSelfHire(person: SankeyPerson): boolean {
  const bachelor = keyOf(person.bachelor_institution), current = keyOf(person.current_institution);
  return bachelor !== null && bachelor !== 'unresolved' && bachelor === current;
}
function uniquePeople(people: readonly SankeyPerson[]): { people: SankeyPerson[]; duplicateCount: number } {
  const ids = new Set<string>(); const distinct: SankeyPerson[] = []; let duplicateCount = 0;
  for (const person of people) {
    if (ids.has(person.id)) { duplicateCount++; continue; }
    ids.add(person.id); distinct.push(person);
  }
  return { people: distinct, duplicateCount };
}
function orderedOptions(values: Iterable<InstitutionOption>): InstitutionOption[] {
  return [...values].sort((a, b) => lexical(a.label, b.label) || lexical(a.key, b.key));
}
/** All valid institutions, including people with missing information at other stages. */
export function buildInstitutionOptions(people: readonly SankeyPerson[], options: Pick<SankeyOptions, 'subject' | 'selfHireOnly'> = {}): Record<FlowStage, InstitutionOption[]> {
  const maps: Record<FlowStage, Map<string, InstitutionOption>> = { bachelor: new Map(), phd: new Map(), current: new Map() };
  for (const person of uniquePeople(people).people) {
    if ((options.subject && person.subject !== options.subject) || (options.selfHireOnly && !isSelfHire(person))) continue;
    const values = valuesOf(person);
    for (const stage of STAGES) {
      const key = keyOf(values[stage]); if (key === null) continue;
      const label = institutionLabel(values[stage]!); const prior = maps[stage].get(key);
      if (prior) { prior.count++; if (lexical(label, prior.label) < 0) prior.label = label; }
      else maps[stage].set(key, { key, label, count: 1 });
    }
  }
  return { bachelor: orderedOptions(maps.bachelor.values()), phd: orderedOptions(maps.phd.values()), current: orderedOptions(maps.current.values()) };
}

export function buildSankey(people: readonly SankeyPerson[], options: SankeyOptions = {}): SankeyData {
  const groupForeign = options.groupForeign ?? false;
  const distinct = uniquePeople(people);
  const subjectPeople = distinct.people.filter(p => !options.subject || p.subject === options.subject);
  const institutions = options.institutions ?? {};
  const filteredPeople = subjectPeople.filter(person => {
    const values = valuesOf(person);
    return STAGES.every(stage => !institutions[stage] || keyOf(values[stage]) === institutions[stage]) && (!options.selfHireOnly || isSelfHire(person));
  });
  const missingByStage: Record<FlowStage, number> = { bachelor: 0, phd: 0, current: 0 };
  const records: FlowRecord[] = [];
  for (const person of filteredPeople) {
    const values = valuesOf(person); let missing = false;
    for (const stage of STAGES) if (isMissingInstitution(values[stage])) { missingByStage[stage]++; missing = true; }
    if (missing) continue;
    const original = values as Record<FlowStage, string>;
    const keys = Object.fromEntries(STAGES.map(s => [s, institutionKey(original[s])])) as Record<FlowStage, string>;
    const labels = Object.fromEntries(STAGES.map(s => [s, institutionLabel(original[s])])) as Record<FlowStage, string>;
    const regions = { bachelor: countryRegion(person.bachelor_country), phd: countryRegion(person.phd_country), current: countryRegion(person.current_country) };
    records.push({ id: person.id, original, keys, labels, regions, origin: keys.bachelor, originLabel: labels.bachelor, selfHire: isSelfHire(person) });
  }
  const nodes = new Map<string, FlowNode>(), links = new Map<string, FlowLink>(), routes = new Map<string, FlowRoute>();
  const origins = new Map<string, InstitutionOption>();
  for (const record of records) {
    const previousOrigin = origins.get(record.origin);
    if (previousOrigin) { previousOrigin.count++; if (lexical(record.originLabel, previousOrigin.label) < 0) previousOrigin.label = record.originLabel; }
    else origins.set(record.origin, { key: record.origin, label: record.originLabel, count: 1 });
    const path: string[] = [];
    for (const stage of STAGES) {
      const region = record.regions[stage];
      // A selected institution is always shown explicitly. Unresolved numeric
      // school codes never acquire an institution identity from country alone.
      const grouped = groupForeign && !institutions[stage] && stage !== 'current' && record.keys[stage] !== 'unresolved' && !['domestic', 'unknown'].includes(region);
      const key = grouped ? `region:${region}` : record.keys[stage];
      const id = stageId(stage, key);
      const label = grouped ? `${REGION_LABELS[region]} ${STAGE_LABELS[stage]}기관` : record.labels[stage];
      const node = nodes.get(id);
      if (node) {
        node.count++; node.personIds.push(record.id);
        if (node.region !== region) node.region = 'unknown';
        if (lexical(label, node.label) < 0) node.label = label;
      } else nodes.set(id, { id, key, stage, label, region, count: 1, personIds: [record.id] });
      path.push(id);
    }
    for (let i = 0; i < 2; i++) {
      const id = JSON.stringify([path[i], path[i + 1], record.origin, record.selfHire]);
      const link = links.get(id);
      if (link) { link.count++; link.personIds.push(record.id); }
      else links.set(id, { id, source: path[i], target: path[i + 1], origin: record.origin, originLabel: record.originLabel, selfHire: record.selfHire, count: 1, personIds: [record.id] });
    }
    const id = JSON.stringify([record.keys.bachelor, record.keys.phd, record.keys.current]);
    const route = routes.get(id);
    if (route) { route.count++; route.personIds.push(record.id); }
    else routes.set(id, { id, labels: [record.labels.bachelor, record.labels.phd, record.labels.current], origin: record.origin, originLabel: record.originLabel, selfHire: record.selfHire, count: 1, personIds: [record.id] });
  }
  for (const link of links.values()) link.originLabel = origins.get(link.origin)!.label;
  for (const route of routes.values()) route.originLabel = origins.get(route.origin)!.label;
  return {
    nodes: [...nodes.values()].sort((a, b) => lexical(a.id, b.id)), links: [...links.values()].sort((a, b) => lexical(a.id, b.id)), records,
    routes: [...routes.values()].sort((a, b) => b.count - a.count || lexical(a.id, b.id)),
    origins: orderedOptions(origins.values()).map(origin => ({ ...origin, color: colorOfOrigin(origin.key) })),
    subjectCount: subjectPeople.length, filterCount: filteredPeople.length, completeCount: records.length,
    missingCount: filteredPeople.length - records.length, duplicateCount: distinct.duplicateCount,
    missingByStage, count: records.length, selfHireCount: records.filter(r => r.selfHire).length,
    unknownCountryCount: records.filter(r => r.regions.bachelor === 'unknown' || r.regions.phd === 'unknown').length,
    unresolvedInstitutionCount: records.filter(r => STAGES.some(s => r.keys[s] === 'unresolved')).length,
  };
}

export type PositionedNode = FlowNode & { x: number; y: number; height: number; labelY: number };
export type PositionedLink = FlowLink & { sourceX: number; targetX: number; sourceY: number; targetY: number; height: number; path: string };
export type SankeyLayout = { nodes: PositionedNode[]; links: PositionedLink[]; width: number; height: number; scale: number };
export function ribbonPath(sourceX: number, targetX: number, sourceY: number, targetY: number, height: number): string {
  const mid = (sourceX + targetX) / 2;
  return `M${sourceX},${sourceY} C${mid},${sourceY} ${mid},${targetY} ${targetX},${targetY} L${targetX},${targetY + height} C${mid},${targetY + height} ${mid},${sourceY + height} ${sourceX},${sourceY + height} Z`;
}
export function layoutSankey(data: SankeyData, labelHeights: ReadonlyMap<string, number> = new Map()): SankeyLayout {
  const width = 1540, top = 44, bottom = 34, gap = 22;
  const groups = STAGES.map(s => data.nodes.filter(n => n.stage === s).sort((a, b) => b.count - a.count || lexical(a.id, b.id)));
  const maxNodes = Math.max(1, ...groups.map(g => g.length));
  const baseHeight = Math.max(710, maxNodes * 36 + 200);
  const scale = data.count ? (baseHeight - top - bottom - (maxNodes - 1) * gap) / data.count : 0;
  // Reserve room for complete, wrapped labels; every ribbon still uses one common person-to-width scale.
  const slotHeight = (node: FlowNode) => Math.max(node.count * scale, labelHeights.get(node.id) ?? 0);
  const usedHeight = (group: FlowNode[]) => group.reduce((sum, node) => sum + slotHeight(node), 0) + Math.max(0, group.length - 1) * gap;
  const height = Math.max(baseHeight, top + bottom + Math.max(0, ...groups.map(usedHeight)));
  const positions = new Map<string, number>();
  const place = () => {
    for (const group of groups) {
      const used = usedHeight(group);
      let y = top + (height - top - bottom - used) / 2;
      for (const n of group) { positions.set(n.id, y + slotHeight(n) / 2); y += slotHeight(n) + gap; }
    }
  };
  place();
  // Alternating weighted barycentres reduce crossings without changing counts or widths.
  for (let pass = 0; pass < 8; pass++) {
    for (const index of pass % 2 ? [1, 0] : [1, 2]) {
      const fromLeft = pass % 2 === 0;
      const weights = new Map<string, { sum: number; n: number }>();
      for (const link of data.links) {
        const id = fromLeft ? link.target : link.source;
        const neighbor = fromLeft ? link.source : link.target;
        const w = weights.get(id) ?? { sum: 0, n: 0 };
        w.sum += (positions.get(neighbor) ?? 0) * link.count; w.n += link.count; weights.set(id, w);
      }
      groups[index].sort((a, b) => {
        const wa = weights.get(a.id), wb = weights.get(b.id);
        return ((wa?.n ? wa.sum / wa.n : positions.get(a.id)!) - (wb?.n ? wb.sum / wb.n : positions.get(b.id)!)) || lexical(a.id, b.id);
      });
      place();
    }
  }
  const xs = [260, 770, 1260], nodeWidth = 12;
  const nodes: PositionedNode[] = groups.flatMap((group, i) => group.map(n => ({ ...n, x: xs[i], y: positions.get(n.id)! - n.count * scale / 2, height: n.count * scale, labelY: positions.get(n.id)! })));
  const nodeMap = new Map(nodes.map(n => [n.id, n]));
  const sy = new Map<string, number>(), ty = new Map<string, number>();
  const outgoingByNode = new Map<string, FlowLink[]>(), incomingByNode = new Map<string, FlowLink[]>();
  for (const link of data.links) {
    if (!outgoingByNode.has(link.source)) outgoingByNode.set(link.source, []);
    if (!incomingByNode.has(link.target)) incomingByNode.set(link.target, []);
    outgoingByNode.get(link.source)!.push(link); incomingByNode.get(link.target)!.push(link);
  }
  for (const n of nodes) {
    let out = n.y, into = n.y;
    const outgoing = (outgoingByNode.get(n.id) ?? []).sort((a, b) => nodeMap.get(a.target)!.y - nodeMap.get(b.target)!.y || lexical(a.id, b.id));
    const incoming = (incomingByNode.get(n.id) ?? []).sort((a, b) => nodeMap.get(a.source)!.y - nodeMap.get(b.source)!.y || lexical(a.id, b.id));
    for (const l of outgoing) { sy.set(l.id, out); out += l.count * scale; }
    for (const l of incoming) { ty.set(l.id, into); into += l.count * scale; }
  }
  const links = data.links.map(l => {
    const sourceX = nodeMap.get(l.source)!.x + nodeWidth, targetX = nodeMap.get(l.target)!.x;
    const sourceY = sy.get(l.id)!, targetY = ty.get(l.id)!, h = l.count * scale;
    return { ...l, sourceX, targetX, sourceY, targetY, height: h, path: ribbonPath(sourceX, targetX, sourceY, targetY, h) };
  });
  return { nodes, links, width, height, scale };
}
