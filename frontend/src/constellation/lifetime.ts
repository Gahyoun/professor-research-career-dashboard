import {
  institutionKey, normalizeCountry, normalizeInstitution,
  type CurrentPosition, type FacultyAppointment, type InstitutionUnit,
  type LifetimeLinkEvidence, type ResearcherRecord,
} from './hypergraph';

export type LifetimeStage = 'doctoral' | 'postdoc' | 'first_faculty' | 'current';
export type LifetimeEvidence = LifetimeLinkEvidence;
export interface LifetimeOptions {
  releaseYear?: number;
  includeEstimated?: boolean;
  estimatedYears?: number;
  includeInferredDepartments?: boolean;
  stages?: readonly LifetimeStage[];
}
export interface LifetimeInterval {
  id: string; stage: LifetimeStage; unitKey: string; institution: string; department?: string; country: string | null;
  matchingBasis?: 'institution_subject'; subject?: string;
  startYear: number; endYear: number; estimated: boolean; inferredDepartment: boolean; basis: string[];
}
export interface LifetimeGroup extends LifetimeInterval {
  label: string; condition: string; members: string[]; memberEvidence: LifetimeEvidence[];
  temporalSemantics: 'selected_interval_union';
}
export interface LifetimeStageResult {
  id: LifetimeStage; stage: LifetimeStage; label: string; condition: string;
  intervals: LifetimeInterval[]; groups: LifetimeGroup[]; excludedReasons: string[];
}
export interface LifetimePeer {
  id: string; score: number; sharedUnitYears: number; comparedUnitYears: number;
  stageCount: number; evidence: LifetimeEvidence[];
}
export interface LifetimeCoverage {
  totalStages: number; eligibleStages: number; eligibleIntervals: number; totalIntervals: number;
  groupCount: number; peerCount: number; unverifiedFacultyIntervals: number;
  missingDepartmentIntervals: number; missingCountryIntervals: number;
  excludedInferredDepartmentIntervals: number; excludedEstimatedIntervals: number;
}
export interface LifetimeResult {
  selectedId: string; selectedFound: boolean; stages: LifetimeStageResult[];
  peers: LifetimePeer[]; coverage: LifetimeCoverage;
}
export interface LifetimeIndex {
  ids: string[];
  /** A fresh result per request; detailed results are not retained by the index. */
  get(selectedId: string): LifetimeResult;
}

const STAGES: LifetimeStage[] = ['doctoral', 'postdoc', 'first_faculty', 'current'];
const LABELS: Record<LifetimeStage, string> = {
  doctoral: '박사과정', postdoc: '포닥', first_faculty: '첫 조교수', current: '현직',
};
const CONDITIONS: Record<LifetimeStage, string> = {
  doctoral: '같은 학교·학과에서 재학 기간이 겹친 박사과정 동료와 재직이 확인된 교수',
  postdoc: '같은 기관에서 포닥 기간이 겹친 박사과정·포닥 동료와 재직이 확인된 교수',
  first_faculty: '첫 조교수 임용이 명확히 확인된 구간의 같은 학교·학과 재직 교수',
  current: '기준 연도의 현직 관측에서 같은 학교·계열(수학·물리·화학·생물)에 소속된 연구자',
};
const SUBJECT_LABELS: Record<string, string> = { mathematics: '수학', physics: '물리', chemistry: '화학', biology: '생물' };
type Role = LifetimeEvidence['peerStage'];
type SourceInterval = {
  role: Role; unit: InstitutionUnit; start: number; end: number; estimated: boolean;
  basis: string[]; firstAssistant: boolean; subject?: string;
};
type Profile = { intervals: SourceInterval[]; reasons: Record<LifetimeStage, string[]>; unverifiedFaculty: number };
type ValidUnit = { key: string; institution: string; country: string | null; department?: string; inferred: boolean;
  matchingBasis?: 'institution_subject'; subject?: string };

