PRAGMA foreign_keys = ON;
BEGIN IMMEDIATE;

UPDATE education
SET country='Korea'
WHERE lower(trim(COALESCE(country,''))) IN ('koreea','koresa');

COMMIT;
