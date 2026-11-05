"""Career-consistency namesake rule, shared by the private build and the public patch.

An OpenAlex author ID can absorb a namesake's papers (observed 2026-11-05: a network
scientist's ID also held food-science papers by a namesake, with no or unrelated
affiliations; even a coauthor ID was shared by two people of the same common name). KOAD
keeps such papers when the ID itself looks right. This rule judges each published
(researcher, work) pair against the researcher's own career:

  anchor     the authorship's institution matches an institution of the researcher's career
             (doctoral, postdoc, faculty) — the work is consistent.
  A non-anchor work is
    kept     if it shares >= 2 coauthor IDs with the anchor works (one shared coauthor is not
             enough: common names merge in OpenAlex too). Visits abroad pass here;
    dropped  'career_institution_mismatch' if its authorship names institutions, none of
             them in the career;
    dropped  'career_coauthor_mismatch' if it names no institution, has coauthors, and shares
             none of them with the anchor works;
    dropped  'career_field_mismatch' if it names no institution, shares one coauthor, and its
             OpenAlex subfield is not among the anchor works' subfields;
    kept     otherwise (not enough evidence: solo papers, one shared coauthor in a known subfield).
The rule is not applied to researchers with fewer than MIN_ANCHORS anchor works (no basis).
"""
import json
import re
import unicodedata

MIN_ANCHORS = 3
REASONS = ('career_institution_mismatch', 'career_coauthor_mismatch', 'career_field_mismatch')


def norm_institution(name):
    """'Umeå University' == 'umea university'; campus qualifiers and punctuation ignored."""
    s = unicodedata.normalize('NFKD', name or '').encode('ascii', 'ignore').decode().lower()
    s = re.sub(r'\(.*?\)', ' ', s)
    s = re.sub(r'\b(the|of|campus)\b', ' ', s)
    return re.sub(r'[^a-z0-9]+', '', s)


def classify(works, career_institutions, min_anchors=MIN_ANCHORS):
    """works: [{'id', 'institutions': [names or keys], 'coauthors': [ids], 'subfield': str|None}]
    career_institutions: names or keys of the researcher's career units.
    Returns {work_id: reason} for dropped works only."""
    career = {norm_institution(c) for c in career_institutions if c}
    career.discard('')
    anchors, rest = [], []
    for w in works:
        inst = {norm_institution(i) for i in w.get('institutions') or [] if i}
        inst.discard('')
        (anchors if inst & career else rest).append((w, inst))
    if len(anchors) < min_anchors:
        return {}
    anchor_coauthors = {c for w, _ in anchors for c in w.get('coauthors') or [] if c}
    anchor_subfields = {w.get('subfield') for w, _ in anchors if w.get('subfield')}
    out = {}
    for w, inst in rest:
        coauthors = {c for c in w.get('coauthors') or [] if c}
        shared = len(coauthors & anchor_coauthors)
        if shared >= 2:
            continue
        if inst:
            out[w['id']] = 'career_institution_mismatch'
        elif coauthors and shared == 0:
            out[w['id']] = 'career_coauthor_mismatch'
        elif shared == 1 and w.get('subfield') and w['subfield'] not in anchor_subfields:
            out[w['id']] = 'career_field_mismatch'
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
    co_col, field_col = col('work_authorship_evidence', 'coauthor_ids_json'), col('work_authorship_evidence', 'subfield_name')
    for uid, wid, coauthors, field in con.execute(f'''
        SELECT w.professor_uid, w.work_id, {'w.' + co_col if co_col != 'NULL' else 'NULL'}, {'w.' + field_col if field_col != 'NULL' else 'NULL'}
        FROM work_authorship_evidence w JOIN koad.work_decision k USING(professor_uid, work_id)
        WHERE w.identity_decision='keep' AND k.decision='true_paper' '''):
        try:
            co = json.loads(coauthors or '[]')
        except ValueError:
            co = []
        works[(uid, wid)] = {'id': wid, 'institutions': [], 'coauthors': co, 'subfield': field}
    for uid, wid, unit, name in con.execute(f"SELECT professor_uid, work_id, {col('raw_affiliation_units', 'institution_unit_id')}, "
                                            f"{col('raw_affiliation_units', 'institution_name')} FROM raw_affiliation_units"):
        w = works.get((uid, wid))
        if w is not None:
            w['institutions'].extend(keys(unit, name))
    by_uid = {}
    for (uid, _), w in works.items():
        by_uid.setdefault(uid, []).append(w)
    rows = [(uid, wid, reason) for uid, ws in by_uid.items()
            for wid, reason in classify(ws, career.get(uid, ())).items()]
    con.executemany('INSERT OR REPLACE INTO temp.career_inconsistent VALUES (?,?,?)', rows)
    return len(rows)
