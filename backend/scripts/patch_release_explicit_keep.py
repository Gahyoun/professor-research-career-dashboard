#!/usr/bin/env python3
"""Explicit per-researcher decision: keep only the works a person confirmed as the researcher's
(by OpenAlex field or venue), drop the rest as namesakes, and rebuild that researcher's public
release from the kept works. For IDs so mixed that the general rule cannot help (2026-11-05: a
mathematician's OpenAlex ID held hundreds of papers by several namesakes at his own PhD and
current universities, so institution anchors were contaminated too).

  OPENALEX_API_KEY=… NAMES_PASSWORD=… python3 backend/scripts/patch_release_explicit_keep.py \
      --public-id P-… --uid prof:… --keep-field Mathematics \
      --keep-venue '(?i)differential equations|mathemat|nonlinear analysis|functional analysis|calculus of variations' \
      --rejected-out PRIVATE/rejected.json [--dry-run]

Kept: works whose OpenAlex primary field is a --keep-field, or whose venue matches --keep-venue
(the venue of an unresolved paper is read from its encrypted title row). Rebuilt from the kept,
resolved works with the full build's rules: topic map (Louvain resolution 1.05, seed 4), lead
output (first/corresponding author, journal, year >= PhD-5), research areas. --rejected-out writes
the dropped work IDs as apply_verified_works.py "rejected_works" for the private build.
"""
import argparse
import json
import os
import re
import sqlite3
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'backend' / 'scripts'))
from patch_release_verified_works import (  # noqa: E402
    ALLOWED, EMPTY, MAX_YEAR, OpenAlex, add_areas, add_lead_works, analyse, build_one, compact_researcher, ctfidf_terms,
    english_label, english_tags, fold_in, norm_title, normalise_doi, oa_compact, read_titles, rebind_constellation, short,
    stable_seed, text_of, topic_vectors_from, vault_key, write_titles)
