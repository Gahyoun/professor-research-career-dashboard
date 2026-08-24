#!/usr/bin/env python3
import argparse
import base64
import gzip
import hashlib
import hmac
import json
import os
import re
import secrets
import shutil
import sqlite3
from collections import defaultdict
from pathlib import Path

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

parser = argparse.ArgumentParser(description='Build anonymized public dashboard assets.')
parser.add_argument('--year', default=os.environ.get('RELEASE_YEAR', '2026'))
parser.add_argument('--project-root', default=str(Path(__file__).resolve().parents[2]))
parser.add_argument(
    '--reuse-encrypted-names', action='store_true',
    help='Reuse the existing encrypted name bundle for a filter-only rebuild',
)
args = parser.parse_args()

root = Path(args.project_root)
year = str(args.year)
cache = root / 'backend' / 'cache' / year
release_dir = root / 'data' / 'releases' / year
public_data = root / 'public' / 'data'
public_downloads = root / 'public' / 'downloads'
private_dir = root / '.private'
for directory in (release_dir, public_data, public_downloads, private_dir):
    directory.mkdir(parents=True, exist_ok=True)

password = os.environ.get('NAMES_PASSWORD')
if not password and not args.reuse_encrypted_names:
    raise SystemExit('NAMES_PASSWORD is required and is never written to disk')
db_path = Path((cache / 'source_db_path.txt').read_text().strip())
role_dir = cache / 'work_role_batches'
alias_role_dir = cache / 'alias_work_role_batches'
sources = json.loads((cache / 'sources.json').read_text())

anon_salt_path = private_dir / 'anon_salt.bin'
if not anon_salt_path.exists():
    anon_salt_path.write_bytes(secrets.token_bytes(32))
anon_salt = anon_salt_path.read_bytes()

def anon_id(uid):
    digest = hmac.new(anon_salt, uid.encode(), hashlib.sha256).digest()
    token = base64.b32encode(digest).decode().rstrip('=')[:10]
    return f'P-{token}'

