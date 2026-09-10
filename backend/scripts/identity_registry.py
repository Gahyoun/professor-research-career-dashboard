"""Offline private identity registry. No network, public export, or authentication logic."""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
from pathlib import Path
import re
import sqlite3
import stat
import subprocess
from typing import Any
from urllib.parse import parse_qs, unquote, urlsplit

SCHEMA = Path(__file__).with_name("identity_registry_schema.sql")
NAMESPACES = {"national_researcher_number", "legacy_kri_researcher_number", "orcid"}
STATUSES = {"candidate", "accepted", "rejected", "conflict"}
SOURCE_KINDS = {"source_database", "official_registry", "publication", "manual_review"}
FORBIDDEN_KEYS = (
    "password", "token", "secret", "loginid", "loginname", "username", "credential", "authorization",
    "cookie", "apikey", "accesskey", "agcpw", "kricertify", "krirshcrregno", "krirschrregno",
    "encryptedresearchernumber", "encryptednationalresearchernumber", "encryptedresearcherno",
)
ACCEPTED_EVIDENCE_KEYS = {
    "human_reviewed", "matched_author", "no_conflict", "independent_orcid", "shared_dois",
    "independent_publication_check", "institution_time_agreement", "registry_observation", "notes",
}
INDEPENDENT_ORCID_KEYS = {"checked_independently", "researcher_orcid", "target_orcid", "source_kind", "source_url"}
REGISTRY_OBSERVATION_KEYS = {"namespace", "identifier", "source_url", "record_reference"}
FORBIDDEN_DIRECTORIES = {"public", "downloads", "release", "releases", "dist", "outputs"}


class RegistryError(ValueError):
    """Messages are deliberately identity-free and safe for count-only CLI output."""


def _text(value: Any, maximum: int, description: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum or any(ord(c) < 32 for c in value):
        raise RegistryError(f"Invalid {description}.")
    return value.strip()


def _no_credentials(value: Any) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            decoded = str(key)
            for _ in range(3):
                decoded = unquote(decoded)
            normalized = re.sub(r"[^a-z0-9]", "", decoded.lower())
            if any(word in normalized for word in FORBIDDEN_KEYS):
                raise RegistryError("Credential fields are prohibited.")
            _no_credentials(child)
    elif isinstance(value, list):
        for child in value:
            _no_credentials(child)
    elif isinstance(value, str) and value.lstrip().lower().startswith(("https://", "http://")):
        parsed = urlsplit(value.strip())
        if parsed.username or parsed.password:
            raise RegistryError("Credential-bearing source URLs are prohibited.")
        _no_credentials(parse_qs(parsed.query.replace(";", "&"), keep_blank_values=True))


def normalize_orcid(value: str) -> str:
    value = _text(value, 100, "ORCID")
    if value.startswith("https://"):
        parsed = urlsplit(value)
        if parsed.hostname not in {"orcid.org", "www.orcid.org"} or parsed.query or parsed.fragment or parsed.username or parsed.password:
            raise RegistryError("Invalid ORCID URL.")
        value = parsed.path.strip("/")
    compact = value.replace("-", "").upper()
    if not re.fullmatch(r"[0-9]{15}[0-9X]", compact):
        raise RegistryError("Invalid ORCID format.")
    total = 0
    for digit in compact[:15]:
        total = (total + int(digit)) * 2
    result = (12 - total % 11) % 11
    if compact[-1] != ("X" if result == 10 else str(result)):
        raise RegistryError("Invalid ORCID checksum.")
    return "-".join(compact[i:i + 4] for i in range(0, 16, 4))


def normalize_doi(value: Any) -> str:
    value = _text(value, 1000, "DOI").lower()
    value = re.sub(r"^doi:\s*", "", value)
    if value.startswith(("https://", "http://")):
        parsed = urlsplit(value)
        if parsed.hostname not in {"doi.org", "dx.doi.org"} or parsed.query or parsed.fragment or parsed.username or parsed.password:
            raise RegistryError("Invalid DOI URL.")
        value = unquote(parsed.path.lstrip("/"))
    if not re.fullmatch(r"10\.[0-9]{4,9}/[^\s]+", value):
        raise RegistryError("Invalid DOI format.")
    return value


def _official_url(value: Any, namespace: str) -> str:
    value = _text(value, 2048, "official source URL")
    parsed = urlsplit(value)
    allowed = {"orcid.org"} if namespace == "orcid" else {"kri.go.kr", "iris.go.kr"}
    host = (parsed.hostname or "").lower()
    try:
        valid_port = parsed.port in {None, 443}
    except ValueError:
        valid_port = False
    if parsed.scheme != "https" or parsed.username or parsed.password or not valid_port or not any(host == domain or host.endswith("." + domain) for domain in allowed):
        raise RegistryError("Accepted identifiers require an official HTTPS registry source.")
    return value


def _checked_at(value: Any) -> str | None:
    if value is None:
        return None
    value = _text(value, 50, "review date")
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None or parsed.utcoffset() is None or parsed > dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=5):
            raise ValueError
    except ValueError as exc:
        raise RegistryError("Review date must be a non-future ISO timestamp with timezone.") from exc
    return parsed.isoformat()


