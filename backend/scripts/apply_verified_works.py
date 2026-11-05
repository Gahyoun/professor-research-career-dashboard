#!/usr/bin/env python3
"""Add a researcher's externally verified works (e.g. checked one by one against a Google
Scholar profile) to COPIES of the private source and KOAD decision databases.

Why work by work: an OpenAlex author ID often mixes people. Example from 2026-11-05: the ID
added for one physicist held 163 works, 8 of them hers; the rest were emergency-medicine
papers by a namesake. Accepting the ID would import the namesake; leaving it out loses her
papers. This tool accepts only the listed (researcher, work) pairs.

  python3 backend/scripts/apply_verified_works.py \
      --source-db PRIVATE/web.sqlite --decisions-db PRIVATE/identity_decisions.sqlite \
      --verified verified.json [--works-jsonl works.jsonl.gz] --out-dir PRIVATE/verified_YYYYMMDD

Steps, all on copies (inputs are opened read-only and never changed):
  1. works not yet in work_authorship_evidence are imported with augment_openalex_evidence.py,
     each as a verified anchor of the author ID on its authorship (decision 'keep');
  2. for every listed pair, evidence and raw-affiliation rows are set to 'keep', and the KOAD
     work_decision to 'true_paper';
  3. every change is written to manual_work_verification_audit (previous value, new value,
     source, time) in the output database it changed.
Works whose authorship has no OpenAlex author ID cannot be imported this way; they are
reported, not guessed.

verified.json (one spec, or a JSON list of specs for several researchers):
  {"professor_uid": "prof:physics:phy0000",
   "source": {"kind": "google_scholar_profile", "url": "...", "checked": "YYYY-MM-DD"},
   "works": [{"work_id": "W…", "author_id": "A…" | null, "note": "..."}]}
works.jsonl(.gz): {"professor_uid", "target_author_id", "work": <full OpenAlex work>} per line.
  Optional: without --works-jsonl the packets of works that need importing are fetched from
  OpenAlex (key from $OPENALEX_API_KEY, never printed) and saved to OUT/works.jsonl.gz.

Then build the release from the outputs:
  KOAD_DECISIONS_DB=OUT/identity_decisions.sqlite backend/scripts/update_release.sh 2026 OUT/web.sqlite
Rerun this tool after any KOAD reclassification (it is idempotent); a reclassification may
otherwise overwrite the manual decisions.
"""
import argparse
from contextlib import closing
from datetime import datetime, timezone
import gzip
import json
import os
from pathlib import Path
import shutil
import sqlite3
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
from augment_openalex_evidence import augment, entity_id, read_only  # noqa: E402

AUDIT = '''CREATE TABLE IF NOT EXISTS manual_work_verification_audit(
  professor_uid TEXT NOT NULL, work_id TEXT NOT NULL, target TEXT NOT NULL,
  previous_value TEXT, new_value TEXT NOT NULL, source_json TEXT NOT NULL, recorded_at TEXT NOT NULL)'''


def read_json(path):
    path = Path(path)
    raw = gzip.open(path, 'rt', encoding='utf-8').read() if path.suffix == '.gz' else path.read_text(encoding='utf-8')
    return json.loads(raw)


def load_rejected(path):
    """Optional per spec: "rejected_works": [{"work_id", "note"}] — works a person confirmed to be a
    namesake's; their KOAD decision becomes namesake_paper (audited)."""
    data = read_json(path)
    specs = data if isinstance(data, list) else [data]
    return [{'uid': s['professor_uid'], 'work_id': entity_id(w['work_id'], 'W'), 'source': s.get('source'), 'note': w.get('note')}
            for s in specs for w in s.get('rejected_works') or []]


def load_verified(path):
    """One researcher spec ({professor_uid, source, works}) or a list of them -> flat items
    [{uid, work_id, author_id, source}]. A spec may hold only rejected_works."""
    data = read_json(path)
    specs = data if isinstance(data, list) else [data]
    items, seen = [], set()
    for spec in specs:
        uid = spec.get('professor_uid')
        if not uid or not isinstance(spec.get('works', []), list) or not (spec.get('works') or spec.get('rejected_works')):
            raise ValueError('each verified spec needs professor_uid and works or rejected_works')
        if not spec.get('source'):
            raise ValueError(f'{uid}: a source (where the works were checked) is required')
        for w in spec.get('works') or []:
            wid = entity_id(w['work_id'], 'W')
            if (uid, wid) in seen:
                raise ValueError(f'duplicate work {wid} for {uid}')
            seen.add((uid, wid))
            items.append({'uid': uid, 'work_id': wid, 'author_id': entity_id(w['author_id'], 'A') if w.get('author_id') else None,
                          'source': spec['source'], 'note': w.get('note')})
    return items


def open_lines(path):
    return gzip.open(path, 'rt', encoding='utf-8') if str(path).endswith('.gz') else open(path, encoding='utf-8')