def compact(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'))

campus_aliases = {
    'Korea-Sejong': 'Korea University (Sejong Campus)',
    'Korea_sejong': 'Korea University (Sejong Campus)',
    'Yonsei-Mirae': 'Yonsei University (Mirae Campus)',
    'Yonsei_Mirae': 'Yonsei University (Mirae Campus)',
    'Hanyang-ERICA': 'Hanyang University (ERICA Campus)',
    'Hanyang_ERICA': 'Hanyang University (ERICA Campus)',
}
main_campus_aliases = {
    'Korea': 'Korea University (Seoul Campus)',
    'Yonsei': 'Yonsei University (Seoul Campus)',
    'Hanyang': 'Hanyang University (Seoul Campus)',
}
institution_full_name_aliases = {}

def canonical_institution(full_name, raw_name=None, current_profile=False):
    raw = (raw_name or '').strip()
    if raw in campus_aliases:
        return campus_aliases[raw]
    if full_name == 'Yonsei University Mirae Campus':
        return 'Yonsei University (Mirae Campus)'
    if current_profile and raw in main_campus_aliases:
        return main_campus_aliases[raw]
    alias = institution_full_name_aliases.get(raw.lower())
    if alias:
        return alias
    if full_name == 'Gyeongsang':
        return 'Gyeongsang National University'
    return full_name or raw_name

def canonical_country(value):
    if not value:
        return value
    country = re.sub(r'\s+', ' ', value).strip()
    return {
        'koreea': 'Korea',
        'koresa': 'Korea',
    }.get(country.casefold(), country)

def clean_department(label):
    if not label:
        return None
    parts = [x.strip() for x in re.split(r'\s*/\s*|\s+and\s+', label) if x.strip()]
    for part in parts:
        if re.search(r'(?i)\bdepartment\b|학과', part):
            return part[:160]
    return parts[0][:160] if parts else None

def source_impact(source_id):
    source = sources.get(source_id or '', {})
    value = (source.get('summary_stats') or {}).get('2yr_mean_citedness')
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None

def impact_band(value):
    if value is None:
        return 'unknown'
    if value < 2:
        return 'low'
    if value < 5:
        return 'medium'
    return 'high'

# Role/source enrichment is intentionally stored only in ignored backend/cache.
roles = {}
for file in sorted(role_dir.glob('batch_*.jsonl.gz')):
    with gzip.open(file, 'rt') as fh:
        for line in fh:
            if not line.strip():
                continue
            row = json.loads(line)
            roles[(row['target_author_id'], row['work_id'])] = row

alias_roles = []
for file in sorted(alias_role_dir.glob('batch_*.jsonl.gz')):
    with gzip.open(file, 'rt') as fh:
        alias_roles.extend(json.loads(line) for line in fh if line.strip())

uri = f'file:{db_path.resolve()}?mode=ro&immutable=1'
con = sqlite3.connect(uri, uri=True)
con.row_factory = sqlite3.Row
koad_applied = bool(con.execute(
    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='koad_application_audit'"
).fetchone())
koad_changed_work_count = con.execute(
    'SELECT COUNT(*) FROM koad_application_audit'
).fetchone()[0] if koad_applied else 0

for row in con.execute('''
  SELECT ia.raw_label,iu.display_name,ia.confidence
  FROM institution_aliases ia JOIN institution_units iu ON iu.unit_id=ia.unit_id
  WHERE ia.confidence>=0.9
  ORDER BY ia.raw_label,CASE ia.context WHEN 'current_institution' THEN 0 ELSE 1 END,ia.confidence DESC
'''):
    institution_full_name_aliases.setdefault(row['raw_label'].strip().lower(), row['display_name'])

institution_full_name_aliases.update({
    'seoul': 'Seoul National University',
    'kaist': 'Korea Advanced Institute of Science and Technology',
    'postech': 'Pohang University of Science and Technology',
    'korea': 'Korea University',
    'yonsei': 'Yonsei University',
    'sungkyunkwan': 'Sungkyunkwan University',
    'mit': 'Massachusetts Institute of Technology',
    'dankuk': 'Dankook University',
    'ulsan': 'University of Ulsan',
    'konkuk_glocal': 'Konkuk University (GLOCAL Campus)',
    'konkuk-glocal': 'Konkuk University (GLOCAL Campus)',
    'kumoh': 'Kumoh National Institute of Technology',
    'andong': 'Gyeongguk National University (Andong Campus)',
    'seokyeong': 'Seokyeong University',
    'inje': 'Inje University',
    'daegu haany': 'Daegu Haany University',
    'kmou': 'Korea Maritime and Ocean University',
    'wonkwang': 'Wonkwang University',
    'dongshin': 'Dongshin University',
    'kosin': 'Kosin University',
    'jungwon': 'Jungwon University',
    'yong in': 'Yong In University',
    'donggkuk_wise': 'Dongguk University (WISE Campus)',
})

education = defaultdict(dict)
for row in con.execute('''
  SELECT e.professor_uid,e.degree_level,e.institution_raw,e.institution_unit_id,e.country,e.award_year,
         e.inferred_start_year,iu.display_name AS full_name
  FROM education e LEFT JOIN institution_units iu ON iu.unit_id=e.institution_unit_id
  WHERE e.degree_level IN ('bachelor','phd')
'''):
    education[row['professor_uid']][row['degree_level']] = dict(row)

current_departments = {}
for row in con.execute('''
  SELECT a.professor_uid,a.unit_label,a.period,a.work_count,a.confidence
  FROM affiliation_periods a JOIN professors p USING(professor_uid)
  WHERE a.institution_unit_id=p.latest_institution_unit_id AND a.unit_label IS NOT NULL
  ORDER BY a.professor_uid,a.period DESC,
           CASE a.confidence WHEN 'confirmed' THEN 4 WHEN 'high' THEN 3 WHEN 'medium' THEN 2 ELSE 1 END DESC,
           a.work_count DESC
'''):
    current_departments.setdefault(row['professor_uid'], clean_department(row['unit_label']))

career_by_uid = defaultdict(list)
for row in con.execute('''
  SELECT c.professor_uid,c.position_type,c.position_no,
         COALESCE(iu.display_name,c.institution_name) AS institution_name,
         c.start_period,c.end_period,c.start_year,c.end_year,c.confidence,c.reasoning,
         c.is_institution_successor
  FROM career_positions_v2 c LEFT JOIN institution_units iu ON iu.unit_id=c.institution_unit_id
  ORDER BY c.professor_uid,c.start_year,c.start_period,c.institution_name
'''):
    stage = {'doctoral_training': 'doctoral', 'postdoctoral_or_research': 'postdoc', 'faculty': 'faculty'}.get(row['position_type'])
    if not stage:
        continue
    career_by_uid[row['professor_uid']].append({
        'stage': stage, 'position_no': row['position_no'], 'institution': row['institution_name'],
        'start_period': row['start_period'], 'end_period': row['end_period'],
        'start_year': row['start_year'], 'end_year': row['end_year'],
        'confidence': row['confidence'], 'is_institution_successor': bool(row['is_institution_successor']),
        'evidence_basis': row['reasoning'], 'is_estimated': False,
    })

same_phd_affiliations = defaultdict(list)
for row in con.execute('''
  SELECT a.professor_uid,a.period,a.work_count,a.institution_unit_id
  FROM affiliation_periods a JOIN education e
    ON e.professor_uid=a.professor_uid AND e.degree_level='phd'
   AND e.institution_unit_id=a.institution_unit_id
  WHERE a.work_count>0
  ORDER BY a.professor_uid,a.period
'''):
    same_phd_affiliations[row['professor_uid']].append(dict(row))

domestic_department_affiliations = defaultdict(list)
for row in con.execute('''
  SELECT a.professor_uid,a.period,a.work_count,a.unit_label,a.institution_unit_id,
         iu.display_name AS institution_name
  FROM affiliation_periods a JOIN institution_units iu ON iu.unit_id=a.institution_unit_id
  WHERE a.work_count>0 AND iu.country_code='KR' AND iu.institution_type='education'
    AND a.unit_label IS NOT NULL
  ORDER BY a.professor_uid,a.period
'''):
    if re.search(r'(?i)research\s+(assistant\s+)?professor|research\s+prof\b|연구교수', row['unit_label'] or ''):
        continue
    if re.search(r'(?i)\bdepartment\b|학과|학부', row['unit_label'] or ''):
        domestic_department_affiliations[row['professor_uid']].append(dict(row))

research_professor_affiliations = defaultdict(list)
for row in con.execute('''
  SELECT r.professor_uid,r.period,COALESCE(iu.display_name,r.institution_name) AS institution_name,
         r.unit_label
  FROM raw_affiliation_units r LEFT JOIN institution_units iu ON iu.unit_id=r.institution_unit_id
  WHERE r.identity_decision='keep' AND (
    lower(COALESCE(r.unit_label,'')) LIKE '%research professor%'
    OR lower(COALESCE(r.unit_label,'')) LIKE '%research prof%'
    OR r.unit_label LIKE '%연구교수%'
  )
  ORDER BY r.professor_uid,r.period
'''):
    research_professor_affiliations[row['professor_uid']].append(dict(row))

def normalized_source_id(value):
    return re.sub(r'[^a-z0-9]', '', (value or '').lower())

def period_index(period):
    match = re.fullmatch(r'(\d{4})-H([12])', period or '')
    return int(match.group(1)) * 2 + int(match.group(2)) - 1 if match else None

def consecutive_period_groups(rows):
    groups = []
    for row in rows:
        index = period_index(row.get('period'))
        if index is None:
            continue
        if not groups or index > groups[-1][-1][0] + 1:
            groups.append([])
        groups[-1].append((index, row))
    return [[item[1] for item in group] for group in groups]

gyeongguk_names = {
    'Andong', 'Andong National University', 'Gyeongguk National University',
    'Gyeongguk National University (Andong Campus)',
}

def split_gyeongguk_successor(careers):
    """Keep historical Andong naming and use the successor name from 2025-H1."""
    result = []
    for original in careers:
        item = dict(original)
        if item['institution'] not in gyeongguk_names:
            result.append(item)
            continue
        start_year = item.get('start_year') or 2025
        end_year = item.get('end_year') or int(year)
        if end_year < 2025:
            item['institution'] = 'Andong National University'
            item['is_institution_successor'] = False
            result.append(item)
            continue
        if start_year < 2025:
            previous = dict(item)
            previous.update({
                'institution': 'Andong National University', 'end_period': '2024-H2',
                'end_year': 2024, 'is_institution_successor': False,
            })
            result.append(previous)
            item.update({'start_period': '2025-H1', 'start_year': 2025})
        item['institution'] = 'Gyeongguk National University (Andong Campus)'
        item['is_institution_successor'] = True
        item['evidence_basis'] = '2025-03 국립안동대학교·경북도립대학교 통합 출범에 따른 기관 승계'
        result.append(item)
    return result

professors = []
private_names = {}
uid_to_public = {}
source_to_uid = {}
primary_author_by_uid = {}
for row in con.execute('''
  SELECT p.*,iu.display_name AS current_full_name
  FROM professors p LEFT JOIN institution_units iu ON iu.unit_id=p.latest_institution_unit_id
  ORDER BY p.subject,p.professor_uid
'''):
    uid = row['professor_uid']
    pid = anon_id(uid)
    uid_to_public[uid] = pid
    source_to_uid[normalized_source_id(row['source_professor_id'])] = uid
    primary_author_by_uid[uid] = row['openalex_id']
    private_names[pid] = row['name']
    bachelor = education.get(uid, {}).get('bachelor', {})
    phd = education.get(uid, {}).get('phd', {})
    phd_year = row['phd_year'] or phd.get('award_year')
    doctoral_start_year = int(phd_year) - 5 if phd_year else None
    base_careers = [dict(item) for item in career_by_uid.get(uid, [])]
    if doctoral_start_year is not None:
        temporally_valid_careers = []
        for item in base_careers:
            if item['stage'] == 'doctoral':
                temporally_valid_careers.append(item)
                continue
            if item.get('end_year') is not None and int(item['end_year']) < doctoral_start_year:
                continue
            if item.get('start_year') is not None and int(item['start_year']) < doctoral_start_year:
                item['start_year'] = doctoral_start_year
                item['start_period'] = f'{doctoral_start_year}-H1'
                item['evidence_basis'] = f"{item.get('evidence_basis') or ''}; 박사학위-5년 시간 게이트로 시작점 절단".strip('; ')
            temporally_valid_careers.append(item)
        base_careers = temporally_valid_careers
    research_professor_institutions = {item['institution_name'] for item in research_professor_affiliations.get(uid, [])}
    base_careers = [item for item in base_careers if not (item['stage'] == 'faculty' and item['institution'] in research_professor_institutions)]
    careers = [item for item in base_careers if item['stage'] != 'doctoral'] if phd_year else base_careers

    existing_research_postdocs = {item['institution'] for item in careers if item['stage'] == 'postdoc'}
    for research_row in research_professor_affiliations.get(uid, []):
        if research_row['institution_name'] in existing_research_postdocs:
            continue
        period = research_row['period']
        careers.append({
            'stage': 'postdoc', 'position_no': None, 'institution': research_row['institution_name'],
            'start_period': period, 'end_period': period,
            'start_year': int(period[:4]), 'end_year': int(period[:4]),
            'confidence': 'confirmed', 'is_institution_successor': False,
            'evidence_basis': '연구교수 직함 원문 확인: 포닥·연구원으로 우선 분류', 'is_estimated': False,
        })

    bachelor_name = canonical_institution(bachelor.get('full_name'), bachelor.get('institution_raw'))
    if phd_year:
        phd_name = canonical_institution(phd.get('full_name'), phd.get('institution_raw'))
        if phd_name:
            careers.append({
                'stage': 'doctoral', 'position_no': None, 'institution': phd_name,
                'start_period': f'{int(phd_year) - 5}-H1', 'end_period': f'{int(phd_year)}-H2',
                'start_year': int(phd_year) - 5, 'end_year': int(phd_year),
                'confidence': 'estimated', 'is_institution_successor': False,
                'evidence_basis': '박사학위 연도를 끝점으로 최근 5년 추정', 'is_estimated': True,
            })

    faculties = [x for x in careers if x['stage'] == 'faculty']
    faculty_starts = [x['start_year'] for x in faculties if x.get('start_year')]
    postdoc_limit = min(faculty_starts) if faculty_starts else row['appointment_year']
    phd_name = canonical_institution(phd.get('full_name'), phd.get('institution_raw'))
    if phd_year and phd_name:
        evidence_rows = []
        for evidence in same_phd_affiliations.get(uid, []):
            evidence_year = int(evidence['period'][:4])
            if evidence_year <= int(phd_year) or (postdoc_limit and evidence_year >= int(postdoc_limit)):
                continue
            evidence_rows.append(evidence)
        existing_same = [x for x in careers if x['stage'] == 'postdoc' and x['institution'] == phd_name]
        if not existing_same:
            for group in consecutive_period_groups(evidence_rows):
                first, last = group[0], group[-1]
                careers.append({
                    'stage': 'postdoc', 'position_no': None, 'institution': phd_name,
                    'start_period': first['period'], 'end_period': last['period'],
                    'start_year': int(first['period'][:4]), 'end_year': int(last['period'][:4]),
                    'confidence': 'high', 'is_institution_successor': False,
                    'evidence_basis': '박사학위 이후 동일기관 저자소속 논문 증거', 'is_estimated': False,
                })

    current_faculty_start = min(faculty_starts) if faculty_starts else row['appointment_year']
    existing_faculty_institutions = {item['institution'] for item in faculties}
    department_by_institution = defaultdict(list)
    for evidence in domestic_department_affiliations.get(uid, []):
        evidence_year = int(evidence['period'][:4])
        if phd_year and evidence_year <= int(phd_year):
            continue
        if current_faculty_start and evidence['period'] >= f'{int(current_faculty_start)}-H2':
            continue
        if evidence['institution_name'] in existing_faculty_institutions:
            continue
        department_by_institution[evidence['institution_name']].append(evidence)
    for institution_name, evidence_rows in department_by_institution.items():
        distinct_periods = sorted({item['period'] for item in evidence_rows})
        if len(distinct_periods) < 2:
            continue
        if current_faculty_start:
            current_start_index = period_index(f'{int(current_faculty_start)}-H2')
            last_evidence_index = period_index(distinct_periods[-1])
            if current_start_index is not None and last_evidence_index is not None and current_start_index - last_evidence_index > 2:
                continue
        overlaps_postdoc = any(
            item['stage'] == 'postdoc' and item.get('start_year') is not None and
            any(item['start_year'] <= int(period[:4]) <= (item.get('end_year') or int(period[:4])) for period in distinct_periods)
            for item in careers
        )
        if overlaps_postdoc:
            continue
        careers.append({
            'stage': 'faculty', 'position_no': None, 'institution': institution_name,
            'start_period': distinct_periods[0], 'end_period': distinct_periods[-1],
            'start_year': int(distinct_periods[0][:4]), 'end_year': int(distinct_periods[-1][:4]),
            'confidence': 'high', 'is_institution_successor': False,
            'evidence_basis': '국내 대학 학과 소속 논문 2개 반기 이상·포닥 비중첩·현재 교수직 직전 이동 증거', 'is_estimated': False,
        })

    careers = split_gyeongguk_successor(careers)
    if row['latest_institution_raw'] == 'Andong':
        has_current_successor = any(
            item['stage'] == 'faculty'
            and item['institution'] == 'Gyeongguk National University (Andong Campus)'
            and (item.get('end_year') or int(year)) >= int(year)
            for item in careers
        )
        if not has_current_successor:
            careers.append({
                'stage': 'faculty', 'position_no': None,
                'institution': 'Gyeongguk National University (Andong Campus)',
                'start_period': '2025-H1', 'end_period': f'{year}-H2',
                'start_year': 2025, 'end_year': int(year), 'confidence': 'confirmed',
                'is_institution_successor': True, 'is_estimated': False,
                'evidence_basis': '2025-03 국립안동대학교·경북도립대학교 통합 출범 및 최신 명부 증거',
            })
    careers.sort(key=lambda item: (item.get('start_year') or 9999, item.get('start_period') or '', item['stage'], item['institution']))
    for faculty_number, faculty in enumerate((item for item in careers if item['stage'] == 'faculty'), start=1):
        faculty['position_no'] = faculty_number
    faculties = [x for x in careers if x['stage'] == 'faculty']
    current_full = canonical_institution(row['current_full_name'], row['latest_institution_raw'], current_profile=True)
    generic_current = row['current_full_name'] or row['latest_institution_raw']
    for career in careers:
        if career['stage'] == 'faculty' and career['institution'] == generic_current:
            career['institution'] = current_full
    professors.append({
        'id': pid, 'subject': row['subject'], 'current_institution': current_full,
        'department': current_departments.get(uid),
        'bachelor_institution': bachelor_name,
        'phd_institution': canonical_institution(phd.get('full_name'), phd.get('institution_raw')),
        'phd_country': canonical_country(phd.get('country')),
        'phd_year': phd_year, 'appointment_year': row['appointment_year'],
        'first_faculty_institution': faculties[0]['institution'] if faculties else None,
        'latest_faculty_institution': faculties[-1]['institution'] if faculties else current_full,
        'career': careers, 'yearly': [],
    })

by_pid = {p['id']: p for p in professors}
alias_author_to_uid = {}
alias_path = cache / 'author_aliases.json'
if alias_path.exists():
    for record in json.loads(alias_path.read_text()):
        uid = source_to_uid.get(normalized_source_id(record.get('source_professor_id')))
        if not uid:
            continue
        for author_id in record.get('openalex_ids', []):
            if author_id == primary_author_by_uid.get(uid):
                continue
            other = alias_author_to_uid.get(author_id)
            if other and other != uid:
                raise RuntimeError(f'OpenAlex alias collision: {author_id}')
            alias_author_to_uid[author_id] = uid

year_agg = defaultdict(lambda: defaultdict(lambda: {
    'total': 0, 'first_author': 0, 'corresponding_author': 0,
    'impact_low': 0, 'impact_medium': 0, 'impact_high': 0, 'impact_unknown': 0,
    'impact_sum': 0.0, 'impact_known': 0, 'article_citations': 0,
}))
journal_agg = defaultdict(lambda: defaultdict(lambda: {'lead_work_count': 0, 'impact_sum': 0.0, 'impact_known': 0, 'journal': None}))
seen_works = defaultdict(set)

def add_role(pid, publication_year, role):
    work_id = role.get('work_id')
    if not pid or not work_id or work_id in seen_works[pid]:
        return False
    seen_works[pid].add(work_id)
    agg = year_agg[pid][int(publication_year)]
    agg['total'] += 1
    agg['first_author'] += int(role.get('author_position') == 'first')
    agg['corresponding_author'] += int(bool(role.get('is_corresponding')))
    metric = source_impact((role.get('source') or {}).get('id'))
    agg[f'impact_{impact_band(metric)}'] += 1
    if metric is not None:
        agg['impact_sum'] += metric
        agg['impact_known'] += 1
    agg['article_citations'] += int(role.get('cited_by_count') or 0)
    source = role.get('source') or {}
    journal_key = source.get('display_name') or source.get('id')
    if journal_key:
        journal = journal_agg[pid][journal_key]
        journal['lead_work_count'] += 1
        if metric is not None:
            journal['impact_sum'] += metric
            journal['impact_known'] += 1
        journal['journal'] = source.get('display_name') or journal_key
    return True

allowed_types = {'article', 'review', 'letter', 'editorial'}
for row in con.execute('''
  SELECT w.professor_uid,w.openalex_id,w.work_id,w.publication_year,w.work_type
  FROM work_authorship_evidence w JOIN professors p USING(professor_uid)
  WHERE w.identity_decision='keep' AND w.publication_year<=?
    AND (p.phd_year IS NULL OR w.publication_year>=p.phd_year-5)
''', (int(year),)):
    role = roles.get((row['openalex_id'], row['work_id']))
    if not role or not (role.get('author_position') == 'first' or role.get('is_corresponding')):
        continue
    if row['work_type'] not in allowed_types or (role.get('source') or {}).get('type') != 'journal':
        continue
    pid = uid_to_public.get(row['professor_uid'])
    if not pid:
        continue
    add_role(pid, row['publication_year'], role)

alias_work_count = 0
for role in alias_roles:
    uid = alias_author_to_uid.get(role.get('target_author_id'))
    if not uid or not (role.get('author_position') == 'first' or role.get('is_corresponding')):
        continue
    if role.get('work_type') not in allowed_types or (role.get('source') or {}).get('type') != 'journal':
        continue
    publication_year = role.get('publication_year')
    if not publication_year or int(publication_year) > int(year):
        continue
    alias_professor = by_pid.get(uid_to_public.get(uid))
    if alias_professor and alias_professor.get('phd_year') and int(publication_year) < int(alias_professor['phd_year']) - 5:
        continue
    alias_work_count += int(add_role(uid_to_public.get(uid), publication_year, role))

def stage_for_year(careers, y, phd_year, appointment_year):
    priority = {'doctoral': 1, 'postdoc': 2, 'faculty': 3}
    active = [x['stage'] for x in careers if x.get('start_year') is not None and x['start_year'] <= y <= (x.get('end_year') or y)]
    if active:
        return max(active, key=lambda x: priority[x])
    if phd_year and y <= phd_year:
        return 'doctoral'
    if appointment_year and y < appointment_year:
        return 'postdoc'
    if appointment_year and y >= appointment_year:
        return 'faculty'
    return None

for professor in professors:
    pid = professor['id']
    years = year_agg.get(pid, {})
    if years:
        doctoral_starts = [item['start_year'] for item in professor['career'] if item['stage'] == 'doctoral' and item.get('start_year')]
        chart_start = min([min(years)] + doctoral_starts)
    else:
        chart_start = None
    for y in range(chart_start, int(year) + 1) if chart_start is not None else []:
        agg = years.get(y) or {
            'total': 0, 'first_author': 0, 'corresponding_author': 0,
            'impact_low': 0, 'impact_medium': 0, 'impact_high': 0, 'impact_unknown': 0,
            'impact_sum': 0.0, 'impact_known': 0, 'article_citations': 0,
        }
        professor['yearly'].append({
            'year': y,
            'stage': stage_for_year(professor['career'], y, professor['phd_year'], professor['appointment_year']),
            'total': agg['total'], 'first_author': agg['first_author'],
            'corresponding_author': agg['corresponding_author'],
            'impact_low': agg['impact_low'], 'impact_medium': agg['impact_medium'],
            'impact_high': agg['impact_high'], 'impact_unknown': agg['impact_unknown'],
            'mean_journal_2yr_citedness': round(agg['impact_sum'] / agg['impact_known'], 3) if agg['impact_known'] else None,
            'article_citations': agg['article_citations'],
        })
    professor['lead_work_count'] = sum(x['total'] for x in professor['yearly'])
    professor['journals'] = sorted(({
        'journal': item['journal'], 'lead_work_count': item['lead_work_count'],
        'openalex_2yr_mean_citedness': round(item['impact_sum'] / item['impact_known'], 3) if item['impact_known'] else None,
    } for item in journal_agg.get(pid, {}).values()), key=lambda item: (-item['lead_work_count'], item['journal']))

filters = {
    'subjects': sorted({p['subject'] for p in professors if p['subject']}),
    'current_institutions': sorted({p['current_institution'] for p in professors if p['current_institution']}),
    'departments': sorted({p['department'] for p in professors if p['department']}),
    'phd_institutions': sorted({p['phd_institution'] for p in professors if p['phd_institution']}),
    'phd_countries': sorted({p['phd_country'] for p in professors if p['phd_country']}),
}
meta = {
    'release_year': int(year), 'professor_count': len(professors),
    'lead_work_count': sum(p['lead_work_count'] for p in professors),
    'impact_metric': 'OpenAlex source summary_stats.2yr_mean_citedness',
    'lead_definition': 'OpenAlex author_position=first OR is_corresponding=true',
    'identity_filter': (
        'KOAD career-aware same-person keep; review preserves prior decision; '
        'publication_year>=phd_year-5 when PhD year is known'
        if koad_applied else
        'identity_decision=keep (or annotated secondary ID) AND publication_year>=phd_year-5 when PhD year is known'
    ),
    'identity_filter_version': 'KOAD 1.0' if koad_applied else 'legacy',
    'identity_decisions_changed': koad_changed_work_count,
    'secondary_openalex_author_count': len(alias_author_to_uid),
    'secondary_openalex_lead_work_count': alias_work_count,
    'bachelor_display_rule': 'institution only; no timeline estimate because leave/military and other gaps are unobserved',
    'doctoral_period_rule': 'phd_degree_year-5 through phd_degree_year, estimated',
    'pre_doctoral_hard_gate': 'works and affiliations earlier than phd_degree_year-5 are duplicate_drop_candidate',
    'same_institution_postdoc_rule': 'post-PhD same-institution affiliation period with work_count>0 before first faculty appointment',
    'names_encrypted': True,
}
dashboard = {'meta': meta, 'filters': filters, 'professors': professors}
(release_dir / 'dashboard.json').write_text(compact(dashboard))

# Encrypt names; filter-only rebuilds may safely reuse the unchanged encrypted bundle.
encrypted_name_path = release_dir / 'encrypted_names.json'
if args.reuse_encrypted_names:
    if not encrypted_name_path.exists():
        raise SystemExit('--reuse-encrypted-names requires an existing release encrypted_names.json')
else:
    plain = compact(private_names).encode()
    kdf_salt, nonce = secrets.token_bytes(16), secrets.token_bytes(12)
    iterations = 600_000
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=kdf_salt, iterations=iterations)
    key = kdf.derive(password.encode())
    aad = b'professor-names-v1'
    ciphertext = AESGCM(key).encrypt(nonce, plain, aad)
    encrypted_names = {
        'version': 1, 'kdf': 'PBKDF2-SHA256', 'iterations': iterations,
        'salt': base64.b64encode(kdf_salt).decode(), 'nonce': base64.b64encode(nonce).decode(),
        'aad': base64.b64encode(aad).decode(), 'ciphertext': base64.b64encode(ciphertext).decode(),
    }
    encrypted_name_path.write_text(compact(encrypted_names))

