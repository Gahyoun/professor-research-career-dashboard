#!/usr/bin/env python3
"""Layered, resumable OpenAlex collector for the two citation channels.

  refs   backward: referenced_works. Layer k fetches the reference lists of every node at
         distance <= k-1 from the focal works, so depth-k neighbourhoods are complete.
         Layer 1 is task T1 of the handoff (references of the faculty's own works).
  cites  forward: citing works, inside a fixed window of W years after the FOCAL work's
         publication year (exposure control). Layer k fetches citers of every node within
         k-1 forward hops; a node reached from several focal works is fetched up to the
         latest of their deadlines. Focal works whose window is not yet closed
         (year + W > --last-complete-year) are not eligible.

The two channels go to separate tables (cd_refs, cd_citers) and are never mixed.

  python3 -I citation_layers.py plan   --db MAIN.sqlite --channel refs --layer 1
  python3 -I citation_layers.py fetch  --db MAIN.sqlite --channel refs --layer 1 --env-file .env
  python3 -I citation_layers.py status --db MAIN.sqlite --channel refs

--store puts the collected tables in a separate SQLite file (default: the main DB itself).
The API key is read from $OPENALEX_API_KEY or OPENALEX_API_KEY=… in --env-file and is never
printed. Interrupt at any time: each batch is committed atomically with its log rows, and a
rerun fetches only what is not logged.
"""
import argparse
import json
import math
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cdcommon import (DEFAULT_WORKS_SQL, connect, id_prefix, identity_report, load_focal,  # noqa: E402
                      open_store, wid, wtext)

API = "https://api.openalex.org"
SELECT = "id,publication_year,referenced_works,cited_by_count"
UA = {"User-Agent": "professor-career-dashboard/citation-layers"}
OPEN = []


def now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------- frontier
def stage_focal(store, focal):
    """Temp table focal(work, year); OpenAlex's own year (cd_meta) wins over the main DB's,
    so focal and citer years come from the same source."""
    store.execute("DROP TABLE IF EXISTS temp.focal")
    store.execute("CREATE TEMP TABLE focal (work INTEGER PRIMARY KEY, year INTEGER)")
    store.executemany("INSERT INTO focal VALUES (?, ?)", focal.items())
    store.execute("UPDATE focal SET year = (SELECT m.year FROM cd_meta m WHERE m.work = focal.work) "
                  "WHERE EXISTS (SELECT 1 FROM cd_meta m WHERE m.work = focal.work AND m.year IS NOT NULL)")


def build_reach(store, channel, hops, window, last_complete):
    """temp.reach(work, d, deadline): nodes within `hops` hops of the focal set.

    refs:  d = minimum distance; deadline NULL.
    cites: only eligible focal works; a citer joins if its year <= the deadline of the node it
           cites; deadline = max over the anchors that reach it within `hops` hops. Each round
           reads a snapshot (prev) so a round adds exactly one hop.
    """
    store.execute("DROP TABLE IF EXISTS temp.reach")
    store.execute("CREATE TEMP TABLE reach (work INTEGER PRIMARY KEY, d INTEGER, deadline INTEGER)")
    if channel == "refs":
        store.execute("INSERT INTO reach SELECT work, 0, NULL FROM focal")
        for j in range(1, hops + 1):
            store.execute("INSERT OR IGNORE INTO reach SELECT r.dst, ?, NULL FROM cd_refs r "
                          "JOIN reach x ON r.src = x.work WHERE x.d = ?", (j, j - 1))
        return
    store.execute("INSERT INTO reach SELECT work, 0, year + ? FROM focal "
                  "WHERE year IS NOT NULL AND year + ? <= ?", (window, window, last_complete))
    for _ in range(hops):
        store.execute("DROP TABLE IF EXISTS temp.prev")
        store.execute("CREATE TEMP TABLE prev AS SELECT * FROM reach")
        store.execute("CREATE INDEX temp.prev_work ON prev(work)")
        store.execute("""
            INSERT INTO reach (work, d, deadline)
            SELECT c.src, MIN(p.d) + 1, MAX(p.deadline)
            FROM cd_citers c JOIN prev p ON c.dst = p.work JOIN cd_meta m ON m.work = c.src
            WHERE m.year IS NOT NULL AND m.year <= p.deadline
            GROUP BY c.src
            ON CONFLICT(work) DO UPDATE SET d = MIN(d, excluded.d),
                                            deadline = MAX(deadline, excluded.deadline)""")


