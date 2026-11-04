import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest

from augment_openalex_evidence import augment, department_labels, read_audit_json
from release_identity import PublicationIdentityGate


def create_source(path):
    with sqlite3.connect(path) as connection:
        connection.executescript('''
            CREATE TABLE professors(professor_uid TEXT PRIMARY KEY,openalex_id TEXT,latest_institution_unit_id TEXT,orcid TEXT);
            INSERT INTO professors VALUES('synthetic-one','A1001','I2002','https://orcid.org/0000-0000-0000-0001');
            INSERT INTO professors VALUES('synthetic-two','A1003','I2002',NULL);
            CREATE TABLE education(education_id INTEGER PRIMARY KEY,professor_uid TEXT,degree_level TEXT,institution_unit_id TEXT,confidence TEXT);
            INSERT INTO education VALUES(1,'synthetic-one','phd','doctoral-campus','high');
            CREATE TABLE career_positions_v2(professor_uid TEXT,position_type TEXT,institution_unit_id TEXT);
            INSERT INTO career_positions_v2 VALUES('synthetic-one','faculty','I2003');
            CREATE TABLE institution_units(unit_id TEXT PRIMARY KEY,openalex_institution_id TEXT,ror TEXT,display_name TEXT NOT NULL,
                country_code TEXT,institution_type TEXT,lineage_json TEXT NOT NULL,campus_cluster_id TEXT,postal_code TEXT,city TEXT,canonical_source TEXT NOT NULL);
            INSERT INTO institution_units VALUES('doctoral-campus','I2001',NULL,'Existing Doctoral Campus','KR','education','[]',NULL,NULL,NULL,'existing');
            INSERT INTO institution_units VALUES('I2002','I2002',NULL,'Existing Current University','KR','education','[]',NULL,NULL,NULL,'existing');
            INSERT INTO institution_units VALUES('I2003','I2003',NULL,'Existing Faculty University','KR','education','[]',NULL,NULL,NULL,'existing');
            CREATE TABLE work_authorship_evidence(professor_uid TEXT NOT NULL,openalex_id TEXT NOT NULL,work_id TEXT NOT NULL,
                doi TEXT,title TEXT,publication_date TEXT,publication_year INTEGER,period TEXT,work_type TEXT,raw_author_name TEXT,raw_orcid TEXT,
                topic_id TEXT,topic_name TEXT,subfield_id TEXT,subfield_name TEXT,field_id TEXT,field_name TEXT,domain_id TEXT,domain_name TEXT,
                topic_tree_distance REAL,identity_decision TEXT NOT NULL,duplicate_candidate_score INTEGER NOT NULL,duplicate_candidate_severity TEXT,
                decision_reasons_json TEXT NOT NULL,anchor_flags_json TEXT NOT NULL,coauthor_ids_json TEXT NOT NULL,source_url TEXT NOT NULL,
                PRIMARY KEY(professor_uid,work_id),FOREIGN KEY(professor_uid) REFERENCES professors(professor_uid));
            INSERT INTO work_authorship_evidence VALUES('synthetic-one','A1001','W3000',NULL,'Existing title','2010-01-01',2010,'2010-H1','article',
                'Existing author',NULL,'T4001','Physics','3104','Condensed Matter Physics','31','Physics and Astronomy','3','Physical Sciences',
                NULL,'duplicate_drop_candidate',100,'high','["existing decision"]','{}','[]','https://openalex.org/W3000');
            CREATE TABLE raw_affiliation_units(raw_affiliation_id INTEGER PRIMARY KEY,professor_uid TEXT NOT NULL,work_id TEXT NOT NULL,
                period TEXT,raw_affiliation_string TEXT,unit_label TEXT,postal_code TEXT,institution_unit_id TEXT,institution_name TEXT,
                country_code TEXT,nation TEXT,region TEXT,city TEXT,campus_cluster_id TEXT,postal_campus_cluster_id TEXT,identity_decision TEXT NOT NULL,
                UNIQUE(professor_uid,work_id,raw_affiliation_string,institution_unit_id,unit_label,postal_code));
            CREATE TABLE openalex_author_profiles(professor_uid TEXT NOT NULL,openalex_id TEXT NOT NULL,display_name TEXT,orcid TEXT,works_count INTEGER,
                topics_json TEXT NOT NULL,updated_date TEXT,retrieved_date TEXT NOT NULL,PRIMARY KEY(professor_uid,openalex_id));
            INSERT INTO openalex_author_profiles VALUES('synthetic-one','A1001','Existing profile',NULL,123,'[]',NULL,'2000-01-01');
        ''')


