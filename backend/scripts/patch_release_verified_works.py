#!/usr/bin/env python3
"""Add externally verified works to the PUBLISHED release for a few researchers, from real
OpenAlex records, when the private source database is not at hand.

The full rebuild (apply_verified_works.py on the private DB, then update_release.sh) stays
the reference path; this patch computes the same public quantities for the listed people
with the same rules, so a later full rebuild with the same verified list reproduces it.

  OPENALEX_API_KEY=… NAMES_PASSWORD=… python3 backend/scripts/patch_release_verified_works.py \
      --verified verified.json --public-ids anon_map.json [--dry-run]

verified.json  as for apply_verified_works.py (one spec or a list); public-ids maps each
               professor_uid to its public P-… id. Works with author_id null are skipped
               (the private path cannot import them either).

Per researcher P:
  1. current topic papers: P's encrypted title file (DOIs) resolved to OpenAlex works;
  2. new works: listed works passing the topic selection rule (article/review/letter/
     editorial, year <= 2026, year >= PhD year - 5) and holding the listed authorship;
  3. topics: build_release_topics.build_one on current + new (bibliographic coupling,
     Louvain resolution 1.05, seed 4, eras from the public career), exported as
     export_public_index.py does; topic vectors are folded into the existing shared LSA
     space from its published term vectors (the space itself is not refit);
  4. lead output (dashboard yearly, journals, public SQLite): each NEW work that is first-
     or corresponding-author and in a journal is added with build_release.py's add_role
     rule; existing counts are kept as published;
  5. research areas: each new work's OpenAlex primary topic is counted.
Release metadata records the patch (counts only; no names, titles or ids).
"""
import argparse
import base64
import gzip
import hashlib
import json
import math
import os
import re
import secrets
import sqlite3
import sys
import time
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'backend' / 'scripts'))
sys.path.insert(0, str(ROOT / 'backend' / 'topics'))
from build_release_topics import JOURNAL_TYPES, MAX_YEAR, build_one, compact as oa_compact  # noqa: E402
from compact_index import compact_researcher  # noqa: E402
from encrypt_titles import normalise_doi  # noqa: E402
from export_public_index import text_of  # noqa: E402
from info_flow import analyse, stable_seed  # noqa: E402
from topic_semantics import TOKEN, ctfidf_terms, english_label, english_tags, quantize  # noqa: E402

API = 'https://api.openalex.org'
ALLOWED = {'article', 'review', 'letter', 'editorial'}


# ---------------------------------------------------------------- OpenAlex
class OpenAlex:
    def __init__(self, key):
        self.key, self.calls = key, 0

    def get(self, path, **params):
        params['api_key'] = self.key
        url = f'{API}/{path}?' + urllib.parse.urlencode(params)
        for attempt in range(6):
            try:
                with urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent': 'professor-career-dashboard/1'}),
                                            timeout=90) as r:
                    self.calls += 1
                    return json.loads(r.read())
            except Exception:
                if attempt == 5:
                    raise RuntimeError(f'OpenAlex request failed: {path}')
                time.sleep(2 ** attempt)

    def works(self, ids):
        out = {}
        ids = sorted(set(ids))
        for i in range(0, len(ids), 50):
            chunk = ids[i:i + 50]
            for w in self.get('works', filter='openalex:' + '|'.join(chunk), **{'per-page': 50})['results']:
                out[w['id'].rsplit('/', 1)[1]] = w
        return out

    def by_doi(self, dois):
        out = defaultdict(list)
        dois = sorted(set(dois))
        for i in range(0, len(dois), 50):
            chunk = dois[i:i + 50]
            res = self.get('works', filter='doi:' + '|'.join(chunk), **{'per-page': 200})['results']
            for w in res:
                out[(w.get('doi') or '').lower()].append(w)
        return out

    def sources(self, ids):
        out = {}
        ids = sorted({i for i in ids if i})
        for i in range(0, len(ids), 50):
            chunk = ids[i:i + 50]
            for s in self.get('sources', filter='openalex:' + '|'.join(chunk), **{'per-page': 50})['results']:
                out[s['id']] = s
        return out


def short(x):
    return str(x or '').rstrip('/').rsplit('/', 1)[-1]


def norm_title(t):
    return re.sub(r'[^a-z0-9]', '', (t or '').lower())


