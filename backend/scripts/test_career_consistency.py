import sqlite3
import unittest

from career_consistency import classify, norm_institution, prepare
from release_identity import STRICT_IDENTITY_PREDICATE, PublicationIdentityGate

CAREER = ['Korea Advanced Institute of Science and Technology', 'Umeå University',
          'Korea Institute for Advanced Study', 'Gyeongsang National University']


def work(wid, institutions=(), coauthors=(), subfield='Statistical and Nonlinear Physics',
         field='Physics and Astronomy', domain='Physical Sciences'):
    return {'id': wid, 'institutions': list(institutions), 'coauthors': list(coauthors),
            'subfield': subfield, 'field': field, 'domain': domain}


FOOD = dict(subfield='Food Science', field='Agricultural and Biological Sciences', domain='Life Sciences')


class ClassifyTests(unittest.TestCase):
    """The 2026-11-05 case: a network scientist's OpenAlex ID also held food-science papers by a
    namesake; a common-name coauthor ID ('A-park') linked some of them to a real collaborator."""

    def setUp(self):
        self.works = [
            work('W1', ['Korea Advanced Institute of Science and Technology'], ['A-kim', 'A-jeong']),
            work('W2', ['Umea University'], ['A-holme', 'A-porter']),           # accent-free spelling
            work('W3', ['Korea Institute for Advanced Study'], ['A-porter', 'A-cucuringu']),
            work('W4', ['Gyeongsang National University (Main Campus)'], ['A-son', 'A-park'],
                 'Molecular Biology', 'Biochemistry, Genetics and Molecular Biology', 'Life Sciences'),
            work('W5', ['University of Oxford'], ['A-porter']),                  # physics visit: home domain
            work('W6', [], ['A-food1', 'A-food2'], **FOOD),                     # no shared coauthor, new subfield
            work('W7', ['Chungbuk National University'], ['A-park', 'A-food3'], **FOOD),   # one shared, new field
            work('W8', [], ['A-food4'], 'Molecular Biology', 'Biochemistry, Genetics and Molecular Biology', 'Life Sciences'),
            work('W9', [], [], **FOOD),                                         # solo: protected
            work('W10', ['Harvard University'], ['A-x', 'A-y'], 'Genetics', 'Biochemistry, Genetics and Molecular Biology',
                 'Life Sciences'),                                              # field known from anchors, subfield new
        ]

    def test_physicist_namesakes_dropped_genuine_kept(self):
        self.assertEqual(classify(self.works, CAREER, 'physics'), {
            'W6': 'career_subfield_mismatch', 'W7': 'career_field_mismatch', 'W10': 'career_subfield_mismatch'})

    def test_home_domain_is_never_judged(self):
        self.assertEqual(classify(self.works, CAREER, 'biology'), {})

    def test_needs_enough_anchor_works(self):
        self.assertEqual(classify(self.works[4:], CAREER, 'physics'), {})

    def test_institution_names_normalise(self):
        self.assertEqual(norm_institution('Umeå University'), norm_institution('UMEA university'))
        self.assertEqual(norm_institution('Hanyang University (ERICA Campus)'), norm_institution('Hanyang University'))