def synthetic_work(work_id='W3001'):
    institution = lambda iid: {'id': 'https://openalex.org/' + iid, 'display_name': 'Synthetic University ' + iid,
                              'country_code': 'KR', 'type': 'education', 'lineage': ['https://openalex.org/' + iid]}
    return {
        'id': 'https://openalex.org/' + work_id, 'doi': 'https://doi.org/10.0000/synthetic-' + work_id,
        'title': 'Synthetic quantum transport paper', 'publication_date': '2012-08-20', 'publication_year': 2012, 'type': 'article',
        'primary_topic': {'id': 'https://openalex.org/T4001', 'display_name': 'Synthetic Physics',
            'subfield': {'id': 'https://openalex.org/subfields/3104', 'display_name': 'Condensed Matter Physics'},
            'field': {'id': 'https://openalex.org/fields/31', 'display_name': 'Physics and Astronomy'},
            'domain': {'id': 'https://openalex.org/domains/3', 'display_name': 'Physical Sciences'}},
        'authorships': [
            {'author': {'id': 'https://openalex.org/A1002', 'display_name': 'Synthetic Alias', 'orcid': 'https://orcid.org/0000-0000-0000-0001'},
             'raw_author_name': 'Synthetic Alias', 'raw_orcid': None, 'author_position': 'first', 'is_corresponding': True,
             'institutions': [institution(iid) for iid in ('I2001', 'I2002', 'I2003')],
             'raw_affiliation_strings': ['Department of Physics, Synthetic Doctoral University', 'Unmapped synthetic address'],
             'affiliations': [{'raw_affiliation_string': 'Department of Physics, Synthetic Doctoral University', 'institution_ids': ['I2001']}]},
            {'author': {'id': 'https://openalex.org/A1004', 'display_name': 'Synthetic Coauthor'}, 'institutions': []},
        ],
        'extra_private_metadata': {'preserve_exact_value': ['example', 0, None]},
    }


class AugmentEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        self.source = self.root / 'source.sqlite'
        create_source(self.source)
        self.original = self.source.read_bytes()
        self.aliases = self.root / 'accepted.json'
        self.aliases.write_text(json.dumps([{'professor_uid': 'synthetic-one', 'openalex_ids': ['A1002'],
            'verified_work_ids': ['https://openalex.org/W3002'], 'source': {'kind': 'synthetic_verified_publication'},
            'evidence': {'description': 'Synthetic proof'}}]))
        self.works = self.root / 'works.jsonl'
        self.output = self.root / 'augmented.sqlite'

    def write_records(self, works):
        self.works.write_text(''.join(json.dumps({'professor_uid': 'synthetic-one', 'target_author_id': 'A1002', 'work': work}) + '\n' for work in works))

    def run_import(self):
        return augment(self.source, self.aliases, self.works, self.output)

    def test_new_candidates_review_verified_anchors_keep_existing_decisions_unchanged(self):
        works = [synthetic_work('W3000'), synthetic_work('W3001'), synthetic_work('W3002')]
        self.write_records(works + [works[1]])
        counts = self.run_import()
        self.assertEqual(counts['new_works'], 2)
        self.assertEqual(counts['existing_works_preserved'], 1)
        self.assertEqual(counts['existing_authorship_contexts_preserved'], 1)
        self.assertEqual(counts['verified_new_works'], 1)
        self.assertEqual(counts['audit_records'], 3)
        self.assertEqual(self.source.read_bytes(), self.original)
        self.assertEqual(os.stat(self.output).st_mode & 0o777, 0o600)
        with sqlite3.connect(self.output) as connection:
            self.assertEqual(dict(connection.execute('SELECT work_id,identity_decision FROM work_authorship_evidence')), {
                'W3000': 'duplicate_drop_candidate', 'W3001': 'review', 'W3002': 'keep'})
            existing = connection.execute("SELECT openalex_id,title,duplicate_candidate_score,decision_reasons_json FROM work_authorship_evidence WHERE work_id='W3000'").fetchone()
            self.assertEqual(existing, ('A1001', 'Existing title', 100, '["existing decision"]'))
            self.assertEqual(connection.execute("SELECT count(*) FROM raw_affiliation_units WHERE work_id='W3000'").fetchone()[0], 0)
            row = connection.execute("SELECT period,topic_id,subfield_id,field_id,domain_id,anchor_flags_json,coauthor_ids_json,raw_orcid FROM work_authorship_evidence WHERE work_id='W3001'").fetchone()
            self.assertEqual(row[:5], ('2012-H2', 'T4001', '3104', '31', '3'))
            self.assertEqual(json.loads(row[5]), {'phd_institution': True, 'current_institution': True, 'faculty_chain': True, 'orcid_exact': True})
            self.assertEqual(json.loads(row[6]), ['A1004'])
            self.assertIsNone(row[7])  # profile ORCID does not masquerade as a raw authorship ORCID
            self.assertEqual(connection.execute("SELECT display_name FROM institution_units WHERE unit_id='I2002'").fetchone()[0], 'Existing Current University')
            profile = connection.execute("SELECT display_name,works_count FROM openalex_author_profiles WHERE openalex_id='A1002'").fetchone()
            self.assertEqual(profile, ('Synthetic Alias', None))
            self.assertEqual(connection.execute("SELECT works_count FROM openalex_author_profiles WHERE openalex_id='A1001'").fetchone()[0], 123)
            saved = connection.execute("SELECT full_work_json,target_authorship_json FROM alias_work_import_audit WHERE work_id='W3001'").fetchone()
            self.assertIsInstance(saved[0], bytes)
            self.assertEqual(read_audit_json(saved[0]), works[1])
            self.assertEqual(json.loads(saved[1]), works[1]['authorships'][0])
            packet = connection.execute("SELECT input_record_json FROM alias_work_import_audit WHERE work_id='W3001'").fetchone()[0]
            self.assertEqual(read_audit_json(packet)['work'], works[1])
            self.assertEqual(read_audit_json(json.dumps(works[1])), works[1])
            unbound = connection.execute("SELECT institution_unit_id,unit_label FROM raw_affiliation_units WHERE raw_affiliation_string='Unmapped synthetic address' LIMIT 1").fetchone()
            self.assertEqual(unbound, (None, None))
            connection.execute("ATTACH DATABASE ':memory:' AS koad")
            connection.execute('CREATE TABLE koad.work_decision(professor_uid TEXT,work_id TEXT,decision TEXT)')
            connection.executemany('INSERT INTO koad.work_decision VALUES(?,?,?)', [('synthetic-one', wid, 'true_paper') for wid in ('W3001', 'W3002')])
            gate = PublicationIdentityGate.from_connection(connection)
            self.assertEqual(gate.exclusion_reason('synthetic-one', 'W3001'), 'missing_kept_source_evidence')
            self.assertIsNone(gate.exclusion_reason('synthetic-one', 'W3002'))
        second = self.root / 'second-copy.sqlite'
        again = augment(self.output, self.aliases, self.works, second)
        self.assertEqual(again['new_works'], 0)
        self.assertEqual(again['new_affiliations'], 0)
        self.assertEqual(again['audit_records'], 0)

    def test_target_authorship_mismatch_rolls_back_entire_copy(self):
        wrong = synthetic_work('W3999')
        wrong['authorships'][0]['author']['id'] = 'https://openalex.org/A9999'
        self.write_records([synthetic_work(), wrong])
        with self.assertRaisesRegex(ValueError, 'exactly one target authorship'):
            self.run_import()
        self.assertFalse(self.output.exists())
        self.assertEqual(self.source.read_bytes(), self.original)

    def test_unaccepted_alias_and_unknown_researcher_are_rejected(self):
        self.write_records([synthetic_work()])
        record = json.loads(self.works.read_text())
        record['target_author_id'] = 'A9999'
        self.works.write_text(json.dumps(record) + '\n')
        with self.assertRaisesRegex(ValueError, 'not covered'):
            self.run_import()
        acceptance = json.loads(self.aliases.read_text())
        acceptance[0]['professor_uid'] = 'unknown-person'
        self.aliases.write_text(json.dumps(acceptance))
        with self.assertRaisesRegex(ValueError, 'unknown researcher'):
            self.run_import()
        self.assertFalse(self.output.exists())

    def test_shared_profile_preserves_separate_researchers_and_prior_decisions(self):
        acceptance = json.loads(self.aliases.read_text())
        acceptance.append({'professor_uid': 'synthetic-two', 'openalex_ids': ['A1002'],
                           'source': {'kind': 'synthetic_mixed_profile'}})
        self.aliases.write_text(json.dumps(acceptance))
        self.write_records([synthetic_work('W3002')])
        packet = json.loads(self.works.read_text())
        packet['professor_uid'] = 'synthetic-two'
        self.works.write_text(self.works.read_text() + json.dumps(packet) + '\n')
        self.run_import()
        with sqlite3.connect(self.output) as c:
            self.assertEqual(c.execute("SELECT professor_uid,identity_decision FROM work_authorship_evidence WHERE work_id='W3002' ORDER BY professor_uid").fetchall(),
                             [('synthetic-one', 'keep'), ('synthetic-two', 'review')])
            self.assertEqual(c.execute('SELECT professor_uid,openalex_id FROM professors ORDER BY professor_uid').fetchall(),
                             [('synthetic-one', 'A1001'), ('synthetic-two', 'A1003')])
        self.assertEqual(self.source.read_bytes(), self.original)

    def test_only_null_primary_can_be_assigned_with_private_audit(self):
        with sqlite3.connect(self.source) as c:
            c.execute("UPDATE professors SET openalex_id=NULL WHERE professor_uid='synthetic-one'")
        self.original = self.source.read_bytes()
        accepted = json.loads(self.aliases.read_text())
        accepted[0]['primary_id'] = 'A1002'
        self.aliases.write_text(json.dumps(accepted))
        self.write_records([synthetic_work()])
        self.assertEqual(self.run_import()['new_primary_assignments'], 1)
        with sqlite3.connect(self.output) as c:
            self.assertEqual(c.execute("SELECT openalex_id FROM professors WHERE professor_uid='synthetic-one'").fetchone()[0], 'A1002')
            self.assertEqual(c.execute('SELECT previous_openalex_id,new_openalex_id FROM alias_primary_assignment_audit').fetchall(), [(None, 'A1002')])
        self.assertEqual(self.source.read_bytes(), self.original)
        with self.assertRaisesRegex(ValueError, 'included in the accepted IDs'):
            accepted[0]['primary_id'] = 'A9999'; self.aliases.write_text(json.dumps(accepted))
            augment(self.source, self.aliases, self.works, self.root / 'invalid.sqlite')
        accepted[0]['primary_id'] = 'A1002'; self.aliases.write_text(json.dumps(accepted))
        with sqlite3.connect(self.source) as c:
            c.execute("UPDATE professors SET openalex_id='A1001' WHERE professor_uid='synthetic-one'")
        with self.assertRaisesRegex(ValueError, 'Cannot replace'):
            augment(self.source, self.aliases, self.works, self.root / 'replacement.sqlite')

    def test_proven_wrong_primary_is_archived_before_new_primary_assignment(self):
        accepted = json.loads(self.aliases.read_text())
        accepted[0]['primary_id'] = 'A1002'
        self.aliases.write_text(json.dumps(accepted))
        self.write_records([synthetic_work('W3002')])
        rejected = self.root / 'rejected.json'
        record = {'professor_uid': 'synthetic-one', 'wrong_id': 'A1001',
                  'reason': 'Synthetic independent publications identify another person',
                  'source_urls': ['https://example.invalid/synthetic-proof']}
        rejected.write_text(json.dumps([record]))
        result = augment(self.source, self.aliases, self.works, self.output, rejected)
        self.assertEqual(result['wrong_link_works_quarantined'], 1)
        self.assertEqual(result['new_primary_assignments'], 1)
        with sqlite3.connect(self.output) as c:
            self.assertEqual(c.execute('SELECT work_id FROM work_authorship_evidence').fetchall(), [('W3002',)])
            self.assertEqual(c.execute("SELECT openalex_id FROM professors WHERE professor_uid='synthetic-one'").fetchone()[0], 'A1002')
            archived = c.execute("SELECT original_row_json,rejection_json FROM wrong_link_quarantine_audit WHERE table_name='work_authorship_evidence'").fetchone()
            self.assertEqual(json.loads(archived[0])['title'], 'Existing title')
            self.assertEqual(json.loads(archived[1]), record)
        self.assertEqual(self.source.read_bytes(), self.original)
        record['wrong_id'] = 'A9999'; rejected.write_text(json.dumps([record]))
        with self.assertRaisesRegex(ValueError, 'match the existing primary'):
            augment(self.source, self.aliases, self.works, self.root / 'bad-rejection.sqlite', rejected)
        self.assertFalse((self.root / 'bad-rejection.sqlite').exists())

    def test_original_or_existing_output_cannot_be_overwritten(self):
        self.write_records([synthetic_work()])
        with self.assertRaisesRegex(ValueError, 'differ'):
            augment(self.source, self.aliases, self.works, self.source)
        self.output.write_bytes(b'existing output')
        with self.assertRaises(FileExistsError):
            self.run_import()
        self.assertEqual(self.output.read_bytes(), b'existing output')
        self.assertEqual(self.source.read_bytes(), self.original)

    def test_missing_verification_provenance_and_inconsistent_dates_are_rejected(self):
        self.write_records([synthetic_work()])
        accepted = json.loads(self.aliases.read_text())
        del accepted[0]['source']; del accepted[0]['evidence']
        self.aliases.write_text(json.dumps(accepted))
        with self.assertRaisesRegex(ValueError, 'verification source or evidence'):
            self.run_import()
        accepted[0]['source'] = 'synthetic proof'
        self.aliases.write_text(json.dumps(accepted))
        wrong = synthetic_work(); wrong['publication_year'] = 2013
        self.write_records([wrong])
        with self.assertRaisesRegex(ValueError, 'year and date disagree'):
            self.run_import()
        self.assertFalse(self.output.exists())

    def test_departments_are_literal_and_not_invented_from_research_topics(self):
        self.assertEqual(department_labels('Synthetic University, City, KR'), [None])
        self.assertEqual(department_labels('Dept. of Physics, Synthetic University'), ['Dept. of Physics'])
        self.assertEqual(department_labels('Department of Physics and Astronomy, University'), ['Department of Physics and Astronomy'])


if __name__ == '__main__':
    unittest.main()
