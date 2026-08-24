PRAGMA foreign_keys = ON;

CREATE TABLE release_metadata (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);

CREATE TABLE professors (
  professor_id TEXT PRIMARY KEY,
  subject TEXT NOT NULL,
  current_institution TEXT,
  department TEXT,
  bachelor_institution TEXT,
  phd_institution TEXT,
  phd_country TEXT,
  phd_year INTEGER,
  appointment_year INTEGER,
  first_faculty_institution TEXT,
  latest_faculty_institution TEXT,
  lead_work_count INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE career_segments (
  segment_id INTEGER PRIMARY KEY,
  professor_id TEXT NOT NULL,
  stage TEXT NOT NULL CHECK(stage IN ('doctoral','postdoc','faculty')),
  position_no INTEGER,
  institution TEXT NOT NULL,
  start_period TEXT,
  end_period TEXT,
  start_year INTEGER,
  end_year INTEGER,
  confidence TEXT NOT NULL,
  evidence_basis TEXT,
  is_estimated INTEGER NOT NULL DEFAULT 0,
  is_institution_successor INTEGER NOT NULL DEFAULT 0,
  FOREIGN KEY(professor_id) REFERENCES professors(professor_id)
);

CREATE TABLE yearly_lead_output (
  professor_id TEXT NOT NULL,
  year INTEGER NOT NULL,
  career_stage TEXT,
  total_count INTEGER NOT NULL,
  first_author_count INTEGER NOT NULL,
  corresponding_author_count INTEGER NOT NULL,
  impact_low_count INTEGER NOT NULL,
  impact_medium_count INTEGER NOT NULL,
  impact_high_count INTEGER NOT NULL,
  impact_unknown_count INTEGER NOT NULL,
  mean_journal_2yr_citedness REAL,
  article_citations_total INTEGER NOT NULL,
  PRIMARY KEY(professor_id, year),
  FOREIGN KEY(professor_id) REFERENCES professors(professor_id)
);

CREATE TABLE professor_journal_output (
  professor_id TEXT NOT NULL,
  journal TEXT NOT NULL,
  lead_work_count INTEGER NOT NULL,
  openalex_2yr_mean_citedness REAL,
  PRIMARY KEY(professor_id,journal),
  FOREIGN KEY(professor_id) REFERENCES professors(professor_id)
);

CREATE INDEX idx_professor_filter ON professors(subject,current_institution,department,phd_institution,phd_country,bachelor_institution);
CREATE INDEX idx_career_prof_year ON career_segments(professor_id,start_year,end_year);
CREATE INDEX idx_output_year ON yearly_lead_output(year,career_stage);
CREATE INDEX idx_journal_threshold ON professor_journal_output(openalex_2yr_mean_citedness,lead_work_count);

CREATE VIEW v_professor_dashboard AS
SELECT p.professor_id,p.subject,p.current_institution,p.department,p.bachelor_institution,p.phd_institution,p.phd_country,
       p.phd_year,p.appointment_year,p.first_faculty_institution,p.latest_faculty_institution,
       y.year,y.career_stage,y.total_count,y.first_author_count,y.corresponding_author_count,
       y.impact_low_count,y.impact_medium_count,y.impact_high_count,y.impact_unknown_count,
       y.mean_journal_2yr_citedness,y.article_citations_total
FROM professors p LEFT JOIN yearly_lead_output y USING(professor_id);
