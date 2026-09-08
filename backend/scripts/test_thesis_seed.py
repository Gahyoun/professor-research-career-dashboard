"""Offline synthetic thesis-seed tests. Never read actual researcher data."""
import contextlib
import hashlib
import io
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import build_thesis_seed as builder


class ThesisSeedTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.project = self.root / 'source'
        (self.project / '.private').mkdir(parents=True)
        self.cache = self.project / 'backend/cache/2026'
        self.cache.mkdir(parents=True)
        self.salt = b'synthetic-thesis-salt' * 2
        (self.project / '.private/anon_salt.bin').write_bytes(self.salt)
        self.db = self.root / 'synthetic.sqlite'
        with sqlite3.connect(self.db) as connection:
            connection.executescript('''
                CREATE TABLE professors(professor_uid TEXT,name TEXT,current_department TEXT);
                CREATE TABLE education(education_id INTEGER PRIMARY KEY,professor_uid TEXT,
                    degree_level TEXT,institution_raw TEXT,institution_unit_id TEXT,country TEXT,
                    award_year INTEGER,inferred_start_year INTEGER);
                CREATE TABLE institution_units(unit_id TEXT,display_name TEXT,country_code TEXT);
                CREATE TABLE work_authorship_evidence(professor_uid TEXT,work_id TEXT,title TEXT,
                    raw_author_name TEXT,publication_year INTEGER,doi TEXT,work_type TEXT,identity_decision TEXT);
                CREATE TABLE raw_affiliation_units(raw_affiliation_id INTEGER PRIMARY KEY,
                    professor_uid TEXT,work_id TEXT,institution_unit_id TEXT,identity_decision TEXT);
            ''')
        (self.cache / 'source_db_path.txt').write_text(str(self.db))
        self.public = self.root / 'dashboard.json'
        self.records = []
        self.add_person('synthetic-person')
        self.output = self.root / 'private/thesis-seed.json'

    def tearDown(self):
        self.temp.cleanup()

    def sql(self, query, params=()):
        with sqlite3.connect(self.db) as connection:
            cursor = connection.execute(query, params)
            return cursor.lastrowid

    def add_person(self, uid, *, education_country='Korea', unit_country='KR', award=2000):
        self.sql('INSERT INTO professors VALUES(?,?,?)', (uid, 'Synthetic source author', 'NEVER CURRENT DEPARTMENT'))
        unit = uid + '-unit'
        self.sql('INSERT INTO institution_units VALUES(?,?,?)', (unit, 'Synthetic University ' + uid, unit_country))
        degree = self.sql('INSERT INTO education VALUES(NULL,?,?,?,?,?,?,?)',
                         (uid, 'phd', 'Synthetic University ' + uid, unit, education_country, award, 1995))
        self.records.append({'id': builder.anonymous_id(uid, self.salt), 'phd_year': award})
        self.save_public()
        return degree

    def save_public(self):
        self.public.write_text(json.dumps({'meta': {'release_year': 2026}, 'professors': self.records}))

    def work(self, work_id='W1', uid='synthetic-person', *, year=2000, title='Synthetic dissertation',
             author='Synthetic source author', doi=None, work_type='dissertation', decision='keep'):
        self.sql('INSERT INTO work_authorship_evidence VALUES(?,?,?,?,?,?,?,?)',
                 (uid, work_id, title, author, year, doi, work_type, decision))

    def build(self, queue=None):
        return builder.build_seed(self.project, self.public, '2026', self.output, queue)

    def payload(self):
        return json.loads(self.output.read_text())

    def riss_queue(self):
        queue = self.root / 'private/riss-queue.json'
        queue.parent.mkdir(exist_ok=True)
        queue.write_text(json.dumps({'schema_version': 1, 'release_year': 2026,
            'public_data_sha256': hashlib.sha256(self.public.read_bytes()).hexdigest(), 'researchers': [{
                'professor_uid': 'synthetic-person', 'anon_id': self.records[0]['id'],
                'name': 'Synthetic source author', 'institution_unit_id': 'synthetic-person-unit',
                'institution_canonical': 'Synthetic University synthetic-person',
                'institution_query': 'Synthetic University synthetic-person', 'country': 'KR',
                'award_year': 2000, 'degree_level': 'phd'}]}))
        return queue

    def test_snapshot_hash_exact_id_map_all_anchors_retained_private_modes_and_no_source_write(self):
        self.add_person('missing-award', award=None)
        self.add_person('foreign-no-candidate', education_country='US', unit_country=None)
        self.work()
        before = self.db.read_bytes()
        counts = self.build()
        payload = self.payload()
        self.assertEqual(set(payload), {'schema_version','source_snapshot_sha256','education_records','thesis_records','links'})
        self.assertEqual(payload['source_snapshot_sha256'], hashlib.sha256(before).hexdigest())
        self.assertEqual(len(payload['education_records']), 3)
        self.assertEqual(counts['education_records_without_candidate'], 2)
        self.assertEqual(counts['candidate_links'], 1)
        self.assertNotIn('NEVER CURRENT DEPARTMENT', self.output.read_text())
        audit = self.output.with_suffix('.audit.json')
        for value in ['synthetic-person', 'Synthetic source author', 'Synthetic dissertation', 'W1', self.records[0]['id']]:
            self.assertNotIn(value, audit.read_text())
        for path in (self.output, audit):
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.output.parent.stat().st_mode & 0o777, 0o700)
        self.assertEqual(before, self.db.read_bytes())

    def test_domestic_foreign_missing_and_unrecognized_country_states(self):
        cases = [('KR','KR','domestic'), ('Korea',None,'domestic_unresolved'),
                 (None,'KR','domestic_unresolved'), ('Korea','US','country_conflict'),
                 ('US','GB','country_conflict'), ('US',None,'foreign'),
                 (None,'JP','foreign'), ('UK','GB','foreign'), ('US','US','foreign'),
                 (None,None,'unknown'), ('unrecognized foreign country','KR','unknown'),
                 ('Korea','ZZ','unknown')]
        for education, institution, expected in cases:
            with self.subTest(education=education, institution=institution):
                self.assertEqual(builder.classify_domestic(education, institution), expected)

    def test_foreign_candidates_allowed_but_conflicts_and_unknown_retained_without_links(self):
        for index, (education, institution) in enumerate([('US',None), ('Korea',None), ('Korea','US'),
                                                        ('US','GB'), ('unrecognized foreign country','KR')], 2):
            self.add_person('synthetic-' + str(index), education_country=education, unit_country=institution)
            self.work('W' + str(index), 'synthetic-' + str(index))
        counts = self.build()
        self.assertEqual(counts['education_records'], 6)
        self.assertEqual(counts['candidate_counts_by_region']['foreign']['candidate_links'], 1)
        self.assertEqual(counts['candidate_counts_by_region']['domestic']['candidate_links'], 1)
        self.assertTrue(all(row['query_status'] == 'anchor_review_required' for row in self.payload()['education_records']))

    def test_dissertation_type_and_keep_required_master_title_is_not_phd_proof(self):
        self.work('W1', title='Synthetic masters thesis')
        self.work('W2', work_type='article')
        self.work('W3', work_type='preprint')
        self.work('W4', decision='duplicate_drop_candidate')
        counts = self.build()
        self.assertEqual(counts['candidate_links'], 1)
        thesis = self.payload()['thesis_records'][0]
        self.assertEqual(thesis['title'], 'Synthetic masters thesis')
        self.assertIsNone(thesis['reported_degree_level'])
        self.assertIsNone(thesis['reported_department'])
        evidence = self.payload()['links'][0]['evidence']
        self.assertFalse(evidence['doctoral_level_verified'])
        self.assertFalse(evidence['degree_department_verified'])
        self.assertTrue(evidence['candidate_only'])

    def test_actual_year_bounds_no_inferred_year_fallback(self):
        for index, year in enumerate([1998,1999,2000,2001,2002,None,2027], 1):
            self.work('W' + str(index), year=year)
        self.add_person('no-award', award=None)
        self.work('W8', 'no-award', year=2000)
        self.add_person('invalid-award', award=1899)
        self.work('W9', 'invalid-award', year=1900)
        counts = self.build()
        self.assertEqual(counts['candidate_links'], 3)
        self.assertEqual(counts['missing_or_invalid_actual_award_years'], 2)
        self.assertEqual(sorted(row['evidence']['year_difference'] for row in self.payload()['links']), [-1,0,1])
        invalid = [row for row in self.payload()['education_records'] if row['source_professor_uid'] == 'invalid-award'][0]
        self.assertIsNone(invalid['award_year'])

    def test_multiple_phd_rows_preserved_without_selecting_one(self):
        self.sql("INSERT INTO education SELECT NULL,professor_uid,degree_level,institution_raw,institution_unit_id,country,award_year,inferred_start_year FROM education")
        self.work()
        counts = self.build()
        self.assertEqual(counts['education_records'], 2)
        self.assertEqual(counts['multiple_phd_researchers'], 1)
        self.assertEqual(counts['candidate_links'], 0)

    def test_same_work_person_and_unit_affiliation_is_observation_only(self):
        self.work('https://openalex.org/W1')
        self.work('W2')
        self.add_person('other-person')
        for uid, work, unit, decision in [('synthetic-person','W1','synthetic-person-unit','keep'),
                                         ('other-person','W2','synthetic-person-unit','keep'),
                                         ('synthetic-person','W2','other-unit','keep'),
                                         ('synthetic-person','W2','synthetic-person-unit','duplicate_drop_candidate')]:
            self.sql('INSERT INTO raw_affiliation_units VALUES(NULL,?,?,?,?)', (uid,work,unit,decision))
        self.build()
        by_work = {row['provider_record_id']: row['evidence'] for row in self.payload()['links']}
        self.assertTrue(by_work['W1']['kept_same_work_degree_institution_affiliation'])
        self.assertEqual(by_work['W1']['kept_same_work_degree_institution_affiliation_count'], 1)
        self.assertFalse(by_work['W1']['source_affiliation_is_awarding_institution_proof'])
        self.assertFalse(by_work['W2']['kept_same_work_degree_institution_affiliation'])

    def test_normalized_ids_dois_identical_duplicates_dedup_and_metadata_conflicts_quarantine(self):
        self.assertEqual(builder.normalize_doi('https://doi.org/10.1234/ABC%28D%29'), '10.1234/abc(d)')
        self.assertIsNone(builder.normalize_doi('https://doi.org/10.1234/ABC?tracking=1'))
        self.work('https://openalex.org/W1', doi='https://doi.org/10.1234/ABC')
        self.work('W1', doi='10.1234/abc')
        self.work('W2', title='one title')
        self.work('W2', title='contradictory title')
        self.work('W3', author='one author')
        self.work('W3', author='contradictory author')
        self.work('W4', doi='not a DOI')
        self.work('W01')
        counts = self.build()
        self.assertEqual(counts['candidate_links'], 2)
        self.assertEqual(counts['quarantined_metadata_conflict_works'], 2)
        self.assertEqual(counts['quarantined_eligible_metadata_conflict_works'], 2)
        self.assertEqual(counts['suppressed_duplicate_candidate_links'], 1)
        self.assertEqual(counts['invalid_work_id_rows'], 1)
        self.assertEqual(counts['invalid_doi_rows'], 1)
        by_work = {row['provider_record_id']: row for row in self.payload()['thesis_records']}
        self.assertEqual(by_work['W1']['source_url'], 'https://openalex.org/W1')
        self.assertEqual(by_work['W1']['doi'], '10.1234/abc')
        self.assertIsNone(by_work['W4']['doi'])

    def test_existing_all_country_riss_queue_marks_only_exact_matching_anchors_ready(self):
        self.add_person('foreign', education_country='US', unit_country='US')
        self.add_person('foreign-unresolved', education_country='US', unit_country=None)
        queue = self.riss_queue()
        data = json.loads(queue.read_text())
        data['researchers'].append({
            'professor_uid': 'foreign', 'anon_id': self.records[1]['id'], 'name': 'Synthetic source author',
            'institution_unit_id': 'foreign-unit', 'institution_canonical': 'Synthetic University foreign',
            'institution_query': 'Synthetic University foreign', 'country': 'US', 'award_year': 2000,
            'degree_level': 'phd'})
        queue.write_text(json.dumps(data))
        counts = self.build(queue)
        self.assertEqual(counts['query_ready_records'], 2)
        unresolved = [row for row in self.payload()['education_records'] if row['source_professor_uid'] == 'foreign-unresolved'][0]
        self.assertEqual(unresolved['query_status'], 'anchor_review_required')

    def test_release_id_mismatch_and_queue_anchor_mismatch_fail_without_outputs(self):
        queue = self.riss_queue()
        data = json.loads(queue.read_text())
        data['researchers'][0]['award_year'] = 2001
        queue.write_text(json.dumps(data))
        with self.assertRaises(ValueError):
            self.build(queue)
        self.assertFalse(self.output.exists())
        self.records[0]['id'] = 'P-WRONG-SYNTHETIC'
        self.save_public()
        with self.assertRaises(ValueError):
            self.build()
        self.assertFalse(self.output.exists())

    def test_private_guards_sidecars_no_overwrite_and_sanitized_cli_errors(self):
        for directory in ['public','DiSt','Downloads','release','releases','outputs']:
            with self.subTest(directory=directory), self.assertRaises(ValueError):
                builder.build_seed(self.project, self.public, '2026', self.root / directory / 'private/seed.json')
        repo = self.root / 'repository'
        repo.mkdir()
        subprocess.run(['git','init','-q',str(repo)], check=True, capture_output=True)
        (repo / '.gitignore').write_text('private/seed.json\n')
        with self.assertRaises(ValueError):
            builder.build_seed(self.project,self.public,'2026',repo / 'private/seed.json')
        self.assertFalse((repo / 'private/seed.json').exists())
        self.build()
        before = self.output.read_bytes()
        with self.assertRaises(FileExistsError):
            self.build()
        self.assertEqual(self.output.read_bytes(), before)
        stderr = io.StringIO()
        argv = ['build_thesis_seed.py','--private-project',str(self.project),'--public-data',str(self.public),'--output',str(self.output)]
        with (patch.object(sys,'argv',argv), patch.object(builder,'build_seed',side_effect=ValueError('SECRET NAME /PRIVATE/PATH')),
              contextlib.redirect_stderr(stderr)):
            with self.assertRaises(SystemExit):
                builder.main()
        self.assertNotIn('SECRET', stderr.getvalue())
        self.assertNotIn('/PRIVATE/PATH', stderr.getvalue())


if __name__ == '__main__':
    unittest.main()