def _accepted_evidence(record: dict[str, Any]) -> None:
    evidence = record["evidence"]
    if set(evidence) - ACCEPTED_EVIDENCE_KEYS:
        raise RegistryError("Accepted evidence contains unsupported fields.")
    if "notes" in evidence and (not isinstance(evidence["notes"], str) or len(evidence["notes"]) > 2000):
        raise RegistryError("Review notes must be bounded plain text.")
    for key in ("human_reviewed", "matched_author", "no_conflict", "independent_publication_check", "institution_time_agreement"):
        if key in evidence and not isinstance(evidence[key], bool):
            raise RegistryError("Review attestations must be explicit booleans.")
    if not record["reviewed_by"] or not record["checked_at"] or record["source_kind"] != "official_registry":
        raise RegistryError("Acceptance requires a named human reviewer, review time, and official registry source.")
    if any(evidence.get(key) is not True for key in ("human_reviewed", "matched_author", "no_conflict")):
        raise RegistryError("Acceptance requires explicit human author-match and conflict review.")
    _official_url(record["source_url"], record["namespace"])
    if record["namespace"] == "orcid" and normalize_orcid(record["source_url"]) != record["identifier"]:
        raise RegistryError("The official ORCID source must match the reviewed identifier.")
    observation = evidence.get("registry_observation")
    if record["namespace"] != "orcid" or observation is not None:
        if not isinstance(observation, dict) or set(observation) != REGISTRY_OBSERVATION_KEYS:
            raise RegistryError("Acceptance requires an explicit observed registry record with a private audit reference.")
        if observation["namespace"] != record["namespace"] or observation["identifier"] != record["identifier"]:
            raise RegistryError("Observed registry namespace and identifier must match the reviewed identifier exactly.")
        _official_url(observation["source_url"], record["namespace"])
        _text(observation["record_reference"], 1000, "private registry record reference")
    same_orcid = False
    match = evidence.get("independent_orcid")
    if match is not None and (not isinstance(match, dict) or set(match) - INDEPENDENT_ORCID_KEYS):
        raise RegistryError("Independent ORCID evidence contains unsupported fields.")
    if isinstance(match, dict) and match.get("checked_independently") is True and match.get("source_kind") == "official_registry":
        researcher_orcid = normalize_orcid(match.get("researcher_orcid"))
        target_orcid = normalize_orcid(match.get("target_orcid"))
        _official_url(match.get("source_url"), "orcid")
        if normalize_orcid(match["source_url"]) != target_orcid:
            raise RegistryError("Independent ORCID source must match the target ORCID.")
        same_orcid = researcher_orcid == target_orcid
        if record["namespace"] == "orcid":
            same_orcid = same_orcid and target_orcid == record["identifier"]
    shared = evidence.get("shared_dois", [])
    if not isinstance(shared, list):
        raise RegistryError("Shared DOI evidence must be a list.")
    distinct_dois = {normalize_doi(doi) for doi in shared}
    publications = len(distinct_dois) >= 2 and evidence.get("independent_publication_check") is True and evidence.get("institution_time_agreement") is True
    if not (same_orcid or publications):
        raise RegistryError("Acceptance needs independently checked matching ORCID or two distinct independently checked shared DOIs plus institution/time agreement.")