# ---------------------------------------------------------------- title vault
def vault_key(topics_dir, password):
    key = json.loads((topics_dir / 'titles' / 'key.json').read_text())
    aes = __import__('cryptography.hazmat.primitives.ciphers.aead', fromlist=['AESGCM']).AESGCM(
        hashlib.pbkdf2_hmac('sha256', password.encode(), base64.b64decode(key['salt']), key['iterations'], 32))
    return aes, key['aad']


def read_titles(topics_dir, aes, aad, pid):
    f = topics_dir / 'titles' / f'{pid}.json'
    if not f.exists():
        return []
    d = json.loads(f.read_text())
    return json.loads(gzip.decompress(aes.decrypt(base64.b64decode(d['nonce']), base64.b64decode(d['ciphertext']),
                                                  (aad + pid).encode())))


def write_titles(topics_dir, aes, aad, pid, rows):
    nonce = secrets.token_bytes(12)
    plain = gzip.compress(json.dumps(rows, ensure_ascii=False, separators=(',', ':')).encode(), mtime=0)
    ct = aes.encrypt(nonce, plain, (aad + pid).encode())
    (topics_dir / 'titles' / f'{pid}.json').write_text(json.dumps({'nonce': base64.b64encode(nonce).decode(),
                                                                    'ciphertext': base64.b64encode(ct).decode()}))


# ---------------------------------------------------------------- semantic fold-in
def fold_in(texts, semantic):
    """Unit document vectors in the published LSA space: sublinear tf × published term vectors."""
    import numpy as np
    terms = semantic['terms']
    scale = float(semantic.get('scale', 127))
    dims = int(semantic['dims'])
    pat = re.compile(TOKEN)
    out = []
    for t in texts:
        tf = Counter(w for w in pat.findall((t or '').lower()) if w in terms)
        v = np.zeros(dims)
        for w, n in tf.items():
            v += (1 + math.log(n)) * np.asarray(terms[w], dtype=float) / scale
        nrm = np.linalg.norm(v)
        out.append(v / nrm if nrm else v)
    return np.asarray(out)


def topic_vectors_from(doc_vecs, members):
    import numpy as np
    out = {}
    for k, rows in members.items():
        if rows:
            c = doc_vecs[rows].mean(axis=0)
            n = np.linalg.norm(c)
            if n:
                out[k] = quantize((c / n)[None, :])[0]
    return out


# ---------------------------------------------------------------- lead output (build_release.py rules)
def impact_band(v):
    return 'unknown' if v is None else 'low' if v < 2 else 'medium' if v < 5 else 'high'


def stage_for_year(careers, y, phd_year, appointment_year):
    priority = {'doctoral': 1, 'postdoc': 2, 'faculty': 3}
    active = [x['stage'] for x in careers if x.get('start_year') is not None and x['start_year'] <= y <= (x.get('end_year') or y)]
    if active:
        return max(active, key=lambda x: priority[x])
    if phd_year and y <= phd_year:
        return 'doctoral'
    if appointment_year and y < appointment_year:
        return 'postdoc'
    if appointment_year and y >= appointment_year:
        return 'faculty'
    return None


EMPTY = {'total': 0, 'first_author': 0, 'corresponding_author': 0, 'impact_low': 0, 'impact_medium': 0,
         'impact_high': 0, 'impact_unknown': 0, 'impact_sum': 0.0, 'impact_known': 0, 'article_citations': 0}


