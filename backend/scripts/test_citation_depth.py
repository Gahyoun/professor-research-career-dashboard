"""Tests for backend/topics/depth: layered collector and depth sweep.

A synthetic citation world with planted fields is served by a local fake OpenAlex, collected
with citation_layers.py, and analysed with depth_sweep.py.
"""
import contextlib
import csv
import io
import json
import os
import sqlite3
import sys
import tempfile
import threading
import unittest
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import numpy as np

DEPTH = Path(__file__).resolve().parents[1] / "topics" / "depth"
sys.path.insert(0, str(DEPTH))
import cdcommon  # noqa: E402
import citation_layers as cl  # noqa: E402

try:
    import scipy.sparse as sp  # noqa: F401
    import sklearn  # noqa: F401
    import depth_sweep as ds  # noqa: E402
    import faculty_louvain as fl  # noqa: E402
    HAVE_SCI = True
except ImportError:
    HAVE_SCI = False

os.environ["no_proxy"] = os.environ["NO_PROXY"] = "127.0.0.1,localhost"
cl.time.sleep = lambda s: None          # retries without waiting


# ---------------------------------------------------------------- synthetic world
def make_world(seed=1, fields=4, per_field=60, profs_per_field=6):
    """Works 1..: deep ancestors (2 hops), references (1 hop), focal works, later citers.
    Ids are integers; OpenAlex form is W<id>."""
    rng = np.random.default_rng(seed)
    nid = iter(range(1000, 10 ** 7))
    year, refs = {}, {}
    hubs = [next(nid) for _ in range(5)]
    for h in hubs:
        year[h], refs[h] = 1960, []
    deep = {f: [next(nid) for _ in range(40)] for f in range(fields)}
    for f, ws in deep.items():
        for w in ws:
            year[w], refs[w] = 1980, list(rng.choice(hubs, 2, replace=False))
    mid = {f: [next(nid) for _ in range(80)] for f in range(fields)}
    for f, ws in mid.items():
        for w in ws:
            own = list(rng.choice(deep[f], 6, replace=False))
            other = list(rng.choice(deep[(f + 1) % fields], 1))
            year[w], refs[w] = 2000, own + other + [int(rng.choice(hubs))]
    focal, field_of, profs = {}, {}, []
    for f in range(fields):
        for i in range(per_field):
            w = next(nid)
            y = int(rng.integers(2012, 2025))
            r = list(rng.choice(mid[f], 8, replace=False)) + list(rng.choice(mid[int(rng.integers(fields))], 1))
            year[w], refs[w] = y, [int(x) for x in r]
            focal[w], field_of[w] = y, f
        for p in range(profs_per_field):
            profs.append((f"P{f}_{p}", f))
    # citers: each focal work gets citers within and beyond its 3-year window
    for w, y in list(focal.items()):
        f = field_of[w]
        for k in range(4):
            c = next(nid)
            year[c] = y + int(rng.integers(0, 6))
            peers = [x for x in focal if field_of[x] == f and x != w]
            refs[c] = [w] + [int(x) for x in rng.choice(peers, 2, replace=False)]
    links = []
    fw = sorted(focal)
    for uid, f in profs:
        mine = [w for w in fw if field_of[w] == f]
        for w in rng.choice(mine, 12, replace=False):
            links.append((uid, int(w)))
    return {"year": year, "refs": refs, "focal": focal, "field": field_of, "links": links, "hubs": hubs}


def write_main_db(path, world, prefix="https://openalex.org/"):
    con = sqlite3.connect(path)
    con.execute("""CREATE TABLE work_authorship_evidence (professor_uid TEXT, work_id TEXT, publication_year INTEGER,
                   identity_decision TEXT, subfield_id TEXT, PRIMARY KEY (professor_uid, work_id))""")
    for uid, w in world["links"]:
        con.execute("INSERT OR IGNORE INTO work_authorship_evidence VALUES (?,?,?,?,?)",
                    (uid, f"{prefix}W{w}", world["focal"][w], "true_paper", f"sf{world['field'][w]}"))
    # one namesake row and one NULL-decision row that the default SQL must exclude
    con.execute("INSERT INTO work_authorship_evidence VALUES ('PX', 'W99999999', 2015, 'namesake_paper', 'sfX')")
    con.execute("INSERT INTO work_authorship_evidence VALUES ('PY', 'W99999998', 2015, NULL, 'sfY')")
    con.commit()
    con.close()