def validate_identifier_record(value: Any, *, seed: bool = False) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise RegistryError("Identifier records must be objects.")
    _no_credentials(value)
    allowed = {"source_professor_uid", "namespace", "identifier", "status", "source_url", "source_kind", "reviewed_by", "checked_at", "evidence"}
    if set(value) - allowed:
        raise RegistryError("Unsupported identifier fields.")
    uid = _text(value.get("source_professor_uid"), 200, "source UID")
    namespace = value.get("namespace")
    if namespace not in NAMESPACES:
        raise RegistryError("Unsupported identifier namespace.")
    identifier = _text(value.get("identifier"), 100, "identifier")
    if namespace == "orcid":
        identifier = normalize_orcid(identifier)
    elif not re.fullmatch(r"[0-9]{1,32}", identifier):
        raise RegistryError("Researcher numbers must be digit strings of at most 32 digits; leading zeros are preserved.")
    status_value = value.get("status", "candidate")
    if status_value not in STATUSES or (seed and status_value not in {"candidate", "conflict"}):
        raise RegistryError("Invalid status; source seeds cannot contain review decisions.")
    source_kind = value.get("source_kind", "source_database")
    if source_kind not in SOURCE_KINDS:
        raise RegistryError("Unsupported source kind.")
    source_url = value.get("source_url")
    if source_url is not None:
        source_url = _text(source_url, 2048, "source URL")
        parsed = urlsplit(source_url)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
            raise RegistryError("Sources must use HTTPS and contain no credentials.")
    reviewer = value.get("reviewed_by")
    if reviewer is not None:
        reviewer = _text(reviewer, 200, "reviewer")
    evidence = value.get("evidence", {})
    if not isinstance(evidence, dict) or len(json.dumps(evidence, ensure_ascii=False)) > 100_000:
        raise RegistryError("Evidence must be a bounded JSON object.")
    result = dict(source_professor_uid=uid, namespace=namespace, identifier=identifier, status=status_value,
                  source_url=source_url, source_kind=source_kind, reviewed_by=reviewer, checked_at=_checked_at(value.get("checked_at")), evidence=evidence)
    if status_value == "accepted":
        _accepted_evidence(result)
    return result


def _private_path(value: str | Path, *, exists: bool) -> Path:
    path = Path(os.path.abspath(Path(value).expanduser()))
    if path.suffix.lower() not in {".sqlite", ".sqlite3", ".db"}:
        raise RegistryError("Private registry output must be a SQLite database file.")
    private_roots = [parent for parent in path.parents if parent.name in {"private", ".private"} and parent.parent != Path("/")]
    if any(part.lower() in FORBIDDEN_DIRECTORIES for part in path.parts) or not private_roots:
        raise RegistryError("Registry must be under a private/.private directory outside publication and download paths.")
    for parent in [path, *path.parents]:
        if parent.is_symlink():
            raise RegistryError("Symlinks are not permitted in private registry paths.")
    repo = next((parent for parent in path.parents if (parent / ".git").exists()), None)
    if repo:
        try:
            relative = str(path.relative_to(repo))
            tracked = subprocess.run(["git", "-C", str(repo), "ls-files", "--error-unmatch", "--", relative], capture_output=True, check=False)
            ignored = subprocess.run(["git", "-C", str(repo), "check-ignore", "-q", "--", relative], capture_output=True, check=False)
        except OSError as exc:
            raise RegistryError("Cannot verify private Git exclusion.") from exc
        if tracked.returncode == 0 or ignored.returncode != 0:
            raise RegistryError("Private registry must be untracked and covered by repository ignore rules.")
    if exists:
        try:
            info, parent_info = path.stat(), path.parent.stat()
        except OSError as exc:
            raise RegistryError("Private registry does not exist.") from exc
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o600 or stat.S_IMODE(parent_info.st_mode) != 0o700:
            raise RegistryError("Registry requires a private owned regular file (0600), one link, and parent directory (0700).")
    elif path.exists():
        raise RegistryError("Refusing to replace an existing registry.")
    return path


