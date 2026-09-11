import type { Professor } from '../types';
import { canonicalSchool } from '../schoolIdentity';
import type { InstitutionUnit, ResearcherRecord } from './hypergraph';

const unitFields = (unit: InstitutionUnit) => ({
  institution: unit.institution, institution_canonical: canonicalSchool(unit.institution_canonical || unit.institution),
  country: unit.country, department: unit.department,
  department_inferred: unit.department_inferred,
});

/** Explicit public-field projection shared by the graph and whole-release catalogue. */
export function toResearcherRecords(professors: readonly Professor[]): ResearcherRecord[] {
  return professors.map(p => ({
    id: p.id, subject: p.subject,
    phd_institution: canonicalSchool(p.phd_institution_canonical || p.phd_institution),
    bachelor_institution: canonicalSchool(p.bachelor_institution_canonical || p.bachelor_institution),
    phd_year: p.phd_year, phd_country: p.phd_country, bachelor_country: p.bachelor_country,
    phd_department: p.phd_department, bachelor_department: p.bachelor_department,
    phd_department_inferred: p.phd_department_inferred,
    bachelor_department_inferred: p.bachelor_department_inferred,
    career: p.career.map(c => ({ ...unitFields(c), stage: c.stage,
      start_year: c.start_year, end_year: c.end_year, is_estimated: c.is_estimated,
      evidence_basis: c.evidence_basis,
    })),
    faculty_appointments: p.faculty_appointments?.map(a => ({ ...unitFields(a),
      institution: a.institution, country: a.country, role: a.role,
      start_year: a.start_year, end_year: a.end_year, observed_terms: a.observed_terms,
      evidence_kind: a.evidence_kind, evidence_status: a.evidence_status,
      rank: a.rank, first_assistant_professor_verified: a.first_assistant_professor_verified,
    })),
    current_position: p.current_position ? { ...unitFields(p.current_position),
      institution: p.current_position.institution, country: p.current_position.country,
      observation_year: p.current_position.observation_year,
      department_observation_year: p.current_position.department_observation_year,
      evidence_kind: p.current_position.evidence_kind, evidence_status: p.current_position.evidence_status,
    } : null,
  }));
}