def frontier(store, channel, layer, window, last_complete):
    """Nodes whose neighbours layer `layer` needs, minus those already logged.

    Returns (todo [(work, d, deadline)], stats). If a lower layer is incomplete, todo holds
    only that lower layer's nodes (the reach of higher layers is not yet knowable)."""
    build_reach(store, channel, layer - 1, window, last_complete)
    if channel == "refs":
        rows = store.execute("""
            SELECT x.work, x.d, x.deadline, l.status FROM reach x
            LEFT JOIN cd_log l ON l.work = x.work AND l.channel = 'refs'""").fetchall()
        pending = [(w, d, dl) for w, d, dl, st in rows if st is None]
    else:
        rows = store.execute("""
            SELECT x.work, x.d, x.deadline, l.status, l.upto_year FROM reach x
            LEFT JOIN cd_log l ON l.work = x.work AND l.channel = 'cites'""").fetchall()
        pending = [(w, d, dl) for w, d, dl, st, up in rows
                   if st is None or (st == "ok" and (up is None or up < dl))]
    by_d = {}
    for w, d, dl, *_ in rows:
        by_d.setdefault(d, 0)
        by_d[d] += 1
    low = [p for p in pending if p[1] < layer - 1]
    stats = {"need": len(rows), "need_by_distance": by_d, "pending": len(pending),
             "lower_layer_pending": len(low)}
    return (low if low else pending), stats


# ---------------------------------------------------------------- HTTP
class Stop(Exception):
    """Unrecoverable for this run (key refused, quota exhausted)."""


class Suspect(Exception):
    """A response that parses but cannot be trusted (e.g. silently empty)."""


def get_json(url, tries=6, timeout=120, opener=urllib.request.urlopen):
    last = None
    for attempt in range(tries):
        try:
            with opener(urllib.request.Request(url, headers=UA), timeout=timeout) as r:
                body = json.loads(r.read())
                remaining = r.headers.get("X-RateLimit-Remaining") if r.headers else None
            if not isinstance(body, dict) or not isinstance(body.get("results"), list) or "meta" not in body:
                raise Suspect("response without results/meta")
            return body, remaining
        except urllib.error.HTTPError as e:
            if e.code in (401, 403):
                raise Stop(f"OpenAlex refused the request (HTTP {e.code}); check the API key")
            last = f"HTTP {e.code}"
            if e.code == 429 and attempt >= 3:
                raise Stop("HTTP 429 persists: daily budget likely exhausted; rerun later")
            time.sleep(min(60, 2 ** attempt * (5 if e.code == 429 else 1)))
        except (Suspect, ValueError) as e:
            last = str(e)
            time.sleep(2 ** attempt)
        except Exception as e:  # network
            last = type(e).__name__
            time.sleep(2 ** attempt)
    raise RuntimeError(f"gave up after {tries} tries: {last}")


def fetch_refs_batch(base, key, nodes, get=get_json):
    """nodes [(work, d, None)] -> ({work: (year, refs, cited_by)}, missing, calls)."""
    ids = [w for w, _, _ in nodes]
    params = {"filter": "openalex:" + "|".join(wtext(w) for w in ids),
              "per-page": len(ids), "select": SELECT}
    if key:
        params["api_key"] = key
    for attempt in range(3):
        body, remaining = get(f"{base}/works?" + urllib.parse.urlencode(params))
        if body["results"] or len(ids) < 10:
            break
        time.sleep(2 ** attempt * 5)     # silently empty batch: never mark as fetched
    else:
        raise Suspect(f"{len(ids)} ids requested, 0 returned three times")
    want, got = set(ids), {}
    for w in body["results"]:
        n = wid(w.get("id"))
        if n in want:
            got[n] = (w.get("publication_year"), [r for r in map(wid, w.get("referenced_works") or []) if r],
                      w.get("cited_by_count"))
    return got, sorted(want - set(got)), 1, remaining


