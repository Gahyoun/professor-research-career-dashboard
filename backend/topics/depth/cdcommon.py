"""Shared pieces of citation_layers.py (collector) and depth_sweep.py (analysis).

Work ids are stored as integers: W2059161157 -> 2059161157. The main DB may hold short
ids ("W…") or full URLs; both normalise to the same integer, and the compatibility view
`work_references` re-emits the prefix the main DB uses.

Store tables (written by citation_layers.py; never mixed between channels):

  cd_refs(src, dst)        src cites dst. Backward channel: lists of referenced_works.
  cd_citers(dst, src)      src cites dst, kept only inside the forward window.
  cd_meta(work, year, n_refs, cited_by)
  cd_log(work, channel, layer, status, n, upto_year, at)   layer = fetch layer = distance + 1
                           one row per node whose neighbours were fetched in a channel.
                           status 'ok' (n may be 0) or 'missing' (not returned: merged or
                           withdrawn). A failed batch writes nothing and is retried.
  cd_runs                  one row per fetch run, for provenance.
"""
import re
import sqlite3
from pathlib import Path

WID = re.compile(r"W(\d+)\s*$", re.I)

DEFAULT_WORKS_SQL = (
    "SELECT DISTINCT work_id, publication_year FROM work_authorship_evidence "
    "WHERE identity_decision != 'namesake_paper' AND publication_year IS NOT NULL")
DEFAULT_LINKS_SQL = (
    "SELECT professor_uid, work_id, publication_year FROM work_authorship_evidence "
    "WHERE identity_decision != 'namesake_paper' AND publication_year IS NOT NULL")

SCHEMA = """
CREATE TABLE IF NOT EXISTS cd_refs (
  src INTEGER NOT NULL, dst INTEGER NOT NULL, PRIMARY KEY (src, dst)) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS cd_citers (
  dst INTEGER NOT NULL, src INTEGER NOT NULL, PRIMARY KEY (dst, src)) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS cd_meta (
  work INTEGER PRIMARY KEY, year INTEGER, n_refs INTEGER, cited_by INTEGER);
CREATE TABLE IF NOT EXISTS cd_log (
  work INTEGER NOT NULL, channel TEXT NOT NULL, layer INTEGER NOT NULL,
  status TEXT NOT NULL, n INTEGER, upto_year INTEGER, at TEXT,
  PRIMARY KEY (work, channel)) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS cd_runs (
  run_id INTEGER PRIMARY KEY AUTOINCREMENT, channel TEXT, layer INTEGER,
  started TEXT, finished TEXT, batches_ok INTEGER, batches_failed INTEGER,
  calls INTEGER, nodes_ok INTEGER, nodes_missing INTEGER, note TEXT);
"""


def wid(value):
    """'W123', 'https://openalex.org/W123', 123 -> 123; anything else -> None."""
    if value is None:
        return None
    if isinstance(value, int):
        return value
    m = WID.search(str(value).strip())
    return int(m.group(1)) if m else None


def wtext(n):
    return f"W{n}"


def connect(path, readonly=False):
    if readonly:
        con = sqlite3.connect(f"file:{Path(path).resolve()}?mode=ro", uri=True)
    else:
        con = sqlite3.connect(str(path))
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("PRAGMA synchronous=NORMAL")
    con.execute("PRAGMA temp_store=MEMORY")
    return con


def id_prefix(db):
    """Text before 'W…' in the main DB's work ids ('' or 'https://openalex.org/')."""
    try:
        row = db.execute("SELECT work_id FROM work_authorship_evidence "
                         "WHERE work_id IS NOT NULL LIMIT 1").fetchone()
    except sqlite3.Error:
        return ""
    if not row:
        return ""
    m = WID.search(str(row[0]).strip())
    return str(row[0]).strip()[:m.start()] if m else ""


def open_store(store_path, prefix=""):
    """Create the store tables, and the T1-compatible `work_references` view unless a table
    or view of that name already exists (then it is left alone and a note is returned)."""
    con = connect(store_path)
    con.executescript(SCHEMA)
    note = None
    hit = con.execute("SELECT type FROM sqlite_master WHERE name='work_references'").fetchone()
    if hit is None:
        p = prefix.replace("'", "''")
        con.execute(f"CREATE VIEW work_references AS SELECT '{p}W' || src AS work_id, "
                    f"'{p}W' || dst AS referenced_work_id FROM cd_refs")
        con.commit()
    elif hit[0] != "view":
        note = ("a table named work_references already exists; the cd_refs view was not "
                "created (read cd_refs directly)")
    return con, note


def load_focal(db, sql):
    """Run the works SELECT (work_id, publication_year) -> ({int id: year}, report)."""
    focal, bad, conflicts = {}, 0, 0
    for row in db.execute(sql):
        w = wid(row[0])
        if w is None:
            bad += 1
            continue
        y = int(row[1]) if len(row) > 1 and row[1] is not None else None
        if w in focal and focal[w] != y:
            conflicts += 1
            y = min(v for v in (focal[w], y) if v is not None) if (focal[w] or y) else None
        focal[w] = y
    return focal, {"focal_works": len(focal), "unparseable_ids": bad, "year_conflicts": conflicts}


def identity_report(db):
    """Distribution of identity_decision, including NULL. `x != 'namesake_paper'` is NULL for
    NULL rows, so the default SELECT silently drops them; this makes the count visible."""
    try:
        rows = db.execute("SELECT identity_decision, COUNT(*) FROM work_authorship_evidence "
                          "GROUP BY 1 ORDER BY 2 DESC").fetchall()
    except sqlite3.Error:
        return None
    return {("NULL" if k is None else str(k)): n for k, n in rows}
