#!/usr/bin/env python3
"""Seed private, unverified thesis candidates from existing dissertation records.

Every source PhD education row is retained, including incomplete foreign and
domestic anchors. Only kept dissertation-type authorships within one year of an
actual award year can become links. No article affiliations establish degrees,
and no external lookup, original DB write, or verified promotion is performed.
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
from identity_registry import RegistryError, normalize_doi as registry_normalize_doi
from riss_api import validate_queue


ISO2 = set('AD AE AF AG AI AL AM AO AQ AR AS AT AU AW AX AZ BA BB BD BE BF BG BH BI BJ BL BM BN BO BQ BR BS BT BV BW BY BZ CA CC CD CF CG CH CI CK CL CM CN CO CR CU CV CW CX CY CZ DE DJ DK DM DO DZ EC EE EG EH ER ES ET FI FJ FK FM FO FR GA GB GD GE GF GG GH GI GL GM GN GP GQ GR GS GT GU GW GY HK HM HN HR HT HU ID IE IL IM IN IO IQ IR IS IT JE JM JO JP KE KG KH KI KM KN KP KR KW KY KZ LA LB LC LI LK LR LS LT LU LV LY MA MC MD ME MF MG MH MK ML MM MN MO MP MQ MR MS MT MU MV MW MX MY MZ NA NC NE NF NG NI NL NO NP NR NU NZ OM PA PE PF PG PH PK PL PM PN PR PS PT PW PY QA RE RO RS RU RW SA SB SC SD SE SG SH SI SJ SK SL SM SN SO SR SS ST SV SX SY SZ TC TD TF TG TH TJ TK TL TM TN TO TR TT TV TW TZ UA UG UM US UY UZ VA VC VE VG VI VN VU WF WS YE YT ZA ZM ZW'.split())
MISSING_COUNTRY = {'', 'unknown', 'none', 'null', 'n/a', 'na', '미상', '-'}


def country_code(raw: str | None) -> str | None:
    result = 'GB' if norm(raw) == 'uk' else country(raw)
    return result if result in ISO2 else None


def classify_domestic(education_raw: str | None, institution_raw: str | None) -> str:
    education = country_code(education_raw)
    institution = country_code(institution_raw)
    # An unrecognized, nonblank label is not the same as a missing country.
    if (education is None and norm(education_raw) not in MISSING_COUNTRY or
            institution is None and norm(institution_raw) not in MISSING_COUNTRY):
        return 'unknown'
    if education and institution:
        if education != institution:
            return 'country_conflict'
        return 'domestic' if education == 'KR' else 'foreign'
    known = education or institution
    if known == 'KR':
        return 'domestic_unresolved'
    return 'foreign' if known else 'unknown'


def normalize_work_id(raw: object) -> str | None:
    if not isinstance(raw, str) or any(ord(c) < 32 for c in raw):
        return None
    match = re.fullmatch(r'(?:https://openalex\.org/)?(W[1-9][0-9]{0,20})', raw.strip())
    return match.group(1) if match else None


def normalize_doi(raw: object) -> str | None:
    try:
        return registry_normalize_doi(raw)
    except RegistryError:
        return None


def text_value(raw: object) -> str | None:
    if not isinstance(raw, str):
        return None
    clean = re.sub(r'\s+', ' ', unicodedata.normalize('NFKC', raw)).strip()
    return clean or None


def valid_year(value: object, release_year: int) -> int | None:
    return value if type(value) is int and 1900 <= value <= release_year else None


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def common_metadata(rows: list[dict]) -> dict | None:
    """Missing values can be filled by agreement; contradictory values quarantine.

    Author text is per-source authorship, so inconsistent author text on the same
    work also requires review rather than silently selecting one researcher.
    """
    result = {}
    for field in ('title', 'author_text', 'publication_year', 'doi'):
        values = {row[field] for row in rows if row[field] is not None}
        if len(values) > 1:
            return None
        result[field] = next(iter(values)) if values else None
    return result


def build_seed(private_project: Path, public_data: Path, year: str, output: Path,
               riss_queue: Path | None = None) -> dict[str, object]:
    if not re.fullmatch(r'[12][0-9]{3}', str(year)):
        raise ValueError('Invalid release year.')
    release_year = int(year)
    output = private_output(output)
    source = Path((private_project / 'backend' / 'cache' / str(year) / 'source_db_path.txt').read_text().strip()).resolve()
    salt = (private_project / '.private' / 'anon_salt.bin').read_bytes()
    if len(salt) < 16:
        raise ValueError('Invalid existing anonymization salt.')
    public_bytes = public_data.read_bytes()
    public_hash = hashlib.sha256(public_bytes).hexdigest()
    dashboard = json.loads(public_bytes)
    if dashboard['meta']['release_year'] != release_year:
        raise ValueError('Requested year does not match the public release.')
    public_ids = [row['id'] for row in dashboard['professors']]
    if len(public_ids) != len(set(public_ids)):
        raise ValueError('Duplicate public IDs.')
    before = source.stat()
    snapshot_hash = sha256_file(source)
    with sqlite3.connect(source.as_uri() + '?mode=ro&immutable=1', uri=True) as connection:
        connection.row_factory = sqlite3.Row
        people = {row['professor_uid']: dict(row) for row in connection.execute('SELECT professor_uid,name FROM professors')}
        people_count = connection.execute('SELECT COUNT(*) FROM professors').fetchone()[0]
        education = [dict(row) for row in connection.execute(
            "SELECT e.education_id,e.professor_uid,e.institution_unit_id,e.institution_raw,e.country,e.award_year,"
            "u.display_name,u.country_code FROM education e LEFT JOIN institution_units u ON u.unit_id=e.institution_unit_id "
            "WHERE e.degree_level='phd' ORDER BY e.education_id")]
        works = [dict(row) for row in connection.execute(
            "SELECT professor_uid,work_id,title,raw_author_name,publication_year,doi FROM work_authorship_evidence "
            "WHERE work_type='dissertation' AND identity_decision='keep'")]
        affiliation_rows = [dict(row) for row in connection.execute(
            "WITH kept_dissertations AS (SELECT DISTINCT professor_uid,"
            "replace(trim(work_id),'https://openalex.org/','') normalized_work_id FROM work_authorship_evidence "
            "WHERE work_type='dissertation' AND identity_decision='keep') "
            "SELECT r.professor_uid,r.work_id,r.institution_unit_id,COUNT(DISTINCT r.raw_affiliation_id) evidence_count "
            "FROM raw_affiliation_units r JOIN kept_dissertations w ON w.professor_uid=r.professor_uid "
            "AND w.normalized_work_id=replace(trim(r.work_id),'https://openalex.org/','') "
            "WHERE r.identity_decision='keep' "
            "GROUP BY r.professor_uid,r.work_id,r.institution_unit_id")]
    after = source.stat()
    if (before.st_size, before.st_mtime_ns, before.st_ino) != (after.st_size, after.st_mtime_ns, after.st_ino):
        raise ValueError('Source snapshot changed during read.')
    anon = {uid: anonymous_id(uid, salt) for uid in people}
    if (len(people) != people_count or len(set(anon.values())) != people_count or
            set(anon.values()) != set(public_ids)):
        raise ValueError('Source and existing salt do not match every public researcher exactly.')
    if any(row['professor_uid'] not in people for row in education):
        raise ValueError('An education record has no source researcher.')
    degree_counts = Counter(row['professor_uid'] for row in education)
    if len({row['education_id'] for row in education}) != len(education):
        raise ValueError('Duplicate source education IDs.')

    ready = {}
    if riss_queue:
        queue = validate_queue(json.loads(riss_queue.read_text()))
        if queue['release_year'] != release_year or queue['public_data_sha256'] != public_hash:
            raise ValueError('RISS queue does not match the public release.')
        ready = {row['professor_uid']: row for row in queue['researchers']}
        if any(uid not in anon or row['anon_id'] != anon[uid] for uid, row in ready.items()):
            raise ValueError('RISS queue identity mapping differs from the source.')

    education_records = []
    degrees_by_uid: dict[str, list[dict]] = defaultdict(list)
    invalid_award_years = 0
    for row in education:
        uid = row['professor_uid']
        status = classify_domestic(row['country'], row['country_code'])
        award_year = valid_year(row['award_year'], release_year)
        invalid_award_years += award_year is None
        source_name = text_value(people[uid]['name'])
        query_status = 'anchor_review_required'
        if uid in ready:
            query = ready[uid]
            if degree_counts[uid] == 1 and not (
                status in {'domestic', 'foreign'} and award_year == query['award_year'] and
                country_code(row['country']) == query['country'] == country_code(row['country_code']) and
                row['institution_unit_id'] == query['institution_unit_id'] and
                norm(row['display_name']) == norm(query['institution_canonical']) and
                source_name and norm(source_name) == norm(query['name'])
            ):
                raise ValueError('RISS query anchors differ from the source education record.')
            if degree_counts[uid] == 1:
                query_status = 'ready'
        record = {
            'source_education_id': row['education_id'], 'source_professor_uid': uid,
            'source_author_name': source_name, 'degree_level': 'phd',
            'institution_unit_id': row['institution_unit_id'], 'institution_canonical': row['display_name'],
            'institution_raw': row['institution_raw'], 'education_country_raw': row['country'],
            'institution_country_raw': row['country_code'], 'education_country_code': country_code(row['country']),
            'institution_country_code': country_code(row['country_code']), 'award_year': award_year,
            'domestic_status': status, 'query_status': query_status,
        }
        education_records.append(record)
        degrees_by_uid[uid].append(record)

    affiliation_counts: Counter[tuple[str, str, str]] = Counter()
    for row in affiliation_rows:
        work_id = normalize_work_id(row['work_id'])
        if work_id:
            affiliation_counts[(row['professor_uid'], work_id, row['institution_unit_id'])] += row['evidence_count']
    grouped: dict[str, list[dict]] = defaultdict(list)
    invalid_work_ids = 0
    invalid_dois = 0
    unknown_work_people = 0
    for row in works:
        work_id = normalize_work_id(row['work_id'])
        if not work_id:
            invalid_work_ids += 1
            continue
        if row['professor_uid'] not in people:
            unknown_work_people += 1
            continue
        doi = normalize_doi(row['doi'])
        invalid_dois += bool(row['doi']) and doi is None
        grouped[work_id].append({**row, 'provider_record_id': work_id, 'doi': doi,
                                'title': text_value(row['title']), 'author_text': text_value(row['raw_author_name'])})

    thesis_records = []
    links = []
    quarantined = 0
    quarantined_eligible = 0
    suppressed_duplicate_links = 0
    seen_links = set()
    for work_id in sorted(grouped):
        rows = grouped[work_id]
        eligible = []
        for row in rows:
            degrees = degrees_by_uid.get(row['professor_uid'], [])
            if len(degrees) != 1:
                continue
            degree = degrees[0]
            publication_year = valid_year(row['publication_year'], release_year)
            if (degree['domestic_status'] not in {'domestic', 'domestic_unresolved', 'foreign'} or
                    degree['award_year'] is None or publication_year is None or
                    abs(publication_year - degree['award_year']) > 1):
                continue
            eligible.append((row, degree))
        metadata = common_metadata(rows)
        if metadata is None:
            quarantined += 1
            quarantined_eligible += bool(eligible)
            continue
        if not eligible:
            continue
        thesis_records.append({
            'provider': 'openalex', 'provider_record_id': work_id, **metadata, 'publisher': None,
            'reported_degree_level': None, 'reported_department': None,
            'source_url': 'https://openalex.org/' + work_id,
        })
        for row, degree in eligible:
            key = (degree['source_education_id'], work_id)
            if key in seen_links:
                suppressed_duplicate_links += 1
                continue
            seen_links.add(key)
            uid = degree['source_professor_uid']
            count = affiliation_counts[(uid, work_id, degree['institution_unit_id'])]
            links.append({
                'source_education_id': degree['source_education_id'], 'provider': 'openalex',
                'provider_record_id': work_id, 'match_method': 'source_openalex_dissertation',
                'evidence': {
                    'year_difference': row['publication_year'] - degree['award_year'],
                    'source_identity_decision': 'keep', 'matched_source_professor_uid': uid,
                    'source_work_type': 'dissertation', 'source_author_text': row['author_text'],
                    'degree_region': 'foreign' if degree['domestic_status'] == 'foreign' else 'domestic',
                    'kept_same_work_degree_institution_affiliation': count > 0,
                    'kept_same_work_degree_institution_affiliation_count': count,
                    'source_affiliation_is_awarding_institution_proof': False,
                    'doctoral_level_verified': False, 'awarding_institution_verified': False,
                    'degree_department_verified': False, 'source_identity_verified': False,
                    'candidate_only': True,
                },
            })
    links.sort(key=lambda row: (row['source_education_id'], row['provider_record_id']))
    statuses = Counter(row['domestic_status'] for row in education_records)
    region_counts = {}
    for region in ('domestic', 'foreign'):
        selected = [link for link in links if link['evidence']['degree_region'] == region]
        region_counts[region] = {'candidate_links': len(selected),
                                'distinct_works': len({link['provider_record_id'] for link in selected}),
                                'researchers': len({link['evidence']['matched_source_professor_uid'] for link in selected}),
                                'exact_year_links': sum(link['evidence']['year_difference'] == 0 for link in selected),
                                'same_work_affiliation_unit_links': sum(link['evidence']['kept_same_work_degree_institution_affiliation'] for link in selected)}
    linked_degrees = {row['source_education_id'] for row in links}
    counts = {
        'source_researchers': people_count, 'exact_public_id_match': True,
        'education_records': len(education_records), 'domestic_statuses': dict(sorted(statuses.items())),
        'query_ready_records': sum(row['query_status'] == 'ready' for row in education_records),
        'missing_or_invalid_actual_award_years': invalid_award_years,
        'multiple_phd_researchers': sum(count > 1 for count in degree_counts.values()),
        'education_records_without_candidate': len(education_records) - len(linked_degrees),
        'kept_dissertation_source_rows': len(works), 'thesis_records': len(thesis_records),
        'candidate_links': len(links), 'candidate_counts_by_region': region_counts,
        'invalid_work_id_rows': invalid_work_ids, 'invalid_doi_rows': invalid_dois,
        'unknown_work_researcher_rows': unknown_work_people,
        'quarantined_metadata_conflict_works': quarantined,
        'quarantined_eligible_metadata_conflict_works': quarantined_eligible,
        'suppressed_duplicate_candidate_links': suppressed_duplicate_links,
    }
    payload = {'schema_version': 1, 'source_snapshot_sha256': snapshot_hash,
               'education_records': education_records, 'thesis_records': thesis_records, 'links': links}
    audit = {'schema_version': 1, 'release_year': release_year, 'public_data_sha256': public_hash,
             'source_snapshot_sha256': snapshot_hash, 'counts': counts,
             'assertions': {'source_database_read_only': True, 'existing_salt_reused': True,
                            'network_requests_made': False, 'all_phd_records_retained': True,
                            'regular_article_evidence_used': False, 'verified_links_created': False,
                            'degree_departments_inferred': False}}
    write_new_jsons([(output, payload), (output.with_suffix('.audit.json'), audit)])
    return counts


class ThesisArgumentParser(SafeArgumentParser):
    def error(self, message: str) -> None:
        self.exit(2, 'Thesis seed arguments are invalid; private values are not displayed.\n')


def main() -> None:
    parser = ThesisArgumentParser(prog='build_thesis_seed.py', description=__doc__)
    parser.add_argument('--private-project', type=Path, required=True)
    parser.add_argument('--public-data', type=Path, required=True)
    parser.add_argument('--year', default='2026')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--riss-queue', type=Path)
    args = parser.parse_args()
    try:
        counts = build_seed(args.private_project.resolve(), args.public_data.resolve(), str(args.year), args.output,
                            args.riss_queue.resolve() if args.riss_queue else None)
    except Exception:
        parser.exit(1, 'Thesis seed generation failed; check private paths, permissions, and input validity. No files were replaced.\n')
    print(json.dumps(counts, ensure_ascii=False, sort_keys=True))


if __name__ == '__main__':
    main()
