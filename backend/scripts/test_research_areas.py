import importlib.util
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('research_areas', ROOT / 'build_research_areas.py')
areas = importlib.util.module_from_spec(spec)
spec.loader.exec_module(areas)


class ResearchAreaTests(unittest.TestCase):
    def test_aggregate_counts_and_hierarchy(self):
        rows = [('u1', 'Physical Sciences', 'Physics and Astronomy', 'Condensed Matter Physics', 'Topological insulators')] * 3 + [
            ('u1', 'Physical Sciences', 'Materials Science', 'Materials Chemistry', 'Perovskite solar cells'),
            ('u2', 'Physical Sciences', 'Mathematics', 'Applied Mathematics', None),
            ('u3', 'Physical Sciences', 'Chemistry', 'Organic Chemistry', 'Catalysis'),
        ]
        out = areas.aggregate(rows, lambda uid: {'u1': 'P-A', 'u2': 'P-B'}.get(uid))
        self.assertEqual(sorted(out['researchers']), ['P-A', 'P-B'])  # u3 is not in the public release
        a = out['researchers']['P-A']
        self.assertEqual(a['n'], 4)
        top_subfield, count = a['s'][0]
        self.assertEqual(out['subfields'][top_subfield][0], 'Condensed Matter Physics')
        self.assertEqual(count, 3)
        field_name, domain_idx = out['fields'][out['subfields'][top_subfield][1]]
        self.assertEqual(field_name, 'Physics and Astronomy')
        self.assertEqual(out['domains'][domain_idx], 'Physical Sciences')
        topic_idx = a['t'][0][0]
        self.assertEqual(out['subfields'][out['topics'][topic_idx][1]][0], 'Condensed Matter Physics')
        self.assertEqual(out['researchers']['P-B']['t'], [])
        self.assertNotIn('Organic Chemistry', [s for s, _ in out['subfields']])

    def test_build_applies_release_identity_rules(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / 'source.sqlite'
            with sqlite3.connect(db) as con:
                con.execute('CREATE TABLE professors(professor_uid TEXT, phd_year INTEGER)')
                con.execute('''CREATE TABLE work_authorship_evidence(professor_uid TEXT, work_id TEXT, publication_year INTEGER,
                    identity_decision TEXT, domain_name TEXT, field_name TEXT, subfield_name TEXT, topic_name TEXT, title TEXT, doi TEXT)''')
                con.execute("INSERT INTO professors VALUES('uid-1', 2010)")
                con.executemany('INSERT INTO work_authorship_evidence VALUES(?,?,?,?,?,?,?,?,?,?)', [
                    ('uid-1', 'W1', 2012, 'keep', 'Physical Sciences', 'Physics and Astronomy', 'Condensed Matter Physics', 'Spin', 'secret title', '10.1/x'),
                    ('uid-1', 'W2', 2003, 'keep', 'Physical Sciences', 'Physics and Astronomy', 'Optics', 'Lasers', 't', 'd'),        # before phd_year-5
                    ('uid-1', 'W3', 2013, 'drop', 'Physical Sciences', 'Physics and Astronomy', 'Optics', 'Lasers', 't', 'd'),        # source drop
                    ('uid-1', 'W4', 2014, 'keep', 'Physical Sciences', 'Physics and Astronomy', 'Optics', 'Lasers', 't', 'd'),        # KOAD namesake
                    ('uid-1', 'W5', 2030, 'keep', 'Physical Sciences', 'Physics and Astronomy', 'Optics', 'Lasers', 't', 'd'),        # after release
                    ('uid-1', 'W6', 2014, 'keep', 'Physical Sciences', 'Physics and Astronomy', 'Optics', 'Lasers', 't', 'd'),        # no KOAD decision
                ])
            with sqlite3.connect(Path(tmp) / 'identity_decisions.sqlite') as con:
                con.execute('CREATE TABLE work_decision(professor_uid TEXT, work_id TEXT, decision TEXT)')
                con.execute("INSERT INTO work_decision VALUES('uid-1','W4','namesake_paper')")
                con.executemany('INSERT INTO work_decision VALUES(?,?,?)', [('uid-1', wid, 'true_paper') for wid in ('W1', 'W2', 'W3', 'W5')])
            salt = b'k' * 32
            pid = areas.anon_id(salt, 'uid-1')
            out = areas.build(db, salt, {pid}, 2026)
            self.assertEqual(out['researchers'][pid]['n'], 1)
            text = json.dumps(out)
            for leaked in ('uid-1', 'W1', 'secret title', '10.1/x'):
                self.assertNotIn(leaked, text)


if __name__ == '__main__':
    unittest.main()