def fetch_packets(need, out_path, key, base='https://api.openalex.org'):
    """Full OpenAlex work objects for items [{uid, author_id, work_id}], each checked to hold
    exactly one authorship of that author. Written to out_path (gzip JSONL)."""
    import time
    import urllib.parse
    import urllib.request
    with gzip.open(out_path, 'wt', encoding='utf-8') as fh:
        for w in need:
            url = f"{base}/works/{w['work_id']}?" + urllib.parse.urlencode({'api_key': key})
            for attempt in range(6):
                try:
                    with urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent': 'professor-career-dashboard/1'}),
                                                timeout=60) as r:
                        work = json.loads(r.read())
                    break
                except Exception:
                    if attempt == 5:
                        raise RuntimeError(f"OpenAlex fetch failed for {w['work_id']}")
                    time.sleep(2 ** attempt)
            hits = [a for a in work.get('authorships') or []
                    if entity_id(((a.get('author') or {}).get('id') or 'A0'), 'A') == w['author_id']]
            if len(hits) != 1:
                raise ValueError(f"{w['work_id']}: {len(hits)} authorships of {w['author_id']} (expected 1)")
            fh.write(json.dumps({'professor_uid': w['uid'], 'target_author_id': w['author_id'], 'work': work}, ensure_ascii=False) + '\n')
    return out_path


