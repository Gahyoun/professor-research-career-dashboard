import sqlite3
import unittest

from career_consistency import classify, norm_institution, prepare
from release_identity import STRICT_IDENTITY_PREDICATE, PublicationIdentityGate

CAREER = ['Korea Advanced Institute of Science and Technology', 'Umeå University',
          'Korea Institute for Advanced Study', 'Gyeongsang National University']


def work(wid, institutions=(), coauthors=(), subfield='Statistical and Nonlinear Physics'):
    return {'id': wid, 'institutions': list(institutions), 'coauthors': list(coauthors), 'subfield': subfield}


class ClassifyTests(unittest.TestCase):
    """Mirrors the 2026-11-05 case: a network scientist's OpenAlex ID also held food-science
    papers by a namesake, some with an unrelated affiliation and some with none; a common-name
    coauthor ID ('A-park') linked the namesake's papers to the real collaborator."""

    def setUp(self):
        self.works = [
            work('W1', ['Korea Advanced Institute of Science and Technology'], ['A-kim', 'A-jeong']),
            work('W2', ['Umea University'], ['A-holme', 'A-porter']),           # accent-free spelling
            work('W3', ['Korea Institute for Advanced Study', 'University of Oxford'], ['A-porter', 'A-cucuringu']),
            work('W4', ['Gyeongsang National University (Main Campus)'], ['A-son', 'A-park'], 'Molecular Biology'),
            work('W5', ['University of Oxford'], ['A-porter', 'A-cucuringu']),   # visit abroad: two shared coauthors
            work('W6', ['Chungbuk National University'], ['A-park', 'A-food1'], 'Biochemistry (medical)'),
            work('W7', [], ['A-food2', 'A-food3'], 'Molecular Biology'),         # no affiliation, nobody shared
            work('W8', [], ['A-park', 'A-food4'], 'Plant Science'),              # one shared (common name), other subfield
            work('W9', [], ['A-jeong'], 'Statistical and Nonlinear Physics'),    # one shared, own subfield
            work('W10', [], []),                                                 # solo, no affiliation
        ]

    def test_namesakes_dropped_visits_and_unknowns_kept(self):
        self.assertEqual(classify(self.works, CAREER), {'W6': 'career_institution_mismatch',
                                                         'W7': 'career_coauthor_mismatch',
                                                         'W8': 'career_field_mismatch'})

    def test_needs_enough_anchor_works(self):
        self.assertEqual(classify(self.works[4:], CAREER), {})

    def test_institution_names_normalise(self):
        self.assertEqual(norm_institution('Umeå University'), norm_institution('UMEA university'))
        self.assertEqual(norm_institution('Hanyang University (ERICA Campus)'), norm_institution('Hanyang University'))


class PrivateBuildTests(unittest.TestCase):
    def test_predicate_and_gate_exclude_inconsistent_pairs(self):
        con = sqlite3.connect(':memory:')
        con.execute("ATTACH DATABASE ':memory:' AS koad")
        con.executescript('''
            CREATE TABLE work_authorship_evidence(professor_uid TEXT, work_id TEXT, identity_decision TEXT,
                coauthor_ids_json TEXT, subfield_name TEXT);
            CREATE TABLE raw_affiliation_units(professor_uid TEXT, work_id TEXT, institution_unit_id TEXT, institution_name TEXT);
            CREATE TABLE career_positions_v2(professor_uid TEXT, position_type TEXT, institution_unit_id TEXT, institution_name TEXT);
            CREATE TABLE institution_units(unit_id TEXT, display_name TEXT);
            CREATE TABLE koad.work_decision(professor_uid TEXT, work_id TEXT, decision TEXT);
        ''')
        con.executemany('INSERT INTO institution_units VALUES (?,?)', [('U1', 'Gyeongsang National University'), ('U9', 'Chungbuk National University')])
        con.execute("INSERT INTO career_positions_v2 VALUES ('p','faculty','U1',NULL)")
        for wid, unit, co, field in (('W1', 'U1', '["A1"]', 'Physics'), ('W2', 'U1', '["A2"]', 'Physics'),
                                     ('W3', 'U1', '["A3"]', 'Physics'), ('W9', 'U9', '["A9"]', 'Food')):
            con.execute('INSERT INTO work_authorship_evidence VALUES (?,?,?,?,?)', ('p', wid, 'keep', co, field))
            con.execute('INSERT INTO raw_affiliation_units VALUES (?,?,?,NULL)', ('p', wid, unit))
            con.execute("INSERT INTO koad.work_decision VALUES ('p',?,'true_paper')", (wid,))
        self.assertEqual(prepare(con), 1)
        kept = [r[0] for r in con.execute(
            f"SELECT work_id FROM work_authorship_evidence w WHERE {STRICT_IDENTITY_PREDICATE.format(alias='w')} ORDER BY work_id")]
        self.assertEqual(kept, ['W1', 'W2', 'W3'])
        gate = PublicationIdentityGate.from_connection(con)
        self.assertEqual(gate.exclusion_reason('p', 'W9'), 'career_institution_mismatch')
        self.assertIsNone(gate.exclusion_reason('p', 'W1'))

    def test_missing_tables_leave_everything_published(self):
        con = sqlite3.connect(':memory:')
        self.assertEqual(prepare(con), 0)
        self.assertEqual(con.execute('SELECT COUNT(*) FROM temp.career_inconsistent').fetchone()[0], 0)


if __name__ == '__main__':
    unittest.main()
