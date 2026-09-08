import { institutionDisplayName } from './schoolIdentity';

/** Pure, deterministic aggregation of the public release. No private name data. */
export type SankeyPerson = {
  id: string; subject: string; bachelor_institution: string | null;
  phd_institution: string | null; current_institution: string | null;
  bachelor_country?: string | null; phd_country?: string | null; current_country?: string | null;
};
export type FlowStage = 'bachelor' | 'phd' | 'current';
export type Region = 'domestic' | 'us' | 'europe' | 'japan-china' | 'foreign' | 'unknown';
export type Origin = 'snu' | 'kaist' | 'postech' | 'yonsei' | 'korea' | 'other';
export const STAGES: FlowStage[] = ['bachelor', 'phd', 'current'];
export const STAGE_LABELS: Record<FlowStage, string> = { bachelor: '학사', phd: '박사', current: '현재 재직' };
export const ORIGIN_LABELS: Record<Origin, string> = {
  snu: institutionDisplayName('Seoul National University'),
  kaist: institutionDisplayName('Korea Advanced Institute of Science and Technology'),
  postech: institutionDisplayName('Pohang University of Science and Technology'),
  yonsei: institutionDisplayName('Yonsei University'),
  korea: institutionDisplayName('Korea University'),
  other: '그 외 학부',
};
export const ORIGIN_COLORS: Record<Origin, string> = { snu: '#163c7a', kaist: '#087e9b', postech: '#a94269', yonsei: '#256ef4', korea: '#8f4754', other: '#8796a6' };
export const SUBJECT_LABELS: Record<string, string> = { mathematics: '수학', physics: '물리학', chemistry: '화학', biology: '생물학' };
const REGION_LABELS: Record<Region, string> = { domestic: '국내', us: '미국', europe: '유럽', 'japan-china': '일본·중국', foreign: '기타 해외', unknown: '국가 미확인' };

