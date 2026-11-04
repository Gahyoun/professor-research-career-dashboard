#!/usr/bin/env python3
"""Import accepted alias authorships into a new private KOAD input database.

No network access. Existing evidence and decisions are never overwritten. New
works start as review unless the accepted mapping explicitly verifies that work.
Run KOAD classify and apply-copy after importing, before any public release.
"""
import argparse
from contextlib import closing
from datetime import date, datetime, timezone
import hashlib
import gzip
import json
import os
from pathlib import Path
import re
import sqlite3
from urllib.parse import quote


def compact(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def read_audit_json(payload):
    """Read lossless gzip audit BLOBs, including earlier plain JSON audit rows."""
    if isinstance(payload, bytes):
        payload = gzip.decompress(payload).decode('utf-8')
    return json.loads(payload)


def compressed_audit_text(value):
    return gzip.compress(value.encode('utf-8'), compresslevel=3, mtime=0)


def short(value):
    return str(value).rstrip('/').rsplit('/', 1)[-1] if value is not None else None


def entity_id(value, kind):
    value = str(value or '').strip().rstrip('/')
    pattern = rf'(?:https?://(?:api\.)?openalex\.org/(?:(?:authors|works|institutions)/)?)?({kind}\d+)'
    match = re.fullmatch(pattern, value, re.I)
    if not match:
        raise ValueError(f'Invalid OpenAlex {kind} identifier')
    return match.group(1).upper()


def optional_id(value, kind):
    return entity_id(value, kind) if value else None


def fingerprint(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def read_only(path):
    return sqlite3.connect(f'file:{quote(str(Path(path).resolve()))}?mode=ro&immutable=1', uri=True)


def load_acceptances(path, source):
    records = json.loads(Path(path).read_text(encoding='utf-8'))
    if not isinstance(records, list):
        raise ValueError('Accepted aliases must be a JSON list')
    people = {row[0] for row in source.execute('SELECT professor_uid FROM professors')}
    accepted = {}
    primaries = {}
    for record in records:
        if not isinstance(record, dict) or record.get('professor_uid') not in people:
            raise ValueError('Accepted mapping refers to an unknown researcher')
        if not (record.get('source') or record.get('evidence')):
            raise ValueError('Accepted alias mapping requires verification source or evidence')
        ids = record.get('openalex_ids')
        if not isinstance(ids, list) or not ids:
            raise ValueError('Accepted mapping needs a nonempty openalex_ids list')
        verified = record.get('verified_work_ids', [])
        if not isinstance(verified, list):
            raise ValueError('verified_work_ids must be a list')
        verified = {entity_id(work, 'W') for work in verified}
        uid = record['professor_uid']
        normalized_ids = {entity_id(value, 'A') for value in ids}
        primary = optional_id(record.get('primary_id'), 'A')
        if primary:
            if primary not in normalized_ids:
                raise ValueError('Primary assignment must be included in the accepted IDs')
            if uid in primaries and primaries[uid] != primary:
                raise ValueError('Conflicting primary assignments for one researcher')
            previous = source.execute('SELECT openalex_id FROM professors WHERE professor_uid=?', (uid,)).fetchone()[0]
            if previous and entity_id(previous, 'A') != primary:
                raise ValueError('Cannot replace an existing researcher primary ID')
            primaries[uid] = primary
        for aid in normalized_ids:
            entry = accepted.setdefault((uid, aid), {'verified': set(), 'records': []})
            entry['verified'].update(verified)
            entry['records'].append(record)
            if primary == aid:
                entry['primary_id'] = primary
    return accepted


def department_labels(raw):
    """Extract literal formal units only; never derive a department from topics."""
    if not raw:
        return [None]
    labels = re.findall(
        r'(?i)\b(?:department|dept\.?|school|division)\s+of\s+[^,;\n]+'
        r'|[^,;\n]*(?:학과|학부|전공)', raw,
    )
    return sorted({label.strip() for label in labels if label.strip()}) or [None]


def institution_anchors(connection, uid):
    def canonical(units):
        result = set()
        for unit in units:
            if not unit:
                continue
            row = connection.execute(
                'SELECT openalex_institution_id FROM institution_units WHERE unit_id=?', (unit,)
            ).fetchone()
            value = row[0] if row and row[0] else unit
            try:
                result.add(entity_id(value, 'I'))
            except ValueError:
                pass
        return result
    person = connection.execute(
        'SELECT latest_institution_unit_id,orcid FROM professors WHERE professor_uid=?', (uid,)
    ).fetchone()
    phd = canonical(row[0] for row in connection.execute(
        "SELECT institution_unit_id FROM education WHERE professor_uid=? AND degree_level='phd'", (uid,)
    ))
    faculty = canonical(row[0] for row in connection.execute(
        "SELECT institution_unit_id FROM career_positions_v2 WHERE professor_uid=? AND position_type='faculty'", (uid,)
    ))
    return phd, canonical([person[0]]), faculty, person[1]


def add_institution(connection, institution):
    iid = optional_id(institution.get('id'), 'I')
    if not iid:
        return None
    if connection.execute('SELECT 1 FROM institution_units WHERE unit_id=?', (iid,)).fetchone():
        return iid
    # Missing institution metadata stays unresolved; its original IDs are in the audit.
    if not institution.get('display_name'):
        return None
    geo = institution.get('geo') or {}
    connection.execute('''
        INSERT INTO institution_units(unit_id,openalex_institution_id,ror,display_name,country_code,
            institution_type,lineage_json,campus_cluster_id,postal_code,city,canonical_source)
        VALUES(?,?,?,?,?,?,?,NULL,?,?,?)
    ''', (iid, iid, institution.get('ror'), institution['display_name'], institution.get('country_code'),
          institution.get('type'), compact(institution.get('lineage') or []),
          geo.get('postal_code'), geo.get('city'), 'openalex_alias_authorship'))
    return iid


def affiliation_rows(authorship, institutions):
    """Use explicit raw-string/ID bindings; retain unbound facts separately."""
    rows, bound_raw, bound_ids = [], set(), set()
    for affiliation in authorship.get('affiliations') or []:
        raw = affiliation.get('raw_affiliation_string')
        ids = [entity_id(value, 'I') for value in affiliation.get('institution_ids') or []]
        for iid in ids or [None]:
            rows.append((raw, iid))
            if iid:
                bound_ids.add(iid)
        if raw is not None:
            bound_raw.add(raw)
    for raw in authorship.get('raw_affiliation_strings') or []:
        if raw not in bound_raw:
            rows.append((raw, None))
    for iid in institutions:
        if iid not in bound_ids:
            rows.append((None, iid))
    return list(dict.fromkeys(rows))


def create_audit_tables(connection):
    connection.executescript('''
        BEGIN IMMEDIATE;
        CREATE TABLE IF NOT EXISTS alias_mapping_evidence(
            evidence_id INTEGER PRIMARY KEY,professor_uid TEXT NOT NULL,openalex_id TEXT NOT NULL,
            verified_work_ids_json TEXT NOT NULL,source_json TEXT NOT NULL,evidence_json TEXT NOT NULL,
            record_json TEXT NOT NULL,record_sha256 TEXT NOT NULL,recorded_at TEXT NOT NULL,
            UNIQUE(professor_uid,openalex_id,record_sha256)
        );
        CREATE TABLE IF NOT EXISTS alias_work_import_audit(
            professor_uid TEXT NOT NULL,target_author_id TEXT NOT NULL,work_id TEXT NOT NULL,
            payload_sha256 TEXT NOT NULL,verified_work INTEGER NOT NULL,source_identity_decision TEXT NOT NULL,
            inserted_work INTEGER NOT NULL,evidence_ids_json TEXT NOT NULL,full_work_json BLOB NOT NULL,
            target_authorship_json TEXT NOT NULL,input_record_json BLOB NOT NULL,anchor_flags_json TEXT NOT NULL,recorded_at TEXT NOT NULL,
            PRIMARY KEY(professor_uid,target_author_id,work_id,payload_sha256)
        );
        CREATE TABLE IF NOT EXISTS alias_import_runs(
            imported_at TEXT NOT NULL,source_database_sha256 TEXT NOT NULL,
            accepted_aliases_sha256 TEXT NOT NULL,works_jsonl_sha256 TEXT NOT NULL,counts_json TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS alias_primary_assignment_audit(
            professor_uid TEXT PRIMARY KEY,previous_openalex_id TEXT,new_openalex_id TEXT NOT NULL,
            evidence_ids_json TEXT NOT NULL,recorded_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS wrong_link_quarantine_audit(
            professor_uid TEXT NOT NULL,wrong_author_id TEXT NOT NULL,table_name TEXT NOT NULL,
            original_row_json TEXT NOT NULL,rejection_json TEXT NOT NULL,recorded_at TEXT NOT NULL,
            UNIQUE(professor_uid,wrong_author_id,table_name,original_row_json)
        );
    ''')


def quarantine_wrong_links(connection, path, recorded_at):
    """Archive proven wrong primary evidence in the copy before classification."""
    if path is None:
        return 0
    records = json.loads(Path(path).read_text())
    if not isinstance(records, list):
        raise ValueError('Rejected links must be a JSON list')
    count = 0
    for record in records:
        uid = record.get('professor_uid')
        wrong = entity_id(record.get('wrong_id'), 'A')
        if not (record.get('source') or record.get('evidence') or record.get('source_urls')) or not record.get('reason'):
            raise ValueError('Wrong-link quarantine requires explicit evidence and reason')
        if connection.execute('SELECT 1 FROM wrong_link_quarantine_audit WHERE professor_uid=? AND wrong_author_id=?', (uid, wrong)).fetchone():
            continue
        cursor = connection.execute('SELECT * FROM professors WHERE professor_uid=?', (uid,))
        row = cursor.fetchone()
        if row is None:
            raise ValueError('Wrong-link quarantine refers to an unknown researcher')
        person = dict(zip((d[0] for d in cursor.description), row))
        if optional_id(person.get('openalex_id'), 'A') != wrong:
            raise ValueError('Wrong-link quarantine must match the existing primary ID')
        def archive(table, where, parameters):
            cursor = connection.execute(f'SELECT * FROM {table} WHERE {where}', parameters)
            columns = [d[0] for d in cursor.description]
            rows = cursor.fetchall()
            connection.executemany('INSERT OR IGNORE INTO wrong_link_quarantine_audit VALUES(?,?,?,?,?,?)',
                [(uid, wrong, table, compact(dict(zip(columns, row))), compact(record), recorded_at) for row in rows])
            return len(rows)
        archive('professors', 'professor_uid=?', (uid,))
        condition = 'professor_uid=? AND work_id IN (SELECT work_id FROM work_authorship_evidence WHERE professor_uid=? AND openalex_id=?)'
        parameters = (uid, uid, wrong)
        for table in ('raw_affiliation_units', 'duplicate_drop_candidate'):
            if connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone():
                archive(table, condition, parameters)
                connection.execute(f'DELETE FROM {table} WHERE {condition}', parameters)
        count += archive('work_authorship_evidence', 'professor_uid=? AND openalex_id=?', (uid, wrong))
        connection.execute('DELETE FROM work_authorship_evidence WHERE professor_uid=? AND openalex_id=?', (uid, wrong))
        archive('openalex_author_profiles', 'professor_uid=? AND openalex_id=?', (uid, wrong))
        connection.execute('DELETE FROM openalex_author_profiles WHERE professor_uid=? AND openalex_id=?', (uid, wrong))
        connection.execute('UPDATE professors SET openalex_id=NULL WHERE professor_uid=?', (uid,))
    return count


def augment(source_db, accepted_aliases, works_jsonl, output_db, rejected_links=None):
    source_db, accepted_aliases, works_jsonl, output_db = map(Path, (source_db, accepted_aliases, works_jsonl, output_db))
    if output_db.resolve() == source_db.resolve():
        raise ValueError('Output must differ from the source database')
    if output_db.exists() or output_db.is_symlink():
        raise FileExistsError('Output database already exists; refusing to overwrite')
    imported_at = datetime.now(timezone.utc).isoformat()
    counts = {'input_records': 0, 'new_works': 0, 'existing_works_preserved': 0,
              'new_affiliations': 0, 'new_author_profiles': 0, 'audit_records': 0, 'verified_new_works': 0,
              'new_primary_assignments': 0, 'wrong_link_works_quarantined': 0,
              'existing_authorship_contexts_preserved': 0}
    connection = None
    created = False
    with closing(read_only(source_db)) as source:
        output_db.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        descriptor = os.open(output_db, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        os.close(descriptor)
        created = True
        try:
            connection = sqlite3.connect(output_db)
            source.backup(connection)
            connection.execute('PRAGMA foreign_keys=ON')
            create_audit_tables(connection)
            counts['wrong_link_works_quarantined'] = quarantine_wrong_links(connection, rejected_links, imported_at)
            acceptances = load_acceptances(accepted_aliases, connection)
            for (uid, aid), acceptance in acceptances.items():
                acceptance['evidence_ids'] = []
                for record in acceptance['records']:
                    serialized = compact(record)
                    digest = hashlib.sha256(serialized.encode()).hexdigest()
                    connection.execute('''
                        INSERT OR IGNORE INTO alias_mapping_evidence(professor_uid,openalex_id,verified_work_ids_json,
                            source_json,evidence_json,record_json,record_sha256,recorded_at) VALUES(?,?,?,?,?,?,?,?)
                    ''', (uid, aid, compact(sorted(entity_id(value, 'W') for value in record.get('verified_work_ids', []))), compact(record.get('source')),
                          compact(record.get('evidence')), serialized, digest, imported_at))
                    evidence_id = connection.execute('''SELECT evidence_id FROM alias_mapping_evidence
                        WHERE professor_uid=? AND openalex_id=? AND record_sha256=?''', (uid, aid, digest)).fetchone()[0]
                    acceptance['evidence_ids'].append(evidence_id)
                if acceptance.get('primary_id'):
                    previous = connection.execute('SELECT openalex_id FROM professors WHERE professor_uid=?', (uid,)).fetchone()[0]
                    if not previous:
                        connection.execute('UPDATE professors SET openalex_id=? WHERE professor_uid=? AND openalex_id IS NULL', (aid, uid))
                        if connection.execute('SELECT changes()').fetchone()[0]:
                            connection.execute('INSERT INTO alias_primary_assignment_audit VALUES(?,?,?,?,?)',
                                (uid, previous, aid, compact(acceptance['evidence_ids']), imported_at))
                            counts['new_primary_assignments'] += 1
            anchors = {}
            open_works = gzip.open if works_jsonl.suffix == '.gz' else open
            with open_works(works_jsonl, mode='rt', encoding='utf-8') as stream:
                for line in stream:
                    if not line.strip():
                        continue
                    counts['input_records'] += 1
                    record = json.loads(line)
                    uid = record.get('professor_uid')
                    aid = entity_id(record.get('target_author_id'), 'A')
                    acceptance = acceptances.get((uid, aid))
                    if acceptance is None:
                        raise ValueError('Work record is not covered by an accepted researcher/alias mapping')
                    work = record.get('work')
                    if not isinstance(work, dict):
                        raise ValueError('Work record requires a full OpenAlex work object')
                    wid = entity_id(work.get('id'), 'W')
                    matches = [auth for auth in work.get('authorships') or []
                               if optional_id((auth.get('author') or {}).get('id'), 'A') == aid]
                    if len(matches) != 1:
                        raise ValueError('Expected exactly one target authorship matching the accepted alias')
                    authorship = matches[0]
                    digest = hashlib.sha256(compact(record).encode()).hexdigest()
                    if connection.execute('''SELECT 1 FROM alias_work_import_audit
                        WHERE professor_uid=? AND target_author_id=? AND work_id=? AND payload_sha256=?''',
                        (uid, aid, wid, digest)).fetchone():
                        continue
                    verified = wid in acceptance['verified']
                    author = authorship['author']
                    institutions = {}
                    for institution in authorship.get('institutions') or []:
                        iid = optional_id(institution.get('id'), 'I')
                        if iid:
                            institutions[iid] = institution
                            add_institution(connection, institution)
                    raw_rows = affiliation_rows(authorship, institutions)
                    actual_ids = set(institutions) | {iid for _, iid in raw_rows if iid}
                    if uid not in anchors:
                        anchors[uid] = institution_anchors(connection, uid)
                    phd, current, faculty, person_orcid = anchors[uid]
                    observed_orcid = authorship.get('raw_orcid') or author.get('orcid')
                    norm_orcid = lambda value: str(value or '').rstrip('/').rsplit('/', 1)[-1].casefold()
                    flags = {'phd_institution': bool(actual_ids & phd), 'current_institution': bool(actual_ids & current),
                             'faculty_chain': bool(actual_ids & faculty),
                             'orcid_exact': bool(person_orcid and observed_orcid and norm_orcid(person_orcid) == norm_orcid(observed_orcid))}
                    publication_date = work.get('publication_date')
                    publication_year = work.get('publication_year')
                    if publication_year is not None and (type(publication_year) is not int or not 1 <= publication_year <= 9999):
                        raise ValueError('Publication year must be an integer or null')
                    period = None
                    if publication_date:
                        published = date.fromisoformat(publication_date)
                        period = f'{published.year}-H{1 if published.month <= 6 else 2}'
                        if publication_year not in (None, published.year):
                            raise ValueError('Publication year and date disagree')
                        publication_year = published.year
                    topic = work.get('primary_topic') or {}
                    subfield, field, domain = (topic.get(name) or {} for name in ('subfield', 'field', 'domain'))
                    existing = connection.execute('''SELECT identity_decision,period,openalex_id FROM work_authorship_evidence
                        WHERE professor_uid=? AND work_id=?''', (uid, wid)).fetchone()
                    decision = existing[0] if existing else ('keep' if verified else 'review')
                    if existing:
                        counts['existing_works_preserved'] += 1
                        period = existing[1]
                        counts['existing_authorship_contexts_preserved'] += int(existing[2] != aid)
                    else:
                        coauthors = sorted({entity_id(auth['author']['id'], 'A') for auth in work.get('authorships') or []
                                            if (auth.get('author') or {}).get('id') and entity_id(auth['author']['id'], 'A') != aid})
                        values = (uid, aid, wid, work.get('doi'), work.get('title') or work.get('display_name'),
                                  publication_date, publication_year, period, work.get('type'),
                                  authorship.get('raw_author_name'), authorship.get('raw_orcid'),
                                  short(topic.get('id')), topic.get('display_name'), short(subfield.get('id')), subfield.get('display_name'),
                                  short(field.get('id')), field.get('display_name'), short(domain.get('id')), domain.get('display_name'),
                                  None, decision, 0, None,
                                  compact(['verified_publication_anchor' if verified else 'accepted_alias_candidate_requires_koad']),
                                  compact(flags), compact(coauthors), f'https://openalex.org/{wid}')
                        connection.execute('INSERT INTO work_authorship_evidence VALUES(' + ','.join('?' for _ in values) + ')', values)
                        counts['new_works'] += 1
                        counts['verified_new_works'] += int(verified)
                    # Another alias may have different authorship context for an
                    # already reviewed work. Retain it in the audit, without
                    # merging its affiliations into the selected source author.
                    source_raw_rows = raw_rows if not existing or existing[2] == aid else ()
                    for raw, iid in source_raw_rows:
                        unit = connection.execute('''SELECT unit_id,display_name,country_code,city
                            FROM institution_units WHERE unit_id=?''', (iid,)).fetchone() if iid else None
                        for label in department_labels(raw):
                            unit_id = unit[0] if unit else None
                            if connection.execute('''SELECT 1 FROM raw_affiliation_units WHERE professor_uid=? AND work_id=?
                                AND raw_affiliation_string IS ? AND institution_unit_id IS ? AND unit_label IS ?''',
                                (uid, wid, raw, unit_id, label)).fetchone():
                                continue
                            connection.execute('''INSERT INTO raw_affiliation_units(professor_uid,work_id,period,
                                raw_affiliation_string,unit_label,postal_code,institution_unit_id,institution_name,
                                country_code,nation,region,city,campus_cluster_id,postal_campus_cluster_id,identity_decision)
                                VALUES(?,?,?,?,?,NULL,?,?,?,NULL,NULL,?,NULL,NULL,?)''',
                                (uid, wid, period, raw, label, unit_id, unit[1] if unit else None,
                                 unit[2] if unit else None, unit[3] if unit else None, decision))
                            counts['new_affiliations'] += 1
                    if not connection.execute('SELECT 1 FROM openalex_author_profiles WHERE professor_uid=? AND openalex_id=?', (uid, aid)).fetchone():
                        connection.execute('INSERT INTO openalex_author_profiles VALUES(?,?,?,?,?,?,?,?)',
                            (uid, aid, author.get('display_name'), author.get('orcid'), None, '[]', None, imported_at[:10]))
                        counts['new_author_profiles'] += 1
                    connection.execute('INSERT INTO alias_work_import_audit VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',
                        (uid, aid, wid, digest, int(verified), decision, int(existing is None),
                         compact(sorted(set(acceptance['evidence_ids']))), compressed_audit_text(compact(work)), compact(authorship),
                         compressed_audit_text(line.rstrip('\r\n')), compact(flags), imported_at))
                    counts['audit_records'] += 1
            connection.execute('INSERT INTO alias_import_runs VALUES(?,?,?,?,?)',
                (imported_at, fingerprint(source_db), fingerprint(accepted_aliases), fingerprint(works_jsonl), compact(counts)))
            if connection.execute('PRAGMA integrity_check').fetchone()[0] != 'ok' or connection.execute('PRAGMA foreign_key_check').fetchone():
                raise ValueError('Augmented database failed integrity checks')
            connection.commit()
            connection.close()
            connection = None
        except BaseException:
            if connection is not None:
                connection.rollback()
                connection.close()
            if created:
                for path in (output_db, *(Path(str(output_db) + suffix) for suffix in ('-wal', '-shm', '-journal'))):
                    path.unlink(missing_ok=True)
            raise
    return counts


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-db', type=Path, required=True)
    parser.add_argument('--accepted-aliases', type=Path, required=True)
    parser.add_argument('--works-jsonl', type=Path, required=True, help='Full work packets as JSONL or JSONL.gz')
    parser.add_argument('--output-db', type=Path, required=True)
    parser.add_argument('--rejected-links', type=Path, help='Evidence-backed wrong primary links to archive only in the copy')
    args = parser.parse_args()
    print(json.dumps(augment(args.source_db, args.accepted_aliases, args.works_jsonl, args.output_db, args.rejected_links), sort_keys=True))


if __name__ == '__main__':
    main()
