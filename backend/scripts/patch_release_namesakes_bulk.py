#!/usr/bin/env python3
"""Apply the career-consistency namesake rule to EVERY researcher of the published release,
from a cache of the published papers' OpenAlex records (no re-clustering).

  NAMES_PASSWORD=… OPENALEX_API_KEY=… python3 backend/scripts/patch_release_namesakes_bulk.py \
      --cache DIR [--rule career|conflict --inst-meta institutions.json] [--dry-run]

--rule conflict applies career_conflict() instead of classify(); institutions.json maps every
OpenAlex institution ID on the cached authorships to {'type', 'lineage'} (OpenAlex institutions).

DIR holds works.jsonl.gz (OpenAlex works of the published DOIs) and papers.jsonl
({pid, i, year, topic, doi, title} per published topic paper, i = row in the title file).
Per researcher: papers resolved by DOI (title-checked); the researcher's authorship is the
author ID on most of them; classify() as the private build does. A dropped paper leaves the
topic map (its row in the index and the encrypted title file; topic sizes and birth years
recounted, emptied topics removed), the lead output when it was a first/corresponding journal
paper (build_release.py's rule) and the research areas. Topic keywords, vectors and the
merge/diverge block are kept as published (recomputing them needs the reference lists).
"""
import argparse
import gzip
import json
import os
import re
import sqlite3
import sys
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'backend' / 'scripts'))
from career_consistency import career_conflict, classify  # noqa: E402
from patch_release_verified_works import (ALLOWED, MAX_YEAR, OpenAlex, add_areas, add_lead_works,  # noqa: E402
                                          read_titles, rebind_constellation, short, vault_key, write_titles)

