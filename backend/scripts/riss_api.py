#!/usr/bin/env python3
"""Bounded private RISS thesis candidate collection; never verifies a degree or person."""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import re
import ssl
from typing import Any, Callable
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, HTTPSHandler, ProxyHandler, Request, build_opener
import xml.etree.ElementTree as ET

from build_identity_seed import private_output, write_new_jsons

ENDPOINT = "https://www.riss.kr/openApi"
MAX_XML_BYTES = 2 * 1024 * 1024
MAX_QUEUE_BYTES = 8 * 1024 * 1024
TIMEOUT_SECONDS = 15
QUEUE_FIELDS = {"professor_uid", "anon_id", "name", "institution_unit_id", "institution_canonical", "institution_query", "country", "award_year", "degree_level"}


class RissError(ValueError):
    """Only predefined, non-identifying error codes may cross the CLI boundary."""
    def __init__(self, code: str, *, api_code: str | None = None):
        super().__init__(code)
        self.code = code
        self.api_code = api_code


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise RissError("redirect_refused")


def fetch_xml(url: str) -> bytes:
    parsed = urlsplit(url)
    if parsed.scheme != "https" or parsed.netloc != "www.riss.kr" or parsed.path != "/openApi" or parsed.fragment:
        raise RissError("invalid_api_origin")
    opener = build_opener(ProxyHandler({}), _NoRedirect(), HTTPSHandler(context=ssl.create_default_context()))
    try:
        request = Request(url, headers={"Accept": "application/xml,text/xml", "User-Agent": "K-STEM-private-thesis-review/1.0"})
        with opener.open(request, timeout=TIMEOUT_SECONDS) as response:
            # Defensive origin check even though redirects are disabled.
            final = urlsplit(response.geturl())
            if final.scheme != "https" or final.netloc != "www.riss.kr" or final.path != "/openApi":
                raise RissError("invalid_api_origin")
            body = response.read(MAX_XML_BYTES + 1)
    except RissError:
        raise
    except Exception:
        # urllib exceptions can contain the full key- and name-bearing request URL.
        raise RissError("request_failed") from None
    if len(body) > MAX_XML_BYTES:
        raise RissError("response_too_large")
    return body


class _PlainText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_data(self, data):
        self.parts.append(data)


def _clean_text(value: str | None, maximum: int = 4000) -> str | None:
    if not value:
        return None
    parser = _PlainText()
    parser.feed(value)
    clean = re.sub(r"\s+", " ", " ".join(parser.parts)).strip()
    return clean[:maximum] if clean else None


def normalize_detail_url(value: str | None) -> tuple[str | None, str | None]:
    """Keep only public record identifiers; discard request keys and search echoes."""
    if not value or len(value) > 4000:
        return None, None
    try:
        parsed = urlsplit(value.strip())
        host = (parsed.hostname or "").lower()
        if parsed.scheme not in {"https", "http"} or host not in {"riss.kr", "www.riss.kr", "m.riss.kr"} or parsed.username or parsed.password or parsed.port not in {None, 80, 443}:
            return None, None
        params = parse_qs(parsed.query)
        if parsed.path.rstrip("/") == "/link":
            identifier = params.get("id", [""])[0]
            if re.fullmatch(r"T[0-9]{1,30}", identifier):
                return "https://www.riss.kr/link?" + urlencode({"id": identifier}), identifier
        if parsed.path in {"/search/detail/DetailView.do", "/search/detail/detailView.do"}:
            control = params.get("control_no", [""])[0]
            material = params.get("p_mat_type", [""])[0]
            if re.fullmatch(r"[a-zA-Z0-9_-]{1,128}", control):
                kept = {"control_no": control}
                if re.fullmatch(r"[a-zA-Z0-9_-]{1,128}", material):
                    kept["p_mat_type"] = material
                return urlunsplit(("https", "www.riss.kr", "/search/detail/DetailView.do", urlencode(kept), "")), "control:" + control
    except (ValueError, TypeError):
        pass
    return None, None