function validYear(year: unknown): year is number {
  return typeof year === 'number' && Number.isInteger(year) && year >= 1900 && year <= 3000;
}
function stageOf(stage: string): Role | null {
  const normalized = stage.toLowerCase().replace(/[\s._-]+/g, '');
  if (/postdoc|박사후|포닥/.test(normalized)) return 'postdoc';
  if (/doctoral|doctorate|phd|박사/.test(normalized)) return 'doctoral';
  return /faculty|professor|교수/.test(normalized) ? 'faculty' : null;
}
function employmentConfirmed(record: FacultyAppointment | CurrentPosition): boolean {
  return ['semester_roster', 'official_profile', 'verified_cv'].includes(record.evidence_kind) &&
    ['observed', 'verified'].includes(record.evidence_status);
}
function employmentBasis(record: FacultyAppointment | CurrentPosition): string {
  return record.evidence_kind === 'semester_roster' ? '학기별 교수 명부 관측' :
    record.evidence_kind === 'verified_cv' ? '공식 이력서의 재직 구간 확인' : '공식 기관 프로필의 재직 구간 확인';
}
function emptyReasons(): Profile['reasons'] { return { doctoral: [], postdoc: [], first_faculty: [], current: [] }; }

/** Sources remain separate: publication affiliations never become employment. */
function profile(record: ResearcherRecord, options: LifetimeOptions): Profile {
  const result: Profile = { intervals: [], reasons: emptyReasons(), unverifiedFaculty: 0 };
  const year = validYear(options.releaseYear) ? options.releaseYear : 2026;
  const years = Math.min(40, Math.max(1, Math.round(Number.isFinite(options.estimatedYears) ? options.estimatedYears! : 5)));
  const add = (role: Role, unit: InstitutionUnit, start: unknown, end: unknown, estimated: boolean,
    basis: string[], stage: LifetimeStage, firstAssistant = false) => {
    if (!validYear(start) || !validYear(end) || start > end || end - start > 80 || end > year) {
      result.reasons[stage].push('유효한 시작·종료 연도 근거가 없습니다.'); return;
    }
    if (estimated && options.includeEstimated === false) {
      result.reasons[stage].push('추정 기간을 제외한 상태입니다.'); return;
    }
    result.intervals.push({ role, unit, start, end, estimated, basis, firstAssistant,
      ...(role === 'current' ? { subject: record.subject } : {}) });
  };
  const careers = record.career ?? [];
  const actualDoctoral = careers.filter(c => stageOf(c.stage) === 'doctoral' && c.is_estimated === false &&
    validYear(c.start_year) && validYear(c.end_year) && c.start_year <= c.end_year && c.end_year - c.start_year <= 40);
  if (actualDoctoral.length) {
    for (const c of actualDoctoral) {
      const actualSchool = normalizeInstitution(c.institution_canonical) ?? normalizeInstitution(c.institution);
      const degreeSchool = normalizeInstitution(record.phd_institution_canonical) ?? normalizeInstitution(record.phd_institution);
      const actualCountry = normalizeCountry(c.country), degreeCountry = normalizeCountry(record.phd_country);
      const sameSchool = (!actualSchool || actualSchool === degreeSchool) &&
        (!actualCountry || !degreeCountry || actualCountry === degreeCountry);
      const unit = sameSchool ? {
        institution: c.institution || record.phd_institution,
        institution_canonical: c.institution_canonical || record.phd_institution_canonical,
        country: c.country ?? record.phd_country, department: c.department ?? record.phd_department,
        department_inferred: c.department ? c.department_inferred : record.phd_department_inferred,
      } : c;
      add('doctoral', unit, c.start_year, c.end_year, false, ['공개 학위 경력의 재학 구간'], 'doctoral');
    }
  } else if (validYear(record.phd_year)) {
    add('doctoral', { institution: record.phd_institution, institution_canonical: record.phd_institution_canonical,
      country: record.phd_country, department: record.phd_department, department_inferred: record.phd_department_inferred },
    record.phd_year - years, record.phd_year, true, [`학위 연도에서 ${years}년을 뺀 박사 재학 추정 구간`], 'doctoral');
  } else result.reasons.doctoral.push('박사 재학 구간 또는 학위 연도가 없습니다.');

  for (const c of careers) {
    if (stageOf(c.stage) === 'postdoc') add('postdoc', c, c.start_year, c.end_year, c.is_estimated,
      ['공개 경력의 포닥 분류와 기간(직급의 독립 검증은 아님)'], 'postdoc');
    if (stageOf(c.stage) === 'faculty') result.unverifiedFaculty++;
  }
  if (!careers.some(c => stageOf(c.stage) === 'postdoc')) result.reasons.postdoc.push('포닥 경력 구간이 없습니다.');
  for (const appointment of record.faculty_appointments ?? []) {
    if (appointment.role !== 'faculty' || !employmentConfirmed(appointment)) { result.unverifiedFaculty++; continue; }
    const first = appointment.rank === 'assistant_professor' && appointment.first_assistant_professor_verified === true;
    add('faculty', appointment, appointment.start_year, appointment.end_year, false,
      [employmentBasis(appointment)], 'first_faculty', first);
  }
  const firstUnits = new Set(result.intervals.filter(i => i.firstAssistant).map(i =>
    `${normalizeCountry(i.unit.country)}:${normalizeInstitution(i.unit.institution_canonical) ?? normalizeInstitution(i.unit.institution)}:${normalizeInstitution(i.unit.department)}`));
  if (firstUnits.size > 1) {
    result.intervals.forEach(i => { i.firstAssistant = false; });
    result.reasons.first_faculty.push('첫 조교수 임용 기관 근거가 서로 충돌합니다.');
  } else if (!firstUnits.size) result.reasons.first_faculty.push('첫 조교수 직급과 최초 임용을 함께 확인한 근거가 없습니다.');
  const current = record.current_position;
  if (!current || !employmentConfirmed(current)) result.reasons.current.push('출처가 확인된 현직 관측 기록이 없습니다.');
  else if (current.observation_year !== year) result.reasons.current.push(`기준 연도 ${year}년의 현직 관측이 없습니다. 과거 명부를 현재로 연장하지 않습니다.`);
  else add('current', current, current.observation_year, current.observation_year, false,
    [employmentBasis(current), `${year}년 현직 관측(과거 재직으로 연장하지 않음)`], 'current');
  return result;
}

