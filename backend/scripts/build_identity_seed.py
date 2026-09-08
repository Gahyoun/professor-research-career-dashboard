#!/usr/bin/env python3
"""Seed a private candidate identity registry from existing source claims.

Reads the original SQLite database and anonymization salt without changing them.
Existing primary OpenAlex IDs and annotated aliases are imported claims, not new
identity verification. ORCID links remain candidates, including when the source
author profile carries the same ORCID. Never infer KRI/NRI from roster identifiers.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess
from collections import defaultdict

FORBIDDEN_DIRECTORIES = {'public', 'dist', 'downloads', 'release', 'releases', 'outputs'}


def normalized_source_id(value: str | None) -> str:
    """Match the release import's existing roster-ID normalization exactly."""
    return re.sub(r'[^a-z0-9]', '', (value or '').lower())


def normalize_openalex(value: str | None) -> str | None:
    if not isinstance(value, str) or not value or len(value) > 100 or any(ord(c) < 32 for c in value):
        return None
    match = re.fullmatch(r'(?:https://openalex\.org/)?(A[1-9][0-9]{0,20})', value.strip())
    return match.group(1) if match else None


def normalize_orcid(value: str | None) -> str | None:
    """Canonical bare ORCID with ISO 7064 MOD 11-2 checksum verification."""
    if not value:
        return None
    clean = re.sub(r'^https?://orcid\.org/', '', value.strip(), flags=re.I).rstrip('/').upper()
    compact = clean.replace('-', '')
    if not re.fullmatch(r'[0-9]{15}[0-9X]', compact):
        return None
    total = 0
    for digit in compact[:15]:
        total = (total + int(digit)) * 2
    check = (12 - total % 11) % 11
    if compact[-1] != ('X' if check == 10 else str(check)):
        return None
    return '-'.join(compact[i:i + 4] for i in range(0, 16, 4))


def anonymous_id(uid: str, salt: bytes) -> str:
    digest = hmac.new(salt, uid.encode(), hashlib.sha256).digest()
    return 'P-' + base64.b32encode(digest).decode().rstrip('=')[:10]


def private_output(path: Path) -> Path:
    expanded = path.expanduser()
    absolute = expanded if expanded.is_absolute() else Path.cwd() / expanded
    # Inspect the original spelling before resolving '..', which could otherwise
    # conceal a symlink component or a prohibited publication directory.
    if any(part.lower() in FORBIDDEN_DIRECTORIES for part in absolute.parts):
        raise ValueError('Private output cannot use publication or download directories.')
    current = Path(absolute.anchor)
    for part in absolute.parts[1:]:
        current = current / part
        if current.is_symlink():
            raise ValueError('Symlinks are not permitted in private output paths.')
    resolved = Path(os.path.abspath(absolute))
    private_roots = [parent for parent in resolved.parents
                     if parent.name in {'private', '.private'} and parent.parent != Path('/')]
    if not private_roots:
        raise ValueError('Output must be inside a private/.private directory.')
    repo = next((parent for parent in resolved.parents if (parent / '.git').exists()), None)
    if repo:
        relative = str(resolved.relative_to(repo))
        try:
            tracked = subprocess.run(['git', '-C', str(repo), 'ls-files', '--error-unmatch', '--', relative],
                                     capture_output=True, check=False)
            ignored = subprocess.run(['git', '-C', str(repo), 'check-ignore', '-q', '--', relative],
                                     capture_output=True, check=False)
        except OSError as exc:
            raise ValueError('Cannot verify private Git exclusion.') from exc
        if tracked.returncode != 1 or ignored.returncode != 0:
            raise ValueError('Private output must be untracked and covered by repository ignore rules.')
    private_root = private_roots[0]
    private_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(private_root, 0o700)
    resolved.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    current = resolved.parent
    while current != private_root:
        os.chmod(current, 0o700)
        current = current.parent
    return resolved


