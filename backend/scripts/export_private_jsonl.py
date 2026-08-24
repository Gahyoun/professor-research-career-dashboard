#!/usr/bin/env python3
"""Rebuild the three private JSONL snapshots from their SQLite sources."""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable


def connect_read_only(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    return connection


def parse_json(value: str | None) -> list[Any]:
    if not value:
        return []
    parsed = json.loads(value)
    return parsed if isinstance(parsed, list) else []


def write_jsonl(path: Path, records: Iterable[dict[str, Any]]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as stream:
        for record in records:
            stream.write(
                json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n"
            )
    os.replace(temporary, path)


def grouped(connection: sqlite3.Connection, query: str) -> dict[str, list[sqlite3.Row]]:
    rows: dict[str, list[sqlite3.Row]] = defaultdict(list)
    for row in connection.execute(query):
        rows[row["professor_uid"]].append(row)
    return rows


def export_careers(connection: sqlite3.Connection, output: Path) -> None:
    education = grouped(
        connection,
        """SELECT * FROM education
           ORDER BY professor_uid, education_id""",
    )
    career = grouped(
        connection,
        """SELECT * FROM v_professor_career
           ORDER BY professor_uid, start_year, end_year, role_type, institution_label""",
    )
    moves = grouped(
        connection,
        """SELECT * FROM v_professor_moves
           ORDER BY professor_uid, first_seen_term, to_institution_label""",
    )
    flags = grouped(
        connection,
        """SELECT * FROM qc_flags
           WHERE professor_uid IS NOT NULL
           ORDER BY professor_uid, flag_id""",
    )

    def records() -> Iterable[dict[str, Any]]:
        professors = connection.execute(
            """SELECT p.*,
                      COALESCE(i.display_name,p.latest_institution_raw) current_institution
               FROM professors p
               LEFT JOIN institution_units i
                 ON i.unit_id=p.latest_institution_unit_id
               ORDER BY p.professor_uid"""
        )
        for professor in professors:
            uid = professor["professor_uid"]
            degrees = education.get(uid, [])
            bachelor = next(
                (row["institution_raw"] for row in degrees if row["degree_level"] == "bachelor"),
                None,
            )
            phd = next(
                (row["institution_raw"] for row in degrees if row["degree_level"] == "phd"),
                None,
            )
            yield {
                "professor_uid": uid,
                "subject": professor["subject"],
                "name": professor["name"],
                "openalex_id": professor["openalex_id"],
                "orcid": professor["orcid"],
                "latest_term": professor["latest_term"],
                "current_institution": professor["current_institution"],
                "latest_rank": professor["latest_rank"],
                "appointment_year": professor["appointment_year"],
                "phd_year": professor["phd_year"],
                "declared_field": professor["declared_field"],
                "bachelor_institution": bachelor,
                "phd_institution": phd,
                "education": [
                    {
                        "degree_level": row["degree_level"],
                        "institution_raw": row["institution_raw"],
                        "country": row["country"],
                        "award_year": row["award_year"],
                        "inferred_start_year": row["inferred_start_year"],
                        "confidence": row["confidence"],
                    }
                    for row in degrees
                ],
                "career": [
                    {
                        "role_type": row["role_type"],
                        "institution_label": row["institution_label"],
                        "start_year": row["start_year"],
                        "end_year": row["end_year"],
                        "start_term": row["start_term"],
                        "end_term": row["end_term"],
                        "time_precision": row["time_precision"],
                        "evidence_status": row["evidence_status"],
                        "is_concurrent": row["is_concurrent"],
                        "confidence": row["confidence"],
                        "reasoning": row["reasoning"],
                    }
                    for row in career.get(uid, [])
                ],
                "moves_2023_2026": [
                    {
                        "from_institution_label": row["from_institution_label"],
                        "to_institution_label": row["to_institution_label"],
                        "last_seen_term": row["last_seen_term"],
                        "first_seen_term": row["first_seen_term"],
                        "confidence": row["confidence"],
                        "transition_type": row["transition_type"],
                    }
                    for row in moves.get(uid, [])
                ],
                "qc_flags": [
                    {
                        "code": row["flag_code"],
                        "severity": row["severity"],
                        "details": row["details"],
                    }
                    for row in flags.get(uid, [])
                ],
            }

    write_jsonl(output, records())


def export_timeline(connection: sqlite3.Connection, output: Path) -> None:
    affiliations = grouped(
        connection,
        """SELECT * FROM affiliation_periods
           ORDER BY professor_uid, period, affiliation_period_id""",
    )
    candidate_counts = {
        row["professor_uid"]: row["candidate_count"]
        for row in connection.execute(
            """SELECT professor_uid,COUNT(*) candidate_count
               FROM duplicate_drop_candidate GROUP BY professor_uid"""
        )
    }

    def records() -> Iterable[dict[str, Any]]:
        for professor in connection.execute(
            """SELECT professor_uid,name,subject,openalex_id,orcid,phd_year,appointment_year
               FROM professors ORDER BY professor_uid"""
        ):
            uid = professor["professor_uid"]
            periods: list[dict[str, Any]] = []
            for row in affiliations.get(uid, []):
                if not periods or periods[-1]["period"] != row["period"]:
                    periods.append(
                        {
                            "period": row["period"],
                            "year": row["year"],
                            "half": row["half"],
                            "affiliation_count": 0,
                            "affiliations": [],
                        }
                    )
                periods[-1]["affiliations"].append(
                    {
                        "institution": row["institution_name"],
                        "institution_unit_id": row["institution_unit_id"],
                        "nation": row["nation"],
                        "country_code": row["country_code"],
                        "region": row["region"],
                        "city": row["city"],
                        "unit_label": row["unit_label"],
                        "postal_code": row["postal_code"],
                        "campus_cluster_id": row["campus_cluster_id"],
                        "postal_campus_cluster_id": row["postal_campus_cluster_id"],
                        "status": row["status"],
                        "career_stage": row["career_stage"],
                        "faculty_position_no": row["faculty_position_no"],
                        "confidence": row["confidence"],
                        "work_count": row["work_count"],
                        "source_work_ids": parse_json(row["source_work_ids_json"]),
                    }
                )
                periods[-1]["affiliation_count"] += 1
            yield {
                "professor_uid": uid,
                "name": professor["name"],
                "subject": professor["subject"],
                "openalex_id": professor["openalex_id"],
                "orcid": professor["orcid"],
                "phd_year": professor["phd_year"],
                "appointment_year": professor["appointment_year"],
                "periods": periods,
                "duplicate_drop_candidate_count": candidate_counts.get(uid, 0),
            }

    write_jsonl(output, records())


def export_candidates(connection: sqlite3.Connection, output: Path) -> None:
    candidates = grouped(
        connection,
        """SELECT d.*,w.topic_id,w.subfield_id,w.subfield_name,w.field_id,w.domain_id
           FROM duplicate_drop_candidate d
           LEFT JOIN work_authorship_evidence w
             ON w.professor_uid=d.professor_uid AND w.work_id=d.work_id
           ORDER BY d.professor_uid,d.publication_date,d.work_id""",
    )

    def records() -> Iterable[dict[str, Any]]:
        for professor in connection.execute(
            """SELECT professor_uid,name,subject,openalex_id
               FROM professors ORDER BY professor_uid"""
        ):
            uid = professor["professor_uid"]
            rows = candidates.get(uid, [])
            if not rows:
                continue
            yield {
                "professor_uid": uid,
                "name": professor["name"],
                "subject": professor["subject"],
                "openalex_id": professor["openalex_id"],
                "candidate_count": len(rows),
                "candidates": [
                    {
                        "work_id": row["work_id"],
                        "doi": row["doi"],
                        "title": row["title"],
                        "publication_date": row["publication_date"],
                        "period": row["period"],
                        "candidate_score": row["candidate_score"],
                        "severity": row["severity"],
                        "topic": {
                            "id": row["topic_id"],
                            "display_name": row["topic_name"],
                            "subfield_id": row["subfield_id"],
                            "subfield": row["subfield_name"],
                            "field_id": row["field_id"],
                            "field": row["field_name"],
                            "domain_id": row["domain_id"],
                            "domain": row["domain_name"],
                        },
                        "institution_ids": parse_json(row["institution_ids_json"]),
                        "institution_names": parse_json(row["institution_names_json"]),
                        "raw_affiliation_strings": parse_json(
                            row["raw_affiliation_strings_json"]
                        ),
                        "reasons": parse_json(row["reasons_json"]),
                        "source_url": row["source_url"],
                    }
                    for row in rows
                ],
            }

    write_jsonl(output, records())


def update_manifest(
    connection: sqlite3.Connection, database: Path, output_dir: Path
) -> None:
    path = output_dir / "professor_affiliation_qc_manifest.json"
    manifest: dict[str, Any] = {}
    if path.exists():
        manifest = json.loads(path.read_text(encoding="utf-8"))

    table_names = [
        "professors",
        "semester_snapshots",
        "education",
        "work_authorship_evidence",
        "raw_affiliation_units",
        "affiliation_periods",
        "career_positions_v2",
        "duplicate_drop_candidate",
    ]
    manifest["database"] = str(database)
    manifest["integrity_check"] = connection.execute(
        "PRAGMA integrity_check"
    ).fetchone()[0]
    manifest["foreign_key_error_count"] = len(
        connection.execute("PRAGMA foreign_key_check").fetchall()
    )
    manifest["table_counts"] = {
        name: connection.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]
        for name in table_names
    }
    manifest["identity_decision_counts"] = {
        row["identity_decision"]: row["count"]
        for row in connection.execute(
            """SELECT identity_decision,COUNT(*) count
               FROM work_authorship_evidence GROUP BY identity_decision"""
        )
    }
    manifest["candidate_severity_counts"] = {
        row["severity"]: row["count"]
        for row in connection.execute(
            """SELECT severity,COUNT(*) count
               FROM duplicate_drop_candidate GROUP BY severity"""
        )
    }
    manifest["timeline_jsonl_records"] = manifest["table_counts"]["professors"]
    manifest["duplicate_candidate_jsonl_researchers"] = connection.execute(
        "SELECT COUNT(DISTINCT professor_uid) FROM duplicate_drop_candidate"
    ).fetchone()[0]

    hard_gate = {
        "pre_cutoff_keep_works": connection.execute(
            """SELECT COUNT(*)
               FROM work_authorship_evidence w JOIN professors p USING(professor_uid)
               WHERE p.phd_year IS NOT NULL
                 AND w.publication_year < p.phd_year-5
                 AND w.identity_decision='keep'"""
        ).fetchone()[0],
        "pre_cutoff_affiliation_periods": connection.execute(
            """SELECT COUNT(*)
               FROM affiliation_periods a JOIN professors p USING(professor_uid)
               WHERE p.phd_year IS NOT NULL AND a.year < p.phd_year-5"""
        ).fetchone()[0],
        "pre_cutoff_career_positions": connection.execute(
            """SELECT COUNT(*)
               FROM career_positions_v2 v JOIN professors p USING(professor_uid)
               WHERE p.phd_year IS NOT NULL AND v.start_year < p.phd_year-5"""
        ).fetchone()[0],
        "pre_cutoff_career_spells": connection.execute(
            """SELECT COUNT(*)
               FROM career_spells s JOIN professors p USING(professor_uid)
               WHERE p.phd_year IS NOT NULL AND s.start_year < p.phd_year-5"""
        ).fetchone()[0],
    }
    hard_gate["passed"] = all(value == 0 for value in hard_gate.values())
    manifest["pre_phd_minus_5_hard_gate"] = hard_gate
    manifest["passed"] = (
        manifest["integrity_check"] == "ok"
        and manifest["foreign_key_error_count"] == 0
        and hard_gate["passed"]
    )

    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--careers-db", type=Path, required=True)
    parser.add_argument("--timeline-db", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    with connect_read_only(args.careers_db) as careers:
        export_careers(careers, args.output_dir / "professor_careers_2023_2026.jsonl")
    with connect_read_only(args.timeline_db) as timeline:
        export_timeline(
            timeline,
            args.output_dir / "professor_affiliation_timeline_through_2026.jsonl",
        )
        export_candidates(timeline, args.output_dir / "duplicate_drop_candidate.jsonl")
        update_manifest(timeline, args.timeline_db, args.output_dir)


if __name__ == "__main__":
    main()
