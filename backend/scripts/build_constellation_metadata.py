#!/usr/bin/env python3
"""Export anonymous institution, department and observed employment evidence.

The private source is read-only; the existing HMAC salt is read only in memory.
Names are read only to validate optional private reviewed evidence, never exported.
Paper affiliations are explicitly inferred units, never verified degree units.
"""
from __future__ import annotations

import argparse
import base64
from collections import Counter, defaultdict
import hashlib
import hmac
import json
from pathlib import Path
import re
import sqlite3
import unicodedata
from urllib.parse import urlparse

COUNTRIES = {
    'korea': 'KR', 'south korea': 'KR', 'republic of korea': 'KR',
    'united states': 'US', 'usa': 'US', 'united kingdom': 'GB', 'uk': 'GB',
    'japan': 'JP', 'germany': 'DE', 'india': 'IN', 'canada': 'CA',
    'france': 'FR', 'sweden': 'SE', 'australia': 'AU', 'netherlands': 'NL',
    'israel': 'IL', 'austria': 'AT', 'italy': 'IT', 'poland': 'PL',
    'russia': 'RU', 'spain': 'ES', 'switzerland': 'CH', 'china': 'CN',
    'taiwan': 'TW', 'singapore': 'SG', 'new zealand': 'NZ', 'belgium': 'BE',
    'finland': 'FI', 'norway': 'NO', 'denmark': 'DK', 'czech republic': 'CZ',
    'hungary': 'HU', 'pakistan': 'PK', 'iran': 'IR', 'romania': 'RO',
    'brazil': 'BR', 'turkey': 'TR', 'bangladesh': 'BD', 'portugal': 'PT',
    'south africa': 'ZA', 'sri lanka': 'LK', 'ukraine': 'UA',
}


def norm(value):
    return re.sub(r'\s+', ' ', unicodedata.normalize('NFKC', value or '')).strip().casefold()


def country(value):
    clean = norm(value)
    if re.fullmatch(r'[a-z]{2}', clean):
        return clean.upper()
    return COUNTRIES.get(clean)


FORMAL_UNIT = re.compile(r'\b(?:Department|School|Division)\s+of\b', re.I)
TRAILING_DEPARTMENT = re.compile(r'[A-Za-z][A-Za-z &-]+\s+Department', re.I)
NON_DEPARTMENT = re.compile(r'\s+(?:and|&)\s+(?:the\s+)?(?:Center|Centre|Institute|College|Laboratory|Research Center)\b|\s*/\s*(?:College|Institute|Center|Centre|Laboratory)\b', re.I)


def department_label(raw):
    """Only formal department-like labels, with cosmetic normalization.

    Multiple formal units and comma-separated/complex strings are intentionally
    unresolved. Synonyms, subjects and unrelated current departments never map.
    """
    clean = unicodedata.normalize('NFKC', raw or '')
    clean = re.sub(r'\\[rnt]', ' ', clean)
    clean = re.sub(r'\s+', ' ', clean).strip(' .;')
    matches = list(FORMAL_UNIT.finditer(clean))
    if not matches:
        if TRAILING_DEPARTMENT.fullmatch(clean) and not re.search(r'\b(?:Center|Centre|Institute|College|Laboratory|School|Division)\b', clean, re.I):
            return clean, False
        return None, False
    if len(matches) != 1 or matches[0].start() != 0:
        return None, True
    clean = NON_DEPARTMENT.split(clean, maxsplit=1)[0].strip(' .;')
    if any(char in clean for char in [',', ';', '/', '@', '\n']) or len(clean) > 150:
        return None, True
    # No inferred equivalence across singular/plural units or merged departments.
    return clean, False


