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
        }
        career_fields = {
            'segment_index', 'institution', 'start_year', 'end_year', 'country', 'department',
            'institution_canonical',
            'department_inferred', 'department_evidence', 'department_supporting_affiliations',
        }
        for public_id, row in metadata.items():
            self.assertRegex(public_id, r'^P-[A-Z2-7]{10}$')
            self.assertEqual(set(row), degree_fields)
            self.assertIsNone(row['bachelor_department'])
            self.assertFalse(row['bachelor_department_inferred'])
            self.assertEqual(bool(row['phd_department']), row['phd_department_inferred'])
            self.assertGreaterEqual(row['phd_department_supporting_affiliations'], bool(row['phd_department']))
            self.assertEqual(len(row['career_units']), len(public[public_id]['career']))
            for unit in row['career_units']:
                self.assertEqual(set(unit), career_fields)
                segment = public[public_id]['career'][unit['segment_index']]
                for field in ['institution', 'start_year', 'end_year']:
                    self.assertEqual(unit[field], segment[field])
                self.assertEqual(bool(unit['department']), unit['department_inferred'])
                if unit['country'] is not None:
                    self.assertRegex(unit['country'], r'^[A-Z]{2}$')
        serialized = json.dumps(metadata)
        self.assertNotRegex(serialized, r'openalex\.org/A\d+|doi\.org/|orcid\.org/|\b\d{4}-\d{4}-\d{4}-\d{3}[\dX]\b')

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


if __name__ == '__main__':
    unittest.main()
