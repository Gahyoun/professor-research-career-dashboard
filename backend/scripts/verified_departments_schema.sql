-- PRIVATE overlay only. Never copy this database into public/ or a release.
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS degree_department_verifications (
  verification_id INTEGER PRIMARY KEY,
  professor_uid TEXT NOT NULL,
  anon_id TEXT NOT NULL,
  degree_level TEXT NOT NULL CHECK (degree_level='phd'),
  institution_unit_id TEXT NOT NULL,
  institution_canonical TEXT NOT NULL,
  country TEXT NOT NULL CHECK (country='KR'),
  award_year INTEGER NOT NULL,
  department TEXT,
  source_author TEXT,
  source_institution_canonical TEXT,
  source_award_year INTEGER,
  source_degree_level TEXT,
  source_department TEXT,
  source_url TEXT,
  verification_status TEXT NOT NULL CHECK (verification_status IN
    ('verified','no_matching_thesis','access_limited','ambiguous_identity','mismatch','queued')),
  checked_at TEXT NOT NULL,
  evidence_excerpt TEXT,
  evidence_type TEXT NOT NULL CHECK (evidence_type IN ('riss_dissertation','kiss_degree_record','search_only')),
  notes TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS verified_degree_person ON degree_department_verifications(professor_uid,degree_level,verification_status);
CREATE TABLE IF NOT EXISTS verification_search_audit (
  search_id INTEGER PRIMARY KEY,
  verification_id INTEGER NOT NULL REFERENCES degree_department_verifications(verification_id),
  provider TEXT NOT NULL,
  search_url TEXT NOT NULL,
  result_status TEXT NOT NULL,
  checked_at TEXT NOT NULL,
  notes TEXT NOT NULL DEFAULT ''
);