def add_lead_works(prof, roles, release_year, sign=1):
    """roles: [{year, author_position, is_corresponding, source{id,display_name,type}, cited_by_count, impact}].
    Merges into the published yearly/journals of prof (dict), rebuilding the year axis as
    build_release.py does. Returns the number of works added."""
    agg = {}
    for y in prof.get('yearly') or []:
        if y['total']:
            known = y['total'] - y['impact_unknown']
            agg[y['year']] = {**{k: y[k] for k in ('total', 'first_author', 'corresponding_author', 'impact_low',
                                                  'impact_medium', 'impact_high', 'impact_unknown', 'article_citations')},
                              'impact_known': known,
                              'impact_sum': (y['mean_journal_2yr_citedness'] or 0.0) * known}
    journals = {j['journal']: {'n': j['lead_work_count'], 'm': j['openalex_2yr_mean_citedness']} for j in prof.get('journals') or []}
    for r in roles:          # sign=-1 removes works (namesake patch); counts never go below zero
        a = agg.setdefault(int(r['year']), dict(EMPTY))
        a['total'] += sign
        a['first_author'] += sign * int(r['author_position'] == 'first')
        a['corresponding_author'] += sign * int(bool(r['is_corresponding']))
        a[f"impact_{impact_band(r['impact'])}"] += sign
        if r['impact'] is not None:
            a['impact_sum'] += sign * r['impact']
            a['impact_known'] += sign
        a['article_citations'] = max(0, a['article_citations'] + sign * int(r.get('cited_by_count') or 0))
        if a['total'] < 0:
            raise ValueError(f"removing a work not counted in {r['year']}")
        if sign < 0:   # the published role/impact of a removed work may differ slightly: keep counters consistent
            for k in ('first_author', 'corresponding_author', 'impact_known', 'impact_low', 'impact_medium', 'impact_high', 'impact_unknown'):
                a[k] = max(0, a[k])
            a['impact_sum'] = max(0.0, a['impact_sum']) if a['impact_known'] else 0.0
            bands = ('impact_unknown', 'impact_low', 'impact_medium', 'impact_high')
            excess = sum(a[k] for k in bands) - a['total']
            for k in bands:
                take = min(max(excess, 0), a[k])
                a[k] -= take
                excess -= take
            if excess < 0:
                a['impact_unknown'] -= excess
            a['impact_known'] = min(a['impact_known'], a['total'] - a['impact_unknown'])
            a['first_author'] = min(a['first_author'], a['total'])
            a['corresponding_author'] = min(a['corresponding_author'], a['total'])
        name = r['source'].get('display_name') or r['source'].get('id')
        if name:
            j = journals.setdefault(name, {'n': 0, 'm': None})
            j['n'] += sign
            if j['m'] is None and r['impact'] is not None and sign > 0:
                j['m'] = round(r['impact'], 3)
            if j['n'] <= 0:
                del journals[name]
    agg = {y: v for y, v in agg.items() if v['total'] > 0}
    if not agg:
        prof['yearly'], prof['lead_work_count'], prof['journals'] = [], 0, []
        return len(roles)
    doctoral = [c['start_year'] for c in prof['career'] if c['stage'] == 'doctoral' and c.get('start_year')]
    start = min([min(agg)] + doctoral)
    prof['yearly'] = []
    for y in range(start, int(release_year) + 1):
        a = agg.get(y) or dict(EMPTY)
        prof['yearly'].append({
            'year': y, 'stage': stage_for_year(prof['career'], y, prof['phd_year'], prof['appointment_year']),
            'total': a['total'], 'first_author': a['first_author'], 'corresponding_author': a['corresponding_author'],
            'impact_low': a['impact_low'], 'impact_medium': a['impact_medium'], 'impact_high': a['impact_high'],
            'impact_unknown': a['impact_unknown'],
            'mean_journal_2yr_citedness': round(a['impact_sum'] / a['impact_known'], 3) if a['impact_known'] else None,
            'article_citations': a['article_citations']})
    prof['lead_work_count'] = sum(x['total'] for x in prof['yearly'])
    prof['journals'] = sorted(({'journal': k, 'lead_work_count': v['n'], 'openalex_2yr_mean_citedness': v['m']}
                               for k, v in journals.items()), key=lambda x: (-x['lead_work_count'], x['journal']))
    return len(roles)


# ---------------------------------------------------------------- research areas
def add_areas(areas, pid, works, sign=1):
    names = {k: {(row[0] if isinstance(row, list) else row): i for i, row in enumerate(areas[k])}
             for k in ('domains', 'fields', 'subfields', 'topics')}

    def idx(kind, name, parent=None):
        if name not in names[kind]:
            areas[kind].append(name if kind == 'domains' else [name, parent])
            names[kind][name] = len(areas[kind]) - 1
        return names[kind][name]

    r = areas['researchers'].setdefault(pid, {'n': 0, 'f': [], 's': [], 't': []})
    counts = {k: dict((i, n) for i, n in r[k]) for k in ('f', 's', 't')}
    for w in works:
        pt = w.get('primary_topic') or {}
        if not pt:
            continue
        d = idx('domains', (pt.get('domain') or {}).get('display_name'))
        f = idx('fields', (pt.get('field') or {}).get('display_name'), d)
        s = idx('subfields', (pt.get('subfield') or {}).get('display_name'), f)
        t = idx('topics', pt.get('display_name'), s)
        for k, i in (('f', f), ('s', s), ('t', t)):
            counts[k][i] = max(0, counts[k].get(i, 0) + sign)
        r['n'] = max(0, r['n'] + sign)
    for k in ('f', 's', 't'):
        r[k] = sorted(([i, n] for i, n in counts[k].items() if n > 0), key=lambda x: (-x[1], x[0]))