function validateUnit(unit: InstitutionUnit, institutionOnly: boolean, options: LifetimeOptions): { unit?: ValidUnit; reason?: string } {
  const institution = normalizeInstitution(unit.institution_canonical) ?? normalizeInstitution(unit.institution);
  const country = normalizeCountry(unit.country);
  if (!institution) return { reason: '기관 정보가 없거나 해석되지 않은 기관 코드입니다.' };
  if (!country) return { reason: '국가 정보가 없거나 충돌합니다.' };
  const label = (normalizeInstitution(unit.institution_canonical) ? unit.institution_canonical : unit.institution)!.trim();
  if (institutionOnly) return { unit: { key: `${country}::${institution}`, institution: label, country, inferred: false } };
  if (!normalizeInstitution(unit.department)) return { reason: '해당 시기의 학과 근거가 없습니다. 현재 학과로 대체하지 않습니다.' };
  if (unit.department_inferred && !options.includeInferredDepartments) return { reason: '논문 소속으로 추정한 학과를 제외한 상태입니다.' };
  const key = institutionKey(unit, options);
  return key ? { unit: { key, institution: label, country, department: unit.department!.trim(), inferred: unit.department_inferred === true } } :
    { reason: '학교·학과 단위가 일치하는지 확인할 수 없습니다.' };
}

