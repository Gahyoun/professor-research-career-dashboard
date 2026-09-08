/** Sparse researcher hypergraph; no names, URLs, or identity-bearing profiles are copied. */
export interface ResearcherRecord {
  id: string;
  subject?: string;
  phd_institution?: string | null;
  bachelor_institution?: string | null;
  phd_institution_canonical?: string | null;
  bachelor_institution_canonical?: string | null;
  phd_country?: string | null;
  bachelor_country?: string | null;
  phd_department?: string | null;
  bachelor_department?: string | null;
  phd_department_inferred?: boolean;
  bachelor_department_inferred?: boolean;
  phd_year?: number | null;
  faculty_appointments?: readonly FacultyAppointment[];
  current_position?: CurrentPosition | null;
  career?: readonly {
    stage: string;
    start_year: number | null;
    end_year: number | null;
    is_estimated: boolean;
    institution?: string | null;
    institution_canonical?: string | null;
    country?: string | null;
    department?: string | null;
    department_inferred?: boolean;
    evidence_basis?: string | null;
  }[];
}

export interface HypergraphOptions {
  spatialEnabled?: boolean;
  temporalEnabled?: boolean;
  institutionLevel?: 'phd' | 'bachelor';
  estimatedYears?: number;
  includeEstimated?: boolean;
  spatialWeight?: number;
  temporalWeight?: number;
  includeInferredDepartments?: boolean;
  bachelorTemporalEnabled?: boolean;
  bachelorStartOffset?: number;
  bachelorEndOffset?: number;
  cohortEnabled?: boolean;
}

export interface Hyperedge {
  id: string;
  kind: 'spatial' | 'temporal' | 'cohort';
  degree?: 'bachelor' | 'phd';
  label: string;
  members: number[];
  years?: number[];
  institution?: string;
  department?: string;
  country?: string;
  inferredDepartment?: boolean;
  lifetimeStage?: 'doctoral' | 'postdoc' | 'first_faculty' | 'current';
  condition?: string;
  startYear?: number;
  endYear?: number;
  estimated?: boolean;
  temporalSemantics?: 'selected_interval_union';
  memberEvidence?: LifetimeLinkEvidence[];
  weight: number;
  sizeAdjustment: number;
  overlapAdjustment: number;
}

export interface Hypergraph {
  nodes: { id: string; subject: string; layoutYear?: number }[];
  edges: Hyperedge[];
  incidence: number[][];
  timeWindows: { nodeIndex: number; startYear: number; endYear: number; estimated: boolean; degree?: 'bachelor' | 'phd' }[];
  diagnostics: {
    inputCount: number;
    duplicateIdsCount: number;
    invalidIdsCount: number;
    nodeCount: number;
    spatialEdgeCount: number;
    temporalEdgeCount: number;
    cohortEdgeCount: number;
    bachelorTemporalEdgeCount: number;
    estimatedBachelorCount: number;
    annualTemporalSetCount: number;
    mergedTemporalSetCount: number;
    missingInstitutionCount: number;
    missingCountryCount: number;
    missingDepartmentCount: number;
    excludedInferredDepartmentCount: number;
    inferredDepartmentCount: number;
    spatialEligibleCount: number;
    missingTimeCount: number;
    actualTimeCount: number;
    estimatedCount: number;
    excludedEstimatedCount: number;
    invalidIntervalsCount: number;
    isolatedCount: number;
    incidenceCount: number;
  };
}

export interface LayoutOptions {
  width?: number;
  height?: number;
  padding?: number;
  minDistance?: number;
  iterations?: number;
  restarts?: number;
  onProgress?: (progress: { phase: 'spectral' | 'overlap'; progress: number }) => void;
  chronologicalStrength?: number;
}

export interface HypergraphLayout {
  positions: { id: string; x: number; y: number }[];
  diagnostics: {
    method: string;
    objective: number;
    candidateObjectives: number[];
    iterations: number;
    restarts: number;
    components: number;
    collisionPairs: number;
    requestedMinDistance: number;
    effectiveMinDistance: number;
    chronologicalStrength: number;
    elapsedMs: number;
  };
}

const missingInstitutions = new Set([
  '', '-', '—', 'na', 'n/a', 'n a', 'nan', 'none', 'null', 'unknown', 'not available',
  '미상', '알수없음', '알 수 없음', '정보없음', '정보 없음', '없음', '불명',
]);

/** Conservative typographic normalization; deliberately does not guess institution aliases. */
export function normalizeInstitution(value: string | null | undefined): string | null {
  if (typeof value !== 'string') return null;
  if (/^[\d\s.]+$/.test(value.normalize('NFKC'))) return null;
  const normalized = value.normalize('NFKC').trim().toLocaleLowerCase('en-US')
    .replace(/[.,·]/g, ' ').replace(/\s+/g, ' ').trim();
  return missingInstitutions.has(normalized) ? null : normalized;
}

const countryCodes = new Set('AD AE AF AG AI AL AM AO AQ AR AS AT AU AW AX AZ BA BB BD BE BF BG BH BI BJ BL BM BN BO BQ BR BS BT BV BW BY BZ CA CC CD CF CG CH CI CK CL CM CN CO CR CU CV CW CX CY CZ DE DJ DK DM DO DZ EC EE EG EH ER ES ET FI FJ FK FM FO FR GA GB GD GE GF GG GH GI GL GM GN GP GQ GR GS GT GU GW GY HK HM HN HR HT HU ID IE IL IM IN IO IQ IR IS IT JE JM JO JP KE KG KH KI KM KN KP KR KW KY KZ LA LB LC LI LK LR LS LT LU LV LY MA MC MD ME MF MG MH MK ML MM MN MO MP MQ MR MS MT MU MV MW MX MY MZ NA NC NE NF NG NI NL NO NP NR NU NZ OM PA PE PF PG PH PK PL PM PN PR PS PT PW PY QA RE RO RS RU RW SA SB SC SD SE SG SH SI SJ SK SL SM SN SO SR SS ST SV SX SY SZ TC TD TF TG TH TJ TK TL TM TN TO TR TT TV TW TZ UA UG UM US UY UZ VA VC VE VG VI VN VU WF WS YE YT ZA ZM ZW'.split(' '));
const countryAliases: Record<string, string> = {
  korea: 'KR', 'south korea': 'KR', 'republic of korea': 'KR', 'korea republic of': 'KR', kor: 'KR', 한국: 'KR', 대한민국: 'KR',
  'united states': 'US', 'united states of america': 'US', usa: 'US', america: 'US', 미국: 'US',
  'united kingdom': 'GB', uk: 'GB', britain: 'GB', england: 'GB', gbr: 'GB', 영국: 'GB',
  japan: 'JP', jpn: 'JP', 일본: 'JP', germany: 'DE', deu: 'DE', 독일: 'DE', india: 'IN', ind: 'IN',
  canada: 'CA', can: 'CA', france: 'FR', fra: 'FR', sweden: 'SE', swe: 'SE', australia: 'AU', aus: 'AU',
  netherlands: 'NL', nld: 'NL', israel: 'IL', isr: 'IL', austria: 'AT', aut: 'AT', italy: 'IT', ita: 'IT',
  poland: 'PL', pol: 'PL', spain: 'ES', esp: 'ES', russia: 'RU', rus: 'RU', switzerland: 'CH', che: 'CH',
  serbia: 'RS', srb: 'RS', china: 'CN', chn: 'CN', belgium: 'BE', bel: 'BE', norway: 'NO', nor: 'NO',
  'new zealand': 'NZ', nzl: 'NZ', hungary: 'HU', hun: 'HU', uzbekistan: 'UZ', uzb: 'UZ',
  'hong kong': 'HK', hkg: 'HK', taiwan: 'TW', taipei: 'TW', twn: 'TW', singapore: 'SG', sgp: 'SG',
};