def fetch_cites_batch(base, key, nodes, get=get_json, per_page=200):
    """nodes [(work, d, deadline)] -> citers [(citer, year, refs, cited_by)], calls.
    One OR filter over the batch, bounded by the batch's latest deadline; per-node deadlines
    are applied when edges are written."""
    ids = [w for w, _, _ in nodes]
    top = max(dl for _, _, dl in nodes)
    flt = "cites:" + "|".join(wtext(w) for w in ids) + f",publication_year:<{top + 1}"
    cursor, out, calls, remaining = "*", [], 0, None
    while cursor:
        params = {"filter": flt, "per-page": per_page, "select": SELECT, "cursor": cursor}
        if key:
            params["api_key"] = key
        body, remaining = get(f"{base}/works?" + urllib.parse.urlencode(params))
        calls += 1
        for w in body["results"]:
            n = wid(w.get("id"))
            if n:
                out.append((n, w.get("publication_year"),
                            [r for r in map(wid, w.get("referenced_works") or []) if r], w.get("cited_by_count")))
        cursor = (body.get("meta") or {}).get("next_cursor") if body["results"] else None
        if calls > 2000:
            raise Suspect("more than 2000 pages for one batch; lower --batch")
    return out, calls, remaining


# ---------------------------------------------------------------- write
UPSERT_META = ("INSERT INTO cd_meta (work, year, n_refs, cited_by) VALUES (?, ?, ?, ?) "
               "ON CONFLICT(work) DO UPDATE SET year = COALESCE(excluded.year, year), "
               "n_refs = COALESCE(excluded.n_refs, n_refs), cited_by = COALESCE(excluded.cited_by, cited_by)")


def write_refs(store, nodes, got, missing):
    at, d_of = now(), {w: d + 1 for w, d, _ in nodes}      # log the fetch layer (= distance + 1)
    with store:
        for w, (year, refs, cited) in got.items():
            store.execute(UPSERT_META, (w, year, len(refs), cited))
            store.executemany("INSERT OR IGNORE INTO cd_refs VALUES (?, ?)", [(w, r) for r in refs if r != w])
            store.execute("INSERT OR REPLACE INTO cd_log VALUES (?, 'refs', ?, 'ok', ?, NULL, ?)",
                          (w, d_of[w], len(refs), at))
        for w in missing:
            store.execute("INSERT OR REPLACE INTO cd_log VALUES (?, 'refs', ?, 'missing', 0, NULL, ?)",
                          (w, d_of[w], at))


def write_cites(store, nodes, citers):
    at = now()
    deadline = {w: dl for w, _, dl in nodes}
    counts = dict.fromkeys(deadline, 0)
    with store:
        for c, year, refs, cited in citers:
            store.execute(UPSERT_META, (c, year, len(refs), cited))
            if year is None:
                continue
            for r in set(refs) & deadline.keys():
                if year <= deadline[r] and r != c:
                    store.execute("INSERT OR IGNORE INTO cd_citers VALUES (?, ?)", (r, c))
                    counts[r] += 1
        for w, d, dl in nodes:
            store.execute("INSERT OR REPLACE INTO cd_log VALUES (?, 'cites', ?, 'ok', ?, ?, ?)",
                          (w, d + 1, counts[w], dl, at))


# ---------------------------------------------------------------- commands
def read_key(a):
    if os.environ.get("OPENALEX_API_KEY"):
        return os.environ["OPENALEX_API_KEY"].strip()
    if a.env_file:
        for line in Path(a.env_file).read_text().splitlines():
            m = re.match(r"\s*(?:export\s+)?OPENALEX_API_KEY=(.*)$", line)
            if m:
                v = m.group(1).strip()
                return v[1:-1] if v[:1] in "'\"" and v[-1:] == v[:1] else v
    return None


def setup(a):
    db = connect(a.db, readonly=(a.store is not None and Path(a.store).resolve() != Path(a.db).resolve()))
    store, note = open_store(a.store or a.db, id_prefix(db))
    focal, rep = load_focal(db, a.works_sql)
    if not focal:
        sys.exit("works SQL returned no parseable work ids")
    ident = identity_report(db)
    stage_focal(store, focal)
    OPEN.extend([db, store])
    return db, store, focal, rep, ident, note


def batches_of(todo, size, channel):
    if channel == "cites":
        todo = sorted(todo, key=lambda t: (t[2], t[0]))   # similar deadlines share a batch
    return [todo[i:i + size] for i in range(0, len(todo), size)]


def estimate_calls(store, todo, channel, size):
    if channel == "refs":
        return math.ceil(len(todo) / size), "exact"
    known, pages = 0, 0
    for b in batches_of(todo, size, channel):
        cb = 0
        for w, _, _ in b:
            r = store.execute("SELECT cited_by FROM cd_meta WHERE work = ?", (w,)).fetchone()
            if r and r[0] is not None:
                known += 1
                cb += r[0]
        pages += max(1, math.ceil(cb / 200))
    return pages, f"upper bound from total cited_by_count (known for {known:,}/{len(todo):,} nodes)"


