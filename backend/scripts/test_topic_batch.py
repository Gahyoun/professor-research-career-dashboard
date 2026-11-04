"""End-to-end test of backend/topics/topic_batch.py on synthetic private data (no network)."""
import base64
import json
import random
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'topics'))
import topic_batch as tb  # noqa: E402

SALT = b's' * 32
POOLS = {
    'spin': 'spin glass replica symmetry breaking frustrated magnets',
    'epi': 'epidemic spreading contact networks outbreak threshold',
    'sync': 'kuramoto oscillators synchronization transition coupled phase',
}


def make_world(root):
    """Two researchers: A with three coupled themes plus isolated papers, B with one theme; one namesake work."""
    rnd = random.Random(7)
    src = root / 'source.sqlite'
    con = sqlite3.connect(src)
    con.executescript('''
      CREATE TABLE professors(professor_uid TEXT PRIMARY KEY, phd_year INTEGER);
      CREATE TABLE work_authorship_evidence(professor_uid TEXT, work_id TEXT, publication_year INTEGER, identity_decision TEXT);
    ''')
    koad = sqlite3.connect(root / 'identity_decisions.sqlite')
    koad.execute('CREATE TABLE work_decision(professor_uid TEXT, work_id TEXT, decision TEXT)')
    works, n = {}, 0
    plan = {'uid-a': [('spin', 2000, 8), ('epi', 2006, 9), ('sync', 2012, 7), (None, 2010, 2)], 'uid-b': [('sync', 2015, 6)]}
    for uid, themes in plan.items():
        con.execute('INSERT INTO professors VALUES (?,?)', (uid, 1998))
        for theme, start, count in themes:
            for k in range(count):
                n += 1
                wid = f'W{n}'
                year = start + k // 2
                refs = [f'R-{theme}-{rnd.randrange(12)}' for _ in range(8)] if theme else []
                text = POOLS.get(theme, 'unrelated note')
                works[wid] = {'id': f'https://openalex.org/{wid}', 'doi': f'10.1/{wid}', 'title': f'Paper {wid} on {text.split()[0]} {text.split()[1]}',
                              'publication_year': year, 'cited_by_count': k, 'referenced_works': [f'https://openalex.org/{r}' for r in refs],
                              'primary_location': {'source': {'display_name': 'Journal X'}}, 'topics': [], 'keywords': [],
                              'abstract_inverted_index': {w: [i] for i, w in enumerate(text.split())}, 'type': 'article'}
                con.execute('INSERT INTO work_authorship_evidence VALUES (?,?,?,?)', (uid, wid, year, 'keep'))
    # A namesake work and a pre-PhD work must both be dropped.
    con.execute("INSERT INTO work_authorship_evidence VALUES ('uid-a','W900',2011,'keep')")
    koad.execute("INSERT INTO work_decision VALUES ('uid-a','W900','namesake_paper')")
    con.execute("INSERT INTO work_authorship_evidence VALUES ('uid-a','W901',1980,'keep')")
    con.commit(), koad.commit()
    con.close(), koad.close()
    (root / 'salt.bin').write_bytes(SALT)
    a, b = tb.anon_id(SALT, 'uid-a'), tb.anon_id(SALT, 'uid-b')
    career = [{'stage': 'doctoral', 'institution': 'Univ X', 'start_year': 1993, 'end_year': 1998},
              {'stage': 'faculty', 'institution': 'Univ Y', 'start_year': 2005, 'end_year': None}]
    dashboard = {'meta': {'release_year': 2026, 'identity_filter_version': 'KOAD test'}, 'professors': [
        {'id': a, 'subject': 'physics', 'current_institution': 'Univ Y', 'career': career},
        {'id': b, 'subject': 'physics', 'current_institution': 'Univ Z', 'career': []}]}
    (root / 'dashboard.json').write_text(json.dumps(dashboard))
    return src, works, a, b


class FakeBatches:
    def __init__(self, reply):
        self.reply, self.store = reply, {}

    def create(self, requests):
        bid = f'msgbatch_{len(self.store)}'
        self.store[bid] = requests
        return SimpleNamespace(id=bid, processing_status='in_progress')

    def retrieve(self, bid):
        return SimpleNamespace(id=bid, processing_status='ended')

    def results(self, bid):
        for r in self.store[bid]:
            text = json.dumps(self.reply(r))
            msg = SimpleNamespace(stop_reason='end_turn', content=[SimpleNamespace(type='text', text=text)])
            yield SimpleNamespace(custom_id=r['custom_id'], result=SimpleNamespace(type='succeeded', message=msg))


