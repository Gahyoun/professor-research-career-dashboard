"""Triage of researchers with < 30 published papers (free OpenAlex singleton lookups only).
For each: published works (cache) -> anchor author id(s) -> authors/{id} (works_count, affiliations
with years, topics). Output: triage.jsonl (one row per researcher, resumable)."""
import gzip, json, os, re, sys, time, urllib.request, urllib.parse
from collections import Counter, defaultdict
S = sys.argv[1]; G = S + '/global'; A = S + '/audit'
KEY = os.environ['OPENALEX_API_KEY']
rows = json.load(open(G + '/kept_counts.json'))
dash = {p['id']: p for p in json.load(open('public/data/dashboard.json'))['professors']}
targets = [r for r in rows if r[2] < 30]
need = {r[0] for r in targets}
dois = defaultdict(list)
for l in open(G + '/papers.jsonl'):
    d = json.loads(l)
    if d['pid'] in need and d.get('doi'): dois[d['pid']].append(d['doi'].lower())
want = {x for v in dois.values() for x in v}
works = {}
with gzip.open(G + '/works.jsonl.gz', 'rt') as f:
    for l in f:
        w = json.loads(l)
        if (w.get('doi') or '').lower() in want: works[(w.get('doi') or '').lower()] = w
def get(path):
    for t in range(6):
        try:
            with urllib.request.urlopen(f'https://api.openalex.org/{path}?api_key={KEY}', timeout=60) as r: return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code == 404: return None
            time.sleep(2 ** t)
        except Exception: time.sleep(2 ** t)
    return None
out = A + '/triage.jsonl'
done = {json.loads(l)['pid'] for l in open(out)} if os.path.exists(out) else set()
fh = open(out, 'a')
for pid, subj, kept, lead in targets:
    if pid in done: continue
    p = dash[pid]
    ws = [works[d] for d in dois.get(pid, []) if d in works]
    ids = Counter(a['author']['id'].rsplit('/', 1)[-1] for w in ws for a in w['authorships'] if a['author'].get('id'))
    # anchor = author ids present in >= half of the researcher's works (or the top one)
    anchors = [a for a, c in ids.most_common(3) if c >= max(1, len(ws) / 2)] or [a for a, _ in ids.most_common(1)]
    raw = Counter(a.get('raw_author_name') for w in ws for a in w['authorships'] if (a['author'].get('id') or '').rsplit('/', 1)[-1] in anchors)
    info = []
    for a in anchors:
        r = get('authors/' + a)
        if not r: continue
        info.append({'id': a, 'name': r.get('display_name'), 'works_count': r.get('works_count'),
                     'alt': (r.get('display_name_alternatives') or [])[:8],
                     'affiliations': [(x['institution']['display_name'], min(x['years']), max(x['years'])) for x in r.get('affiliations') or []][:15],
                     'topics': [(t['display_name'], t['field']['display_name'], t['count']) for t in (r.get('topics') or [])[:6]],
                     'fields': Counter({}) and None})
    fh.write(json.dumps({'pid': pid, 'subject': subj, 'kept': kept, 'lead': lead, 'phd_year': p.get('phd_year'),
                         'institution': p.get('current_institution'),
                         'career': [(c['stage'], c['institution'], c.get('start_year'), c.get('end_year')) for c in p['career']],
                         'raw_names': raw.most_common(3), 'anchors': info}, ensure_ascii=False) + '\n'); fh.flush()
print('TRIAGEDONE')
