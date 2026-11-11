"""Verify harvested candidates with OpenAlex records and the release acceptance rules.
accept a candidate work for researcher P when ALL hold:
  * journal type (article / review / letter), year within [phd_year-5, 2026];
  * exactly one authorship whose raw name matches P's Korean name (strict romanization matcher)
    or a raw name on P's published works;
  * the work's primary field is in P's allowed fields: subject home fields plus fields holding
    >= 15% (and >= 2) of P's published works;
  * EITHER the authorship institution is a career institution within that segment +-1 year
    (the current faculty institution counts from the end of the last pre-faculty segment, since
    rosters only observe recent years), OR the authorship has no institution and shares >= 2
    coauthor IDs with P's published works.
Output: accepted.jsonl / rejected reasons summary."""
import base64, gzip, hashlib, json, os, re, sys, time, urllib.parse, urllib.request
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
S = sys.argv[1]; A = S + '/audit'; G = S + '/global'
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); import romanize as R
sys.path.insert(0, 'backend/scripts'); from career_consistency import norm_institution as NI
KEY = os.environ['OPENALEX_API_KEY']
e = json.load(open('public/data/encrypted_names.json')); b = base64.b64decode
k = hashlib.pbkdf2_hmac('sha256', os.environ['NAMES_PASSWORD'].encode(), b(e['salt']), int(e['iterations']), 32)
names = json.loads(AESGCM(k).decrypt(b(e['nonce']), b(e['ciphertext']), b(e['aad'])))
HOME = {'physics': {'Physics and Astronomy'}, 'chemistry': {'Chemistry'}, 'mathematics': {'Mathematics'},
        'biology': {'Biochemistry, Genetics and Molecular Biology', 'Agricultural and Biological Sciences', 'Immunology and Microbiology', 'Neuroscience'}}
TYPES = {'article', 'review', 'letter'}
MED = re.compile(r'(?i)hospital|medical cent|college of medicine|school of medicine|cancer cent|clinic|health system|medical school')
dash = {p['id']: p for p in json.load(open('public/data/dashboard.json'))['professors']}
tri = {json.loads(l)['pid']: json.loads(l) for l in open(A + '/triage.jsonl')}
cands = [json.loads(l) for l in open(A + '/cands.jsonl')]
need = {c['pid'] for c in cands}
pubdoi = defaultdict(set)
for l in open(G + '/papers.jsonl'):
    d = json.loads(l)
    if d['pid'] in need and d.get('doi'): pubdoi[d['pid']].add(d['doi'].lower())
want = {x for v in pubdoi.values() for x in v}
pubw = {}
with gzip.open(G + '/works.jsonl.gz', 'rt') as f:
    for l in f:
        w = json.loads(l); d = (w.get('doi') or '').lower()
        if d in want: pubw[d] = w
cache_p = A + '/oa_cache.jsonl'
cache = {}
if os.path.exists(cache_p):
    for l in open(cache_p):
        d = json.loads(l); cache[d['doi']] = d['w']
def fetch(doi):
    if doi in cache: return doi, cache[doi]
    for t in range(6):
        try:
            with urllib.request.urlopen(f'https://api.openalex.org/works/doi:{urllib.parse.quote(doi)}?api_key={KEY}', timeout=60) as r:
                return doi, json.load(r)
        except urllib.error.HTTPError as x:
            if x.code == 404: return doi, None
            time.sleep(2 ** t)
        except Exception: time.sleep(2 ** t)
    return doi, 'ERR'
alld = sorted({c['doi'] for r in cands for c in r['cands']} - set(cache))
with open(cache_p, 'a') as fh, ThreadPoolExecutor(8) as ex:
    for i, (doi, w) in enumerate(ex.map(fetch, alld)):
        if w == 'ERR': continue
        slim = None
        if w:
            slim = {k: w.get(k) for k in ('id', 'doi', 'title', 'publication_year', 'type', 'primary_topic')}
            slim['authorships'] = [{'author': {'id': a['author'].get('id')}, 'raw_author_name': a.get('raw_author_name'),
                                    'institutions': [{'display_name': x['display_name']} for x in a.get('institutions') or []]}
                                   for a in w.get('authorships') or []]
        cache[doi] = slim; fh.write(json.dumps({'doi': doi, 'w': slim}) + '\n')
        if i % 2000 == 0: print('fetched', i, len(alld), flush=True)
