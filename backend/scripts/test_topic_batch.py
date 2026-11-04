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
                              'publication_year': year, 'publication_date': f'{year}-0{1 + k % 9}-15', 'cited_by_count': k, 'referenced_works': [f'https://openalex.org/{r}' for r in refs],
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

            def text_reply(prompt):
                self.assertNotIn('uid-', prompt)
                self.assertNotIn(a, prompt)
                self.assertNotIn('Univ', prompt)
                self.assertIn('Papers per year: ', prompt)
                self.assertRegex(prompt, r'published \d{4}-\d{2}-\d{2} – \d{4}-\d{2}-\d{2}')
                if 'kuramoto' in prompt.lower():  # copies a title verbatim → must be rejected
                    title = next(l for l in prompt.splitlines() if l.startswith('1. ')).split(' — ')[1]
                    return {'summary_en': f'This cluster is {title} again', 'summary_ko': '동기화 연구'}
                return {'summary_en': 'Studies of collective behaviour in disordered systems, growing after 2004.', 'summary_ko': '무질서계의 집단 거동 연구.'}

            calls = {'n': 0}

            def runner(prompt):
                calls['n'] += 1
                if calls['n'] <= 2:  # first wave hits a usage limit: whole wave retried, no attempt spent
                    return {'status': 'retry', 'detail': 'usage limit'}
                return {'status': 'ok', **{k[8:]: v for k, v in text_reply(prompt).items()}, 'cost': 0.01}
            args.cli_workers, args.backoff = 1, 0
            tb.step_summarize(paths, args, runner=runner)
            statuses = dict(con.execute('SELECT status, COUNT(*) FROM summaries GROUP BY status').fetchall())
            self.assertGreater(statuses.get('ok', 0), 0)
            self.assertGreater(statuses.get('rejected_title_overlap', 0), 0)
            self.assertEqual(sum(statuses.values()), 5)
            before = calls['n']
            tb.step_summarize(paths, args, runner=runner)  # nothing pending on rerun
            self.assertEqual(before, calls['n'])

            # The Batches API engine stores the same rows; force it by clearing summaries.
            with con:
                con.execute('DELETE FROM summaries')
            args.engine = 'api'
            client = SimpleNamespace(messages=SimpleNamespace(batches=FakeBatches(lambda r: text_reply(r['params']['messages'][0]['content']))))
            tb.step_summarize(paths, args, client=client)
            self.assertEqual(dict(con.execute('SELECT status, COUNT(*) FROM summaries GROUP BY status').fetchall()), statuses)

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

    def test_corpus_flow(self):
        """works → fetch → cluster → corpus; Claude Code reads chunks and submits; export publishes."""
        import contextlib
        import io
        import re
        import topic_corpus as tc
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            src, works, a, b = make_world(root)
            common = ['--project-root', tmp, '--source-db', str(src), '--anon-salt', str(root / 'salt.bin'),
                      '--dashboard', str(root / 'dashboard.json'), '--topics-db', str(root / 'topics.sqlite'),
                      '--cache-db', str(root / 'cache.sqlite'), '--out-dir', str(root / 'out'), '--null', '10', '--chunk-size', '2']
            args = tb.parser().parse_args(['all'] + common)
            paths = tb.Paths(args)
            tb.step_works(paths)
            tb.step_fetch(paths, fetcher=lambda ids: (ids, {i: tb.compact_work(works[i]) for i in ids}))
            tb.step_cluster(paths, args)
            tb.step_corpus(paths, args)

            def run(*argv, stdin=None):
                out = io.StringIO()
                old = sys.stdin
                if stdin is not None:
                    sys.stdin = io.StringIO(stdin)
                code = 0
                try:
                    with contextlib.redirect_stdout(out):
                        tc.main(list(argv) + ['--topics-db', str(root / 'topics.sqlite')])
                except SystemExit as e:
                    code = e.code or 0
                finally:
                    sys.stdin = old
                return code, out.getvalue()

            code, status = run('status')
            self.assertIn('5 topics, 0 done, 5 pending in 3 chunks', status)
            self.assertIn('Do not quote', run('rules')[1])
            _, chunk0 = run('next', '--chunk', '0')
            ids = re.findall(r'^## id: (\w+)$', chunk0, re.M)
            self.assertEqual(len(ids), 2)
            self.assertNotIn(a, chunk0)
            self.assertNotIn('Univ', chunk0)
            self.assertIn('Papers per year:', chunk0)
            second = chunk0.split(f'## id: {ids[1]}')[1]
            title = re.search(r'^1\. \S+ — (.+?) — ', second, re.M).group(1)
            lines = [json.dumps({'id': ids[0], 'en': 'Collective behaviour studied since 2000.', 'ko': '2000년부터 집단 거동을 다룬다.'}),
                     json.dumps({'id': ids[1], 'en': f'It repeats {title} verbatim.', 'ko': '제목 반복.'}),
                     json.dumps({'id': 'nope', 'en': 'x', 'ko': 'y'})]
            code, out = run('submit', '-', stdin='\n'.join(lines))
            self.assertEqual(code, 1)
            self.assertIn('ok 1, rejected_title_overlap 1', out)
            self.assertIn("unknown id 'nope'", out)
            _, again = run('next', '--chunk', '0')
            self.assertEqual(re.findall(r'^## id: (\w+)$', again, re.M), [ids[1]])  # only the rejected one remains
            code, out = run('submit', '-', stdin=json.dumps({'id': ids[1], 'en': 'Rewritten summary.', 'ko': '다시 쓴 요약.'}))
            self.assertEqual(code, 0)
            self.assertIn('pending topics left: 3', out)
            tb.step_corpus(paths, args)  # rebuilding leaves out summarized topics
            self.assertIn('3 topics, 0 done, 3 pending', run('status')[1])
            tb.step_export(paths, args)
            summaries = [json.loads((root / 'out' / 'detail' / f'{x}.json').read_text())['summaries'] for x in (a, b)]
            self.assertEqual(sum(len(x) for x in summaries), 2)
            index = json.loads((root / 'out' / 'index.json').read_text())
            self.assertIn('claude-code', index['method']['summaries'])

    def test_repeats_title(self):
        title = 'Synchronization of phase oscillators on scale-free networks'
        self.assertFalse(tb.repeats_title('Starting with oscillators on scale-free networks, it moved to power grids.', [title]))
        self.assertTrue(tb.repeats_title(f'This cluster revisits {title.lower()} in detail.', [title]))
        long_title = 'A unified view of replica symmetry breaking in finite dimensional spin glass models'
        self.assertTrue(tb.repeats_title('It builds a unified view of replica symmetry breaking in finite dimensional systems.', [long_title]))
        self.assertFalse(tb.repeats_title('Explosive synchronization recurs.', ['Explosive synchronization']))

if __name__ == '__main__':
    unittest.main()
