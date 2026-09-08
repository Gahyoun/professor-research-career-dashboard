"""Synthetic tests only: no real names, private source reads, or network calls."""
import contextlib
import copy
import io
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

import identity_registry as identities
import thesis_registry as registry


SNAPSHOT = "a" * 64


def education(source_id=1, uid="fixture-1", country="KR"):
    return {"source_education_id": source_id, "source_professor_uid": uid,
            "source_author_name": "Synthetic Author " + uid[-1], "degree_level": "phd",
            "institution_unit_id": 10, "institution_canonical": "Fixture University",
            "institution_raw": "Fixture University", "education_country_code": country,
            "education_country_raw": country, "institution_country_code": country,
            "institution_country_raw": country, "award_year": 2000,
            "domestic_status": "domestic" if country == "KR" else "foreign",
            "query_status": "ready" if country == "KR" else "anchor_review_required"}


def thesis(provider="openalex", identifier="W123", doi=None):
    return {"provider": provider, "provider_record_id": identifier, "title": "Synthetic dissertation",
            "author_text": "Synthetic Author 1", "publisher": None, "publication_year": 2000,
            "reported_degree_level": None, "reported_department": None, "doi": doi,
            "source_url": ("https://openalex.org/" + identifier if provider == "openalex" else "https://www.riss.kr/link?id=" + identifier)}


def link(source_id=1, provider="openalex", identifier="W123"):
    return {"source_education_id": source_id, "provider": provider, "provider_record_id": identifier,
            "match_method": "source_dissertation_year_candidate", "evidence": {"year_distance": 0}}


def seed():
    return {"schema_version": 1, "source_snapshot_sha256": SNAPSHOT,
            "education_records": [education()], "thesis_records": [thesis()], "links": [link()]}


def review(degree=1, thesis_id=1, status="verified", **evidence):
    base = {"source_author": "Synthetic Author 1", "source_institution_unit_id": 10,
            "source_title": "Synthetic dissertation", "confirmed_thesis": True,
            "source_award_year": 2000, "source_degree_level": "phd",
            "source_url": "https://www.riss.kr/link?id=T123", "record_reference": "private/inspection/fixture-1",
            "confirmed_author": True, "confirmed_degree": True, "confirmed_institution": True,
            "confirmed_year": True, "no_conflict": True}
    base.update(evidence)
    return {"degree_id": degree, "thesis_id": thesis_id, "status": status,
            "reviewed_by": "Synthetic reviewer", "checked_at": "2025-01-01T00:00:00Z", "evidence": base if status == "verified" else {"notes": "Synthetic alternative rejected after inspection"}}


def riss_collection(country="KR"):
    return {"schema_version": 1, "release_year": 2026, "public_data_sha256": "b" * 64,
            "source": "RISS thesis OpenAPI", "queries": [{
                "professor_uid": "fixture-1", "anon_id": "anon-1", "name": "Synthetic Author 1",
                "institution_unit_id": 10, "institution_canonical": "Fixture University",
                "institution_query": "Fixture University", "country": country, "award_year": 2000,
                "degree_level": "phd", "status": "complete_candidates", "request_attempts": 1,
                "pages_received": 1, "totalcount": 1, "truncated": False,
                "query": {"version": "1.0", "type": "T", "stype": "id" if country == "KR" else "od",
                          "author": "Synthetic Author 1", "publisher": "Fixture University", "spubdate": 2000, "epubdate": 2000},
                "candidates": [{"riss_id": "T123", "source_url": "https://www.riss.kr/link?id=T123",
                    "title": "Synthetic dissertation", "author": "Synthetic Author 1", "publisher": None,
                    "publication_date": "2000.02", "document_type": "학위논문",
                    "material_type": "국내박사" if country == "KR" else "해외박사",
                    "abstract_available": True, "toc_available": False, "fulltext_available": True,
                    "department": None, "verification_status": "candidate_needs_degree_detail"}]}]}


class ThesisRegistryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.database = Path(self.temporary.name).resolve() / "private" / "registry.sqlite"
        identities.init_registry({"researchers": [
            {"source_professor_uid": "fixture-1", "anon_id": "anon-1"},
            {"source_professor_uid": "fixture-2", "anon_id": "anon-2"}]}, self.database)

    def tearDown(self):
        self.temporary.cleanup()

    def rows(self, sql, args=()):
        connection = identities._connect(self.database)
        try:
            return [dict(row) for row in connection.execute(sql, args)]
        finally:
            connection.close()

    def populate(self, payload=None):
        registry.migrate(self.database)
        return registry.import_records(self.database, payload or seed())

    def test_migration_idempotent_preserves_identity_and_permissions(self):
        first = registry.migrate(self.database)
        self.assertEqual(first, registry.migrate(self.database))
        self.assertEqual(len(self.rows("SELECT * FROM researchers")), 2)
        self.assertEqual(self.database.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.database.parent.stat().st_mode & 0o777, 0o700)
        self.assertEqual(self.rows("PRAGMA foreign_key_check"), [])

    def test_migration_failure_rolls_back_all_ddl_and_version(self):
        with sqlite3.connect(self.database) as conn:
            conn.execute("CREATE TABLE thesis_records(dummy TEXT)")
        with self.assertRaises(sqlite3.Error):
            registry.migrate(self.database)
        self.assertEqual(self.rows("PRAGMA user_version")[0]["user_version"], 1)
        self.assertFalse(self.rows("SELECT name FROM sqlite_master WHERE name='education_records'"))
        self.assertEqual(len(self.rows("SELECT * FROM researchers")), 2)

    def test_candidate_idempotency_general_and_domestic_left_join(self):
        payload = seed()
        payload["education_records"].append(education(2, "fixture-2", "GB"))
        result = self.populate(payload)
        self.assertEqual(result["links"], {"candidate": 1})
        self.assertEqual(result["unlinked_degrees"], 1)
        self.assertTrue(registry.import_records(self.database, payload)["already_imported"])
        self.assertEqual(len(self.rows("SELECT * FROM v_phd_theses")), 2)
        self.assertEqual(len(self.rows("SELECT * FROM v_domestic_phd_theses")), 1)
        self.assertIsNone(self.rows("SELECT thesis_id FROM v_phd_theses WHERE domestic_status='foreign'")[0]["thesis_id"])

    def test_fk_and_late_link_failure_roll_back_entire_batch(self):
        registry.migrate(self.database)
        payload = seed()
        payload["education_records"][0]["source_professor_uid"] = "absent-person"
        with self.assertRaises(sqlite3.IntegrityError):
            registry.import_records(self.database, payload)
        self.assertEqual(registry.summary(self.database)["education_records"], 0)
        payload = seed()
        payload["links"][0]["source_education_id"] = 999
        with self.assertRaises(identities.RegistryError):
            registry.import_records(self.database, payload)
        self.assertEqual(registry.summary(self.database)["thesis_records"], 0)
        self.assertEqual(registry.summary(self.database)["import_batches"], 0)

    def test_contradictory_metadata_no_silent_overwrite(self):
        self.populate()
        for collection, field, value in [("education_records", "award_year", 2001), ("thesis_records", "title", "Different title")]:
            changed = seed()
            changed[collection][0][field] = value
            with self.assertRaises(identities.RegistryError):
                registry.import_records(self.database, changed)
        self.assertEqual(registry.summary(self.database)["import_batches"], 1)
        self.assertEqual(self.rows("SELECT award_year FROM education_records")[0]["award_year"], 2000)

    def test_no_imported_verified_or_credentials(self):
        registry.migrate(self.database)
        payload = seed()
        payload["links"][0]["status"] = "verified"
        with self.assertRaises(identities.RegistryError):
            registry.import_records(self.database, payload)
        payload = seed()
        payload["links"][0]["evidence"] = {"nested": {"AgcPw": "fake-secret"}}
        with self.assertRaises(identities.RegistryError):
            registry.import_records(self.database, payload)

    def test_shared_thesis_conflict_rejection_then_explicit_verification(self):
        payload = seed()
        payload["education_records"].append(education(2, "fixture-2"))
        payload["links"].append(link(2))
        self.assertEqual(self.populate(payload)["links"], {"conflict": 2})
        with self.assertRaises(identities.RegistryError):
            registry.review_links(self.database, [review()])
        result = registry.review_links(self.database, [review(), review(2, 1, "rejected")])
        self.assertEqual(result["links"], {"rejected": 1, "verified": 1})
        # A distinct import batch still cannot erase a human rejection/verification.
        repeat = copy.deepcopy(payload)
        repeat["links"][0]["evidence"]["new_raw_observation"] = True
        self.assertEqual(registry.import_records(self.database, repeat)["links"], result["links"])

    def test_review_exact_identity_degree_and_official_detail_requirements(self):
        self.populate()
        invalid = [
            {"source_author": "Another author"}, {"source_institution_unit_id": "11"},
            {"source_title": "An unrelated thesis"}, {"confirmed_thesis": False},
            {"source_doi": "10.1234/unrelated"},
            {"source_award_year": 1999}, {"source_degree_level": "master"},
            {"source_url": "https://openalex.org/W123"}, {"source_url": "https://www.riss.kr/"},
            {"source_url": "https://www.riss.kr/link?id=T123&AgcPw=secret"},
            {"record_reference": ""}, {"no_conflict": False}, {"confirmed_degree": 1},
            {"source_department": "Physics"}, {"unexpected_auth_blob": "none"},
        ]
        for changed in invalid:
            with self.subTest(changed=tuple(changed)):
                with self.assertRaises(identities.RegistryError):
                    registry.review_links(self.database, [review(**changed)])
        self.assertEqual(registry.summary(self.database)["reviews"], 0)
        result = registry.review_links(self.database, [review(source_department="Physics", confirmed_department=True)])
        self.assertEqual(result["links"], {"verified": 1})
        self.assertEqual(self.rows("SELECT verified_department FROM v_phd_theses")[0]["verified_department"], "Physics")

    def test_foreign_review_allowed_country_conflict_and_master_blocked(self):
        payload = seed()
        payload["education_records"][0] = education(country="GB")
        self.populate(payload)
        self.assertEqual(registry.review_links(self.database, [review()])["links"], {"verified": 1})
        with identities._connect(self.database) as conn:
            conn.execute("UPDATE education_records SET domestic_status='country_conflict'")
        changed = review()
        changed["checked_at"] = "2025-02-01T00:00:00Z"
        with self.assertRaises(identities.RegistryError):
            registry.review_links(self.database, [changed])

    def test_duplicate_doi_requires_review_and_no_auto_merge(self):
        payload = seed()
        payload["thesis_records"][0]["doi"] = "https://doi.org/10.1234/Thesis"
        payload["thesis_records"].append(thesis("riss", "T123", "10.1234/thesis"))
        payload["links"].append(link(1, "riss", "T123"))
        result = self.populate(payload)
        self.assertEqual(result["thesis_records"], 2)
        self.assertEqual(result["duplicate_doi_groups"], 1)
        self.assertEqual(self.rows("SELECT other_records_same_doi FROM v_phd_theses")[0]["other_records_same_doi"], 1)
        with self.assertRaises(identities.RegistryError):
            registry.review_links(self.database, [review()])
        self.assertEqual(registry.review_links(self.database, [review(), review(1, 2, "rejected")])["links"], {"rejected": 1, "verified": 1})

    def test_review_batch_rollback_history_append_only_and_idempotent(self):
        self.populate()
        with self.assertRaises(identities.RegistryError):
            registry.review_links(self.database, [review(status="rejected"), review(999)])
        self.assertEqual(registry.summary(self.database)["reviews"], 0)
        registry.review_links(self.database, [review()])
        self.assertTrue(registry.review_links(self.database, [review()])["already_imported"])
        with identities._connect(self.database) as conn:
            for sql in ("DELETE FROM thesis_link_reviews", "UPDATE thesis_link_reviews SET status='rejected'"):
                with self.assertRaises(sqlite3.IntegrityError):
                    conn.execute(sql)
        self.assertEqual(registry.summary(self.database)["reviews"], 1)

    def test_direct_sql_constraints_reject_empty_verification_and_fractional_year(self):
        self.populate()
        with identities._connect(self.database) as conn:
            for sql in (
                "UPDATE degree_thesis_links SET status='verified',reviewed_by='reviewer',checked_at='2025-01-01T00:00:00Z'",
                "UPDATE education_records SET award_year=1990.5",
                "UPDATE thesis_records SET publication_year=1990.5",
                "UPDATE education_records SET education_country_code='KOR'",
                "UPDATE education_records SET institution_country_code='kr'",
                "UPDATE education_records SET institution_country_code='US'",
            ):
                with self.subTest(sql=sql), self.assertRaises(sqlite3.IntegrityError):
                    conn.execute(sql)

    def test_country_inconsistency_rolls_back_and_legacy_corruption_cannot_verify(self):
        registry.migrate(self.database)
        malformed = seed()
        malformed["education_records"][0]["institution_country_code"] = "US"
        with self.assertRaises(identities.RegistryError):
            registry.import_records(self.database, malformed)
        self.assertEqual(registry.summary(self.database)["education_records"], 0)
        missing_country = seed()
        missing_country["education_records"][0].update(institution_country_code=None, domestic_status="domestic_unresolved")
        with self.assertRaises(identities.RegistryError):
            registry.import_records(self.database, missing_country)  # Cannot remain query-ready.
        registry.import_records(self.database, seed())
        # Simulate an externally corrupted old DB; runtime must not trust status alone.
        with identities._connect(self.database) as conn:
            conn.execute("PRAGMA ignore_check_constraints=ON")
            conn.execute("UPDATE education_records SET institution_country_code='US'")
        with self.assertRaises(identities.RegistryError):
            registry.review_links(self.database, [review()])
        with self.assertRaises(identities.RegistryError):
            registry.import_riss(self.database, riss_collection())

    def test_riss_import_candidate_only_missing_fields_foreign_and_idempotent(self):
        payload = seed()
        payload["education_records"][0] = education(country="GB")
        self.populate(payload)
        collection = riss_collection("GB")
        collection["queries"][0]["candidates"].append({"riss_id": None, "source_url": None, "verification_status": "candidate_needs_degree_detail"})
        result = registry.import_riss(self.database, collection)
        self.assertEqual(result["links"], {"candidate": 2})
        self.assertEqual(result["skipped_candidates"], 1)
        self.assertTrue(registry.import_riss(self.database, collection)["already_imported"])
        row = self.rows("SELECT * FROM thesis_records WHERE provider='riss'")[0]
        self.assertIsNone(row["publisher"])
        self.assertIsNone(row["reported_department"])
        self.assertEqual(row["reported_degree_level"], "phd")
        self.assertIsNone(row["source_snapshot_sha256"])

    def test_riss_wrong_id_or_anon_rolls_back_all(self):
        self.populate()
        collection = riss_collection()
        bad = copy.deepcopy(collection["queries"][0]["candidates"][0])
        bad["riss_id"] = "T999"
        collection["queries"][0]["candidates"].append(bad)
        with self.assertRaises(identities.RegistryError):
            registry.import_riss(self.database, collection)

    def test_riss_query_audit_must_match_anchors_and_attempts(self):
        self.populate()
        for field, value in [("stype", "od"), ("author", "Other author"), ("publisher", "Other institution"), ("spubdate", 2020)]:
            collection = riss_collection()
            collection["queries"][0]["query"][field] = value
            with self.subTest(field=field), self.assertRaises(identities.RegistryError):
                registry.import_riss(self.database, collection)
        for status in ("not_queried_due_to_prior_error", "complete_no_matching"):
            collection = riss_collection()
            collection["queries"][0].update(status=status, pages_received=0, request_attempts=0)
            with self.subTest(status=status), self.assertRaises(identities.RegistryError):
                registry.import_riss(self.database, collection)
        self.assertEqual(registry.summary(self.database)["thesis_records"], 1)
        collection = riss_collection()
        collection["queries"][0]["anon_id"] = "anon-2"
        with self.assertRaises(identities.RegistryError):
            registry.import_riss(self.database, collection)

    def test_riss_multiple_snapshots_requires_selector(self):
        self.populate()
        other = seed()
        other["source_snapshot_sha256"] = "c" * 64
        registry.import_records(self.database, other)
        with self.assertRaises(identities.RegistryError):
            registry.import_riss(self.database, riss_collection())
        result = registry.import_riss(self.database, riss_collection(), SNAPSHOT)
        self.assertEqual(result["input_candidates_linked"], 1)

    def test_riss_observation_identifier_and_master_block_verification(self):
        self.populate()
        collection = riss_collection()
        registry.import_riss(self.database, collection)
        with self.assertRaises(identities.RegistryError):
            registry.review_links(self.database, [review(1, 2, source_url="https://www.riss.kr/link?id=T999")])
        with identities._connect(self.database) as conn:
            conn.execute("UPDATE thesis_records SET reported_degree_level='master' WHERE thesis_id=2")
        with self.assertRaises(identities.RegistryError):
            registry.review_links(self.database, [review(1, 2)])

    def test_private_path_guard_and_cli_count_only_error(self):
        self.populate()
        self.database.chmod(0o644)
        with self.assertRaises(identities.RegistryError):
            registry.summary(self.database)
        self.database.chmod(0o600)
        raw = self.database.parent / "synthetic.json"
        payload = seed()
        payload["links"][0]["evidence"] = {"password": "SYNTHETIC_SECRET"}
        raw.write_text(json.dumps(payload))
        output = io.StringIO()
        with patch("sys.argv", ["thesis_registry.py", "import", "--database", str(self.database), "--records-json", str(raw)]), contextlib.redirect_stdout(output):
            self.assertEqual(registry.main(), 1)
        for private_value in ("SYNTHETIC_SECRET", "Synthetic Author", "fixture-1", str(self.database)):
            self.assertNotIn(private_value, output.getvalue())


if __name__ == "__main__":
    unittest.main()
