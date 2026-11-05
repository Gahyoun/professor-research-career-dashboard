#!/usr/bin/env python3
"""Add evidence-backed pre-faculty career segments to the PUBLISHED release for a few
researchers, when the private source database is not at hand (companion of
patch_release_verified_works.py).

  OPENALEX_API_KEY=… NAMES_PASSWORD=… python3 backend/scripts/patch_release_career.py --spec segments.json [--dry-run]
  … patch_release_career.py --auto verified.json --public-ids anon_map.json [--dry-run]
      (derive segments for those researchers: an institution absent from the career with >= 2
       published works after the PhD and before the first faculty period)

segments.json: [{"public_id": "P-…", "stage": "postdoc", "institution": "<public display name>",
                 "openalex_institution": "I…",
                 "evidence": [{"work_id": "W…", "author_id": "A…"}, …],
                 "metadata": {"institution_canonical", "country", "department",
                              "department_inferred", "department_evidence"}}]

Rules (as the full build's postdoc recovery: "medium-confidence postdoc rows require strictly
retained same-institution work evidence inside the recorded interval"):
  * every evidence work must be published already for that researcher (in its encrypted
    title file) and its authorship of author_id must carry openalex_institution;
  * the interval is the half-years of the first and last evidence publication dates;
  * it must start after the PhD year and end before the first faculty segment starts, and
    must not overlap another segment of the researcher.
Updates dashboard.json (both copies), the public SQLite (career_segments, yearly stages),
constellation_metadata.json career units (segment indexes shifted, manifest hashes and counts
updated). Topic eras follow the career: rerun
  patch_release_verified_works.py --refresh-topics
afterwards for the same researchers.
"""
import argparse
import hashlib
import json
import os
import sqlite3
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'backend' / 'scripts'))
from patch_release_verified_works import OpenAlex, read_titles, short, stage_for_year, vault_key  # noqa: E402

EVIDENCE_BASIS = '박사 후 첫 교수 임용 전 논문 소속; 공식 직함 미확인'


def half(d):
    return f"{d[:4]}-H{1 if int(d[5:7]) <= 6 else 2}"


def build_segment(spec, works, published_dois, prof):
    periods = []
    for ev in spec['evidence']:
        w = works.get(ev['work_id'])
        if w is None:
            raise ValueError(f"{ev['work_id']}: not in OpenAlex")
        if (w.get('doi') or '').lower() not in published_dois:
            raise ValueError(f"{ev['work_id']}: not a published work of {spec['public_id']}")
        mine = [a for a in w.get('authorships') or [] if short((a.get('author') or {}).get('id')) == ev['author_id']]
        if len(mine) != 1 or spec['openalex_institution'] not in {short(i.get('id')) for i in mine[0].get('institutions') or []}:
            raise ValueError(f"{ev['work_id']}: authorship lacks {spec['openalex_institution']}")
        periods.append(half(w['publication_date']))
    start, end = min(periods), max(periods)
    seg = {'stage': spec['stage'], 'position_no': None, 'institution': spec['institution'],
           'start_period': start, 'end_period': end, 'start_year': int(start[:4]), 'end_year': int(end[:4]),
           'confidence': 'medium', 'is_institution_successor': False, 'evidence_basis': EVIDENCE_BASIS,
           'is_estimated': False}
    if prof.get('phd_year') and seg['start_year'] <= prof['phd_year']:
        raise ValueError(f"{spec['public_id']}: segment starts before the PhD year ends")
    faculty = [c['start_period'] for c in prof['career'] if c['stage'] == 'faculty' and c.get('start_period')]
    if faculty and seg['end_period'] >= min(faculty):
        raise ValueError(f"{spec['public_id']}: segment reaches the first faculty period {min(faculty)}")
    for c in prof['career']:
        if c['stage'] != 'doctoral' and c.get('start_period') and not (seg['end_period'] < c['start_period'] or c['end_period'] < seg['start_period']):
            raise ValueError(f"{spec['public_id']}: overlaps {c['institution']} {c['start_period']}–{c['end_period']}")
    return seg


