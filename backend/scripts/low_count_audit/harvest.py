"""Crossref candidate harvest for researchers with < 30 published papers (free API).
For each researcher: query forms = romanized Korean name variants + the raw name on published
works; keep Crossref records whose author list holds an exact name match (romanize.matcher, or
the published raw name), published from phd_year-5, not already published. Output: cands.jsonl."""
import base64, json, os, re, sys, time, urllib.parse, urllib.request
from concurrent.futures import ThreadPoolExecutor
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
import hashlib
S = sys.argv[1]; A = S + '/audit'; G = S + '/global'
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); import romanize as R
e = json.load(open('public/data/encrypted_names.json')); b = base64.b64decode
k = hashlib.pbkdf2_hmac('sha256', os.environ['NAMES_PASSWORD'].encode(), b(e['salt']), int(e['iterations']), 32)
names = json.loads(AESGCM(k).decrypt(b(e['nonce']), b(e['ciphertext']), b(e['aad'])))
tri = {}
for l in open(A + '/triage.jsonl'):
    r = json.loads(l); tri[r['pid']] = r
pub = {}
for l in open(G + '/papers.jsonl'):
    d = json.loads(l)
    if d['pid'] in tri and d.get('doi'): pub.setdefault(d['pid'], set()).add(d['doi'].lower().replace('https://doi.org/', ''))
out = A + '/cands.jsonl'
done = {json.loads(l)['pid'] for l in open(out)} if os.path.exists(out) else set()
def cr(params):
    params['mailto'] = 'research-dashboard@example.org'
    u = 'https://api.crossref.org/works?' + urllib.parse.urlencode(params)
    for t in range(5):
        try:
            with urllib.request.urlopen(u, timeout=60) as r: return json.load(r)['message']['items']
        except Exception: time.sleep(2 ** t)
    return []
def one(pid):
    r = tri[pid]; nm = names.get(pid) or ''
    m = R.matcher(nm) if nm else None
    raws = {R.norm(x) for x, _ in r['raw_names'] if x}
    forms = set(R.variants(nm)) if nm else set()
    for x, _ in r['raw_names'][:1]:
        if x and len(R.norm(x)) > 4: forms.add(x)
    start = (r['phd_year'] or 1990) - 5
    got = {}
    for f in sorted(forms):
        for off in (0, 200):
            items = cr({'query.author': f, 'filter': f'from-pub-date:{start}', 'rows': 200, 'offset': off,
                        'select': 'DOI,author,issued,container-title,type'})
            for it in items:
                hit = [a for a in it.get('author', []) if (m and m.match(R.norm(a.get('given', '') + a.get('family', ''))))
                       or R.norm(a.get('given', '') + ' ' + a.get('family', '')) in raws]
                doi = it['DOI'].lower()
                if hit and doi not in pub.get(pid, set()):
                    got[doi] = {'doi': doi, 'type': it.get('type'), 'year': ((it.get('issued') or {}).get('date-parts') or [[None]])[0][0],
                                'names': [a.get('given', '') + ' ' + a.get('family', '') for a in hit][:2]}
            if len(items) < 200: break
    return {'pid': pid, 'name_forms': sorted(forms), 'cands': list(got.values())}
todo = [p for p in tri if p not in done]
with open(out, 'a') as fh, ThreadPoolExecutor(4) as ex:
    for res in ex.map(one, todo):
        fh.write(json.dumps(res, ensure_ascii=False) + '\n'); fh.flush()
print('HARVESTDONE')
