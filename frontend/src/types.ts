export type Stage = 'doctoral' | 'postdoc' | 'faculty';
export type Career = {
  country?: string | null; department?: string | null; department_inferred?: boolean; department_evidence?: string; institution_canonical?: string | null;
  stage: Stage; position_no: number | null; institution: string;
  start_period: string | null; end_period: string | null;
  start_year: number | null; end_year: number | null; confidence: string;
  evidence_basis: string | null; is_estimated: boolean; is_institution_successor: boolean;
};
export type YearPoint = {
  year: number; stage: Stage | null; total: number; first_author: number;
  corresponding_author: number; impact_low: number; impact_medium: number;
  impact_high: number; impact_unknown: number;
  mean_journal_2yr_citedness: number | null; article_citations: number;
};
export type JournalStat = { journal: string; lead_work_count: number; openalex_2yr_mean_citedness: number | null };
export type Professor = {
  phd_department?: string | null; phd_department_inferred?: boolean; phd_department_evidence?: string;
  bachelor_country?: string | null; bachelor_department?: string | null; bachelor_department_inferred?: boolean; bachelor_department_evidence?: string;
  current_country?: string | null; phd_institution_canonical?: string | null; bachelor_institution_canonical?: string | null;
  id: string; subject: string; current_institution: string | null; department: string | null;
  bachelor_institution: string | null;
  phd_institution: string | null; phd_country: string | null; phd_year: number | null; appointment_year: number | null;
  first_faculty_institution: string | null; latest_faculty_institution: string | null;
  lead_work_count: number; career: Career[]; yearly: YearPoint[]; journals: JournalStat[];
};
export type Dashboard = {
  meta: { release_year: number; professor_count: number; lead_work_count: number; impact_metric: string };
  filters: { subjects: string[]; current_institutions: string[]; departments: string[]; phd_institutions: string[]; phd_countries: string[] };
  professors: Professor[];
};