class TopicBatchTest(unittest.TestCase):
    def test_pipeline(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            src, works, a, b = make_world(root)
            args = tb.parser().parse_args(['all', '--year', '2026', '--project-root', tmp, '--source-db', str(src),
                                           '--anon-salt', str(root / 'salt.bin'), '--dashboard', str(root / 'dashboard.json'),
                                           '--topics-db', str(root / 'topics.sqlite'), '--cache-db', str(root / 'cache.sqlite'),
                                           '--out-dir', str(root / 'out'), '--null', '20', '--poll', '0'])
            paths = tb.Paths(args)
            tb.step_works(paths)
            con = sqlite3.connect(paths.topics_db)
            kept = {r[0] for r in con.execute('SELECT work_id FROM researcher_works')}
            self.assertNotIn('W900', kept)  # KOAD namesake
            self.assertNotIn('W901', kept)  # before phd_year-5
            self.assertEqual(len(kept), len(works))

            calls = []

            def fetcher(ids):
                calls.append(len(ids))
                return ids, {i: tb.compact_work(works[i]) for i in ids if i in works}
            tb.step_fetch(paths, fetcher=fetcher, workers=2, group=10)
            tb.step_fetch(paths, fetcher=fetcher, workers=2, group=10)  # resumable: nothing left
            self.assertEqual(sum(calls), len(works))

            tb.step_cluster(paths, args)
            topics = con.execute('SELECT anon_id, label, size, is_misc, members_hash FROM topics ORDER BY anon_id, topic_id').fetchall()
            a_topics = [t for t in topics if t[0] == a]
            self.assertEqual(sum(t[3] for t in a_topics), 1, 'isolated papers pooled into one Other topic')
            self.assertTrue(any(t[1].startswith('Other') for t in a_topics))
            self.assertGreaterEqual(len([t for t in a_topics if not t[3]]), 3)
            first = con.execute('SELECT input_hash FROM researcher_runs').fetchall()
            tb.step_cluster(paths, args)  # unchanged input → skipped, same hash
            self.assertEqual(first, con.execute('SELECT input_hash FROM researcher_runs').fetchall())

            def reply(request):
                prompt = request['params']['messages'][0]['content']
                self.assertNotIn('uid-', prompt)
                self.assertNotIn(a, prompt)
                self.assertNotIn('Univ', prompt)
                if 'kuramoto' in prompt.lower():  # copies a title verbatim → must be rejected
                    title = next(l for l in prompt.splitlines() if l.startswith('1. ')).split(' — ')[0][3:]
                    return {'summary_en': f'This cluster is {title} again', 'summary_ko': '동기화 연구'}
                return {'summary_en': 'Studies of collective behaviour in disordered systems.', 'summary_ko': '무질서계의 집단 거동 연구.'}
            client = SimpleNamespace(messages=SimpleNamespace(batches=FakeBatches(reply)))
            tb.step_summarize(paths, args, client=client)
            statuses = dict(con.execute('SELECT status, COUNT(*) FROM summaries GROUP BY status').fetchall())
            self.assertGreater(statuses.get('ok', 0), 0)
            self.assertGreater(statuses.get('rejected_title_overlap', 0), 0)
            submitted = sum(len(v) for v in client.messages.batches.store.values())
            tb.step_summarize(paths, args, client=client)  # nothing pending on rerun
            self.assertEqual(submitted, sum(len(v) for v in client.messages.batches.store.values()))

            import os
            os.environ['TEST_TOPIC_PW'] = 'pw'
            args.password_env = 'TEST_TOPIC_PW'
            tb.step_export(paths, args)
            out = root / 'out'
            index = json.loads((out / 'index.json').read_text())
            self.assertEqual(index['schema'], tb.SCHEMA)
            self.assertEqual({r['id'] for r in index['researchers']}, {a, b})
            text = (out / 'index.json').read_text()
            for word in ('"title"', '"doi"', 'uid-', 'W1"'):
                self.assertNotIn(word, text)
            ra = next(r for r in index['researchers'] if r['id'] == a)
            self.assertEqual(sum(c[3] for c in ra['paper_cells']), ra['counts']['kept_works'])
            self.assertEqual(len(base64.b64decode(ra['topics'][0]['vector_b64'])), index['semantic']['dims'])
            self.assertIn('Univ Y 교원 (2005-)', [e['label'] for e in ra['eras']])
            detail = json.loads((out / 'detail' / f'{a}.json').read_text())
            self.assertTrue(detail['summaries'])
            self.assertIsNotNone(detail['info'])
            key = json.loads((out / 'titles' / 'key.json').read_text())
            shard = json.loads((out / 'titles' / f'{a}.json').read_text())
            import hashlib
            from cryptography.hazmat.primitives.ciphers.aead import AESGCM
            k = hashlib.pbkdf2_hmac('sha256', b'pw', base64.b64decode(key['salt']), key['iterations'], 32)
            rows = json.loads(AESGCM(k).decrypt(base64.b64decode(shard['nonce']), base64.b64decode(shard['ciphertext']), base64.b64decode(key['aad'])))
            self.assertEqual(len(rows), ra['counts']['kept_works'])
            self.assertTrue(all(r['doi'].startswith('https://doi.org/') for r in rows))
            con.close()

    def test_repeats_title(self):
        self.assertTrue(tb.repeats_title('We revisit the spin glass replica symmetry breaking picture', ['Spin glass replica symmetry breaking in 3D']))
        self.assertFalse(tb.repeats_title('Replica methods for spin glasses', ['Spin glass replica symmetry breaking in 3D']))


if __name__ == '__main__':
    unittest.main()
