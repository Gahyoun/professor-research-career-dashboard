PRAGMA foreign_keys = ON;
BEGIN IMMEDIATE;

INSERT INTO duplicate_drop_candidate (
  professor_uid,openalex_id,work_id,doi,title,publication_date,period,
  candidate_score,severity,topic_name,field_name,domain_name,
  institution_ids_json,institution_names_json,raw_affiliation_strings_json,
  reasons_json,source_url
)
SELECT
  w.professor_uid,w.openalex_id,w.work_id,w.doi,w.title,w.publication_date,w.period,
  MAX(20,w.duplicate_candidate_score),'critical',w.topic_name,w.field_name,w.domain_name,
  COALESCE((SELECT json_group_array(DISTINCT r.institution_unit_id)
            FROM raw_affiliation_units r
            WHERE r.professor_uid=w.professor_uid AND r.work_id=w.work_id
              AND r.institution_unit_id IS NOT NULL),'[]'),
  COALESCE((SELECT json_group_array(DISTINCT r.institution_name)
            FROM raw_affiliation_units r
            WHERE r.professor_uid=w.professor_uid AND r.work_id=w.work_id
              AND r.institution_name IS NOT NULL),'[]'),
  COALESCE((SELECT json_group_array(DISTINCT r.raw_affiliation_string)
            FROM raw_affiliation_units r
            WHERE r.professor_uid=w.professor_uid AND r.work_id=w.work_id
              AND r.raw_affiliation_string IS NOT NULL),'[]'),
  json_array('publication_before_phd_minus_5_hard_gate:+20'),w.source_url
FROM work_authorship_evidence w JOIN professors p USING(professor_uid)
WHERE p.phd_year IS NOT NULL
  AND w.publication_year < p.phd_year-5
  AND w.identity_decision='keep'
ON CONFLICT(professor_uid,work_id) DO UPDATE SET
  candidate_score=MAX(candidate_score,excluded.candidate_score),
  severity='critical',
  reasons_json=excluded.reasons_json;

UPDATE work_authorship_evidence
SET identity_decision='duplicate_drop_candidate',
    duplicate_candidate_score=MAX(20,duplicate_candidate_score),
    duplicate_candidate_severity='critical',
    decision_reasons_json=json_insert(
      CASE WHEN json_valid(decision_reasons_json) THEN decision_reasons_json ELSE '[]' END,
      '$[#]','publication_before_phd_minus_5_hard_gate:+20'
    )
WHERE identity_decision='keep'
  AND EXISTS (
    SELECT 1 FROM professors p
    WHERE p.professor_uid=work_authorship_evidence.professor_uid
      AND p.phd_year IS NOT NULL
      AND work_authorship_evidence.publication_year < p.phd_year-5
  );

UPDATE raw_affiliation_units
SET identity_decision='duplicate_drop_candidate'
WHERE identity_decision='keep'
  AND EXISTS (
    SELECT 1
    FROM work_authorship_evidence w JOIN professors p USING(professor_uid)
    WHERE w.professor_uid=raw_affiliation_units.professor_uid
      AND w.work_id=raw_affiliation_units.work_id
      AND p.phd_year IS NOT NULL
      AND w.publication_year < p.phd_year-5
  );

COMMIT;
