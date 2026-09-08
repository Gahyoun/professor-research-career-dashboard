import { buildResearcherTrajectory, normalizeInstitution } from './constellation/hypergraph.js';
import type { ResearcherRecord, TrajectoryInterval, TrajectoryCoverage } from './constellation/hypergraph.js';
import { isInstitutionSuccession } from './institutionSuccession.js';

export type TemporalOptions = { releaseYear: number; subject?: string; includeEstimated?: boolean; includeInferredDepartments?: boolean };
export type InstitutionYear = {
  year: number; active: number; estimatedOnly: number; inferredDepartmentPeople: number;
  hyperedges: number; singletonUnits: number; meanHyperedgeSize: number | null; largestHyperedge: number;
  jaccard: number | null; turnover: number | null; retained: number;
  hyperedgeContinuity: number | null;
  entries: number | null; exits: number | null; leftCensored: number; rightCensored: number;
  mergerEntries: number; mergerExits: number;
  crossDepartmentPeople: number | null; crossDepartmentShare: number | null;
  stageDiversity: number | null; stages: Record<'doctoral' | 'postdoc' | 'faculty', number>;
};
export type TemporalInstitution = { id: string; label: string; country: string; availablePeople: number; eligiblePeople: number; years: InstitutionYear[] };
export type TemporalData = { institutions: TemporalInstitution[]; cohortPeople: number; eligiblePeople: number; excludedPeople: number; duplicateIds: number; coverage: TrajectoryCoverage };
const schoolKey = (i: TrajectoryInterval) => `${i.country}::${normalizeInstitution(i.institution)}`;
const STAGES = ['doctoral', 'postdoc', 'faculty'] as const;
type AnnualMembership = Map<string, { units: Set<string>; stages: Set<TrajectoryInterval['stage']>; observed: boolean; estimated: boolean; inferred: boolean }>;
export function jaccard(a: ReadonlySet<string>, b: ReadonlySet<string>): number | null {
  let shared = 0; for (const id of a) if (b.has(id)) shared++;
  return a.size + b.size - shared ? shared / (a.size + b.size - shared) : null;
}
export function normalizedStageEntropy(stages: Record<TrajectoryInterval['stage'], number>): number | null {
  const sum = STAGES.reduce((n, s) => n + stages[s], 0);
  return sum ? Math.max(0, -STAGES.reduce((h, s) => { const p = stages[s] / sum; return h + (p ? p * Math.log(p) : 0); }, 0) / Math.log(3)) : null;
}
/** Cauteruccio et al. (2026), Sec. 4.2.1, δ_noa. Institution snapshots replace REN extraction. */
export function nodeOverlapAwareSimilarity(previous: readonly ReadonlySet<string>[], current: readonly ReadonlySet<string>[]): number | null {
  const unique = (groups: readonly ReadonlySet<string>[]) => {
    const deduplicated = new Map<string, ReadonlySet<string>>();
    for (const group of groups) if (group.size >= 2) deduplicated.set(JSON.stringify([...group].sort()), group);
    return [...deduplicated.values()];
  };
  const a = unique(previous), b = unique(current);
  // The paper's max over an empty collection is undefined; do not invent structural evidence.
  if (!a.length || !b.length) return null;
  const maximumOverlap = (source: ReadonlySet<string>[], target: ReadonlySet<string>[]) => source.reduce((sum, e) => {
    let best = 0; for (const f of target) best = Math.max(best, jaccard(e, f) ?? 0);
    return sum + best;
  }, 0);
  return (maximumOverlap(a, b) + maximumOverlap(b, a)) / (a.length + b.length);
}
export function buildTemporalInstitutions(records: readonly ResearcherRecord[], options: TemporalOptions): TemporalData {
  const releaseYear = Math.max(1900, Math.min(3000, Math.floor(options.releaseYear)));
  const seen = new Set<string>(); let duplicateIds = 0;
  const people = records.filter(p => !options.subject || p.subject === options.subject).filter(p => {
    if (!p.id || seen.has(p.id)) { duplicateIds++; return false; } seen.add(p.id); return true;
  });
  const coverage = { totalIntervals: 0, eligibleIntervals: 0, missingInstitutionIntervals: 0, missingCountryIntervals: 0, missingDepartmentIntervals: 0, invalidDateIntervals: 0, excludedEstimatedIntervals: 0, excludedInferredDepartmentIntervals: 0, inferredDepartmentIntervals: 0, unitYears: 0 };
  const catalogue = new Map<string, { label: string; country: string; people: Set<string> }>();
  const membership = new Map<string, Map<number, AnnualMembership>>();
  const observable = new Map<string, Set<number>>();
  // Exact annual records only: succession never fills gaps or extends employment.
  const observedSchools = new Map<string, Map<number, Map<string, { label: string; country: string }>>>();
  const eligiblePeople = new Set<string>();
  for (const p of people) {
    // The permissive catalogue keeps a school selectable when strict filters exclude all its records.
    const possible = buildResearcherTrajectory(p, { includeEstimated: true, includeInferredDepartments: true });
    for (const interval of possible.intervals) {
      if (interval.startYear > releaseYear) continue;
      const key = schoolKey(interval);
      if (!catalogue.has(key)) catalogue.set(key, { label: interval.institution, country: interval.country, people: new Set() });
      catalogue.get(key)!.people.add(p.id);
    }
    const result = buildResearcherTrajectory(p, { includeEstimated: options.includeEstimated ?? true, includeInferredDepartments: options.includeInferredDepartments ?? false });
    for (const k of Object.keys(coverage) as (keyof TrajectoryCoverage)[]) coverage[k] += result.coverage[k];
    for (const i of result.intervals) {
      const end = Math.min(releaseYear, i.endYear);
      if (i.startYear > end) continue;
      eligiblePeople.add(p.id);
      const key = schoolKey(i);
      if (!membership.has(key)) membership.set(key, new Map());
      if (!observable.has(p.id)) observable.set(p.id, new Set());
      if (!observedSchools.has(p.id)) observedSchools.set(p.id, new Map());
      for (let year = i.startYear; year <= end; year++) {
        observable.get(p.id)!.add(year);
        if (!observedSchools.get(p.id)!.has(year)) observedSchools.get(p.id)!.set(year, new Map());
        observedSchools.get(p.id)!.get(year)!.set(key, { label: i.institution, country: i.country });
        if (!membership.get(key)!.has(year)) membership.get(key)!.set(year, new Map());
        const annual = membership.get(key)!.get(year)!;
        if (!annual.has(p.id)) annual.set(p.id, { units: new Set(), stages: new Set(), observed: false, estimated: false, inferred: false });
        const member = annual.get(p.id)!;
        member.units.add(i.unitKey); member.stages.add(i.stage); member.observed ||= !i.estimated; member.estimated ||= i.estimated; member.inferred ||= i.inferredDepartment;
      }
    }
  }
  const institutions: TemporalInstitution[] = [];
  for (const [id, school] of catalogue) {
    const annual = membership.get(id) ?? new Map<number, AnnualMembership>();
    const unique = new Set([...annual.values()].flatMap(a => [...a.keys()]));
    const start = annual.size ? Math.min(...annual.keys()) : releaseYear;
    const years: InstitutionYear[] = [];
    let previous = new Set<string>();
    let previousGroups: Set<string>[] = [];
    for (let year = start; annual.size && year <= releaseYear; year++) {
      const active: AnnualMembership = annual.get(year) ?? new Map();
      const current = new Set<string>(active.keys());
      const units = new Map<string, Set<string>>();
      const stages = { doctoral: 0, postdoc: 0, faculty: 0 };
      let estimatedOnly = 0, inferredDepartmentPeople = 0, crossDepartmentPeople = 0;
      for (const [pid, member] of active) {
        for (const unit of member.units) { if (!units.has(unit)) units.set(unit, new Set()); units.get(unit)!.add(pid); }
        for (const stage of member.stages) stages[stage] += 1 / member.stages.size;
        if (!member.observed && member.estimated) estimatedOnly++;
        if (member.inferred) inferredDepartmentPeople++;
        if (member.units.size >= 2) crossDepartmentPeople++;
      }
      let retained = 0, entries = 0, exits = 0, mergerEntries = 0, mergerExits = 0, leftCensored = 0, rightCensored = 0;
      const successionAt = (pid: string, observationYear: number, entering: boolean) =>
        [...(observedSchools.get(pid)?.get(observationYear) ?? new Map()).entries()]
          .some(([otherId, other]) => otherId !== id && school.country === 'KR' && other.country === school.country &&
            isInstitutionSuccession(entering ? other.label : school.label, entering ? school.label : other.label, year));
      for (const pid of current) {
        if (previous.has(pid)) retained++;
        else if (successionAt(pid, year - 1, true)) mergerEntries++;
        else if (year > start && observable.get(pid)?.has(year - 1)) entries++;
        else leftCensored++;
      }
      for (const pid of previous) if (!current.has(pid)) {
        if (successionAt(pid, year, false)) mergerExits++;
        else if (observable.get(pid)?.has(year)) exits++;
        else rightCensored++;
      }
      const sizes = [...units.values()].map(u => u.size), multi = sizes.filter(n => n >= 2);
      const similarity = year === start ? null : jaccard(previous, current);
      const currentGroups = [...units.values()].filter(group => group.size >= 2);
      years.push({ year, active: current.size, estimatedOnly, inferredDepartmentPeople,
        hyperedges: multi.length, singletonUnits: sizes.filter(n => n === 1).length,
        meanHyperedgeSize: multi.length ? multi.reduce((a, b) => a + b, 0) / multi.length : null,
        largestHyperedge: multi.length ? Math.max(...multi) : 0, jaccard: similarity, turnover: similarity === null ? null : 1 - similarity,
        hyperedgeContinuity: year === start ? null : nodeOverlapAwareSimilarity(previousGroups, currentGroups),
        retained, entries: year === start ? null : entries, exits: year === start ? null : exits, mergerEntries, mergerExits, leftCensored, rightCensored,
        crossDepartmentPeople,
        crossDepartmentShare: current.size ? crossDepartmentPeople / current.size : null,
        stageDiversity: normalizedStageEntropy(stages), stages });
      previous = current;
      previousGroups = currentGroups;
    }
    institutions.push({ id, label: school.label, country: school.country, availablePeople: school.people.size, eligiblePeople: unique.size, years });
  }
  institutions.sort((a, b) => a.label.localeCompare(b.label, 'ko') || a.id.localeCompare(b.id));
  return { institutions, cohortPeople: people.length, eligiblePeople: eligiblePeople.size, excludedPeople: people.length - eligiblePeople.size, duplicateIds, coverage };
}