class PrivateBuildTests(unittest.TestCase):
    def test_predicate_and_gate_exclude_inconsistent_pairs(self):
        con = sqlite3.connect(':memory:')
        con.execute("ATTACH DATABASE ':memory:' AS koad")
        con.executescript('''
            CREATE TABLE work_authorship_evidence(professor_uid TEXT, work_id TEXT, identity_decision TEXT,
                coauthor_ids_json TEXT, subfield_name TEXT, field_name TEXT, domain_name TEXT);
            CREATE TABLE professors(professor_uid TEXT, subject TEXT);
            INSERT INTO professors VALUES ('p', 'physics');
            CREATE TABLE raw_affiliation_units(professor_uid TEXT, work_id TEXT, institution_unit_id TEXT, institution_name TEXT);
            CREATE TABLE career_positions_v2(professor_uid TEXT, position_type TEXT, institution_unit_id TEXT, institution_name TEXT);
            CREATE TABLE institution_units(unit_id TEXT, display_name TEXT);
            CREATE TABLE koad.work_decision(professor_uid TEXT, work_id TEXT, decision TEXT);
        ''')
        con.executemany('INSERT INTO institution_units VALUES (?,?)', [('U1', 'Gyeongsang National University'), ('U9', 'Chungbuk National University')])
        con.execute("INSERT INTO career_positions_v2 VALUES ('p','faculty','U1',NULL)")
        for wid, unit, co, sub, fld, dom in (('W1', 'U1', '["A1"]', 'Physics', 'Physics', 'Physical Sciences'),
                                             ('W2', 'U1', '["A2"]', 'Physics', 'Physics', 'Physical Sciences'),
                                             ('W3', 'U1', '["A3"]', 'Physics', 'Physics', 'Physical Sciences'),
                                             ('W9', 'U9', '["A9"]', 'Food Science', 'Agricultural', 'Life Sciences')):
            con.execute('INSERT INTO work_authorship_evidence VALUES (?,?,?,?,?,?,?)', ('p', wid, 'keep', co, sub, fld, dom))
            con.execute('INSERT INTO raw_affiliation_units VALUES (?,?,?,NULL)', ('p', wid, unit))
            con.execute("INSERT INTO koad.work_decision VALUES ('p',?,'true_paper')", (wid,))
        self.assertEqual(prepare(con), 1)
        kept = [r[0] for r in con.execute(
            f"SELECT work_id FROM work_authorship_evidence w WHERE {STRICT_IDENTITY_PREDICATE.format(alias='w')} ORDER BY work_id")]
        self.assertEqual(kept, ['W1', 'W2', 'W3'])
        gate = PublicationIdentityGate.from_connection(con)
        self.assertEqual(gate.exclusion_reason('p', 'W9'), 'career_subfield_mismatch')
        self.assertIsNone(gate.exclusion_reason('p', 'W1'))

    def test_missing_tables_leave_everything_published(self):
        con = sqlite3.connect(':memory:')
        self.assertEqual(prepare(con), 0)
        self.assertEqual(con.execute('SELECT COUNT(*) FROM temp.career_inconsistent').fetchone()[0], 0)


class CorroborationTests(unittest.TestCase):
    """An ID that merged a physicist with a food scientist of the same name; one coauthor ID is
    shared too. Only works with BOTH an identity and a subject affirmation survive."""

    def test_identity_and_subject_both_required(self):
        from career_consistency import corroboration
        segs = [('Sungkyunkwan University', 2011, 2016), ('Max Planck Institute for Evolutionary Biology', 2017, 2021),
                ('Inha University', 2022, 2026)]
        sp = dict(subfield='Statistical and Nonlinear Physics', domain='Physical Sciences')
        food = dict(subfield='Food Science', domain='Life Sciences')
        works = [
            dict(id='W1', year=2014, institutions=['Sungkyunkwan University'], coauthors=['A-kim'], **sp),
            dict(id='W2', year=2019, institutions=['Max Planck Institute for Evolutionary Biology'], coauthors=['A-traulsen'],
                 subfield='Genetics', domain='Life Sciences'),
            dict(id='W3', year=2024, institutions=['Inha University'], coauthors=['A-kim'], **sp),
            dict(id='W4', year=2020, institutions=[], coauthors=['A-traulsen'], subfield='Genetics', domain='Life Sciences'),
            dict(id='W5', year=2013, institutions=[], coauthors=[], **food),            # nothing affirms it
            dict(id='W6', year=2015, institutions=[], coauthors=['A-kim'], **food),     # shared coauthor only
            dict(id='W7', year=2016, institutions=[], coauthors=[], subfield='Pollution', domain='Physical Sciences'),  # domain only
        ]
        self.assertEqual(corroboration(works, segs, 'physics'),
                         {'W5': 'uncorroborated', 'W6': 'uncorroborated', 'W7': 'uncorroborated'})


if __name__ == '__main__':
    unittest.main()