export function normalizeCountry(country: string | null | undefined): string | null {
  if (typeof country !== 'string') return null;
  const value = country.normalize('NFKC').trim().toLowerCase().replace(/[.,]/g, ' ').replace(/\s+/g, ' ').trim();
  return countryCodes.has(value.toUpperCase()) ? value.toUpperCase() : countryAliases[value] ?? null;
}

export interface InstitutionUnit {
  institution?: string | null;
  institution_canonical?: string | null;
  country?: string | null;
  department?: string | null;
  department_inferred?: boolean;
}

export type EmploymentEvidenceKind = 'semester_roster' | 'official_profile' | 'verified_cv';
export interface FacultyAppointment extends InstitutionUnit {
  start_year: number | null;
  end_year: number | null;
  role: 'faculty';
  evidence_kind: EmploymentEvidenceKind;
  evidence_status: 'observed' | 'verified';
  rank?: 'assistant_professor' | 'associate_professor' | 'professor';
  first_assistant_professor_verified?: boolean;
}
export interface CurrentPosition extends InstitutionUnit {
  observation_year: number | null;
  evidence_kind: EmploymentEvidenceKind;
  evidence_status: 'observed' | 'verified';
}
export interface LifetimeLinkEvidence {
  peerId: string;
  unitKey: string;
  institution: string;
  department?: string;
  country: string;
  selectedStage: 'doctoral' | 'postdoc' | 'first_faculty' | 'current';
  peerStage: 'doctoral' | 'postdoc' | 'faculty' | 'current';
  startYear: number;
  endYear: number;
  selectedStartYear: number;
  selectedEndYear: number;
  peerStartYear: number;
  peerEndYear: number;
  estimated: boolean;
  inferredDepartment: boolean;
  basis: string[];
}

/** Every educational unit requires its own department, irrespective of country. */
export function institutionKey(unit: InstitutionUnit, options: { includeInferredDepartments?: boolean } = {}): string | null {
  const institution = normalizeInstitution(unit.institution_canonical) ?? normalizeInstitution(unit.institution);
  const country = normalizeCountry(unit.country);
  if (!institution || !country) return null;
  const department = normalizeInstitution(unit.department);
  if (!department || (unit.department_inferred && !options.includeInferredDepartments)) return null;
  return `${country}::${institution}::${department}`;
}

function validYear(year: unknown): year is number {
  return typeof year === 'number' && Number.isInteger(year) && year >= 1000 && year <= 3000;
}

function doctoralStage(stage: string): boolean {
  const s = stage.toLowerCase().replace(/[\s._-]+/g, '');
  return !/postdoc|박사후/.test(s) && /phd|doctoral|doctorate|박사/.test(s);
}

function positive(value: number | undefined, fallback: number): number {
  return value === undefined || !Number.isFinite(value) ? fallback : Math.max(0, value);
}

function yearLabel(years: readonly number[]): string {
  const runs: string[] = [];
  for (let i = 0; i < years.length; i++) {
    const start = years[i];
    let end = start;
    while (i + 1 < years.length && years[i + 1] === end + 1) end = years[++i];
    runs.push(start === end ? String(start) : `${start}–${end}`);
  }
  return runs.join(', ');
}