export const TEMPORAL_SOURCES = [
  { id: 'ren', year: 2026, authors: 'Cauteruccio, Citraro, Failla & Rossetti', title: 'Structure and dynamics of temporal hypergraphs via multi-rooted ego networks', journal: 'Social Network Analysis and Mining 16, 64', url: 'https://doi.org/10.1007/s13278-026-01603-6', note: '선정 방법. §4.2.1의 구성원 겹침 기반 δNOA 수식을 실제로 계산합니다. REN 추출 대신 기관별 연간 그룹 집합을 비교합니다.' },
  { id: 'rhem', year: 2025, authors: 'Lerner, Hâncean & Perc', title: 'Modeling temporal hypergraphs', journal: 'Journal of Complex Networks 13, cnaf054', url: 'https://doi.org/10.1093/comnet/cnaf054', note: '시간적 의존성을 평가하려면 적절한 귀무모형이 필요하다는 근거. 이 페이지는 RHEM 검정이나 유의성 판정을 수행하지 않습니다.' },
  { id: 'memory', year: 2024, authors: 'Gallo, Lacasa, Latora & Battiston', title: 'Higher-order correlations reveal complex memory in temporal hypergraphs', journal: 'Nature Communications 15, 4754', url: 'https://doi.org/10.1038/s41467-024-48578-6', note: '시간에 따라 구성원이 달라지는 그룹을 하이퍼엣지로 다루는 근거. 여기의 연간 지속성을 논문의 고차 기억 상관함수와 동일시하지 않습니다.' },
  { id: 'cores', year: 2024, authors: 'Mancastroppa, Iacopini, Petri & Barrat', title: 'The structural evolution of temporal hypergraphs through the lens of hyper-cores', journal: 'EPJ Data Science 13, 50', url: 'https://doi.org/10.1140/epjds/s13688-024-00490-1', note: '그룹 규모와 구조의 시간 변화를 함께 읽는 근거. 이 페이지는 hyper-core 분해 점수나 기관 순위를 계산하지 않습니다.' },
] as const;