from patch_release_namesakes import resolve  # noqa: E402


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--public-id', required=True)
    p.add_argument('--uid', required=True, help='private professor_uid, for the rejected list')
    p.add_argument('--keep-field', action='append', default=[])
    p.add_argument('--keep-venue', default='')
    p.add_argument('--rejected-out')
    p.add_argument('--author-name', help="regex on the lowercase letters of the author's raw name, e.g. '^(sunghoonkim|kimsunghoon|shkim|kimsh)$'")
    p.add_argument('--note', default='explicit keep decision')
    p.add_argument('--year', default='2026')
    p.add_argument('--dry-run', action='store_true')
    a = p.parse_args()
    pid = a.public_id
    release = ROOT / 'data' / 'releases' / a.year
    topics_dir = ROOT / 'public' / 'data' / 'topics'
    dashboard = json.loads((release / 'dashboard.json').read_text())
    prof = next(x for x in dashboard['professors'] if x['id'] == pid)
    index = json.loads((topics_dir / 'index.json').read_text())
    areas = json.loads((ROOT / 'public' / 'data' / 'research_areas.json').read_text())
    aes, aad = vault_key(topics_dir, os.environ['NAMES_PASSWORD'])
    oa = OpenAlex(os.environ['OPENALEX_API_KEY'])
    venue_re = re.compile(a.keep_venue) if a.keep_venue else None
    rows = read_titles(topics_dir, aes, aad, pid)
    resolved, unresolved = resolve(oa, rows)

    def keep_work(w, venue):
        field = (((w or {}).get('primary_topic') or {}).get('field') or {}).get('display_name')
        return field in a.keep_field or bool(venue_re and venue and venue_re.search(venue))

    kept, dropped = {}, []
    for r, w in resolved:
        venue = (((w.get('primary_location') or {}).get('source') or {}).get('display_name')) or r.get('venue')
        (kept.__setitem__(short(w['id']), w) if keep_work(w, venue) else dropped.append(short(w['id'])))
    unresolved_kept = [r for r in unresolved if venue_re and r.get('venue') and venue_re.search(r['venue'])]
    report = {'published': len(rows), 'resolved': len(resolved), 'kept': len(kept), 'dropped_resolved': len(dropped),
              'unresolved': len(unresolved), 'unresolved_math_venue_lost_from_topics': len(unresolved_kept)}

    # topics from the kept works
    trows = [{'work_id': k, 'year': w['publication_year'], 'doi': w.get('doi') or '', 'title': w.get('title') or ''} for k, w in kept.items()]
    seeds, alluvial, stats = build_one(prof, trows, {k: oa_compact(w) for k, w in kept.items()},
                                       SimpleNamespace(min_shared=2, resolution=1.05, seed=4, fetched_at=str(date.today())))
    seeds_by = {w['id']: w for w in seeds['works']}
    papers, private, texts, refs, owners = [], [], [], [], []
    for paper in sorted(alluvial['papers'], key=lambda x: (x.get('year') or 0)):
        papers.append({'year': paper['year'], 'topic': paper['topic'], 'era': paper.get('era'), 'cited': paper.get('cited', 0)})
        private.append({'year': paper['year'], 'topic': paper['topic'], 'title': paper['title'], 'venue': paper.get('venue') or None,
                        'doi': normalise_doi(paper.get('doi'))})
        texts.append(text_of(seeds_by.get(paper['id'], {'title': paper['title']})))
        refs.append(seeds_by.get(paper['id'], {}).get('referenced_works') or [])
        owners.append(paper['topic'])
    exclude = frozenset(n.lower() for w in kept.values() for x in w.get('authorships') or []
                        for n in (x.get('raw_author_name') or '', (x.get('author') or {}).get('display_name') or '') if n.strip())
    docs, members = defaultdict(list), defaultdict(list)
    for i, t in enumerate(owners):
        docs[t].append(texts[i])
        members[t].append(i)
    keywords = ctfidf_terms(dict(docs), n_terms=8, exclude=exclude)
    vectors = topic_vectors_from(fold_in(texts, index['semantic']), dict(members))
    topics = []
    for t in alluvial['topics']:
        kw = keywords.get(t['id'], [])
        label = english_label(kw, curated=t['label'])
        topics.append({'id': t['id'], 'label': label, 'size': t['size'], 'birth_year': t.get('birth_year'),
                       'parent': ({k: t['parent'].get(k) for k in ('from', 'sim', 'from_year', 'to_year')} if t.get('parent') else None),
                       'keywords': kw, 'tags': english_tags(label, kw), 'vector': vectors.get(t['id'])})
    entry = {'id': pid, 'alias': None, 'subject': prof['subject'], 'institution': prof.get('current_institution'),
             'eras': [{'label': e.get('label'), 'start': e.get('start'), 'end': e.get('end')} for e in alluvial['era_span']],
             'topics': topics, 'papers': papers, 'recip': [],
             'counts': {'source_works': None, 'kept_works': len(papers), 'merged_versions': None}, 'fetched_at': alluvial['fetched_at']}
    info = analyse([x['year'] for x in papers], [x['topic'] for x in papers], refs, width=3, n_null=200, n_boot=200, seed=stable_seed(pid))
    compact_researcher(entry)
    pos = next(i for i, r in enumerate(index['researchers']) if r['id'] == pid)
    index['researchers'][pos] = entry

    # lead output recomputed from the kept works (the researcher's authorship = the name-matching one)
    name_re = re.compile(a.author_name) if a.author_name else None

    def mine(w):
        cand = [x for x in w.get('authorships') or []
                if name_re and name_re.search(re.sub(r'[^a-z]', '', (x.get('raw_author_name') or (x.get('author') or {}).get('display_name') or '').lower()))]
        return cand[0] if len(cand) == 1 else None
    roles = []
    for w in kept.values():
        me = mine(w)
        src = (w.get('primary_location') or {}).get('source') or {}
        y = w.get('publication_year')
        if me and (me.get('author_position') == 'first' or me.get('is_corresponding')) and w.get('type') in ALLOWED \
                and src.get('type') == 'journal' and y and y <= MAX_YEAR and not (prof.get('phd_year') and y < prof['phd_year'] - 5):
            roles.append({'year': y, 'author_position': me.get('author_position'), 'is_corresponding': me.get('is_corresponding'),
                          'source': src, 'cited_by_count': w.get('cited_by_count'), 'source_id': src.get('id')})
    srcs = oa.sources([r['source_id'] for r in roles])
    for r in roles:
        v = ((srcs.get(r['source_id']) or {}).get('summary_stats') or {}).get('2yr_mean_citedness')
        r['impact'] = float(v) if v is not None else None
    before = prof['lead_work_count']
    prof['yearly'], prof['journals'], prof['lead_work_count'] = [], [], 0
    add_lead_works(prof, roles, a.year)
    areas['researchers'].pop(pid, None)
    add_areas(areas, pid, list(kept.values()))
    report.update({'topic_papers_after': len(papers), 'topics_after': stats['topics'], 'lead_work_count': [before, prof['lead_work_count']]})
    print(json.dumps(report, ensure_ascii=False, indent=1))
    if a.rejected_out:
        Path(a.rejected_out).write_text(json.dumps({'professor_uid': a.uid, 'source': {'kind': 'explicit_keep_decision', 'checked': str(date.today()),
                                                    'keep_fields': a.keep_field, 'keep_venue': a.keep_venue, 'note': a.note},
                                                    'rejected_works': [{'work_id': k} for k in sorted(dropped)]}, ensure_ascii=False, indent=1))
    if a.dry_run:
        return

    (topics_dir / 'info' / f'{pid}.json').write_text(json.dumps(info, ensure_ascii=False, separators=(',', ':')))
    write_titles(topics_dir, aes, aad, pid, private)
    patch = {'date': str(date.today()), 'researchers': 1, 'papers_removed': len(rows) - len(papers), 'rule': a.note}
    dashboard['meta'].setdefault('manual_explicit_patches', []).append(patch)
    dashboard['meta']['lead_work_count'] = sum(x['lead_work_count'] for x in dashboard['professors'])
    text = json.dumps(dashboard, ensure_ascii=False, separators=(',', ':'))
    for path in (release / 'dashboard.json', ROOT / 'public' / 'data' / 'dashboard.json'):
        path.write_text(text)
    (topics_dir / 'index.json').write_text(json.dumps(index, ensure_ascii=False, separators=(',', ':')))
    (ROOT / 'public' / 'data' / 'research_areas.json').write_text(json.dumps(areas, ensure_ascii=False, separators=(',', ':')))
    db = release / f'professor_dashboard_{a.year}.sqlite'
    con = sqlite3.connect(db)
    con.execute('UPDATE professors SET lead_work_count=? WHERE professor_id=?', (prof['lead_work_count'], pid))
    con.execute('DELETE FROM yearly_lead_output WHERE professor_id=?', (pid,))
    con.executemany('INSERT INTO yearly_lead_output VALUES (?,?,?,?,?,?,?,?,?,?,?,?)', [
        (pid, y['year'], y['stage'], y['total'], y['first_author'], y['corresponding_author'], y['impact_low'], y['impact_medium'],
         y['impact_high'], y['impact_unknown'], y['mean_journal_2yr_citedness'], y['article_citations']) for y in prof['yearly']])
    con.execute('DELETE FROM professor_journal_output WHERE professor_id=?', (pid,))
    con.executemany('INSERT INTO professor_journal_output (professor_id,journal,lead_work_count,openalex_2yr_mean_citedness) VALUES (?,?,?,?)',
                    [(pid, j['journal'], j['lead_work_count'], j['openalex_2yr_mean_citedness']) for j in prof['journals']])
    con.execute("UPDATE release_metadata SET value=? WHERE key='lead_work_count'", (str(dashboard['meta']['lead_work_count']),))
    con.execute("INSERT OR REPLACE INTO release_metadata VALUES ('manual_explicit_patches', ?)",
                (json.dumps(dashboard['meta']['manual_explicit_patches'], ensure_ascii=False),))
    con.commit()
    con.execute('VACUUM')
    integrity = con.execute('PRAGMA integrity_check').fetchone()[0]
    con.close()
    manifest = json.loads((release / 'manifest.json').read_text())
    manifest.update({'lead_work_count': dashboard['meta']['lead_work_count'], 'manual_explicit_patches': dashboard['meta']['manual_explicit_patches'],
                     'public_db_bytes': db.stat().st_size, 'sqlite_integrity': integrity})
    mtext = json.dumps(manifest, ensure_ascii=False, indent=2)
    for path in (release / 'manifest.json', ROOT / 'public' / 'data' / 'manifest.json'):
        path.write_text(mtext)
    (ROOT / 'public' / 'downloads' / db.name).write_bytes(db.read_bytes())
    rebind_constellation(ROOT, {'date': patch['date'], 'note': f"{patch['date']} explicit keep decision: lead-output fields only"})
    print(f"patched {pid}: lead {before} -> {prof['lead_work_count']}; topic papers {len(rows)} -> {len(papers)}")


if __name__ == '__main__':
    main()