export function buildHypergraph(records: readonly ResearcherRecord[], options: HypergraphOptions = {}): Hypergraph {
  const spatialEnabled = options.spatialEnabled !== false && positive(options.spatialWeight, 1) > 0;
  const temporalEnabled = options.temporalEnabled !== false && positive(options.temporalWeight, 1) > 0;
  const estimatedYears = Math.min(40, Math.max(1, Math.round(positive(options.estimatedYears, 5))));
  const includeEstimated = options.includeEstimated !== false;
  const level = options.institutionLevel ?? 'phd';
  const bachelorTemporalEnabled = options.bachelorTemporalEnabled === true && positive(options.temporalWeight, 1) > 0;
  const bachelorStartOffset = Math.min(60, Math.max(0, Math.round(positive(options.bachelorStartOffset, 10))));
  const bachelorEndOffset = Math.min(bachelorStartOffset, Math.max(0, Math.round(positive(options.bachelorEndOffset, 8))));
  const graph: Hypergraph = {
    nodes: [], edges: [], incidence: [], timeWindows: [],
    diagnostics: {
      inputCount: records.length, duplicateIdsCount: 0, invalidIdsCount: 0, nodeCount: 0,
      spatialEdgeCount: 0, temporalEdgeCount: 0, cohortEdgeCount: 0, bachelorTemporalEdgeCount: 0,
      estimatedBachelorCount: 0, annualTemporalSetCount: 0,
      mergedTemporalSetCount: 0, missingInstitutionCount: 0, missingCountryCount: 0,
      missingDepartmentCount: 0, excludedInferredDepartmentCount: 0, inferredDepartmentCount: 0,
      spatialEligibleCount: 0, missingTimeCount: 0,
      actualTimeCount: 0, estimatedCount: 0, excludedEstimatedCount: 0,
      invalidIntervalsCount: 0, isolatedCount: 0, incidenceCount: 0,
    },
  };
  const ids = new Set<string>();
  const institutions = new Map<string, { label: string; institution: string; department?: string; country: string; inferred: boolean; members: number[] }>();
  const annual = new Map<number, number[]>();
  const bachelorAnnual = new Map<number, number[]>();
  const acceptedRecords: ResearcherRecord[] = [];
  for (const record of records) {
    if (typeof record.id !== 'string' || !record.id.trim()) {
      graph.diagnostics.invalidIdsCount++;
      continue;
    }
    if (ids.has(record.id)) {
      graph.diagnostics.duplicateIdsCount++;
      continue;
    }
    ids.add(record.id);
    const nodeIndex = graph.nodes.length;
    graph.nodes.push({ id: record.id, subject: record.subject ?? '',
      ...(validYear(record.phd_year) ? { layoutYear: record.phd_year - (level === 'bachelor' ? bachelorEndOffset : 0) } : {}) });
    acceptedRecords.push(record);
    graph.incidence.push([]);
    const rawInstitution = level === 'phd' ? record.phd_institution : record.bachelor_institution;
    const canonicalInstitution = level === 'phd' ? record.phd_institution_canonical : record.bachelor_institution_canonical;
    const institution = normalizeInstitution(canonicalInstitution) ?? normalizeInstitution(rawInstitution);
    const rawCountry = level === 'phd' ? record.phd_country : record.bachelor_country;
    const country = normalizeCountry(rawCountry);
    const rawDepartment = level === 'phd' ? record.phd_department : record.bachelor_department;
    const department = normalizeInstitution(rawDepartment);
    const inferred = level === 'phd' ? record.phd_department_inferred : record.bachelor_department_inferred;
    const unitKey = institutionKey({ institution: rawInstitution, institution_canonical: canonicalInstitution, country: rawCountry, department: rawDepartment, department_inferred: inferred }, options);
    if (institution === null) graph.diagnostics.missingInstitutionCount++;
    else if (country === null) graph.diagnostics.missingCountryCount++;
    else if (!department) graph.diagnostics.missingDepartmentCount++;
    else if (inferred && !options.includeInferredDepartments) graph.diagnostics.excludedInferredDepartmentCount++;
    if (unitKey) {
      graph.diagnostics.spatialEligibleCount++;
      if (inferred) graph.diagnostics.inferredDepartmentCount++;
      if (spatialEnabled) {
        const schoolLabel = (normalizeInstitution(canonicalInstitution) ? canonicalInstitution : rawInstitution)!.normalize('NFKC').trim().replace(/\s+/g, ' ');
        const departmentLabel = rawDepartment!.normalize('NFKC').trim();
        if (!institutions.has(unitKey)) institutions.set(unitKey, {
          label: departmentLabel ? `${schoolLabel} · ${departmentLabel}` : schoolLabel,
          institution: schoolLabel, department: departmentLabel, country: country!, inferred: false, members: [],
        });
        const group = institutions.get(unitKey)!;
        group.members.push(nodeIndex);
        group.inferred ||= inferred === true;
      }
    }

    if (bachelorTemporalEnabled && includeEstimated && validYear(record.phd_year)) {
      const startYear = record.phd_year - bachelorStartOffset, endYear = record.phd_year - bachelorEndOffset;
      graph.timeWindows.push({ nodeIndex, startYear, endYear, estimated: true, degree: 'bachelor' });
      graph.diagnostics.estimatedBachelorCount++;
      for (let year = startYear; year <= endYear; year++) {
        if (!bachelorAnnual.has(year)) bachelorAnnual.set(year, []);
        bachelorAnnual.get(year)!.push(nodeIndex);
      }
    }

    const actual: { start: number; end: number }[] = [];
    for (const career of record.career ?? []) {
      if (!doctoralStage(career.stage) || career.is_estimated !== false) continue;
      if (!validYear(career.start_year) || !validYear(career.end_year) ||
          career.start_year > career.end_year || career.end_year - career.start_year > 40) {
        graph.diagnostics.invalidIntervalsCount++;
      } else actual.push({ start: career.start_year, end: career.end_year });
    }
    let windows: { start: number; end: number }[];
    let estimated = false;
    if (actual.length) {
      windows = actual;
      graph.diagnostics.actualTimeCount++;
      if (graph.nodes[nodeIndex].layoutYear === undefined) graph.nodes[nodeIndex].layoutYear = Math.max(...actual.map(window => window.end));
    } else if (validYear(record.phd_year)) {
      estimated = true;
      if (!includeEstimated) {
        graph.diagnostics.excludedEstimatedCount++;
        continue;
      }
      windows = [{ start: record.phd_year - estimatedYears, end: record.phd_year }];
      graph.diagnostics.estimatedCount++;
    } else {
      graph.diagnostics.missingTimeCount++;
      continue;
    }
    const years = new Set<number>();
    for (const window of windows) {
      graph.timeWindows.push({ nodeIndex, startYear: window.start, endYear: window.end, estimated, degree: 'phd' });
      for (let year = window.start; year <= window.end; year++) years.add(year);
    }
    if (temporalEnabled) for (const year of years) {
      if (!annual.has(year)) annual.set(year, []);
      annual.get(year)!.push(nodeIndex);
    }
  }

  for (const [key, institution] of [...institutions].sort(([a], [b]) => a.localeCompare(b, 'en'))) {
    if (institution.members.length < 2) continue;
    graph.edges.push({
      id: `spatial:${level}:${key}`, kind: 'spatial', degree: level, label: institution.label,
      institution: institution.institution, department: institution.department, country: institution.country,
      inferredDepartment: institution.inferred, members: institution.members,
      weight: positive(options.spatialWeight, 1), sizeAdjustment: 1, overlapAdjustment: 1,
    });
  }
  const duplicateMemberships = new Map<string, Hyperedge>();
  for (const [year, members] of [...annual].sort(([a], [b]) => a - b)) {
    if (members.length < 2) continue;
    graph.diagnostics.annualTemporalSetCount++;
    const key = members.join(',');
    const existing = duplicateMemberships.get(key);
    if (existing) existing.years!.push(year);
    else {
      const edge: Hyperedge = {
        id: `temporal:phd:${year}`, kind: 'temporal', degree: 'phd', label: '', years: [year], members,
        weight: positive(options.temporalWeight, 1), sizeAdjustment: 1, overlapAdjustment: 1,
      };
      duplicateMemberships.set(key, edge);
      graph.edges.push(edge);
    }
  }
  const bachelorDuplicates = new Map<string, Hyperedge>();
  for (const [year, members] of [...bachelorAnnual].sort(([a], [b]) => a - b)) {
    if (members.length < 2) continue;
    graph.diagnostics.annualTemporalSetCount++;
    const key = members.join(',');
    const existing = bachelorDuplicates.get(key);
    if (existing) existing.years!.push(year);
    else {
      const edge: Hyperedge = { id: `temporal:bachelor:${year}`, kind: 'temporal', degree: 'bachelor',
        label: '', years: [year], members, weight: positive(options.temporalWeight, 1), sizeAdjustment: 1, overlapAdjustment: 1 };
      bachelorDuplicates.set(key, edge); graph.edges.push(edge);
    }
  }
  if (options.cohortEnabled !== false && spatialEnabled) {
    const units = new Map<string, { unit: InstitutionUnit; degree: 'bachelor' | 'phd'; annual: Map<number, Set<number>> }>();
    for (const window of graph.timeWindows) {
      const degree = window.degree ?? 'phd';
      if (degree === 'phd' ? !temporalEnabled : !bachelorTemporalEnabled) continue;
      const record = acceptedRecords[window.nodeIndex];
      const unit: InstitutionUnit = degree === 'phd' ? {
        institution: record.phd_institution, institution_canonical: record.phd_institution_canonical,
        country: record.phd_country, department: record.phd_department, department_inferred: record.phd_department_inferred,
      } : {
        institution: record.bachelor_institution, institution_canonical: record.bachelor_institution_canonical,
        country: record.bachelor_country, department: record.bachelor_department, department_inferred: record.bachelor_department_inferred,
      };
      const key = institutionKey(unit, options);
      if (!key) continue;
      const groupKey = `${degree}:${key}`;
      if (!units.has(groupKey)) units.set(groupKey, { unit, degree, annual: new Map() });
      const group = units.get(groupKey)!;
      if (unit.department_inferred) group.unit.department_inferred = true;
      for (let year = window.startYear; year <= window.endYear; year++) {
        if (!group.annual.has(year)) group.annual.set(year, new Set());
        group.annual.get(year)!.add(window.nodeIndex);
      }
    }
    for (const [unitKey, group] of units) {
      const duplicates = new Map<string, Hyperedge>();
      for (const [year, memberSet] of [...group.annual].sort(([a], [b]) => a - b)) {
        if (memberSet.size < 2) continue;
        const members = [...memberSet].sort((a, b) => a - b), key = members.join(',');
        const existing = duplicates.get(key);
        if (existing) existing.years!.push(year);
        else {
          const country = normalizeCountry(group.unit.country)!;
          const edge: Hyperedge = { id: `cohort:${unitKey}:${year}`, kind: 'cohort', degree: group.degree,
            institution: group.unit.institution_canonical || group.unit.institution || '', country,
            department: group.unit.department ?? undefined,
            inferredDepartment: group.unit.department_inferred === true,
            label: '', years: [year], members,
            weight: Math.sqrt(positive(options.spatialWeight, 1) * positive(options.temporalWeight, 1)),
            sizeAdjustment: 1, overlapAdjustment: 1 };
          duplicates.set(key, edge); graph.edges.push(edge);
        }
      }
    }
  }
  for (let e = 0; e < graph.edges.length; e++) {
    const edge = graph.edges[e];
    if (edge.kind === 'temporal') edge.label = edge.degree === 'bachelor' ? `학부 · ${yearLabel(edge.years!)}` : yearLabel(edge.years!);
    if (edge.kind === 'cohort') edge.label = `${edge.degree === 'bachelor' ? '학부' : '박사'} · ${edge.institution}${edge.department ? ` · ${edge.department}` : ''} · ${yearLabel(edge.years!)}`;
    for (const v of edge.members) graph.incidence[v].push(e);
  }

  // Count shared memberships only among incident edge pairs: no all-pairs researcher matrix.
  // Redundancy is corrected within each evidence type; spatial/time evidence remains distinct.
  const intersections = new Map<number, number>();
  const edgeCount = graph.edges.length;
  for (const incidence of graph.incidence) {
    for (let a = 0; a < incidence.length; a++) for (let b = a + 1; b < incidence.length; b++) {
      const i = incidence[a], j = incidence[b];
      if (graph.edges[i].kind !== graph.edges[j].kind || graph.edges[i].degree !== graph.edges[j].degree) continue;
      const key = i * edgeCount + j;
      intersections.set(key, (intersections.get(key) ?? 0) + 1);
    }
  }
  const redundancy = new Float64Array(edgeCount);
  for (const [key, intersection] of intersections) {
    const i = Math.floor(key / edgeCount), j = key % edgeCount;
    const jaccard = intersection / (graph.edges[i].members.length + graph.edges[j].members.length - intersection);
    redundancy[i] += jaccard;
    redundancy[j] += jaccard;
  }
  for (let i = 0; i < edgeCount; i++) {
    const edge = graph.edges[i];
    edge.sizeAdjustment = 1 / (edge.members.length - 1);
    edge.overlapAdjustment = 1 / (1 + redundancy[i]);
    // De^-1 supplies 1/|e| in the operator. Multiplication by |e| here avoids
    // applying cardinality normalization twice: each pair receives 1/(|e|-1).
    edge.weight *= edge.members.length * edge.sizeAdjustment * edge.overlapAdjustment;
  }
  const d = graph.diagnostics;
  d.nodeCount = graph.nodes.length;
  d.spatialEdgeCount = graph.edges.filter(e => e.kind === 'spatial').length;
  d.temporalEdgeCount = graph.edges.filter(e => e.kind === 'temporal').length;
  d.cohortEdgeCount = graph.edges.filter(e => e.kind === 'cohort').length;
  d.bachelorTemporalEdgeCount = graph.edges.filter(e => e.kind === 'temporal' && e.degree === 'bachelor').length;
  d.mergedTemporalSetCount = d.annualTemporalSetCount - d.temporalEdgeCount;
  d.isolatedCount = graph.incidence.filter(es => es.length === 0).length;
  d.incidenceCount = graph.incidence.reduce((sum, es) => sum + es.length, 0);
  return graph;
}