class FakeOpenAlex:
    """Implements the two query shapes the collector sends."""

    def __init__(self, world, fail_first=0, empty_first=0, per_page_cap=200):
        self.w = world
        self.citers = {}
        for c, rs in world["refs"].items():
            for r in rs:
                self.citers.setdefault(r, []).append(c)
        self.fail_left, self.empty_left, self.calls = fail_first, empty_first, 0
        self.cap = per_page_cap
        self.lock = threading.Lock()

    def record(self, n):
        return {"id": f"https://openalex.org/W{n}", "publication_year": self.w["year"].get(n),
                "referenced_works": [f"https://openalex.org/W{r}" for r in self.w["refs"].get(n, [])],
                "cited_by_count": len(self.citers.get(n, []))}

    def handle(self, query):
        q = urllib.parse.parse_qs(query)
        with self.lock:
            self.calls += 1
            if self.fail_left:
                self.fail_left -= 1
                return 500, {}
            if self.empty_left:
                self.empty_left -= 1
                return 200, {"meta": {"count": 0}, "results": []}
        flt = q["filter"][0]
        if flt.startswith("openalex:"):
            ids = [int(x[1:]) for x in flt.split(":", 1)[1].split("|")]
            res = [self.record(i) for i in ids if i in self.w["year"]]
            return 200, {"meta": {"count": len(res)}, "results": res}
        parts = dict(p.split(":", 1) for p in flt.split(","))
        ids = [int(x[1:]) for x in parts["cites"].split("|")]
        top = int(parts["publication_year"].lstrip("<"))
        found = sorted({c for i in ids for c in self.citers.get(i, []) if self.w["year"][c] < top})
        per = min(int(q["per-page"][0]), self.cap)
        cur = q.get("cursor", ["*"])[0]
        off = 0 if cur == "*" else int(cur)
        page = found[off:off + per]
        nxt = str(off + per) if off + per < len(found) else None
        return 200, {"meta": {"count": len(found), "next_cursor": nxt}, "results": [self.record(c) for c in page]}


@contextlib.contextmanager
def serve(fake):
    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            code, body = fake.handle(urllib.parse.urlsplit(self.path).query)
            data = json.dumps(body).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("X-RateLimit-Remaining", "1000")
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *a):
            pass

    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        yield f"http://127.0.0.1:{srv.server_address[1]}"
    finally:
        srv.shutdown()


def quiet(fn, *a):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        fn(*a)
    return buf.getvalue()


def collect(db, base, channel, layers, extra=()):
    for k in layers:
        for _ in range(3):      # a lower-layer top-up may need a rerun
            quiet(cl.main, ["fetch", "--db", db, "--channel", channel, "--layer", str(k), "--no-key",
                            "--api-base", base, "--threads", "2", *extra])


# ---------------------------------------------------------------- tests
class IdTests(unittest.TestCase):
    def test_wid_forms(self):
        self.assertEqual(cdcommon.wid("W123"), 123)
        self.assertEqual(cdcommon.wid("https://openalex.org/W123"), 123)
        self.assertEqual(cdcommon.wid(" openalex.org/w42 "), 42)
        self.assertIsNone(cdcommon.wid("A123"))
        self.assertIsNone(cdcommon.wid(None))


class CollectorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = str(Path(self.tmp.name) / "main.sqlite")
        self.world = make_world(per_field=20, profs_per_field=3)
        write_main_db(self.db, self.world)

    def tearDown(self):
        self.tmp.cleanup()

    def store(self):
        return sqlite3.connect(self.db)

    def test_default_sql_and_identity_report(self):
        con = sqlite3.connect(self.db)
        focal, rep = cdcommon.load_focal(con, cdcommon.DEFAULT_WORKS_SQL)
        self.assertNotIn(99999999, focal)               # namesake excluded
        self.assertNotIn(99999998, focal)               # NULL decision silently excluded …
        self.assertEqual(cdcommon.identity_report(con)["NULL"], 1)   # … and reported
        self.assertEqual(cdcommon.id_prefix(con), "https://openalex.org/")

    def test_refs_layers_complete_and_resumable(self):
        fake = FakeOpenAlex(self.world, fail_first=6)  # first batches fail: nothing logged
        with serve(fake) as base:
            quiet(cl.main, ["fetch", "--db", self.db, "--channel", "refs", "--layer", "1", "--no-key",
                            "--api-base", base, "--threads", "1", "--batch", "10"])
            con = self.store()
            logged_first = con.execute("SELECT COUNT(*) FROM cd_log").fetchone()[0]
            self.assertLess(logged_first, len({w for _, w in self.world["links"]}))
            collect(self.db, base, "refs", [1, 2, 3], ["--batch", "10"])
        con = self.store()
        focal = {w for _, w in self.world["links"]}
        # layer 1: every focal work logged, all references stored
        got = {r[0] for r in con.execute("SELECT work FROM cd_log WHERE channel='refs' AND layer=1")}
        self.assertEqual(got, focal)
        n1 = sum(len(self.world["refs"][w]) for w in focal)
        self.assertEqual(con.execute(f"SELECT COUNT(*) FROM cd_refs WHERE src IN ({','.join(map(str, focal))})").fetchone()[0],
                         sum(len(set(self.world['refs'][w])) for w in focal))
        self.assertGreater(n1, 0)
        # layer 3 reached the hubs' (empty) reference lists
        for h in self.world["hubs"]:
            st = con.execute("SELECT status, n FROM cd_log WHERE work=? AND channel='refs'", (h,)).fetchone()
            self.assertEqual(st, ("ok", 0))
        # T1-compatible view with the main DB's prefix
        v = con.execute("SELECT work_id, referenced_work_id FROM work_references LIMIT 1").fetchone()
        self.assertTrue(v[0].startswith("https://openalex.org/W"))
        # rerun fetches nothing
        with serve(FakeOpenAlex(self.world)) as base:
            out = quiet(cl.main, ["fetch", "--db", self.db, "--channel", "refs", "--layer", "3", "--no-key", "--api-base", base])
        self.assertIn("0 pending nodes", out)

    def test_silently_empty_batch_is_not_logged(self):
        fake = FakeOpenAlex(self.world, empty_first=10)
        with serve(fake) as base:
            quiet(cl.main, ["fetch", "--db", self.db, "--channel", "refs", "--layer", "1", "--no-key",
                            "--api-base", base, "--threads", "1", "--batch", "20", "--max-batches", "1"])
        con = self.store()
        self.assertEqual(con.execute("SELECT COUNT(*) FROM cd_log").fetchone()[0], 0)

    def test_missing_ids_are_logged_as_missing(self):
        world = dict(self.world)
        gone = self.world["links"][0][1]
        world["year"] = {k: v for k, v in self.world["year"].items() if k != gone}
        with serve(FakeOpenAlex(world)) as base:
            collect(self.db, base, "refs", [1])
        st = self.store().execute("SELECT status FROM cd_log WHERE work=?", (gone,)).fetchone()
        self.assertEqual(st, ("missing",))

    def test_cites_window_and_eligibility(self):
        with serve(FakeOpenAlex(self.world, per_page_cap=3)) as base:   # forces paging
            collect(self.db, base, "cites", [1, 2], ["--window", "3", "--last-complete-year", "2025", "--batch", "7"])
        con = self.store()
        focal = {w for _, w in self.world["links"]}
        eligible = {w for w in focal if self.world["focal"][w] + 3 <= 2025}
        logged1 = {r[0] for r in con.execute("SELECT work FROM cd_log WHERE channel='cites' AND layer=1")}
        self.assertEqual(logged1, eligible)
        for dst, src in con.execute("SELECT dst, src FROM cd_citers WHERE dst IN (%s)" % ",".join(map(str, eligible))):
            self.assertLessEqual(self.world["year"][src], self.world["focal"][dst] + 3)
        # every in-window citer of an eligible focal work was stored
        want = {(w, c) for w in eligible for c, rs in self.world["refs"].items()
                if w in rs and self.world["year"][c] <= self.world["focal"][w] + 3}
        have = set(con.execute("SELECT dst, src FROM cd_citers WHERE dst IN (%s)" % ",".join(map(str, eligible))))
        self.assertEqual(have, want)