def _tag(element: ET.Element) -> str:
    return element.tag.rsplit("}", 1)[-1] if isinstance(element.tag, str) else ""


def _child(element: ET.Element, name: str) -> str | None:
    values = ["".join(child.itertext()) for child in element if _tag(child) == name]
    return "; ".join(values) if values else None


def _flag(value: str | None) -> bool | None:
    if value is None:
        return None
    lowered = value.strip().lower()
    if lowered in {"y", "yes", "true", "1"}:
        return True
    if lowered in {"n", "no", "false", "0"}:
        return False
    return None


def parse_response(body: bytes) -> dict[str, Any]:
    if not isinstance(body, bytes) or len(body) > MAX_XML_BYTES:
        raise RissError("response_too_large")
    # Reject entity definitions before invoking the standard XML parser, including UTF-16 spellings.
    inspected = body.replace(b"\x00", b"").upper()
    if b"<!DOCTYPE" in inspected or b"<!ENTITY" in inspected:
        raise RissError("unsafe_xml")
    try:
        root = ET.fromstring(body)
    except (ET.ParseError, ValueError):
        raise RissError("invalid_xml") from None
    if _tag(root) != "record":
        raise RissError("unexpected_response_root")
    heads = [child for child in root if _tag(child) == "head"]
    if len(heads) != 1:
        raise RissError("missing_response_header")
    error = (_child(heads[0], "Error") or "").strip()
    if error != "0":
        if not error:
            raise RissError("missing_api_status")
        # ErrorMessage is never retained; it can echo the request and API key.
        raise RissError("api_error", api_code=error if re.fullmatch(r"[0-9]{1,10}", error) else "unclassified")
    total = (_child(heads[0], "totalcount") or "").strip()
    if not re.fullmatch(r"[0-9]{1,10}", total):
        raise RissError("invalid_totalcount")
    metadata = [child for child in root if _tag(child) == "metadata"]
    if len(metadata) > 100:
        raise RissError("too_many_records")
    candidates: list[dict[str, Any]] = []
    for item in metadata:
        source_url, riss_id = normalize_detail_url(_child(item, "url"))
        candidate = {
            "riss_id": riss_id, "source_url": source_url,
            "title": _clean_text(_child(item, "riss.title")),
            "author": _clean_text(_child(item, "riss.author")),
            "publisher": _clean_text(_child(item, "riss.publisher")),
            "publication_date": _clean_text(_child(item, "riss.pubdate"), 100),
            "document_type": _clean_text(_child(item, "riss.type"), 200),
            "material_type": _clean_text(_child(item, "riss.mtype"), 200),
            "abstract_available": _flag(_child(item, "riss.abstract")),
            "toc_available": _flag(_child(item, "riss.toc")),
            "fulltext_available": _flag(_child(item, "riss.image")),
            "department": None, "verification_status": "candidate_needs_degree_detail",
        }
        # Do not fabricate candidates from entirely empty metadata containers.
        if any(candidate[key] for key in ("riss_id", "source_url", "title", "author", "publisher", "publication_date")):
            candidates.append(candidate)
    return {"totalcount": int(total), "metadata_count": len(metadata), "candidates": candidates}


