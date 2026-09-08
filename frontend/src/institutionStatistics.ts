import type { Professor } from './types';
import { canonicalSchool } from './schoolIdentity';
import { INSTITUTION_SUCCESSIONS, isInstitutionSuccession } from './institutionSuccession';

export type CountShare = { label: string; count: number; share: number | null };
export type OriginSummary = {
  total: number; schools: CountShare[]; countries: CountShare[];
  domestic: number; foreign: number; unknownCountry: number; unknownSchool: number;
  foreignShareBounds: { lower: number; upper: number } | null;
  validPhdYears: number; missingOrInvalidPhdYears: number;
  medianPhdYear: number | null; q1PhdYear: number | null; q3PhdYear: number | null;
};
export type InstitutionMovement = {
  comparable: boolean; reason: string; previousYear: number | null; previousCount: number | null;
  retained: number | null; added: number | null; removed: number | null;
  movesIn: number | null; movesOut: number | null; mergerIn: number | null; mergerOut: number | null;
  priorUnobserved: number | null; nextUnobserved: number | null;
  ambiguousIn: number | null; ambiguousOut: number | null;
  sources: CountShare[]; destinations: CountShare[];
};
export type InstitutionYearStatistics = {
  year: number; count: number; totalObservedPeople: number; shareOfObserved: number | null;
  change: number | null; subjects: CountShare[]; origins: OriginSummary; movement: InstitutionMovement;
};
export type InstitutionSeries = { id: string; label: string; country: string | null; years: InstitutionYearStatistics[] };
export type AnnualRosterCoverage = { year: number; people: number; institutions: number; unresolvedInstitutionPeople: number; subjects: CountShare[] };
export type InstitutionStatistics = {
  institutions: InstitutionSeries[]; years: number[]; term: RosterTerm;
  coverage: { releasePeople: number; observedPeople: number; excludedPeople: number;
    duplicateIds: number; ignoredAppointmentRows: number; missingInstitutionRows: number; missingTermRows: number;
    annual: AnnualRosterCoverage[] };
};
export type RosterTerm = 'spring' | 'fall';
export type InstitutionStatisticsOptions = { releaseYear: number; subject?: string; term?: RosterTerm };

const UNKNOWN = '정보 없음';
const UNRESOLVED_INSTITUTION = '\u0000unresolved-institution';
const key = (value: string) => value.normalize('NFKC').trim().toLowerCase().replace(/[–—−]/g, '-').replace(/\s+/g, ' ');
const validYear = (value: unknown, last: number): value is number => typeof value === 'number' && Number.isInteger(value) && value >= 1900 && value <= last;
function school(value: string | null | undefined): string | null {
  const label = canonicalSchool(value);
  return label && !/^(unknown|none|null|n\/a|미상|정보 없음|미분류)$/i.test(label) ? label : null;
}
function country(value: string | null | undefined): string | null {
  const normalized = value?.trim().toUpperCase();
  return normalized && /^[A-Z]{2}$/.test(normalized) && !['XX', 'ZZ'].includes(normalized) ? normalized : null;
}
/** Stable series IDs distinguish institutional succession from a mere display-name change. */
function statisticalSchool(original: string, year: number, releaseYear: number): { id: string; label: string } {
  const rule = INSTITUTION_SUCCESSIONS.find(r => r.names.some(name => key(name) === key(original)));
  if (!rule) return { id: key(original), label: original };
  const predecessor = rule.predecessorNames.some(name => key(name) === key(original));
  if (predecessor && year < rule.effectiveYear) return { id: `${rule.id}:predecessor`, label: rule.predecessorNames[0] };
  return { id: `${rule.id}:anchor`, label: releaseYear >= rule.effectiveYear ? rule.label : rule.seriesAnchorLabel };
}
function shares(counts: Map<string, number>, total: number): CountShare[] {
  return [...counts].map(([label, count]) => ({ label, count, share: total ? count / total : null }))
    .sort((a, b) => b.count - a.count || a.label.localeCompare(b.label));
}
const increment = (counts: Map<string, number>, label: string) => counts.set(label, (counts.get(label) ?? 0) + 1);

/** Linear-interpolated empirical quantiles, h=(n-1)p; descriptive, not a confidence interval. */
export function empiricalQuantile(sorted: readonly number[], probability: number): number | null {
  if (!sorted.length) return null;
  const index = (sorted.length - 1) * Math.min(1, Math.max(0, probability));
  const lower = Math.floor(index), upper = Math.ceil(index);
  return sorted[lower] + (sorted[upper] - sorted[lower]) * (index - lower);
}