@unittest.skipUnless(HAVE_SCI, "scipy/scikit-learn not installed")
class SweepUnitTests(unittest.TestCase):
    def graph(self, edges, years=None, n=None):
        ids = np.arange(n or (max(max(e) for e in edges) + 1), dtype=np.int64)
        u, v = zip(*edges)
        A = sp.csr_matrix((np.ones(len(u), dtype=np.float32), (u, v)), shape=(len(ids), len(ids)))
        year = np.array(years if years is not None else [2000] * len(ids), dtype=np.int64)
        return ds.Graph(ids, A, year, np.ones(len(ids), bool), np.full(len(ids), 9999))

    def test_reach_layers_are_minimum_distance(self):
        # 0->1, 0->2, 1->2, 2->3, 3->0 (cycle back to self)
        G = self.graph([(0, 1), (0, 2), (1, 2), (2, 3), (3, 0)])
        L = ds.hop_layers(G, np.array([0]), np.array([ds.NOYEAR]), 3, "reach", "refs")
        self.assertEqual(sorted(L[0].indices), [1, 2])
        self.assertEqual(sorted(L[1].indices), [3])           # 2 already at distance 1
        self.assertEqual(L[2].nnz, 0)                          # 0 is self: removed
        P = ds.hop_layers(G, np.array([0]), np.array([ds.NOYEAR]), 2, "paths", "refs")
        self.assertEqual(dict(zip(P[1].indices, P[1].data)), {2: 1.0, 3: 1.0})   # 0->1->2, 0->2->3

    def test_window_applies_on_every_hop(self):
        # cites direction: 0 is cited by 1 (2015) and 2 (2019); 1 is cited by 3 (2016)
        G = self.graph([(0, 1), (0, 2), (1, 3)], years=[2014, 2015, 2019, 2016])
        L = ds.hop_layers(G, np.array([0]), np.array([2017]), 2, "reach", "cites")
        self.assertEqual(list(L[0].indices), [1])
        self.assertEqual(list(L[1].indices), [3])

    def test_qhat_is_unbiased_u_statistic(self):
        rng = np.random.default_rng(0)
        E = rng.normal(size=(7, 5))
        E /= np.linalg.norm(E, axis=1)[:, None]
        works = np.arange(7, dtype=np.int64)
        q = ds.qhat_groups(E, works, [("p", int(i), 2020) for i in range(7)], by_year=False)
        brute = np.mean([np.sum((E[i] - E[j]) ** 2) for i in range(7) for j in range(7) if i != j])
        self.assertAlmostEqual(q["p"][1], brute, places=5)
        self.assertEqual(ds.qhat_groups(E, works, [("p", 0, 2020)], by_year=False), {})    # n = 1 dropped

    def test_row_side_svd_matches_exact(self):
        # 10 planted groups sharing column blocks, plus noise: a decaying spectrum like real data
        rng = np.random.default_rng(1)
        n, m, g = 400, 3000, 10
        grp = rng.integers(g, size=n)
        rows, cols = [], []
        for i in range(n):
            c = np.concatenate([grp[i] * 200 + rng.choice(200, 15, replace=False), rng.choice(m, 10, replace=False)])
            rows += [i] * len(c)
            cols += c.tolist()
        X = sp.csr_matrix((np.ones(len(rows), dtype=np.float32), (rows, cols)), shape=(n, m))
        X.data[:] = 1
        E, energy, k, zero = ds.embed(X, 12, seed=0)
        s = np.linalg.svd(X.toarray(), compute_uv=False)
        exact = float((s[:12] ** 2).sum() / (s ** 2).sum())
        self.assertGreater(energy, 0.98 * exact)
        self.assertLessEqual(energy, exact + 1e-4)
        idx, _ = ds.knn(E, 10)
        self.assertGreater(float((grp[idx] == grp[:, None]).mean()), 0.95)   # neighbours in the planted group
        self.assertEqual((k, zero), (12, 0))

    def test_overlap_and_survival_identities(self):
        idx = np.array([[1, 2], [0, 2], [0, 1]])
        self.assertEqual(ds.knn_overlap(idx, idx), 1.0)
        lab = np.array([0] * 6 + [1] * 6)
        self.assertEqual(ds.survival(lab, lab, 5), (1.0, 1.0))
        self.assertEqual(ds.survival(lab, np.arange(12), 5), (0.0, 0.0))


