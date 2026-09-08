import { canonicalSchool } from './schoolIdentity';
import type { Dashboard } from './types';

type UnitMetadata = {
  country: string | null; department: string | null; department_inferred: boolean;
  department_evidence: string; institution_canonical?: string | null;
};
export type ResearcherMetadata = {
  phd_country: string | null; phd_department: string | null; phd_department_inferred: boolean;
  phd_department_evidence: string; phd_institution_canonical?: string | null;
  bachelor_country: string | null; bachelor_department: string | null; bachelor_department_inferred: boolean;
  bachelor_department_evidence: string; bachelor_institution_canonical?: string | null;
  career_units: (UnitMetadata & { segment_index: number; institution: string; start_year: number | null; end_year: number | null })[];
};

/** Join by anonymous ID and verify segment identity; never use a current department for a past degree. */
export function mergeMetadata(dashboard: Dashboard, metadata: Record<string, ResearcherMetadata>): Dashboard {
  if (Object.keys(metadata).length !== dashboard.professors.length || dashboard.professors.some(p => !metadata[p.id])) throw new Error('Metadata researcher mismatch');
  return { ...dashboard, professors: dashboard.professors.map(p => {
    const m = metadata[p.id];
    const career = p.career.map((c, i) => {
      const row = m.career_units.find(r => r.segment_index === i);
      if (!row || row.institution !== c.institution || row.start_year !== c.start_year || row.end_year !== c.end_year) throw new Error('Metadata career mismatch');
      return { ...c, country: row.country, department: row.department, department_inferred: row.department_inferred,
        department_evidence: row.department_evidence, institution_canonical: canonicalSchool(c.institution) };
    });
    return { ...p, phd_country: m.phd_country, phd_department: m.phd_department, phd_department_inferred: m.phd_department_inferred,
      phd_department_evidence: m.phd_department_evidence, phd_institution_canonical: canonicalSchool(p.phd_institution),
      bachelor_country: m.bachelor_country, bachelor_department: m.bachelor_department, bachelor_department_inferred: m.bachelor_department_inferred,
      bachelor_department_evidence: m.bachelor_department_evidence, bachelor_institution_canonical: canonicalSchool(p.bachelor_institution),
      current_country: career.filter(c => c.stage === 'faculty' && c.institution === p.current_institution).at(-1)?.country ?? null,
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
    return { dashboard: mergeMetadata(dashboard, JSON.parse(metadataText)), metadataAvailable: true };
  } catch { return { dashboard, metadataAvailable: false }; }
}