function originSummary(people: readonly Professor[], year: number): OriginSummary {
  const schools = new Map<string, number>(), countries = new Map<string, number>(), phdYears: number[] = [];
  let domestic = 0, foreign = 0, unknownCountry = 0, unknownSchool = 0;
  for (const person of people) {
    // Historical degree institutions are not replaced by present-day merger names.
    const degreeSchool = school(person.phd_institution_canonical || person.phd_institution);
    const degreeCountry = country(person.phd_country);
    increment(schools, degreeSchool ?? UNKNOWN); increment(countries, degreeCountry ?? UNKNOWN);
    if (!degreeSchool) unknownSchool++;
    if (!degreeCountry) unknownCountry++; else if (degreeCountry === 'KR') domestic++; else foreign++;
    if (validYear(person.phd_year, year)) phdYears.push(person.phd_year);
  }
  phdYears.sort((a, b) => a - b);
  return { total: people.length, schools: shares(schools, people.length), countries: shares(countries, people.length),
    domestic, foreign, unknownCountry, unknownSchool,
    foreignShareBounds: people.length ? { lower: foreign / people.length, upper: (foreign + unknownCountry) / people.length } : null,
    validPhdYears: phdYears.length,
    missingOrInvalidPhdYears: people.length - phdYears.length, medianPhdYear: empiricalQuantile(phdYears, .5),
    q1PhdYear: empiricalQuantile(phdYears, .25), q3PhdYear: empiricalQuantile(phdYears, .75) };
}

function unavailableMovement(reason: string, previousYear: number | null): InstitutionMovement {
  return { comparable: false, reason, previousYear, previousCount: null, retained: null, added: null, removed: null,
    movesIn: null, movesOut: null, mergerIn: null, mergerOut: null, priorUnobserved: null, nextUnobserved: null,
    ambiguousIn: null, ambiguousOut: null, sources: [], destinations: [] };
}

