import { canonicalSchool } from './schoolIdentity';
import type { Dashboard, FacultyAppointment, CurrentPosition } from './types';
import { applyInstitutionSuccessions } from './institutionSuccession';
import { normalizeInstitution } from './constellation/hypergraph';

type UnitMetadata = {
  country: string | null; department: string | null; department_inferred: boolean;
  department_evidence: string; institution_canonical?: string | null;
};
export type ResearcherMetadata = {
  faculty_appointments?: FacultyAppointment[]; current_position?: CurrentPosition | null;
  phd_country: string | null; phd_department: string | null; phd_department_inferred: boolean;
  phd_department_evidence: string; phd_institution_canonical?: string | null;
  bachelor_country: string | null; bachelor_department: string | null; bachelor_department_inferred: boolean;
  bachelor_department_evidence: string; bachelor_institution_canonical?: string | null;
  career_units: (UnitMetadata & { segment_index: number; institution: string; start_year: number | null; end_year: number | null })[];
};

function institutionEvidenceKey(value: string | null | undefined): string | null {
  // Cosmetic punctuation and explicit aliases only; no campus, hospital or
  // institutional-succession inference is appropriate for a historical degree.
  const clean = value?.normalize('NFKC').trim().replace(/[–—−]/g, '-')
    .replace(/[.,·]/g, ' ').replace(/\s+/g, ' ').trim();
  return normalizeInstitution(canonicalSchool(clean));
}

function checkedDepartment(sourceInstitution: string | null | undefined, publicInstitution: string | null | undefined,
  department: string | null | undefined, inferred: boolean | undefined, evidence: string | undefined) {
  if (!department?.trim()) return { department: null, department_inferred: false, department_evidence: evidence };
  const source = institutionEvidenceKey(sourceInstitution), target = institutionEvidenceKey(publicInstitution);
  if (source && target && source === target) return { department, department_inferred: inferred === true, department_evidence: evidence };
  return { department: null, department_inferred: false,
    department_evidence: source && target
      ? '학과 근거의 기관과 공개 학교의 동일성이 확인되지 않아 학과를 제외했습니다.'
      : '학과 근거의 기관 정보가 부족해 공개 학교와의 동일성을 확인할 수 없습니다.' };
}

/** Join by anonymous ID and verify segment identity; never use a current department for a past degree. */
export function mergeMetadata(dashboard: Dashboard, metadata: Record<string, ResearcherMetadata>): Dashboard {
  if (Object.keys(metadata).length !== dashboard.professors.length || dashboard.professors.some(p => !metadata[p.id])) throw new Error('Metadata researcher mismatch');
  return { ...dashboard, professors: dashboard.professors.map(p => {
    const m = metadata[p.id];
    if (m.current_position && m.current_position.institution !== p.current_institution) throw new Error('Metadata current position mismatch');
    const phd = checkedDepartment(m.phd_institution_canonical, p.phd_institution,
      m.phd_department, m.phd_department_inferred, m.phd_department_evidence);
    const bachelor = checkedDepartment(m.bachelor_institution_canonical, p.bachelor_institution,
      m.bachelor_department, m.bachelor_department_inferred, m.bachelor_department_evidence);
    const career = p.career.map((c, i) => {
      const row = m.career_units.find(r => r.segment_index === i);
      if (!row || row.institution !== c.institution || row.start_year !== c.start_year || row.end_year !== c.end_year) throw new Error('Metadata career mismatch');
      const department = checkedDepartment(row.institution_canonical, c.institution,
        row.department, row.department_inferred, row.department_evidence);
      return { ...c, country: row.country, ...department, institution_canonical: canonicalSchool(c.institution) };
    });
    return { ...p, phd_country: m.phd_country, phd_department: phd.department, phd_department_inferred: phd.department_inferred,
      phd_department_evidence: phd.department_evidence, phd_institution_canonical: canonicalSchool(p.phd_institution),
      bachelor_country: m.bachelor_country, bachelor_department: bachelor.department, bachelor_department_inferred: bachelor.department_inferred,
      bachelor_department_evidence: bachelor.department_evidence, bachelor_institution_canonical: canonicalSchool(p.bachelor_institution),
      faculty_appointments: (m.faculty_appointments ?? []).map(a => ({ ...a, institution_canonical: canonicalSchool(a.institution) })),
      current_position: m.current_position ? { ...m.current_position, institution_canonical: canonicalSchool(m.current_position.institution) } : null,
      current_country: m.current_position?.country ?? null,
      career,
    };
  }) };
}

async function sha256(text: string) {
  return [...new Uint8Array(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(text)))].map(b => b.toString(16).padStart(2, '0')).join('');
}

export async function loadDashboard(base: string): Promise<{ dashboard: Dashboard; metadataAvailable: boolean }> {
  const [response, supplementary] = await Promise.all([
    fetch(`${base}data/dashboard.json`),
    Promise.all([fetch(`${base}data/constellation_metadata.json`), fetch(`${base}data/constellation_metadata.manifest.json`)]).catch(() => null),
  ]);
  if (!response.ok) throw new Error('Public release unavailable');
  const publicText = await response.text();
  const dashboard = JSON.parse(publicText) as Dashboard;
  try {
    if (!supplementary || supplementary.some(r => !r.ok)) throw new Error('Supplement unavailable');
    const [metadataText, manifest] = await Promise.all([supplementary[0].text(), supplementary[1].json()]);
    const [publicHash, metadataHash] = await Promise.all([sha256(publicText), sha256(metadataText)]);
    if (manifest.release_year !== dashboard.meta.release_year || manifest.public_data_sha256 !== publicHash || manifest.metadata_sha256 !== metadataHash) throw new Error('Supplement version mismatch');
    return { dashboard: applyInstitutionSuccessions(mergeMetadata(dashboard, JSON.parse(metadataText))), metadataAvailable: true };
  } catch { return { dashboard: applyInstitutionSuccessions(dashboard), metadataAvailable: false }; }
}
