"""Synthetic offline RISS query planning tests; no real names, DBs, or requests."""
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

import build_riss_queue as builder


class RissQueueTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.project = self.root / 'source'
        (self.project / '.private').mkdir(parents=True)
        self.cache = self.project / 'backend/cache/2026'
        self.cache.mkdir(parents=True)
        self.salt = b'synthetic-riss-test-salt' * 2
        (self.project / '.private/anon_salt.bin').write_bytes(self.salt)
        self.db = self.root / 'synthetic.sqlite'
        with sqlite3.connect(self.db) as connection:
            connection.executescript('''
                CREATE TABLE professors(professor_uid TEXT,name TEXT,current_department TEXT);
                CREATE TABLE education(professor_uid TEXT,degree_level TEXT,institution_raw TEXT,
                    institution_unit_id TEXT,country TEXT,award_year INTEGER,inferred_start_year INTEGER);
                CREATE TABLE institution_units(unit_id TEXT,display_name TEXT,country_code TEXT);
                CREATE TABLE institution_aliases(raw_label TEXT,unit_id TEXT,confidence REAL);
                INSERT INTO institution_units VALUES('synthetic-unit','Synthetic University','KR');
                INSERT INTO institution_aliases VALUES('합성대학교','synthetic-unit',0.99);
            ''')
        (self.cache / 'source_db_path.txt').write_text(str(self.db))
        self.public = self.root / 'dashboard.json'
        self.records = []
        self.add_person('synthetic-person')
        self.output = self.root / 'private/riss-query-queue.json'

    def tearDown(self):
        self.temp.cleanup()

    def add_person(self, uid, *, unit='synthetic-unit', raw='Synthetic University',
                   country='Korea', award=2000, public_year=2000, name='합성연구자'):
        with sqlite3.connect(self.db) as connection:
            connection.execute('INSERT INTO professors VALUES(?,?,?)', (uid, name, 'NEVER USE CURRENT DEPARTMENT'))
            connection.execute('INSERT INTO education VALUES(?,?,?,?,?,?,?)',
                               (uid, 'phd', raw, unit, country, award, 1995))
        self.records.append({'id': builder.anonymous_id(uid, self.salt), 'phd_year': public_year,
                             'phd_institution': raw, 'department': 'NEVER USE PUBLIC CURRENT DEPARTMENT'})
        self.save_public()

    def save_public(self):
        self.public.write_text(json.dumps({'meta': {'release_year': 2026}, 'professors': self.records}))

    def sql(self, query, args=()):
        with sqlite3.connect(self.db) as connection:
            connection.execute(query, args)

    def build(self):
        return builder.build_queue(self.project, self.public, '2026', self.output)

    def test_exact_identity_and_canonical_query_anchors_private_output_source_unchanged(self):
        before = self.db.read_bytes()
        counts = self.build()
        queue = json.loads(self.output.read_text())
        self.assertEqual(counts['planned_queries'], 1)
        self.assertEqual(queue['public_data_sha256'], hashlib.sha256(self.public.read_bytes()).hexdigest())
        row = queue['researchers'][0]
        self.assertEqual(set(row), {'professor_uid','anon_id','name','institution_unit_id',
                                   'institution_canonical','institution_query','country','award_year','degree_level'})
        self.assertEqual(row['anon_id'], self.records[0]['id'])
        self.assertEqual(row['institution_canonical'], 'Synthetic University')
        self.assertEqual(row['institution_query'], '합성대학교')
        self.assertEqual(row['country'], 'KR')
        self.assertEqual(row['award_year'], 2000)
        self.assertEqual(row['degree_level'], 'phd')
        self.assertNotIn('DEPARTMENT', self.output.read_text())
        audit = self.output.with_suffix('.audit.json')
        for forbidden in ['합성연구자', 'synthetic-person', 'synthetic-unit', row['anon_id']]:
            self.assertNotIn(forbidden, audit.read_text())
        for path in (self.output, audit):
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.output.parent.stat().st_mode & 0o777, 0o700)
        self.assertEqual(self.db.read_bytes(), before)

    def test_requires_consistent_education_and_unit_country(self):
        self.sql("INSERT INTO institution_units VALUES('foreign-unit','Foreign University','US')")
        self.sql("INSERT INTO institution_units VALUES('unknown-unit','Unknown Country University',NULL)")
        self.add_person('source-foreign-unit-domestic', country='US')
        self.add_person('source-domestic-unit-foreign', unit='foreign-unit', raw='Foreign University')
        self.add_person('foreign', unit='foreign-unit', raw='Foreign University', country='US')
        self.add_person('missing-education-country', country=None)
        self.add_person('missing-unit-country', unit='unknown-unit', raw='Unknown Country University')
        counts = self.build()
        self.assertEqual(counts['planned_queries'], 1)
        self.assertEqual(counts['exclusions'], {'country_conflict': 2, 'missing_country_anchor': 2, 'non_domestic_phd': 1})

    def test_scope_default_foreign_and_all_keep_unique_exact_country_anchors(self):
        self.sql("INSERT INTO institution_units VALUES('foreign-unit','Foreign University','US')")
        self.sql("INSERT INTO institution_units VALUES('unknown-code','Unresolved University','ZZ')")
        self.add_person('foreign', unit='foreign-unit', raw='Foreign University', country='United States')
        self.add_person('country-conflict', unit='foreign-unit', raw='Foreign University', country='Korea')
        self.add_person('unknown-code', unit='unknown-code', raw='Unresolved University', country='ZZ')
        default_counts = self.build()  # Existing four-argument call remains domestic.
        default_rows = json.loads(self.output.read_text())['researchers']
        self.assertEqual(default_counts['domestic_queries'], 1)
        self.assertEqual(default_counts['foreign_queries'], 0)
        self.assertEqual(default_counts['exclusions'], {'country_conflict': 1, 'missing_country_anchor': 1, 'non_domestic_phd': 1})
        scope_rows = {}
        for scope, expected in [('foreign', 1), ('all', 2)]:
            output = self.output.with_name(scope + '.json')
            counts = builder.build_queue(self.project, self.public, '2026', output, scope=scope)
            scope_rows[scope] = json.loads(output.read_text())['researchers']
            self.assertEqual(counts['planned_queries'], expected)
            self.assertEqual(counts['exclusions']['country_conflict'], 1)
            self.assertEqual(counts['exclusions']['missing_country_anchor'], 1)
            self.assertEqual(json.loads(output.with_suffix('.audit.json').read_text())['scope'], scope)
        self.assertEqual(scope_rows['foreign'][0]['country'], 'US')
        self.assertEqual(scope_rows['foreign'][0]['institution_query'], 'Foreign University')
        all_ids = [r['anon_id'] for r in scope_rows['all']]
        self.assertEqual(len(all_ids), len(set(all_ids)))
        self.assertEqual(set(all_ids), {r['anon_id'] for r in default_rows + scope_rows['foreign']})
        self.assertEqual([r for r in scope_rows['all'] if r['country'] == 'KR'], default_rows)

    def test_invalid_scope_fails_before_private_input_reads(self):
        with patch.object(Path, 'read_text') as read, self.assertRaises(ValueError):
            builder.build_queue(self.project, self.public, '2026', self.output, scope='unrecognized')
        read.assert_not_called()

    def test_cli_foreign_scope_reaches_builder(self):
        self.sql("INSERT INTO institution_units VALUES('foreign-unit','Foreign University','GB')")
        self.add_person('foreign', unit='foreign-unit', raw='Foreign University', country='United Kingdom')
        args = ['build_riss_queue.py', '--private-project', str(self.project), '--public-data', str(self.public),
                '--output', str(self.output), '--scope', 'foreign']
        with patch.object(sys, 'argv', args), contextlib.redirect_stdout(io.StringIO()) as out:
            builder.main()
        self.assertEqual(json.loads(out.getvalue())['foreign_queries'], 1)
        rows = json.loads(self.output.read_text())['researchers']
        self.assertEqual([r['country'] for r in rows], ['GB'])

    def test_only_actual_award_year_matching_public_release(self):
        self.add_person('missing-actual', award=None)  # inferred_start_year cannot fill this.
        self.add_person('future-actual', award=2027, public_year=2027)
        self.add_person('old-invalid', award=1000, public_year=1000)
        self.add_person('public-mismatch', award=2001)
        self.add_person('public-missing', public_year=None)
        counts = self.build()
        self.assertEqual(counts['planned_queries'], 1)
        self.assertEqual(counts['exclusions'], {'missing_or_invalid_actual_award_year': 3, 'public_award_year_mismatch': 2})

    def test_multiple_phd_rows_including_equal_duplicates_require_review(self):
        self.sql("INSERT INTO education SELECT * FROM education WHERE professor_uid='synthetic-person'")
        self.add_person('missing-degree')
        self.sql("DELETE FROM education WHERE professor_uid='missing-degree'")
        self.add_person('distinct-degrees')
        self.sql("INSERT INTO education VALUES('distinct-degrees','phd','Synthetic University','synthetic-unit','KR',2001,1995)")
        counts = self.build()
        self.assertEqual(counts['planned_queries'], 0)
        self.assertEqual(counts['exclusions'], {'missing_phd_record': 1, 'multiple_phd_records': 2})

    def test_source_korean_raw_preferred_and_ambiguous_alias_not_translated(self):
        self.sql("UPDATE education SET institution_raw='합성대학교 대학원' WHERE professor_uid='synthetic-person'")
        self.add_person('ambiguous-alias', raw='101')
        self.sql("INSERT INTO institution_units VALUES('other-unit','Other University','KR')")
        self.sql("INSERT INTO institution_aliases VALUES('합성대학교','other-unit',0.99)")
        self.sql("INSERT INTO institution_aliases VALUES('추측대학교','synthetic-unit',0.5)")
        counts = self.build()
        rows = {row['professor_uid']: row for row in json.loads(self.output.read_text())['researchers']}
        self.assertEqual(rows['synthetic-person']['institution_query'], '합성대학교 대학원')
        self.assertEqual(rows['ambiguous-alias']['institution_query'], 'Synthetic University')
        self.assertEqual(counts['query_label_sources'], {'existing_canonical_fallback': 1, 'korean_education_raw': 1})

    def test_conflicting_labels_missing_unit_invalid_canonical_and_missing_name_excluded(self):
        self.sql("INSERT INTO institution_units VALUES('other-unit','Other University','KR')")
        self.sql("INSERT INTO institution_units VALUES('numeric-unit','101','KR')")
        self.add_person('conflicting-label', raw='Other University')
        self.add_person('missing-unit', unit='orphan', raw='Unresolved University')
        self.add_person('numeric-canonical', unit='numeric-unit', raw='101')
        self.add_person('missing-name', name=' ')
        counts = self.build()
        self.assertEqual(counts['planned_queries'], 1)
        self.assertEqual(counts['exclusions'], {'institution_label_conflict': 1,
            'missing_or_ambiguous_institution_unit': 1, 'invalid_institution_label': 1, 'missing_or_invalid_source_name': 1})

    def test_exact_unambiguous_unit_fallback_matches_metadata_canonical(self):
        self.sql("UPDATE education SET institution_unit_id=NULL")
        self.assertEqual(self.build()['planned_queries'], 1)
        row = json.loads(self.output.read_text())['researchers'][0]
        self.assertEqual(row['institution_unit_id'], 'synthetic-unit')
        self.assertEqual(row['institution_canonical'], 'Synthetic University')

    def test_release_identity_and_year_mismatches_fail_closed(self):
        self.records[0]['id'] = 'P-SYNTHETIC'
        self.save_public()
        with self.assertRaises(ValueError):
            self.build()
        self.assertFalse(self.output.exists())
        with self.assertRaises(ValueError):
            builder.build_queue(self.project, self.public, '../2026', self.output)

    def test_private_guard_sidecar_guard_and_no_overwrite_preserve_existing_files(self):
        for directory in ['public', 'DiSt', 'Downloads', 'release', 'releases', 'outputs']:
            with self.subTest(directory=directory), self.assertRaises(ValueError):
                builder.build_queue(self.project, self.public, '2026', self.root / directory / 'private/queue.json')
        repo = self.root / 'repository'
        repo.mkdir()
        subprocess.run(['git', 'init', '-q', str(repo)], check=True, capture_output=True)
        (repo / '.gitignore').write_text('private/queue.json\n')
        with self.assertRaises(ValueError):
            builder.build_queue(self.project, self.public, '2026', repo / 'private/queue.json')
        self.assertFalse((repo / 'private/queue.json').exists())
        self.assertFalse((repo / 'private/queue.audit.json').exists())
        self.build()
        before = self.output.read_bytes()
        with self.assertRaises(FileExistsError):
            self.build()
        self.assertEqual(self.output.read_bytes(), before)

    def test_cli_never_echoes_private_exception_or_arguments_and_stdout_only_counts(self):
        argv = ['build_riss_queue.py', '--private-project', str(self.project), '--public-data', str(self.public),
                '--year', '2026', '--output', str(self.output)]
        stdout, stderr = io.StringIO(), io.StringIO()
        with patch.object(sys, 'argv', argv), contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            builder.main()
        self.assertEqual(json.loads(stdout.getvalue())['planned_queries'], 1)
        self.assertEqual(stderr.getvalue(), '')
        self.assertNotIn('합성연구자', stdout.getvalue())
        with (patch.object(sys, 'argv', argv), patch.object(builder, 'build_queue', side_effect=ValueError('SECRET NAME /PRIVATE/PATH')),
              contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(stderr)):
            with self.assertRaises(SystemExit):
                builder.main()
        self.assertNotIn('SECRET', stderr.getvalue())
        self.assertNotIn('/PRIVATE/PATH', stderr.getvalue())


if __name__ == '__main__':
    unittest.main()