short = lambda x: (x or '').rsplit('/', 1)[-1]
field = lambda w: (((w or {}).get('primary_topic') or {}).get('field') or {}).get('display_name')
acc_out = open(A + '/accepted.jsonl', 'w'); why = Counter(); per = {}
for r in cands:
    pid = r['pid']; p = dash[pid]; t = tri[pid]; nm = names.get(pid, '')
    m = R.matcher(nm) if nm else None
    raws = {R.norm(x) for x, _ in t['raw_names'] if x}
    pw = [pubw[d] for d in pubdoi[pid] if d in pubw]
    fc = Counter(field(w) for w in pw)
    allowed = HOME[p['subject']] | {f for f, n in fc.items() if f and n >= 2 and n / max(1, len(pw)) >= 0.15}
    anchors = {short(a['author'].get('id')) for w in pw for a in w['authorships']
               if a['author'].get('id') and (R.norm(a.get('raw_author_name')) in raws or (m and m.match(R.norm(a.get('raw_author_name')))))}
    coauth = {short(a['author'].get('id')) for w in pw for a in w['authorships'] if a['author'].get('id')} - anchors
    car = p['career']; phd = p.get('phd_year') or 0
    pre_end = max([c.get('end_year') or 0 for c in car if c['stage'] != 'faculty'] + [phd])
    segs = []
    for c in car:
        s, e2 = c.get('start_year'), c.get('end_year')
        if c['stage'] == 'faculty': s = min(s or 9999, pre_end); e2 = 2026 if c['institution'] == p.get('current_institution') else e2
        segs.append((NI(c['institution']), s, e2))
    segs4 = [(NI(c['institution']), c.get('start_year'), c.get('end_year'), c['stage']) for c in car]
    acc = []
    for c in r['cands']:
        w = cache.get(c['doi'])
        if not w: why['not_in_openalex'] += 1; continue
        y = w.get('publication_year') or 0
        if w.get('type') not in TYPES or y > 2026 or (phd and y < phd - 5): why['type_or_year'] += 1; continue
        mine = [a for a in w['authorships'] if (m and m.match(R.norm(a.get('raw_author_name')))) or R.norm(a.get('raw_author_name')) in raws]
        if len(mine) != 1: why['name_not_unique'] += 1; continue
        a = mine[0]
        if field(w) not in allowed: why['field'] += 1; continue
        insts = {NI(i['display_name']) for i in a['institutions']}
        ok = any(i == n and s and s - 1 <= y <= (e2 or 9999) + 1 for i in insts for n, s, e2 in segs)
        if not ok and not insts:
            shared = len({short(x['author'].get('id')) for x in w['authorships'] if x is not a and x['author'].get('id')} & coauth)
            ok = shared >= 2
            if not ok: why['no_institution_no_coauthors'] += 1; continue
        elif not ok: why['institution_or_period'] += 1; continue
        if any(MED.search(i['display_name']) for i in a['institutions']): why['medical_affiliation'] += 1; continue
        acc.append({'work_id': short(w['id']), 'author_id': short(a['author'].get('id')) or None,
                    'coauthors': sorted({short(x['author'].get('id')) for x in w['authorships'] if x is not a and x['author'].get('id')}),
                    'pre_faculty': any(i == n and s and s - 1 <= y <= (e2 or 9999) + 1 for i in insts for n, s, e2, st in segs4 if st != 'faculty'),
                    'raw_author_name': None if a['author'].get('id') else a.get('raw_author_name'),
                    'year': y, 'field': field(w), 'institutions': [i['display_name'] for i in a['institutions']]})
        why['accepted'] += 1
    # drop duplicate work ids
    seen = set(); acc = [x for x in acc if not (x['work_id'] in seen or seen.add(x['work_id']))]
    # coherence: components of accepted works linked by a shared coauthor id or the same author id
    parent = list(range(len(acc)))
    def find(i):
        while parent[i] != i: parent[i] = parent[parent[i]]; i = parent[i]
        return i
    for i in range(len(acc)):
        for j in range(i + 1, len(acc)):
            if set(acc[i]['coauthors']) & set(acc[j]['coauthors']) or (acc[i]['author_id'] and acc[i]['author_id'] == acc[j]['author_id']):
                parent[find(i)] = find(j)
    comps = defaultdict(list)
    for i in range(len(acc)): comps[find(i)].append(acc[i])
    def anchored(ws):
        return any(set(w['coauthors']) & coauth or (w['author_id'] and w['author_id'] in anchors) or w['pre_faculty'] for w in ws)
    good = [ws for ws in comps.values() if anchored(ws)]
    if not good and comps:
        big = max(comps.values(), key=len)
        if len(big) >= 2 and len(big) >= 0.8 * len(acc): good = [big]
    auto = [w for ws in good for w in ws]
    review = [w for w in acc if w not in auto]
    why['auto'] += len(auto); why['review'] += len(review)
    per[pid] = len(auto)
    if acc: acc_out.write(json.dumps({'pid': pid, 'kept': t['kept'], 'works': auto, 'review': review,
                                      'components': sorted((len(v) for v in comps.values()), reverse=True)}, ensure_ascii=False) + '\n')
print(json.dumps({'reasons': why, 'researchers_with_additions': sum(1 for v in per.values() if v),
                  'works_added': sum(per.values())}, indent=1))
print('VERIFYDONE')