def derive_specs(prof, pid, works, author_ids, metadata_all, min_works=2):
    """Auto mode: pre-faculty segments from published works whose authorship (one of author_ids)
    lists an institution absent from the career, after the PhD year and before the first faculty
    period. >= min_works works per institution; overlapping candidates keep the larger one."""
    from career_consistency import norm_institution
    career = {norm_institution(c['institution']): c['institution'] for c in prof['career']}
    phd = prof.get('phd_year') or 0
    faculty = [c['start_period'] for c in prof['career'] if c['stage'] == 'faculty' and c.get('start_period')]
    first = min(faculty) if faculty else '9999-H2'
    groups = {}
    for w in works:
        if not w.get('publication_date') or not (phd < w['publication_year']) or half(w['publication_date']) >= first:
            continue
        for a in w.get('authorships') or []:
            if short((a.get('author') or {}).get('id')) not in author_ids:
                continue
            for inst in a.get('institutions') or []:
                key = norm_institution(inst.get('display_name'))
                if not key:
                    continue
                g = groups.setdefault(short(inst['id']), {'name': career.get(key, inst['display_name']), 'country': inst.get('country_code'),
                                                          'in_career': key in career, 'evidence': {}})
                g['evidence'][short(w['id'])] = short(a['author']['id'])
    cands = []
    for iid, g in groups.items():
        if len(g['evidence']) < min_works or g['in_career']:
            continue
        canon = [u.get('institution_canonical') for r in metadata_all.values() for u in r['career_units'] if u['institution'] == g['name']]
        canonical = max(set(canon), key=canon.count) if canon else g['name']
        cands.append({'public_id': pid, 'stage': 'postdoc', 'institution': g['name'], 'openalex_institution': iid,
                      'evidence': [{'work_id': k, 'author_id': v} for k, v in sorted(g['evidence'].items())],
                      'metadata': {'institution_canonical': canonical, 'country': g['country'], 'department': None,
                                   'department_inferred': False, 'department_evidence': 'no_formal_department_evidence'}})
    return sorted(cands, key=lambda c: -len(c['evidence']))


