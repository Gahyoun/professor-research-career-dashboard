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

career_conflict() (2026-11-11) adds a contradicting-affirmation rule: while the career places the
researcher at an institution (doctoral or faculty segment), a work whose authorship names only
other universities or hospitals is a namesake's. Calibrated on all 257,996 published papers: the
unrestricted version flagged 3,128 papers of 586 researchers, including co-located institutes (IBS
with KAIST students, Inserm with Paris students), parent/child names (Stanford Medicine / Stanford
University), publication lag after a move and master's work published during an estimated
doctoral period. The final rule (institution types, OpenAlex lineage, lag-aware years, a subfield
mismatch in doctoral periods) drops 1,849 papers of 265 researchers. corroboration() is the
stricter per-researcher decision 'require_corroboration'.
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


def corroboration(works, career_segments, subject=None):
    """Strict rule for a researcher whose OpenAlex author ID is known to hold a namesake
    (explicit decision 'require_corroboration'). A published work is kept only when two
    mutually supporting affirmations hold:
      identity  the authorship institution is a career institution within that segment +-1
                year, OR the work shares a coauthor ID with the career-anchored works;
      subject   the work's subfield appears among the anchored works, OR its domain is a
                home domain of the researcher's subject.
    A shared coauthor alone is not enough (common-name coauthor IDs are merged too), nor is
    a matching topic alone (a namesake can work in a related area).
    works: [{'id', 'year', 'institutions', 'coauthors', 'subfield', 'domain'}];
    career_segments: [(institution, start_year, end_year)]. Returns {work_id: 'uncorroborated'}."""
    segs = [(norm_institution(n), s, e) for n, s, e in career_segments if n and s]
    home = HOME.get(subject, set())

    def anchored(w):
        y = w.get('year') or 0
        return any(norm_institution(i) == n and s - 1 <= y <= (e or 9999) + 1
                   for i in w.get('institutions') or [] for n, s, e in segs)
    anchors = [w for w in works if anchored(w)]
    subfields = {w.get('subfield') for w in anchors if w.get('subfield')}
    out = {}
    for w in works:
        co = {c for c in w.get('coauthors') or [] if c}
        others = {c for a in anchors if a is not w for c in a.get('coauthors') or [] if c}
        identity = anchored(w) or bool(co & others)
        subject_ok = w.get('subfield') in subfields or w.get('domain') in home
        if not (identity and subject_ok):
            out[w['id']] = 'uncorroborated'
    return out


CONFLICT_TYPES = {'education', 'healthcare'}
GENERIC = re.compile(r'\b(the|of|at|and|for|in|de|du|la|university|universit\w*|college|institute|institut|school|faculty|'
                     r'medicine|medical|center|centre|hospital|national|state|campus|science|sciences|technology|research|'
                     r'graduate|main|seoul|korea|new|york)\b')


def core_name(name):
    """Distinctive part of an institution name: 'State University of New York at Stony Brook' -> 'stonybrook'."""
    s = unicodedata.normalize('NFKD', name or '').encode('ascii', 'ignore').decode().lower()
    s = re.sub(r'\(.*?\)', ' ', s)
    return re.sub(r'[^a-z0-9]+', '', GENERIC.sub(' ', re.sub(r'[^a-z0-9 ]+', ' ', s)))


def same_institution(a, b):
    """Same name, or one distinctive core (>= 4 letters) contained in the other. Used only to
    KEEP works, so a loose match errs on the safe side."""
    if norm_institution(a) == norm_institution(b):
        return True
    x, y = core_name(a), core_name(b)
    return len(x) >= 4 and len(y) >= 4 and (x in y or y in x)
WHEREABOUTS = {'doctoral', 'faculty'}


def career_conflict(works, career, subject=None, inst_meta=None, min_anchors=MIN_ANCHORS):
    """A contradicting affirmation from the career: while the researcher is known to be at an
    institution (a doctoral or faculty segment), a published work whose authorship names only
    OTHER universities or hospitals is a namesake's (e.g. a physicist's PhD years at one
    university and a food-science paper from another university under the same name).
    works: [{'id', 'year', 'institutions': [names], 'institution_ids': [I…], 'coauthors', 'subfield'}]
    career: [{'stage', 'institution', 'start_year', 'end_year'}] (public career segments)
    inst_meta: {I…: {'type', 'lineage': [I…]}} from OpenAlex institutions.
    A work is dropped ('career_conflict') when ALL hold:
      * the researcher has >= min_anchors works whose authorship names a career institution;
      * its authorship lists institutions, none of them a career institution or in the same
        OpenAlex lineage as an institution of the anchored works (Stanford Medicine ~ Stanford
        University), and all of them are universities or hospitals (research institutes such as
        IBS or Inserm host students and faculty, so they never contradict);
      * its year lies inside a doctoral or faculty segment and is not one of the years that can
        carry the previous or next institution: any segment's first two years (publication lag) and
        last year, and the year before a faculty segment ends;
      * in a doctoral (not faculty) period, its subfield is also absent from the anchored works
        (doctoral years are estimated and doctoral institution names are often abbreviated);
      * it shares no coauthor ID with the anchored works, or exactly one while its subfield is
        absent from them (two shared coauthors mean a real collaboration or a visit)."""
    meta = inst_meta or {}
    names = {norm_institution(c['institution']) for c in career if c.get('institution')} - {''}
    anchors = [w for w in works if {norm_institution(i) for i in w.get('institutions') or []} & names]
    if len(anchors) < min_anchors:
        return {}
    family = set()
    for w in anchors:
        for iid, name in zip(w.get('institution_ids') or [], w.get('institutions') or []):
            if iid and norm_institution(name) in names:
                family |= {iid, *(meta.get(iid, {}).get('lineage') or [])}
    segs = [(c.get('start_year'), c.get('end_year'), c.get('stage')) for c in career
            if c.get('stage') in WHEREABOUTS and c.get('start_year')]
    # years that can carry the previous or next institution: a segment's first two years (work done
    # before arriving is published after it; an estimated doctoral start may still be a master's
    # elsewhere) and its last year, plus the year before a faculty move
    bounds = set()
    for c in career:
        s0, e0 = c.get('start_year'), c.get('end_year')
        if s0:
            bounds |= {s0, s0 + 1}
        if e0:
            bounds |= {e0} | ({e0 - 1} if c.get('stage') == 'faculty' else set())
    aco = {c for w in anchors for c in w.get('coauthors') or [] if c}
    asub = {w.get('subfield') for w in anchors if w.get('subfield')}
    out = {}
    for w in works:
        insts = [norm_institution(i) for i in w.get('institutions') or []]
        iids = [i for i in w.get('institution_ids') or [] if i]
        y = w.get('year') or 0
        if not insts or set(insts) & names or not iids:
            continue
        if any(same_institution(i, c['institution']) for i in w.get('institutions') or [] for c in career if c.get('institution')):
            continue
        if any(i in family or set(meta.get(i, {}).get('lineage') or []) & family for i in iids):
            continue
        if not all(meta.get(i, {}).get('type') in CONFLICT_TYPES for i in iids):
            continue
        stages = {st for s, e, st in segs if s <= y <= (e or 9999)}
        if not stages or y in bounds:
            continue
        # doctoral years are estimated and doctoral institution names are often abbreviated, so a
        # doctoral-period conflict also needs a subfield the anchored works never show
        if 'faculty' not in stages and w.get('subfield') in asub:
            continue
        shared = len({c for c in w.get('coauthors') or [] if c} & aco)
        if shared == 0 or (shared == 1 and w.get('subfield') not in asub):
            out[w['id']] = 'career_conflict'
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
