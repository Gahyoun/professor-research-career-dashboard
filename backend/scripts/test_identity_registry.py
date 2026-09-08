"""Synthetic, temporary-only registry tests; no actual researcher data are loaded."""
import contextlib
import datetime as dt
import io
import json
import os
from pathlib import Path
import sqlite3
import stat
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import identity_registry as registry


def synthetic_orcid(base="000000000000001"):
    total = 0
    for digit in base:
        total = (total + int(digit)) * 2
    result = (12 - total % 11) % 11
    digits = base + ("X" if result == 10 else str(result))
    return "-".join(digits[i:i + 4] for i in range(0, 16, 4))


def candidate(uid="synthetic-a", identifier="000001", namespace="national_researcher_number", **extra):
    return {"source_professor_uid": uid, "namespace": namespace, "identifier": identifier,
            "status": "candidate", "source_kind": "source_database", "source_url": None, "evidence": {}, **extra}


def accepted(uid="synthetic-a", identifier="000001", **extra):
    return candidate(uid, identifier, status="accepted", source_kind="official_registry",
                     source_url="https://www.iris.go.kr/",
                     reviewed_by="Synthetic human reviewer", checked_at=dt.datetime.now(dt.timezone.utc).isoformat(),
                     evidence={"human_reviewed": True, "matched_author": True, "no_conflict": True,
                               "registry_observation": {"namespace": "national_researcher_number", "identifier": identifier,
                                   "source_url": "https://www.iris.go.kr/", "record_reference": "private://synthetic-review/" + uid + "/" + identifier},
                               "shared_dois": ["10.99999/synthetic-a", "10.99999/synthetic-b"],
                               "independent_publication_check": True, "institution_time_agreement": True}, **extra)


class IdentityRegistryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.path = self.root / "private" / "registry.sqlite"
        self.seed = {"researchers": [
            {"source_professor_uid": "synthetic-a", "anon_id": "SYNTHETIC-ANON-A", "openalex_author_ids": ["A1", "A2", "A1"]},
            {"source_professor_uid": "synthetic-b", "anon_id": "SYNTHETIC-ANON-B", "openalex_author_ids": ["A1"]}], "identifier_links": []}

    def tearDown(self):
        self.temp.cleanup()

    def initialize(self):
        return registry.init_registry(self.seed, self.path)

    def query(self, query, values=()):
        with sqlite3.connect(self.path) as connection:
            return connection.execute(query, values).fetchall()

    def test_seed_preserves_multiple_authors_and_shared_identity_conflicts(self):
        orcid = synthetic_orcid()
        self.seed["identifier_links"] = [candidate("synthetic-a", orcid, "orcid"), candidate("synthetic-b", orcid, "orcid")]
        result = self.initialize()
        self.assertEqual(result["openalex_links"], {"conflict": 2, "imported_source_link": 1})
        self.assertEqual(result["identifier_links"], {"orcid:conflict": 2})
        self.assertEqual(stat.S_IMODE(self.path.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(self.path.parent.stat().st_mode), 0o700)
        self.assertNotIn("synthetic", json.dumps(result))

    def test_candidates_preserve_leading_zeros_and_import_idempotently(self):
        self.initialize()
        first = registry.import_identifiers(self.path, [candidate()])
        second = registry.import_identifiers(self.path, [candidate(), candidate()])
        self.assertEqual(first, second)
        self.assertEqual(self.query("SELECT identifier FROM researcher_identifier_links"), [("000001",)])
        with self.assertRaises(registry.RegistryError):
            registry.import_identifiers(self.path, [candidate(identifier=1)])

    def test_incomplete_or_name_and_doi_only_evidence_cannot_be_accepted(self):
        self.initialize()
        for field in ("human_reviewed", "matched_author", "no_conflict", "independent_publication_check", "institution_time_agreement"):
            record = accepted()
            record["evidence"].pop(field)
            with self.assertRaises(registry.RegistryError):
                registry.import_identifiers(self.path, [record])
        record = accepted()
        record["reviewed_by"] = None
        with self.assertRaises(registry.RegistryError):
            registry.import_identifiers(self.path, [record])
        self.assertEqual(self.query("SELECT count(*) FROM researcher_identifier_links"), [(0,)])

    def test_normalized_duplicate_dois_are_one_evidence_item(self):
        self.initialize()
        record = accepted()
        record["evidence"]["shared_dois"] = ["10.99999/Synthetic-A", "https://doi.org/10.99999/synthetic-a", "doi:10.99999/synthetic-a"]
        with self.assertRaises(registry.RegistryError):
            registry.import_identifiers(self.path, [record])
        record["evidence"]["shared_dois"].append("10.99999/synthetic-b")
        self.assertEqual(registry.import_identifiers(self.path, [record])["identifier_links"], {"national_researcher_number:accepted": 1})

    def test_independently_reviewed_same_orcid_is_alternate_evidence(self):
        self.initialize()
        record = accepted()
        orcid = synthetic_orcid()
        record["evidence"] = {"human_reviewed": True, "matched_author": True, "no_conflict": True,
                              "registry_observation": record["evidence"]["registry_observation"],
                              "independent_orcid": {"checked_independently": True, "researcher_orcid": orcid,
                              "target_orcid": orcid, "source_kind": "official_registry", "source_url": "https://orcid.org/" + orcid}}
        registry.import_identifiers(self.path, [record])
        record["identifier"] = "000002"
        record["evidence"]["independent_orcid"]["source_kind"] = "source_database"
        with self.assertRaises(registry.RegistryError):
            registry.import_identifiers(self.path, [record])

    def test_national_and_legacy_acceptance_require_separate_observed_registry_record(self):
        self.initialize()
        for namespace in ("national_researcher_number", "legacy_kri_researcher_number"):
            for change in ("missing", "namespace", "identifier", "unofficial_url", "empty_reference"):
                with self.subTest(namespace=namespace, change=change):
                    record = accepted()
                    record["namespace"] = namespace
                    record["evidence"]["registry_observation"]["namespace"] = namespace
                    observed = record["evidence"]["registry_observation"]
                    if change == "missing":
                        del record["evidence"]["registry_observation"]
                    elif change == "namespace":
                        observed["namespace"] = "orcid"
                    elif change == "identifier":
                        observed["identifier"] = "000002"
                    elif change == "unofficial_url":
                        observed["source_url"] = "https://example.invalid/"
                    else:
                        observed["record_reference"] = "  "
                    with self.assertRaises(registry.RegistryError):
                        registry.import_identifiers(self.path, [record])
        self.assertEqual(self.query("SELECT count(*) FROM researcher_identifier_links"), [(0,)])

    def test_protected_official_registry_record_can_use_private_audit_reference(self):
        self.initialize()
        record = accepted()
        record["evidence"]["registry_observation"]["source_url"] = "https://www.kri.go.kr/protected-review"
        record["evidence"]["registry_observation"]["record_reference"] = ".private/review-evidence/synthetic-record.json#review-1"
        result = registry.import_identifiers(self.path, [record])
        self.assertEqual(result["identifier_links"], {"national_researcher_number:accepted": 1})

    def test_independent_orcid_source_must_reference_the_matching_target(self):
        self.initialize()
        record = accepted()
        orcid, other = synthetic_orcid(), synthetic_orcid("000000000000002")
        record["evidence"]["independent_orcid"] = {
            "checked_independently": True, "researcher_orcid": orcid, "target_orcid": orcid,
            "source_kind": "official_registry", "source_url": "https://orcid.org/" + other,
        }
        # Invalid ORCID source must fail even if the alternative DOI evidence was sufficient.
        with self.assertRaisesRegex(registry.RegistryError, "must match the target"):
            registry.import_identifiers(self.path, [record])
        self.assertEqual(self.query("SELECT count(*) FROM researcher_identifier_links"), [(0,)])
        record["evidence"]["independent_orcid"]["source_url"] = "https://orcid.org/" + orcid
        registry.import_identifiers(self.path, [record])

    def test_known_kri_and_common_credentials_are_rejected_nested_and_in_urls(self):
        self.initialize()
        for key in ("AgcPw", "Kri_certify", "Kri_rshcrRegNo", "Kri_rschrRegNo", "encrypted_researcher_number", "api_key", "access_key", "Cookie"):
            with self.subTest(key=key):
                nested = candidate(evidence={"source_details": [{key: "synthetic-opaque-value"}]})
                with self.assertRaisesRegex(registry.RegistryError, "Credential"):
                    registry.import_identifiers(self.path, [nested])
                for url in (f"https://www.kri.go.kr/?{key}=synthetic-opaque-value", f"https://www.kri.go.kr/?{key}="):
                    with self.assertRaisesRegex(registry.RegistryError, "Credential"):
                        registry.import_identifiers(self.path, [candidate(source_url=url)])
        for url in (" HTTPS://www.kri.go.kr/?AgcPw=synthetic ", "https://www.kri.go.kr/?Agc%2550w=synthetic", "https://www.kri.go.kr/?ordinary=1;Kri_certify=synthetic"):
            with self.assertRaisesRegex(registry.RegistryError, "Credential"):
                registry.import_identifiers(self.path, [candidate(source_url=url)])
        self.assertEqual(self.query("SELECT count(*) FROM researcher_identifier_links"), [(0,)])
        # Numbered parameters are not assumed to be secrets without evidence.
        registry.import_identifiers(self.path, [candidate(source_url="https://www.kri.go.kr/?Kri_Param2=public-context")])

    def test_accepted_evidence_allowlist_rejects_unknown_payloads(self):
        self.initialize()
        for extra in ({"opaque_blob": "synthetic-opaque-value"}, {"notes": {"context": "synthetic"}}):
            record = accepted()
            record["evidence"].update(extra)
            with self.assertRaises(registry.RegistryError):
                registry.import_identifiers(self.path, [record])
        record = accepted()
        orcid = synthetic_orcid()
        record["evidence"]["independent_orcid"] = {"checked_independently": True, "researcher_orcid": orcid,
            "target_orcid": orcid, "source_kind": "official_registry", "source_url": "https://orcid.org/" + orcid,
            "opaque_blob": "synthetic"}
        with self.assertRaises(registry.RegistryError):
            registry.import_identifiers(self.path, [record])

    def test_official_https_hosts_dates_and_orcid_checksums_are_validated(self):
        self.initialize()
        for url in ("http://www.iris.go.kr/", "https://www.iris.go.kr.evil.invalid/", "https://iris.go.kr@evil.invalid/", "https://iris.go.kr:444/", "https://example.invalid/"):
            record = accepted()
            record["source_url"] = url
            with self.assertRaises(registry.RegistryError):
                registry.import_identifiers(self.path, [record])
        for timestamp in ("2026-01-01", "invalid", "2999-01-01T00:00:00Z"):
            record = accepted()
            record["checked_at"] = timestamp
            with self.assertRaises(registry.RegistryError):
                registry.import_identifiers(self.path, [record])
        valid = synthetic_orcid()
        self.assertEqual(registry.normalize_orcid(valid), valid)
        with self.assertRaises(registry.RegistryError):
            registry.normalize_orcid(valid[:-1] + ("1" if valid[-1] == "0" else "0"))

    def test_accepted_collisions_and_late_batch_collision_roll_back(self):
        self.initialize()
        registry.import_identifiers(self.path, [accepted()])
        before = registry.summary(self.path)
        with self.assertRaises(registry.RegistryError):
            registry.import_identifiers(self.path, [candidate(identifier="000099"), accepted("synthetic-b")])
        self.assertEqual(registry.summary(self.path), before)
        with self.assertRaises(registry.RegistryError):
            registry.import_identifiers(self.path, [accepted(identifier="000002")])
        with self.assertRaises(registry.RegistryError):
            registry.import_identifiers(self.path, [accepted("synthetic-b", "000003"), candidate("synthetic-a", "000003")])
        self.assertEqual(registry.summary(self.path), before)

    def test_sql_foreign_key_failure_rolls_back_whole_import(self):
        self.initialize()
        with self.assertRaises(sqlite3.IntegrityError):
            registry.import_identifiers(self.path, [candidate(), candidate("missing-synthetic-uid", "000002")])
        self.assertEqual(self.query("SELECT count(*) FROM researcher_identifier_links"), [(0,)])

    def test_schema_rejects_acceptance_without_review_flags_and_non_numeric_numbers(self):
        self.initialize()
        with sqlite3.connect(self.path) as connection:
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute("""INSERT INTO researcher_identifier_links
                    (source_professor_uid,namespace,identifier,status,source_kind,reviewed_by,checked_at,evidence)
                    VALUES ('synthetic-a','national_researcher_number','000001','accepted','official_registry','reviewer','2020-01-01T00:00:00Z','{}')""")
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute("""INSERT INTO researcher_identifier_links
                    (source_professor_uid,namespace,identifier,status,source_kind)
                    VALUES ('synthetic-a','national_researcher_number','not-numeric','candidate','source_database')""")

    def test_candidates_do_not_overwrite_review_and_new_collision_is_flagged(self):
        self.initialize()
        registry.import_identifiers(self.path, [accepted()])
        registry.import_identifiers(self.path, [candidate()])
        self.assertEqual(self.query("SELECT status FROM researcher_identifier_links"), [("accepted",)])
        registry.import_identifiers(self.path, [candidate("synthetic-b")])
        self.assertEqual(self.query("SELECT status FROM researcher_identifier_links ORDER BY source_professor_uid"), [("conflict",), ("conflict",)])

    def test_seed_cannot_be_accepted_and_failed_init_removes_database(self):
        self.seed["identifier_links"] = [accepted()]
        with self.assertRaises(registry.RegistryError):
            self.initialize()
        self.assertFalse(self.path.exists())

    def test_private_path_overwrite_symlink_and_permissions(self):
        for path in (self.root / "data.sqlite", self.root / "public" / "private" / "x.sqlite", self.root / "Downloads" / "private" / "x.sqlite", self.root / "releases" / "private" / "x.sqlite"):
            with self.assertRaises(registry.RegistryError):
                registry.init_registry(self.seed, path)
        with self.assertRaises(registry.RegistryError):
            registry.init_registry(self.seed, self.root / "private" / ".." / "outside.sqlite")
        self.initialize()
        with self.assertRaises(registry.RegistryError):
            self.initialize()
        self.path.chmod(0o644)
        with self.assertRaises(registry.RegistryError):
            registry.summary(self.path)
        self.path.chmod(0o600)
        linked = self.path.parent / "linked.sqlite"
        linked.symlink_to(self.path)
        with self.assertRaises(registry.RegistryError):
            registry.summary(linked)

    def test_repository_ignore_is_required_even_inside_private_directory(self):
        repo = self.root / "repo"
        repo.mkdir()
        subprocess.run(["git", "init", "-q", str(repo)], check=True, capture_output=True)
        path = repo / "private" / "test.sqlite"
        with self.assertRaises(registry.RegistryError):
            registry.init_registry(self.seed, path)
        (repo / ".gitignore").write_text("/private/\n")
        registry.init_registry(self.seed, path)
        subprocess.run(["git", "-C", str(repo), "add", "-f", "private/test.sqlite"], check=True, capture_output=True)
        with self.assertRaises(registry.RegistryError):
            registry.summary(path)

    def test_credentials_are_rejected_and_cli_summary_never_prints_identity(self):
        self.initialize()
        for extra in ({"password": "synthetic"}, {"evidence": {"access_token": "synthetic"}}, {"source_url": "https://www.iris.go.kr/?session_token=synthetic"}):
            with self.assertRaises(registry.RegistryError):
                registry.import_identifiers(self.path, [candidate(**extra)])
        with patch("sys.argv", ["identity_registry.py", "summary", "--database", str(self.path)]), contextlib.redirect_stdout(io.StringIO()) as captured:
            self.assertEqual(registry.main(), 0)
        self.assertNotIn("synthetic", captured.getvalue())
        self.assertNotIn("A1", captured.getvalue())
        self.assertEqual(json.loads(captured.getvalue())["researchers"], 2)


if __name__ == "__main__":
    unittest.main()