/** Current affiliation uses the recorded broad field, never a historical or inferred department. */
function validateCurrentUnit(unit: InstitutionUnit, subject: string | undefined,
  schoolCountries: ReadonlyMap<string, ReadonlySet<string>>): ReturnType<typeof validateUnit> {
  const institution = normalizeInstitution(unit.institution_canonical) ?? normalizeInstitution(unit.institution);
  if (!institution) return { reason: '기관 정보가 없거나 해석되지 않은 기관 코드입니다.' };
  if (!subject || !Object.hasOwn(SUBJECT_LABELS, subject)) return { reason: '수학·물리·화학·생물 계열 정보가 없거나 확인되지 않았습니다.' };
  const country = normalizeCountry(unit.country);
  // A specific observed current school is sufficient when country is missing.
  // Contradictory known countries stay separate, including an unknown partition.
  const partition = (schoolCountries.get(institution)?.size ?? 0) > 1 ? `::country:${country ?? 'unknown'}` : '';
  const label = (normalizeInstitution(unit.institution_canonical) ? unit.institution_canonical : unit.institution)!.trim();
  return { unit: { key: `institution:${institution}${partition}::subject:${subject}`,
    institution: label, country, inferred: false, matchingBasis: 'institution_subject', subject } };
}

function permittedPeer(stage: LifetimeStage, peer: SourceInterval): boolean {
  if (stage === 'doctoral') return peer.role === 'doctoral' || peer.role === 'faculty';
  if (stage === 'postdoc') return peer.role === 'doctoral' || peer.role === 'postdoc' || peer.role === 'faculty';
  if (stage === 'first_faculty') return peer.role === 'faculty';
  return peer.role === 'current';
}
function selectedFor(stage: LifetimeStage, interval: SourceInterval): boolean {
  return stage === 'first_faculty' ? interval.firstAssistant : interval.role === stage;
}

/**
 * Ego-window unions: each member overlaps the selected person's stage interval.
 * Members need not overlap one another, and yearly memberships are never implied.
 */
