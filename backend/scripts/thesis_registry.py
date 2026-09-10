"""Offline, private PhD/thesis linkage. Candidates are never degree verification.

The normalized registry copies source claims by immutable snapshot, retains absent
links, and records explicit human decisions. No API requests or public exports.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import unicodedata
from typing import Any
from urllib.parse import parse_qs, urlsplit

from identity_registry import RegistryError, _checked_at, _connect, _no_credentials, _private_path, _text, normalize_doi
from riss_api import ISO_COUNTRY_CODES, normalize_detail_url

SCHEMA = Path(__file__).with_name("thesis_registry_schema.sql")
SCHEMA_V3 = Path(__file__).with_name("thesis_registry_v3.sql")
LIBRARY_ANCHORS = (
    "source_education_id", "source_professor_uid", "source_author_name", "institution_unit_id",
    "institution_canonical", "award_year", "education_country_code", "institution_country_code",
)
LIBRARY_INSTITUTIONS = {
    "kaist": {"kaist", "koreaadvancedinstituteofscienceandtechnology", "한국과학기술원", "한국과학기술대학"},
    "snu": {"snu", "seoulnationaluniversity", "seoul", "서울대학교", "서울대"},
}
EDUCATION_FIELDS = (
    "source_education_id", "source_professor_uid", "source_author_name", "degree_level",
    "institution_unit_id", "institution_canonical", "institution_raw", "education_country_code",
    "education_country_raw", "institution_country_code", "institution_country_raw", "award_year",
    "domestic_status", "query_status",
)
THESIS_FIELDS = (
    "provider", "provider_record_id", "title", "author_text", "publisher", "publication_year",
    "reported_degree_level", "reported_department", "doi", "source_url",
)
REVIEW_EVIDENCE_FIELDS = {
    "source_author", "source_institution_unit_id", "source_award_year", "source_degree_level",
    "source_department", "source_url", "record_reference", "confirmed_author", "confirmed_degree",
    "confirmed_institution", "confirmed_year", "confirmed_department", "no_conflict", "notes",
    "source_title", "confirmed_thesis", "source_doi",
}


def _json(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError, RecursionError) as exc:
        raise RegistryError("Input must contain bounded JSON values.") from exc


def _sha(value: Any) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
        raise RegistryError("A lowercase SHA-256 source snapshot is required.")
    return value


def _optional(value: Any, maximum: int = 2000) -> str | None:
    return None if value is None else _text(value, maximum, "source text")


def _integer(value: Any, *, nullable=False, minimum=0, maximum=2**63 - 1) -> int | None:
    if value is None and nullable:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise RegistryError("Invalid integer or year.")
    return value


def _unit(value: Any) -> str | None:
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        value = str(value)
    return _optional(value, 300)


def _name(value: Any) -> str:
    normalized = "".join(c for c in unicodedata.normalize("NFKC", _text(value, 500, "source author")).casefold() if c.isalnum())
    if not normalized:
        raise RegistryError("Source author must contain letters or numbers.")
    return normalized


def _title(value: Any) -> str:
    normalized = "".join(c for c in unicodedata.normalize("NFKC", _text(value, 4000, "inspected thesis title")).casefold() if c.isalnum())
    if not normalized:
        raise RegistryError("Inspected thesis title must contain letters or numbers.")
    return normalized


def _country(value: Any) -> str | None:
    if value is not None and (not isinstance(value, str) or value not in ISO_COUNTRY_CODES):
        raise RegistryError("Country codes must be known uppercase ISO two-letter codes or null.")
    return value


def _evidence(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or len(_json(value)) > 32000:
        raise RegistryError("Evidence must be a bounded JSON object.")
    _no_credentials(value)
    return value


def _riss_url(value: Any) -> tuple[str, str]:
    value = _text(value, 2048, "RISS detail URL")
    _no_credentials(value)
    try:
        parsed = urlsplit(value)
        params = parse_qs(parsed.query, keep_blank_values=True)
        allowed = {"id"} if parsed.path.rstrip("/") == "/link" else {"control_no", "p_mat_type"}
        if parsed.scheme != "https" or parsed.fragment or parsed.port not in {None, 443} or set(params) - allowed or any(len(v) != 1 for v in params.values()):
            raise ValueError
        canonical, identifier = normalize_detail_url(value)
    except (ValueError, TypeError) as exc:
        raise RegistryError("An official HTTPS RISS public degree-detail URL is required.") from exc
    if not canonical or not identifier:
        raise RegistryError("An official HTTPS RISS public degree-detail URL is required.")
    return canonical, identifier


def _library_url(value: Any) -> tuple[str, str, str]:
    """Whitelist public detail records, never search pages or authentication URLs."""
    value = _text(value, 2048, "university repository detail URL")
    _no_credentials(value)
    try:
        parsed = urlsplit(value)
        if parsed.scheme != "https" or parsed.username or parsed.password or parsed.fragment or parsed.port not in {None, 443}:
            raise ValueError
        host = parsed.hostname
        if host in {"koasas.kaist.ac.kr", "s-space.snu.ac.kr"} and not parsed.query:
            prefix, provider = ("10203", "kaist") if host == "koasas.kaist.ac.kr" else ("10371", "snu")
            match = re.fullmatch(r"/handle/(" + prefix + r"/[1-9][0-9]*)/?", parsed.path)
            if match:
                return provider, "https://" + host + "/handle/" + match[1], match[1]
        if host == "dcollection.snu.ac.kr" and not parsed.query:
            match = re.fullmatch(r"/(?:srch/srchDetail|common/orgView)/([0-9]{12})/?", parsed.path)
            if match:
                return "snu", "https://dcollection.snu.ac.kr/srch/srchDetail/" + match[1], "dcollection:" + match[1]
        if host == "library.kaist.ac.kr" and parsed.path == "/search/detail/view.do":
            params = parse_qs(parsed.query, keep_blank_values=True, strict_parsing=True)
            if set(params) == {"bibCtrlNo", "flag"} and len(params["bibCtrlNo"]) == 1 and params["flag"] == ["dissertation"] and re.fullmatch(r"[1-9][0-9]*", params["bibCtrlNo"][0]):
                record_id = params["bibCtrlNo"][0]
                return "kaist", "https://library.kaist.ac.kr/search/detail/view.do?bibCtrlNo=" + record_id + "&flag=dissertation", "bib:" + record_id
    except (ValueError, TypeError):
        pass
    raise RegistryError("An official HTTPS KAIST or Seoul National University thesis-detail URL is required.")


def _library_institution(provider: str, institution: Any) -> bool:
    return _name(institution) in LIBRARY_INSTITUTIONS[provider]


def _education(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) - set(EDUCATION_FIELDS):
        raise RegistryError("Unsupported education anchor fields.")
    item = {key: value.get(key) for key in EDUCATION_FIELDS}
    item["source_education_id"] = _integer(item["source_education_id"])
    item["source_professor_uid"] = _text(item["source_professor_uid"], 200, "source UID")
    for key in ("source_author_name", "institution_canonical", "institution_raw", "education_country_raw", "institution_country_raw"):
        item[key] = _optional(item[key], 2000 if key != "source_author_name" else 500)
    item["institution_unit_id"] = _unit(item["institution_unit_id"])
    for key in ("education_country_code", "institution_country_code"):
        item[key] = _country(item[key])
    item["award_year"] = _integer(item["award_year"], nullable=True, minimum=1900, maximum=3000)
    if item["degree_level"] != "phd" or item["domestic_status"] not in {"domestic", "domestic_unresolved", "country_conflict", "foreign", "unknown"} or item["query_status"] not in {"ready", "anchor_review_required", "not_target"}:
        raise RegistryError("Invalid degree or source anchor status.")
    ec, ic, status = item["education_country_code"], item["institution_country_code"], item["domestic_status"]
    known = {c for c in (ec, ic) if c is not None}
    if (ec and ic and ec != ic and status != "country_conflict" or
        status == "domestic" and (ec != "KR" or ic != "KR") or
        status == "domestic_unresolved" and not (known == {"KR"} and (ec is None or ic is None)) or
        status == "foreign" and (not known or "KR" in known or len(known) != 1)):
        raise RegistryError("Country codes contradict the supplied degree status.")
    if item["query_status"] == "ready" and (not ec or ec != ic or status not in {"domestic", "foreign"} or
        item["source_author_name"] is None or item["institution_unit_id"] is None or item["institution_canonical"] is None or item["award_year"] is None):
        raise RegistryError("Ready queries require complete agreeing country, author, institution and year anchors.")
    return item


def _thesis(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) - set(THESIS_FIELDS):
        raise RegistryError("Unsupported thesis metadata fields.")
    item = {key: value.get(key) for key in THESIS_FIELDS}
    for key in ("title", "author_text", "publisher", "reported_department"):
        item[key] = _optional(item[key], 4000)
    item["publication_year"] = _integer(item["publication_year"], nullable=True, minimum=1900, maximum=3000)
    if item["reported_degree_level"] not in {None, "phd", "master", "unknown"}:
        raise RegistryError("Invalid reported degree level.")
    item["doi"] = None if item["doi"] is None else normalize_doi(item["doi"])
    identifier = _text(item["provider_record_id"], 200, "provider record ID")
    if item["provider"] == "openalex":
        if not re.fullmatch(r"W[1-9][0-9]{0,20}", identifier) or item["source_url"] != "https://openalex.org/" + identifier:
            raise RegistryError("OpenAlex record IDs require the matching canonical HTTPS work URL.")
    elif item["provider"] == "riss":
        item["source_url"], actual_id = _riss_url(item["source_url"])
        if actual_id != identifier:
            raise RegistryError("RISS detail URL and record identifier disagree.")
    elif item["provider"] in LIBRARY_INSTITUTIONS:
        actual_provider, item["source_url"], actual_id = _library_url(item["source_url"])
        if actual_provider != item["provider"] or actual_id != identifier:
            raise RegistryError("University repository URL, provider and record identifier disagree.")
    else:
        raise RegistryError("Unsupported thesis provider.")
    item["provider_record_id"] = identifier
    return item


def _open(database: str | Path) -> sqlite3.Connection:
    connection = _connect(_private_path(database, exists=True))
    if connection.execute("PRAGMA user_version").fetchone()[0] != 3:
        connection.close()
        raise RegistryError("Thesis registry requires migration to schema version 3.")
    return connection


def _summary(connection: sqlite3.Connection) -> dict[str, Any]:
    return {
        "schema_version": 3,
        "education_records": connection.execute("SELECT count(*) FROM education_records").fetchone()[0],
        "thesis_records": connection.execute("SELECT count(*) FROM thesis_records").fetchone()[0],
        "education_statuses": {r[0]: r[1] for r in connection.execute("SELECT domestic_status,count(*) FROM education_records GROUP BY domestic_status")},
        "links": {r[0]: r[1] for r in connection.execute("SELECT status,count(*) FROM degree_thesis_links GROUP BY status")},
        "unlinked_degrees": connection.execute("SELECT count(*) FROM education_records e WHERE NOT EXISTS(SELECT 1 FROM degree_thesis_links l WHERE l.degree_id=e.degree_id)").fetchone()[0],
        "duplicate_doi_groups": connection.execute("SELECT count(*) FROM (SELECT doi FROM thesis_records WHERE doi IS NOT NULL GROUP BY doi HAVING count(*)>1)").fetchone()[0],
        "reviews": connection.execute("SELECT count(*) FROM thesis_link_reviews").fetchone()[0],
        "import_batches": connection.execute("SELECT count(*) FROM thesis_import_batches").fetchone()[0],
        "source_observations": connection.execute("SELECT count(*) FROM thesis_source_observations").fetchone()[0],
    }


def summary(database: str | Path) -> dict[str, Any]:
    connection = _open(database)
    try:
        return _summary(connection)
    finally:
        connection.close()


def migrate(database: str | Path) -> dict[str, Any]:
    connection = _connect(_private_path(database, exists=True))
    try:
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        if version in {1, 2}:
            try:
                # SQLite requires foreign_keys OFF before beginning a parent-table
                # replacement. Restore it on every exit and check the rebuilt graph
                # inside the transaction before publishing the schema version.
                connection.execute("PRAGMA foreign_keys=OFF")
                schema = SCHEMA.read_text(encoding="utf-8") if version == 1 else ""
                connection.executescript("BEGIN IMMEDIATE;\n" + schema + "\n" + SCHEMA_V3.read_text(encoding="utf-8"))
                if connection.execute("PRAGMA foreign_key_check").fetchone() is not None:
                    raise RegistryError("Migration found an invalid foreign-key reference; all changes rolled back.")
                connection.execute("PRAGMA user_version=3")
                connection.commit()
            except Exception:
                connection.rollback()
                raise
            finally:
                connection.execute("PRAGMA foreign_keys=ON")
        elif version != 3:
            raise RegistryError("Unsupported identity registry schema version.")
        return _summary(connection)
    finally:
        connection.close()


def _batch_key(kind: str, payload: Any, selector: str | None = None) -> str:
    return hashlib.sha256(_json({"source_kind": kind, "payload": payload, "source_snapshot_selector": selector}).encode()).hexdigest()


def _prior_batch(connection: sqlite3.Connection, key: str) -> dict[str, Any] | None:
    row = connection.execute("SELECT counts FROM thesis_import_batches WHERE batch_sha256=?", (key,)).fetchone()
    if row:
        return {"already_imported": True, **json.loads(row[0])}
    return None


def _finish_batch(connection: sqlite3.Connection, key: str, kind: str, counts: dict, audit: Any = None) -> dict:
    connection.execute("INSERT INTO thesis_import_batches VALUES(?,?,?,?,?)", (key, kind, dt.datetime.now(dt.timezone.utc).isoformat(), _json(counts), _json(audit or {})))
    return {"already_imported": False, **counts}


def _insert_education(connection: sqlite3.Connection, snapshot: str, item: dict) -> int:
    row = connection.execute("SELECT * FROM education_records WHERE source_snapshot_sha256=? AND source_education_id=?", (snapshot, item["source_education_id"])).fetchone()
    if row:
        if any(row[key] != item[key] for key in EDUCATION_FIELDS):
            raise RegistryError("Existing education snapshot metadata conflicts; import rolled back.")
        return row["degree_id"]
    keys = ("source_snapshot_sha256",) + EDUCATION_FIELDS
    cursor = connection.execute(f"INSERT INTO education_records({','.join(keys)}) VALUES({','.join('?' for _ in keys)})", (snapshot,) + tuple(item[key] for key in EDUCATION_FIELDS))
    return cursor.lastrowid


def _insert_thesis(connection: sqlite3.Connection, item: dict, snapshot: str | None) -> int:
    row = connection.execute("SELECT * FROM thesis_records WHERE provider=? AND provider_record_id=?", (item["provider"], item["provider_record_id"])).fetchone()
    if row:
        if any(row[key] != item[key] for key in THESIS_FIELDS):
            raise RegistryError("Existing thesis metadata conflicts; import rolled back.")
        return row["thesis_id"]
    keys = THESIS_FIELDS + ("source_snapshot_sha256", "imported_at")
    cursor = connection.execute(f"INSERT INTO thesis_records({','.join(keys)}) VALUES({','.join('?' for _ in keys)})", tuple(item[key] for key in THESIS_FIELDS) + (snapshot, dt.datetime.now(dt.timezone.utc).isoformat()))
    return cursor.lastrowid


def _insert_link(connection: sqlite3.Connection, degree: int, thesis: int, method: Any, evidence: Any) -> None:
    method = _text(method, 300, "match method")
    evidence = _json(_evidence(evidence))
    # Raw imports cannot replace human decisions or the original candidate evidence.
    connection.execute("INSERT OR IGNORE INTO degree_thesis_links(degree_id,thesis_id,status,match_method,evidence) VALUES(?,?,'candidate',?,?)", (degree, thesis, method, evidence))


def _reconcile_conflicts(connection: sqlite3.Connection) -> None:
    connection.execute("""UPDATE degree_thesis_links SET status='conflict' WHERE status<>'rejected' AND
      EXISTS(SELECT 1 FROM education_records e JOIN thesis_records t ON t.thesis_id=degree_thesis_links.thesis_id
        WHERE e.degree_id=degree_thesis_links.degree_id AND t.provider IN ('kaist','snu') AND
          (e.domestic_status='country_conflict' OR e.education_country_code<>'KR' OR e.institution_country_code<>'KR'))""")
    connection.execute("""UPDATE degree_thesis_links SET status='conflict' WHERE status<>'rejected' AND thesis_id IN
      (SELECT l.thesis_id FROM degree_thesis_links l JOIN education_records e USING(degree_id)
       WHERE l.status<>'rejected' GROUP BY l.thesis_id HAVING count(DISTINCT e.source_professor_uid)>1)""")
    # Newly imported duplicate DOI metadata invalidates an old verification until review.
    connection.execute("""UPDATE degree_thesis_links SET status='conflict' WHERE status='verified' AND thesis_id IN
      (SELECT t.thesis_id FROM thesis_records t WHERE t.doi IS NOT NULL AND EXISTS
        (SELECT 1 FROM thesis_records d WHERE d.doi=t.doi AND d.thesis_id<>t.thesis_id AND
          (NOT EXISTS(SELECT 1 FROM degree_thesis_links x WHERE x.thesis_id=d.thesis_id) OR
           EXISTS(SELECT 1 FROM degree_thesis_links x WHERE x.thesis_id=d.thesis_id AND x.status<>'rejected'))))""")


def import_records(database: str | Path, payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict) or set(payload) != {"schema_version", "source_snapshot_sha256", "education_records", "thesis_records", "links"} or payload["schema_version"] != 1:
        raise RegistryError("Unsupported normalized thesis import schema.")
    _no_credentials(payload)
    snapshot = _sha(payload["source_snapshot_sha256"])
    if any(not isinstance(payload[key], list) for key in ("education_records", "thesis_records", "links")):
        raise RegistryError("Import collections must be lists.")
    educations = [_education(item) for item in payload["education_records"]]
    theses = [_thesis(item) for item in payload["thesis_records"]]
    if any(item["provider"] in LIBRARY_INSTITUTIONS for item in theses) or any(isinstance(item, dict) and item.get("provider") in LIBRARY_INSTITUTIONS for item in payload["links"]):
        raise RegistryError("University repository candidates require import-library with source observations and exact degree anchors.")
    links = []
    for link in payload["links"]:
        if not isinstance(link, dict) or set(link) != {"source_education_id", "provider", "provider_record_id", "match_method", "evidence"}:
            raise RegistryError("Links contain unsupported fields; imported links are candidates only.")
        links.append((_integer(link["source_education_id"]), _text(link["provider"], 20, "provider"), _text(link["provider_record_id"], 200, "record ID"), _text(link["match_method"], 300, "match method"), _evidence(link["evidence"])))
    key = _batch_key("normalized_seed", payload)
    connection = _open(database)
    try:
        with connection:
            connection.execute("BEGIN IMMEDIATE")
            prior = _prior_batch(connection, key)
            if prior:
                return {**_summary(connection), **prior}
            for item in educations:
                _insert_education(connection, snapshot, item)
            for item in theses:
                _insert_thesis(connection, item, snapshot)
            for source_id, provider, record_id, method, evidence in links:
                degree = connection.execute("SELECT degree_id FROM education_records WHERE source_snapshot_sha256=? AND source_education_id=?", (snapshot, source_id)).fetchone()
                thesis = connection.execute("SELECT thesis_id FROM thesis_records WHERE provider=? AND provider_record_id=?", (provider, record_id)).fetchone()
                if not degree or not thesis:
                    raise RegistryError("A link references an absent degree or thesis; import rolled back.")
                _insert_link(connection, degree[0], thesis[0], method, evidence)
            _reconcile_conflicts(connection)
            result = _finish_batch(connection, key, "normalized_seed", {"input_education_records": len(educations), "input_thesis_records": len(theses), "input_links": len(links)})
        return {**_summary(connection), **result}
    finally:
        connection.close()


def _verify_evidence(connection: sqlite3.Connection, degree: sqlite3.Row, thesis: sqlite3.Row, evidence: dict) -> None:
    if set(evidence) - REVIEW_EVIDENCE_FIELDS:
        raise RegistryError("Verification evidence contains unsupported fields.")
    for key in ("confirmed_author", "confirmed_degree", "confirmed_institution", "confirmed_year", "confirmed_thesis", "no_conflict"):
        if evidence.get(key) is not True:
            raise RegistryError("Verification requires explicit author, thesis, PhD, institution, year and conflict review.")
    ec, ic = degree["education_country_code"], degree["institution_country_code"]
    if (ec is not None and ic is not None and ec != ic or degree["domestic_status"] in {"country_conflict", "unknown"} or degree["source_author_name"] is None or degree["institution_unit_id"] is None or degree["award_year"] is None):
        raise RegistryError("Unresolved degree anchors must be resolved in a new source snapshot before verification.")
    if _name(evidence.get("source_author")) != _name(degree["source_author_name"]):
        raise RegistryError("Reviewed author does not match the degree's source author.")
    if _title(evidence.get("source_title")) != _title(thesis["title"]):
        raise RegistryError("The inspected degree record's title must match the linked thesis.")
    if evidence.get("source_doi") is not None and normalize_doi(evidence["source_doi"]) != thesis["doi"]:
        raise RegistryError("The inspected DOI must match the linked thesis DOI.")
    if _unit(evidence.get("source_institution_unit_id")) != degree["institution_unit_id"] or _integer(evidence.get("source_award_year"), minimum=1900, maximum=3000) != degree["award_year"] or evidence.get("source_degree_level") != "phd":
        raise RegistryError("Reviewed PhD institution and award year must match the source degree exactly.")
    try:
        _, source_id = _riss_url(evidence.get("source_url"))
        source_provider = "riss"
    except RegistryError:
        source_provider, _, source_id = _library_url(evidence.get("source_url"))
        if not _library_institution(source_provider, degree["institution_canonical"]) or any(country is not None and country != "KR" for country in (ec, ic)):
            raise RegistryError("The inspected repository must agree with the degree institution and country; contradictory anchors need a corrected snapshot.")
    if thesis["provider"] != "openalex" and (source_provider != thesis["provider"] or source_id != thesis["provider_record_id"]):
        raise RegistryError("The inspected official record must match the linked thesis provider and identifier.")
    _text(evidence.get("record_reference"), 1000, "private inspected record reference")
    if thesis["reported_degree_level"] == "master":
        raise RegistryError("A reported master's thesis cannot verify a PhD degree.")
    department = evidence.get("source_department")
    if department is not None:
        _text(department, 4000, "observed department")
        if evidence.get("confirmed_department") is not True:
            raise RegistryError("Reported department requires explicit department inspection.")
    if thesis["reported_department"] is not None and department != thesis["reported_department"]:
        raise RegistryError("Observed department must agree with the thesis metadata.")
    competing = connection.execute("""SELECT 1 FROM degree_thesis_links l JOIN education_records e USING(degree_id)
        WHERE (l.thesis_id=? AND e.source_professor_uid<>? AND l.status<>'rejected')
           OR (l.degree_id=? AND l.thesis_id<>? AND l.status='verified')
           OR (l.thesis_id=? AND l.degree_id<>? AND l.status='verified') LIMIT 1""",
        (thesis["thesis_id"], degree["source_professor_uid"], degree["degree_id"], thesis["thesis_id"], thesis["thesis_id"], degree["degree_id"])).fetchone()
    if competing:
        raise RegistryError("Competing person or verified degree/thesis links must be rejected before verification.")
    if thesis["doi"] is not None:
        duplicate = connection.execute("""SELECT 1 FROM thesis_records d WHERE d.doi=? AND d.thesis_id<>? AND
          (NOT EXISTS(SELECT 1 FROM degree_thesis_links x WHERE x.thesis_id=d.thesis_id) OR
           EXISTS(SELECT 1 FROM degree_thesis_links x WHERE x.thesis_id=d.thesis_id AND x.status<>'rejected')) LIMIT 1""", (thesis["doi"], thesis["thesis_id"])).fetchone()
        if duplicate:
            raise RegistryError("Duplicate DOI records need explicit competing-link rejection before verification.")


def review_links(database: str | Path, payload: Any) -> dict[str, Any]:
    if isinstance(payload, dict) and set(payload) == {"reviews"}:
        payload = payload["reviews"]
    if not isinstance(payload, list):
        raise RegistryError("Review input must be a list or a reviews collection.")
    _no_credentials(payload)
    prepared = []
    for item in payload:
        if not isinstance(item, dict) or set(item) != {"degree_id", "thesis_id", "status", "reviewed_by", "checked_at", "evidence"} or item["status"] not in {"verified", "rejected"}:
            raise RegistryError("Unsupported human review schema.")
        date = _checked_at(item["checked_at"])
        if not date:
            raise RegistryError("Review timestamp is required.")
        evidence = _evidence(item["evidence"])
        if "notes" in evidence:
            _optional(evidence["notes"], 2000)
        prepared.append({**item, "degree_id": _integer(item["degree_id"], minimum=1), "thesis_id": _integer(item["thesis_id"], minimum=1), "reviewed_by": _text(item["reviewed_by"], 200, "human reviewer"), "checked_at": date, "evidence": evidence})
    key = _batch_key("human_reviews", payload)
    connection = _open(database)
    try:
        with connection:
            connection.execute("BEGIN IMMEDIATE")
            prior = _prior_batch(connection, key)
            if prior:
                return {**_summary(connection), **prior}
            # Resolve rejected alternatives first so one atomic batch can disambiguate.
            for item in sorted(prepared, key=lambda item: item["status"] != "rejected"):
                link = connection.execute("SELECT * FROM degree_thesis_links WHERE degree_id=? AND thesis_id=?", (item["degree_id"], item["thesis_id"])).fetchone()
                if not link:
                    raise RegistryError("Review references an absent degree/thesis link.")
                if link["checked_at"] and dt.datetime.fromisoformat(item["checked_at"]) < dt.datetime.fromisoformat(link["checked_at"]):
                    raise RegistryError("An older review cannot replace a later decision.")
                if item["status"] == "verified":
                    degree = connection.execute("SELECT * FROM education_records WHERE degree_id=?", (item["degree_id"],)).fetchone()
                    thesis = connection.execute("SELECT * FROM thesis_records WHERE thesis_id=?", (item["thesis_id"],)).fetchone()
                    _verify_evidence(connection, degree, thesis, item["evidence"])
                encoded = _json(item["evidence"])
                connection.execute("INSERT INTO thesis_link_reviews(degree_id,thesis_id,previous_status,status,reviewed_by,checked_at,evidence) VALUES(?,?,?,?,?,?,?)", (item["degree_id"], item["thesis_id"], link["status"], item["status"], item["reviewed_by"], item["checked_at"], encoded))
                connection.execute("UPDATE degree_thesis_links SET status=?,reviewed_by=?,checked_at=?,evidence=? WHERE degree_id=? AND thesis_id=?", (item["status"], item["reviewed_by"], item["checked_at"], encoded, item["degree_id"], item["thesis_id"]))
            result = _finish_batch(connection, key, "human_reviews", {"input_reviews": len(prepared)})
        return {**_summary(connection), **result}
    finally:
        connection.close()


def _publication_year(value: Any) -> int | None:
    if value is None:
        return None
    text = _text(value, 100, "publication date")
    matched = re.match(r"^([0-9]{4})(?:$|[^0-9])", text)
    return _integer(int(matched[1]), minimum=1900, maximum=3000) if matched else None


def _reported_level(value: Any) -> str:
    text = re.sub(r"\s+", "", _optional(value, 4000) or "").casefold()
    if "박사" in text and "석사" not in text:
        return "phd"
    if "석사" in text and "박사" not in text:
        return "master"
    return "unknown"


def _validate_query_audit(query: dict) -> None:
    expected = {"version": "1.0", "type": "T", "stype": "id" if query["country"] == "KR" else "od",
                "author": query["name"], "publisher": query["institution_query"],
                "spubdate": query["award_year"], "epubdate": query["award_year"]}
    if query.get("query") != expected:
        raise RegistryError("RISS query parameters disagree with the person, institution, country or year anchors.")
    attempts = _integer(query.get("request_attempts"))
    pages = _integer(query.get("pages_received"))
    total = _integer(query.get("totalcount"), nullable=True)
    status = query["status"]
    candidates = query["candidates"]
    if pages > attempts or (candidates and pages == 0):
        raise RegistryError("RISS candidate collection contradicts its request/page audit.")
    if status == "not_queried_due_to_prior_error":
        if attempts or pages or candidates or total is not None or query.get("truncated") is not None:
            raise RegistryError("Unqueried RISS entries cannot contain returned candidates or page counts.")
    elif status.startswith("complete_"):
        if pages < 1 or total is None or query.get("truncated") is not False or (status == "complete_no_matching" and (candidates or total != 0)) or (status == "complete_candidates" and not candidates):
            raise RegistryError("Complete RISS status contradicts the returned candidate audit.")
    elif attempts < 1 or query.get("truncated") is not True:
        raise RegistryError("Incomplete RISS status requires an attempted query and incomplete audit.")


def import_riss(database: str | Path, payload: Any, source_snapshot_sha256: str | None = None) -> dict[str, Any]:
    if not isinstance(payload, dict) or payload.get("schema_version") != 1 or payload.get("source") != "RISS thesis OpenAPI" or not isinstance(payload.get("queries"), list):
        raise RegistryError("Unsupported RISS candidate collection schema.")
    _no_credentials(payload)
    _sha(payload.get("public_data_sha256"))
    _integer(payload.get("release_year"), minimum=1900, maximum=3000)
    if source_snapshot_sha256 is not None:
        _sha(source_snapshot_sha256)
    key = _batch_key("riss_candidates", payload, source_snapshot_sha256)
    connection = _open(database)
    try:
        with connection:
            connection.execute("BEGIN IMMEDIATE")
            prior = _prior_batch(connection, key)
            if prior:
                return {**_summary(connection), **prior}
            skipped = []
            imported = 0
            for qi, query in enumerate(payload["queries"]):
                if not isinstance(query, dict) or not isinstance(query.get("candidates"), list) or query.get("degree_level") != "phd" or query.get("status") not in {"complete_candidates", "complete_no_matching", "incomplete_truncated", "incomplete_error", "not_queried_due_to_prior_error"}:
                    raise RegistryError("Invalid RISS query audit schema.")
                uid = _text(query.get("professor_uid"), 200, "source UID")
                anon = _text(query.get("anon_id"), 100, "anonymous ID")
                unit = _unit(query.get("institution_unit_id"))
                school = _text(query.get("institution_canonical"), 2000, "institution")
                name = _name(query.get("name"))
                year = _integer(query.get("award_year"), minimum=1900, maximum=3000)
                country = _country(query.get("country"))
                if not country or unit is None:
                    raise RegistryError("RISS queries require known country and institution anchors.")
                _text(query.get("institution_query"), 2000, "query institution")
                _validate_query_audit(query)
                anchors = connection.execute("""SELECT e.* FROM education_records e JOIN researchers r USING(source_professor_uid)
                  WHERE e.source_professor_uid=? AND r.anon_id=? AND e.institution_unit_id=? AND e.institution_canonical=? AND e.award_year=?
                    AND e.domestic_status NOT IN ('country_conflict','unknown')""", (uid, anon, unit, school, year)).fetchall()
                anchors = [a for a in anchors if a["source_author_name"] is not None and _name(a["source_author_name"]) == name and (source_snapshot_sha256 is None or a["source_snapshot_sha256"] == source_snapshot_sha256) and a["education_country_code"] == country and a["institution_country_code"] == country and a["domestic_status"] == ("domestic" if country == "KR" else "foreign")]
                if len(anchors) != 1:
                    raise RegistryError("RISS query must match exactly one degree snapshot; supply a snapshot selector or resolve anchors.")
                degree = anchors[0]
                for ci, candidate in enumerate(query["candidates"]):
                    if not isinstance(candidate, dict) or candidate.get("verification_status") != "candidate_needs_degree_detail":
                        raise RegistryError("Only unverified RISS detail candidates can be imported.")
                    rid = candidate.get("riss_id")
                    url = candidate.get("source_url")
                    if not rid or not url:
                        skipped.append({"query_index": qi, "candidate_index": ci, "reason": "missing_usable_riss_identifier_or_url"})
                        continue
                    canonical, actual = _riss_url(url)
                    if actual != rid:
                        raise RegistryError("RISS candidate URL and identifier disagree.")
                    # API flags and query filters are not degree or department proof.
                    if candidate.get("department") is not None:
                        raise RegistryError("The RISS search adapter does not report departments.")
                    item = _thesis({"provider": "riss", "provider_record_id": rid, "source_url": canonical,
                        "title": candidate.get("title"), "author_text": candidate.get("author"), "publisher": candidate.get("publisher"),
                        "publication_year": _publication_year(candidate.get("publication_date")), "reported_degree_level": _reported_level(candidate.get("material_type")),
                        "reported_department": None, "doi": None})
                    thesis = _insert_thesis(connection, item, None)
                    _insert_link(connection, degree["degree_id"], thesis, "riss_search_author_institution_year_candidate", {
                        "verification_status": "candidate_needs_degree_detail", "query_index": qi,
                        "candidate_index": ci, "query_status": query["status"], "query_totalcount": query.get("totalcount"),
                        "query_truncated": query.get("truncated"), "public_data_sha256": payload["public_data_sha256"],
                        "source_collection_sha256": key,
                    })
                    imported += 1
            _reconcile_conflicts(connection)
            result = _finish_batch(connection, key, "riss_candidates", {"input_queries": len(payload["queries"]), "input_candidates_linked": imported, "skipped_candidates": len(skipped)}, {"skipped": skipped})
        return {**_summary(connection), **result}
    finally:
        connection.close()


def import_library(database: str | Path, payload: Any) -> dict[str, Any]:
    """Import observed library metadata as candidates, never a human decision.

    source_sha256 is the collector's hash of its saved observation (HTML for
    direct_http, observed index text for web_indexed), not a claimed live-page
    hash. The source is not refetched here; the method and original metadata
    remain available to an eventual human reviewer.
    """
    if not isinstance(payload, dict) or set(payload) != {"schema_version", "source", "candidates"} or payload.get("schema_version") != 1 or payload.get("source") != "Official university repository" or not isinstance(payload.get("candidates"), list):
        raise RegistryError("Unsupported university repository candidate collection schema.")
    _no_credentials(payload)
    key = _batch_key("library_candidates", payload)
    connection = _open(database)
    try:
        with connection:
            connection.execute("BEGIN IMMEDIATE")
            prior = _prior_batch(connection, key)
            if prior:
                return {**_summary(connection), **prior}
            for candidate in payload["candidates"]:
                if not isinstance(candidate, dict) or set(candidate) != {"degree_id", "source_snapshot_sha256", "anchors", "thesis", "observation"}:
                    raise RegistryError("Library candidates require an exact degree, source snapshot, anchors and observation.")
                degree_id = _integer(candidate["degree_id"], minimum=1)
                snapshot = _sha(candidate["source_snapshot_sha256"])
                anchors = candidate["anchors"]
                if not isinstance(anchors, dict) or set(anchors) != set(LIBRARY_ANCHORS):
                    raise RegistryError("Library candidate degree anchors are incomplete or unsupported.")
                anchors = {**anchors, "institution_unit_id": _unit(anchors["institution_unit_id"]),
                           "source_education_id": _integer(anchors["source_education_id"]),
                           "award_year": _integer(anchors["award_year"], minimum=1900, maximum=3000)}
                if anchors["institution_unit_id"] is None:
                    raise RegistryError("Library candidates require a known degree institution identifier.")
                degree = connection.execute("SELECT * FROM education_records WHERE degree_id=? AND source_snapshot_sha256=?", (degree_id, snapshot)).fetchone()
                if degree is None or any(degree[field] != anchors[field] for field in LIBRARY_ANCHORS):
                    raise RegistryError("Library candidate anchors disagree with the stored degree snapshot.")
                item = _thesis(candidate["thesis"])
                if item["provider"] not in LIBRARY_INSTITUTIONS or not _library_institution(item["provider"], degree["institution_canonical"]):
                    raise RegistryError("Library candidate repository must agree with the degree institution.")
                if item["reported_degree_level"] != "phd" or degree["award_year"] is None or item["publication_year"] is None or abs(item["publication_year"] - degree["award_year"]) > 1:
                    raise RegistryError("Library candidates require an explicitly reported PhD and a publication year within one year of the source award.")
                _text(item["title"], 4000, "observed thesis title")
                observation = candidate["observation"]
                if not isinstance(observation, dict) or set(observation) != {"fetched_at", "retrieval_method", "source_sha256", "record_reference", "source_metadata", "authors"}:
                    raise RegistryError("Library source observations require collection method, time, hash, reference, author fields and original metadata.")
                fetched_at = _checked_at(observation["fetched_at"])
                source_hash = _sha(observation["source_sha256"])
                reference = _text(observation["record_reference"], 1000, "private source observation reference")
                if not fetched_at or observation["retrieval_method"] not in {"direct_http", "web_indexed"}:
                    raise RegistryError("Library observations require a timestamp and an explicit retrieval method.")
                source_metadata = _evidence(observation["source_metadata"])
                if not source_metadata:
                    raise RegistryError("Library observations must retain original source metadata.")
                degree_statement = _text(source_metadata.get("degree_statement"), 4000, "observed degree statement")
                statement = re.sub(r"[\s.]+", "", degree_statement).casefold()
                if not any(marker in statement for marker in ("박사", "phd", "doctoral", "doctorof", "dgri:d")) or any(marker in statement for marker in ("석사", "master")):
                    raise RegistryError("The observed library degree statement must explicitly and unambiguously report a PhD.")
                authors = observation["authors"]
                if not isinstance(authors, list) or not 1 <= len(authors) <= 30:
                    raise RegistryError("Library observations require actual author-field values, excluding advisors.")
                observed_authors = {_name(author) for author in authors}
                if _name(degree["source_author_name"]) not in observed_authors or _name(item["author_text"]) not in observed_authors:
                    raise RegistryError("Library author fields must match the source degree author and stored thesis author.")
                observation_hash = hashlib.sha256(_json({"thesis": item, "observation": observation}).encode()).hexdigest()
                thesis_id = _insert_thesis(connection, item, source_hash)
                _insert_link(connection, degree_id, thesis_id, "library_author_institution_phd_year_candidate", {
                    "verification_status": "candidate_needs_human_review",
                    "source_collection_sha256": key, "source_snapshot_sha256": snapshot,
                    "source_sha256": source_hash, "observation_sha256": observation_hash,
                    "retrieval_method": observation["retrieval_method"],
                    "year_distance": abs(item["publication_year"] - degree["award_year"]),
                    "reported_degree_level": item["reported_degree_level"],
                    "matched_source_author": degree["source_author_name"],
                })
                connection.execute("""INSERT OR IGNORE INTO thesis_source_observations
                    (degree_id,thesis_id,observation_sha256,source_sha256,source_snapshot_sha256,fetched_at,retrieval_method,record_reference,metadata)
                    VALUES(?,?,?,?,?,?,?,?,?)""", (degree_id, thesis_id, observation_hash, source_hash, snapshot,
                    fetched_at, observation["retrieval_method"], reference, _json({"authors": authors, "source_metadata": source_metadata, "thesis": item})))
            _reconcile_conflicts(connection)
            result = _finish_batch(connection, key, "library_candidates", {"input_candidates_linked": len(payload["candidates"])})
        return {**_summary(connection), **result}
    finally:
        connection.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for command in ("migrate", "summary", "import", "import-riss", "import-library", "review"):
        sub = commands.add_parser(command)
        sub.add_argument("--database", required=True)
        if command == "import":
            sub.add_argument("--records-json", required=True)
        elif command == "import-riss":
            sub.add_argument("--candidates-json", required=True)
            sub.add_argument("--source-snapshot-sha256")
        elif command == "import-library":
            sub.add_argument("--candidates-json", required=True)
        elif command == "review":
            sub.add_argument("--reviews-json", required=True)
    args = parser.parse_args()
    try:
        if args.command == "migrate":
            result = migrate(args.database)
        elif args.command == "summary":
            result = summary(args.database)
        elif args.command == "import":
            result = import_records(args.database, json.loads(Path(args.records_json).read_text(encoding="utf-8")))
        elif args.command == "import-riss":
            result = import_riss(args.database, json.loads(Path(args.candidates_json).read_text(encoding="utf-8")), args.source_snapshot_sha256)
        elif args.command == "import-library":
            result = import_library(args.database, json.loads(Path(args.candidates_json).read_text(encoding="utf-8")))
        else:
            result = review_links(args.database, json.loads(Path(args.reviews_json).read_text(encoding="utf-8")))
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0
    except RegistryError as exc:
        print(json.dumps({"error": str(exc)}))
    except (OSError, sqlite3.Error, ValueError, TypeError, RecursionError):
        print(json.dumps({"error": "Private thesis registry operation failed; no identities were printed."}))
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
