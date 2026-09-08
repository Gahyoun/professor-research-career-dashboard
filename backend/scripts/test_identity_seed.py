"""Synthetic seed-generator tests; never load actual researcher data or salts."""
import contextlib
import io
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import build_identity_seed as builder


def synthetic_orcid():
    base = '000000000000001'
    total = 0
    for digit in base:
        total = (total + int(digit)) * 2
    check = (12 - total % 11) % 11
    digits = base + ('X' if check == 10 else str(check))
    return '-'.join(digits[i:i + 4] for i in range(0, 16, 4))


class IdentitySeedTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.project = self.root / 'source'
        (self.project / '.private').mkdir(parents=True)
        self.cache = self.project / 'backend/cache/2026'
        self.cache.mkdir(parents=True)
        self.salt = b'synthetic-test-salt' * 2
        (self.project / '.private/anon_salt.bin').write_bytes(self.salt)
        self.db = self.root / 'synthetic.sqlite'
        self.orcid = synthetic_orcid()
        with sqlite3.connect(self.db) as connection:
            connection.execute('CREATE TABLE professors(professor_uid TEXT,source_professor_id TEXT,openalex_id TEXT,orcid TEXT,identity_confidence TEXT)')
            connection.executemany('INSERT INTO professors VALUES(?,?,?,?,?)', [
                ('synthetic-1', 'ROW-1', 'A1', self.orcid, 'high'),
                ('synthetic-2', 'ROW-2', 'A1', self.orcid[:-1] + ('0' if self.orcid[-1] != '0' else '1'), 'medium'),
                ('synthetic-3', None, None, None, 'medium'),
            ])
        (self.cache / 'source_db_path.txt').write_text(str(self.db))
        (self.cache / 'author_aliases.json').write_text(json.dumps([
            {'source_professor_id': 'row1', 'name': 'MUST NOT COPY', 'openalex_ids': ['A1', 'https://openalex.org/A2']},
            {'source_professor_id': 'unmatched', 'openalex_ids': ['A3']},
        ]))
        self.public = self.root / 'dashboard.json'
        self.public.write_text(json.dumps({'meta': {'release_year': 2026}, 'professors': [
            {'id': builder.anonymous_id(f'synthetic-{i}', self.salt)} for i in (1, 2, 3)
        ]}))
        self.output = self.root / 'private/seed.json'

    def tearDown(self):
        self.temp.cleanup()

    def build(self):
        return builder.build_seed(self.project, self.public, '2026', self.output)

    def git_repo(self):
        repo = self.root / 'repository'
        repo.mkdir()
        subprocess.run(['git', 'init', '-q', str(repo)], check=True, capture_output=True)
        return repo

    def test_source_claims_dedup_private_modes_and_source_unchanged(self):
        before = self.db.read_bytes()
        counts = self.build()
        seed = json.loads(self.output.read_text())
        self.assertEqual(counts['researchers'], 3)
        self.assertEqual(counts['openalex_person_links'], 3)
        self.assertEqual(counts['openalex_collision_groups'], 1)
        self.assertEqual(counts['unmatched_alias_records'], 1)
        self.assertEqual(seed['researchers'][0]['openalex_author_ids'], ['A1', 'A2'])
        self.assertEqual(seed['identifier_links'][0]['status'], 'candidate')
        self.assertNotIn('MUST NOT COPY', self.output.read_text())
        for path in (self.output, self.output.with_suffix('.audit.json'), self.output.with_suffix('.invalid-identifiers.json')):
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.output.parent.stat().st_mode & 0o777, 0o700)
        self.assertEqual(before, self.db.read_bytes())

    def test_checksum_quarantine_audit_contains_only_counts_and_labels(self):
        counts = self.build()
        self.assertEqual(counts['invalid_orcids'], 1)
        self.assertEqual(counts['orcid_candidate_links'], 1)
        audit = self.output.with_suffix('.audit.json').read_text()
        self.assertNotIn('synthetic-', audit)
        self.assertNotIn(self.orcid, audit)
        rejected = json.loads(self.output.with_suffix('.invalid-identifiers.json').read_text())
        self.assertEqual(len(rejected['invalid_identifiers']), 1)

    def test_openalex_registry_pattern_and_invalid_alias_quarantine(self):
        for value in ['A0', 'A01', 'A' + '1' * 22, 'a1', 'http://openalex.org/A1', 'https://example.org/A1', 'A1\n', 1]:
            self.assertIsNone(builder.normalize_openalex(value))
        for value in ['A1', 'A' + '1' * 21, 'https://openalex.org/A42']:
            self.assertIsNotNone(builder.normalize_openalex(value))
        (self.cache / 'author_aliases.json').write_text(json.dumps([
            {'source_professor_id': 'row1', 'openalex_ids': ['A01', 'A7']}
        ]))
        with sqlite3.connect(self.db) as connection:
            connection.execute("UPDATE professors SET openalex_id='A0' WHERE professor_uid='synthetic-2'")
        counts = self.build()
        self.assertEqual(counts['invalid_identifiers'], 3)
        seed = json.loads(self.output.read_text())
        self.assertEqual(seed['researchers'][0]['openalex_author_ids'], ['A1', 'A7'])
        self.assertEqual(seed['researchers'][1]['openalex_author_ids'], [])

    def test_never_overwrites_any_output(self):
        self.build()
        before = self.output.read_bytes()
        with self.assertRaises(FileExistsError):
            self.build()
        self.assertEqual(before, self.output.read_bytes())

    def test_existing_audit_prevents_partial_seed_creation(self):
        self.output.parent.mkdir()
        audit = self.output.with_suffix('.audit.json')
        audit.write_text('existing synthetic audit')
        with self.assertRaises(FileExistsError):
            self.build()
        self.assertFalse(self.output.exists())
        self.assertEqual(audit.read_text(), 'existing synthetic audit')

    def test_publication_directories_rejected_case_insensitively(self):
        for directory in ['public', 'DIST', 'Downloads', 'Release', 'reLEASEs', 'Outputs']:
            with self.assertRaises(ValueError):
                builder.private_output(self.root / directory / 'private/seed.json')
        with self.assertRaises(ValueError):
            builder.private_output(self.root / 'seed.json')

    def test_symlink_components_and_dangling_output_are_rejected(self):
        real = self.root / 'private'
        real.mkdir()
        link = self.root / 'shortcut'
        link.symlink_to(real, target_is_directory=True)
        for path in [link / 'seed.json', link / '../private/seed.json']:
            with self.assertRaises(ValueError):
                builder.private_output(path)
        dangling = real / 'dangling.json'
        dangling.symlink_to(real / 'absent.json')
        with self.assertRaises(ValueError):
            builder.private_output(dangling)

    def test_git_output_requires_untracked_and_ignored(self):
        repo = self.git_repo()
        candidate = repo / '.private/seed.json'
        with self.assertRaises(ValueError):
            builder.private_output(candidate)
        (repo / '.gitignore').write_text('.private/\n')
        self.assertEqual(builder.private_output(candidate), candidate)
        candidate.write_text('synthetic only')
        subprocess.run(['git', '-C', str(repo), 'add', '-f', '--', '.private/seed.json'], check=True, capture_output=True)
        with self.assertRaises(ValueError):
            builder.private_output(candidate)

    def test_git_ignore_guard_also_covers_audit_and_rejected_identifiers(self):
        repo = self.git_repo()
        (repo / '.gitignore').write_text('.private/seed.json\n')
        self.output = repo / '.private/seed.json'
        with self.assertRaises(ValueError):
            self.build()
        self.assertFalse(self.output.exists())
        self.assertFalse(self.output.with_suffix('.audit.json').exists())
        (repo / '.gitignore').write_text('.private/seed.json\n.private/seed.audit.json\n')
        with self.assertRaises(ValueError):
            self.build()
        self.assertFalse(self.output.exists())
        (repo / '.gitignore').write_text('.private/\n')
        self.assertEqual(self.build()['researchers'], 3)

    def test_mismatched_public_release_fails_before_output(self):
        public = json.loads(self.public.read_text())
        public['professors'].pop()
        self.public.write_text(json.dumps(public))
        with self.assertRaises(ValueError):
            self.build()
        self.assertFalse(self.output.exists())

    def test_cli_hides_exception_identity_and_path_values(self):
        secret = 'PRIVATE_UID_AND_PATH_DO_NOT_PRINT'
        argv = ['build_identity_seed.py', '--private-project', secret, '--public-data', secret,
                '--output', secret]
        error = io.StringIO()
        with patch.object(sys, 'argv', argv), patch.object(builder, 'build_seed', side_effect=RuntimeError(secret)), contextlib.redirect_stderr(error):
            with self.assertRaises(SystemExit) as result:
                builder.main()
        self.assertEqual(result.exception.code, 1)
        self.assertNotIn(secret, error.getvalue())
        self.assertNotIn('Traceback', error.getvalue())
        error = io.StringIO()
        with patch.object(sys, 'argv', ['build_identity_seed.py', '--unknown', secret]), contextlib.redirect_stderr(error):
            with self.assertRaises(SystemExit) as result:
                builder.main()
        self.assertEqual(result.exception.code, 2)
        self.assertNotIn(secret, error.getvalue())


if __name__ == '__main__':
    unittest.main()
