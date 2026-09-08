#!/usr/bin/env python3
"""Prepare private PhD lookup anchors for later RISS source review.

This command makes no network requests and verifies no departments. It reads
education award years (never inferred dates or current departments) and reuses
the exact release identity map and institution canonical labels. Queue entries
are planned queries, not matches, candidates from RISS, or verified evidence.
"""
from __future__ import annotations

from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import unicodedata

from build_constellation_metadata import country, norm
from build_identity_seed import SafeArgumentParser, anonymous_id, private_output, write_new_jsons
from riss_api import ISO_COUNTRY_CODES


def clean_label(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    # Normalize query whitespace, but do not translate or infer institution names.
    clean = re.sub(r'\s+', ' ', unicodedata.normalize('NFKC', value)).strip()
    if not clean or len(clean) > 300 or any(unicodedata.category(c).startswith('C') for c in clean):
        return None
    if norm(clean) in {'unknown', 'none', 'null', 'n/a', 'na', '미상', '알 수 없음', '-'}:
        return None
    return clean if any(c.isalpha() for c in clean) else None


def korean(value: str) -> bool:
    return bool(re.search(r'[가-힣ᄀ-ᇿㄱ-ㆎ]', value))


def choose_query(raw: object, unit_id: str, canonical: str,
                 aliases: dict[str, set[str]], unit_aliases: dict[str, set[str]]) -> tuple[str, str]:
    raw_label = clean_label(raw)
    if raw_label and korean(raw_label) and aliases.get(norm(raw_label), {unit_id}) == {unit_id}:
        return raw_label, 'korean_education_raw'
    canonical_query = clean_label(canonical)
    if korean(canonical_query):
        return canonical_query, 'korean_canonical'
    choices = [label for label in unit_aliases.get(unit_id, set())
               if korean(label) and aliases.get(norm(label)) == {unit_id}]
    if choices:
        # Stable selection among existing high-confidence labels, not translation.
        return sorted(choices, key=lambda label: (not label.endswith('대학교'), -len(label), norm(label), label))[0], 'korean_verified_alias'
    return canonical_query, 'existing_canonical_fallback'


def build_queue(private_project: Path, public_data: Path, year: str, output: Path,
                scope: str = 'domestic') -> dict[str, object]:
    if scope not in {'domestic', 'foreign', 'all'}:
        raise ValueError('Invalid doctorate scope.')
    if not re.fullmatch(r'[12][0-9]{3}', str(year)):
        raise ValueError('Invalid release year.')
    release_year = int(year)
    output = private_output(output)
    source_db = Path((private_project / 'backend' / 'cache' / str(year) / 'source_db_path.txt').read_text().strip()).resolve()
    salt = (private_project / '.private' / 'anon_salt.bin').read_bytes()
    if len(salt) < 16:
        raise ValueError('Existing anonymization salt is invalid.')
    public_bytes = public_data.read_bytes()
    dashboard = json.loads(public_bytes)
    if dashboard['meta']['release_year'] != release_year:
        raise ValueError('Public release year differs from the requested year.')
    records = dashboard['professors']
    public = {record['id']: record for record in records}
    if len(public) != len(records):
        raise ValueError('Duplicate public anonymous IDs.')

    # immutable is appropriate for the release snapshot and prevents journal writes.
    with sqlite3.connect(source_db.as_uri() + '?mode=ro&immutable=1', uri=True) as connection:
        connection.row_factory = sqlite3.Row
        people = [dict(row) for row in connection.execute('SELECT professor_uid,name FROM professors ORDER BY professor_uid')]
        education: dict[str, list[dict]] = defaultdict(list)
        for row in connection.execute("SELECT professor_uid,institution_raw,institution_unit_id,country,award_year FROM education WHERE degree_level='phd'"):
            education[row['professor_uid']].append(dict(row))
        units = {row['unit_id']: dict(row) for row in connection.execute('SELECT unit_id,display_name,country_code FROM institution_units')}
        alias_rows = [dict(row) for row in connection.execute('SELECT raw_label,unit_id FROM institution_aliases WHERE confidence>=0.9')]

    uids = [person['professor_uid'] for person in people]
    anon = {uid: anonymous_id(uid, salt) for uid in uids}
    if len(anon) != len(people) or len(set(anon.values())) != len(people) or set(anon.values()) != set(public):
        raise ValueError('Source identities and salt do not match the exact public release.')
    aliases: dict[str, set[str]] = defaultdict(set)
    unit_aliases: dict[str, set[str]] = defaultdict(set)
    for unit_id, unit in units.items():
        if norm(unit['display_name']):
            aliases[norm(unit['display_name'])].add(unit_id)
    for row in alias_rows:
        label = clean_label(row['raw_label'])
        if label and row['unit_id'] in units:
            aliases[norm(label)].add(row['unit_id'])
            unit_aliases[row['unit_id']].add(label)

    excluded: Counter[str] = Counter()
    query_sources: Counter[str] = Counter()
    planned = []
    for person in people:
        uid = person['professor_uid']
        rows = education.get(uid, [])
        # Even equal duplicate rows need review: never pick whichever SQL returned last.
        if len(rows) != 1:
            excluded['missing_phd_record' if not rows else 'multiple_phd_records'] += 1
            continue
        degree = rows[0]
        source_country = country(degree['country'])
        unit_id = degree['institution_unit_id']
        if unit_id not in units:
            # Match the metadata builder's exact-label fallback, requiring uniqueness.
            found = set()
            for label in (degree['institution_raw'], public[anon[uid]].get('phd_institution')):
                found.update(aliases.get(norm(label), set()))
            if len(found) != 1:
                excluded['missing_or_ambiguous_institution_unit'] += 1
                continue
            unit_id = next(iter(found))
        unit = units[unit_id]
        unit_country = country(unit['country_code'])
        if source_country and unit_country and source_country != unit_country:
            excluded['country_conflict'] += 1
            continue
        if source_country not in ISO_COUNTRY_CODES or unit_country not in ISO_COUNTRY_CODES:
            excluded['missing_country_anchor'] += 1
            continue
        if scope == 'domestic' and source_country != 'KR':
            excluded['non_domestic_phd'] += 1
            continue
        if scope == 'foreign' and source_country == 'KR':
            excluded['domestic_phd'] += 1
            continue
        # Use precisely the DB canonical string expected by the overlay validator.
        canonical = unit['display_name']
        if not clean_label(canonical) or not isinstance(unit_id, str) or not unit_id.strip():
            excluded['invalid_institution_label'] += 1
            continue
        label_conflict = any(
            aliases.get(norm(label)) and unit_id not in aliases[norm(label)]
            for label in (degree['institution_raw'], public[anon[uid]].get('phd_institution'))
        )
        if label_conflict:
            excluded['institution_label_conflict'] += 1
            continue
        award_year = degree['award_year']
        if type(award_year) is not int or not 1900 <= award_year <= release_year:
            excluded['missing_or_invalid_actual_award_year'] += 1
            continue
        public_year = public[anon[uid]].get('phd_year')
        if type(public_year) is not int or public_year != award_year:
            excluded['public_award_year_mismatch'] += 1
            continue
        name = clean_label(person['name'])
        if not name or len(name) > 200:
            excluded['missing_or_invalid_source_name'] += 1
            continue
        query, source = choose_query(degree['institution_raw'], unit_id, canonical, aliases, unit_aliases)
        query_sources[source] += 1
        planned.append({
            'professor_uid': uid, 'anon_id': anon[uid], 'name': name,
            'institution_unit_id': unit_id, 'institution_canonical': canonical,
            'institution_query': query, 'country': source_country, 'award_year': award_year, 'degree_level': 'phd',
        })

    public_hash = hashlib.sha256(public_bytes).hexdigest()
    payload = {'schema_version': 1, 'release_year': release_year,
               'public_data_sha256': public_hash, 'researchers': planned}
    counts = {'source_researchers': len(people), 'source_phd_rows': sum(map(len, education.values())),
              'planned_queries': len(planned), 'excluded_researchers': sum(excluded.values()),
              'domestic_queries': sum(row['country'] == 'KR' for row in planned),
              'foreign_queries': sum(row['country'] != 'KR' for row in planned),
              'exact_public_id_match': True, 'exclusions': dict(sorted(excluded.items())),
              'query_label_sources': dict(sorted(query_sources.items())),
              'korean_institution_queries': sum(korean(row['institution_query']) for row in planned),
              'distinct_institution_units': len({row['institution_unit_id'] for row in planned})}
    audit = {'schema_version': 1, 'release_year': release_year,
             'public_data_sha256': public_hash, 'scope': scope, 'counts': counts,
             'assertions': {'source_database_read_only': True, 'existing_salt_reused': True,
                            'network_requests_made': False, 'departments_verified': False,
                            'current_department_used': False, 'estimated_award_years_used': False,
                            'queue_is_only_planned_queries': True}}
    write_new_jsons([(output, payload), (output.with_suffix('.audit.json'), audit)])
    return counts


class RissArgumentParser(SafeArgumentParser):
    def error(self, message: str) -> None:
        self.exit(2, 'RISS queue arguments are invalid; private values are not displayed.\n')


def main() -> None:
    parser = RissArgumentParser(prog='build_riss_queue.py', description=__doc__)
    parser.add_argument('--private-project', type=Path, required=True)
    parser.add_argument('--public-data', type=Path, required=True)
    parser.add_argument('--year', default='2026')
    parser.add_argument('--scope', choices=('domestic', 'foreign', 'all'), default='domestic')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    try:
        counts = build_queue(args.private_project.resolve(), args.public_data.resolve(), str(args.year), args.output, scope=args.scope)
    except Exception:
        parser.exit(1, 'RISS queue generation failed; check private paths, permissions, and input validity. No files were replaced.\n')
    print(json.dumps(counts, ensure_ascii=False, sort_keys=True))


if __name__ == '__main__':
    main()