def _connect(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys=ON")
    connection.execute("PRAGMA journal_mode=DELETE")
    connection.execute("PRAGMA busy_timeout=5000")
    return connection


def _normalize_author(value: Any) -> str:
    value = _text(value, 100, "OpenAlex author ID")
    if value.startswith("https://openalex.org/"):
        value = value.removeprefix("https://openalex.org/")
    if not re.fullmatch(r"A[1-9][0-9]{0,20}", value):
        raise RegistryError("Invalid OpenAlex author ID.")
    return value


def _reconcile_conflicts(connection: sqlite3.Connection) -> None:
    connection.execute("""UPDATE openalex_author_links SET status='conflict'
        WHERE status <> 'rejected' AND author_id IN
        (SELECT author_id FROM openalex_author_links WHERE status <> 'rejected' GROUP BY author_id HAVING count(DISTINCT source_professor_uid)>1)""")
    connection.execute("""UPDATE researcher_identifier_links SET status='conflict'
        WHERE status <> 'rejected' AND (namespace,identifier) IN
        (SELECT namespace,identifier FROM researcher_identifier_links WHERE status <> 'rejected'
         GROUP BY namespace,identifier HAVING count(DISTINCT source_professor_uid)>1)""")


def _import_records(connection: sqlite3.Connection, records: list[Any], *, seed: bool = False) -> None:
    normalized = [validate_identifier_record(value, seed=seed) for value in records]
    for accepted in (r for r in normalized if r["status"] == "accepted"):
        if any(r["namespace"] == accepted["namespace"] and r["identifier"] == accepted["identifier"] and r["source_professor_uid"] != accepted["source_professor_uid"] and r["status"] != "rejected" for r in normalized):
            raise RegistryError("Acceptance conflicts with another record in this import.")
    for record in normalized:
        key = (record["source_professor_uid"], record["namespace"], record["identifier"])
        if record["status"] == "accepted":
            other = connection.execute("""SELECT 1 FROM researcher_identifier_links
                WHERE namespace=? AND status <> 'rejected' AND
                ((identifier=? AND source_professor_uid<>?) OR
                 (source_professor_uid=? AND identifier<>? AND status='accepted')) LIMIT 1""",
                (key[1], key[2], key[0], key[0], key[2])).fetchone()
            if other:
                raise RegistryError("Acceptance conflicts with an existing identifier link; resolve candidates first.")
        existing = connection.execute("SELECT status FROM researcher_identifier_links WHERE source_professor_uid=? AND namespace=? AND identifier=?", key).fetchone()
        if existing and existing["status"] in {"accepted", "rejected"} and record["status"] == "candidate":
            continue  # Repeated raw-source imports do not override a human decision.
        record["evidence"] = json.dumps(record["evidence"], ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
        connection.execute("""INSERT INTO researcher_identifier_links
            (source_professor_uid,namespace,identifier,status,source_url,source_kind,reviewed_by,checked_at,evidence)
            VALUES (:source_professor_uid,:namespace,:identifier,:status,:source_url,:source_kind,:reviewed_by,:checked_at,:evidence)
            ON CONFLICT(source_professor_uid,namespace,identifier) DO UPDATE SET
            status=excluded.status,source_url=excluded.source_url,source_kind=excluded.source_kind,
            reviewed_by=excluded.reviewed_by,checked_at=excluded.checked_at,evidence=excluded.evidence""", record)
    _reconcile_conflicts(connection)


def init_registry(seed: Any, output: str | Path) -> dict[str, Any]:
    if not isinstance(seed, dict) or set(seed) - {"researchers", "openalex_author_links", "identifier_links"}:
        raise RegistryError("Invalid seed schema.")
    _no_credentials(seed)
    if not isinstance(seed.get("researchers"), list) or any(not isinstance(seed.get(k, []), list) for k in ("openalex_author_links", "identifier_links")):
        raise RegistryError("Seed collections must be lists.")
    path = _private_path(output, exists=False)
    private_ancestor = next(parent for parent in path.parents if parent.name in {"private", ".private"} and parent.parent != Path("/"))
    private_ancestor.mkdir(parents=True, exist_ok=True, mode=0o700)
    private_ancestor.chmod(0o700)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.parent.chmod(0o700)
    previous_umask = os.umask(0o077)
    connection = None
    created = False
    try:
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_RDWR, 0o600)
        os.close(descriptor)
        created = True
        connection = _connect(path)
        connection.executescript(SCHEMA.read_text(encoding="utf-8"))
        with connection:
            author_links = list(seed.get("openalex_author_links", []))
            for person in seed["researchers"]:
                if not isinstance(person, dict) or set(person) - {"source_professor_uid", "anon_id", "openalex_author_ids"}:
                    raise RegistryError("Unsupported researcher seed fields.")
                uid = _text(person.get("source_professor_uid"), 200, "source UID")
                anon = _text(person.get("anon_id"), 100, "anonymous ID")
                prior = connection.execute("SELECT anon_id FROM researchers WHERE source_professor_uid=?", (uid,)).fetchone()
                if prior and prior["anon_id"] != anon:
                    raise RegistryError("Conflicting researcher mapping in seed.")
                connection.execute("INSERT OR IGNORE INTO researchers VALUES (?,?)", (uid, anon))
                if not connection.execute("SELECT 1 FROM researchers WHERE source_professor_uid=? AND anon_id=?", (uid, anon)).fetchone():
                    raise RegistryError("Anonymous ID is assigned to multiple researchers.")
                authors = person.get("openalex_author_ids", [])
                if not isinstance(authors, list):
                    raise RegistryError("OpenAlex IDs must be a list.")
                author_links.extend({"source_professor_uid": uid, "author_id": author} for author in authors)
            for link in author_links:
                if not isinstance(link, dict) or set(link) != {"source_professor_uid", "author_id"}:
                    raise RegistryError("Invalid OpenAlex link seed.")
                connection.execute("INSERT OR IGNORE INTO openalex_author_links(source_professor_uid,author_id) VALUES (?,?)",
                                   (_text(link["source_professor_uid"], 200, "source UID"), _normalize_author(link["author_id"])))
            _import_records(connection, seed.get("identifier_links", []), seed=True)
        return _summary(connection)
    except Exception:
        if connection:
            connection.close()
            connection = None
        if created:
            path.unlink(missing_ok=True)
            Path(str(path) + "-journal").unlink(missing_ok=True)
        raise
    finally:
        if connection:
            connection.close()
        os.umask(previous_umask)


def import_identifiers(database: str | Path, records: Any) -> dict[str, Any]:
    if isinstance(records, dict) and set(records) == {"identifier_links"}:
        records = records["identifier_links"]
    if not isinstance(records, list):
        raise RegistryError("Import input must be a list of identifier records.")
    path = _private_path(database, exists=True)
    connection = _connect(path)
    try:
        # Version 2 adds normalized PhD/thesis tables without changing identity tables.
        if connection.execute("PRAGMA user_version").fetchone()[0] not in {1, 2, 3, 4}:
            raise RegistryError("Unsupported registry version.")
        with connection:
            connection.execute("BEGIN IMMEDIATE")
            _import_records(connection, records)
        return _summary(connection)
    finally:
        connection.close()


def _summary(connection: sqlite3.Connection) -> dict[str, Any]:
    return {"researchers": connection.execute("SELECT count(*) FROM researchers").fetchone()[0],
            "openalex_links": {r["status"]: r["n"] for r in connection.execute("SELECT status,count(*) n FROM openalex_author_links GROUP BY status")},
            "identifier_links": {f"{r['namespace']}:{r['status']}": r["n"] for r in connection.execute("SELECT namespace,status,count(*) n FROM researcher_identifier_links GROUP BY namespace,status")}}


def summary(database: str | Path) -> dict[str, Any]:
    connection = _connect(_private_path(database, exists=True))
    try:
        return _summary(connection)
    finally:
        connection.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    initialize = sub.add_parser("init")
    initialize.add_argument("--seed-json", required=True)
    initialize.add_argument("--output", required=True)
    importer = sub.add_parser("import")
    importer.add_argument("--database", required=True)
    importer.add_argument("--records-json", required=True)
    report = sub.add_parser("summary")
    report.add_argument("--database", required=True)
    args = parser.parse_args()
    try:
        if args.command == "init":
            result = init_registry(json.loads(Path(args.seed_json).read_text(encoding="utf-8")), args.output)
        elif args.command == "import":
            result = import_identifiers(args.database, json.loads(Path(args.records_json).read_text(encoding="utf-8")))
        else:
            result = summary(args.database)
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0
    except RegistryError as exc:
        print(json.dumps({"error": str(exc)}))
    except (OSError, sqlite3.Error, ValueError, TypeError):
        print(json.dumps({"error": "Private registry operation failed; no identities were printed."}))
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