def rebind_constellation(root, patch):
    """The page refuses constellation_metadata.json unless its manifest names the exact
    dashboard.json hash. The patch changes only lead-output fields, which that metadata does
    not use, so the manifest is rebound to the new bytes and says so."""
    path = root / 'public' / 'data' / 'constellation_metadata.manifest.json'
    manifest = json.loads(path.read_text())
    manifest['public_data_sha256'] = hashlib.sha256((root / 'public' / 'data' / 'dashboard.json').read_bytes()).hexdigest()
    note = patch.get('note') or (f"{patch['date']} manual_verified_patch: lead-output fields only; "
                                 "career and department metadata not recomputed")
    notes = manifest.get('rebound_after_patch') or []
    notes = [notes] if isinstance(notes, str) else notes
    manifest['rebound_after_patch'] = notes + ([note] if note not in notes else [])
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n')


# ---------------------------------------------------------------- main
def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--verified', required=True)
    p.add_argument('--public-ids', required=True, help='JSON {professor_uid: P-…}')
    p.add_argument('--year', default='2026')
    p.add_argument('--dry-run', action='store_true')
    p.add_argument('--refresh-topics', action='store_true',
                   help='rebuild the topic entries of the listed researchers even without new works (after a career patch)')
    a = p.parse_args()
    key, password = os.environ.get('OPENALEX_API_KEY'), os.environ.get('NAMES_PASSWORD')
    if not key or not password:
        sys.exit('OPENALEX_API_KEY and NAMES_PASSWORD are required (read from the environment, never printed)')

    sys.path.insert(0, str(ROOT / 'backend' / 'scripts'))
    from apply_verified_works import load_verified
    items = load_verified(a.verified)
    public_ids = json.loads(Path(a.public_ids).read_text())
    release = ROOT / 'data' / 'releases' / a.year
    topics_dir = ROOT / 'public' / 'data' / 'topics'
    dash_path = release / 'dashboard.json'
    dashboard = json.loads(dash_path.read_text())
    profs = {x['id']: x for x in dashboard['professors']}
    index = json.loads((topics_dir / 'index.json').read_text())
    areas = json.loads((ROOT / 'public' / 'data' / 'research_areas.json').read_text())
    aes, aad = vault_key(topics_dir, password)
    oa = OpenAlex(key)
    report = {'researchers': {}, 'skipped_no_author_id': 0}
    pending = {}

    def flush():
        for pid, (info, private) in pending.items():
            (topics_dir / 'info' / f'{pid}.json').write_text(json.dumps(info, ensure_ascii=False, separators=(',', ':')))
            write_titles(topics_dir, aes, aad, pid, private)

    by_uid = defaultdict(list)
    for it in items:
        by_uid[it['uid']].append(it)
    for uid, its in by_uid.items():
        pid = public_ids.get(uid)
        if pid not in profs:
            sys.exit(f'{uid}: no public id in --public-ids or not in the dashboard')
        prof = profs[pid]
        phd = prof.get('phd_year')
        rep = report['researchers'][pid] = {'listed': len(its)}

        # 1. current topic papers → OpenAlex ids
        current_rows = read_titles(topics_dir, aes, aad, pid)
        dois = [r['doi'].lower() for r in current_rows if r.get('doi')]
        found = oa.by_doi(dois) if dois else {}
        current = {}
        unresolved = []
        for r in current_rows:
            cands = found.get((r.get('doi') or '').lower(), [])
            cands = [w for w in cands if w.get('type') in JOURNAL_TYPES] or cands
            best = max(cands, key=lambda w: (norm_title(w.get('title')) == norm_title(r['title']),
                                             w.get('publication_year') == r['year'], -len(w.get('authorships') or [])),
                       default=None)
            if best is None:
                try:
                    hits = oa.get('works', search=r['title'][:200], **{'per-page': 5})['results']
                except RuntimeError:          # a title the search endpoint rejects counts as unresolved
                    hits = []
                best = next((w for w in hits if norm_title(w.get('title')) == norm_title(r['title'])), None)
            if best is None:
                unresolved.append(r['title'][:40])
                continue
            current[short(best['id'])] = best
        if unresolved:   # rebuilding topics would lose these papers: leave this researcher unchanged
            rep['skipped'] = f'{len(unresolved)} published papers not resolved to OpenAlex'
            continue
        rep['current_papers'] = len(current)

        # 2. new works
        listed = [i for i in its if i['author_id']]
        report['skipped_no_author_id'] += len(its) - len(listed)
        fetched = oa.works([i['work_id'] for i in listed])
        new, roles, why = {}, [], Counter()
        for i in listed:
            w = fetched.get(i['work_id'])
            if w is None:
                why['not_in_openalex'] += 1
                continue
            if i['work_id'] in current:
                why['already_published'] += 1
                continue
            y, t = w.get('publication_year'), w.get('type')
            mine = [x for x in w.get('authorships') or [] if short((x.get('author') or {}).get('id')) == i['author_id']]
            if len(mine) != 1:
                why['authorship_not_found'] += 1
                continue
            if t not in JOURNAL_TYPES or y is None or y > MAX_YEAR or (phd and y < phd - 5):
                why['outside_selection_rule'] += 1
                continue
            new[i['work_id']] = w
            src = (w.get('primary_location') or {}).get('source') or {}
            if (mine[0].get('author_position') == 'first' or mine[0].get('is_corresponding')) and t in ALLOWED \
                    and src.get('type') == 'journal':
                roles.append({'year': y, 'author_position': mine[0].get('author_position'),
                              'is_corresponding': mine[0].get('is_corresponding'), 'source': src,
                              'cited_by_count': w.get('cited_by_count'), 'source_id': src.get('id')})
        rep.update({'new_papers': len(new), 'new_lead_works': len(roles), 'not_added': dict(why)})
        if not new and not a.refresh_topics:
            continue

        # 3. topics
        allw = {**current, **new}
        rows = [{'work_id': wid, 'year': w['publication_year'], 'doi': w.get('doi') or '', 'title': w.get('title') or ''}
                for wid, w in allw.items()]
        oa_compacted = {wid: oa_compact(w) for wid, w in allw.items()}
        args = SimpleNamespace(min_shared=2, resolution=1.05, seed=4, fetched_at=str(date.today()))
        seeds, alluvial, stats = build_one(prof, rows, oa_compacted, args)
        seeds_by = {w['id']: w for w in seeds['works']}
        spans = alluvial.get('era_span')
        papers, private, texts, refs, owners = [], [], [], [], []
        for paper in sorted(alluvial['papers'], key=lambda x: (x.get('year') or 0)):
            papers.append({'year': paper['year'], 'topic': paper['topic'], 'era': paper.get('era'), 'cited': paper.get('cited', 0)})
            private.append({'year': paper['year'], 'topic': paper['topic'], 'title': paper['title'],
                            'venue': paper.get('venue') or None, 'doi': normalise_doi(paper.get('doi'))})
            texts.append(text_of(seeds_by.get(paper['id'], {'title': paper['title']})))
            refs.append(seeds_by.get(paper['id'], {}).get('referenced_works') or [])
            owners.append(paper['topic'])
        exclude = frozenset(n.lower() for w in allw.values() for x in w.get('authorships') or []
                            for n in ((x.get('raw_author_name') or ''), ((x.get('author') or {}).get('display_name') or ''))
                            if n.strip())
        docs, members = defaultdict(list), defaultdict(list)
        for row, tid in enumerate(owners):
            docs[tid].append(texts[row])
            members[tid].append(row)
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
                 'eras': [{'label': e.get('label'), 'start': e.get('start'), 'end': e.get('end')} for e in spans],
                 'topics': topics, 'papers': papers, 'recip': [],
                 'counts': {'source_works': None, 'kept_works': len(papers), 'merged_versions': None},
                 'fetched_at': alluvial['fetched_at']}
        info = analyse([x['year'] for x in papers], [x['topic'] for x in papers], refs, width=3, n_null=200, n_boot=200,
                       seed=stable_seed(pid))
        compact_researcher(entry)
        pos = next((k for k, r in enumerate(index['researchers']) if r['id'] == pid), None)
        if pos is None:
            index['researchers'].append(entry)
        else:
            index['researchers'][pos] = entry
        rep['topic_papers_after'] = len(papers)
        rep['topics_after'] = stats['topics']
        pending[pid] = (info, private)      # written together with index.json at the end

        if not new:          # --refresh-topics only (e.g. after a career patch changed the eras)
            continue

        # 4. lead output
        srcs = oa.sources([r['source_id'] for r in roles])
        for r in roles:
            v = ((srcs.get(r['source_id']) or {}).get('summary_stats') or {}).get('2yr_mean_citedness')
            r['impact'] = float(v) if v is not None else None
        before = prof.get('lead_work_count', 0)
        add_lead_works(prof, roles, a.year)
        rep['lead_work_count'] = [before, prof.get('lead_work_count', 0)]

        # 5. research areas
        add_areas(areas, pid, list(new.values()))

    added_papers = sum(r.get('new_papers', 0) for r in report['researchers'].values())
    added_lead = sum(r.get('new_lead_works', 0) for r in report['researchers'].values())
    report['openalex_calls'] = oa.calls
    print(json.dumps(report, ensure_ascii=False, indent=1))
    if a.dry_run:
        return
    if not added_papers:
        if a.refresh_topics:
            flush()
            (topics_dir / 'index.json').write_text(json.dumps(index, ensure_ascii=False, separators=(',', ':')))
            print('topics refreshed for the listed researchers')
        else:
            print('nothing to add (already published); no file written')
        return

    patch = {'date': str(date.today()), 'researchers': sum(1 for r in report['researchers'].values() if r.get('new_papers')),
             'papers_added': added_papers, 'lead_works_added': added_lead,
             'rule': 'externally verified works (Google Scholar profile / mapping review) added work by work; '
                     'same selection, identity-year and lead rules as the full build'}
    dashboard['meta']['lead_work_count'] = sum(x['lead_work_count'] for x in dashboard['professors'])
    dashboard['meta']['manual_verified_patch'] = patch
    text = json.dumps(dashboard, ensure_ascii=False, separators=(',', ':'))
    for path in (release / 'dashboard.json', ROOT / 'public' / 'data' / 'dashboard.json'):
        path.write_text(text)
    index.setdefault('method', {})['manual_patch'] = (f"{patch['date']}: {added_papers} verified papers added for "
                                                     f"{patch['researchers']} researchers; topic vectors folded into the shared space")
    flush()
    (topics_dir / 'index.json').write_text(json.dumps(index, ensure_ascii=False, separators=(',', ':')))
    (ROOT / 'public' / 'data' / 'research_areas.json').write_text(json.dumps(areas, ensure_ascii=False, separators=(',', ':')))

    db = release / f'professor_dashboard_{a.year}.sqlite'
    con = sqlite3.connect(db)
    for pid in report['researchers']:
        x = profs[pid]
        con.execute('UPDATE professors SET lead_work_count=? WHERE professor_id=?', (x['lead_work_count'], pid))
        con.execute('DELETE FROM yearly_lead_output WHERE professor_id=?', (pid,))
        con.executemany('INSERT INTO yearly_lead_output VALUES (?,?,?,?,?,?,?,?,?,?,?,?)', [
            (pid, y['year'], y['stage'], y['total'], y['first_author'], y['corresponding_author'], y['impact_low'],
             y['impact_medium'], y['impact_high'], y['impact_unknown'], y['mean_journal_2yr_citedness'], y['article_citations'])
            for y in x['yearly']])
        con.execute('DELETE FROM professor_journal_output WHERE professor_id=?', (pid,))
        con.executemany('INSERT INTO professor_journal_output (professor_id,journal,lead_work_count,openalex_2yr_mean_citedness) '
                        'VALUES (?,?,?,?)', [(pid, j['journal'], j['lead_work_count'], j['openalex_2yr_mean_citedness'])
                                             for j in x['journals']])
    con.execute("UPDATE release_metadata SET value=? WHERE key='lead_work_count'", (str(dashboard['meta']['lead_work_count']),))
    con.execute("INSERT OR REPLACE INTO release_metadata VALUES ('manual_verified_patch', ?)", (json.dumps(patch, ensure_ascii=False),))
    con.commit()
    con.execute('VACUUM')
    integrity = con.execute('PRAGMA integrity_check').fetchone()[0]
    con.close()
    manifest = json.loads((release / 'manifest.json').read_text())
    manifest.update({'lead_work_count': dashboard['meta']['lead_work_count'], 'manual_verified_patch': patch,
                     'public_db_bytes': db.stat().st_size, 'sqlite_integrity': integrity})
    mtext = json.dumps(manifest, ensure_ascii=False, indent=2)
    for path in (release / 'manifest.json', ROOT / 'public' / 'data' / 'manifest.json'):
        path.write_text(mtext)
    (ROOT / 'public' / 'downloads' / db.name).write_bytes(db.read_bytes())
    rebind_constellation(ROOT, patch)
    print(f'patched: {added_papers} papers, {added_lead} lead works; lead_work_count {dashboard["meta"]["lead_work_count"]:,}')


if __name__ == '__main__':
    main()