# Public, name-free SQLite database.
public_db = release_dir / f'professor_dashboard_{year}.sqlite'
if public_db.exists():
    public_db.unlink()
pub = sqlite3.connect(public_db)
pub.executescript((root / 'backend' / 'sql' / 'schema_public.sql').read_text())
pub.executemany('INSERT INTO release_metadata VALUES (?,?)', [(k, compact(v) if isinstance(v, (dict, list, bool)) else str(v)) for k, v in meta.items()])
for p in professors:
    pub.execute('''INSERT INTO professors VALUES (?,?,?,?,?,?,?,?,?,?,?,?)''', (
        p['id'],p['subject'],p['current_institution'],p['department'],p['bachelor_institution'],p['phd_institution'],p['phd_country'],
        p['phd_year'],p['appointment_year'],p['first_faculty_institution'],
        p['latest_faculty_institution'],p['lead_work_count'],
    ))
    for c in p['career']:
        pub.execute('''INSERT INTO career_segments
          (professor_id,stage,position_no,institution,start_period,end_period,start_year,end_year,confidence,evidence_basis,is_estimated,is_institution_successor)
          VALUES (?,?,?,?,?,?,?,?,?,?,?,?)''', (
            p['id'],c['stage'],c['position_no'],c['institution'],c['start_period'],c['end_period'],
            c['start_year'],c['end_year'],c['confidence'],c.get('evidence_basis'),int(c.get('is_estimated',False)),int(c['is_institution_successor']),
        ))
    for y in p['yearly']:
        pub.execute('''INSERT INTO yearly_lead_output VALUES (?,?,?,?,?,?,?,?,?,?,?,?)''', (
            p['id'],y['year'],y['stage'],y['total'],y['first_author'],y['corresponding_author'],
            y['impact_low'],y['impact_medium'],y['impact_high'],y['impact_unknown'],
            y['mean_journal_2yr_citedness'],y['article_citations'],
        ))
    for journal in p['journals']:
        pub.execute('''INSERT INTO professor_journal_output
          (professor_id,journal,lead_work_count,openalex_2yr_mean_citedness)
          VALUES (?,?,?,?)''', (
            p['id'],journal['journal'],journal['lead_work_count'],journal['openalex_2yr_mean_citedness'],
        ))
pub.commit()
pub.execute('VACUUM')
integrity = pub.execute('PRAGMA integrity_check').fetchone()[0]
fk_errors = len(pub.execute('PRAGMA foreign_key_check').fetchall())
pub.close()

manifest = {
    **meta, 'public_db_bytes': public_db.stat().st_size,
    'sqlite_integrity': integrity, 'foreign_key_errors': fk_errors,
    'plaintext_names_in_public_assets': False,
}
(release_dir / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2))

shutil.copy2(release_dir / 'dashboard.json', public_data / 'dashboard.json')
shutil.copy2(release_dir / 'encrypted_names.json', public_data / 'encrypted_names.json')
shutil.copy2(release_dir / 'manifest.json', public_data / 'manifest.json')
shutil.copy2(public_db, public_downloads / public_db.name)
shutil.copy2(root / 'backend' / 'sql' / 'schema_public.sql', public_downloads / 'schema_public.sql')
shutil.copy2(root / 'backend' / 'sql' / 'queries_public.sql', public_downloads / 'queries_public.sql')

con.close()
print(json.dumps(manifest, ensure_ascii=False))
