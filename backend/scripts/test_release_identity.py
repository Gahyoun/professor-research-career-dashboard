import contextlib
import csv
import gzip
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest

from release_identity import (
    IDENTITY_FILTER_VERSION, STRICT_IDENTITY_PREDICATE,
    PublicationIdentityGate, decision_database_path, register_author_alias, alias_professor_uid,
)

SCRIPTS = Path(__file__).resolve().parent
PROJECT = SCRIPTS.parents[1]


def load_topic_module(name, filename):
    spec = importlib.util.spec_from_file_location(name, PROJECT / 'backend/topics' / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class IdentityGateTests(unittest.TestCase):
    def setUp(self):
        self.connection = sqlite3.connect(':memory:')
        self.addCleanup(self.connection.close)
        self.connection.executescript('''
            CREATE TABLE work_authorship_evidence(professor_uid TEXT,work_id TEXT,identity_decision TEXT);
            ATTACH DATABASE ':memory:' AS koad;
            CREATE TABLE koad.work_decision(professor_uid TEXT,work_id TEXT,decision TEXT);
            INSERT INTO work_authorship_evidence VALUES
                ('person-one','accepted','keep'),('person-one','unclassified','keep'),
                ('person-one','namesake','keep'),('person-one','other-person-decision','keep'),
                ('person-one','quarantined','duplicate_drop_candidate');
            INSERT INTO koad.work_decision VALUES
                ('person-one','accepted','true_paper'),('person-one','namesake','namesake_paper'),
                ('person-two','other-person-decision','true_paper'),
                ('person-one','quarantined','true_paper'),('person-one','missing-source','true_paper');
        ''')

    def test_only_positive_same_person_work_with_kept_source_is_public(self):
        gate = PublicationIdentityGate.from_connection(self.connection)
        self.assertIsNone(gate.exclusion_reason('person-one', 'accepted'))
        self.assertEqual(gate.exclusion_reason('person-one', 'unclassified'), 'missing_koad_decision')
        self.assertEqual(gate.exclusion_reason('person-one', 'other-person-decision'), 'missing_koad_decision')
        self.assertEqual(gate.exclusion_reason('person-one', 'namesake'), 'namesake_paper')
        self.assertEqual(gate.exclusion_reason('person-one', 'quarantined'), 'missing_kept_source_evidence')
        self.assertEqual(gate.exclusion_reason('person-one', 'missing-source'), 'missing_kept_source_evidence')
        self.assertEqual(gate.unclassified_kept_source_count, 2)
        retained = self.connection.execute(
            'SELECT w.work_id FROM work_authorship_evidence w WHERE ' +
            STRICT_IDENTITY_PREDICATE.format(alias='w')
        ).fetchall()
        self.assertEqual(retained, [('accepted',)])

    def test_shared_profile_candidates_still_require_individual_work_decisions(self):
        aliases = {}
        owners = {'primary-one': 'person-one', 'primary-two': 'person-two'}
        register_author_alias(aliases, owners, 'alias-one', 'person-one')
        register_author_alias(aliases, owners, 'alias-one', 'person-one')
        register_author_alias(aliases, owners, 'alias-one', 'person-two')
        register_author_alias(aliases, owners, 'primary-two', 'person-one')
        self.assertEqual(aliases['alias-one'], {'person-one', 'person-two'})
        self.connection.execute("INSERT INTO work_authorship_evidence VALUES('person-two','accepted','keep')")
        self.connection.execute("INSERT INTO koad.work_decision VALUES('person-two','accepted','namesake_paper')")
        gate = PublicationIdentityGate.from_connection(self.connection)
        public_candidates = [uid for uid in aliases['alias-one'] if gate.exclusion_reason(uid, 'accepted') is None]
        self.assertEqual(public_candidates, ['person-one'])
        self.assertEqual(alias_professor_uid({'professor_uid': 'person-two', 'source_professor_id': 'stale'},
                                            {'person-one', 'person-two'}, {'stale': 'person-one'}), 'person-two')
        with self.assertRaisesRegex(ValueError, 'unknown researcher'):
            alias_professor_uid({'professor_uid': 'absent'}, {'person-one'}, {})
        self.assertIsNone(alias_professor_uid({'source_professor_id': None}, {'person-one'}, {'': 'person-one'}))

    def test_review_keeps_source_policy_without_overriding_namesakes(self):
        adapter = load_topic_module('synthetic_verdicts', 'koad_verdicts.py')
        gate = PublicationIdentityGate.from_connection(self.connection)
        records = [
            {'professor_uid': 'person-one', 'work_id': work, 'decision': decision, 'recommended_action': 'review'}
            for work, decision in [('accepted', 'true_paper'), ('namesake', 'namesake_paper'), ('missing-source', 'true_paper')]
        ]
        for policy in ('source', 'keep'):
            verdicts, counts = adapter.build_verdicts(records, 'person-one', gate, policy)
            self.assertEqual([v['work_id'].rsplit('/', 1)[-1] for v in verdicts if v['is_target']], ['accepted'])
            self.assertEqual(counts, {'keep': 1, 'drop': 2, 'review': 3})
        self.assertFalse(any(v['is_target'] for v in adapter.build_verdicts(records, 'person-one', gate, 'drop')[0]))
        self.assertEqual(adapter.build_verdicts(records, 'person-one', gate, 'skip')[0], [])
        conflicting = records + [{**records[0], 'decision': 'namesake_paper'}]
        with self.assertRaisesRegex(ValueError, 'Conflicting'):
            adapter.build_verdicts(conflicting, 'person-one', gate)

    def test_prepared_decision_pointer_does_not_follow_another_source(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'source_db_path.txt').write_text(str(root / 'prepared.sqlite'))
            (root / 'identity_decisions_path.txt').write_text(str(root / 'reviewed.sqlite'))
            self.assertEqual(decision_database_path(root / 'prepared.sqlite', root), root / 'reviewed.sqlite')
            self.assertEqual(decision_database_path(root / 'other.sqlite', root), root.resolve() / 'identity_decisions.sqlite')
            self.assertEqual(decision_database_path(root / 'other.sqlite', root, root / 'explicit.sqlite'), root / 'explicit.sqlite')


class PublicReleaseIntegrationTests(unittest.TestCase):
    def test_alias_cache_cannot_publish_unclassified_works_or_another_coauthors_role(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            cache = root / 'backend/cache/2026'
            cache.mkdir(parents=True)
            sql = root / 'backend/sql'
            sql.mkdir()
            for filename in ('schema_public.sql', 'queries_public.sql'):
                shutil.copy2(PROJECT / 'backend/sql' / filename, sql / filename)
            source = root / 'source.sqlite'
            with sqlite3.connect(source) as connection:
                connection.executescript('''
                    CREATE TABLE professors(professor_uid TEXT,source_professor_id TEXT,name TEXT,subject TEXT,openalex_id TEXT,
                        phd_year INTEGER,appointment_year INTEGER,latest_institution_raw TEXT,latest_institution_unit_id TEXT);
                    INSERT INTO professors VALUES('person-one','SYNTH_1','Synthetic Person','physics','primary-one',2000,2010,'Synthetic University','unit-one');
                    CREATE TABLE institution_units(unit_id TEXT,display_name TEXT,country_code TEXT,institution_type TEXT);
                    INSERT INTO institution_units VALUES('unit-one','Synthetic University','KR','education');
                    CREATE TABLE institution_aliases(raw_label TEXT,unit_id TEXT,confidence REAL,context TEXT);
                    CREATE TABLE education(professor_uid TEXT,degree_level TEXT,institution_raw TEXT,institution_unit_id TEXT,
                        country TEXT,award_year INTEGER,inferred_start_year INTEGER);
                    CREATE TABLE career_positions_v2(professor_uid TEXT,position_type TEXT,position_no INTEGER,institution_unit_id TEXT,
                        institution_name TEXT,start_period TEXT,end_period TEXT,start_year INTEGER,end_year INTEGER,confidence TEXT,
                        reasoning TEXT,is_institution_successor INTEGER,evidence_status TEXT);
                    CREATE TABLE raw_affiliation_units(professor_uid TEXT,work_id TEXT,identity_decision TEXT,institution_unit_id TEXT,
                        unit_label TEXT,period TEXT,institution_name TEXT);
                    INSERT INTO raw_affiliation_units VALUES
                        ('person-one','accepted','keep','unit-one','Department of Physics','2012-H1','Synthetic University'),
                        ('person-one','unclassified','keep','unit-one','Department of Wrong Namesake','2026-H1','Synthetic University');
                    CREATE TABLE work_authorship_evidence(professor_uid TEXT,openalex_id TEXT,work_id TEXT,
                        publication_year INTEGER,work_type TEXT,identity_decision TEXT);
                ''')
                works = [('accepted', 'primary-one', 'keep'), ('new-accepted', 'alias-one', 'keep'),
                         ('review-accepted', 'alias-one', 'keep'), ('unclassified', 'primary-one', 'keep'),
                         ('namesake', 'alias-one', 'keep'), ('other-person-decision', 'alias-one', 'keep'),
                         ('quarantined', 'alias-one', 'duplicate_drop_candidate')]
                connection.executemany('INSERT INTO work_authorship_evidence VALUES(?,?,?,?,?,?)',
                    [('person-one', author, work, 2012, 'article', decision) for work, author, decision in works])
            decisions = root / 'reviewed.sqlite'
            with sqlite3.connect(decisions) as connection:
                connection.execute('CREATE TABLE work_decision(professor_uid TEXT,work_id TEXT,decision TEXT,recommended_action TEXT)')
                connection.executemany('INSERT INTO work_decision VALUES(?,?,?,?)', [
                    ('person-one', 'accepted', 'true_paper', 'keep'), ('person-one', 'new-accepted', 'true_paper', 'keep'),
                    ('person-one', 'review-accepted', 'true_paper', 'review'), ('person-one', 'namesake', 'namesake_paper', 'review'),
                    ('person-two', 'other-person-decision', 'true_paper', 'keep'),
                    ('person-one', 'quarantined', 'true_paper', 'review'), ('person-one', 'missing-source', 'true_paper', 'keep'),
                ])
            (cache / 'source_db_path.txt').write_text(str(source))
            (cache / 'identity_decisions_path.txt').write_text(str(decisions))
            (cache / 'sources.json').write_text('{}')
            (cache / 'author_aliases.json').write_text(json.dumps([{'professor_uid': 'person-one', 'source_professor_id': None,
                'openalex_ids': ['primary-one', 'alias-one']}]))
            def role(work, author='alias-one'):
                return {'target_author_id': author, 'work_id': work, 'publication_year': 2012, 'work_type': 'article',
                        'author_position': 'first', 'is_corresponding': True,
                        'source': {'id': 'synthetic-journal', 'type': 'journal', 'display_name': 'Synthetic Journal'}}
            for dirname, records in (
                # One paper has the selected researcher in the middle and an
                # alias-profile coauthor first: a work verdict cannot transfer
                # the coauthor's first-author position to the researcher.
                ('work_role_batches', [{**role('accepted', 'primary-one'), 'author_position': 'middle', 'is_corresponding': False},
                                       role('unclassified', 'primary-one'), role('new-accepted')]),
                ('alias_work_role_batches', [role(work) for work in (
                    'accepted', 'new-accepted', 'new-accepted', 'review-accepted', 'unclassified',
                    'namesake', 'other-person-decision', 'quarantined', 'missing-source', 'missing-decision')]
                    + [{**role('unclassified-middle-author'), 'author_position': 'middle', 'is_corresponding': False}]),
            ):
                (cache / dirname).mkdir()
                with gzip.open(cache / dirname / 'batch_synthetic.jsonl.gz', 'wt') as stream:
                    stream.writelines(json.dumps(record) + '\n' for record in records)
            original_bytes = source.read_bytes()
            result = subprocess.run([sys.executable, str(SCRIPTS / 'build_release.py'), '--project-root', str(root)],
                env={**os.environ, 'NAMES_PASSWORD': 'synthetic-only-test-password'}, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            public = json.loads((root / 'public/data/dashboard.json').read_text())
            self.assertEqual(public['meta']['identity_filter_version'], IDENTITY_FILTER_VERSION)
            self.assertEqual(public['professors'][0]['lead_work_count'], 2)
            self.assertEqual(public['professors'][0]['department'], 'Department of Physics')
            self.assertEqual(public['meta']['secondary_openalex_lead_work_count'], 2)
            self.assertEqual(public['meta']['secondary_openalex_role_exclusions'], {'different_selected_author': 1})
            self.assertEqual(public['meta']['koad_unclassified_source_keep_excluded'], 2)
            self.assertEqual(public['meta']['secondary_openalex_identity_exclusions'], {
                'missing_koad_decision': 4, 'missing_kept_source_evidence': 2, 'namesake_paper': 1,
            })
            self.assertEqual(source.read_bytes(), original_bytes)
            text = json.dumps(public)
            for private_value in ('Synthetic Person', 'person-one', 'primary-one', 'alias-one', 'new-accepted'):
                self.assertNotIn(private_value, text)

    def test_topic_selection_excludes_missing_decisions_and_handles_empty_kept_set(self):
        topics = load_topic_module('synthetic_topic_release', 'build_release_topics.py')
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            cache = root / 'backend/cache/2026'
            cache.mkdir(parents=True)
            source = root / 'source.sqlite'
            with sqlite3.connect(source) as connection:
                connection.executescript('''
                    CREATE TABLE professors(professor_uid TEXT,phd_year INTEGER);
                    INSERT INTO professors VALUES('person-one',2010);
                    CREATE TABLE work_authorship_evidence(professor_uid TEXT,work_id TEXT,publication_year INTEGER,
                        work_type TEXT,identity_decision TEXT,doi TEXT,title TEXT);
                    INSERT INTO work_authorship_evidence VALUES('person-one','unclassified',2012,'article','keep','','Synthetic title');
                ''')
            with sqlite3.connect(root / 'identity_decisions.sqlite') as connection:
                connection.execute('CREATE TABLE work_decision(professor_uid TEXT,work_id TEXT,decision TEXT)')
            (cache / 'source_db_path.txt').write_text(str(source))
            args = SimpleNamespace(private=root, work_dir=root / 'private-work')
            with contextlib.redirect_stdout(io.StringIO()):
                topics.cmd_select(args)
            with open(args.work_dir / '01_selected.csv') as stream:
                self.assertEqual(list(csv.DictReader(stream)), [])
            with open(args.work_dir / '01_dropped.csv') as stream:
                self.assertEqual(next(csv.DictReader(stream))['reason'], 'missing_koad_decision')
            with sqlite3.connect(source) as connection:
                connection.executemany('INSERT INTO work_authorship_evidence VALUES(?,?,?,?,?,?,?)', [
                    ('person-one', 'accepted', 2012, 'article', 'keep', '', 'Synthetic accepted title'),
                    ('person-one', 'too-early', 2004, 'article', 'keep', '', 'Synthetic early title'),
                ])
            with sqlite3.connect(root / 'identity_decisions.sqlite') as connection:
                connection.executemany('INSERT INTO work_decision VALUES(?,?,?)', [
                    ('person-one', 'accepted', 'true_paper'), ('person-one', 'too-early', 'true_paper'),
                ])
            with contextlib.redirect_stdout(io.StringIO()):
                topics.cmd_select(args)
            with open(args.work_dir / '01_selected.csv') as stream:
                self.assertEqual([r['work_id'] for r in csv.DictReader(stream)], ['accepted'])
            with open(args.work_dir / '01_dropped.csv') as stream:
                self.assertEqual({r['reason'] for r in csv.DictReader(stream)}, {'missing_koad_decision', 'before_phd_minus_five'})


if __name__ == '__main__':
    unittest.main()
