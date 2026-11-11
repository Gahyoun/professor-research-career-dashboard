"""Final guards on verify.py output -> verified spec (auto) + review list.
  * volume: additions inside non-faculty segments averaging > 6 per year -> review (a senior namesake's output)
  * medical subfields (Cancer Research, Oncology, Pharmacology, Toxicology, Clinical Biochemistry, Drug
    Discovery, Pharmaceutical Science) need >= 15% of the researcher's published works in that subfield."""
import json, sys, gzip
from collections import Counter, defaultdict
S = sys.argv[1]; A = S + '/audit'; G = S + '/global'
MEDSUB = {'Cancer Research', 'Oncology', 'Pharmacology', 'Toxicology', 'Clinical Biochemistry', 'Drug Discovery', 'Pharmaceutical Science'}
MEDFIELD = {'Medicine', 'Nursing', 'Health Professions', 'Dentistry', 'Pharmacology, Toxicology and Pharmaceutics'}
dash = {p['id']: p for p in json.load(open('public/data/dashboard.json'))['professors']}
cache = {}
for l in open(A + '/oa_cache.jsonl'):
    d = json.loads(l)
    if d['w']: cache[d['w']['id'].rsplit('/', 1)[-1]] = d['w']
acc = [json.loads(l) for l in open(A + '/accepted.jsonl')]
need = {a['pid'] for a in acc}
pubdoi = defaultdict(set)
for l in open(G + '/papers.jsonl'):
    d = json.loads(l)
    if d['pid'] in need and d.get('doi'): pubdoi[d['pid']].add(d['doi'].lower())
want = {x for v in pubdoi.values() for x in v}; pubsub = defaultdict(Counter)
with gzip.open(G + '/works.jsonl.gz', 'rt') as f:
    for l in f:
        w = json.loads(l); d = (w.get('doi') or '').lower()
        if d in want:
            for pid in [p for p in need if d in pubdoi[p]]:
                pubsub[pid][((w.get('primary_topic') or {}).get('subfield') or {}).get('display_name')] += 1
sub = lambda wid: ((cache[wid].get('primary_topic') or {}).get('subfield') or {}).get('display_name')
specs, review, why = [], [], Counter()
for a in acc:
    p = dash[a['pid']]; auto = list(a['works']); rev = [dict(w, why='coherence') for w in a['review']]
    tot = sum(pubsub[a['pid']].values())
    keep = []
    for w in auto:
        s = sub(w['work_id'])
        fld = ((cache[w['work_id']].get('primary_topic') or {}).get('field') or {}).get('display_name')
        if fld in MEDFIELD:
            rev.append(dict(w, why='medical_field')); why['medical_field'] += 1
        elif s in MEDSUB and pubsub[a['pid']][s] < max(2, 0.15 * tot):
            rev.append(dict(w, why='medical_subfield')); why['medical_subfield'] += 1
        else: keep.append(w)
    auto = keep
    nonfac = [c for c in p['career'] if c['stage'] != 'faculty' and c.get('start_year')]
    inseg = [w for w in auto if any(c['start_year'] <= w['year'] <= (c.get('end_year') or 2026) for c in nonfac)]
    if inseg:
        years = max(1, max(w['year'] for w in inseg) - min(w['year'] for w in inseg) + 1)
        if len(inseg) / years > 6:
            rev += [dict(w, why='volume') for w in auto]; why['volume_researchers'] += 1; auto = []
    if rev: review.append({'pid': a['pid'], 'works': rev})
    if auto:
        specs.append({'professor_uid': a['pid'], 'source': {'kind': 'crossref_openalex_career_match', 'checked': '2026-11-05',
                      'note': 'Low-count audit: Crossref name candidates verified on OpenAlex (strict Korean-name romanization match, allowed field, career institution x period or >=2 shared coauthors, coherent with published works / pre-faculty evidence; medical affiliations excluded)'},
                      'works': [{'work_id': w['work_id'], 'author_id': w['author_id'], 'raw_author_name': w.get('raw_author_name'),
                                 'note': f"{w['year']} {', '.join(w['institutions'][:2]) or 'no affiliation; coauthors shared'}"} for w in auto]})
json.dump(specs, open(A + '/verified_audit.json', 'w'), ensure_ascii=False)
json.dump({s['professor_uid']: s['professor_uid'] for s in specs}, open(A + '/anon_audit.json', 'w'))
json.dump(review, open(A + '/review_audit.json', 'w'), ensure_ascii=False)
print(json.dumps({'researchers': len(specs), 'works': sum(len(s['works']) for s in specs),
                  'review_researchers': len(review), 'review_works': sum(len(r['works']) for r in review), **why}))
