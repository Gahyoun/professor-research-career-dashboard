#!/usr/bin/env python3
import argparse
import base64
import json
import os
import re
import sqlite3
from pathlib import Path

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

parser = argparse.ArgumentParser()
parser.add_argument('--year', default=os.environ.get('RELEASE_YEAR', '2026'))
parser.add_argument('--project-root', default=str(Path(__file__).resolve().parents[2]))
parser.add_argument(
    '--reuse-encrypted-names', action='store_true',
    help='Validate a filter-only rebuild that reused the existing encrypted name bundle',
)
args = parser.parse_args()
root = Path(args.project_root)
release = root / 'data' / 'releases' / str(args.year)
password = os.environ.get('NAMES_PASSWORD')
if not password and not args.reuse_encrypted_names:
    raise SystemExit('NAMES_PASSWORD is required for validation')

dashboard_path = release / 'dashboard.json'
encrypted_path = release / 'encrypted_names.json'
db_path = release / f'professor_dashboard_{args.year}.sqlite'
dashboard_text = dashboard_path.read_text()
dashboard = json.loads(dashboard_text)
encrypted = json.loads(encrypted_path.read_text())

def b64(value):
    return base64.b64decode(value)

names = None
if password:
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(), length=32, salt=b64(encrypted['salt']),
        iterations=int(encrypted['iterations']),
    )
    key = kdf.derive(password.encode())
    names = json.loads(AESGCM(key).decrypt(
        b64(encrypted['nonce']), b64(encrypted['ciphertext']), b64(encrypted['aad'])
    ))

con = sqlite3.connect(f'file:{db_path.resolve()}?mode=ro&immutable=1', uri=True)
db_counts = {
    'professors': con.execute('SELECT COUNT(*) FROM professors').fetchone()[0],
    'career_segments': con.execute('SELECT COUNT(*) FROM career_segments').fetchone()[0],
    'yearly_lead_output': con.execute('SELECT COUNT(*) FROM yearly_lead_output').fetchone()[0],
    'professor_journal_output': con.execute('SELECT COUNT(*) FROM professor_journal_output').fetchone()[0],
}
columns = [r[1] for r in con.execute('PRAGMA table_info(professors)')]
abbreviated_current = con.execute("""
  SELECT COUNT(*) FROM professors
  WHERE current_institution IN ('Gyeongsang','KAIST','POSTECH','Seoul','Yonsei','Korea')
""").fetchone()[0]
generic_multicampus_current = con.execute("""
  SELECT COUNT(*) FROM professors
  WHERE current_institution IN ('Korea University','Yonsei University','Hanyang University')
""").fetchone()[0]
year_gap_professors = con.execute("""
  SELECT COUNT(*) FROM (
    SELECT professor_id FROM yearly_lead_output GROUP BY professor_id
    HAVING COUNT(*) != MAX(year)-MIN(year)+1
  )
""").fetchone()[0]
pre_doctoral_output = con.execute("""
  SELECT COUNT(*) FROM yearly_lead_output y JOIN professors p USING(professor_id)
  WHERE p.phd_year IS NOT NULL AND y.year < p.phd_year-5 AND y.total_count > 0
""").fetchone()[0]
pre_doctoral_career = con.execute("""
  SELECT COUNT(*) FROM career_segments c JOIN professors p USING(professor_id)
  WHERE p.phd_year IS NOT NULL AND c.end_year < p.phd_year-5
""").fetchone()[0]
invalid_phd_country = con.execute("""
  SELECT COUNT(*) FROM professors
  WHERE lower(trim(COALESCE(phd_country,''))) IN ('koreea','koresa')
""").fetchone()[0]

mijin_ok = False
for pid in ('P-S4F4ZDO26D',):
    profile = con.execute("SELECT subject,current_institution FROM professors WHERE professor_id=?", (pid,)).fetchone()
    if profile != ('physics', 'Pusan National University'):
        continue
    rows = con.execute("SELECT institution,start_period,end_period FROM career_segments WHERE professor_id=? AND stage='faculty' ORDER BY start_period", (pid,)).fetchall()
    mijin_ok = any(row[0] == 'Hanyang University' and row[2] == '2025-H1' for row in rows) and any(row[0] == 'Pusan National University' and row[1] == '2025-H2' for row in rows)

sanghoon_ok = False
for pid in ('P-XKPSPQXY7D',):
    profile = con.execute("SELECT subject,current_institution FROM professors WHERE professor_id=?", (pid,)).fetchone()
    if profile != ('physics', 'Gyeongsang National University'):
        continue
    wrong = con.execute("SELECT COUNT(*) FROM career_segments WHERE professor_id=? AND stage='faculty' AND institution='Sungkyunkwan University'", (pid,)).fetchone()[0]
    expected = con.execute("SELECT COUNT(*) FROM career_segments WHERE professor_id=? AND stage='faculty' AND institution IN ('Gyeongnam National University of Science and Technology','Gyeongsang National University')", (pid,)).fetchone()[0]
    sanghoon_ok = wrong == 0 and expected == 2

