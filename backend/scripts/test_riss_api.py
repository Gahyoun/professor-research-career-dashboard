"""Synthetic responses only. Never sends an issued or example API key to RISS."""
import contextlib
import io
import json
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlsplit

import riss_api as riss


def metadata(identifier="T1", *, publisher=True):
    return (f"<metadata><riss.type>학위논문</riss.type><riss.title>합성 제목</riss.title>"
            f"<riss.author>합성 연구자</riss.author>" + ("<riss.publisher>합성대학교</riss.publisher>" if publisher else "") +
            f"<riss.pubdate>2000</riss.pubdate><riss.mtype>학위논문</riss.mtype>"
            f"<riss.abstract>Y</riss.abstract><riss.toc>N</riss.toc><riss.image>1</riss.image>"
            f"<url>http://www.riss.kr/link?id={identifier}&amp;key=SHOULD-BE-STRIPPED&amp;author=QUERY-ECHO</url></metadata>")


def response(total=1, items=None, error="0", message="No Error"):
    return (f"<record><head><totalcount>{total}</totalcount><Error>{error}</Error><ErrorMessage>{message}</ErrorMessage></head>"
            + "".join(items if items is not None else [metadata()]) + "</record>").encode()


def queue():
    return {"schema_version": 1, "release_year": 2026, "public_data_sha256": "a" * 64,
            "researchers": [{"professor_uid": f"synthetic-{n}", "anon_id": f"ANON-{n}", "name": "합성 연구자",
                "institution_unit_id": "KR::synthetic::physics", "institution_canonical": "Synthetic University",
                "institution_query": "합성대학교", "country": "KR", "award_year": 2000, "degree_level": "phd"} for n in range(2)]}


class RissApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.queue_path = self.root / "private" / "queue.json"
        self.queue_path.parent.mkdir(mode=0o700)
        self.queue_path.write_text(json.dumps(queue()))
        self.output = self.queue_path.with_name("candidates.json")
        self.environment = patch.dict(os.environ, {"RISS_API_KEY": "SYNTHETIC-KEY-NEVER-SENT"})
        self.environment.start()

    def tearDown(self):
        self.environment.stop()
        self.temp.cleanup()

    def result(self):
        return json.loads(self.output.read_text())

    def test_literal_dotted_xml_siblings_missing_publisher_and_flag_fields(self):
        parsed = riss.parse_response(response(2, [metadata("T1"), metadata("T2", publisher=False)]))
        self.assertEqual(parsed["totalcount"], 2)
        self.assertEqual(len(parsed["candidates"]), 2)
        first, second = parsed["candidates"]
        self.assertTrue(first["abstract_available"])
        self.assertFalse(first["toc_available"])
        self.assertTrue(first["fulltext_available"])
        self.assertNotIn("image_available", first)
        self.assertIsNone(first["department"])
        self.assertIsNone(second["publisher"])
        self.assertEqual(first["source_url"], "https://www.riss.kr/link?id=T1")
        self.assertNotIn("abstract", first)
        self.assertEqual(first["verification_status"], "candidate_needs_degree_detail")

    def test_api_error_html_malformed_and_entity_responses_are_rejected(self):
        samples = [response(0, [], "101", "SECRET AND NAME"), b"<html><body>Login</body></html>", b"<record>",
                   b'<!DOCTYPE record [<!ENTITY x "expanded">]><record>&x;</record>',
                   '<!DOCTYPE record [<!ENTITY x "expanded">]><record>&x;</record>'.encode('utf-16'),
                   b"x" * (riss.MAX_XML_BYTES + 1), b"<record><head><totalcount>0</totalcount></head></record>"]
        for sample in samples:
            with self.subTest(sample_size=len(sample)), self.assertRaises(riss.RissError) as captured:
                riss.parse_response(sample)
            self.assertNotIn("SECRET", str(captured.exception))
        with self.assertRaises(riss.RissError) as captured:
            riss.parse_response(response(0, [], "101", "SECRET AND NAME"))
        self.assertEqual(captured.exception.api_code, "101")

    def test_missing_key_performs_zero_input_output_or_network_operations(self):
        with patch.dict(os.environ, {"RISS_API_KEY": ""}), patch.object(Path, "read_text") as read, patch.object(Path, "stat") as stat_call, patch.object(riss, "private_output") as output, patch.object(riss, "fetch_xml") as network:
            with self.assertRaisesRegex(riss.RissError, "missing_api_key"):
                riss.collect_candidates(self.queue_path, self.output)
            read.assert_not_called(); stat_call.assert_not_called(); output.assert_not_called(); network.assert_not_called()
        self.assertFalse(self.output.exists())

    def test_pagination_is_bounded_and_known_year_author_publisher_filters_are_sent(self):
        request = Mock(side_effect=[response(5, [metadata("T1"), metadata("T2")]), response(5, [metadata("T3"), metadata("T4")])])
        counts = riss.collect_candidates(self.queue_path, self.output, limit=1, max_pages=2, page_size=2, requester=request)
        self.assertEqual(counts["request_attempts"], 2)
        self.assertEqual(counts["verified_candidates"], 0)
        for index, call in enumerate(request.call_args_list):
            parsed = urlsplit(call.args[0]); params = parse_qs(parsed.query)
            self.assertEqual(parsed.scheme, "https"); self.assertEqual(parsed.netloc, "www.riss.kr")
            for key, expected in {"version": "1.0", "type": "T", "stype": "id", "author": "합성 연구자", "publisher": "합성대학교", "spubdate": "2000", "epubdate": "2000", "rsnum": str(1 + index * 2), "rowcount": "2"}.items():
                self.assertEqual(params[key], [expected])
            self.assertNotIn("typeid", params)
        result = self.result()["queries"][0]
        self.assertEqual(result["status"], "incomplete_truncated")
        self.assertEqual(result["totalcount"], 5)
        self.assertEqual(len(result["candidates"]), 4)

    def test_duplicate_record_ids_and_urls_are_deduplicated_and_cannot_imply_completeness(self):
        request = Mock(return_value=response(2, [metadata("T1"), metadata("T1")]))
        riss.collect_candidates(self.queue_path, self.output, limit=1, page_size=2, requester=request)
        result = self.result()["queries"][0]
        self.assertEqual(len(result["candidates"]), 1)
        self.assertEqual(result["status"], "incomplete_truncated")

    def test_real_zero_total_is_complete_but_empty_page_with_positive_total_is_incomplete(self):
        request = Mock(side_effect=[response(0, []), response(4, [])])
        riss.collect_candidates(self.queue_path, self.output, requester=request)
        results = self.result()["queries"]
        self.assertEqual(results[0]["status"], "complete_no_matching")
        self.assertEqual(results[1]["status"], "incomplete_truncated")

    def test_failure_stops_remaining_queries_without_saving_exception_key_or_name_echo(self):
        request = Mock(side_effect=RuntimeError("SYNTHETIC-KEY-NEVER-SENT + 합성 연구자 + https://www.riss.kr/openApi?key=secret"))
        with contextlib.redirect_stdout(io.StringIO()) as out:
            counts = riss.collect_candidates(self.queue_path, self.output, requester=request)
        self.assertEqual(out.getvalue(), "")
        self.assertEqual(counts["request_attempts"], 1)
        results = self.result()["queries"]
        self.assertEqual(results[0]["status"], "incomplete_error")
        self.assertEqual(results[0]["pages_received"], 0)
        self.assertEqual(results[0]["error"], "request_failed")
        self.assertEqual(results[1]["status"], "not_queried_due_to_prior_error")
        self.assertEqual(results[1]["request_attempts"], 0)
        self.assertNotIn("SYNTHETIC-KEY", self.output.read_text())
        self.assertNotIn("openApi?", self.output.read_text())

    def test_api_auth_error_stops_without_error_message_leak(self):
        request = Mock(return_value=response(0, [], "401", "SYNTHETIC-KEY-NEVER-SENT author echo"))
        riss.collect_candidates(self.queue_path, self.output, requester=request)
        result = self.result()["queries"][0]
        self.assertEqual(result["error"], "api_error")
        self.assertEqual(result["api_error_code"], "401")
        self.assertNotIn("author echo", self.output.read_text())
        self.assertEqual(request.call_count, 1)

    def test_output_guards_permissions_and_no_overwrite_precede_requests(self):
        request = Mock(return_value=response(0, []))
        with self.assertRaisesRegex(riss.RissError, "unsafe_private_output"):
            riss.collect_candidates(self.queue_path, self.root / "public" / "private" / "x.json", requester=request)
        request.assert_not_called()
        riss.collect_candidates(self.queue_path, self.output, limit=1, requester=request)
        self.assertEqual(stat.S_IMODE(self.output.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(self.output.with_suffix(".audit.json").stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(self.output.parent.stat().st_mode), 0o700)
        request.reset_mock()
        with self.assertRaisesRegex(riss.RissError, "output_exists"):
            riss.collect_candidates(self.queue_path, self.output, requester=request)
        request.assert_not_called()

    def test_only_public_riss_detail_identifiers_survive_url_validation(self):
        valid, identifier = riss.normalize_detail_url("https://www.riss.kr/search/detail/DetailView.do?control_no=abc123&p_mat_type=xyz&key=secret&author=private")
        self.assertEqual(identifier, "control:abc123")
        self.assertEqual(parse_qs(urlsplit(valid).query), {"control_no": ["abc123"], "p_mat_type": ["xyz"]})
        for url in ("https://evil.invalid/link?id=T1", "https://www.riss.kr/search/Search.do?author=private", "https://www.riss.kr@evil.invalid/link?id=T1", "https://www.riss.kr/openApi?key=secret"):
            self.assertEqual(riss.normalize_detail_url(url), (None, None))

    def test_fetch_rejects_wrong_origin_and_redirect_handler_never_follows(self):
        with patch.object(riss, "build_opener") as opener:
            for url in ("http://www.riss.kr/openApi?key=synthetic", "https://evil.invalid/openApi", "https://www.riss.kr/other"):
                with self.assertRaisesRegex(riss.RissError, "invalid_api_origin"):
                    riss.fetch_xml(url)
            opener.assert_not_called()
        with self.assertRaisesRegex(riss.RissError, "redirect_refused"):
            riss._NoRedirect().redirect_request(None, None, 302, "redirect", {}, "http://www.riss.kr/openApi")

    def test_cli_missing_key_prints_only_safe_status_and_bad_arguments_do_not_echo_secret(self):
        args = ["riss_api.py", "--queue-json", str(self.queue_path), "--output", str(self.output)]
        with patch.dict(os.environ, {"RISS_API_KEY": ""}), patch("sys.argv", args), contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(riss.main(), 1)
        self.assertEqual(json.loads(out.getvalue()), {"error": "missing_api_key", "request_attempts": 0, "written_files": 0})
        with patch("sys.argv", args + ["--api-key", "SYNTHETIC-SECRET"]), contextlib.redirect_stderr(io.StringIO()) as err:
            with self.assertRaises(SystemExit):
                riss.main()
        self.assertNotIn("SYNTHETIC-SECRET", err.getvalue())

    def test_cli_api_failure_preserves_audit_but_returns_nonzero_without_identity_output(self):
        args = ["riss_api.py", "--queue-json", str(self.queue_path), "--output", str(self.output)]
        with patch("sys.argv", args), patch.object(riss, "fetch_xml", return_value=response(0, [], "401", "SYNTHETIC-KEY-NEVER-SENT 합성 연구자")) as request, contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(riss.main(), 1)
        self.assertEqual(request.call_count, 1)
        self.assertTrue(self.output.with_suffix(".audit.json").is_file())
        self.assertEqual(json.loads(out.getvalue())["incomplete_queries"], 1)
        self.assertNotIn("SYNTHETIC-KEY", out.getvalue())
        self.assertNotIn("합성", out.getvalue())

    def test_cli_incomplete_pagination_or_unattempted_queries_are_not_success(self):
        args = ["riss_api.py", "--queue-json", str(self.queue_path), "--output", str(self.output)]
        for incomplete, unattempted, expected in [(0, 0, 0), (1, 0, 1), (0, 1, 1)]:
            with self.subTest(incomplete=incomplete, unattempted=unattempted), patch("sys.argv", args), patch.object(riss, "collect_candidates", return_value={"incomplete_queries": incomplete, "not_queried": unattempted}), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(riss.main(), expected)


if __name__ == "__main__":
    unittest.main()