def validate_verified_record(record, *, uid, public_id, person_name, institution_ids, institution_name, award_year):
    """Fail closed on every identity/degree anchor before a private override.

    This validates a reviewed evidence record; it does not itself establish that
    an arbitrary submitted claim is true. Actual source inspection is required.
    """
    checks = {
        'unverified_record': record['verification_status'] == 'verified',
        'person_id_mismatch': record['professor_uid'] == uid and record['anon_id'] == public_id,
        'source_author_mismatch': bool(person_name) and norm(record['source_author']) == norm(person_name),
        'institution_mismatch': record['institution_unit_id'] in institution_ids and
            norm(record['institution_canonical']) == norm(institution_name) and
            norm(record['source_institution_canonical']) == norm(institution_name),
        'year_mismatch': isinstance(award_year, int) and record['award_year'] == award_year and record['source_award_year'] == award_year,
        'degree_mismatch': record['degree_level'] == 'phd' and record['source_degree_level'] == 'phd',
        'country_mismatch': record['country'] == 'KR',
        'department_mismatch': bool(record['department']) and norm(record['department']) == norm(record['source_department']),
        'missing_check_time': bool(record['checked_at']),
        'excerpt_too_long': len((record['evidence_excerpt'] or '').split()) <= 25,
    }
    source_url = urlparse(record['source_url'] or '')
    host = (source_url.hostname or '').lower()
    riss = host in {'riss.kr', 'www.riss.kr', 'm.riss.kr', 'riss.or.kr', 'www.riss.or.kr'}
    kiss = host == 'kiss.kstudy.com'
    checks['invalid_degree_source'] = source_url.scheme == 'https' and (
        record['evidence_type'] == 'riss_dissertation' and riss and ('/search/detail/' in source_url.path or source_url.path == '/link' and re.search(r'(?:^|&)id=T\d+(?:&|$)', source_url.query))
        or record['evidence_type'] == 'kiss_degree_record' and kiss and source_url.path.startswith('/Detail/')
    )
    department = record['department'] or ''
    checks['invalid_department'] = (
        1 <= len(department) <= 150 and not re.search(r'https?://|@|[\r\n]', department) and
        bool(re.search(r'\b(?:Department|School|Division)\b|(?:학과|학부|전공)', department, re.I))
    )
    for reason, valid in checks.items():
        if not valid:
            raise ValueError(f'Invalid verified degree overlay: {reason}; no output written.')
    return record['department'].strip()



def valid_year(value, release_year):
    return type(value) is int and 1900 <= value <= release_year


def load_lifetime_overlay(path, *, public_hash, uid_to_public, private_names, public, release_year):
    """Read explicitly reviewed private primary-source evidence, never scrape it.

    Review establishes the evidence. This loader only enforces person/snapshot
    anchors and safe structured fields; a JSON assertion is not authentication.
    """
    if not path:
        return defaultdict(list)
    data = json.loads(path.read_text())
    if data.get('schema_version') != 1 or data.get('public_data_sha256') != public_hash or not isinstance(data.get('records'), list):
        raise ValueError('Lifetime overlay version/public release mismatch; no output written.')
    records = defaultdict(list)
    for record in data['records']:
        uid = record.get('professor_uid')
        public_id = uid_to_public.get(uid)
        person = public.get(public_id, {})
        url = urlparse(record.get('source_url') or '')
        if (not public_id or record.get('anon_id') != public_id or
            not private_names.get(uid) or norm(record.get('person_name')) != norm(private_names[uid]) or
            record.get('verification_status') != 'verified' or
            record.get('evidence_kind') not in {'official_profile', 'verified_cv'} or
            not re.fullmatch(r'\d{4}-\d{2}-\d{2}T[^ ]+', record.get('checked_at') or '') or
            url.scheme != 'https' or not url.hostname or url.username or url.password):
            raise ValueError('Lifetime overlay person/review/source mismatch; no output written.')
        kind = record.get('kind')
        department = record.get('department')
        if (kind not in {'phd_department', 'faculty_appointment', 'current_position'} or
            not isinstance(record.get('institution'), str) or not record['institution'].strip() or
            not re.fullmatch(r'[A-Z]{2}', record.get('country') or '') or
            not isinstance(department, str) or not 1 <= len(department) <= 150 or
            re.search(r'https?://|@|[\r\n]', department) or
            not re.search(r'\b(?:Department|School|Division)\b|(?:학과|학부|전공)', department, re.I)):
            raise ValueError('Lifetime overlay invalid structured claim; no output written.')
        if kind == 'phd_department':
            if (not valid_year(record.get('award_year'), release_year) or record['award_year'] != person.get('phd_year') or
                norm(record['institution']) != norm(person.get('phd_institution'))):
                raise ValueError('Lifetime overlay degree anchor mismatch; no output written.')
        elif kind == 'faculty_appointment':
            if (not valid_year(record.get('start_year'), release_year) or not valid_year(record.get('end_year'), release_year) or
                record['start_year'] > record['end_year'] or
                record.get('rank') not in {None, 'assistant_professor', 'associate_professor', 'professor'} or
                ('first_assistant_professor_verified' in record and type(record['first_assistant_professor_verified']) is not bool) or
                (record.get('first_assistant_professor_verified') and
                 (record.get('rank') != 'assistant_professor' or record.get('first_assistant_evidence') != 'complete_prior_employment_history_reviewed'))):
                raise ValueError('Lifetime overlay employment interval/first-rank mismatch; no output written.')
        elif (not valid_year(record.get('observation_year'), release_year) or
              norm(record['institution']) != norm(person.get('current_institution'))):
            raise ValueError('Lifetime overlay current institution/year mismatch; no output written.')
        records[uid].append(record)
    return records