def write_new_jsons(items: list[tuple[Path, object]]) -> None:
    """Exclusive creation: never replace an existing seed or audit file."""
    # Every sidecar receives the same Git/symlink/publication guard as the seed;
    # a seed-only ignore pattern must never expose rejected private identifiers.
    items = [(private_output(path), payload) for path, payload in items]
    if any(path.exists() for path, _ in items):
        raise FileExistsError('A requested private output already exists; no files replaced.')
    created: list[Path] = []
    try:
        for path, payload in items:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            created.append(path)
            with os.fdopen(fd, 'w', encoding='utf-8') as stream:
                os.fchmod(stream.fileno(), 0o600)
                json.dump(payload, stream, ensure_ascii=False, separators=(',', ':'))
                stream.write('\n')
    except Exception:
        for path in created:
            path.unlink(missing_ok=True)
        raise


def build_seed(private_project: Path, public_data: Path, year: str, output: Path,
               author_aliases: Path | None = None) -> dict[str, object]:
    output = private_output(output)
    cache = private_project / 'backend' / 'cache' / year
    source_db = Path((cache / 'source_db_path.txt').read_text().strip()).resolve()
    salt = (private_project / '.private' / 'anon_salt.bin').read_bytes()
    if len(salt) < 16:
        raise ValueError('Existing anonymization salt is invalid; no replacement generated.')
    public_bytes = public_data.read_bytes()
    dashboard = json.loads(public_bytes)
    if dashboard['meta']['release_year'] != int(year):
        raise ValueError('Public release year does not match the requested year.')
    public_ids = [record['id'] for record in dashboard['professors']]
    if len(set(public_ids)) != len(public_ids):
        raise ValueError('Public release contains duplicate anonymous IDs.')
    with sqlite3.connect(source_db.as_uri() + '?mode=ro&immutable=1', uri=True) as connection:
        connection.row_factory = sqlite3.Row
        people = [dict(row) for row in connection.execute(
            'SELECT professor_uid,source_professor_id,openalex_id,orcid,identity_confidence '
            'FROM professors ORDER BY professor_uid'
        )]
    uids = [person['professor_uid'] for person in people]
    anon = {uid: anonymous_id(uid, salt) for uid in uids}
    if len(anon) != len(people) or len(set(anon.values())) != len(people) or set(anon.values()) != set(public_ids):
        raise ValueError('Source database and existing salt do not map exactly to this public release.')

    source_uids: dict[str, set[str]] = defaultdict(set)
    authors: dict[str, set[str]] = defaultdict(set)
    primary_author: dict[str, str] = {}
    invalid: list[dict[str, object]] = []
    links: list[dict[str, object]] = []
    raw_primary_present = 0
    for person in people:
        uid = person['professor_uid']
        source = normalized_source_id(person['source_professor_id'])
        if source:
            source_uids[source].add(uid)
        raw_primary = person['openalex_id']
        if raw_primary:
            raw_primary_present += 1
            author = normalize_openalex(raw_primary)
            if author:
                authors[uid].add(author)
                primary_author[uid] = author
            else:
                invalid.append({'source_professor_uid': uid, 'namespace': 'openalex',
                                'raw_identifier': raw_primary, 'reason': 'invalid_primary_format'})
        raw_orcid = person['orcid']
        if raw_orcid:
            orcid = normalize_orcid(raw_orcid)
            if orcid:
                links.append({'source_professor_uid': uid, 'namespace': 'orcid',
                              'identifier': orcid, 'status': 'candidate',
                              'source_kind': 'source_database', 'source_url': None,
                              'evidence': {'source_table': 'professors', 'source_column': 'orcid',
                                           'import_assertion': 'existing_source_claim_not_verified'}})
            else:
                invalid.append({'source_professor_uid': uid, 'namespace': 'orcid',
                                'raw_identifier': raw_orcid, 'reason': 'invalid_format_or_checksum'})

    alias_path = author_aliases if author_aliases is not None else cache / 'author_aliases.json'
    if author_aliases is not None and not alias_path.is_file():
        raise ValueError('Explicit alias source is missing; refusing to silently omit it.')
    alias_records = json.loads(alias_path.read_text()) if alias_path.exists() else []
    if not isinstance(alias_records, list):
        raise ValueError('Alias source must be a JSON array.')
    unmatched_indexes: list[int] = []
    ambiguous_indexes: list[int] = []
    alias_links: set[tuple[str, str]] = set()
    for record_index, record in enumerate(alias_records):
        source = normalized_source_id(record.get('source_professor_id'))
        matches = source_uids.get(source, set()) if source else set()
        if not matches:
            unmatched_indexes.append(record_index)
            continue
        if len(matches) != 1:
            ambiguous_indexes.append(record_index)
            continue
        uid = next(iter(matches))
        for raw_author in record.get('openalex_ids', []):
            author = normalize_openalex(raw_author)
            if not author:
                invalid.append({'source_professor_uid': uid, 'namespace': 'openalex',
                                'raw_identifier': raw_author, 'reason': 'invalid_alias_format',
                                'alias_record_index': record_index})
                continue
            authors[uid].add(author)
            if author != primary_author.get(uid):
                alias_links.add((uid, author))

    author_people: dict[str, set[str]] = defaultdict(set)
    orcid_people: dict[str, set[str]] = defaultdict(set)
    for uid, identifiers in authors.items():
        for identifier in identifiers:
            author_people[identifier].add(uid)
    for link in links:
        orcid_people[str(link['identifier'])].add(str(link['source_professor_uid']))
    payload = {'researchers': [
        {'source_professor_uid': uid, 'anon_id': anon[uid], 'openalex_author_ids': sorted(authors[uid])}
        for uid in uids
    ], 'identifier_links': links}
    counts = {
        'researchers': len(people), 'exact_public_id_match': True,
        'primary_openalex_claims_present': raw_primary_present,
        'primary_openalex_claims_valid': len(primary_author),
        'researchers_with_openalex': sum(bool(authors[uid]) for uid in uids),
        'openalex_person_links': sum(len(values) for values in authors.values()),
        'distinct_openalex_ids': len(author_people),
        'openalex_collision_groups': sum(len(values) > 1 for values in author_people.values()),
        'orcid_candidate_links': len(links), 'distinct_candidate_orcids': len(orcid_people),
        'orcid_collision_groups': sum(len(values) > 1 for values in orcid_people.values()),
        'alias_source_records': len(alias_records), 'secondary_openalex_person_links': len(alias_links),
        'unmatched_alias_records': len(unmatched_indexes), 'ambiguous_alias_records': len(ambiguous_indexes),
        'invalid_identifiers': len(invalid),
        'invalid_orcids': sum(record['namespace'] == 'orcid' for record in invalid),
        'blank_source_roster_ids': sum(not normalized_source_id(person['source_professor_id']) for person in people),
    }
    audit = {'schema_version': 1, 'release_year': int(year),
             'public_data_sha256': hashlib.sha256(public_bytes).hexdigest(),
             'counts': counts, 'unmatched_alias_record_indexes': unmatched_indexes,
             'ambiguous_alias_record_indexes': ambiguous_indexes,
             'assertions': {'source_database_read_only': True, 'existing_salt_reused': True,
                            'names_exported': False, 'kri_nri_inferred': False,
                            'source_claims_are_identity_proof': False}}
    items = [(output, payload), (output.with_suffix('.audit.json'), audit)]
    if invalid:
        items.append((output.with_suffix('.invalid-identifiers.json'), {'invalid_identifiers': invalid}))
    write_new_jsons(items)
    return counts


class SafeArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        self.exit(2, 'Identity seed arguments are invalid; private values are not displayed.\n')


def main() -> None:
    parser = SafeArgumentParser(prog='build_identity_seed.py', description=__doc__)
    parser.add_argument('--private-project', type=Path, required=True)
    parser.add_argument('--public-data', type=Path, required=True)
    parser.add_argument('--year', default='2026')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--author-aliases', type=Path)
    args = parser.parse_args()
    try:
        counts = build_seed(args.private_project.resolve(), args.public_data.resolve(), str(args.year),
                            args.output, args.author_aliases.resolve() if args.author_aliases else None)
    except Exception:
        parser.exit(1, 'Identity seed generation failed; check private paths, permissions, and input validity. No files were replaced.\n')
    print(json.dumps(counts, ensure_ascii=False, sort_keys=True))


if __name__ == '__main__':
    main()