/** Same-semester source observations only. No inferred careers, department gates, or population extrapolation. */
export function buildInstitutionStatistics(records: readonly Professor[], options: InstitutionStatisticsOptions): InstitutionStatistics {
  const term = options.term ?? 'spring';
  const distinct = new Map<string, Professor>();
  let duplicateIds = 0;
  for (const person of records) {
    if (typeof person.id !== 'string' || !person.id.trim()) continue;
    if (distinct.has(person.id)) { duplicateIds++; continue; }
    distinct.set(person.id, person);
  }
  const people = [...distinct.values()].filter(p => !options.subject || p.subject === options.subject);
  const byId = new Map(people.map(p => [p.id, p]));
  // year -> researcher -> observed institution IDs; these IDs never enter returned aggregates.
  const roster = new Map<number, Map<string, Set<string>>>();
  const catalogue = new Map<string, { label: string; countries: Set<string> }>();
  const observedPeople = new Set<string>();
  let ignoredAppointmentRows = 0, missingInstitutionRows = 0, missingTermRows = 0;
  for (const person of people) for (const row of person.faculty_appointments ?? []) {
    if (row.evidence_kind !== 'semester_roster' || row.evidence_status !== 'observed' || row.role !== 'faculty' ||
        !validYear(row.start_year, options.releaseYear) || row.start_year !== row.end_year) {
      ignoredAppointmentRows++; continue;
    }
    const terms = row.observed_terms;
    if (!Array.isArray(terms) || !terms.length || terms.some(t => typeof t !== 'string' || !new RegExp(`^${row.start_year}-(spring|fall)$`).test(t))) {
      missingTermRows++; continue;
    }
    if (!terms.includes(`${row.start_year}-${term}`)) continue;
    if (!roster.has(row.start_year)) roster.set(row.start_year, new Map());
    const annual = roster.get(row.start_year)!;
    if (!annual.has(person.id)) annual.set(person.id, new Set());
    observedPeople.add(person.id);
    const originalSchool = school(row.institution_canonical || row.institution);
    if (!originalSchool) { missingInstitutionRows++; annual.get(person.id)!.add(UNRESOLVED_INSTITUTION); continue; }
    const { id: institutionId, label } = statisticalSchool(originalSchool, row.start_year, options.releaseYear);
    if (!catalogue.has(institutionId)) catalogue.set(institutionId, { label, countries: new Set() });
    const observedCountry = country(row.country);
    if (observedCountry) catalogue.get(institutionId)!.countries.add(observedCountry);
    annual.get(person.id)!.add(institutionId); observedPeople.add(person.id);
  }
  const years = [...roster.keys()].sort((a, b) => a - b);
  const coverage: InstitutionStatistics['coverage'] = { releasePeople: people.length, observedPeople: observedPeople.size,
    excludedPeople: people.length - observedPeople.size, duplicateIds, ignoredAppointmentRows, missingInstitutionRows, missingTermRows,
    annual: years.map(year => {
      const annual = roster.get(year)!; const institutions = new Set<string>(); const subjects = new Map<string, number>();
      let unresolvedInstitutionPeople = 0;
      for (const [id, units] of annual) {
        increment(subjects, byId.get(id)!.subject || UNKNOWN);
        if (units.has(UNRESOLVED_INSTITUTION)) unresolvedInstitutionPeople++;
        units.forEach(unit => { if (unit !== UNRESOLVED_INSTITUTION) institutions.add(unit); });
      }
      return { year, people: annual.size, institutions: institutions.size, unresolvedInstitutionPeople, subjects: shares(subjects, annual.size) };
    }) };
  const fieldCoverage = new Map(coverage.annual.map(y => [y.year, y.subjects.map(s => s.label).sort().join('|')]));
  const members = (annual: Map<string, Set<string>>, institutionId: string) => new Set([...annual].filter(([, units]) => units.has(institutionId)).map(([id]) => id));
  const institutions = [...catalogue].map(([institutionId, unit]): InstitutionSeries => ({
    id: institutionId, label: unit.label, country: unit.countries.size === 1 ? [...unit.countries][0] : null,
    years: years.map(year => {
      const current = roster.get(year)!, currentIds = members(current, institutionId);
      const currentPeople = [...currentIds].map(id => byId.get(id)!);
      const subjectCounts = new Map<string, number>(); currentPeople.forEach(p => increment(subjectCounts, p.subject || UNKNOWN));
      const previous = roster.get(year - 1);
      let movement: InstitutionMovement;
      if (!previous) movement = unavailableMovement('전년도 같은 학기의 명부가 없습니다. 관측 공백을 연결하지 않습니다.', null);
      else if (fieldCoverage.get(year - 1) !== fieldCoverage.get(year)) movement = unavailableMovement('전후 연도의 수집 분야가 달라 증감과 이동을 비교하지 않습니다. 같은 분야로 좁혀 살펴볼 수 있습니다.', year - 1);
      else {
        const previousIds = members(previous, institutionId);
        const added = [...currentIds].filter(id => !previousIds.has(id)), removed = [...previousIds].filter(id => !currentIds.has(id));
        movement = { comparable: true, reason: '전년도 같은 학기와 같은 분야 범위의 관측 기록을 비교합니다. 기관별 수집 완전성은 보장되지 않습니다.',
          previousYear: year - 1, previousCount: previousIds.size, retained: currentIds.size - added.length,
          added: added.length, removed: removed.length, movesIn: 0, movesOut: 0, mergerIn: 0, mergerOut: 0,
          priorUnobserved: 0, nextUnobserved: 0, ambiguousIn: 0, ambiguousOut: 0, sources: [], destinations: [] };
        const sources = new Map<string, number>(), destinations = new Map<string, number>();
        for (const id of added) {
          const prior = previous.get(id), next = current.get(id)!;
          if (!prior?.size) movement.priorUnobserved!++;
          else if (prior.size !== 1 || next.size !== 1 || prior.has(UNRESOLVED_INSTITUTION) || next.has(UNRESOLVED_INSTITUTION)) movement.ambiguousIn!++;
          else {
            const from = catalogue.get([...prior][0])!.label;
            if (isInstitutionSuccession(from, unit.label, year)) movement.mergerIn!++;
            else { movement.movesIn!++; increment(sources, from); }
          }
        }
        for (const id of removed) {
          const prior = previous.get(id)!, next = current.get(id);
          if (!next?.size) movement.nextUnobserved!++;
          else if (prior.size !== 1 || next.size !== 1 || prior.has(UNRESOLVED_INSTITUTION) || next.has(UNRESOLVED_INSTITUTION)) movement.ambiguousOut!++;
          else {
            const to = catalogue.get([...next][0])!.label;
            if (isInstitutionSuccession(unit.label, to, year)) movement.mergerOut!++;
            else { movement.movesOut!++; increment(destinations, to); }
          }
        }
        movement.sources = shares(sources, movement.movesIn!); movement.destinations = shares(destinations, movement.movesOut!);
      }
      return { year, count: currentIds.size, totalObservedPeople: current.size, shareOfObserved: current.size ? currentIds.size / current.size : null,
        change: movement.comparable ? currentIds.size - movement.previousCount! : null,
        subjects: shares(subjectCounts, currentPeople.length), origins: originSummary(currentPeople, year), movement };
    }),
  })).sort((a, b) => a.label.localeCompare(b.label));
  return { institutions, years, term, coverage };
}