def _bounded_string(value: Any, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum or any(ord(c) < 32 for c in value):
        raise RissError("invalid_queue_record")
    return value.strip()


def validate_queue(queue: Any) -> dict[str, Any]:
    if not isinstance(queue, dict) or set(queue) != {"schema_version", "release_year", "public_data_sha256", "researchers"} or queue["schema_version"] != 1:
        raise RissError("invalid_queue_schema")
    release = queue["release_year"]
    if type(release) is not int or not 1900 <= release <= 3000 or not isinstance(queue["public_data_sha256"], str) or not re.fullmatch(r"[0-9a-fA-F]{64}", queue["public_data_sha256"]):
        raise RissError("invalid_release_provenance")
    if not isinstance(queue["researchers"], list) or len(queue["researchers"]) > 10000:
        raise RissError("invalid_queue_records")
    ids: set[str] = set()
    anonymous: set[str] = set()
    clean = []
    for person in queue["researchers"]:
        if not isinstance(person, dict) or set(person) != QUEUE_FIELDS:
            raise RissError("invalid_queue_record")
        entry = {key: _bounded_string(person[key], 500 if key in {"institution_canonical", "institution_query", "institution_unit_id"} else 300 if key == "name" else 200) for key in QUEUE_FIELDS - {"award_year"}}
        if entry["country"] != "KR" or entry["degree_level"] != "phd" or type(person["award_year"]) is not int or not 1900 <= person["award_year"] <= release:
            raise RissError("invalid_domestic_doctorate_query")
        if entry["professor_uid"] in ids or entry["anon_id"] in anonymous:
            raise RissError("duplicate_queue_identity")
        ids.add(entry["professor_uid"])
        anonymous.add(entry["anon_id"])
        entry["award_year"] = person["award_year"]
        clean.append(entry)
    return {**queue, "researchers": clean}


def build_query_url(person: dict[str, Any], api_key: str, *, start: int, page_size: int) -> str:
    # Official stype=id means 국내박사학위논문. It is not a 'typeid' parameter.
    params = {"key": api_key, "version": "1.0", "type": "T", "stype": "id",
              "author": person["name"], "publisher": person["institution_query"],
              "spubdate": str(person["award_year"]), "epubdate": str(person["award_year"]),
              "rsnum": str(start), "rowcount": str(page_size)}
    return ENDPOINT + "?" + urlencode(params)


def _candidate_key(candidate: dict[str, Any]) -> str:
    return candidate["riss_id"] or candidate["source_url"] or "metadata:" + hashlib.sha256(json.dumps(candidate, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def collect_candidates(queue_json: Path, output: Path, *, limit: int = 5, max_pages: int = 2,
                       page_size: int = 20, requester: Callable[[str], bytes] | None = None) -> dict[str, Any]:
    api_key = os.environ.get("RISS_API_KEY", "").strip()
    if not api_key:
        raise RissError("missing_api_key")  # Intentionally before reading queue or touching output paths.
    if len(api_key) > 2048 or any(ord(c) < 33 for c in api_key):
        raise RissError("invalid_api_key_configuration")
    if type(limit) is not int or not 1 <= limit <= 100 or type(max_pages) is not int or not 1 <= max_pages <= 20 or type(page_size) is not int or not 1 <= page_size <= 100:
        raise RissError("invalid_collection_bounds")
    try:
        if queue_json.stat().st_size > MAX_QUEUE_BYTES:
            raise RissError("queue_too_large")
        queue = validate_queue(json.loads(queue_json.read_text(encoding="utf-8")))
    except RissError:
        raise
    except Exception:
        raise RissError("queue_read_failed") from None
    try:
        output = private_output(output)
        audit_path = private_output(output.with_suffix(".audit.json"))
        if output.exists() or audit_path.exists():
            raise RissError("output_exists")
    except RissError:
        raise
    except Exception:
        raise RissError("unsafe_private_output") from None
    request = requester or fetch_xml
    queries = []
    stopped = False
    total_requests = 0
    for person in queue["researchers"][:limit]:
        result = {**person, "status": "not_queried_due_to_prior_error" if stopped else "pending",
                  "request_attempts": 0, "pages_received": 0, "totalcount": None,
                  "truncated": None, "candidates": [], "query": {"version": "1.0", "type": "T", "stype": "id",
                  "author": person["name"], "publisher": person["institution_query"], "spubdate": person["award_year"], "epubdate": person["award_year"]}}
        queries.append(result)
        if stopped:
            continue
        keys: set[str] = set()
        raw_received = 0
        for page in range(max_pages):
            start = 1 + page * page_size
            result["request_attempts"] += 1
            total_requests += 1
            try:
                response = parse_response(request(build_query_url(person, api_key, start=start, page_size=page_size)))
                if api_key in json.dumps(response, ensure_ascii=False):
                    raise RissError("sensitive_response_rejected")
                if response["metadata_count"] > page_size:
                    raise RissError("page_size_mismatch")
                if response["totalcount"] == 0 and response["metadata_count"]:
                    raise RissError("inconsistent_totalcount")
            except Exception as error:
                result["status"] = "incomplete_error"
                result["truncated"] = True
                result["error"] = error.code if isinstance(error, RissError) else "request_failed"
                if isinstance(error, RissError) and error.api_code:
                    result["api_error_code"] = error.api_code
                stopped = True
                break
            result["pages_received"] += 1
            if result["totalcount"] is not None and result["totalcount"] != response["totalcount"]:
                result["totalcount_changed"] = True
            result["totalcount"] = response["totalcount"]
            raw_received += response["metadata_count"]
            for candidate in response["candidates"]:
                key = _candidate_key(candidate)
                if key not in keys:
                    keys.add(key)
                    result["candidates"].append(candidate)
            if raw_received >= response["totalcount"]:
                complete = not result.get("totalcount_changed") and len(result["candidates"]) >= response["totalcount"]
                result["status"] = ("complete_candidates" if result["candidates"] else "complete_no_matching") if complete else "incomplete_truncated"
                result["truncated"] = not complete
                break
            if response["metadata_count"] < page_size:
                # Empty/short pages with a larger total are not evidence of zero matches.
                result["status"] = "incomplete_truncated"
                result["truncated"] = True
                break
        if result["status"] == "pending":
            result["status"] = "incomplete_truncated"
            result["truncated"] = True
    counts = {"queue_researchers": len(queue["researchers"]), "selected_researchers": len(queries),
              "request_attempts": total_requests, "complete_queries": sum(q["status"].startswith("complete_") for q in queries),
              "incomplete_queries": sum(q["status"].startswith("incomplete_") for q in queries),
              "errored_queries": sum(q["status"] == "incomplete_error" for q in queries),
              "not_queried": sum(q["status"] == "not_queried_due_to_prior_error" for q in queries),
              "returned_candidates": sum(len(q["candidates"]) for q in queries), "verified_candidates": 0}
    audit = {"schema_version": 1, "release_year": queue["release_year"], "public_data_sha256": queue["public_data_sha256"],
             "created_at": dt.datetime.now(dt.timezone.utc).isoformat(), "limits": {"researchers": limit, "pages_per_researcher": max_pages, "page_size": page_size},
             "counts": counts, "stopped_on_error": stopped, "raw_response_saved": False, "api_key_saved": False,
             "assertions": {"official_domestic_doctorate_filter": True, "department_returned_by_api": False, "candidate_collection_is_degree_verification": False}}
    payload = {"schema_version": 1, "release_year": queue["release_year"], "public_data_sha256": queue["public_data_sha256"], "source": "RISS thesis OpenAPI", "queries": queries}
    try:
        write_new_jsons([(output, payload), (audit_path, audit)])
    except Exception:
        raise RissError("private_output_failed") from None
    return counts


class SafeArgumentParser(argparse.ArgumentParser):
    def error(self, message):
        self.exit(2, '{"error":"invalid_arguments"}\n')


def main() -> int:
    parser = SafeArgumentParser(description=__doc__)
    parser.add_argument("--queue-json", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--max-pages", type=int, default=2)
    parser.add_argument("--page-size", type=int, default=20)
    args = parser.parse_args()
    try:
        counts = collect_candidates(args.queue_json, args.output, limit=args.limit, max_pages=args.max_pages, page_size=args.page_size)
        print(json.dumps(counts, sort_keys=True))
        return 1 if counts["incomplete_queries"] or counts["not_queried"] else 0
    except RissError as error:
        result = {"error": error.code}
        if error.code == "missing_api_key":
            result.update({"request_attempts": 0, "written_files": 0})
        print(json.dumps(result, sort_keys=True))
    except Exception:
        print('{"error":"collection_failed"}')
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