export interface TrajectoryOptions {
  includeEstimated?: boolean;
  estimatedYears?: number;
  includeInferredDepartments?: boolean;
}

export interface TrajectoryInterval {
  unitKey: string;
  institution: string;
  country: string;
  department?: string;
  stage: 'doctoral' | 'postdoc' | 'faculty';
  startYear: number;
  endYear: number;
  estimated: boolean;
  inferredDepartment: boolean;
}

export interface TrajectoryCoverage {
  totalIntervals: number;
  eligibleIntervals: number;
  missingInstitutionIntervals: number;
  missingCountryIntervals: number;
  missingDepartmentIntervals: number;
  invalidDateIntervals: number;
  excludedEstimatedIntervals: number;
  excludedInferredDepartmentIntervals: number;
  inferredDepartmentIntervals: number;
  unitYears: number;
}

export interface TrajectoryPeer {
  id: string;
  score: number;
  jaccard: number;
  sharedUnitYears: number;
  unionUnitYears: number;
  evidence: {
    unitKey: string;
    institution: string;
    department?: string;
    country: string;
    selectedStage: TrajectoryInterval['stage'];
    peerStage: TrajectoryInterval['stage'];
    startYear: number;
    endYear: number;
    estimated: boolean;
    inferredDepartment: boolean;
  }[];
}