def apply(source_db, decisions_db, verified, works_jsonl, out_dir, api_key=None):
    source_db, decisions_db, out_dir = Path(source_db), Path(decisions_db), Path(out_dir)
    items = load_verified(verified)
    out_dir.mkdir(mode=0o700, parents=True, exist_ok=False)
    out_source, out_decisions = out_dir / 'web.sqlite', out_dir / 'identity_decisions.sqlite'
    now = datetime.now(timezone.utc).isoformat()
    report = {'researchers': len({i['uid'] for i in items}), 'verified_works': len(items), 'no_author_id': [],
              'imported': {}, 'evidence_set_keep': 0, 'affiliations_set_keep': 0, 'decisions_set_true_paper': 0,
              'decisions_inserted': 0, 'already_in_place': 0, 'missing_after_import': [], 'per_researcher': {}}

    with closing(read_only(source_db)) as src:
        known = {r[0] for r in src.execute('SELECT professor_uid FROM professors')}
        unknown = sorted({i['uid'] for i in items} - known)
        if unknown:
            raise ValueError(f'unknown researchers {unknown}')
        present = {(r[0], r[1]) for r in src.execute('SELECT professor_uid, work_id FROM work_authorship_evidence')}

    need = [i for i in items if (i['uid'], i['work_id']) not in present]
    report['no_author_id'] = [f"{i['uid']} {i['work_id']}" for i in need if not i['author_id']]
    need = [i for i in need if i['author_id']]

    if need and not works_jsonl:
        if not api_key:
            raise ValueError('works not in the source need --works-jsonl or OPENALEX_API_KEY to fetch them')
        works_jsonl = fetch_packets(need, out_dir / 'works.jsonl.gz', api_key)
    if need:
        packets = {}
        with open_lines(works_jsonl) as fh:
            for line in fh:
                if line.strip():
                    rec = json.loads(line)
                    packets[(rec.get('professor_uid'), entity_id(rec['target_author_id'], 'A'),
                             entity_id(rec['work']['id'], 'W'))] = rec
        missing = [i['work_id'] for i in need if (i['uid'], i['author_id'], i['work_id']) not in packets]
        if missing:
            raise ValueError(f'works.jsonl lacks packets for {missing}')
        groups = {}
        for i in need:
            groups.setdefault((i['uid'], i['author_id']), []).append(i)
        with tempfile.TemporaryDirectory() as tmp:
            aliases = Path(tmp) / 'accepted.json'
            aliases.write_text(json.dumps([{'professor_uid': uid, 'openalex_ids': [aid],
                                            'verified_work_ids': [i['work_id'] for i in group], 'source': group[0]['source'],
                                            'evidence': {'method': 'work-by-work verification',
                                                         'work_ids': [i['work_id'] for i in group]}}
                                           for (uid, aid), group in sorted(groups.items())]), encoding='utf-8')
            subset = Path(tmp) / 'works.jsonl'
            with open(subset, 'w', encoding='utf-8') as fh:
                for i in need:
                    fh.write(json.dumps(packets[(i['uid'], i['author_id'], i['work_id'])], ensure_ascii=False) + '\n')
            report['imported'] = augment(source_db, aliases, subset, out_source)
    else:
        with closing(read_only(source_db)) as src, closing(sqlite3.connect(out_source)) as dst:
            src.backup(dst)
        os.chmod(out_source, 0o600)

    shutil.copyfile(decisions_db, out_decisions)
    os.chmod(out_decisions, 0o600)
    with closing(sqlite3.connect(out_source)) as con, closing(sqlite3.connect(out_decisions)) as dec:
        con.execute(AUDIT)
        dec.execute(AUDIT)
        required = [r[1] for r in dec.execute('PRAGMA table_info(work_decision)') if r[3] and r[4] is None and not r[5]]
        for i in items:
            uid, wid = i['uid'], i['work_id']
            src_json = json.dumps(i['source'], ensure_ascii=False, sort_keys=True)
            per = report['per_researcher'].setdefault(uid, {'listed': 0, 'changed': 0})
            per['listed'] += 1
            row = con.execute('SELECT identity_decision FROM work_authorship_evidence WHERE professor_uid=? AND work_id=?',
                              (uid, wid)).fetchone()
            if row is None:
                if i['author_id']:
                    report['missing_after_import'].append(f'{uid} {wid}')
                continue
            changed = False
            if row[0] != 'keep':
                con.execute("UPDATE work_authorship_evidence SET identity_decision='keep' WHERE professor_uid=? AND work_id=?", (uid, wid))
                con.execute('INSERT INTO manual_work_verification_audit VALUES(?,?,?,?,?,?,?)',
                            (uid, wid, 'work_authorship_evidence.identity_decision', row[0], 'keep', src_json, now))
                report['evidence_set_keep'] += 1
                changed = True
            report['affiliations_set_keep'] += con.execute(
                "UPDATE raw_affiliation_units SET identity_decision='keep' WHERE professor_uid=? AND work_id=? "
                "AND identity_decision!='keep'", (uid, wid)).rowcount
            old = dec.execute('SELECT decision FROM work_decision WHERE professor_uid=? AND work_id=?', (uid, wid)).fetchall()
            if old and all(o[0] == 'true_paper' for o in old):
                report['already_in_place'] += int(not changed)
                per['changed'] += int(changed)
                continue
            if old:
                dec.execute("UPDATE work_decision SET decision='true_paper' WHERE professor_uid=? AND work_id=?", (uid, wid))
                report['decisions_set_true_paper'] += 1
            else:
                extra = [c for c in required if c not in ('professor_uid', 'work_id', 'decision')]
                if extra:
                    raise ValueError(f'work_decision has required columns {extra}; insert for {wid} needs KOAD itself')
                dec.execute('INSERT INTO work_decision(professor_uid,work_id,decision) VALUES(?,?,?)', (uid, wid, 'true_paper'))
                report['decisions_inserted'] += 1
            per['changed'] += 1
            dec.execute('INSERT INTO manual_work_verification_audit VALUES(?,?,?,?,?,?,?)',
                        (uid, wid, 'work_decision.decision', ','.join(sorted({o[0] for o in old})) or None,
                         'true_paper', src_json, now))
        report['decisions_set_namesake'] = 0
        for r in load_rejected(verified):
            if (r['uid'], r['work_id']) in {(i['uid'], i['work_id']) for i in items}:
                raise ValueError(f"{r['work_id']} is both verified and rejected for {r['uid']}")
            old = dec.execute('SELECT decision FROM work_decision WHERE professor_uid=? AND work_id=?', (r['uid'], r['work_id'])).fetchall()
            if old and all(o[0] == 'namesake_paper' for o in old):
                continue
            if old:
                dec.execute("UPDATE work_decision SET decision='namesake_paper' WHERE professor_uid=? AND work_id=?", (r['uid'], r['work_id']))
            elif con.execute('SELECT 1 FROM work_authorship_evidence WHERE professor_uid=? AND work_id=?', (r['uid'], r['work_id'])).fetchone():
                dec.execute('INSERT INTO work_decision(professor_uid,work_id,decision) VALUES(?,?,?)', (r['uid'], r['work_id'], 'namesake_paper'))
            else:
                continue
            dec.execute('INSERT INTO manual_work_verification_audit VALUES(?,?,?,?,?,?,?)',
                        (r['uid'], r['work_id'], 'work_decision.decision', ','.join(sorted({o[0] for o in old})) or None,
                         'namesake_paper', json.dumps(r['source'] or {}, ensure_ascii=False, sort_keys=True), now))
            report['decisions_set_namesake'] += 1
        con.commit()
        dec.commit()
    return report


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--source-db', required=True)
    p.add_argument('--decisions-db', required=True)
    p.add_argument('--verified', required=True)
    p.add_argument('--works-jsonl', help='full work packets; fetched from OpenAlex when omitted')
    p.add_argument('--out-dir', required=True, help='new directory; refuses to reuse an existing one')
    a = p.parse_args()
    report = apply(a.source_db, a.decisions_db, a.verified, a.works_jsonl, a.out_dir, os.environ.get('OPENALEX_API_KEY'))
    print(json.dumps(report, ensure_ascii=False, indent=1))


if __name__ == '__main__':
    main()
