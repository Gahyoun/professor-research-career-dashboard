-- Private extension of the researcher identity registry; never publish this DB.
CREATE TABLE education_records (
    degree_id INTEGER PRIMARY KEY,
    source_snapshot_sha256 TEXT NOT NULL CHECK(length(source_snapshot_sha256)=64 AND source_snapshot_sha256 NOT GLOB '*[^0-9a-f]*'),
    source_education_id INTEGER NOT NULL CHECK(source_education_id>=0),
    source_professor_uid TEXT NOT NULL REFERENCES researchers(source_professor_uid),
    source_author_name TEXT,
    degree_level TEXT NOT NULL CHECK(degree_level='phd'),
    institution_unit_id TEXT,
    institution_canonical TEXT,
    institution_raw TEXT,
    education_country_code TEXT CHECK(education_country_code IS NULL OR (length(education_country_code)=2 AND education_country_code NOT GLOB '*[^A-Z]*')),
    education_country_raw TEXT,
    institution_country_code TEXT CHECK(institution_country_code IS NULL OR (length(institution_country_code)=2 AND institution_country_code NOT GLOB '*[^A-Z]*')),
    institution_country_raw TEXT,
    award_year INTEGER CHECK(award_year IS NULL OR (typeof(award_year)='integer' AND award_year BETWEEN 1900 AND 3000)),
    domestic_status TEXT NOT NULL CHECK(domestic_status IN ('domestic','domestic_unresolved','country_conflict','foreign','unknown')),
    query_status TEXT NOT NULL CHECK(query_status IN ('ready','anchor_review_required','not_target')),
    UNIQUE(source_snapshot_sha256,source_education_id),
    CHECK(education_country_code IS NULL OR institution_country_code IS NULL OR
        education_country_code=institution_country_code OR domestic_status='country_conflict')
);
CREATE INDEX education_person ON education_records(source_professor_uid);
CREATE TABLE thesis_records (
    thesis_id INTEGER PRIMARY KEY,
    provider TEXT NOT NULL CHECK(provider IN ('openalex','riss')),
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
CREATE INDEX thesis_doi ON thesis_records(doi) WHERE doi IS NOT NULL;
CREATE TABLE degree_thesis_links (
    degree_id INTEGER NOT NULL REFERENCES education_records(degree_id),
    thesis_id INTEGER NOT NULL REFERENCES thesis_records(thesis_id),
    status TEXT NOT NULL CHECK(status IN ('candidate','verified','rejected','conflict')),
    match_method TEXT NOT NULL,
    evidence TEXT NOT NULL CHECK(json_valid(evidence) AND json_type(evidence)='object'),
    reviewed_by TEXT,
    checked_at TEXT,
    PRIMARY KEY(degree_id,thesis_id),
    CHECK(status NOT IN ('verified','rejected') OR
        (reviewed_by IS NOT NULL AND length(trim(reviewed_by))>0 AND checked_at IS NOT NULL AND length(trim(checked_at))>0)),
    CHECK(status<>'verified' OR (
        coalesce(json_type(evidence,'$.confirmed_author'),'')='true' AND
        coalesce(json_type(evidence,'$.confirmed_degree'),'')='true' AND
        coalesce(json_type(evidence,'$.confirmed_institution'),'')='true' AND
        coalesce(json_type(evidence,'$.confirmed_year'),'')='true' AND
        coalesce(json_type(evidence,'$.confirmed_thesis'),'')='true' AND
        coalesce(json_type(evidence,'$.no_conflict'),'')='true' AND
        coalesce(json_extract(evidence,'$.source_degree_level'),'')='phd' AND
        length(trim(coalesce(json_extract(evidence,'$.source_title'),'')))>0 AND
        length(trim(coalesce(json_extract(evidence,'$.source_url'),'')))>0 AND
        length(trim(coalesce(json_extract(evidence,'$.record_reference'),'')))>0))
);
CREATE UNIQUE INDEX one_verified_thesis_per_degree ON degree_thesis_links(degree_id) WHERE status='verified';
CREATE UNIQUE INDEX one_verified_degree_per_thesis ON degree_thesis_links(thesis_id) WHERE status='verified';
CREATE INDEX thesis_link_status ON degree_thesis_links(thesis_id,status);
CREATE TABLE thesis_link_reviews (
    review_id INTEGER PRIMARY KEY,
    degree_id INTEGER NOT NULL,
    thesis_id INTEGER NOT NULL,
    previous_status TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('verified','rejected')),
    reviewed_by TEXT NOT NULL,
    checked_at TEXT NOT NULL,
    evidence TEXT NOT NULL CHECK(json_valid(evidence) AND json_type(evidence)='object'),
    FOREIGN KEY(degree_id,thesis_id) REFERENCES degree_thesis_links(degree_id,thesis_id)
);
CREATE TRIGGER thesis_reviews_no_update BEFORE UPDATE ON thesis_link_reviews
BEGIN SELECT RAISE(ABORT,'Thesis reviews are append-only.'); END;
CREATE TRIGGER thesis_reviews_no_delete BEFORE DELETE ON thesis_link_reviews
BEGIN SELECT RAISE(ABORT,'Thesis reviews are append-only.'); END;
CREATE TABLE thesis_import_batches (
    batch_sha256 TEXT PRIMARY KEY CHECK(length(batch_sha256)=64),
    source_kind TEXT NOT NULL CHECK(source_kind IN ('normalized_seed','riss_candidates','human_reviews')),
    imported_at TEXT NOT NULL,
    counts TEXT NOT NULL CHECK(json_valid(counts)),
    audit TEXT NOT NULL CHECK(json_valid(audit))
);
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