function emptyCoverage(): TrajectoryCoverage {
  return { totalIntervals: 0, eligibleIntervals: 0, missingInstitutionIntervals: 0,
    missingCountryIntervals: 0, missingDepartmentIntervals: 0, invalidDateIntervals: 0,
    excludedEstimatedIntervals: 0, excludedInferredDepartmentIntervals: 0,
    inferredDepartmentIntervals: 0, unitYears: 0 };
}

function trajectoryStage(stage: string): TrajectoryInterval['stage'] | null {
  const s = stage.toLowerCase().replace(/[\s._-]+/g, '');
  if (/postdoc|박사후|포닥/.test(s)) return 'postdoc';
  if (doctoralStage(stage)) return 'doctoral';
  return /faculty|professor|교수/.test(s) ? 'faculty' : null;
}

function intervalTokens(intervals: TrajectoryInterval[]): Set<string> {
  const tokens = new Set<string>();
  for (const interval of intervals) for (let year = interval.startYear; year <= interval.endYear; year++) {
    tokens.add(`${interval.unitKey}\u0000${year}`);
  }
  return tokens;
}

/** Uses only explicit degree/career units. No current department or subject fallback. */
export function buildResearcherTrajectory(record: ResearcherRecord, options: TrajectoryOptions = {}): {
  intervals: TrajectoryInterval[]; coverage: TrajectoryCoverage;
} {
  const intervals: TrajectoryInterval[] = [];
  const coverage = emptyCoverage();
  const estimatedYears = Math.min(40, Math.max(1, Math.round(positive(options.estimatedYears, 5))));
  const actualDoctoral = (record.career ?? []).filter(c => doctoralStage(c.stage) && c.is_estimated === false &&
    validYear(c.start_year) && validYear(c.end_year) && c.start_year <= c.end_year && c.end_year - c.start_year <= 40);
  const add = (stage: TrajectoryInterval['stage'], start: number | null, end: number | null, estimated: boolean, unit: InstitutionUnit) => {
    coverage.totalIntervals++;
    if (!validYear(start) || !validYear(end) || start > end || end - start > 80) { coverage.invalidDateIntervals++; return; }
    if (estimated && options.includeEstimated === false) { coverage.excludedEstimatedIntervals++; return; }
    const institution = normalizeInstitution(unit.institution_canonical) ?? normalizeInstitution(unit.institution), country = normalizeCountry(unit.country);
    if (!institution) { coverage.missingInstitutionIntervals++; return; }
    if (!country) { coverage.missingCountryIntervals++; return; }
    if (!normalizeInstitution(unit.department)) { coverage.missingDepartmentIntervals++; return; }
    if (unit.department_inferred && !options.includeInferredDepartments) { coverage.excludedInferredDepartmentIntervals++; return; }
    const key = institutionKey(unit, options);
    if (!key) return;
    const inferred = unit.department_inferred === true;
    if (inferred) coverage.inferredDepartmentIntervals++;
    intervals.push({ unitKey: key, institution: (normalizeInstitution(unit.institution_canonical) ? unit.institution_canonical : unit.institution)!.trim(), country,
      department: unit.department!.trim(), stage,
      startYear: start, endYear: end, estimated, inferredDepartment: inferred });
    coverage.eligibleIntervals++;
  };
  for (const career of record.career ?? []) {
    const stage = trajectoryStage(career.stage);
    if (!stage || stage === 'doctoral') continue;
    add(stage, career.start_year, career.end_year, career.is_estimated, career);
  }
  if (actualDoctoral.length) {
    for (const career of actualDoctoral) {
      const matchingDegree = !career.institution ||
        (normalizeInstitution(career.institution_canonical) ?? normalizeInstitution(career.institution)) ===
        (normalizeInstitution(record.phd_institution_canonical) ?? normalizeInstitution(record.phd_institution));
      // Transfer degree metadata only for exactly the same recorded doctoral institution.
      const unit = matchingDegree ? {
        institution: career.institution || record.phd_institution,
        institution_canonical: career.institution_canonical || record.phd_institution_canonical,
        country: career.country ?? record.phd_country,
        department: career.department ?? record.phd_department,
        department_inferred: career.department ? career.department_inferred : record.phd_department_inferred,
      } : career;
      add('doctoral', career.start_year, career.end_year, false, unit);
    }
  } else {
    add('doctoral', validYear(record.phd_year) ? record.phd_year - estimatedYears : null, record.phd_year ?? null, true, {
      institution: record.phd_institution, country: record.phd_country,
      institution_canonical: record.phd_institution_canonical,
      department: record.phd_department, department_inferred: record.phd_department_inferred,
    });
  }
  intervals.sort((a, b) => a.startYear - b.startYear || a.endYear - b.endYear || a.unitKey.localeCompare(b.unitKey, 'en'));
  coverage.unitYears = intervalTokens(intervals).size;
  return { intervals, coverage };
}

