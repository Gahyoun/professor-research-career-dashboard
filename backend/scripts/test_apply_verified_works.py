import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from apply_verified_works import apply
from release_identity import PublicationIdentityGate
from test_augment_openalex_evidence import create_source, synthetic_work


class ApplyVerifiedWorksTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        root = self.root = Path(self.folder.name)
        self.source = root / 'source.sqlite'
        create_source(self.source)
        with sqlite3.connect(self.source) as c:   # an existing own paper wrongly dropped as a namesake
            c.execute("UPDATE work_authorship_evidence SET identity_decision='namesake_paper' WHERE work_id='W3000'")
        self.decisions = root / 'identity_decisions.sqlite'
        with sqlite3.connect(self.decisions) as c:
            c.execute('CREATE TABLE work_decision(professor_uid TEXT NOT NULL, work_id TEXT NOT NULL, decision TEXT NOT NULL, '
                      'classifier TEXT)')
            c.executemany('INSERT INTO work_decision VALUES(?,?,?,?)', [
                ('synthetic-one', 'W3000', 'namesake_paper', 'koad'),
                ('synthetic-two', 'W3000', 'namesake_paper', 'koad')])
        self.before = (self.source.read_bytes(), self.decisions.read_bytes())
        self.verified = root / 'verified.json'
        self.verified.write_text(json.dumps({
            'professor_uid': 'synthetic-one',
            'source': {'kind': 'google_scholar_profile', 'url': 'https://scholar.example/x', 'checked': '2026-11-05'},
            'works': [{'work_id': 'W3000', 'author_id': 'A1001'},
                      {'work_id': 'https://openalex.org/W3001', 'author_id': 'A1002'},
                      {'work_id': 'W3009', 'author_id': None}]}))
        self.works = root / 'works.jsonl'
        self.works.write_text(json.dumps({'professor_uid': 'synthetic-one', 'target_author_id': 'A1002',
                                          'work': synthetic_work('W3001')}) + '\n')

    def test_listed_pairs_become_public_and_nothing_else_changes(self):
        out = self.root / 'out'
        report = apply(self.source, self.decisions, self.verified, self.works, out)
        self.assertEqual((self.source.read_bytes(), self.decisions.read_bytes()), self.before)   # inputs untouched
        self.assertEqual(report['no_author_id'], ['W3009'])
        self.assertEqual(report['imported']['verified_new_works'], 1)
        self.assertEqual(report['evidence_set_keep'], 1)
        self.assertEqual((report['decisions_set_true_paper'], report['decisions_inserted']), (1, 1))
        with sqlite3.connect(out / 'web.sqlite') as c:
            self.assertEqual(dict(c.execute("SELECT work_id,identity_decision FROM work_authorship_evidence WHERE professor_uid='synthetic-one'")),
                             {'W3000': 'keep', 'W3001': 'keep'})
            self.assertEqual(c.execute('SELECT previous_value,new_value FROM manual_work_verification_audit').fetchall(),
                             [('namesake_paper', 'keep')])
        with sqlite3.connect(out / 'identity_decisions.sqlite') as c:
            rows = {(u, w): d for u, w, d, _ in c.execute('SELECT * FROM work_decision')}
            self.assertEqual(rows[('synthetic-one', 'W3000')], 'true_paper')
            self.assertEqual(rows[('synthetic-one', 'W3001')], 'true_paper')
            self.assertEqual(rows[('synthetic-two', 'W3000')], 'namesake_paper')   # the other person is not touched
            self.assertEqual(c.execute('SELECT count(*) FROM manual_work_verification_audit').fetchone()[0], 2)
        with sqlite3.connect(out / 'web.sqlite') as c:   # the release gate now lets both pairs through
            c.execute('ATTACH DATABASE ? AS koad', (str(out / 'identity_decisions.sqlite'),))
            gate = PublicationIdentityGate.from_connection(c)
            self.assertIsNone(gate.exclusion_reason('synthetic-one', 'W3000'))
            self.assertIsNone(gate.exclusion_reason('synthetic-one', 'W3001'))
            self.assertEqual(gate.exclusion_reason('synthetic-two', 'W3000'), 'namesake_paper')

    def test_rerun_on_its_own_output_is_a_no_op(self):
        first = self.root / 'first'
        apply(self.source, self.decisions, self.verified, self.works, first)
        second = apply(first / 'web.sqlite', first / 'identity_decisions.sqlite', self.verified, self.works, self.root / 'second')
        self.assertEqual((second['evidence_set_keep'], second['decisions_set_true_paper'], second['decisions_inserted']), (0, 0, 0))
        self.assertEqual(second['already_in_place'], 2)

    def test_fetches_packets_when_no_file_is_given(self):
        import apply_verified_works as avw
        calls = []

        def fake_fetch(uid, need, out_path, key, base=None):
            calls.append([w['work_id'] for w in need])
            out_path.parent.mkdir(parents=True, exist_ok=True)
            import gzip
            with gzip.open(out_path, 'wt') as fh:
                fh.write(json.dumps({'professor_uid': uid, 'target_author_id': 'A1002', 'work': synthetic_work('W3001')}) + '\n')
            return out_path
        original, avw.fetch_packets = avw.fetch_packets, fake_fetch
        try:
            report = avw.apply(self.source, self.decisions, self.verified, None, self.root / 'f', api_key='k')
        finally:
            avw.fetch_packets = original
        self.assertEqual(calls, [['W3001']])                      # only works absent from the source
        self.assertEqual(report['imported']['verified_new_works'], 1)
        with self.assertRaises(ValueError):                       # no file and no key
            apply(self.source, self.decisions, self.verified, None, self.root / 'g')

    def test_refuses_missing_packet_and_existing_out_dir(self):
        self.works.write_text('')
        with self.assertRaises(ValueError):
            apply(self.source, self.decisions, self.verified, self.works, self.root / 'x')
        (self.root / 'exists').mkdir()
        with self.assertRaises(FileExistsError):
            apply(self.source, self.decisions, self.verified, self.works, self.root / 'exists')


if __name__ == '__main__':
    unittest.main()
