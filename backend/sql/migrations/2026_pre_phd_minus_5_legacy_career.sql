PRAGMA foreign_keys = ON;
BEGIN IMMEDIATE;

-- Legacy professor_careers cache.  The raw OpenAlex evidence lives in the
-- affiliation-timeline database and is retained there as a drop candidate.
DELETE FROM career_spells
WHERE EXISTS (
  SELECT 1 FROM professors p
  WHERE p.professor_uid=career_spells.professor_uid
    AND p.phd_year IS NOT NULL
    AND career_spells.end_year < p.phd_year-5
);

UPDATE career_spells
SET start_year=(
      SELECT p.phd_year-5 FROM professors p
      WHERE p.professor_uid=career_spells.professor_uid
    ),
    start_term=CASE
      WHEN start_term IS NULL THEN NULL
      ELSE printf('%04d-H1',(
        SELECT p.phd_year-5 FROM professors p
        WHERE p.professor_uid=career_spells.professor_uid
      ))
    END,
    reasoning=reasoning || '; start trimmed by PhD-minus-5 hard gate'
WHERE EXISTS (
  SELECT 1 FROM professors p
  WHERE p.professor_uid=career_spells.professor_uid
    AND p.phd_year IS NOT NULL
    AND career_spells.start_year < p.phd_year-5
    AND career_spells.end_year >= p.phd_year-5
);

COMMIT;