/** Similarity is Jaccard of distinct (institution unit, calendar year) observations. */
export function findTrajectoryPeers(records: readonly ResearcherRecord[], selectedId: string, options: TrajectoryOptions = {}): {
  selectedId: string; selectedFound: boolean; selectedCoverage: TrajectoryCoverage; peers: TrajectoryPeer[];
} {
  const selected = records.find(record => record.id === selectedId);
  if (!selected) return { selectedId, selectedFound: false, selectedCoverage: emptyCoverage(), peers: [] };
  const trajectory = buildResearcherTrajectory(selected, options);
  const selectedTokens = intervalTokens(trajectory.intervals);
  const peers: TrajectoryPeer[] = [];
  const seen = new Set<string>([selectedId]);
  for (const record of records) {
    if (!record.id || seen.has(record.id)) continue;
    seen.add(record.id);
    const candidate = buildResearcherTrajectory(record, options);
    const tokens = intervalTokens(candidate.intervals);
    let shared = 0;
    for (const token of tokens) if (selectedTokens.has(token)) shared++;
    if (!shared) continue;
    const union = selectedTokens.size + tokens.size - shared;
    const evidence: TrajectoryPeer['evidence'] = [];
    const evidenceKeys = new Set<string>();
    for (const a of trajectory.intervals) for (const b of candidate.intervals) {
      if (a.unitKey !== b.unitKey) continue;
      const startYear = Math.max(a.startYear, b.startYear), endYear = Math.min(a.endYear, b.endYear);
      if (startYear > endYear) continue;
      const key = `${a.unitKey}\u0000${a.stage}\u0000${b.stage}\u0000${startYear}:${endYear}:${a.estimated || b.estimated}:${a.inferredDepartment || b.inferredDepartment}`;
      if (evidenceKeys.has(key)) continue;
      evidenceKeys.add(key);
      evidence.push({ unitKey: a.unitKey, institution: a.institution, department: a.department,
        country: a.country, selectedStage: a.stage, peerStage: b.stage, startYear, endYear,
        estimated: a.estimated || b.estimated, inferredDepartment: a.inferredDepartment || b.inferredDepartment });
    }
    evidence.sort((a, b) => a.startYear - b.startYear || a.endYear - b.endYear);
    peers.push({ id: record.id, score: shared / union, jaccard: shared / union, sharedUnitYears: shared, unionUnitYears: union, evidence });
  }
  peers.sort((a, b) => b.score - a.score || b.sharedUnitYears - a.sharedUnitYears || a.id.localeCompare(b.id, 'en'));
  return { selectedId, selectedFound: true, selectedCoverage: trajectory.coverage, peers };
}

function hash(value: string): number {
  let h = 2166136261;
  for (let i = 0; i < value.length; i++) h = Math.imul(h ^ value.charCodeAt(i), 16777619);
  return h >>> 0;
}

