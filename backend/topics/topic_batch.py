#!/usr/bin/env python3
"""All-researcher topic pipeline: private bibliography → community topics → topic DB → public index.

Runs where the private source DB lives (never in CI). Every step is resumable and only
redoes what changed, so the whole population can be rebuilt after a yearly release:

  python3 backend/topics/topic_batch.py all --year 2026          # every step below in order

  python3 backend/topics/topic_batch.py works      # 1. retained works per researcher (KOAD namesake drop)
  python3 backend/topics/topic_batch.py fetch      # 2. OpenAlex references/abstracts → backend/cache/YEAR/topic_works.sqlite
  python3 backend/topics/topic_batch.py cluster    # 3. coupling Louvain per researcher → topics DB
  python3 backend/topics/topic_batch.py summarize  # 4. Claude summaries (Message Batches) → topics DB
  python3 backend/topics/topic_batch.py export     # 5. public/data/topics (index + per-researcher shards)

Works follow the public release's identity rules exactly as build_research_areas.py does:
source decision ``keep``, every KOAD ``namesake_paper`` excluded, phd_year−5 ≤ year ≤ release
year, all author positions. Topics are communities of the bibliographic-coupling graph
(pipeline/scripts/topics.py); communities smaller than ``--min-size`` are pooled into one
"Other" topic per researcher. Topic names/keywords are English c-TF-IDF terms; each named
topic also gets an English and a Korean summary from Claude, written from representative
titles/abstracts only (no names, IDs or institutions are sent) and rejected when it repeats
five or more consecutive words of any paper title (titles stay behind the unlock).

Private outputs: the topics DB (default .private/topics_YEAR.sqlite) holds professor UIDs,
work IDs and summaries; the OpenAlex cache holds titles. Neither is committed.
Environment: OPENALEX_API_KEY (optional, raises OpenAlex limits), ANTHROPIC_API_KEY (or an
``ant auth login`` profile) for ``summarize``, NAMES_PASSWORD for encrypted title shards.
"""
import argparse
import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import shutil
import sqlite3
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timezone
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / "pipeline" / "scripts"))
from branching import parent_links  # noqa: E402
from export_public_index import ITERATIONS, text_of  # noqa: E402
from info_flow import analyse, stable_seed  # noqa: E402
from topic_semantics import build_lsa, ctfidf_terms, english_label, load_glossary, quantize, semantic_block  # noqa: E402
from topics import cluster  # noqa: E402

SCHEMA = "kstem-topic-alluvial/2"
TITLE_AAD = b"topic-titles-v2"
OPENALEX = "https://api.openalex.org"
SELECT = ("id,doi,title,publication_year,cited_by_count,referenced_works,primary_location,"
          "topics,keywords,abstract_inverted_index,type")
STAGE_KO = {"doctoral": "박사과정", "postdoc": "박사후", "faculty": "교원"}
DEFAULT_MODEL = "claude-opus-5-5"
SUMMARY_SCHEMA = {
    "type": "object",
    "properties": {"summary_en": {"type": "string"}, "summary_ko": {"type": "string"}},
    "required": ["summary_en", "summary_ko"],
    "additionalProperties": False,
}
SUMMARY_SYSTEM = """You describe the research theme of one cluster of papers written by a single researcher. \
The cluster was found from shared references, so its papers address a common problem.

Return two summaries of the same content:
- summary_en: one or two sentences in English, at most 45 words.
- summary_ko: the same content in natural Korean, at most 120 characters, using standard Korean \
scientific terms; add an English term in parentheses only when no common Korean term exists.

Describe the shared research problem, the objects or systems studied and the main approach. \
Do not quote or closely paraphrase any paper title. Do not mention people, institutions, \
countries, journals, years, paper counts or citation numbers. If the papers are heterogeneous, \
state what links them instead of listing them."""

DDL = """
CREATE TABLE IF NOT EXISTS researcher_works(
  professor_uid TEXT NOT NULL, anon_id TEXT NOT NULL, work_id TEXT NOT NULL, publication_year INTEGER,
  PRIMARY KEY(professor_uid, work_id));
CREATE INDEX IF NOT EXISTS researcher_works_anon ON researcher_works(anon_id);
CREATE TABLE IF NOT EXISTS researcher_runs(
  anon_id TEXT PRIMARY KEY, professor_uid TEXT NOT NULL, input_hash TEXT NOT NULL, clustered_at TEXT NOT NULL,
  source_works INTEGER NOT NULL, kept_works INTEGER NOT NULL, n_topics INTEGER NOT NULL,
  eras TEXT NOT NULL, info TEXT);
CREATE TABLE IF NOT EXISTS topics(
  anon_id TEXT NOT NULL, topic_id INTEGER NOT NULL, label TEXT NOT NULL, keywords TEXT NOT NULL,
  size INTEGER NOT NULL, birth_year INTEGER, parent TEXT, is_misc INTEGER NOT NULL, members_hash TEXT NOT NULL,
  PRIMARY KEY(anon_id, topic_id));
CREATE INDEX IF NOT EXISTS topics_hash ON topics(members_hash);
CREATE TABLE IF NOT EXISTS topic_members(
  anon_id TEXT NOT NULL, topic_id INTEGER NOT NULL, work_id TEXT NOT NULL, year INTEGER NOT NULL,
  era INTEGER, cited INTEGER NOT NULL, PRIMARY KEY(anon_id, work_id));
CREATE TABLE IF NOT EXISTS summaries(
  members_hash TEXT PRIMARY KEY, status TEXT NOT NULL, summary_en TEXT, summary_ko TEXT,
  model TEXT, detail TEXT, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS summary_batches(
  batch_id TEXT PRIMARY KEY, created_at TEXT NOT NULL, n_requests INTEGER NOT NULL, model TEXT NOT NULL,
  collected INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS summary_requests(
  custom_id TEXT PRIMARY KEY, members_hash TEXT NOT NULL, batch_id TEXT NOT NULL);
"""


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def short_id(value):
    return str(value or "").rstrip("/").rsplit("/", 1)[-1]