const normalize = (s: string) => s.normalize('NFKC').trim().toLowerCase().replace(/[–—]/g, '-').replace(/\s+/g, ' ');
const missingTokens = new Set(['', '-', '--', 'n/a', 'na', 'nan', 'none', 'null', 'unknown', '미상', '미확인', '정보없음', '정보 없음']);
export function isMissingInstitution(value: string | null | undefined): boolean {
  return value == null || missingTokens.has(normalize(String(value)));
}
const ALIASES: Record<string, string> = {};
function alias(id: string, label: string, values: string[]) {
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
alias('kangwon', '강원대학교', ['Kangwon National University', 'Kangwon', '강원대']);
alias('chungang', '중앙대학교', ['Chung-Ang University', 'Chung-Ang', '중앙대']);
alias('ewha', '이화여자대학교', ['Ewha Womans University', 'Ewha', '이화여대']);
alias('sogang', '서강대학교', ['Sogang University', 'Sogang', '서강대']);
alias('jeonbuk', '전북대학교', ['Jeonbuk National University', 'Chonbuk National University', 'Jeonbuk', '전북대']);
alias('gist', 'GIST', ['Gwangju Institute of Science and Technology', '광주과학기술원']);
alias('unist', 'UNIST', ['Ulsan National Institute of Science and Technology', '울산과학기술원']);
alias('gachon', '가천대학교', ['Gachon University', 'Gachon', '가천대']);

export function institutionKey(value: string): string {
  const n = normalize(value);
  return ALIASES[n] ?? `institution:${n}`;
}
export function institutionLabel(value: string): string {
  if (/^\d+(?:\.0)?$/.test(value.trim())) return '기관명 미확인';
  return institutionDisplayName(value);
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
export function originOf(institution: string): Origin {
  const key = institutionKey(institution);
  return ['snu', 'kaist', 'postech', 'yonsei', 'korea'].includes(key) ? key as Origin : 'other';
}
export type FlowRecord = {
  id: string; origin: Origin; selfHire: boolean;
  original: Record<FlowStage, string>; keys: Record<FlowStage, string>; labels: Record<FlowStage, string>;
  regions: Record<FlowStage, Region>;
};
export type FlowNode = { id: string; key: string; stage: FlowStage; label: string; region: Region; count: number; personIds: string[] };
export type FlowLink = { id: string; source: string; target: string; origin: Origin; selfHire: boolean; count: number; personIds: string[] };
export type FlowRoute = { id: string; labels: [string, string, string]; origin: Origin; selfHire: boolean; count: number; personIds: string[] };
export type SankeyData = {
  nodes: FlowNode[]; links: FlowLink[]; records: FlowRecord[]; routes: FlowRoute[];
  subjectCount: number; completeCount: number; missingCount: number; duplicateCount: number;
  missingByStage: Record<FlowStage, number>; count: number; selfHireCount: number; unknownCountryCount: number; unresolvedInstitutionCount: number;
};
export type SankeyOptions = { subject?: string; topN?: number; groupForeign?: boolean; origin?: Origin | 'all'; selfHireOnly?: boolean };
const stageId = (stage: FlowStage, key: string) => JSON.stringify([stage, key]);
const lexical = (a: string, b: string) => a < b ? -1 : a > b ? 1 : 0;

export function buildSankey(people: readonly SankeyPerson[], options: SankeyOptions = {}): SankeyData {
  const topN = Math.max(5, Math.min(14, Math.floor(options.topN ?? 10)));
  const groupForeign = options.groupForeign ?? true;
  const seen = new Set<string>();
  let duplicateCount = 0;
  const subjectPeople = people.filter(p => !options.subject || p.subject === options.subject).filter(p => {
    if (seen.has(p.id)) { duplicateCount++; return false; }
    seen.add(p.id); return true;
  });
  const missingByStage: Record<FlowStage, number> = { bachelor: 0, phd: 0, current: 0 };
  const complete: FlowRecord[] = [];
  for (const person of subjectPeople) {
    const values = { bachelor: person.bachelor_institution, phd: person.phd_institution, current: person.current_institution };
    let missing = false;
    for (const stage of STAGES) if (isMissingInstitution(values[stage])) { missingByStage[stage]++; missing = true; }
    if (missing) continue;
    const original = values as Record<FlowStage, string>;
    const keys = Object.fromEntries(STAGES.map(s => [s, /^\d+(?:\.0)?$/.test(original[s].trim()) ? 'unresolved' : institutionKey(original[s])])) as Record<FlowStage, string>;
    const labels = Object.fromEntries(STAGES.map(s => [s, institutionLabel(original[s])])) as Record<FlowStage, string>;
    const regions = { bachelor: countryRegion(person.bachelor_country), phd: countryRegion(person.phd_country), current: countryRegion(person.current_country) };
    const selfHire = keys.bachelor !== 'unresolved' && keys.bachelor === keys.current;
    complete.push({ id: person.id, original, keys, labels, regions, origin: originOf(original.bachelor), selfHire });
  }
  const records = complete.filter(r => (!options.origin || options.origin === 'all' || r.origin === options.origin) && (!options.selfHireOnly || r.selfHire));
  const rawNodes = new Map<string, { key: string; label: string; region: Region; count: number; stage: FlowStage }>();
  const displayKeys = new Map<string, Record<FlowStage, string>>();
  for (const record of records) {
    const dk = {} as Record<FlowStage, string>;
    for (const stage of STAGES) {
      const region = record.regions[stage];
      const grouped = groupForeign && stage !== 'current' && !['domestic', 'unknown'].includes(region);
      const key = grouped ? `region:${region}` : record.keys[stage];
      const id = stageId(stage, key);
      const label = grouped ? `${REGION_LABELS[region]} ${STAGE_LABELS[stage]}기관` : record.labels[stage];
      const existing = rawNodes.get(id);
      if (existing) {
        existing.count++;
        // Conflicting metadata should not acquire a fabricated country category.
        if (existing.region !== region) existing.region = 'unknown';
      } else rawNodes.set(id, { stage, key, label, region, count: 1 });
      dk[stage] = key;
    }
    displayKeys.set(record.id, dk);
  }
  const kept = new Set<string>();
  for (const stage of STAGES) {
    const candidates = [...rawNodes.values()].filter(n => n.stage === stage);
    const fixed = candidates.filter(n => n.key.startsWith('region:') || (stage === 'bachelor' && n.key in ORIGIN_LABELS && n.key !== 'other'));
    for (const n of fixed) kept.add(stageId(stage, n.key));
    const remaining = candidates.filter(n => !kept.has(stageId(stage, n.key))).sort((a, b) => b.count - a.count || lexical(a.key, b.key));
    // topN counts individual institutions; fixed overseas region groups are additional.
    const individualFixed = fixed.filter(n => !n.key.startsWith('region:')).length;
    for (const n of remaining.slice(0, Math.max(0, topN - individualFixed))) kept.add(stageId(stage, n.key));
  }
  const nodes = new Map<string, FlowNode>();
  const links = new Map<string, FlowLink>();
  const routes = new Map<string, FlowRoute>();
  for (const record of records) {
    const path: string[] = [];
    for (const stage of STAGES) {
      const rawKey = displayKeys.get(record.id)![stage];
      const raw = rawNodes.get(stageId(stage, rawKey))!;
      const keep = kept.has(stageId(stage, rawKey));
      const bucket = raw.region === 'domestic' ? 'domestic' : raw.region === 'unknown' ? 'unknown' : 'foreign';
      const key = keep ? rawKey : `other:${bucket}`;
      const id = stageId(stage, key);
      const label = keep ? raw.label : bucket === 'domestic' ? '기타 국내기관' : bucket === 'foreign' ? '기타 해외기관' : '기타 기관 · 국가 미확인';
      const node = nodes.get(id);
      if (node) { node.count++; node.personIds.push(record.id); }
      else nodes.set(id, { id, key, stage, label, region: raw.region, count: 1, personIds: [record.id] });
      path.push(id);
    }
    for (let i = 0; i < 2; i++) {
      const id = JSON.stringify([path[i], path[i + 1], record.origin, record.selfHire]);
      const link = links.get(id);
      if (link) { link.count++; link.personIds.push(record.id); }
      else links.set(id, { id, source: path[i], target: path[i + 1], origin: record.origin, selfHire: record.selfHire, count: 1, personIds: [record.id] });
    }
    const id = JSON.stringify([record.keys.bachelor, record.keys.phd, record.keys.current]);
    const route = routes.get(id);
    if (route) { route.count++; route.personIds.push(record.id); }
    else routes.set(id, { id, labels: [record.labels.bachelor, record.labels.phd, record.labels.current], origin: record.origin, selfHire: record.selfHire, count: 1, personIds: [record.id] });
  }
  return {
    nodes: [...nodes.values()].sort((a, b) => lexical(a.id, b.id)), links: [...links.values()].sort((a, b) => lexical(a.id, b.id)), records,
    routes: [...routes.values()].sort((a, b) => b.count - a.count || lexical(a.id, b.id)),
    subjectCount: subjectPeople.length, completeCount: complete.length, missingCount: subjectPeople.length - complete.length, duplicateCount,
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
  for (const n of nodes) {
    let out = n.y, into = n.y;
    const outgoing = data.links.filter(l => l.source === n.id).sort((a, b) => nodeMap.get(a.target)!.y - nodeMap.get(b.target)!.y || lexical(a.id, b.id));
    const incoming = data.links.filter(l => l.target === n.id).sort((a, b) => nodeMap.get(a.source)!.y - nodeMap.get(b.source)!.y || lexical(a.id, b.id));
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
