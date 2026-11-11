#!/usr/bin/env python3
"""Remove namesake papers from the PUBLISHED release for given researchers with the
career-consistency rule (career_consistency.py), from real OpenAlex records, when the private
source database is not at hand. The private build applies the same rule through
STRICT_IDENTITY_PREDICATE / PublicationIdentityGate, so a later full rebuild agrees.

  OPENALEX_API_KEY=… NAMES_PASSWORD=… python3 backend/scripts/patch_release_namesakes.py \
      --public-id P-XXXXXXXXXX [--public-id …] [--dry-run]

Per researcher:
  1. published topic papers (encrypted title file) resolved to OpenAlex works (DOI, else exact
     title); unresolved papers are kept and reported;
  2. the researcher's authorship = the author ID present on most resolved works (an ID that
     absorbed a namesake still carries the researcher's own works); works without it are kept;
  (--rule corroboration: career_consistency.corroboration() instead, for researchers with the
   explicit 'require_corroboration' decision: identity AND subject affirmation per work)
  3. classify(): institutions of that authorship vs the public career institutions,
     coauthor IDs, OpenAlex primary field; dropped works leave the topic map (rebuilt with
     the same Louvain rule), the encrypted titles, the lead output (if they were counted:
     first/corresponding, journal) and the research areas.
"""
import argparse
import json
import os
import sqlite3
import sys
from collections import Counter
from datetime import date
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'backend' / 'scripts'))
from career_consistency import classify, corroboration  # noqa: E402
from patch_release_verified_works import (  # noqa: E402
    ALLOWED, JOURNAL_TYPES, MAX_YEAR, OpenAlex, add_areas, add_lead_works, build_one, compact_researcher,
    english_label, english_tags, fold_in, norm_title, normalise_doi, oa_compact, read_titles, rebind_constellation,
    short, stable_seed, text_of, topic_vectors_from, vault_key, write_titles, analyse, ctfidf_terms)