nt = lambda t: re.sub(r'[^a-z0-9]', '', (t or '').lower())


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--cache', required=True)
    p.add_argument('--year', default='2026')
    p.add_argument('--dry-run', action='store_true')
    p.add_argument('--rule', choices=('career', 'conflict'), default='career',
                   help='career: classify() (career consistency); conflict: career_conflict() (a different '
                        'university or hospital while the career places the researcher elsewhere)')
    p.add_argument('--inst-meta', help="with --rule conflict: JSON {I…: {'type', 'lineage'}} of OpenAlex institutions")
    a = p.parse_args()
    if a.rule == 'conflict' and not a.inst_meta:
        p.error('--rule conflict needs --inst-meta')
    inst_meta = json.loads(Path(a.inst_meta).read_text()) if a.inst_meta else {}
    cache = Path(a.cache)
    release = ROOT / 'data' / 'releases' / a.year
    topics_dir = ROOT / 'public' / 'data' / 'topics'
    dashboard = json.loads((release / 'dashboard.json').read_text())
    profs = {x['id']: x for x in dashboard['professors']}
    index = json.loads((topics_dir / 'index.json').read_text())
    areas = json.loads((ROOT / 'public' / 'data' / 'research_areas.json').read_text())
    aes, aad = vault_key(topics_dir, os.environ['NAMES_PASSWORD'])
    by_doi = defaultdict(list)
    for line in gzip.open(cache / 'works.jsonl.gz', 'rt'):
        w = json.loads(line)
        by_doi[(w.get('doi') or '').lower()].append(w)
    papers = defaultdict(list)
    for line in open(cache / 'papers.jsonl'):
        x = json.loads(line)
        papers[x['pid']].append(x)

    plan, reasons = {}, Counter()
    for pid, ps in papers.items():
        res = []
        for x in ps:
            c = by_doi.get(x['doi'], [])
            w = max(c, key=lambda w: (nt(w.get('title')) == nt(x['title']), w.get('publication_year') == x['year']), default=None)
            if w is not None and nt(w.get('title')) == nt(x['title']):
                res.append((x, w))
        ids = Counter(short((au.get('author') or {}).get('id')) for _, w in res for au in w['authorships'] if (au.get('author') or {}).get('id'))
        if not ids:
            continue
        target = ids.most_common(1)[0][0]
        works, rows = [], {}
        for x, w in res:
            me = [au for au in w['authorships'] if short((au.get('author') or {}).get('id')) == target]
            if len(me) != 1:
                continue
            pt = w.get('primary_topic') or {}
            wid = short(w['id'])
            rows[wid] = (x, w, me[0])
            works.append({'id': wid, 'year': w.get('publication_year'),
                          'institutions': [i['display_name'] for i in me[0]['institutions']],
                          'institution_ids': [short(i.get('id')) for i in me[0]['institutions']],
                          'coauthors': [short((au.get('author') or {}).get('id')) for au in w['authorships']
                                        if au is not me[0] and (au.get('author') or {}).get('id')],
                          'field': (pt.get('field') or {}).get('display_name'), 'subfield': (pt.get('subfield') or {}).get('display_name'),
                          'domain': (pt.get('domain') or {}).get('display_name')})
        if a.rule == 'conflict':
            drops = career_conflict(works, profs[pid]['career'], profs[pid]['subject'], inst_meta)
        else:
            drops = classify(works, [c['institution'] for c in profs[pid]['career']], profs[pid]['subject'])
        if drops:
            plan[pid] = {wid: (rows[wid], why) for wid, why in drops.items()}
            reasons.update(drops.values())
    total = sum(len(v) for v in plan.values())
    print(json.dumps({'researchers': len(plan), 'papers': total, 'reasons': dict(reasons)}, indent=1))

    entries = {r['id']: r for r in index['researchers']}
    skipped, roles_all, lead_removed = [], [], 0
    for pid, drops in plan.items():
        entry = entries[pid]
        titles = read_titles(topics_dir, aes, aad, pid)
        cols = entry['paper_cols']
        if len(titles) != len(cols['year']) or any(t['year'] != y or t['topic'] != tp for t, y, tp in zip(titles, cols['year'], cols['topic'])):
            skipped.append(pid)
            continue
        drop_rows = {x['i'] for (x, _, _), _ in drops.values()}
        keep = [i for i in range(len(titles)) if i not in drop_rows]
        entry['paper_cols'] = {k: [v[i] for i in keep] for k, v in cols.items()}
        new_titles = [titles[i] for i in keep]
        sizes = Counter(entry['paper_cols']['topic'])
        births = {}
        for y, tp in zip(entry['paper_cols']['year'], entry['paper_cols']['topic']):
            births[tp] = min(births.get(tp, y), y)
        gone = {t['id'] for t in entry['topics'] if not sizes.get(t['id'])}
        entry['topics'] = [dict(t, size=sizes[t['id']], birth_year=births[t['id']],
                                parent=(None if t.get('parent') and t['parent'].get('from') in gone else t.get('parent')))
                           for t in entry['topics'] if t['id'] not in gone]
        entry['counts'] = dict(entry.get('counts') or {}, kept_works=len(keep))
        prof = profs[pid]
        roles = []
        for (x, w, me), _ in drops.values():
            src = (w.get('primary_location') or {}).get('source') or {}
            y = w.get('publication_year')
            if (me.get('author_position') == 'first' or me.get('is_corresponding')) and w.get('type') in ALLOWED \
                    and src.get('type') == 'journal' and y and y <= MAX_YEAR and not (prof.get('phd_year') and y < prof['phd_year'] - 5):
                roles.append({'pid': pid, 'year': y, 'author_position': me.get('author_position'), 'is_corresponding': me.get('is_corresponding'),
                              'source': src, 'cited_by_count': w.get('cited_by_count'), 'source_id': src.get('id')})
        roles_all += roles
        if not a.dry_run:
            write_titles(topics_dir, aes, aad, pid, new_titles)
        add_areas(areas, pid, [w for (_, w, _), _ in drops.values()], sign=-1)
    oa = OpenAlex(os.environ['OPENALEX_API_KEY'])
    srcs = oa.sources([r['source_id'] for r in roles_all])
    by_pid = defaultdict(list)
    for r in roles_all:
        v = ((srcs.get(r['source_id']) or {}).get('summary_stats') or {}).get('2yr_mean_citedness')
        r['impact'] = float(v) if v is not None else None
        by_pid[r['pid']].append(r)
    for pid, roles in by_pid.items():
        prof = profs[pid]
        counted = Counter(y['year'] for y in prof.get('yearly') or [] for _ in range(y['total']))
        usable = []
        for r in sorted(roles, key=lambda r: r['year']):     # never remove more than a year holds
            if counted[r['year']] > 0:
                counted[r['year']] -= 1
                usable.append(r)
        add_lead_works(prof, usable, a.year, sign=-1)
        lead_removed += len(usable)
    print(json.dumps({'skipped_misaligned': skipped, 'lead_works_removed': lead_removed}, indent=1))
    if a.dry_run:
        return

    patch = {'date': str(date.today()), 'researchers': len(plan) - len(skipped),
             'papers_removed': total - sum(len(plan[p]) for p in skipped), 'lead_works_removed': lead_removed,
             'rule': 'career-consistency namesake rule v2 (career_consistency.py): outside the subject home domains, '
                     'fewer than two coauthors shared with career-anchored works, and a field (one shared) or subfield '
                     '(none shared) absent from those works'}
    key = 'manual_namesake_patch_bulk'
    if a.rule == 'conflict':
        key = 'manual_career_conflict_patch_bulk'
        patch['rule'] = ('career-conflict rule (career_consistency.career_conflict): during a doctoral or faculty segment '
                         '(more than a year from any boundary) the authorship names only other universities or hospitals '
                         '(not in the lineage of the career institutions) and shares no coauthor with career-anchored works, '
                         'or one while the subfield is absent from them')
    dashboard['meta'][key] = patch
    dashboard['meta']['lead_work_count'] = sum(x['lead_work_count'] for x in dashboard['professors'])
    text = json.dumps(dashboard, ensure_ascii=False, separators=(',', ':'))
    for path in (release / 'dashboard.json', ROOT / 'public' / 'data' / 'dashboard.json'):
        path.write_text(text)
    index.setdefault('method', {})[key.replace('manual_', '')] = (f"{patch['date']}: {patch['papers_removed']} papers of "
                                                                f"{patch['researchers']} researchers removed by the "
                                                                f"{'career-conflict' if a.rule == 'conflict' else 'career-consistency'} rule; "
                                                                "topic keywords and vectors kept")
    (topics_dir / 'index.json').write_text(json.dumps(index, ensure_ascii=False, separators=(',', ':')))
    (ROOT / 'public' / 'data' / 'research_areas.json').write_text(json.dumps(areas, ensure_ascii=False, separators=(',', ':')))
    db = release / f'professor_dashboard_{a.year}.sqlite'
    con = sqlite3.connect(db)
    for pid in by_pid:
        x = profs[pid]
        con.execute('UPDATE professors SET lead_work_count=? WHERE professor_id=?', (x['lead_work_count'], pid))
        con.execute('DELETE FROM yearly_lead_output WHERE professor_id=?', (pid,))
        con.executemany('INSERT INTO yearly_lead_output VALUES (?,?,?,?,?,?,?,?,?,?,?,?)', [
            (pid, y['year'], y['stage'], y['total'], y['first_author'], y['corresponding_author'], y['impact_low'],
             y['impact_medium'], y['impact_high'], y['impact_unknown'], y['mean_journal_2yr_citedness'], y['article_citations'])
            for y in x['yearly']])
        con.execute('DELETE FROM professor_journal_output WHERE professor_id=?', (pid,))
        con.executemany('INSERT INTO professor_journal_output (professor_id,journal,lead_work_count,openalex_2yr_mean_citedness) '
                        'VALUES (?,?,?,?)', [(pid, j['journal'], j['lead_work_count'], j['openalex_2yr_mean_citedness']) for j in x['journals']])
    con.execute("UPDATE release_metadata SET value=? WHERE key='lead_work_count'", (str(dashboard['meta']['lead_work_count']),))
    con.execute("INSERT OR REPLACE INTO release_metadata VALUES (?, ?)", (key, json.dumps(patch, ensure_ascii=False)))
    con.commit()
    con.execute('VACUUM')
    integrity = con.execute('PRAGMA integrity_check').fetchone()[0]
    con.close()
    manifest = json.loads((release / 'manifest.json').read_text())
    manifest.update({'lead_work_count': dashboard['meta']['lead_work_count'], key: patch,
                     'public_db_bytes': db.stat().st_size, 'sqlite_integrity': integrity})
    mtext = json.dumps(manifest, ensure_ascii=False, indent=2)
    for path in (release / 'manifest.json', ROOT / 'public' / 'data' / 'manifest.json'):
        path.write_text(mtext)
    (ROOT / 'public' / 'downloads' / db.name).write_bytes(db.read_bytes())
    rebind_constellation(ROOT, {'date': patch['date'], 'note': f"{patch['date']} {key}: lead-output fields only"})
    print(f"patched: {patch['papers_removed']} papers of {patch['researchers']} researchers; lead_work_count {dashboard['meta']['lead_work_count']:,}")


if __name__ == '__main__':
    main()