research_professor_ok = False
for pid in ('P-BQLHUMLPFO',):
    rows = con.execute("SELECT stage,start_period,end_period FROM career_segments WHERE professor_id=? AND institution='Inha University'", (pid,)).fetchall()
    if rows:
        research_professor_ok = all(row[0] == 'postdoc' for row in rows) and any(row[1] == '2021-H1' and row[2] == '2021-H1' for row in rows)

gyeongguk_count = con.execute("SELECT COUNT(*) FROM professors WHERE current_institution='Gyeongguk National University (Andong Campus)'").fetchone()[0]
legacy_andong_current = con.execute("SELECT COUNT(*) FROM professors WHERE current_institution IN ('Andong','Andong National University')").fetchone()[0]
anachronistic_gyeongguk = con.execute("""
  SELECT COUNT(*) FROM career_segments
  WHERE institution LIKE 'Gyeongguk National University%'
    AND (end_year < 2025 OR start_year < 2025)
""").fetchone()[0]
integrity = con.execute('PRAGMA integrity_check').fetchone()[0]
fk_errors = len(con.execute('PRAGMA foreign_key_check').fetchall())
con.close()

ids = [p['id'] for p in dashboard['professors']]
errors = []
if not all(re.fullmatch(r'P-[A-Z2-7]{10}', pid) for pid in ids): errors.append('invalid anonymous id')
if len(ids) != len(set(ids)): errors.append('duplicate anonymous id')
if names is not None and set(ids) != set(names): errors.append('encrypted name mapping mismatch')
if names is None:
    required_encryption_keys = {'version', 'kdf', 'iterations', 'salt', 'nonce', 'aad', 'ciphertext'}
    if not required_encryption_keys.issubset(encrypted): errors.append('invalid encrypted name bundle')
if 'prof:' in dashboard_text or re.search(r'\bA\d{8,}\b', dashboard_text): errors.append('private identifier leaked')
if 'name' in columns: errors.append('plaintext name column in public DB')
if abbreviated_current: errors.append('abbreviated current institution remains')
if generic_multicampus_current: errors.append('multi-campus current institution lacks campus qualifier')
if year_gap_professors: errors.append('yearly output axis has gaps')
if pre_doctoral_output: errors.append('lead work exists before PhD-minus-5 hard gate')
if pre_doctoral_career: errors.append('career evidence exists before PhD-minus-5 hard gate')
if invalid_phd_country: errors.append('misspelled Korea remains in PhD country')
if not mijin_ok: errors.append('Lee Mijin Hanyang-to-Pusan move sentinel failed')
if not sanghoon_ok: errors.append('Lee Sang Hoon faculty/postdoc sentinel failed')
if not research_professor_ok: errors.append('research professor to postdoc sentinel failed')
if not gyeongguk_count or legacy_andong_current: errors.append('Gyeongguk National University succession sentinel failed')
if anachronistic_gyeongguk: errors.append('Gyeongguk name appears before 2025')
if integrity != 'ok' or fk_errors: errors.append('SQLite integrity failure')
if db_counts['professors'] != len(ids): errors.append('JSON/SQLite professor count mismatch')
if dashboard['meta']['lead_work_count'] <= 0: errors.append('no lead-author works')

result = {
    'passed': not errors, 'release_year': int(args.year), 'errors': errors,
    'professors': len(ids), 'decrypted_names': len(names) if names is not None else None,
    'encrypted_names_validation': 'decrypted' if names is not None else 'reused_bundle_structure',
    'lead_work_count': dashboard['meta']['lead_work_count'],
    'db_counts': db_counts, 'sqlite_integrity': integrity,
    'foreign_key_errors': fk_errors, 'abbreviated_current_institutions': abbreviated_current,
    'generic_multicampus_current_institutions': generic_multicampus_current,
    'year_gap_professors': year_gap_professors,
    'pre_doctoral_output_rows': pre_doctoral_output,
    'pre_doctoral_career_segments': pre_doctoral_career,
    'misspelled_korea_phd_country_rows': invalid_phd_country,
    'lee_mijin_move_sentinel': mijin_ok, 'lee_sanghoon_sentinel': sanghoon_ok,
    'research_professor_sentinel': research_professor_ok,
    'gyeongguk_current_professors': gyeongguk_count, 'legacy_andong_current_professors': legacy_andong_current,
    'anachronistic_gyeongguk_segments': anachronistic_gyeongguk,
    'private_identifiers_in_dashboard': 'prof:' in dashboard_text or bool(re.search(r'\bA\d{8,}\b', dashboard_text)),
}
(release / 'validation.json').write_text(json.dumps(result, ensure_ascii=False, indent=2))
print(json.dumps(result, ensure_ascii=False))
if errors:
    raise SystemExit(1)