export function createLifetimeIndex(records: readonly ResearcherRecord[], inputOptions: LifetimeOptions = {},
  currentContextRecords: readonly ResearcherRecord[] = records): LifetimeIndex {
  // Capture options so an existing index cannot change when caller state changes.
  const options = { ...inputOptions, stages: inputOptions.stages ? [...inputOptions.stages] : undefined };
  const distinct = new Map<string, ResearcherRecord>();
  for (const record of records) if (typeof record.id === 'string' && record.id.trim() && !distinct.has(record.id)) distinct.set(record.id, record);
  const profiles = new Map([...distinct].map(([id, record]) => [id, profile(record, options)]));
  const unverifiedFacultyIntervals = [...profiles.values()].reduce((sum, p) => sum + p.unverifiedFaculty, 0);
  // Current country conflicts belong to the full comparison population even
  // when a subject/search filter narrows the candidate records. Reuse prepared
  // profiles for shared objects; this context never adds members to the index.
  const contextProfiles = currentContextRecords === records ? profiles : new Map<string, Profile>();
  if (currentContextRecords !== records) for (const record of currentContextRecords) {
    if (typeof record.id !== 'string' || !record.id.trim() || contextProfiles.has(record.id)) continue;
    contextProfiles.set(record.id, distinct.get(record.id) === record ? profiles.get(record.id)! : profile(record, options));
  }
  const currentSchoolCountries = new Map<string, Set<string>>();
  for (const prepared of contextProfiles.values()) for (const interval of prepared.intervals) {
    if (interval.role !== 'current') continue;
    const school = normalizeInstitution(interval.unit.institution_canonical) ?? normalizeInstitution(interval.unit.institution);
    const country = normalizeCountry(interval.unit.country);
    if (!school || !country) continue;
    if (!currentSchoolCountries.has(school)) currentSchoolCountries.set(school, new Set());
    currentSchoolCountries.get(school)!.add(country);
  }
  type UnitCheck = ReturnType<typeof validateUnit>;
  type PreparedPeer = { source: SourceInterval; unit: ValidUnit };
  const checks = new Map<SourceInterval, { department: UnitCheck; institution: UnitCheck; current: UnitCheck }>();
  // Stage -> matching unit -> peer -> intervals. Insertion order preserves the
  // original researcher order and evidence precedence without a full scan per ego.
  const candidates = new Map<LifetimeStage, Map<string, Map<string, PreparedPeer[]>>>(STAGES.map(stage => [stage, new Map()]));
  for (const [peerId, peerProfile] of profiles) for (const source of peerProfile.intervals) {
    const checked = { department: validateUnit(source.unit, false, options), institution: validateUnit(source.unit, true, options),
      current: source.role === 'current' ? validateCurrentUnit(source.unit, source.subject, currentSchoolCountries) : {} };
    checks.set(source, checked);
    for (const stage of STAGES) {
      if (!permittedPeer(stage, source)) continue;
      const unit = (stage === 'current' ? checked.current : stage === 'postdoc' ? checked.institution : checked.department).unit;
      if (!unit) continue;
      const stageCandidates = candidates.get(stage)!;
      if (!stageCandidates.has(unit.key)) stageCandidates.set(unit.key, new Map());
      const peers = stageCandidates.get(unit.key)!;
      if (!peers.has(peerId)) peers.set(peerId, []);
      peers.get(peerId)!.push({ source, unit });
    }
  }
  const enabled = new Set(options.stages ?? STAGES);
  const get = (selectedId: string): LifetimeResult => {
    const coverage: LifetimeCoverage = { totalStages: 4, eligibleStages: 0, eligibleIntervals: 0, totalIntervals: 0,
      groupCount: 0, peerCount: 0, unverifiedFacultyIntervals: 0, missingDepartmentIntervals: 0,
      missingCountryIntervals: 0, excludedInferredDepartmentIntervals: 0, excludedEstimatedIntervals: 0 };
    const result: LifetimeResult = { selectedId, selectedFound: distinct.has(selectedId), stages: [], peers: [], coverage };
    if (!result.selectedFound) return result;
    const selected = profiles.get(selectedId)!;
    coverage.unverifiedFacultyIntervals = unverifiedFacultyIntervals;
    const peers = new Map<string, LifetimeEvidence[]>();
    const selectedTokens = new Set<string>();
    for (const stage of STAGES) {
      const stageResult: LifetimeStageResult = { id: stage, stage, label: LABELS[stage], condition: CONDITIONS[stage],
        intervals: [], groups: [], excludedReasons: [...selected.reasons[stage]] };
      result.stages.push(stageResult);
      if (!enabled.has(stage)) continue;
      const intervalKeys = new Set<string>();
      for (const source of selected.intervals.filter(i => selectedFor(stage, i))) {
        coverage.totalIntervals++;
        const checked = stage === 'current' ? checks.get(source)!.current : stage === 'postdoc' ? checks.get(source)!.institution : checks.get(source)!.department;
        if (!checked.unit) {
          stageResult.excludedReasons.push(checked.reason!);
          if (checked.reason!.startsWith('해당 시기의 학과')) coverage.missingDepartmentIntervals++;
          if (checked.reason!.startsWith('국가')) coverage.missingCountryIntervals++;
          if (checked.reason!.startsWith('논문 소속')) coverage.excludedInferredDepartmentIntervals++;
          continue;
        }
        const unit = checked.unit;
        const matching = unit.matchingBasis ? { matchingBasis: unit.matchingBasis, subject: unit.subject } : {};
        const id = `lifetime:${stage}:${unit.key}:${source.start}:${source.end}`;
        if (intervalKeys.has(id)) continue;
        intervalKeys.add(id);
        const interval: LifetimeInterval = { id, stage, unitKey: unit.key, institution: unit.institution,
          country: unit.country, department: unit.department, startYear: source.start, endYear: source.end,
          estimated: source.estimated, inferredDepartment: unit.inferred, basis: [...source.basis], ...matching };
        stageResult.intervals.push(interval); coverage.eligibleIntervals++;
        for (let year = source.start; year <= source.end; year++) selectedTokens.add(`${stage}:${unit.key}:${year}`);
        const group: LifetimeGroup = { ...interval, label: `${LABELS[stage]} · ${unit.institution}${unit.subject ? ` · ${SUBJECT_LABELS[unit.subject]}` : unit.department ? ` · ${unit.department}` : ''} · ${source.start === source.end ? source.start : `${source.start}–${source.end}`}`,
          condition: CONDITIONS[stage], members: [selectedId], memberEvidence: [], temporalSemantics: 'selected_interval_union' };
        for (const [peerId, peerIntervals] of candidates.get(stage)!.get(unit.key) ?? []) {
          if (peerId === selectedId) continue;
          const evidenceKeys = new Set<string>();
          for (const { source: peer, unit: peerUnit } of peerIntervals) {
            const startYear = Math.max(source.start, peer.start), endYear = Math.min(source.end, peer.end);
            if (startYear > endYear) continue;
            const key = `${peer.role}:${startYear}:${endYear}:${peer.estimated}:${peerUnit.inferred}`;
            if (evidenceKeys.has(key)) continue;
            evidenceKeys.add(key);
            const evidence: LifetimeEvidence = { peerId, unitKey: unit.key, institution: unit.institution,
              country: stage === 'current' && (!unit.country || !peerUnit.country) ? null : unit.country,
              department: unit.department, selectedStage: stage, peerStage: peer.role,
              startYear, endYear, selectedStartYear: source.start, selectedEndYear: source.end,
              peerStartYear: peer.start, peerEndYear: peer.end, estimated: source.estimated || peer.estimated,
              inferredDepartment: unit.inferred || peerUnit.inferred,
              basis: [...new Set([...source.basis, ...peer.basis])], ...matching };
            group.memberEvidence.push(evidence);
            group.inferredDepartment ||= evidence.inferredDepartment;
            group.estimated ||= evidence.estimated;
            if (!peers.has(peerId)) peers.set(peerId, []);
            peers.get(peerId)!.push(evidence);
          }
          if (evidenceKeys.size) group.members.push(peerId);
        }
        group.memberEvidence.sort((a, b) => a.peerId.localeCompare(b.peerId, 'en') || a.startYear - b.startYear || a.peerStage.localeCompare(b.peerStage, 'en'));
        if (group.members.length > 1) { stageResult.groups.push(group); coverage.groupCount++; }
      }
      if (stageResult.intervals.length) coverage.eligibleStages++;
      if (stage === 'doctoral' && coverage.unverifiedFacultyIntervals > 0) stageResult.excludedReasons.push('논문 소속으로 추정된 교수 구간은 재직 근거로 사용하지 않습니다. 별도의 명부·공식 이력 근거가 있는 구간만 연결합니다.');
      if (!stageResult.groups.length && stageResult.intervals.length) stageResult.excludedReasons.push('현재 자료에서 이 기간·단위의 연결 상대가 확인되지 않았습니다.');
      stageResult.excludedReasons = [...new Set(stageResult.excludedReasons)];
      coverage.excludedEstimatedIntervals += stageResult.excludedReasons.filter(reason => reason.startsWith('추정 기간')).length;
    }
    for (const [id, evidence] of peers) {
      const tokens = new Set<string>();
      for (const item of evidence) for (let year = item.startYear; year <= item.endYear; year++) tokens.add(`${item.selectedStage}:${item.unitKey}:${year}`);
      result.peers.push({ id, evidence, score: selectedTokens.size ? tokens.size / selectedTokens.size : 0,
        sharedUnitYears: tokens.size, comparedUnitYears: selectedTokens.size,
        stageCount: new Set(evidence.map(item => item.selectedStage)).size });
    }
    result.peers.sort((a, b) => b.stageCount - a.stageCount || b.sharedUnitYears - a.sharedUnitYears || a.id.localeCompare(b.id, 'en'));
    coverage.peerCount = result.peers.length;
    return result;
  };
  return { ids: [...distinct.keys()], get };
}

/** Convenience wrapper for a single selection; reuse an index when querying many people. */
export function buildLifetimeTrajectory(records: readonly ResearcherRecord[], selectedId: string,
  options: LifetimeOptions = {}): LifetimeResult {
  return createLifetimeIndex(records, options).get(selectedId);
}
