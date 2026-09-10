-- Explicitly registered providers retain a foreign-key whitelist. Additional
-- observed library adapters can be registered by migrate() without rebuilding
-- the growing thesis/link/observation tables again.
CREATE TABLE thesis_providers (
    provider TEXT PRIMARY KEY CHECK(length(provider) BETWEEN 1 AND 30 AND provider NOT GLOB '*[^a-z_]*'),
    source_type TEXT NOT NULL CHECK(source_type IN ('openalex','riss','university_library'))
);
INSERT INTO thesis_providers VALUES ('openalex','openalex'),('riss','riss'),('kaist','university_library'),('snu','university_library');
-- Applied by migrate() with foreign keys temporarily disabled outside the transaction.
-- Parent-table copies preserve every existing key and all review history.
DROP VIEW v_domestic_phd_theses;
DROP VIEW v_phd_theses;
CREATE TABLE thesis_records_v4 (
    thesis_id INTEGER PRIMARY KEY,
    provider TEXT NOT NULL REFERENCES thesis_providers(provider),
    provider_record_id TEXT NOT NULL,
    title TEXT,
    author_text TEXT,
    publisher TEXT,
    publication_year INTEGER CHECK(publication_year IS NULL OR (typeof(publication_year)='integer' AND publication_year BETWEEN 1900 AND 3000)),
    reported_degree_level TEXT CHECK(reported_degree_level IN ('phd','master','unknown')),
    reported_department TEXT,
    doi TEXT,
    source_url TEXT NOT NULL CHECK(source_url LIKE 'https://%'),
    source_snapshot_sha256 TEXT,
    imported_at TEXT NOT NULL,
    UNIQUE(provider,provider_record_id)
);

INSERT INTO thesis_records_v4 SELECT * FROM thesis_records;
DROP TABLE thesis_records;
ALTER TABLE thesis_records_v4 RENAME TO thesis_records;
CREATE INDEX thesis_doi ON thesis_records(doi) WHERE doi IS NOT NULL;
CREATE TABLE thesis_import_batches_v4 (
    batch_sha256 TEXT PRIMARY KEY CHECK(length(batch_sha256)=64),
    source_kind TEXT NOT NULL CHECK(source_kind IN ('normalized_seed','riss_candidates','human_reviews','library_candidates','riss_public_details')),
    imported_at TEXT NOT NULL,
    counts TEXT NOT NULL CHECK(json_valid(counts)),
    audit TEXT NOT NULL CHECK(json_valid(audit))
);

INSERT INTO thesis_import_batches_v4 SELECT * FROM thesis_import_batches;
DROP TABLE thesis_import_batches;
ALTER TABLE thesis_import_batches_v4 RENAME TO thesis_import_batches;
CREATE VIEW v_phd_theses AS
SELECT e.*, r.anon_id, t.thesis_id, t.provider, t.provider_record_id,
       t.title,t.author_text,t.publisher,t.publication_year,t.reported_degree_level,
       t.reported_department,t.doi,t.source_url,
       l.status AS link_status,l.match_method,l.reviewed_by,l.checked_at,
       CASE WHEN l.status='verified' THEN json_extract(l.evidence,'$.source_department') END AS verified_department,
       CASE WHEN t.doi IS NULL THEN 0 ELSE
           (SELECT count(*) FROM thesis_records d WHERE d.doi=t.doi AND d.thesis_id<>t.thesis_id)
       END AS other_records_same_doi
FROM education_records e JOIN researchers r USING(source_professor_uid)
LEFT JOIN degree_thesis_links l ON l.degree_id=e.degree_id
LEFT JOIN thesis_records t ON t.thesis_id=l.thesis_id;
CREATE VIEW v_domestic_phd_theses AS
SELECT * FROM v_phd_theses WHERE domestic_status IN ('domestic','domestic_unresolved');