def order(career):
    return sorted(career, key=lambda c: (c.get('start_year') or 0, c.get('start_period') or '', c.get('institution') or ''))


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--spec', help='explicit segments (see above)')
    p.add_argument('--auto', help='verified-works file: derive segments for its researchers from their published works')
    p.add_argument('--public-ids', help='with --auto: JSON {professor_uid: P-…}')
    p.add_argument('--year', default='2026')
    p.add_argument('--dry-run', action='store_true')
    a = p.parse_args()
    key, password = os.environ.get('OPENALEX_API_KEY'), os.environ.get('NAMES_PASSWORD')
    if not key or not password:
        sys.exit('OPENALEX_API_KEY and NAMES_PASSWORD are required (environment only)')
    specs = json.loads(Path(a.spec).read_text()) if a.spec else []
    release = ROOT / 'data' / 'releases' / a.year
    dashboard = json.loads((release / 'dashboard.json').read_text())
    profs = {x['id']: x for x in dashboard['professors']}
    meta_path = ROOT / 'public' / 'data' / 'constellation_metadata.json'
    metadata = json.loads(meta_path.read_text())
    topics_dir = ROOT / 'public' / 'data' / 'topics'
    aes, aad = vault_key(topics_dir, password)
    oa = OpenAlex(key)
    skipped = []
    if a.auto:
        verified = json.loads(Path(a.auto).read_text())
        verified = verified if isinstance(verified, list) else [verified]
        public_ids = json.loads(Path(a.public_ids).read_text())
        from patch_release_namesakes import resolve
        for spec in verified:
            pid = public_ids[spec['professor_uid']]
            resolved, _ = resolve(oa, read_titles(topics_dir, aes, aad, pid))
            ids = {w['author_id'] for w in spec['works'] if w.get('author_id')}
            mode = __import__('collections').Counter(short((x.get('author') or {}).get('id')) for _, w in resolved
                                                     for x in w.get('authorships') or [] if (x.get('author') or {}).get('id'))
            if mode:
                ids.add(mode.most_common(1)[0][0])
            specs += derive_specs(profs[pid], pid, [w for _, w in resolved], ids, metadata)
    works = oa.works([ev['work_id'] for s in specs for ev in s['evidence']])
    added, touched = [], set()
    for s in specs:
        prof = profs[s['public_id']]
        dois = {(r.get('doi') or '').lower() for r in read_titles(topics_dir, aes, aad, s['public_id'])}
        try:
            seg = build_segment(s, works, dois, prof)
        except ValueError as e:     # auto candidates that overlap or reach faculty are skipped, not forced
            if not a.auto:
                raise
            skipped.append(str(e))
            continue
        old = list(prof['career'])
        prof['career'] = order(old + [seg])
        # constellation units follow the new segment order; existing units keep their content
        units = {(u['institution'], u['start_year'], u['end_year'], u['segment_index']): u for u in metadata[s['public_id']]['career_units']}
        new_units = []
        for i, c in enumerate(prof['career']):
            if c is seg:
                new_units.append({'segment_index': i, 'institution': c['institution'], 'start_year': c['start_year'],
                                  'end_year': c['end_year'], **s['metadata'],
                                  'department_supporting_affiliations': len(s['evidence']) if s['metadata'].get('department') else 0})
            else:
                j = old.index(c)
                u = dict(units[(c['institution'], c['start_year'], c['end_year'], j)])
                u['segment_index'] = i
                new_units.append(u)
        metadata[s['public_id']]['career_units'] = new_units
        for y in prof.get('yearly') or []:
            y['stage'] = stage_for_year(prof['career'], y['year'], prof['phd_year'], prof['appointment_year'])
        added.append({'public_id': s['public_id'], **{k: seg[k] for k in ('stage', 'institution', 'start_period', 'end_period')},
                      'evidence_works': len(s['evidence'])})
        touched.add(s['public_id'])
    print(json.dumps({'added': added, 'skipped': skipped}, ensure_ascii=False, indent=1))
    if a.dry_run or not added:
        return

    patch = {'date': str(date.today()), 'segments_added': len(added), 'researchers': len(touched),
             'rule': 'pre-faculty postdoc segments from retained same-institution work evidence (medium confidence)'}
    dashboard['meta']['manual_career_patch'] = patch
    text = json.dumps(dashboard, ensure_ascii=False, separators=(',', ':'))
    for path in (release / 'dashboard.json', ROOT / 'public' / 'data' / 'dashboard.json'):
        path.write_text(text)
    meta_text = json.dumps(metadata, ensure_ascii=False, separators=(',', ':'))
    meta_path.write_text(meta_text)

    db = release / f'professor_dashboard_{a.year}.sqlite'
    con = sqlite3.connect(db)
    for pid in touched:
        x = profs[pid]
        con.execute('DELETE FROM career_segments WHERE professor_id=?', (pid,))
        for c in x['career']:
            con.execute('''INSERT INTO career_segments
              (professor_id,stage,position_no,institution,start_period,end_period,start_year,end_year,confidence,evidence_basis,is_estimated,is_institution_successor)
              VALUES (?,?,?,?,?,?,?,?,?,?,?,?)''', (pid, c['stage'], c['position_no'], c['institution'], c['start_period'],
                                                     c['end_period'], c['start_year'], c['end_year'], c['confidence'],
                                                     c.get('evidence_basis'), int(c.get('is_estimated', False)),
                                                     int(c['is_institution_successor'])))
        con.executemany('UPDATE yearly_lead_output SET career_stage=? WHERE professor_id=? AND year=?',
                        [(y['stage'], pid, y['year']) for y in x.get('yearly') or []])
    con.execute("INSERT OR REPLACE INTO release_metadata VALUES ('manual_career_patch', ?)", (json.dumps(patch, ensure_ascii=False),))
    con.commit()
    con.execute('VACUUM')
    integrity = con.execute('PRAGMA integrity_check').fetchone()[0]
    con.close()
    manifest = json.loads((release / 'manifest.json').read_text())
    manifest.update({'manual_career_patch': patch, 'public_db_bytes': db.stat().st_size, 'sqlite_integrity': integrity})
    mtext = json.dumps(manifest, ensure_ascii=False, indent=2)
    for path in (release / 'manifest.json', ROOT / 'public' / 'data' / 'manifest.json'):
        path.write_text(mtext)
    (ROOT / 'public' / 'downloads' / db.name).write_bytes(db.read_bytes())

    cm_path = ROOT / 'public' / 'data' / 'constellation_metadata.manifest.json'
    cm = json.loads(cm_path.read_text())
    counts = cm.get('counts', {})
    applied = [s for s in specs if any(x['public_id'] == s['public_id'] and x['institution'] == s['institution'] for x in added)]
    for s in applied:
        m = s['metadata']
        counts['career_segments'] = counts.get('career_segments', 0) + 1
        counts['career_country_known'] = counts.get('career_country_known', 0) + int(bool(m.get('country')))
        counts['career_domestic'] = counts.get('career_domestic', 0) + int(m.get('country') == 'KR')
        counts['career_department_inferred'] = counts.get('career_department_inferred', 0) + int(bool(m.get('department_inferred')))
        counts['career_domestic_department_inferred'] = counts.get('career_domestic_department_inferred', 0) + int(
            m.get('country') == 'KR' and bool(m.get('department_inferred')))
    cm['public_data_sha256'] = hashlib.sha256((ROOT / 'public' / 'data' / 'dashboard.json').read_bytes()).hexdigest()
    cm['metadata_sha256'] = hashlib.sha256(meta_text.encode()).hexdigest()
    notes = cm.get('rebound_after_patch') or []
    notes = [notes] if isinstance(notes, str) else notes
    cm['rebound_after_patch'] = notes + [f"{patch['date']} manual_career_patch: {len(added)} evidence-backed "
                                         "pre-faculty segments with their career units"]
    cm_path.write_text(json.dumps(cm, ensure_ascii=False, indent=2) + '\n')
    print(f'patched: {len(added)} career segments')


if __name__ == '__main__':
    main()