def cmd_plan(a):
    _, store, focal, rep, ident, note = setup(a)
    print(json.dumps({"focal": rep, "identity_decision": ident}, ensure_ascii=False, indent=1))
    if ident and "NULL" in ident:
        print(f"! {ident['NULL']:,} evidence rows have identity_decision NULL; the default works SQL "
              "drops them (NULL != 'namesake_paper' is NULL). Decide explicitly with --works-sql.")
    if note:
        print("!", note)
    todo, st = frontier(store, a.channel, a.layer, a.window, a.last_complete_year)
    size = a.batch or (100 if a.channel == "refs" else 50)
    calls, how = estimate_calls(store, todo, a.channel, size)
    print(f"channel {a.channel}, layer {a.layer}: nodes needed {st['need']:,} "
          f"(by distance {st['need_by_distance']}); pending {st['pending']:,}")
    if st["lower_layer_pending"]:
        print(f"! lower layers incomplete: {st['lower_layer_pending']:,} nodes; fetch will do those first, "
              "then rerun this layer (its frontier is not knowable yet)")
    print(f"calls ≈ {calls:,} ({how}); cost ≈ ${calls * a.cost_per_call:,.2f} at ${a.cost_per_call}/call")


def cmd_fetch(a):
    _, store, focal, rep, _, note = setup(a)
    key = read_key(a)
    if not key and not a.no_key:
        sys.exit("no OPENALEX_API_KEY (env or --env-file). Without a key the shared per-IP budget "
                 "returns empty pages silently; pass --no-key only for tiny tests.")
    todo, st = frontier(store, a.channel, a.layer, a.window, a.last_complete_year)
    size = min(a.batch or (100 if a.channel == "refs" else 50), 100)
    bl = batches_of(todo, size, a.channel)
    if a.max_batches:
        bl = bl[:a.max_batches]
    if st["lower_layer_pending"]:
        print(f"lower layers incomplete: fetching those {st['lower_layer_pending']:,} nodes first; rerun layer {a.layer} after")
    print(f"{a.channel} layer {a.layer}: {st['pending']:,} pending nodes -> {len(bl):,} batches")
    run = store.execute("INSERT INTO cd_runs (channel, layer, started) VALUES (?, ?, ?)",
                        (a.channel, a.layer, now())).lastrowid
    store.commit()
    s = {"ok": 0, "failed": 0, "calls": 0, "nodes_ok": 0, "missing": 0}
    stop, t0 = None, time.time()

    def job(b):
        if a.channel == "refs":
            return fetch_refs_batch(a.api_base, key, b)
        return fetch_cites_batch(a.api_base, key, b)

    with ThreadPoolExecutor(a.threads) as ex:
        futs = {ex.submit(job, b): b for b in bl}
        for f in as_completed(futs):
            b = futs[f]
            try:
                res = f.result()
            except Stop as e:
                stop = str(e)
                for g in futs:
                    g.cancel()
                continue
            except Exception as e:
                s["failed"] += 1
                if s["failed"] <= 5:
                    print(f"  batch failed ({len(b)} nodes): {e}")
                continue
            if a.channel == "refs":
                got, missing, calls, remaining = res
                write_refs(store, b, got, missing)
                s["nodes_ok"] += len(got)
                s["missing"] += len(missing)
            else:
                citers, calls, remaining = res
                write_cites(store, b, citers)
                s["nodes_ok"] += len(b)
            s["ok"] += 1
            s["calls"] += calls
            if remaining is not None and str(remaining).strip() in ("0", "0.0"):
                stop = "X-RateLimit-Remaining reached 0"
                for g in futs:
                    g.cancel()
            if s["ok"] % 50 == 0:
                print(f"  {s['ok']:,}/{len(bl):,} batches, {s['calls']:,} calls, {time.time() - t0:.0f}s", flush=True)
    store.execute("UPDATE cd_runs SET finished=?, batches_ok=?, batches_failed=?, calls=?, nodes_ok=?, "
                  "nodes_missing=?, note=? WHERE run_id=?",
                  (now(), s["ok"], s["failed"], s["calls"], s["nodes_ok"], s["missing"], stop, run))
    store.commit()
    print(f"done: {s['ok']:,} batches ok, {s['failed']:,} failed, {s['calls']:,} calls, "
          f"{s['nodes_ok']:,} nodes logged, {s['missing']:,} missing in OpenAlex; {time.time() - t0:.0f}s")
    if stop:
        print("stopped early:", stop)
    if s["failed"] or stop or len(bl) < math.ceil(st["pending"] / size):
        print("not complete: rerun the same command (only unlogged nodes are fetched)")
    if note:
        print("!", note)


