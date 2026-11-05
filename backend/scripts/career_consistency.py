"""Career-consistency namesake rule, shared by the private build and the public patch.

An OpenAlex author ID can absorb a namesake's papers (2026-11-05: a network scientist's ID
held food-science papers; a coauthor ID was even shared by two people of a common name).
Calibrated on all 255,856 published papers (2026-11-05): a first rule that dropped any work
without a career institution would have removed 17,030 papers of 2,098 researchers, many of
them genuine (visits, joint institutes, large collaborations). This rule is conservative:

  anchor      the authorship's institution matches a career institution (doctoral, postdoc,
              faculty); anchors define the researcher's fields, subfields and coauthors.
  A non-anchor work is KEPT when
    * its OpenAlex domain is inside the researcher's home domains (HOME[subject]), or
    * it shares >= 2 coauthor IDs with the anchor works.
  Otherwise it is DROPPED when
    * it shares exactly one coauthor and its field is absent from the anchors
      ('career_field_mismatch'), or
    * it shares none, has coauthors, and its subfield is absent from the anchors
      ('career_subfield_mismatch').
  Researchers with fewer than MIN_ANCHORS anchor works are not judged.
On the published release this drops 1,083 papers of 268 researchers.
"""
import json
import re
import unicodedata

MIN_ANCHORS = 3
REASONS = ('career_field_mismatch', 'career_subfield_mismatch')
HOME = {'physics': {'Physical Sciences'}, 'mathematics': {'Physical Sciences'},
        'chemistry': {'Physical Sciences', 'Life Sciences'}, 'biology': {'Life Sciences', 'Health Sciences'}}


def norm_institution(name):
    """'Umeå University' == 'umea university'; campus qualifiers and punctuation ignored."""
    s = unicodedata.normalize('NFKD', name or '').encode('ascii', 'ignore').decode().lower()
    s = re.sub(r'\(.*?\)', ' ', s)
    s = re.sub(r'\b(the|of|campus)\b', ' ', s)
    return re.sub(r'[^a-z0-9]+', '', s)


def classify(works, career_institutions, subject=None, min_anchors=MIN_ANCHORS):
    """works: [{'id', 'institutions': [names or keys], 'coauthors': [ids], 'field', 'subfield', 'domain'}]
    career_institutions: names or keys of the researcher's career units; subject selects HOME.
    Returns {work_id: reason} for dropped works only."""
    career = {norm_institution(c) for c in career_institutions if c}
    career.discard('')
    home = HOME.get(subject, set())
    anchors, rest = [], []
    for w in works:
        inst = {norm_institution(i) for i in w.get('institutions') or [] if i}
        inst.discard('')
        (anchors if inst & career else rest).append(w)
    if len(anchors) < min_anchors:
        return {}
    anchor_coauthors = {c for w in anchors for c in w.get('coauthors') or [] if c}
    anchor_fields = {w.get('field') for w in anchors if w.get('field')}
    anchor_subfields = {w.get('subfield') for w in anchors if w.get('subfield')}
    out = {}
    for w in rest:
        if not w.get('domain') or w['domain'] in home:
            continue
        coauthors = {c for c in w.get('coauthors') or [] if c}
        shared = len(coauthors & anchor_coauthors)
        if shared >= 2:
            continue
        if shared == 1 and w.get('field') and w['field'] not in anchor_fields:
            out[w['id']] = 'career_field_mismatch'
        elif shared == 0 and coauthors and w.get('subfield') and w['subfield'] not in anchor_subfields:
            out[w['id']] = 'career_subfield_mismatch'
    return out


def prepare(con):
    """Private build: create temp.career_inconsistent(professor_uid, work_id, reason) from the
    source DB (koad attached), for pairs that pass KOAD and source keep. Missing tables give an
    empty table, so STRICT_IDENTITY_PREDICATE stays valid everywhere. Returns the row count."""
    con.execute('CREATE TEMP TABLE IF NOT EXISTS career_inconsistent '
                '(professor_uid TEXT NOT NULL, work_id TEXT NOT NULL, reason TEXT NOT NULL, PRIMARY KEY(professor_uid, work_id))')
    con.execute('DELETE FROM temp.career_inconsistent')
    have = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    try:
        koad = bool(con.execute("SELECT 1 FROM koad.sqlite_master WHERE type='table' AND name='work_decision'").fetchone())
    except Exception:
        koad = False
    if not koad or not {'work_authorship_evidence', 'raw_affiliation_units', 'career_positions_v2'} <= have:
        return 0
    def cols(table):
        return {r[1] for r in con.execute(f'PRAGMA table_info({table})')}

    def col(table, name):   # tolerate older or partial schemas: a missing column reads as NULL
        return name if name in cols(table) else 'NULL'

    units = {}
    if 'institution_units' in have:
        units = {r[0]: r[1] for r in con.execute('SELECT unit_id, display_name FROM institution_units')}

    def keys(unit_id, name):
        return [k for k in (f'unit:{unit_id}' if unit_id else None, units.get(unit_id), name) if k]

    career = {}
    for uid, unit, name in con.execute(f"SELECT professor_uid, {col('career_positions_v2', 'institution_unit_id')}, "
                                       f"{col('career_positions_v2', 'institution_name')} FROM career_positions_v2"):
        career.setdefault(uid, set()).update(keys(unit, name))
    works = {}
    q = lambda c: 'w.' + c if col('work_authorship_evidence', c) != 'NULL' else 'NULL'
    for uid, wid, coauthors, field, subfield, domain in con.execute(f'''
        SELECT w.professor_uid, w.work_id, {q('coauthor_ids_json')}, {q('field_name')}, {q('subfield_name')}, {q('domain_name')}
        FROM work_authorship_evidence w JOIN koad.work_decision k USING(professor_uid, work_id)
        WHERE w.identity_decision='keep' AND k.decision='true_paper' '''):
        try:
            co = json.loads(coauthors or '[]')
        except ValueError:
            co = []
        works[(uid, wid)] = {'id': wid, 'institutions': [], 'coauthors': co, 'field': field, 'subfield': subfield, 'domain': domain}
    for uid, wid, unit, name in con.execute(f"SELECT professor_uid, work_id, {col('raw_affiliation_units', 'institution_unit_id')}, "
                                            f"{col('raw_affiliation_units', 'institution_name')} FROM raw_affiliation_units"):
        w = works.get((uid, wid))
        if w is not None:
            w['institutions'].extend(keys(unit, name))
    by_uid = {}
    for (uid, _), w in works.items():
        by_uid.setdefault(uid, []).append(w)
    subjects = dict(con.execute(f"SELECT professor_uid, {col('professors', 'subject')} FROM professors")) if 'professors' in have else {}
    rows = [(uid, wid, reason) for uid, ws in by_uid.items()
            for wid, reason in classify(ws, career.get(uid, ()), subjects.get(uid)).items()]
    con.executemany('INSERT OR REPLACE INTO temp.career_inconsistent VALUES (?,?,?)', rows)
    return len(rows)
