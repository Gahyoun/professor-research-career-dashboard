-- Private, local-only identity reconciliation. This database is never a public release input.
PRAGMA foreign_keys = ON;
PRAGMA user_version = 1;

CREATE TABLE researchers (
    source_professor_uid TEXT PRIMARY KEY CHECK(length(source_professor_uid) BETWEEN 1 AND 200),
    anon_id TEXT NOT NULL UNIQUE CHECK(length(anon_id) BETWEEN 1 AND 100)
);

CREATE TABLE openalex_author_links (
    source_professor_uid TEXT NOT NULL REFERENCES researchers(source_professor_uid),
    author_id TEXT NOT NULL CHECK(length(author_id) BETWEEN 2 AND 22
        AND substr(author_id,1,1)='A' AND substr(author_id,2,1) BETWEEN '1' AND '9'
        AND substr(author_id,2) NOT GLOB '*[^0-9]*'),
    origin TEXT NOT NULL DEFAULT 'source_database' CHECK(origin = 'source_database'),
    status TEXT NOT NULL DEFAULT 'imported_source_link'
        CHECK(status IN ('imported_source_link', 'candidate', 'conflict', 'rejected')),
    PRIMARY KEY(source_professor_uid, author_id)
);

CREATE TABLE researcher_identifier_links (
    source_professor_uid TEXT NOT NULL REFERENCES researchers(source_professor_uid),
    namespace TEXT NOT NULL CHECK(namespace IN
        ('national_researcher_number', 'legacy_kri_researcher_number', 'orcid')),
    identifier TEXT NOT NULL CHECK(length(identifier) BETWEEN 1 AND 100),
    status TEXT NOT NULL CHECK(status IN ('candidate', 'accepted', 'rejected', 'conflict')),
    source_url TEXT,
    source_kind TEXT NOT NULL CHECK(source_kind IN
        ('source_database', 'official_registry', 'publication', 'manual_review')),
    reviewed_by TEXT,
    checked_at TEXT,
    evidence TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(evidence)),
    CHECK(namespace = 'orcid' OR (length(identifier) <= 32 AND identifier NOT GLOB '*[^0-9]*')),
    CHECK(status <> 'accepted' OR
        (reviewed_by IS NOT NULL AND length(trim(reviewed_by)) > 0 AND checked_at IS NOT NULL
         AND source_kind = 'official_registry'
         AND coalesce(json_extract(evidence, '$.human_reviewed'), 0) = 1
         AND coalesce(json_extract(evidence, '$.matched_author'), 0) = 1
         AND coalesce(json_extract(evidence, '$.no_conflict'), 0) = 1)),
    PRIMARY KEY(source_professor_uid, namespace, identifier)
);

CREATE UNIQUE INDEX one_accepted_owner_per_identifier
    ON researcher_identifier_links(namespace, identifier) WHERE status = 'accepted';
CREATE UNIQUE INDEX one_accepted_identifier_per_namespace
    ON researcher_identifier_links(source_professor_uid, namespace) WHERE status = 'accepted';
CREATE INDEX identifier_lookup ON researcher_identifier_links(namespace, identifier);

-- Publication matching supports human identity review only. It is not authentication
-- and does not establish educational degrees or employment claims.