def cmd_status(a):
    _, store, focal, rep, _, _ = setup(a)
    print(f"focal works {len(focal):,}")
    deepest = store.execute("SELECT MAX(layer) FROM cd_log WHERE channel = ?", (a.channel,)).fetchone()[0]
    if deepest is None:
        print(f"{a.channel}: nothing fetched yet")
        return
    for layer in range(1, deepest + 2):
        todo, st = frontier(store, a.channel, layer, a.window, a.last_complete_year)
        if st["lower_layer_pending"]:
            print(f"layer {layer}: unknown until layer {layer - 1} is complete")
            break
        need = st["need"]
        logged = need - st["pending"]
        print(f"layer {layer}: nodes needed {need:,}; logged {logged:,} ({logged / max(need, 1):.1%}); "
              f"pending {st['pending']:,}")
    # T1 acceptance: share of focal works with a non-empty reference list
    if a.channel == "refs":
        row = store.execute("""SELECT COUNT(*), SUM(l.status='ok'), SUM(l.status='missing'), SUM(l.status='ok' AND l.n>0)
                               FROM focal f LEFT JOIN cd_log l ON l.work=f.work AND l.channel='refs'""").fetchone()
        n, ok, miss, nonempty = (x or 0 for x in row)
        print(f"focal works: {n:,}; fetched {ok:,}; missing in OpenAlex {miss:,}; "
              f"non-empty references {nonempty:,} = {nonempty / max(n, 1):.1%} of focal "
              f"({nonempty / max(ok, 1):.1%} of fetched). Handoff T1 threshold: 80%.")
        for lo, hi in ((None, 1999), (2000, 2009), (2010, 2019), (2020, None)):
            q = ("SELECT COUNT(*), SUM(l.status='ok' AND l.n>0) FROM focal f LEFT JOIN cd_log l "
                 "ON l.work=f.work AND l.channel='refs' WHERE f.year IS NOT NULL")
            args = []
            if lo is not None:
                q += " AND f.year >= ?"
                args.append(lo)
            if hi is not None:
                q += " AND f.year <= ?"
                args.append(hi)
            c, ne = (x or 0 for x in store.execute(q, args).fetchone())
            if c:
                print(f"  {lo or '':>4}–{hi or '':<4}: {ne / c:.1%} non-empty of {c:,}")
    else:
        row = store.execute("SELECT COUNT(*) FROM focal WHERE year IS NOT NULL AND year + ? <= ?",
                            (a.window, a.last_complete_year)).fetchone()
        print(f"focal works eligible for the {a.window}-year window (year + {a.window} <= "
              f"{a.last_complete_year}): {row[0]:,} of {len(focal):,}")


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    for name in ("plan", "fetch", "status"):
        q = sub.add_parser(name)
        q.add_argument("--db", required=True, help="main SQLite (work_authorship_evidence)")
        q.add_argument("--store", help="SQLite for collected tables (default: --db)")
        q.add_argument("--works-sql", default=DEFAULT_WORKS_SQL, help="SELECT work_id, publication_year")
        q.add_argument("--channel", choices=("refs", "cites"), required=True)
        q.add_argument("--window", type=int, default=3, help="cites: years after focal publication")
        q.add_argument("--last-complete-year", type=int, default=2025,
                       help="cites: last calendar year OpenAlex holds completely")
        if name != "status":
            q.add_argument("--layer", type=int, required=True)
            q.add_argument("--batch", type=int, help="ids per request (refs 100, cites 50)")
        if name == "plan":
            q.add_argument("--cost-per-call", type=float, default=0.001)
        if name == "fetch":
            q.add_argument("--env-file")
            q.add_argument("--no-key", action="store_true")
            q.add_argument("--threads", type=int, default=4)
            q.add_argument("--max-batches", type=int)
            q.add_argument("--api-base", default=API)
    a = p.parse_args(argv)
    if getattr(a, "layer", 1) < 1:
        p.error("--layer starts at 1")
    {"plan": cmd_plan, "fetch": cmd_fetch, "status": cmd_status}[a.cmd](a)
    for con in OPEN:
        con.close()
    OPEN.clear()


if __name__ == "__main__":
    main()
