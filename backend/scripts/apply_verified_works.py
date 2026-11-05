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

verified.json:
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


def load_verified(path):
    spec = json.loads(Path(path).read_text(encoding='utf-8'))
    uid = spec.get('professor_uid')
    if not uid or not isinstance(spec.get('works'), list) or not spec['works']:
        raise ValueError('verified file needs professor_uid and a nonempty works list')
    if not spec.get('source'):
        raise ValueError('verified file needs a source (where the works were checked)')
    works = []
    for w in spec['works']:
        wid = entity_id(w['work_id'], 'W')
        aid = entity_id(w['author_id'], 'A') if w.get('author_id') else None
        works.append({'work_id': wid, 'author_id': aid, 'note': w.get('note')})
    if len({w['work_id'] for w in works}) != len(works):
        raise ValueError('duplicate work_id in verified file')
    return uid, spec['source'], works


def open_lines(path):
    return gzip.open(path, 'rt', encoding='utf-8') if str(path).endswith('.gz') else open(path, encoding='utf-8')


def fetch_packets(uid, need, out_path, key, base='https://api.openalex.org'):
    """Full OpenAlex work objects for (author_id, work_id) pairs, checked to hold exactly one
    authorship of that author. Written to out_path (gzip JSONL)."""
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
            fh.write(json.dumps({'professor_uid': uid, 'target_author_id': w['author_id'], 'work': work}, ensure_ascii=False) + '\n')
    return out_path


def apply(source_db, decisions_db, verified, works_jsonl, out_dir, api_key=None):
    source_db, decisions_db, out_dir = Path(source_db), Path(decisions_db), Path(out_dir)
    uid, source, works = load_verified(verified)
    out_dir.mkdir(mode=0o700, parents=True, exist_ok=False)
    out_source, out_decisions = out_dir / 'web.sqlite', out_dir / 'identity_decisions.sqlite'
    now = datetime.now(timezone.utc).isoformat()
    report = {'professor_uid': uid, 'verified_works': len(works), 'no_author_id': [], 'imported': {},
              'evidence_set_keep': 0, 'affiliations_set_keep': 0, 'decisions_set_true_paper': 0,
              'decisions_inserted': 0, 'already_in_place': 0, 'missing_after_import': []}

    with closing(read_only(source_db)) as src:
        if not src.execute('SELECT 1 FROM professors WHERE professor_uid=?', (uid,)).fetchone():
            raise ValueError(f'unknown researcher {uid}')
        present = {r[0] for r in src.execute('SELECT work_id FROM work_authorship_evidence WHERE professor_uid=?', (uid,))}

    need = [w for w in works if w['work_id'] not in present]
    report['no_author_id'] = [w['work_id'] for w in need if not w['author_id']]
    need = [w for w in need if w['author_id']]

    if need and not works_jsonl:
        if not api_key:
            raise ValueError('works not in the source need --works-jsonl or OPENALEX_API_KEY to fetch them')
        works_jsonl = fetch_packets(uid, need, out_dir / 'works.jsonl.gz', api_key)
    if need:
        packets = {}
        with open_lines(works_jsonl) as fh:
            for line in fh:
                if line.strip():
                    rec = json.loads(line)
                    if rec.get('professor_uid') == uid:
                        packets[(entity_id(rec['target_author_id'], 'A'), entity_id(rec['work']['id'], 'W'))] = rec
        missing = [w['work_id'] for w in need if (w['author_id'], w['work_id']) not in packets]
        if missing:
            raise ValueError(f'works.jsonl lacks packets for {missing}')
        by_author = {}
        for w in need:
            by_author.setdefault(w['author_id'], []).append(w['work_id'])
        with tempfile.TemporaryDirectory() as tmp:
            aliases = Path(tmp) / 'accepted.json'
            aliases.write_text(json.dumps([{'professor_uid': uid, 'openalex_ids': [aid], 'verified_work_ids': wids,
                                            'source': source, 'evidence': {'method': 'work-by-work verification',
                                                                           'work_ids': wids}}
                                           for aid, wids in sorted(by_author.items())]), encoding='utf-8')
            subset = Path(tmp) / 'works.jsonl'
            with open(subset, 'w', encoding='utf-8') as fh:
                for w in need:
                    fh.write(json.dumps(packets[(w['author_id'], w['work_id'])], ensure_ascii=False) + '\n')
            report['imported'] = augment(source_db, aliases, subset, out_source)
    else:
        with closing(read_only(source_db)) as src, closing(sqlite3.connect(out_source)) as dst:
            src.backup(dst)
        os.chmod(out_source, 0o600)

    shutil.copyfile(decisions_db, out_decisions)
    os.chmod(out_decisions, 0o600)
    src_json = json.dumps(source, ensure_ascii=False, sort_keys=True)
    with closing(sqlite3.connect(out_source)) as con, closing(sqlite3.connect(out_decisions)) as dec:
        con.execute(AUDIT)
        dec.execute(AUDIT)
        dec_cols = [r[1] for r in dec.execute('PRAGMA table_info(work_decision)')]
        required = [r[1] for r in dec.execute('PRAGMA table_info(work_decision)') if r[3] and r[4] is None and not r[5]]
        for w in works:
            wid = w['work_id']
            row = con.execute('SELECT identity_decision FROM work_authorship_evidence WHERE professor_uid=? AND work_id=?',
                              (uid, wid)).fetchone()
            if row is None:
                if w['author_id']:
                    report['missing_after_import'].append(wid)
                continue
            changed = False
            if row[0] != 'keep':
                con.execute("UPDATE work_authorship_evidence SET identity_decision='keep' WHERE professor_uid=? AND work_id=?", (uid, wid))
                con.execute('INSERT INTO manual_work_verification_audit VALUES(?,?,?,?,?,?,?)',
                            (uid, wid, 'work_authorship_evidence.identity_decision', row[0], 'keep', src_json, now))
                report['evidence_set_keep'] += 1
                changed = True
            n = con.execute("UPDATE raw_affiliation_units SET identity_decision='keep' WHERE professor_uid=? AND work_id=? "
                            "AND identity_decision!='keep'", (uid, wid)).rowcount
            report['affiliations_set_keep'] += n
            old = dec.execute('SELECT decision FROM work_decision WHERE professor_uid=? AND work_id=?', (uid, wid)).fetchall()
            if old and all(o[0] == 'true_paper' for o in old):
                report['already_in_place'] += int(not changed)
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
            dec.execute('INSERT INTO manual_work_verification_audit VALUES(?,?,?,?,?,?,?)',
                        (uid, wid, 'work_decision.decision', ','.join(sorted({o[0] for o in old})) or None,
                         'true_paper', src_json, now))
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