function random(seed: number): () => number {
  let s = seed >>> 0;
  return () => {
    s += 0x6d2b79f5;
    let t = Math.imul(s ^ (s >>> 15), 1 | s);
    t ^= t + Math.imul(t ^ (t >>> 7), 61 | t);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

type LocalEdge = { members: number[]; weight: number };
type Point = { x: number; y: number };

function components(graph: Hypergraph): { nodes: number[]; edges: number[] }[] {
  const parent = Int32Array.from({ length: graph.nodes.length }, (_, i) => i);
  const find = (v: number): number => {
    while (parent[v] !== v) { parent[v] = parent[parent[v]]; v = parent[v]; }
    return v;
  };
  for (const e of graph.edges) for (let i = 1; i < e.members.length; i++) {
    const a = find(e.members[0]), b = find(e.members[i]);
    if (a !== b) parent[b] = a;
  }
  const groups = new Map<number, { nodes: number[]; edges: number[] }>();
  for (let i = 0; i < graph.nodes.length; i++) {
    const root = find(i);
    if (!groups.has(root)) groups.set(root, { nodes: [], edges: [] });
    groups.get(root)!.nodes.push(i);
  }
  for (let e = 0; e < graph.edges.length; e++) groups.get(find(graph.edges[e].members[0]))!.edges.push(e);
  return [...groups.values()].sort((a, b) => b.nodes.length - a.nodes.length || a.nodes[0] - b.nodes[0]);
}

/** Applies Dv^-1/2 H W De^-1 H^T Dv^-1/2 in O(total incidence). */
function diffuse(input: Float64Array, output: Float64Array, edges: LocalEdge[], invSqrt: Float64Array): void {
  output.fill(0);
  for (const edge of edges) {
    let sum = 0;
    for (const i of edge.members) sum += input[i] * invSqrt[i];
    sum *= edge.weight / edge.members.length;
    for (const i of edge.members) output[i] += sum * invSqrt[i];
  }
}

function orthonormalize(vector: Float64Array, stationary: Float64Array, previous?: Float64Array): void {
  // Reorthogonalize twice to prevent stationary-mode leakage on slowly mixing graphs.
  for (let pass = 0; pass < 2; pass++) {
    let projection = 0;
    for (let i = 0; i < vector.length; i++) projection += vector[i] * stationary[i];
    for (let i = 0; i < vector.length; i++) vector[i] -= projection * stationary[i];
    if (previous) {
      projection = 0;
      for (let i = 0; i < vector.length; i++) projection += vector[i] * previous[i];
      for (let i = 0; i < vector.length; i++) vector[i] -= projection * previous[i];
    }
  }
  let norm = 0;
  for (const value of vector) norm += value * value;
  norm = Math.sqrt(norm);
  if (norm > 1e-15) for (let i = 0; i < vector.length; i++) vector[i] /= norm;
}

function sunflower(n: number): Point[] {
  return Array.from({ length: n }, (_, i) => {
    const radius = Math.sqrt((i + 0.5) / n);
    const angle = i * 2.399963229728653;
    return { x: radius * Math.cos(angle), y: radius * Math.sin(angle) };
  });
}

function spectral(nodes: number[], edgeIndices: number[], graph: Hypergraph, iterations: number, restarts: number) {
  const n = nodes.length;
  if (n <= 2 || edgeIndices.length <= 1) return {
    points: sunflower(n), objectives: Array(restarts).fill(edgeIndices.length ? Math.min(2, n - 1) : 0) as number[],
  };
  const index = new Map(nodes.map((v, i) => [v, i]));
  const edges = edgeIndices.map(e => ({
    weight: graph.edges[e].weight, members: graph.edges[e].members.map(v => index.get(v)!),
  }));
  const degree = new Float64Array(n);
  for (const edge of edges) for (const i of edge.members) degree[i] += edge.weight;
  const total = degree.reduce((a, b) => a + b, 0);
  const stationary = degree.map(d => Math.sqrt(d / total));
  const invSqrt = degree.map(d => 1 / Math.sqrt(d));
  let bestObjective = Infinity;
  let bestX = new Float64Array(n), bestY = new Float64Array(n);
  const objectives: number[] = [];
  const seed = nodes.reduce((h, v) => (h ^ hash(graph.nodes[v].id)) >>> 0, 37139);
  for (let run = 0; run < restarts; run++) {
    const rng = random(seed + run * 49999);
    let x = Float64Array.from({ length: n }, () => rng() - 0.5);
    let y = Float64Array.from({ length: n }, () => rng() - 0.5);
    let nextX = new Float64Array(n), nextY = new Float64Array(n);
    orthonormalize(x, stationary);
    orthonormalize(y, stationary, x);
    for (let step = 0; step < iterations; step++) {
      diffuse(x, nextX, edges, invSqrt);
      diffuse(y, nextY, edges, invSqrt);
      // Lazy diffusion preserves eigenvectors and stabilizes rank-deficient components.
      for (let i = 0; i < n; i++) { nextX[i] = 0.9 * nextX[i] + 0.1 * x[i]; nextY[i] = 0.9 * nextY[i] + 0.1 * y[i]; }
      orthonormalize(nextX, stationary);
      orthonormalize(nextY, stationary, nextX);
      [x, nextX] = [nextX, x]; [y, nextY] = [nextY, y];
    }
    diffuse(x, nextX, edges, invSqrt); diffuse(y, nextY, edges, invSqrt);
    let objective = 2;
    for (let i = 0; i < n; i++) objective -= x[i] * nextX[i] + y[i] * nextY[i];
    objective = Math.max(0, objective);
    objectives.push(objective);
    if (objective < bestObjective) { bestObjective = objective; bestX = x.slice(); bestY = y.slice(); }
  }
  const transform = (values: Float64Array): number[] => {
    let anchor = 0;
    for (let i = 1; i < n; i++) if (Math.abs(values[i]) > Math.abs(values[anchor])) anchor = i;
    const sign = values[anchor] >= 0 ? 1 : -1;
    const curved = Array.from(values, value => Math.asinh(value * sign * Math.sqrt(n)));
    const max = Math.max(...curved.map(Math.abs), 1e-9);
    return curved.map(value => 0.84 * value / max);
  };
  const xs = transform(bestX), ys = transform(bestY);
  // Incidence-identical researchers have no mathematically preferred internal ordering.
  // Spread each such set isotropically, never in input/subject-ordered rank strips.
  const twins = new Map<string, number[]>();
  nodes.forEach((v, i) => {
    const key = graph.incidence[v].join(',');
    if (!twins.has(key)) twins.set(key, []);
    twins.get(key)!.push(i);
  });
  for (const [key, group] of twins) {
    if (group.length < 2) continue;
    const radius = Math.min(0.32, 1.18 * Math.sqrt(group.length / n));
    const phase = hash(key) / 4294967296 * Math.PI * 2;
    const order = [...group].sort((a, b) => hash(graph.nodes[nodes[a]].id) - hash(graph.nodes[nodes[b]].id));
    order.forEach((v, rank) => {
      const angle = phase + rank * 2.399963229728653;
      const r = radius * Math.sqrt((rank + 0.5) / group.length);
      xs[v] += Math.cos(angle) * r;
      ys[v] += Math.sin(angle) * r;
    });
  }
  const scale = Math.max(1, ...xs.map(Math.abs), ...ys.map(Math.abs));
  for (let i = 0; i < n; i++) { xs[i] /= scale; ys[i] /= scale; }
  return { points: xs.map((x, i) => ({ x, y: ys[i] })), objectives };
}

function packComponents(groups: { nodes: number[] }[], width: number, height: number, padding: number): { x: number; y: number; w: number; h: number }[] {
  const weights = groups.map(g => Math.max(2, g.nodes.length));
  const total = weights.reduce((a, b) => a + b, 0);
  let mass = 0;
  const innerW = width - 2 * padding, innerH = height - 2 * padding;
  return groups.map((group, i) => {
    const fraction = weights[i] / total;
    const radius = Math.sqrt(fraction) * 0.92;
    const angle = i * 2.399963229728653 + hash(String(group.nodes[0])) / 4294967296 * 0.3;
    const centerRadius = i === 0 && fraction > 0.1 ? 0 : Math.min(1 - radius, Math.sqrt((mass + weights[i] / 2) / total));
    mass += weights[i];
    const cx = width / 2 + Math.cos(angle) * centerRadius * innerW / 2;
    const cy = height / 2 + Math.sin(angle) * centerRadius * innerH / 2;
    const w = innerW * radius, h = innerH * radius;
    return { x: cx - w / 2, y: cy - h / 2, w, h };
  });
}

/** Spatial-hash relaxation, followed by a bounded free-cell repair for stubborn coincidences. */
function removeOverlaps(points: Point[], width: number, height: number, padding: number, distance: number): number {
  if (distance <= 0 || points.length < 2) return 0;
  const grid = new Map<string, number[]>();
  const key = (x: number, y: number) => `${Math.floor(x / distance)},${Math.floor(y / distance)}`;
  const clamp = (point: Point) => {
    point.x = Math.min(width - padding, Math.max(padding, point.x));
    point.y = Math.min(height - padding, Math.max(padding, point.y));
  };
  const rebuild = () => {
    grid.clear();
    points.forEach((point, i) => {
      const k = key(point.x, point.y);
      if (!grid.has(k)) grid.set(k, []);
      grid.get(k)!.push(i);
    });
  };
  for (let step = 0; step < 90; step++) {
    rebuild();
    let collisions = 0;
    for (let i = 0; i < points.length; i++) {
      const point = points[i], gx = Math.floor(point.x / distance), gy = Math.floor(point.y / distance);
      for (let dx = -1; dx <= 1; dx++) for (let dy = -1; dy <= 1; dy++) {
        for (const j of grid.get(`${gx + dx},${gy + dy}`) ?? []) {
          if (j <= i) continue;
          const other = points[j];
          let vx = point.x - other.x, vy = point.y - other.y;
          let length = Math.hypot(vx, vy);
          if (length >= distance) continue;
          collisions++;
          if (length < 1e-8) { const a = (i * 37 + j * 17) * 2.399963229728653; vx = Math.cos(a); vy = Math.sin(a); length = 1; }
          const shift = (distance - Math.min(length, distance - 1e-6) + 0.04) * 0.52 / length;
          point.x += vx * shift; point.y += vy * shift;
          other.x -= vx * shift; other.y -= vy * shift;
          clamp(point); clamp(other);
        }
      }
    }
    if (!collisions) break;
  }

  grid.clear();
  const fits = (x: number, y: number): boolean => {
    if (x < padding || y < padding || x > width - padding || y > height - padding) return false;
    const gx = Math.floor(x / distance), gy = Math.floor(y / distance);
    for (let dx = -1; dx <= 1; dx++) for (let dy = -1; dy <= 1; dy++) {
      for (const j of grid.get(`${gx + dx},${gy + dy}`) ?? []) {
        if (Math.hypot(x - points[j].x, y - points[j].y) < distance - 1e-7) return false;
      }
    }
    return true;
  };
  const cols = Math.max(1, Math.floor((width - padding * 2) / distance));
  const rows = Math.max(1, Math.floor((height - padding * 2) / distance));
  const cells = cols * rows;
  const gcd = (a: number, b: number): number => b ? gcd(b, a % b) : a;
  let stride = Math.max(1, Math.floor(cells * 0.61803398875));
  while (gcd(stride, cells) !== 1) stride++;
  let scan = 0;
  for (let i = 0; i < points.length; i++) {
    const point = points[i];
    if (!fits(point.x, point.y)) {
      const origin = { ...point };
      let found = false;
      for (let attempt = 1; attempt <= 1600 && !found; attempt++) {
        const radius = distance * Math.sqrt(attempt) * 0.65;
        const angle = (attempt + i * 0.37) * 2.399963229728653;
        const x = origin.x + radius * Math.cos(angle), y = origin.y + radius * Math.sin(angle);
        if (fits(x, y)) { point.x = x; point.y = y; found = true; }
      }
      // Only extreme crowding reaches this O(number of grid cells) global fallback.
      // A coprime permutation avoids creating artificial upper-left rows or bands.
      for (; !found && scan < cols * rows; scan++) {
        const cell = (scan * stride + Math.floor(cells / 2)) % cells;
        const jitter = random(cell + 3793);
        const x = padding + (cell % cols + 0.25 + jitter() * 0.5) * distance;
        const y = padding + (Math.floor(cell / cols) + 0.25 + jitter() * 0.5) * distance;
        if (fits(x, y)) { point.x = x; point.y = y; found = true; }
      }
    }
    const k = key(point.x, point.y);
    if (!grid.has(k)) grid.set(k, []);
    grid.get(k)!.push(i);
  }
  // Count actual final pairs, not the transient count from relaxation.
  let finalPairs = 0;
  for (let i = 0; i < points.length; i++) {
    const point = points[i], gx = Math.floor(point.x / distance), gy = Math.floor(point.y / distance);
    for (let dx = -1; dx <= 1; dx++) for (let dy = -1; dy <= 1; dy++) {
      for (const j of grid.get(`${gx + dx},${gy + dy}`) ?? []) {
        if (j > i && Math.hypot(point.x - points[j].x, point.y - points[j].y) < distance - 1e-7) finalPairs++;
      }
    }
  }
  return finalPairs;
}

export function layoutHypergraph(graph: Hypergraph, options: LayoutOptions = {}): HypergraphLayout {
  const start = performance.now();
  const width = Math.max(100, positive(options.width, 1200));
  const height = Math.max(100, positive(options.height, 800));
  const padding = Math.min(Math.min(width, height) / 4, positive(options.padding, 44));
  const requestedDistance = positive(options.minDistance, 9);
  // Keep a feasible packing request if callers choose a tiny viewport or huge node radius.
  const capacityDistance = Math.sqrt((width - 2 * padding) * (height - 2 * padding) / Math.max(1, graph.nodes.length) * 0.45);
  const distance = Math.min(requestedDistance, capacityDistance);
  const iterations = Math.max(1, Math.min(400, Math.round(positive(options.iterations, 100))));
  const restarts = Math.max(1, Math.min(8, Math.round(positive(options.restarts, 3))));
  const chronologicalStrength = Math.min(1, positive(options.chronologicalStrength, 0.35));
  const groups = components(graph);
  const boxes = packComponents(groups, width, height, padding);
  const points: Point[] = Array.from({ length: graph.nodes.length }, () => ({ x: width / 2, y: height / 2 }));
  const candidates = Array(restarts).fill(0) as number[];
  let objective = 0, done = 0;
  for (let c = 0; c < groups.length; c++) {
    const group = groups[c], box = boxes[c];
    const result = spectral(group.nodes, group.edges, graph, iterations, restarts);
    const weight = group.nodes.length / Math.max(1, graph.nodes.length);
    result.objectives.forEach((value, run) => { candidates[run] += value * weight; });
    objective += Math.min(...result.objectives) * weight;
    const margin = Math.min(distance * 2 + 8, box.w * 0.15, box.h * 0.15);
    result.points.forEach((point, i) => {
      points[group.nodes[i]] = {
        x: box.x + box.w / 2 + point.x * (box.w / 2 - margin),
        y: box.y + box.h / 2 + point.y * (box.h / 2 - margin),
      };
    });
    done += group.nodes.length;
    options.onProgress?.({ phase: 'spectral', progress: 0.8 * done / Math.max(1, graph.nodes.length) });
  }
  if (chronologicalStrength > 0) {
    const dated = graph.nodes.map(node => node.layoutYear).filter((year): year is number => validYear(year));
    if (dated.length > 1) {
      const minYear = Math.min(...dated), maxYear = Math.max(...dated);
      if (maxYear > minYear) {
        const timelinePadding = padding + distance * 2 + 12;
        const pixelsPerYear = (height - 2 * timelinePadding) / (maxYear - minYear);
        graph.nodes.forEach((node, i) => {
          if (!validYear(node.layoutYear)) return;
          const anchor = timelinePadding + (node.layoutYear - minYear) * pixelsPerYear;
          // Chronological lanes preserve global graduation order; small spectral and
          // identity-independent jitter separates same-year nodes without fake dates.
          const spectralJitter = (points[i].y / height - 0.5) * (1 - chronologicalStrength) * 3;
          const localJitter = (hash(node.id) / 4294967296 - 0.5) * 0.45;
          points[i].y = anchor + (spectralJitter + localJitter) * pixelsPerYear;
        });
      }
    }
  }
  options.onProgress?.({ phase: 'overlap', progress: 0.85 });
  const collisionPairs = removeOverlaps(points, width, height, padding, distance);
  options.onProgress?.({ phase: 'overlap', progress: 1 });
  return {
    positions: points.map((point, i) => ({ id: graph.nodes[i].id, ...point })),
    diagnostics: {
      method: 'Sparse normalized hypergraph spectral embedding with deterministic multistart and spatial-hash overlap adjustment',
      objective, candidateObjectives: candidates, iterations, restarts, components: groups.length,
      collisionPairs, requestedMinDistance: requestedDistance, effectiveMinDistance: distance,
      chronologicalStrength,
      elapsedMs: performance.now() - start,
    },
  };
}
