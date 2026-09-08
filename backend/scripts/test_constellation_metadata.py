import importlib.util
import hashlib
import base64
import contextlib
import hmac
import io
import json
from pathlib import Path
import re
import sqlite3
import tempfile
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('metadata_builder', ROOT / 'build_constellation_metadata.py')
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


class MetadataTests(unittest.TestCase):
    def test_formal_units_preserve_department_distinctions(self):
        self.assertEqual(builder.department_label('Department of Physics and Astronomy'), ('Department of Physics and Astronomy', False))
        self.assertEqual(builder.department_label('Department\\rof Chemistry'), ('Department of Chemistry', False))
        self.assertNotEqual(builder.department_label('Department of Chemistry')[0], builder.department_label('Department of Chemical Engineering')[0])
        self.assertNotEqual(builder.department_label('Department of Life Science')[0], builder.department_label('Department of Life Sciences')[0])

    def test_multiple_or_complex_departments_do_not_collapse(self):
        self.assertEqual(builder.department_label('Department of Chemistry and School of Molecular Science'), (None, True))
        self.assertEqual(builder.department_label('Department of Physics / Department of Astronomy'), (None, True))
        self.assertEqual(builder.department_label('Center for Optics and Department of Physics'), (None, True))
        self.assertEqual(builder.department_label('Department of Physics, Graduate School'), (None, True))

    def test_subjects_and_unrelated_units_are_not_departments(self):
        for value in ['physics', 'mathematics', 'College of Natural Sciences', 'Institute of Physics', 'Center for Applied Physics', None, '']:
            self.assertEqual(builder.department_label(value), (None, False))

    def test_unknown_countries_remain_unknown(self):
        self.assertEqual(builder.country('Korea'), 'KR')
        self.assertEqual(builder.country('United Kingdom'), 'GB')
        self.assertIsNone(builder.country(None))
        self.assertIsNone(builder.country('unknown'))

    def test_verified_overlay_rejects_identity_degree_and_source_mismatches(self):
        record = {
            'professor_uid': 'synthetic-person', 'anon_id': 'P-SYNTHETICX', 'source_author': 'Synthetic Author',
            'institution_unit_id': 'synthetic-unit', 'institution_canonical': 'Synthetic University',
            'source_institution_canonical': 'Synthetic University', 'award_year': 2016, 'source_award_year': 2016,
            'degree_level': 'phd', 'source_degree_level': 'phd', 'country': 'KR',
            'department': 'Department of Physics', 'source_department': 'Department of Physics',
            'checked_at': '2026-09-08T13:00:00Z', 'evidence_excerpt': 'Department of Physics',
            'source_url': 'https://www.riss.kr/link?id=T00000001', 'evidence_type': 'riss_dissertation',
            'verification_status': 'verified',
        }
        context = dict(uid='synthetic-person', public_id='P-SYNTHETICX', person_name='Synthetic Author',
            institution_ids={'synthetic-unit'}, institution_name='Synthetic University', award_year=2016)
        self.assertEqual(builder.validate_verified_record(record, **context), 'Department of Physics')
        for field, value in [
            ('professor_uid', 'other-person'), ('anon_id', 'P-OTHERIDXXX'), ('source_author', 'Namesake'),
            ('institution_unit_id', 'other-unit'), ('source_institution_canonical', 'Other University'),
            ('source_award_year', 2017), ('award_year', 2017), ('source_degree_level', 'master'),
            ('source_department', 'Department of Mathematics'), ('country', 'US'),
            ('verification_status', 'queued'), ('source_url', 'https://www.riss.kr/search/Search.do'),
            ('source_url', 'https://example.invalid/dissertation'), ('evidence_type', 'search_only'),
            ('evidence_excerpt', 'word ' * 26),
        ]:
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                builder.validate_verified_record({**record, field: value}, **context)

    def test_public_enrichment_coverage_and_schema(self):
        metadata = json.loads((ROOT.parents[1] / 'public/data/constellation_metadata.json').read_text())
        dashboard = json.loads((ROOT.parents[1] / 'public/data/dashboard.json').read_text())
        public = {person['id']: person for person in dashboard['professors']}
        self.assertEqual(set(metadata), set(public))
        self.assertEqual(len(metadata), 3937)
        degree_fields = {
            'phd_country', 'phd_department', 'phd_department_inferred', 'phd_department_evidence',
            'phd_institution_canonical', 'bachelor_institution_canonical',
            'phd_department_supporting_affiliations', 'bachelor_country', 'bachelor_department',
            'bachelor_department_inferred', 'bachelor_department_evidence', 'career_units',
            'faculty_appointments', 'current_position',
        }
        career_fields = {
            'segment_index', 'institution', 'start_year', 'end_year', 'country', 'department',
            'institution_canonical',
            'department_inferred', 'department_evidence', 'department_supporting_affiliations',
        }
        appointment_fields = {'institution', 'institution_canonical', 'country', 'department', 'department_inferred',
                              'department_evidence', 'start_year', 'end_year', 'role', 'evidence_kind',
                              'evidence_status', 'first_assistant_professor_verified'}
        current_fields = {'institution', 'institution_canonical', 'country', 'department', 'department_inferred',
                          'department_evidence', 'department_observation_year', 'observation_year', 'evidence_kind', 'evidence_status'}
        for public_id, row in metadata.items():
            self.assertRegex(public_id, r'^P-[A-Z2-7]{10}$')
            self.assertEqual(set(row), degree_fields)
            self.assertIsNone(row['bachelor_department'])
            self.assertFalse(row['bachelor_department_inferred'])
            if row['phd_department_evidence'] == 'verified_degree_record':
                self.assertTrue(row['phd_department'])
                self.assertFalse(row['phd_department_inferred'])
                self.assertEqual(row['phd_department_supporting_affiliations'], 0)
            else:
                self.assertEqual(bool(row['phd_department']), row['phd_department_inferred'])
                self.assertGreaterEqual(row['phd_department_supporting_affiliations'], bool(row['phd_department']))
            for appointment in row['faculty_appointments']:
                self.assertEqual(set(appointment) - {'rank'}, appointment_fields)
                self.assertEqual(appointment['role'], 'faculty')
                if appointment.get('first_assistant_professor_verified'):
                    self.assertEqual(appointment.get('rank'), 'assistant_professor')
                    self.assertEqual(appointment['evidence_status'], 'verified')
                    self.assertIn(appointment['evidence_kind'], {'official_profile', 'verified_cv'})
                self.assertIn(appointment['evidence_kind'], {'semester_roster', 'official_profile', 'verified_cv'})
                self.assertIn(appointment['evidence_status'], {'observed', 'verified'})
                if appointment['evidence_kind'] == 'semester_roster':
                    self.assertEqual(appointment['start_year'], appointment['end_year'])
                    self.assertEqual(appointment['evidence_status'], 'observed')
            if row['current_position']:
                self.assertEqual(set(row['current_position']), current_fields)
                self.assertEqual(row['current_position']['institution'], public[public_id]['current_institution'])
                self.assertLessEqual(row['current_position']['observation_year'], dashboard['meta']['release_year'])
            self.assertEqual(len(row['career_units']), len(public[public_id]['career']))
            for unit in row['career_units']:
                self.assertEqual(set(unit), career_fields)
                segment = public[public_id]['career'][unit['segment_index']]
                for field in ['institution', 'start_year', 'end_year']:
                    self.assertEqual(unit[field], segment[field])
                if unit['department_evidence'] == 'verified_degree_record':
                    self.assertTrue(unit['department'])
                    self.assertFalse(unit['department_inferred'])
                else:
                    self.assertEqual(bool(unit['department']), unit['department_inferred'])
                if unit['country'] is not None:
                    self.assertRegex(unit['country'], r'^[A-Z]{2}$')
        serialized = json.dumps(metadata)
        self.assertNotRegex(serialized, r'https?://|openalex\.org/A\d+|doi\.org/|orcid\.org/|\b\d{4}-\d{4}-\d{4}-\d{3}[\dX]\b')

    def test_manifest_binds_exact_source_and_metadata_bytes(self):
        manifest = json.loads((ROOT.parents[1] / 'public/data/constellation_metadata.manifest.json').read_text())
        data_path = ROOT.parents[1] / 'public/data/dashboard.json'
        public_bytes = data_path.read_bytes()
        metadata_bytes = (ROOT.parents[1] / 'public/data/constellation_metadata.json').read_bytes()
        self.assertEqual(manifest['public_data_sha256'], hashlib.sha256(public_bytes).hexdigest())
        self.assertEqual(manifest['metadata_sha256'], hashlib.sha256(metadata_bytes).hexdigest())
        self.assertEqual(manifest['release_year'], json.loads(public_bytes)['meta']['release_year'])
        changed = json.loads(public_bytes)
        changed['meta']['release_year'] += 1
        self.assertNotEqual(manifest['public_data_sha256'], hashlib.sha256(json.dumps(changed).encode()).hexdigest())
        # Even same-year replacements and metadata tampering must invalidate the join.
        self.assertNotEqual(manifest['public_data_sha256'], hashlib.sha256(public_bytes + b' ').hexdigest())
        self.assertNotEqual(manifest['metadata_sha256'], hashlib.sha256(metadata_bytes + b' ').hexdigest())

    def test_synthetic_source_provenance_does_not_use_current_department(self):
        # A complete synthetic source has no name column at all. This exercises
        # real builder joins without reading private identities in a test.
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            db = root / 'source.sqlite'
            connection = sqlite3.connect(db)
            connection.executescript('''
                CREATE TABLE professors(professor_uid TEXT);
                CREATE TABLE institution_units(unit_id TEXT,display_name TEXT,country_code TEXT);
                CREATE TABLE institution_aliases(raw_label TEXT,unit_id TEXT,confidence REAL);
                CREATE TABLE education(professor_uid TEXT,degree_level TEXT,institution_raw TEXT,institution_unit_id TEXT,country TEXT,award_year INTEGER);
                CREATE TABLE raw_affiliation_units(professor_uid TEXT,institution_unit_id TEXT,period TEXT,unit_label TEXT,work_id TEXT,identity_decision TEXT);
                INSERT INTO professors VALUES ('synthetic-one'),('synthetic-two'),('synthetic-three');
                INSERT INTO institution_units VALUES ('unit-domestic','Domestic Research University','KR'),('unit-foreign','Foreign Research University','US');
                INSERT INTO institution_aliases VALUES ('Domestic alias','unit-domestic',1.0),('uncertain alias','unit-foreign',0.4);
                INSERT INTO education VALUES
                    ('synthetic-one','phd','Domestic alias','unit-domestic','Korea',2010),
                    ('synthetic-two','phd','uncertain alias',NULL,NULL,2010),
                    ('synthetic-three','phd','Domestic alias','unit-domestic','Korea',2010);
                INSERT INTO raw_affiliation_units VALUES
                    ('synthetic-one','unit-domestic','2008-H1','Department of Physics','work-1','keep'),
                    ('synthetic-one','unit-domestic','2011-H1','Department of Chemistry','work-2','keep'),
                    ('synthetic-one','unit-domestic','2008-H1','Department of Biology','work-3','duplicate_drop_candidate'),
                    ('synthetic-one','unit-foreign','2008-H1','Department of Mathematics','work-4','keep'),
                    ('synthetic-three','unit-domestic','2008-H1','Department of Physics','work-5','keep'),
                    ('synthetic-three','unit-domestic','2009-H1','Department of Mathematics','work-6','keep');
            ''')
            connection.commit()
            connection.close()
            salt = bytes(range(32))
            salt_path = root / 'test-salt.bin'
            salt_path.write_bytes(salt)
            people = []
            ids = []
            for uid in ['synthetic-one', 'synthetic-two', 'synthetic-three']:
                public_id = 'P-' + base64.b32encode(hmac.new(salt, uid.encode(), hashlib.sha256).digest()).decode()[:10]
                ids.append(public_id)
                institution = 'uncertain alias' if uid == 'synthetic-two' else 'Domestic alias'
                people.append({
                    'id': public_id, 'phd_institution': institution, 'phd_country': None,
                    'department': 'Department of Current Affiliation Only', 'bachelor_institution': None,
                    'career': [{'stage': 'doctoral', 'institution': institution, 'start_period': '2005-H1', 'end_period': '2010-H2', 'start_year': 2005, 'end_year': 2010}],
                })
            public_path = root / 'dashboard.json'
            public_path.write_text(json.dumps({'meta': {'release_year': 2026}, 'professors': people}))
            args = SimpleNamespace(private_project=root, public_data=public_path, source_db=db, anon_salt=salt_path, year='2026', output=root / 'metadata.json')
            with contextlib.redirect_stdout(io.StringIO()):
                builder.run(args)
            output = json.loads(args.output.read_text())
            self.assertEqual(output[ids[0]]['phd_department'], 'Department of Physics')
            self.assertTrue(output[ids[0]]['phd_department_inferred'])
            self.assertEqual(output[ids[0]]['phd_institution_canonical'], 'Domestic Research University')
            self.assertEqual(output[ids[0]]['career_units'][0]['institution_canonical'], 'Domestic Research University')
            self.assertIsNone(output[ids[1]]['phd_department'])
            self.assertIsNone(output[ids[1]]['phd_institution_canonical'])
            self.assertIsNone(output[ids[1]]['phd_country'])
            self.assertIsNone(output[ids[2]]['phd_department'])
            self.assertEqual(output[ids[2]]['phd_department_evidence'], 'ambiguous_publication_departments')
            self.assertNotIn('Current Affiliation Only', args.output.read_text())
            self.assertNotIn('synthetic-one', args.output.read_text())
            self.assertNotIn('work-1', args.output.read_text())
            args.year = '2027'
            args.output = root / 'wrong-year.json'
            with self.assertRaisesRegex(ValueError, 'release year differ'):
                builder.run(args)
            self.assertFalse(args.output.exists())


    def test_lifetime_uses_observed_years_and_reviewed_sources_without_rank_promotion(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            db = root / 'source.sqlite'
            connection = sqlite3.connect(db)
            connection.executescript("""
                CREATE TABLE professors(professor_uid TEXT,name TEXT,latest_term TEXT,latest_institution_unit_id TEXT);
                CREATE TABLE semester_snapshots(professor_uid TEXT,term TEXT,year INTEGER,institution_unit_id TEXT,rank TEXT);
                CREATE TABLE institution_units(unit_id TEXT,display_name TEXT,country_code TEXT);
                CREATE TABLE institution_aliases(raw_label TEXT,unit_id TEXT,confidence REAL);
                CREATE TABLE education(professor_uid TEXT,degree_level TEXT,institution_raw TEXT,institution_unit_id TEXT,country TEXT,award_year INTEGER);
                CREATE TABLE raw_affiliation_units(professor_uid TEXT,institution_unit_id TEXT,period TEXT,unit_label TEXT,work_id TEXT,identity_decision TEXT);
                INSERT INTO professors VALUES ('synthetic-person','Private Synthetic Name','2024-fall','current-unit');
                INSERT INTO institution_units VALUES ('degree-unit','Degree University','KR'),('current-unit','Current University','KR');
                INSERT INTO education VALUES ('synthetic-person','phd','Degree University','degree-unit','KR',2010);
                INSERT INTO semester_snapshots VALUES
                    ('synthetic-person','2023-spring',2023,'current-unit','assistant'),
                    ('synthetic-person','2024-fall',2024,'current-unit','associate');
                INSERT INTO raw_affiliation_units VALUES
                    ('synthetic-person','current-unit','2023-H1','Department of Physics and Astronomy','secret-work','keep');
            """)
            connection.commit(); connection.close()
            salt = bytes(range(32))
            salt_path = root / 'salt.bin'; salt_path.write_bytes(salt)
            public_id = 'P-' + base64.b32encode(hmac.new(salt, b'synthetic-person', hashlib.sha256).digest()).decode()[:10]
            person = {'id': public_id, 'phd_institution': 'Degree University', 'phd_country': 'KR', 'phd_year': 2010,
                      'current_institution': 'Current University', 'department': 'Department of Physics',
                      'career': [{'stage': 'doctoral', 'institution': 'Degree University', 'start_period': '2005-H1', 'end_period': '2010-H2', 'start_year': 2005, 'end_year': 2010},
                                 {'stage': 'faculty', 'position_no': 1, 'institution': 'Degree University', 'start_year': 2010, 'end_year': 2026}]}
            public_path = root / 'dashboard.json'; public_path.write_text(json.dumps({'meta': {'release_year': 2026}, 'professors': [person]}))
            args = SimpleNamespace(private_project=root, public_data=public_path, source_db=db, anon_salt=salt_path, year='2026', output=root / 'metadata.json')
            with contextlib.redirect_stdout(io.StringIO()): builder.run(args)
            row = json.loads(args.output.read_text())[public_id]
            self.assertEqual([(a['start_year'], a['end_year']) for a in row['faculty_appointments']], [(2023, 2023), (2024, 2024)])
            self.assertTrue(all(a['evidence_status'] == 'observed' and not a['first_assistant_professor_verified'] for a in row['faculty_appointments']))
            self.assertEqual(row['faculty_appointments'][0]['rank'], 'assistant_professor')
            self.assertEqual(row['current_position']['institution'], 'Current University')
            self.assertEqual(row['current_position']['observation_year'], 2024)
            self.assertEqual(row['current_position']['department'], 'Department of Physics and Astronomy')
            self.assertTrue(row['current_position']['department_inferred'])
            self.assertEqual(row['current_position']['department_observation_year'], 2023)
            self.assertIsNone(row['phd_department'])
            record = {'professor_uid': 'synthetic-person', 'anon_id': public_id, 'person_name': 'Private Synthetic Name',
                      'verification_status': 'verified', 'checked_at': '2026-09-09T00:00:00Z',
                      'source_url': 'https://example.edu/faculty/profile', 'evidence_kind': 'official_profile',
                      'kind': 'phd_department', 'institution': 'Degree University', 'country': 'KR',
                      'department': 'Department of Physics', 'award_year': 2010}
            overlay = {'schema_version': 1, 'public_data_sha256': hashlib.sha256(public_path.read_bytes()).hexdigest(), 'records': [record,
                {**record, 'kind': 'faculty_appointment', 'start_year': 2001, 'end_year': 2026},
                {**record, 'kind': 'current_position', 'institution': 'Current University', 'observation_year': 2026}]}
            args.lifetime_evidence_json = root / 'private-overlay.json'; args.lifetime_evidence_json.write_text(json.dumps(overlay))
            with contextlib.redirect_stdout(io.StringIO()): builder.run(args)
            row = json.loads(args.output.read_text())[public_id]
            self.assertEqual(row['phd_department'], 'Department of Physics')
            self.assertFalse(row['phd_department_inferred'])
            self.assertEqual(row['phd_department_evidence'], 'verified_degree_record')
            self.assertEqual(row['faculty_appointments'][-1]['start_year'], 2001)
            self.assertEqual(row['faculty_appointments'][-1]['evidence_status'], 'verified')
            self.assertNotIn('rank', row['faculty_appointments'][-1])
            self.assertFalse(row['current_position']['department_inferred'])
            self.assertEqual(row['current_position']['observation_year'], 2026)
            for secret in ['synthetic-person', 'Private Synthetic Name', 'secret-work', 'https://example.edu']:
                self.assertNotIn(secret, args.output.read_text())
            # Reviewed claims must still match the exact release, person, degree,
            # country and interval; failed imports leave previous bytes untouched.
            valid_output = args.output.read_bytes()
            for field, bad in [('anon_id', 'P-OTHER'), ('person_name', 'Namesake'), ('award_year', 2011),
                               ('country', 'US'), ('institution', 'Current University'), ('verification_status', 'candidate')]:
                with self.subTest(field=field):
                    invalid = {**overlay, 'records': [{**record, field: bad}]}
                    args.lifetime_evidence_json.write_text(json.dumps(invalid))
                    with contextlib.redirect_stdout(io.StringIO()), self.assertRaises(ValueError): builder.run(args)
                    self.assertEqual(args.output.read_bytes(), valid_output)
            for changes in [{'start_year': 2027}, {'end_year': 2000}, {'first_assistant_professor_verified': True}, {'first_assistant_professor_verified': True, 'rank': 'assistant_professor'}]:
                args.lifetime_evidence_json.write_text(json.dumps({**overlay, 'records': [{**overlay['records'][1], **changes}]}))
                with contextlib.redirect_stdout(io.StringIO()), self.assertRaises(ValueError): builder.run(args)
                self.assertEqual(args.output.read_bytes(), valid_output)
            first = {**overlay['records'][1], 'rank': 'assistant_professor', 'first_assistant_professor_verified': True,
                     'first_assistant_evidence': 'complete_prior_employment_history_reviewed'}
            args.lifetime_evidence_json.write_text(json.dumps({**overlay, 'records': [first]}))
            with contextlib.redirect_stdout(io.StringIO()): builder.run(args)
            row = json.loads(args.output.read_text())[public_id]
            self.assertTrue(row['faculty_appointments'][-1]['first_assistant_professor_verified'])
            self.assertEqual(row['faculty_appointments'][-1]['rank'], 'assistant_professor')


if __name__ == '__main__':
    unittest.main()