def resolve(oa, rows):
    found = oa.by_doi([r['doi'].lower() for r in rows if r.get('doi')])
    out, unresolved = [], []
    for r in rows:
        cands = found.get((r.get('doi') or '').lower(), [])
        best = max(cands, key=lambda w: (norm_title(w.get('title')) == norm_title(r['title']),
                                         w.get('publication_year') == r['year']), default=None)
        if best is None:
            try:
                hits = oa.get('works', search=r['title'][:200], **{'per-page': 5})['results']
            except RuntimeError:      # a title the search endpoint rejects stays unresolved
                hits = []
            best = next((w for w in hits if norm_title(w.get('title')) == norm_title(r['title'])), None)
        (out.append((r, best)) if best else unresolved.append(r))
    return out, unresolved


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--public-id', action='append', required=True)
    p.add_argument('--year', default='2026')
    p.add_argument('--dry-run', action='store_true')
    p.add_argument('--rule', choices=('career', 'corroboration'), default='career',
                   help="career: the career-consistency rule; corroboration: the explicit 'require_corroboration' "
                        "decision (identity AND subject affirmation for every work)")
    a = p.parse_args()
    key, password = os.environ.get('OPENALEX_API_KEY'), os.environ.get('NAMES_PASSWORD')
    if not key or not password:
        sys.exit('OPENALEX_API_KEY and NAMES_PASSWORD are required (environment only)')
    release = ROOT / 'data' / 'releases' / a.year
    topics_dir = ROOT / 'public' / 'data' / 'topics'
    dashboard = json.loads((release / 'dashboard.json').read_text())
    profs = {x['id']: x for x in dashboard['professors']}
    index = json.loads((topics_dir / 'index.json').read_text())
    areas = json.loads((ROOT / 'public' / 'data' / 'research_areas.json').read_text())
    aes, aad = vault_key(topics_dir, password)
    oa = OpenAlex(key)
    report, removed_total, lead_total = {}, 0, 0

    for pid in a.public_id:
        prof = profs[pid]
        rows = read_titles(topics_dir, aes, aad, pid)
        resolved, unresolved = resolve(oa, rows)
        ids = Counter(short((x.get('author') or {}).get('id')) for _, w in resolved
                      for x in w.get('authorships') or [] if (x.get('author') or {}).get('id'))
        target = ids.most_common(1)[0][0] if ids else None
        works, by_id = [], {}
        for r, w in resolved:
            wid = short(w['id'])
            mine = [x for x in w.get('authorships') or [] if short((x.get('author') or {}).get('id')) == target]
            if len(mine) != 1:
                continue
            by_id[wid] = (r, w, mine[0])
            works.append({'id': wid, 'year': w.get('publication_year'), 'institutions': [i.get('display_name') for i in mine[0].get('institutions') or []],
                          'coauthors': [short((x.get('author') or {}).get('id')) for x in w['authorships']
                                        if (x.get('author') or {}).get('id') and x is not mine[0]],
                          'subfield': ((w.get('primary_topic') or {}).get('subfield') or {}).get('display_name'),
                          'field': ((w.get('primary_topic') or {}).get('field') or {}).get('display_name'),
                          'domain': ((w.get('primary_topic') or {}).get('domain') or {}).get('display_name')})
        if a.rule == 'corroboration':
            drops = corroboration(works, [(c['institution'], c.get('start_year'), c.get('end_year')) for c in prof['career']],
                                  prof['subject'])
        else:
            drops = classify(works, [c['institution'] for c in prof['career']], prof['subject'])
        rep = report[pid] = {'published': len(rows), 'resolved': len(resolved), 'unresolved_kept': len(unresolved),
                             'dropped': [{'year': by_id[w][0]['year'], 'reason': why, 'title': by_id[w][0]['title'][:80],
                                          'institutions': next(x['institutions'] for x in works if x['id'] == w)}
                                         for w, why in sorted(drops.items(), key=lambda kv: by_id[kv[0]][0]['year'])]}
        if not drops:
            continue

        # topics without the dropped works (resolved survivors only; unresolved papers stay by title)
        keep = {short(w['id']): w for r, w in resolved if short(w['id']) not in drops}
        if unresolved:
            sys.exit(f'{pid}: {len(unresolved)} published papers unresolved; resolve them before rebuilding topics')
        trows = [{'work_id': wid, 'year': w['publication_year'], 'doi': w.get('doi') or '', 'title': w.get('title') or ''}
                 for wid, w in keep.items()]
        seeds, alluvial, stats = build_one(prof, trows, {wid: oa_compact(w) for wid, w in keep.items()},
                                           SimpleNamespace(min_shared=2, resolution=1.05, seed=4, fetched_at=str(date.today())))
        seeds_by = {w['id']: w for w in seeds['works']}
        papers, private, texts, refs, owners = [], [], [], [], []
        for paper in sorted(alluvial['papers'], key=lambda x: (x.get('year') or 0)):
            papers.append({'year': paper['year'], 'topic': paper['topic'], 'era': paper.get('era'), 'cited': paper.get('cited', 0)})
            private.append({'year': paper['year'], 'topic': paper['topic'], 'title': paper['title'],
                            'venue': paper.get('venue') or None, 'doi': normalise_doi(paper.get('doi'))})
            texts.append(text_of(seeds_by.get(paper['id'], {'title': paper['title']})))
            refs.append(seeds_by.get(paper['id'], {}).get('referenced_works') or [])
            owners.append(paper['topic'])
        exclude = frozenset(n.lower() for w in keep.values() for x in w.get('authorships') or []
                            for n in (x.get('raw_author_name') or '', (x.get('author') or {}).get('display_name') or '') if n.strip())
        docs, members = {}, {}
        for row, tid in enumerate(owners):
            docs.setdefault(tid, []).append(texts[row])
            members.setdefault(tid, []).append(row)
        keywords = ctfidf_terms(docs, n_terms=8, exclude=exclude)
        vectors = topic_vectors_from(fold_in(texts, index['semantic']), members)
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
                 'counts': {'source_works': None, 'kept_works': len(papers), 'merged_versions': None},
                 'fetched_at': alluvial['fetched_at']}
        info = analyse([x['year'] for x in papers], [x['topic'] for x in papers], refs, width=3, n_null=200, n_boot=200,
                       seed=stable_seed(pid))
        compact_researcher(entry)
        pos = next(k for k, r in enumerate(index['researchers']) if r['id'] == pid)
        index['researchers'][pos] = entry
        rep.update({'topic_papers_after': len(papers), 'topics_after': stats['topics']})

        # lead output: dropped works that the release counted (same gate as build_release.py)
        roles = []
        for wid in drops:
            r, w, me = by_id[wid]
            src = (w.get('primary_location') or {}).get('source') or {}
            y = w.get('publication_year')
            if (me.get('author_position') == 'first' or me.get('is_corresponding')) and w.get('type') in ALLOWED \
                    and src.get('type') == 'journal' and y and y <= MAX_YEAR and not (prof.get('phd_year') and y < prof['phd_year'] - 5):
                roles.append({'year': y, 'author_position': me.get('author_position'), 'is_corresponding': me.get('is_corresponding'),
                              'source': src, 'cited_by_count': w.get('cited_by_count'), 'source_id': src.get('id')})
        srcs = oa.sources([r['source_id'] for r in roles])
        for r in roles:
            v = ((srcs.get(r['source_id']) or {}).get('summary_stats') or {}).get('2yr_mean_citedness')
            r['impact'] = float(v) if v is not None else None
        before = prof.get('lead_work_count', 0)
        counted = {(y['year']) for y in prof.get('yearly') or [] if y['total']}
        roles = [r for r in roles if r['year'] in counted]
        add_lead_works(prof, roles, a.year, sign=-1)
        rep['lead_work_count'] = [before, prof.get('lead_work_count', 0)]
        add_areas(areas, pid, [by_id[w][1] for w in drops], sign=-1)
        removed_total += len(drops)
        lead_total += len(roles)
        if not a.dry_run:
            (topics_dir / 'info' / f'{pid}.json').write_text(json.dumps(info, ensure_ascii=False, separators=(',', ':')))
            write_titles(topics_dir, aes, aad, pid, private)

    print(json.dumps(report, ensure_ascii=False, indent=1))
    if a.dry_run or not removed_total:
        return
    patch = {'date': str(date.today()), 'researchers': sum(1 for r in report.values() if r['dropped']),
             'papers_removed': removed_total, 'lead_works_removed': lead_total,
             'rule': 'career-consistency namesake rule (career_consistency.py): works without a career institution '
                     'and with fewer than two coauthors shared with career-anchored works'}
    dashboard['meta']['manual_namesake_patch'] = patch
    dashboard['meta']['lead_work_count'] = sum(x['lead_work_count'] for x in dashboard['professors'])
    text = json.dumps(dashboard, ensure_ascii=False, separators=(',', ':'))
    for path in (release / 'dashboard.json', ROOT / 'public' / 'data' / 'dashboard.json'):
        path.write_text(text)
    index.setdefault('method', {})['namesake_patch'] = f"{patch['date']}: {removed_total} papers removed by the career-consistency rule"
    (topics_dir / 'index.json').write_text(json.dumps(index, ensure_ascii=False, separators=(',', ':')))
    (ROOT / 'public' / 'data' / 'research_areas.json').write_text(json.dumps(areas, ensure_ascii=False, separators=(',', ':')))
    db = release / f'professor_dashboard_{a.year}.sqlite'
    con = sqlite3.connect(db)
    for pid in report:
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
    con.execute("INSERT OR REPLACE INTO release_metadata VALUES ('manual_namesake_patch', ?)", (json.dumps(patch, ensure_ascii=False),))
    con.commit()
    con.execute('VACUUM')
    integrity = con.execute('PRAGMA integrity_check').fetchone()[0]
    con.close()
    manifest = json.loads((release / 'manifest.json').read_text())
    manifest.update({'lead_work_count': dashboard['meta']['lead_work_count'], 'manual_namesake_patch': patch,
                     'public_db_bytes': db.stat().st_size, 'sqlite_integrity': integrity})
    mtext = json.dumps(manifest, ensure_ascii=False, indent=2)
    for path in (release / 'manifest.json', ROOT / 'public' / 'data' / 'manifest.json'):
        path.write_text(mtext)
    (ROOT / 'public' / 'downloads' / db.name).write_bytes(db.read_bytes())
    rebind_constellation(ROOT, {'date': patch['date'], 'note': f"{patch['date']} manual_namesake_patch: lead-output fields only"})
    print(f'patched: {removed_total} papers removed, {lead_total} lead works; lead_work_count {dashboard["meta"]["lead_work_count"]:,}')


if __name__ == '__main__':
    main()