def run(args):
    private_root = args.private_project.resolve()
    public_path = args.public_data.resolve()
    source_db = args.source_db or Path((private_root / 'backend' / 'cache' / args.year / 'source_db_path.txt').read_text().strip())
    salt_path = args.anon_salt or private_root / '.private' / 'anon_salt.bin'
    salt = salt_path.read_bytes()
    if len(salt) < 16:
        raise ValueError('Existing anonymization salt is invalid; refusing to replace it.')
    public_bytes = public_path.read_bytes()
    dashboard = json.loads(public_bytes)
    if dashboard['meta']['release_year'] != int(args.year):
        raise ValueError('Requested year and public data release year differ; no output written.')
    public = {person['id']: person for person in dashboard['professors']}
    connection = sqlite3.connect(f'file:{source_db.resolve()}?mode=ro&immutable=1', uri=True)
    connection.row_factory = sqlite3.Row

    def anonymous_id(uid):
        digest = hmac.new(salt, uid.encode(), hashlib.sha256).digest()
        return 'P-' + base64.b32encode(digest).decode().rstrip('=')[:10]

    uid_to_public = {}
    for row in connection.execute('SELECT professor_uid FROM professors'):
        public_id = anonymous_id(row['professor_uid'])
        if public_id in public:
            uid_to_public[row['professor_uid']] = public_id
    if set(uid_to_public.values()) != set(public):
        raise ValueError('Private source/salt does not map exactly to the public release; no output written.')

    units = {}
    unit_ids_by_name = defaultdict(set)
    for row in connection.execute('SELECT unit_id,display_name,country_code FROM institution_units'):
        units[row['unit_id']] = dict(row)
        unit_ids_by_name[norm(row['display_name'])].add(row['unit_id'])
    for row in connection.execute('SELECT raw_label,unit_id FROM institution_aliases WHERE confidence>=0.9'):
        unit_ids_by_name[norm(row['raw_label'])].add(row['unit_id'])
    education = defaultdict(dict)
    for row in connection.execute("SELECT professor_uid,degree_level,institution_raw,institution_unit_id,country,award_year FROM education WHERE degree_level IN ('bachelor','phd')"):
        education[row['professor_uid']][row['degree_level']] = dict(row)

    verified_records = defaultdict(list)
    private_person_names = {}
    verified_db = getattr(args, 'verified_departments_db', None)
    if verified_db:
        overlay = sqlite3.connect(f'file:{verified_db.resolve()}?mode=ro&immutable=1', uri=True)
        overlay.row_factory = sqlite3.Row
        for row in overlay.execute("SELECT * FROM degree_department_verifications WHERE verification_status='verified'"):
            if row['professor_uid'] not in uid_to_public:
                raise ValueError('Verified overlay person is absent from the public source; no output written.')
            verified_records[row['professor_uid']].append(dict(row))
        overlay.close()
        # Name field is read only for explicit second-verification identity checks.
        if verified_records:
            for row in connection.execute('SELECT professor_uid,name FROM professors'):
                if row['professor_uid'] in verified_records:
                    private_person_names[row['professor_uid']] = row['name']

    lifetime_path = getattr(args, 'lifetime_evidence_json', None)
    if lifetime_path:
        # Read private names only to validate explicitly reviewed source records.
        for private_person in connection.execute('SELECT professor_uid,name FROM professors'):
            private_person_names[private_person['professor_uid']] = private_person['name']
    lifetime_records = load_lifetime_overlay(lifetime_path,
        public_hash=hashlib.sha256(public_bytes).hexdigest(), uid_to_public=uid_to_public,
        private_names=private_person_names, public=public, release_year=int(args.year))

    # Kept author-level source affiliations only. No raw strings, names, URLs,
    # OpenAlex identifiers, source work identifiers or plaintext name map is read.
    evidence = defaultdict(list)
    for row in connection.execute('''
        SELECT professor_uid,institution_unit_id,period,unit_label,COUNT(DISTINCT work_id) AS works
        FROM raw_affiliation_units
        WHERE identity_decision='keep' AND unit_label IS NOT NULL
          AND institution_unit_id IS NOT NULL AND period IS NOT NULL
        GROUP BY professor_uid,institution_unit_id,period,unit_label
    '''):
        if row['professor_uid'] not in uid_to_public or not re.fullmatch(r'\d{4}-H[12]', row['period']):
            continue
        label, unresolved = department_label(row['unit_label'])
        if label or unresolved:
            evidence[(row['professor_uid'], row['institution_unit_id'])].append((row['period'], label, unresolved, row['works']))

    def resolve_units(institution, degree=None):
        if degree and degree.get('institution_unit_id') in units:
            return {degree['institution_unit_id']}
        result = set(unit_ids_by_name.get(norm(institution), set()))
        if degree:
            result.update(unit_ids_by_name.get(norm(degree.get('institution_raw')), set()))
        # Ambiguous aliases are never treated as one institutional unit.
        return result if len(result) == 1 else set()

    def resolved_country(ids, explicit=None):
        countries = {country(units[unit]['country_code']) for unit in ids}
        countries.discard(None)
        declared = country(explicit)
        if declared:
            countries.add(declared)
        return next(iter(countries)) if len(countries) == 1 else None

    def canonical_institution(ids):
        return units[next(iter(ids))]['display_name'] if len(ids) == 1 else None

    def infer_department(uid, ids, start_period, end_period):
        if len(ids) != 1 or not start_period or not end_period or start_period > end_period:
            return None, 0, 'missing_institution_or_period'
        candidates = {}
        evidence_count = 0
        unresolved = False
        for unit_id in ids:
            for period, label, complex_label, count in evidence[(uid, unit_id)]:
                if start_period <= period <= end_period:
                    unresolved = unresolved or complex_label
                    if label:
                        candidates.setdefault(norm(label), label)
                        evidence_count += count
        if unresolved or len(candidates) > 1:
            return None, 0, 'ambiguous_publication_departments'
        if len(candidates) == 1:
            return next(iter(candidates.values())), evidence_count, 'kept_author_affiliation_same_institution_and_period'
        return None, 0, 'no_formal_department_evidence'

    # Snapshot evidence is independent of publication-derived career positions.
    # Older test/source schemas without roster columns fail closed to no links.
    source_tables = {r[0] for r in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    professor_columns = {r[1] for r in connection.execute('PRAGMA table_info(professors)')}
    current_records = {}
    if {'latest_term', 'latest_institution_unit_id'} <= professor_columns:
        current_records = {r['professor_uid']: dict(r) for r in connection.execute(
            'SELECT professor_uid,latest_term,latest_institution_unit_id FROM professors')}
    snapshots = defaultdict(lambda: defaultdict(set))
    snapshot_terms = defaultdict(lambda: defaultdict(set))
    if 'semester_snapshots' in source_tables:
        snapshot_columns = {r[1] for r in connection.execute('PRAGMA table_info(semester_snapshots)')}
        semester_column = 'semester' if 'semester' in snapshot_columns else 'NULL AS semester'
        for snapshot in connection.execute(f'SELECT professor_uid,term,year,institution_unit_id,rank,{semester_column} FROM semester_snapshots'):
            if (snapshot['professor_uid'] in uid_to_public and snapshot['institution_unit_id'] in units and
                valid_year(snapshot['year'], int(args.year)) and
                re.fullmatch(str(snapshot['year']) + r'-(?:spring|fall)', snapshot['term'] or '') and
                ('semester' not in snapshot_columns or snapshot['semester'] == snapshot['term'].split('-')[1])):
                key = (snapshot['year'], snapshot['institution_unit_id'])
                snapshots[snapshot['professor_uid']][key].add(snapshot['rank'])
                snapshot_terms[snapshot['professor_uid']][key].add(snapshot['term'])
    rank_names = {'assistant': 'assistant_professor', 'associate': 'associate_professor', 'full': 'professor'}

    def roster_lifetime(uid, person):
        appointments = []
        for (year, unit_id), ranks in sorted(snapshots[uid].items()):
            ids = {unit_id}
            department, _, basis = infer_department(uid, ids, f'{year}-H1', f'{year}-H2')
            item = {
                'institution': canonical_institution(ids), 'institution_canonical': canonical_institution(ids),
                'country': resolved_country(ids), 'department': department,
                'department_inferred': bool(department), 'department_evidence': basis,
                'start_year': year, 'end_year': year, 'role': 'faculty',
                'evidence_kind': 'semester_roster', 'evidence_status': 'observed',
                # Actual source terms only. Annual lifetime intervals stay intact,
                # but semester comparisons must select one of these observations.
                'observed_terms': sorted(snapshot_terms[uid][(year, unit_id)], key=lambda term: term.endswith('-fall')),
                'first_assistant_professor_verified': False,
            }
            if len(ranks) == 1 and next(iter(ranks)) in rank_names:
                item['rank'] = rank_names[next(iter(ranks))]
            appointments.append(item)
        current = current_records.get(uid)
        position = None
        term = re.fullmatch(r'(\d{4})-(?:spring|fall)', (current or {}).get('latest_term') or '')
        if current and term and valid_year(int(term[1]), int(args.year)) and current['latest_institution_unit_id'] in units:
            year = int(term[1])
            ids = {current['latest_institution_unit_id']}
            # Retain the public current-institution anchor (including deliberate
            # existing campus/successor naming), never the last paper institution.
            institution = person.get('current_institution')
            current_unit = current['latest_institution_unit_id']
            observed = (year, current_unit) in snapshots[uid]
            if institution and observed:
                periods = [p for p, _, _, _ in evidence[(uid, current_unit)] if p <= f'{year}-H2']
                latest_period = max(periods, default=None)
                department, _, basis = infer_department(uid, ids, latest_period, latest_period)
                position = {
                    'institution': institution, 'institution_canonical': institution,
                    'country': resolved_country(ids), 'department': department,
                    'department_inferred': bool(department), 'department_evidence': basis,
                    'department_observation_year': int(latest_period[:4]) if department else None,
                    'observation_year': year, 'evidence_kind': 'semester_roster', 'evidence_status': 'observed',
                }
        return appointments, position

    def checked_lifetime_record(record, ids):
        # Exact institution resolution also checks country consistency. No fuzzy
        # school aliases, current-subject substitutions or historical mergers.
        if len(ids) != 1 or resolved_country(ids) != record['country']:
            raise ValueError('Lifetime overlay institution/country mismatch; no output written.')

    output = {}
    counts = Counter()
    for uid, public_id in uid_to_public.items():
        person = public[public_id]
        phd = education[uid].get('phd')
        bachelor = education[uid].get('bachelor')
        phd_units = resolve_units(person.get('phd_institution'), phd)
        bachelor_units = resolve_units(person.get('bachelor_institution'), bachelor)
        phd_country = resolved_country(phd_units, (phd or {}).get('country') or person.get('phd_country'))
        bachelor_country = resolved_country(bachelor_units, (bachelor or {}).get('country'))
        doctoral = next((segment for segment in person['career'] if segment['stage'] == 'doctoral'), None)
        doctoral_start = (doctoral or {}).get('start_period')
        doctoral_end = (doctoral or {}).get('end_period')
        department, support, basis = infer_department(uid, phd_units, doctoral_start, doctoral_end)
        verified_department = None
        for record in verified_records.get(uid, []):
            if not phd or phd.get('award_year') != person.get('phd_year') or phd_country != 'KR':
                raise ValueError('Verified overlay degree does not match both private/public degree anchors; no output written.')
            candidate = validate_verified_record(record, uid=uid, public_id=public_id,
                person_name=private_person_names.get(uid), institution_ids=phd_units,
                institution_name=canonical_institution(phd_units), award_year=person.get('phd_year'))
            if verified_department and norm(verified_department) != norm(candidate):
                raise ValueError('Conflicting verified degree departments; no output written.')
            verified_department = candidate
        for record in lifetime_records.get(uid, []):
            if record['kind'] == 'phd_department':
                if not phd or phd.get('award_year') != record['award_year']:
                    raise ValueError('Lifetime overlay private degree anchor mismatch; no output written.')
                checked_lifetime_record(record, phd_units)
                if phd_country != record['country'] or (verified_department and norm(verified_department) != norm(record['department'])):
                    raise ValueError('Conflicting verified degree departments; no output written.')
                verified_department = record['department']
        if verified_department:
            department, support, basis = verified_department, 0, 'verified_degree_record'
        appointments, current_position = roster_lifetime(uid, person)
        verified_current = None
        for record in lifetime_records.get(uid, []):
            if record['kind'] == 'phd_department':
                continue
            ids = resolve_units(record['institution'])
            checked_lifetime_record(record, ids)
            common = {
                'institution': record['institution'], 'institution_canonical': record['institution'],
                'country': record['country'], 'department': record['department'],
                'department_inferred': False, 'department_evidence': 'verified_official_profile',
                'evidence_kind': record['evidence_kind'], 'evidence_status': 'verified',
            }
            if record['kind'] == 'faculty_appointment':
                appointment = {**common, 'start_year': record['start_year'], 'end_year': record['end_year'],
                    'role': 'faculty', 'first_assistant_professor_verified': record.get('first_assistant_professor_verified', False)}
                if record.get('rank'):
                    appointment['rank'] = record['rank']
                if appointment not in appointments:
                    appointments.append(appointment)
            else:
                if current_position and record['observation_year'] < current_position['observation_year']:
                    raise ValueError('Current official evidence predates the latest roster observation; no output written.')
                if verified_current is not None and verified_current != {**common, 'observation_year': record['observation_year'], 'department_observation_year': record['observation_year']}:
                    raise ValueError('Conflicting current position evidence; no output written.')
                verified_current = {**common, 'observation_year': record['observation_year'], 'department_observation_year': record['observation_year']}
        first_appointments = {tuple(a.get(k) for k in ('institution', 'department', 'start_year')) for a in appointments if a.get('first_assistant_professor_verified')}
        if len(first_appointments) > 1:
            raise ValueError('Conflicting first assistant professor claims; no output written.')
        if verified_current:
            current_position = verified_current
        row = {
            'phd_country': phd_country,
            'phd_institution_canonical': canonical_institution(phd_units),
            'phd_department': department,
            'phd_department_inferred': bool(department) and not bool(verified_department),
            'phd_department_evidence': basis,
            'phd_department_supporting_affiliations': support,
            'bachelor_country': bachelor_country,
            'bachelor_institution_canonical': canonical_institution(bachelor_units),
            'bachelor_department': None,
            'bachelor_department_inferred': False,
            'bachelor_department_evidence': 'no_degree_department_field_in_source',
            'career_units': [],
            'faculty_appointments': appointments,
            'current_position': current_position,
        }
        counts['researchers'] += 1
        counts['observed_faculty_appointment_years'] += sum(a['evidence_status'] == 'observed' for a in appointments)
        counts['observed_faculty_appointment_terms'] += sum(len(a.get('observed_terms', [])) for a in appointments)
        counts['verified_faculty_intervals'] += sum(a['evidence_status'] == 'verified' for a in appointments)
        counts['current_positions'] += bool(current_position)
        counts['current_positions_release_year'] += bool(current_position and current_position['observation_year'] == int(args.year))
        counts['current_department_inferred'] += bool(current_position and current_position['department_inferred'])
        counts['current_department_verified'] += bool(current_position and current_position['department'] and not current_position['department_inferred'])
        counts['first_assistant_professor_verified'] += sum(a.get('first_assistant_professor_verified', False) for a in appointments)
        counts['phd_country_known'] += bool(phd_country)
        counts['bachelor_country_known'] += bool(bachelor_country)
        counts['phd_department_inferred'] += bool(department) and not bool(verified_department)
        counts['phd_department_verified'] += bool(verified_department)
        counts['phd_domestic'] += phd_country == 'KR'
        counts['phd_domestic_department_inferred'] += phd_country == 'KR' and bool(department) and not bool(verified_department)
        counts['phd_' + basis] += 1
        for index, segment in enumerate(person['career']):
            ids = phd_units if segment['stage'] == 'doctoral' else resolve_units(segment['institution'])
            start = segment.get('start_period') or (f"{segment['start_year']}-H1" if segment.get('start_year') else None)
            end = segment.get('end_period') or (f"{segment['end_year']}-H2" if segment.get('end_year') else None)
            unit_country = resolved_country(ids, phd_country if segment['stage'] == 'doctoral' else None)
            unit_department, unit_support, unit_basis = infer_department(uid, ids, start, end)
            verified_unit = segment['stage'] == 'doctoral' and bool(verified_department)
            if verified_unit:
                unit_department, unit_support, unit_basis = verified_department, 0, 'verified_degree_record'
            row['career_units'].append({
                'segment_index': index, 'institution': segment['institution'],
                'institution_canonical': canonical_institution(ids),
                'start_year': segment['start_year'], 'end_year': segment['end_year'],
                'country': unit_country, 'department': unit_department,
                'department_inferred': bool(unit_department) and not verified_unit,
                'department_evidence': unit_basis,
                'department_supporting_affiliations': unit_support,
            })
            counts['career_segments'] += 1
            counts['career_country_known'] += bool(unit_country)
            counts['career_department_inferred'] += bool(unit_department) and not verified_unit
            counts['career_department_verified'] += verified_unit
            counts['career_domestic'] += unit_country == 'KR'
            counts['career_domestic_department_inferred'] += unit_country == 'KR' and bool(unit_department) and not verified_unit
        output[public_id] = row

    connection.close()
    manifest = {
        'release_year': dashboard['meta']['release_year'],
        'public_data_sha256': hashlib.sha256(public_bytes).hexdigest(),
        'source': 'existing KOAD-filtered 2026 private build source mapped to existing anonymous IDs',
        'country_rule': 'explicit degree country and unique exact institution alias; conflicts remain unknown',
        'department_rule': 'unique formal department from kept author affiliations at the same institutional unit and public career interval; any conflicting or unresolved formal labels excluded',
        'degree_department_verified': bool(counts['phd_department_verified']),
        'doctoral_period_estimated': True,
        'faculty_appointment_rule': 'individual observed roster years only, plus explicitly reviewed official employment intervals; publication career stages never establish faculty employment or first assistant professorship',
        'observed_terms_rule': 'actual semester_roster terms only; term/year/semester agree, duplicates removed, no inferred terms for official profile or CV intervals',
        'current_position_rule': 'latest observed roster institution/year; inferred department uses unique formal unit in the latest kept affiliation period at that institution, or explicit reviewed official current unit',
        'bachelor_department_available': False,
        'private_fields_exported': False,
        'counts': dict(sorted(counts.items())),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    output_bytes = (json.dumps(output, ensure_ascii=False, separators=(',', ':')) + '\n').encode('utf-8')
    manifest['metadata_sha256'] = hashlib.sha256(output_bytes).hexdigest()
    args.output.write_bytes(output_bytes)
    manifest_path = args.output.with_name(args.output.stem + '.manifest.json')
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--private-project', type=Path, required=True)
    parser.add_argument('--public-data', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--source-db', type=Path)
    parser.add_argument('--anon-salt', type=Path)
    parser.add_argument('--verified-departments-db', type=Path, help='Optional private RISS/KISS second-verification overlay; never copied to public output.')
    parser.add_argument('--lifetime-evidence-json', type=Path, help='Optional private reviewed official profile/CV overlay; bound to public release hash and exact private identity/degree anchors.')
    parser.add_argument('--year', default='2026')
    run(parser.parse_args())