export const TEMPORAL_METHOD_COMPARISON = [
  { id: 'ren', selected: true, method: '구성원 겹침 기반 그룹 유사도 · δNOA', requirement: '연속 시점의 그룹 구성원 집합', fit: '연간 기관·학과 집합을 직접 비교할 수 있습니다. 일부 구성원이 달라지거나 그룹이 나뉘어도 연속성을 수치화합니다.', limit: '구성원 겹침만 비교하며, 그룹 변화의 원인이나 실제 교류를 식별하지 않습니다.' },
  { id: 'memory', selected: false, method: '차수 내·차수 간 시간 상관과 기억', requirement: '여러 시차·그룹 크기에 걸친 충분한 시간적 변동', fit: '이 명부의 연간 구간 확장만으로 생기는 연속성과 실제 상호작용의 기억을 구별하기 어렵습니다.', limit: '현재 자료에 바로 적용하면 추정 경력 길이가 기억 신호를 만들 수 있어 채택하지 않았습니다.' },
  { id: 'cores', selected: false, method: '시간별 (k,m)-hyper-core 구조와 안정성', requirement: '한 시점에서 여러 그룹에 중첩 참여하는 충분한 구조', fit: '학교·학과 소속은 거의 분할 구조이고 동시 소속 정보가 불완전해 core 깊이의 차이가 제한적입니다.', limit: '이 자료에서는 규모·기록 누락에 민감한 기관 서열로 오해될 수 있어 주지표로 채택하지 않았습니다.' },
] as const;