def anon_id(salt, uid):
    digest = hmac.new(salt, uid.encode(), hashlib.sha256).digest()
    return "P-" + base64.b32encode(digest).decode().rstrip("=")[:10]


def digest(*parts):
    return hashlib.sha256(json.dumps(parts, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


class Paths:
    def __init__(self, a):
        self.year = int(a.year)
        self.root = Path(a.project_root)
        cache = self.root / "backend" / "cache" / str(self.year)
        self.source_db = Path(a.source_db) if a.source_db else (
            Path((cache / "source_db_path.txt").read_text().strip()) if (cache / "source_db_path.txt").exists() else None)
        self.anon_salt = Path(a.anon_salt) if a.anon_salt else self.root / ".private" / "anon_salt.bin"
        self.topics_db = Path(a.topics_db) if a.topics_db else self.root / ".private" / f"topics_{self.year}.sqlite"
        self.cache_db = Path(a.cache_db) if a.cache_db else cache / "topic_works.sqlite"
        self.dashboard = Path(a.dashboard) if a.dashboard else self.root / "public" / "data" / "dashboard.json"
        self.out_dir = Path(a.out_dir) if a.out_dir else self.root / "public" / "data" / "topics"


def open_topics(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    con.executescript(DDL)
    return con


def open_cache(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    con.executescript("""
      CREATE TABLE IF NOT EXISTS works(work_id TEXT PRIMARY KEY, json TEXT NOT NULL, fetched_at TEXT NOT NULL);
      CREATE TABLE IF NOT EXISTS missing(work_id TEXT PRIMARY KEY, checked_at TEXT NOT NULL);
    """)
    return con


def load_dashboard(path):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return data, {p["id"]: p for p in data["professors"]}


# 1. works ------------------------------------------------------------------------------------

def retained_works(source_db, year):
    """(professor_uid, work_id, publication_year) under the public identity rules."""
    source_db = Path(source_db)
    con = sqlite3.connect(f"file:{source_db.resolve()}?mode=ro&immutable=1", uri=True)
    decisions = source_db.parent / "identity_decisions.sqlite"
    if not decisions.exists():
        raise SystemExit(f"KOAD decision database is required: {decisions}")
    con.execute("ATTACH DATABASE ? AS koad", (f"file:{decisions.resolve()}?mode=ro&immutable=1",))
    rows = con.execute("""
      SELECT w.professor_uid, w.work_id, w.publication_year
      FROM work_authorship_evidence w JOIN professors p USING(professor_uid)
      WHERE w.identity_decision='keep' AND w.publication_year<=?
        AND (p.phd_year IS NULL OR w.publication_year>=p.phd_year-5)
        AND NOT EXISTS (SELECT 1 FROM koad.work_decision kd
          WHERE kd.professor_uid=w.professor_uid AND kd.work_id=w.work_id AND kd.decision='namesake_paper')
    """, (int(year),)).fetchall()
    con.close()
    return rows


def step_works(paths, rows=None):
    if rows is None:
        if not paths.source_db:
            raise SystemExit("--source-db is required (or backend/cache/YEAR/source_db_path.txt)")
        rows = retained_works(paths.source_db, paths.year)
    salt = paths.anon_salt.read_bytes()
    _, public = load_dashboard(paths.dashboard)
    ids, out = {}, []
    for uid, work_id, year in rows:
        if uid not in ids:
            pid = anon_id(salt, uid)
            ids[uid] = pid if pid in public else None
        if ids[uid] and work_id:
            out.append((uid, ids[uid], short_id(work_id), year))
    con = open_topics(paths.topics_db)
    with con:
        con.execute("DELETE FROM researcher_works")
        con.executemany("INSERT OR IGNORE INTO researcher_works VALUES (?,?,?,?)", out)
    n = con.execute("SELECT COUNT(*), COUNT(DISTINCT anon_id), COUNT(DISTINCT work_id) FROM researcher_works").fetchone()
    con.close()
    print(f"works: {n[0]:,} researcher–work rows, {n[1]:,} researchers of {len(public):,}, {n[2]:,} unique works")


# 2. fetch ------------------------------------------------------------------------------------

def http_json(url, tries=8):
    req = urllib.request.Request(url, headers={"User-Agent": "kstem-research-atlas-topics/1.0"})
    for attempt in range(1, tries + 1):
        try:
            with urllib.request.urlopen(req, timeout=120) as res:
                return json.load(res)
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            if e.code != 429 and e.code < 500:
                raise
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            pass
        time.sleep(min(120, 2 * attempt * attempt))
    raise RuntimeError(f"OpenAlex failed after {tries} attempts: {url.split('api_key=')[0]}")


def openalex_url(path, params):
    key = os.environ.get("OPENALEX_API_KEY")
    if key:
        params = {**params, "api_key": key}
    return f"{OPENALEX}{path}?{urllib.parse.urlencode(params)}"


def compact_work(w):
    source = ((w.get("primary_location") or {}).get("source") or {})
    return {"id": short_id(w.get("id")), "doi": w.get("doi"), "title": w.get("title") or "",
            "publication_year": w.get("publication_year"), "cited_by_count": w.get("cited_by_count") or 0,
            "referenced_works": [short_id(r) for r in w.get("referenced_works") or []],
            "venue": source.get("display_name"), "type": w.get("type"),
            "topics": [{"display_name": t.get("display_name")} for t in (w.get("topics") or [])[:3]],
            "keywords": [{"display_name": k.get("display_name")} for k in (w.get("keywords") or [])[:8]],
            "abstract_inverted_index": w.get("abstract_inverted_index")}


def fetch_group(ids):
    """One OR-filter request for ≤50 IDs; merged/redirected IDs are retried one by one."""
    data = http_json(openalex_url("/works", {"filter": "openalex_id:" + "|".join(ids), "per-page": 100, "select": SELECT}))
    found = {}
    for w in (data or {}).get("results", []):
        found[short_id(w.get("id"))] = compact_work(w)
    for wid in [i for i in ids if i not in found]:
        w = http_json(openalex_url(f"/works/{wid}", {"select": SELECT}))
        if w:
            found[wid] = {**compact_work(w), "id": wid, "canonical_id": short_id(w.get("id"))}
    return ids, found


def step_fetch(paths, fetcher=fetch_group, workers=4, group=50):
    con = open_topics(paths.topics_db)
    wanted = [r[0] for r in con.execute("SELECT DISTINCT work_id FROM researcher_works ORDER BY work_id")]
    con.close()
    cache = open_cache(paths.cache_db)
    have = {r[0] for r in cache.execute("SELECT work_id FROM works UNION SELECT work_id FROM missing")}
    todo = [w for w in wanted if w not in have]
    groups = [todo[i:i + group] for i in range(0, len(todo), group)]
    print(f"fetch: {len(wanted):,} works, {len(todo):,} not cached → {len(groups):,} requests")
    done = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for ids, found in pool.map(fetcher, groups):
            stamp = now()
            with cache:
                cache.executemany("INSERT OR REPLACE INTO works VALUES (?,?,?)",
                                  [(k, json.dumps(v, ensure_ascii=False, separators=(",", ":")), stamp) for k, v in found.items()])
                cache.executemany("INSERT OR REPLACE INTO missing VALUES (?,?)", [(i, stamp) for i in ids if i not in found])
            done += 1
            if done % 200 == 0 or done == len(groups):
                print(f"  {done:,}/{len(groups):,} requests")
    n_missing = cache.execute("SELECT COUNT(*) FROM missing").fetchone()[0]
    cache.close()
    print(f"fetch: done; {n_missing:,} work IDs not found in OpenAlex")


# 3. cluster ----------------------------------------------------------------------------------

def eras_for(professor, years):
    """Career segments (doctoral/postdoc/faculty) → era labels and a year → era-index function."""
    segs = sorted((c for c in professor.get("career") or [] if c.get("start_year")),
                  key=lambda c: (c["start_year"], c.get("end_year") or 9999))
    if not segs:
        lo, hi = min(years), max(years)
        return [{"label": f"전체 ({lo}-{hi})", "start": lo, "end": hi}], (lambda y: 0)
    eras = []
    for c in segs:
        s, e = c["start_year"], c.get("end_year")
        span = f"{s}-{e}" if e and e != s else (f"{s}-" if not e else f"{s}")
        eras.append({"label": f"{c.get('institution') or '기관 미상'} {STAGE_KO.get(c.get('stage'), '')} ({span})".replace("  ", " "),
                     "start": s, "end": e})
    starts = [e["start"] for e in eras]

    def era_of(year):
        idx = 0
        for i, s in enumerate(starts):
            if s <= year:
                idx = i
        return idx
    return eras, era_of


def researcher_topics(anon, professor, rows, records, opts):
    """rows: [(work_id, db_year)], records: {work_id: compact OpenAlex work}. → dict for the DB."""
    papers = []
    for wid, year in rows:
        rec = records.get(wid)
        y = year or (rec or {}).get("publication_year")
        if rec and y:
            papers.append({"id": wid, "year": int(y), "cited": int(rec.get("cited_by_count") or 0), "rec": rec})
    if not papers:
        return None
    refs = {p["id"]: set(p["rec"].get("referenced_works") or []) for p in papers}
    communities, _ = cluster(refs, opts.min_shared, opts.resolution, opts.seed)
    named = [c for c in communities if len(c) >= opts.min_size]
    pooled = set().union(*[c for c in communities if len(c) < opts.min_size]) if len(named) < len(communities) else set()
    assign = {w: k for k, c in enumerate(named) for w in c}
    misc_id = len(named) if pooled else None
    for w in pooled:
        assign[w] = misc_id
    eras, era_of = eras_for(professor, [p["year"] for p in papers])
    for p in papers:
        p["topic"], p["era"] = assign[p["id"]], era_of(p["year"])
    named_ids = list(range(len(named)))
    births, parents = parent_links([p for p in papers if p["topic"] != misc_id], refs, named_ids)
    texts = {p["id"]: text_of(p["rec"]) for p in papers}
    docs = defaultdict(list)
    for p in papers:
        docs[p["topic"]].append(texts[p["id"]])
    keywords = ctfidf_terms(dict(docs), n_terms=8)
    topics = []
    for k in named_ids + ([misc_id] if misc_id is not None else []):
        members = sorted(p["id"] for p in papers if p["topic"] == k)
        parent = parents.get(k)
        topics.append({
            "id": k, "label": english_label(keywords.get(k, []), curated="기타" if k == misc_id else None),
            "keywords": keywords.get(k, []), "size": len(members),
            "birth_year": min(p["year"] for p in papers if p["topic"] == k),
            "parent": {f: parent[f] for f in ("from", "sim", "from_year", "to_year")} if parent else None,
            "is_misc": k == misc_id, "members_hash": hashlib.sha256("|".join(members).encode()).hexdigest()[:24],
        })
    papers.sort(key=lambda p: (p["year"], p["id"]))
    info = analyse([p["year"] for p in papers], [p["topic"] for p in papers], [refs[p["id"]] for p in papers],
                   width=opts.window, n_null=opts.null, n_boot=opts.null, seed=stable_seed(anon)) if opts.null >= 0 else None
    return {"eras": eras, "topics": topics, "papers": papers, "info": info}


def cluster_params(opts):
    return {k: getattr(opts, k) for k in ("min_shared", "resolution", "seed", "min_size", "window", "null")}


def step_cluster(paths, opts):
    _, public = load_dashboard(paths.dashboard)
    con = open_topics(paths.topics_db)
    cache = open_cache(paths.cache_db)
    by_anon = defaultdict(list)
    uid_of = {}
    for uid, anon, wid, year in con.execute("SELECT professor_uid, anon_id, work_id, publication_year FROM researcher_works"):
        by_anon[anon].append((wid, year))
        uid_of[anon] = uid
    done = {r[0]: r[1] for r in con.execute("SELECT anon_id, input_hash FROM researcher_runs")}
    params = cluster_params(opts)
    changed = skipped = 0
    started = time.time()
    for n, anon in enumerate(sorted(by_anon), 1):
        rows = sorted(set(by_anon[anon]))
        ids = [w for w, _ in rows]
        records = {}
        for i in range(0, len(ids), 500):
            chunk = ids[i:i + 500]
            q = f"SELECT work_id, json FROM works WHERE work_id IN ({','.join('?' * len(chunk))})"
            records.update({w: json.loads(j) for w, j in cache.execute(q, chunk)})
        input_hash = digest(params, rows, sorted(records), public[anon].get("career"))
        if done.get(anon) == input_hash and not opts.force:
            skipped += 1
            continue
        result = researcher_topics(anon, public[anon], rows, records, opts)
        with con:
            con.execute("DELETE FROM topics WHERE anon_id=?", (anon,))
            con.execute("DELETE FROM topic_members WHERE anon_id=?", (anon,))
            con.execute("DELETE FROM researcher_runs WHERE anon_id=?", (anon,))
            if result:
                con.executemany("INSERT INTO topics VALUES (?,?,?,?,?,?,?,?,?)", [
                    (anon, t["id"], t["label"], json.dumps(t["keywords"]), t["size"], t["birth_year"],
                     json.dumps(t["parent"]) if t["parent"] else None, int(t["is_misc"]), t["members_hash"])
                    for t in result["topics"]])
                con.executemany("INSERT INTO topic_members VALUES (?,?,?,?,?,?)", [
                    (anon, p["topic"], p["id"], p["year"], p["era"], p["cited"]) for p in result["papers"]])
            con.execute("INSERT INTO researcher_runs VALUES (?,?,?,?,?,?,?,?,?)", (
                anon, uid_of[anon], input_hash, now(), len(rows), len(result["papers"]) if result else 0,
                len(result["topics"]) if result else 0, json.dumps(result["eras"] if result else [], ensure_ascii=False),
                json.dumps(result["info"], separators=(",", ":")) if result and result["info"] else None))
        changed += 1
        if n % 100 == 0:
            print(f"  {n:,}/{len(by_anon):,} researchers ({time.time() - started:.0f}s)")
    stale = [a for a in done if a not in by_anon]
    with con:
        for anon in stale:
            for table in ("topics", "topic_members", "researcher_runs"):
                con.execute(f"DELETE FROM {table} WHERE anon_id=?", (anon,))
    totals = con.execute("SELECT COUNT(*), SUM(is_misc=0) FROM topics").fetchone()
    con.close()
    cache.close()
    print(f"cluster: {changed:,} researchers (re)clustered, {skipped:,} unchanged, {len(stale):,} removed; "
          f"{totals[0] or 0:,} topics ({totals[1] or 0:,} named)")


# 4. summarize --------------------------------------------------------------------------------

def tokens(text):
    return re.findall(r"[0-9a-z가-힣]+", (text or "").lower())


def repeats_title(summary, titles, n=5):
    """True when the summary contains n consecutive words of any title (de-anonymisation guard)."""
    words = tokens(summary)
    grams = {tuple(words[i:i + n]) for i in range(len(words) - n + 1)}
    for title in titles:
        t = tokens(title)
        if any(tuple(t[i:i + n]) in grams for i in range(len(t) - n + 1)):
            return True
    return False


def exemplars(recs, n=10):
    """Members closest to the topic's TF-IDF centroid (same idea as label_topics.exemplars)."""
    from sklearn.feature_extraction.text import TfidfVectorizer
    texts = [text_of(r) for r in recs]
    try:
        M = TfidfVectorizer(stop_words="english", token_pattern=r"[a-zA-Z][a-zA-Z-]{2,}").fit_transform(texts).toarray()
    except ValueError:
        return sorted(recs, key=lambda r: -(r.get("cited_by_count") or 0))[:n]
    M = M / (np.linalg.norm(M, axis=1, keepdims=True) + 1e-9)
    c = M.mean(axis=0)
    c = c / (np.linalg.norm(c) + 1e-9)
    order = np.argsort(-(M @ c))
    return [recs[i] for i in order[:n]]


def abstract(rec, words=70):
    inv = rec.get("abstract_inverted_index") or {}
    if not inv:
        return ""
    pos = sorted((p, w) for w, ps in inv.items() for p in ps)
    text = " ".join(w for _, w in pos[:words])
    return text + (" …" if len(pos) > words else "")


def summary_prompt(keywords, recs):
    lines = [f"Distinctive terms (c-TF-IDF): {', '.join(keywords) or '—'}", f"Papers in cluster: {len(recs)}",
             "Representative papers (title — abstract excerpt):"]
    for i, r in enumerate(exemplars(recs), 1):
        excerpt = abstract(r)
        lines.append(f"{i}. {r.get('title') or '(untitled)'}" + (f" — {excerpt}" if excerpt else ""))
    return "\n".join(lines)


def topic_records(con, cache, anon, topic_id):
    ids = [r[0] for r in con.execute("SELECT work_id FROM topic_members WHERE anon_id=? AND topic_id=?", (anon, topic_id))]
    q = f"SELECT json FROM works WHERE work_id IN ({','.join('?' * len(ids))})"
    return [json.loads(j) for (j,) in cache.execute(q, ids)] if ids else []


def pending_summaries(con, retry_failed=False):
    """Named topics whose membership has no stored summary and no request in flight; one per hash."""
    statuses = ("ok",) if retry_failed else ("ok", "refused", "rejected_title_overlap", "invalid")
    rows = con.execute(f"""
      SELECT t.members_hash, MIN(t.anon_id), MIN(t.topic_id), MAX(t.keywords) FROM topics t
      WHERE t.is_misc=0
        AND t.members_hash NOT IN (SELECT members_hash FROM summaries WHERE status IN ({','.join('?' * len(statuses))}))
        AND t.members_hash NOT IN (SELECT r.members_hash FROM summary_requests r JOIN summary_batches b USING(batch_id) WHERE b.collected=0)
      GROUP BY t.members_hash ORDER BY MIN(t.anon_id), MIN(t.topic_id)""", statuses).fetchall()
    return rows


def build_request(custom_id, prompt, model):
    return {"custom_id": custom_id, "params": {
        "model": model, "max_tokens": 4096, "system": SUMMARY_SYSTEM,
        "output_config": {"effort": "low", "format": {"type": "json_schema", "schema": SUMMARY_SCHEMA}},
        "messages": [{"role": "user", "content": prompt}]}}


def anthropic_client():
    import anthropic
    return anthropic.Anthropic()


def submit_summaries(paths, opts, client=None):
    con = open_topics(paths.topics_db)
    cache = open_cache(paths.cache_db)
    pending = pending_summaries(con, opts.retry_failed)
    if opts.limit:
        pending = pending[:opts.limit]
    requests = []
    for members_hash, anon, topic_id, keywords in pending:
        recs = topic_records(con, cache, anon, topic_id)
        if recs:
            requests.append(build_request(f"t-{members_hash}", summary_prompt(json.loads(keywords), recs), opts.model))
    chars = sum(len(r["params"]["system"]) + len(r["params"]["messages"][0]["content"]) for r in requests)
    print(f"summarize: {len(requests):,} topics to summarize, ≈{chars / 4 / 1e6:.1f}M input tokens ({opts.model}, Batches API)")
    if opts.dry_run or not requests:
        con.close()
        cache.close()
        return []
    client = client or anthropic_client()
    batch_ids = []
    for i in range(0, len(requests), opts.batch_size):
        chunk = requests[i:i + opts.batch_size]
        batch = client.messages.batches.create(requests=chunk)
        with con:
            con.execute("INSERT INTO summary_batches VALUES (?,?,?,?,0)", (batch.id, now(), len(chunk), opts.model))
            con.executemany("INSERT OR REPLACE INTO summary_requests VALUES (?,?,?)",
                            [(r["custom_id"], r["custom_id"][2:], batch.id) for r in chunk])
        batch_ids.append(batch.id)
        print(f"  submitted {batch.id}: {len(chunk):,} requests")
    con.close()
    cache.close()
    return batch_ids


def message_json(message):
    text = next((b.text for b in message.content if getattr(b, "type", None) == "text"), "")
    data = json.loads(text)
    en, ko = (data.get("summary_en") or "").strip(), (data.get("summary_ko") or "").strip()
    if not en or not ko:
        raise ValueError("empty summary")
    return en, ko


def collect_summaries(paths, opts, client=None, wait=True, poll=60):
    con = open_topics(paths.topics_db)
    cache = open_cache(paths.cache_db)
    open_batches = [r[0] for r in con.execute("SELECT batch_id FROM summary_batches WHERE collected=0 ORDER BY created_at")]
    if not open_batches:
        con.close()
        cache.close()
        print("summarize: no batches in flight")
        return
    client = client or anthropic_client()
    counts = Counter()
    for batch_id in open_batches:
        while True:
            batch = client.messages.batches.retrieve(batch_id)
            if batch.processing_status == "ended":
                break
            if not wait:
                print(f"  {batch_id}: {batch.processing_status}")
                break
            print(f"  {batch_id}: {batch.processing_status} — waiting {poll}s")
            time.sleep(poll)
        if batch.processing_status != "ended":
            continue
        model = con.execute("SELECT model FROM summary_batches WHERE batch_id=?", (batch_id,)).fetchone()[0]
        rows = []
        for result in client.messages.batches.results(batch_id):
            members_hash = result.custom_id[2:]
            kind = result.result.type
            if kind != "succeeded":
                counts[kind] += 1  # errored / canceled / expired: left pending, resubmitted next run
                continue
            message = result.result.message
            if message.stop_reason == "refusal":
                rows.append((members_hash, "refused", None, None, model, None, now()))
                counts["refused"] += 1
                continue
            try:
                en, ko = message_json(message)
            except (ValueError, json.JSONDecodeError) as e:
                rows.append((members_hash, "invalid", None, None, model, str(e)[:200], now()))
                counts["invalid"] += 1
                continue
            topic = con.execute("SELECT anon_id, topic_id FROM topics WHERE members_hash=? LIMIT 1", (members_hash,)).fetchone()
            titles = [r.get("title") or "" for r in topic_records(con, cache, *topic)] if topic else []
            if repeats_title(en, titles) or repeats_title(ko, titles):
                rows.append((members_hash, "rejected_title_overlap", None, None, model, en[:300], now()))
                counts["rejected_title_overlap"] += 1
                continue
            rows.append((members_hash, "ok", en, ko, model, None, now()))
            counts["ok"] += 1
        with con:
            con.executemany("INSERT OR REPLACE INTO summaries VALUES (?,?,?,?,?,?,?)", rows)
            con.execute("UPDATE summary_batches SET collected=1 WHERE batch_id=?", (batch_id,))
    con.close()
    cache.close()
    print("summarize: collected " + ", ".join(f"{k} {v:,}" for k, v in sorted(counts.items())))


def step_summarize(paths, opts, client=None):
    submit_summaries(paths, opts, client)
    if not opts.dry_run:
        collect_summaries(paths, opts, client, wait=not opts.no_wait, poll=opts.poll)


# 5. export -----------------------------------------------------------------------------------

def vector_b64(vec):
    return base64.b64encode(np.asarray(vec, dtype=np.int8).tobytes()).decode()


def encrypt_with(key, payload):
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    nonce = secrets.token_bytes(12)
    ct = AESGCM(key).encrypt(nonce, json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode(), TITLE_AAD)
    return {"nonce": base64.b64encode(nonce).decode(), "ciphertext": base64.b64encode(ct).decode()}


def doi_url(doi):
    doi = (doi or "").strip()
    if not doi:
        return None
    return doi if doi.startswith("https://doi.org/") else "https://doi.org/" + re.sub(r"^(https?://(dx\.)?doi\.org/|doi:)", "", doi, flags=re.I)


def step_export(paths, opts):
    dashboard, public = load_dashboard(paths.dashboard)
    con = open_topics(paths.topics_db)
    cache = open_cache(paths.cache_db)
    runs = {r[0]: r for r in con.execute(
        "SELECT anon_id, clustered_at, source_works, kept_works, eras, info FROM researcher_runs WHERE kept_works>0 ORDER BY anon_id")}
    summaries = {h: (en, ko) for h, en, ko in con.execute("SELECT members_hash, summary_en, summary_ko FROM summaries WHERE status='ok'")}
    topic_rows = defaultdict(list)
    for row in con.execute("SELECT anon_id, topic_id, label, keywords, size, birth_year, parent, is_misc, members_hash FROM topics ORDER BY anon_id, topic_id"):
        topic_rows[row[0]].append(row)
    members = defaultdict(list)
    for row in con.execute("SELECT anon_id, topic_id, work_id, year, era, cited FROM topic_members ORDER BY anon_id, year, work_id"):
        members[row[0]].append(row)

    # One LSA space over every clustered paper: topic vectors become comparable across researchers.
    texts, owners, records = [], [], {}
    for anon in runs:
        ids = [m[2] for m in members[anon]]
        for i in range(0, len(ids), 500):
            chunk = ids[i:i + 500]
            q = f"SELECT work_id, json FROM works WHERE work_id IN ({','.join('?' * len(chunk))})"
            records.update({w: json.loads(j) for w, j in cache.execute(q, chunk)})
        for m in members[anon]:
            texts.append(text_of(records.get(m[2], {})))
            owners.append((anon, m[1]))
    if not texts:
        raise SystemExit("export: no clustered researchers — run works/fetch/cluster first")
    vocab, term_vecs, doc_vecs = build_lsa(texts, dims=opts.dims)
    centroid = defaultdict(list)
    for row, key in enumerate(owners):
        centroid[key].append(row)

    out = paths.out_dir
    out.mkdir(parents=True, exist_ok=True)
    for sub in ("detail", "titles"):
        shutil.rmtree(out / sub, ignore_errors=True)
        (out / sub).mkdir()
    legacy = out / "encrypted_titles.json"
    if legacy.exists():
        legacy.unlink()
    password = os.environ.get(opts.password_env)
    key = None
    if password:
        salt = secrets.token_bytes(16)
        key = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, ITERATIONS, 32)
        (out / "titles" / "key.json").write_text(json.dumps({
            "version": 2, "kdf": "PBKDF2-SHA256", "iterations": ITERATIONS,
            "salt": base64.b64encode(salt).decode(), "aad": base64.b64encode(TITLE_AAD).decode()}))

    researchers, n_papers, n_summaries = [], 0, 0
    for anon, (_, clustered_at, source_works, kept_works, eras_json, info_json) in runs.items():
        prof = public.get(anon)
        if not prof:
            continue
        topics_out, summary_out = [], {}
        for _, tid, label, kw, size, birth, parent, is_misc, mhash in topic_rows[anon]:
            rows = centroid.get((anon, tid), [])
            vec = None
            if rows:
                c = doc_vecs[rows].mean(axis=0)
                vec = vector_b64(quantize((c / (np.linalg.norm(c) + 1e-12))[None, :])[0])
            topics_out.append({"id": tid, "label": label, "size": size, "birth_year": birth,
                               "parent": json.loads(parent) if parent else None, "keywords": json.loads(kw),
                               "misc": bool(is_misc), "vector_b64": vec})
            if mhash in summaries:
                summary_out[str(tid)] = {"en": summaries[mhash][0], "ko": summaries[mhash][1]}
        cells = defaultdict(lambda: [0, 0])
        for _, tid, _, year, era, cited in members[anon]:
            cells[(year, tid, era)][0] += 1
            cells[(year, tid, era)][1] += cited
        n_papers += len(members[anon])
        n_summaries += len(summary_out)
        researchers.append({
            "id": anon, "alias": None, "subject": prof["subject"], "institution": prof.get("current_institution"),
            "eras": json.loads(eras_json), "topics": topics_out,
            "paper_cells": [[y, t, e, n, c] for (y, t, e), (n, c) in sorted(cells.items(), key=lambda kv: (kv[0][0], kv[0][1]))],
            "recip": [], "counts": {"source_works": source_works, "kept_works": kept_works, "merged_versions": None},
            "fetched_at": clustered_at[:10], "detail": f"detail/{anon}.json"})
        (out / "detail" / f"{anon}.json").write_text(json.dumps(
            {"id": anon, "info": json.loads(info_json) if info_json else None, "summaries": summary_out},
            ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        if key:
            titles = [{"year": year, "topic": tid, "title": records.get(wid, {}).get("title") or "",
                       "venue": records.get(wid, {}).get("venue"), "doi": doi_url(records.get(wid, {}).get("doi"))}
                      for _, tid, wid, year, _, _ in members[anon]]
            (out / "titles" / f"{anon}.json").write_text(json.dumps(encrypt_with(key, titles)))

    _, ko2en = load_glossary()
    model = con.execute("SELECT model FROM summaries WHERE status='ok' GROUP BY model ORDER BY COUNT(*) DESC LIMIT 1").fetchone()
    index = {
        "schema": SCHEMA, "source": "release", "generated_at": str(date.today()),
        "method": {"disambiguation": dashboard["meta"].get("identity_filter_version", "KOAD"),
                   "works": "identity_decision=keep; KOAD namesake_paper excluded; phd_year-5 ≤ year ≤ release year; all author positions",
                   "clustering": f"공유 참고문헌 코사인 가중 Louvain (공유 ≥{opts.min_shared}편, resolution {opts.resolution}); {opts.min_size}편 미만 군집은 '기타'로 묶음",
                   "labels": "c-TF-IDF top terms (English)",
                   "summaries": f"Claude ({model[0] if model else '—'}) — 대표 논문 제목·초록에서 생성, 제목 5단어 이상 반복 시 제외",
                   "branching": "탄생기 논문 × 이전 시기 논문의 bibliographic coupling 최댓값",
                   "recip": "not_computed"},
        "semantic": semantic_block(vocab, term_vecs, ko2en), "researchers": researchers}
    text = json.dumps(index, ensure_ascii=False, separators=(",", ":"))
    for forbidden in ('"title"', '"doi"', '"professor_uid"', '"work_id"'):
        if forbidden in text:
            raise SystemExit(f"export: refusing to publish — public index contains {forbidden}")
    (out / "index.json").write_text(text, encoding="utf-8")
    con.close()
    cache.close()
    print(f"export: {len(researchers):,} researchers, {n_papers:,} papers, {sum(len(r['topics']) for r in researchers):,} topics, "
          f"{n_summaries:,} summaries; index {len(text) / 1e6:.1f} MB; titles {'encrypted' if key else 'NOT written (set ' + opts.password_env + ')'}")


# CLI -----------------------------------------------------------------------------------------

def parser():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("step", choices=["works", "fetch", "cluster", "summarize", "collect", "export", "all"])
    p.add_argument("--year", default=os.environ.get("RELEASE_YEAR", "2026"))
    p.add_argument("--project-root", default=str(ROOT))
    p.add_argument("--source-db", help="private career DB (default: backend/cache/YEAR/source_db_path.txt)")
    p.add_argument("--anon-salt", help="default .private/anon_salt.bin (must be the release salt)")
    p.add_argument("--topics-db", help="default .private/topics_YEAR.sqlite")
    p.add_argument("--cache-db", help="default backend/cache/YEAR/topic_works.sqlite")
    p.add_argument("--dashboard", help="default public/data/dashboard.json")
    p.add_argument("--out-dir", help="default public/data/topics")
    p.add_argument("--workers", type=int, default=4, help="parallel OpenAlex requests")
    p.add_argument("--min-shared", type=int, default=2, help="shared references needed for a coupling edge")
    p.add_argument("--resolution", type=float, default=1.05)
    p.add_argument("--seed", type=int, default=4)
    p.add_argument("--min-size", type=int, default=3, help="smaller communities are pooled into one 'Other' topic")
    p.add_argument("--window", type=int, default=3, help="info-flow window width in years")
    p.add_argument("--null", type=int, default=200, help="info-flow permutations/bootstraps (-1 skips info flow)")
    p.add_argument("--force", action="store_true", help="recluster researchers whose input did not change")
    p.add_argument("--model", default=DEFAULT_MODEL)
    p.add_argument("--limit", type=int, default=0, help="summarize at most N topics (trial runs)")
    p.add_argument("--batch-size", type=int, default=10000)
    p.add_argument("--dry-run", action="store_true", help="count summary requests and tokens without calling Claude")
    p.add_argument("--no-wait", action="store_true", help="submit and return; run 'collect' later")
    p.add_argument("--retry-failed", action="store_true", help="resubmit refused/rejected/invalid summaries")
    p.add_argument("--poll", type=int, default=60)
    p.add_argument("--dims", type=int, default=48)
    p.add_argument("--password-env", default="NAMES_PASSWORD")
    return p


def main(argv=None):
    a = parser().parse_args(argv)
    paths = Paths(a)
    steps = ["works", "fetch", "cluster", "summarize", "export"] if a.step == "all" else [a.step]
    for step in steps:
        if step == "works":
            step_works(paths)
        elif step == "fetch":
            step_fetch(paths, workers=a.workers)
        elif step == "cluster":
            step_cluster(paths, a)
        elif step == "summarize":
            step_summarize(paths, a)
        elif step == "collect":
            collect_summaries(paths, a, wait=not a.no_wait, poll=a.poll)
        elif step == "export":
            step_export(paths, a)


if __name__ == "__main__":
    main()