@unittest.skipUnless(HAVE_SCI, "scipy/scikit-learn not installed")
class SweepEndToEnd(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.db = str(Path(cls.tmp.name) / "main.sqlite")
        cls.world = make_world()
        write_main_db(cls.db, cls.world)
        with serve(FakeOpenAlex(cls.world)) as base:
            collect(cls.db, base, "refs", [1, 2])
            collect(cls.db, base, "cites", [1], ["--batch", "25"])

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def run_sweep(self, out, *extra):
        quiet(ds.main, ["run", "--db", self.db, "--out", out, "--dims", "16", "--knn", "8",
                        "--target-k", "4", "--seeds", "3", "--min-size", "5", *extra])
        return json.loads((Path(out) / "summary.json").read_text())

    def test_refs_depth_sweep(self):
        out = str(Path(self.tmp.name) / "refs")
        s = self.run_sweep(out, "--channel", "refs", "--depths", "1,2,3")
        self.assertEqual(s["usable_depths"], [1, 2])
        self.assertIn("3", s["skipped"])                         # layer 3 not fetched -> refused
        r = s["communities"]["4"]
        for d in ("1", "2"):
            self.assertEqual(r["depth"][d]["communities"], 4)    # same K at every depth
            self.assertGreater(r["depth"][d]["ami_vs_reference"]["mean"], 0.8)   # planted fields recovered
        self.assertIn("1-2", r["ami"])
        # floors and between-depth values are both cross-replicate (2 x seeds^2 and seeds^2 pairs)
        self.assertEqual(r["ami"]["1-2"]["n"], 2 * 3 * 3)
        self.assertEqual(r["depth"]["1"]["ami_floor"]["n"], 3 * 3)
        self.assertTrue((Path(out) / "report.md").read_text().startswith("# 깊이 비교"))
        rows = (Path(out) / "professor_qhat.csv").read_text().splitlines()
        self.assertEqual(rows[0], "professor_uid,n_core_works,qhat_d1,qhat_d2")
        self.assertGreater(len(rows), 10)

    def test_cites_channel_and_cross_channel_compare(self):
        a = str(Path(self.tmp.name) / "r1")
        b = str(Path(self.tmp.name) / "c1")
        sa = self.run_sweep(a, "--channel", "refs", "--depths", "1")
        sb = self.run_sweep(b, "--channel", "cites", "--depths", "1,2")
        self.assertEqual(sb["usable_depths"], [1])               # cites layer 2 not fetched
        self.assertLess(sb["eligible"], sa["eligible"])          # open windows excluded
        out = str(Path(self.tmp.name) / "cross")
        quiet(ds.main, ["compare", a, b, "--out", out])
        cmp = json.loads((Path(out) / "compare.json").read_text())
        self.assertGreater(cmp["common_works"], 50)
        self.assertIn("K4_d1 vs K4_d1", cmp["ami"])


@unittest.skipUnless(HAVE_SCI, "scipy/scikit-learn not installed")
class FacultyLouvainTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.db = str(Path(cls.tmp.name) / "main.sqlite")
        cls.world = make_world()
        write_main_db(cls.db, cls.world)
        with serve(FakeOpenAlex(cls.world)) as base:
            collect(cls.db, base, "refs", [1])
            collect(cls.db, base, "cites", [1], ["--include-open-windows", "--batch", "25"])

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def run_fl(self, name, *extra):
        out = Path(self.tmp.name) / name
        quiet(fl.main, ["--db", self.db, "--out", str(out), "--stability-seeds", "1,2",
                        "--labels-sql", "SELECT work_id, subfield_id FROM work_authorship_evidence", *extra])
        rows = list(csv.DictReader(open(out / "work_communities.csv")))
        return json.loads((out / "summary.json").read_text()), rows, out

    def test_open_windows_cover_every_focal_work(self):
        con = sqlite3.connect(self.db)
        focal = {w for _, w in self.world["links"]}
        logged = {r[0] for r in con.execute("SELECT work FROM cd_log WHERE channel='cites'")}
        self.assertEqual(logged, focal)
        late = [w for w in focal if self.world["focal"][w] + 3 > 2025]
        self.assertTrue(late)                                      # recent works included too

    def test_both_directions_fixed_seed(self):
        s, rows, out = self.run_fl("both")
        self.assertTrue(s["rerun_identical"])
        self.assertAlmostEqual(sum(s["shared_neighbour_share_by_channel"].values()), 1.0, places=5)
        self.assertEqual(set(s["shared_neighbour_share_by_channel"]), {"refs", "cites"})
        from sklearn.metrics import adjusted_mutual_info_score as ami
        field = [self.world["field"][int(r["work_id"][1:])] for r in rows if r["community"] != "-1"]
        com = [int(r["community"]) for r in rows if r["community"] != "-1"]
        self.assertGreater(ami(field, com), 0.8)                   # planted fields recovered
        s2, rows2, _ = self.run_fl("both_again")
        self.assertEqual([r["community"] for r in rows], [r["community"] for r in rows2])   # same seed, same file
        self.assertIn("전체 교수 Louvain", (out / "report.md").read_text())
        self.assertTrue((out / "professor_communities.csv").read_text().startswith("professor_uid,community,n_works"))

    def test_single_channel_and_networkx_backend(self):
        s, rows, _ = self.run_fl("refs_only", "--channels", "refs", "--backend", "networkx")
        self.assertEqual(list(s["shared_neighbour_share_by_channel"]), ["refs"])
        self.assertGreater(s["communities"], 1)

    def test_refuses_uncollected_channel(self):
        db = str(Path(self.tmp.name) / "empty.sqlite")
        write_main_db(db, self.world)
        cdcommon.open_store(db)[0].close()
        with self.assertRaises(SystemExit):
            quiet(fl.main, ["--db", db, "--out", str(Path(self.tmp.name) / "x")])


class ImportCacheTests(unittest.TestCase):
    def test_topics_cache_becomes_refs_layer_1(self):
        import gzip
        with tempfile.TemporaryDirectory() as tmp:
            db = str(Path(tmp) / "main.sqlite")
            world = make_world(per_field=20, profs_per_field=2)
            write_main_db(db, world)
            focal = sorted({w for _, w in world["links"]})
            cache = Path(tmp) / "cache"
            cache.mkdir()
            with gzip.open(cache / "b00000.jsonl.gz", "wt") as fh:
                for w in focal[:-3] + [123]:                       # 3 focal missing, 1 non-focal
                    fh.write(json.dumps({"id": f"W{w}", "refs": [f"W{r}" for r in world["refs"].get(w, [])], "cited": 1}) + "\n")
            out = quiet(cl.main, ["import-cache", "--db", db, "--channel", "refs", "--cache", str(cache)])
            self.assertIn("focal works still without refs: 3", out)
            con = sqlite3.connect(db)
            self.assertEqual(con.execute("SELECT COUNT(*) FROM cd_log WHERE channel='refs' AND layer=1").fetchone()[0], len(focal) - 3)
            with serve(FakeOpenAlex(world)) as base:
                out = quiet(cl.main, ["fetch", "--db", db, "--channel", "refs", "--layer", "1", "--no-key", "--api-base", base])
            self.assertIn("3 pending nodes", out)


if __name__ == "__main__":
    unittest.main()
