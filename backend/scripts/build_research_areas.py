#!/usr/bin/env python3
"""Per-researcher OpenAlex research areas (domain → field → subfield → topic) for researcher search.

Reads the private career DB (``work_authorship_evidence`` carries each work's OpenAlex primary
topic and its subfield/field/domain) and writes anonymous aggregate counts only:

  {"schema": ..., "domains": [name], "fields": [[name, domain_idx]], "subfields": [[name, field_idx]], "topics": [[name, subfield_idx]],
   "researchers": {"P-…": {"n": works, "f": [[idx, n]], "s": [[idx, n]], "t": [[idx, n]]}}}

Works follow the public release's identity rules: source decision ``keep``, every KOAD
``namesake_paper`` excluded, publication_year ≤ release year and ≥ phd_year − 5 when the
PhD year is known. All author positions count (the area describes the researcher's work,
not lead authorship). No titles, DOIs, work IDs, raw professor IDs or OpenAlex IDs are written.
"""
import argparse
import base64
import hashlib
import hmac
import json
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path

SCHEMA = 'kstem-research-areas/2'
TOP = {'f': 3, 's': 6, 't': 8}


def anon_id(salt, uid):
    digest = hmac.new(salt, uid.encode(), hashlib.sha256).digest()
    return 'P-' + base64.b32encode(digest).decode().rstrip('=')[:10]


def retained_rows(con, release_year):
    """(professor_uid, domain, field, subfield, topic) for works kept under the public identity rules."""
    return con.execute('''
      SELECT w.professor_uid, w.domain_name, w.field_name, w.subfield_name, w.topic_name
      FROM work_authorship_evidence w JOIN professors p USING(professor_uid)
      WHERE w.identity_decision='keep' AND w.publication_year<=?
        AND (p.phd_year IS NULL OR w.publication_year>=p.phd_year-5)
        AND w.subfield_name IS NOT NULL AND w.subfield_name<>''
        AND NOT EXISTS (SELECT 1 FROM koad.work_decision kd
          WHERE kd.professor_uid=w.professor_uid AND kd.work_id=w.work_id AND kd.decision='namesake_paper')
    ''', (int(release_year),))


def aggregate(rows, public_id, top=TOP):
    """rows: iterable of (uid, domain, field, subfield, topic); public_id(uid) → anon ID or None (not released)."""
    per = defaultdict(lambda: {'n': 0, 'f': Counter(), 's': Counter(), 't': Counter()})
    parent_f, parent_s, parent_t = {}, {}, {}
    for uid, domain, field, subfield, topic in rows:
        pid = public_id(uid)
        if not pid:
            continue
        field = (field or '').strip() or 'Unclassified'
        parent_f.setdefault(field, (domain or '').strip() or 'Unclassified')
        subfield = subfield.strip()
        rec = per[pid]
        rec['n'] += 1
        rec['f'][field] += 1
        rec['s'][subfield] += 1
        parent_s.setdefault(subfield, field)
        if topic and topic.strip():
            rec['t'][topic.strip()] += 1
            parent_t.setdefault(topic.strip(), subfield)

    kept = {pid: {k: (rec[k].most_common(top[k]) if k != 'n' else rec['n']) for k in ('n', 'f', 's', 't')} for pid, rec in per.items()}
    fields = sorted({f for rec in kept.values() for f, _ in rec['f']} | {parent_s[s] for rec in kept.values() for s, _ in rec['s']})
    subfields = sorted({s for rec in kept.values() for s, _ in rec['s']} | {parent_t[t] for rec in kept.values() for t, _ in rec['t']})
    topics = sorted({t for rec in kept.values() for t, _ in rec['t']})
    domains = sorted({parent_f[f] for f in fields})
    di = {name: i for i, name in enumerate(domains)}
    fi = {name: i for i, name in enumerate(fields)}
    si = {name: i for i, name in enumerate(subfields)}
    ti = {name: i for i, name in enumerate(topics)}
    fields_out = [[f, di[parent_f[f]]] for f in fields]
    subfields_out = [[s, fi[parent_s[s]]] for s in subfields]
    topics_out = [[t, si[parent_t[t]]] for t in topics]
    researchers = {pid: {'n': rec['n'],
                         'f': [[fi[k], v] for k, v in rec['f']],
                         's': [[si[k], v] for k, v in rec['s']],
                         't': [[ti[k], v] for k, v in rec['t']]} for pid, rec in sorted(kept.items())}
    return {'domains': domains, 'fields': fields_out, 'subfields': subfields_out, 'topics': topics_out, 'researchers': researchers}


def build(source_db, salt, public_ids, release_year):
    uri = f'file:{Path(source_db).resolve()}?mode=ro&immutable=1'
    con = sqlite3.connect(uri, uri=True)
    decisions = Path(source_db).parent / 'identity_decisions.sqlite'
    if not decisions.exists():
        raise SystemExit(f'KOAD decision database is required: {decisions}')
    con.execute('ATTACH DATABASE ? AS koad', (f'file:{decisions.resolve()}?mode=ro&immutable=1',))
    cache = {}

    def public_id(uid):
        if uid not in cache:
            pid = anon_id(salt, uid)
            cache[uid] = pid if pid in public_ids else None
        return cache[uid]

    out = aggregate(retained_rows(con, release_year), public_id)
    con.close()
    return {'schema': SCHEMA, 'release_year': int(release_year),
            'source': 'OpenAlex primary topic of each retained work (topic → subfield → field → domain)',
            'method': {'works': 'identity_decision=keep; KOAD namesake_paper excluded; phd_year-5 ≤ year ≤ release year; all author positions',
                       'top': TOP},
            **out}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--source-db', type=Path, required=True)
    parser.add_argument('--anon-salt', type=Path, required=True)
    parser.add_argument('--dashboard', type=Path, default=Path('public/data/dashboard.json'))
    parser.add_argument('--output', type=Path, default=Path('public/data/research_areas.json'))
    args = parser.parse_args()
    dashboard = json.loads(args.dashboard.read_text())
    ids = {p['id'] for p in dashboard['professors']}
    result = build(args.source_db, args.anon_salt.read_bytes(), ids, dashboard['meta']['release_year'])
    args.output.write_text(json.dumps(result, ensure_ascii=False, separators=(',', ':')))
    print(json.dumps({'researchers': len(result['researchers']), 'of': len(ids), 'fields': len(result['fields']),
                      'subfields': len(result['subfields']), 'topics': len(result['topics']),
                      'bytes': args.output.stat().st_size}))
