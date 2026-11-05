#!/usr/bin/env python3
"""How much do faculty-wide citation communities change with neighbourhood depth 1, 2, 3?

One run = one channel (refs or cites; never mixed). The node set is FIXED across depths:
the faculty's own works (focal) whose depth-1 vector is non-empty ("core"). Depth only
changes what two works must share to be close:

  depth 1  works they cite directly (bibliographic coupling) / their direct citers
  depth 2  + what those cite / + citers of citers
  depth 3  + one more hop

Pipeline per depth d (identical except d):
  hop layers N_h = nodes at minimum distance h from the work (reach) or walk counts (paths)
  -> TF-IDF over the faculty corpus: idf = ln((1+N)/(1+df)), df over all eligible focal works
     (no +1, so a feature every work reaches weighs 0), min/max df
  -> each hop layer L2-normalised and weighted alpha^(h-1) ("balanced"), row L2-normalised
  -> truncated SVD (same dims as space_fit; randomized, row-side) -> unit vectors
  -> k-nearest-neighbour graph (cosine) -> Leiden (RB configuration), resolution bisected
     so that every depth has the SAME number of communities (size >= --min-size)

Comparisons, each against a noise floor measured the same way:
  kNN neighbourhood overlap (no partition, no resolution)  floor: two SVD seeds
  AMI / ARI between partitions                             floor: Leiden seeds within depth
  community survival (best-match Jaccard >= 0.5)
  AMI against OpenAlex subfield (descriptive only; not validation)
  professor-level Q-hat (Rao, unbiased) rank correlation    — does depth change conclusions?

  python3 -I depth_sweep.py run --db MAIN.sqlite --channel refs --depths 1,2 --out runs/refs
  python3 -I depth_sweep.py compare runs/refs runs/cites --out runs/cross   # cross-channel
"""
import argparse
import csv
import json
import math
import sys
import time
from collections import defaultdict
from pathlib import Path

import numpy as np
import scipy.sparse as sp

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cdcommon import DEFAULT_LINKS_SQL, DEFAULT_WORKS_SQL, connect, load_focal, wid  # noqa: E402

DEFAULT_LABELS_SQL = ("SELECT work_id, subfield_id FROM work_authorship_evidence "
                      "WHERE subfield_id IS NOT NULL")
NOYEAR = 10 ** 6
T0 = time.time()


def say(*x):
    print(f"[{time.time() - T0:7.1f}s]", *x, flush=True)


# ================================================================ graph
class Graph:
    """Integer-indexed channel graph. A[u, v] = 1 for the hop u -> v
    (refs: u cites v; cites: v cites u, i.e. towards descendants)."""

    def __init__(self, ids, A, year, logged, upto):
        self.ids, self.A, self.year, self.logged, self.upto = ids, A, year, logged, upto
        self.n = len(ids)

    def index(self, works):
        works = np.asarray(works, dtype=np.int64)
        pos = np.searchsorted(self.ids, works)
        pos[pos >= self.n] = 0
        ok = self.ids[pos] == works
        return np.where(ok, pos, -1)


def read_pairs(con, sql, params=(), chunk=5_000_000):
    cur, parts = con.execute(sql, params), []
    while True:
        rows = cur.fetchmany(chunk)
        if not rows:
            break
        parts.append(np.asarray(rows, dtype=np.int64).reshape(-1, len(rows[0])))
    return np.concatenate(parts) if parts else np.zeros((0, 2), dtype=np.int64)


def load_graph(store, channel, focal):
    if channel == "refs":
        e = read_pairs(store, "SELECT src, dst FROM cd_refs")
        u, v = e[:, 0], e[:, 1]
    else:
        e = read_pairs(store, "SELECT dst, src FROM cd_citers")
        u, v = e[:, 0], e[:, 1]
    meta = read_pairs(store, "SELECT work, COALESCE(year, -1) FROM cd_meta")
    log = read_pairs(store, "SELECT work, COALESCE(upto_year, -1) FROM cd_log WHERE channel = ?", (channel,))
    fw = np.fromiter(focal.keys(), dtype=np.int64, count=len(focal))
    ids = np.unique(np.concatenate([fw, u, v, meta[:, 0] if len(meta) else fw[:0], log[:, 0] if len(log) else fw[:0]]))
    n = len(ids)
    ui, vi = np.searchsorted(ids, u), np.searchsorted(ids, v)
    A = sp.csr_matrix((np.ones(len(ui), dtype=np.float32), (ui, vi)), shape=(n, n))
    A.sum_duplicates()
    A.data[:] = 1
    year = np.full(n, NOYEAR, dtype=np.int64)
    if len(meta):
        mi = np.searchsorted(ids, meta[:, 0])
        y = meta[:, 1]
        year[mi[y >= 0]] = y[y >= 0]
    fy = np.array([focal[w] if focal[w] is not None else -1 for w in fw], dtype=np.int64)
    fi = np.searchsorted(ids, fw)
    fill = (year[fi] == NOYEAR) & (fy >= 0)
    year[fi[fill]] = fy[fill]
    logged = np.zeros(n, dtype=bool)
    upto = np.full(n, -1, dtype=np.int64)
    if len(log):
        li = np.searchsorted(ids, log[:, 0])
        logged[li] = True
        upto[li] = log[:, 1]
    return Graph(ids, A, year, logged, upto)


def eligible_rows(G, channel, focal, window, last_complete):
    """Focal node indices and per-row deadlines (cites) or NOYEAR (refs).
    refs: every focal work (an unfetched one has an empty row, is counted by coverage(), and
    drops out of the core). cites: only works whose window has closed."""
    fi = np.unique(G.index(list(focal.keys())))
    fi = fi[fi >= 0]
    if channel == "refs":
        return fi, np.full(len(fi), NOYEAR, dtype=np.int64)
    y = G.year[fi]
    ok = (y < NOYEAR) & (y + window <= last_complete)
    rows = fi[ok]
    return rows, y[ok] + window


def coverage(G, channel, rows, deadline, depth):
    """Share of nodes within depth-1 hops (whose neighbours depth `depth` needs) that are logged
    (cites: logged up to the required deadline)."""
    n = G.n
    if depth <= 1:
        need = np.zeros(n, dtype=bool)
        need[rows] = True
        if channel == "refs":
            ok = G.logged
        else:
            dl = np.full(n, -1, dtype=np.int64)
            np.maximum.at(dl, rows, deadline)
            ok = G.logged & (G.upto >= dl)
        return float(ok[need].mean()) if need.any() else 0.0, int(need.sum())
    if channel == "refs":
        reached = np.zeros(n, dtype=bool)
        reached[rows] = True
        front = reached.copy()
        AT = G.A.T.tocsr()
        for _ in range(depth - 1):
            nxt = (AT @ front.astype(np.float32)) > 0
            front = nxt & ~reached
            reached |= nxt
        return float(G.logged[reached].mean()), int(reached.sum())
    A = G.A.tocoo()
    dl = np.full(n, -1, dtype=np.int64)
    np.maximum.at(dl, rows, deadline)
    for _ in range(depth - 1):
        new = dl.copy()
        m = (dl[A.row] >= 0) & (G.year[A.col] <= dl[A.row])
        np.maximum.at(new, A.col[m], dl[A.row[m]])
        dl = new
    need = dl >= 0
    ok = G.logged & (G.upto >= dl)
    return float(ok[need].mean()), int(need.sum())


# ================================================================ features
def _drop(M, keep_entries):
    M.data[~keep_entries] = 0
    M.eliminate_zeros()
    return M


def hop_layers(G, rows, deadline, D, mode, channel):
    """Per row: layers N_1..N_D (c x n). reach: binary, minimum distance h. paths: walk counts."""
    c = len(rows)
    S = sp.csr_matrix((np.ones(c, dtype=np.float32), (np.arange(c), rows)), shape=(c, G.n))
    reach, front, out = S.copy(), S, []
    for _ in range(D):
        nxt = (front @ G.A).tocsr()
        r = np.repeat(np.arange(c), np.diff(nxt.indptr))
        keep = nxt.indices != rows[r]                        # no self (citation cycles)
        if channel == "cites":
            keep &= G.year[nxt.indices] <= deadline[r]       # fixed exposure window, every hop
        nxt = _drop(nxt, keep)
        if mode == "reach":
            nxt.data[:] = 1
            nxt = (nxt - nxt.multiply(reach)).tocsr()
            nxt.eliminate_zeros()
            nxt.data[:] = 1
            reach = reach + nxt
        out.append(nxt)
        front = nxt
    return out


def chunks(n, size):
    for i in range(0, n, size):
        yield slice(i, min(n, i + size))


def document_frequencies(G, rows, deadline, D, mode, channel, chunk):
    df = np.zeros((D, G.n), dtype=np.int64)
    per_layer = np.zeros((D, len(rows)), dtype=np.int64)
    for s in chunks(len(rows), chunk):
        L = hop_layers(G, rows[s], deadline[s], D, mode, channel)
        U = None
        for h in range(D):
            B = L[h].copy()
            B.data[:] = 1
            per_layer[h, s] = np.diff(B.indptr)
            U = B if U is None else ((U + B) > 0).astype(np.float32)
            df[h] += np.bincount(U.indices, minlength=G.n)
    return df, per_layer


def build_matrices(G, rows, deadline, depths, mode, channel, chunk, df, keep, alpha, balanced):
    """Core rows (non-empty depth-1 vector) and X_d (core x kept columns of depth d)."""
    D = max(depths)
    N = len(rows)
    # No "+1": a feature every work reaches (a universal classic) carries no information and
    # gets weight 0. With sklearn's smoothed "+1" it would weigh 1 and, in a small hop layer,
    # dominate that layer after balancing.
    idf = {d: np.log((1 + N) / (1 + df[d - 1])).astype(np.float32) for d in depths}
    cmap = {}
    for d in depths:
        m = np.full(G.n, -1, dtype=np.int64)
        m[keep[d]] = np.arange(keep[d].sum())
        cmap[d] = m
    parts = {d: [] for d in depths}
    core = []
    for s in chunks(len(rows), chunk):
        L = hop_layers(G, rows[s], deadline[s], D, mode, channel)
        rows_ok = None
        for d in sorted(depths):
            X = None
            for h in range(d):
                B = L[h].copy().astype(np.float32)
                B = _drop(B, keep[d][B.indices])
                if mode == "paths":
                    B.data = np.log1p(B.data)
                B.data *= idf[d][B.indices]
                if balanced:
                    B = _rownorm(B)
                if h:
                    B.data *= alpha ** h
                X = B if X is None else X + B
            X = _rownorm(X.tocsr())
            if rows_ok is None:          # the smallest depth requested defines the core
                rows_ok = np.diff(X.indptr) > 0
            X = X[rows_ok]
            X.indices = cmap[d][X.indices].astype(np.int32)
            X = sp.csr_matrix((X.data, X.indices, X.indptr), shape=(X.shape[0], int(keep[d].sum())))
            parts[d].append(X)
        core.append(np.arange(s.start, s.stop)[rows_ok])
    core = np.concatenate(core)
    return core, {d: sp.vstack(parts[d]).tocsr() for d in depths}


def _rownorm(M):
    M = M.tocsr()
    nrm = np.sqrt(np.asarray(M.multiply(M).sum(axis=1)).ravel())
    nrm[nrm == 0] = 1
    return sp.diags(1 / nrm).dot(M).tocsr().astype(np.float32)


def embed(X, dims, seed, n_iter=4, oversample=10):
    """Randomized truncated SVD, power iterations on the ROW side (X X^T, never formed).
    The faculty corpus has far fewer works (rows) than features (columns: up to millions of
    ancestors at depth 2), so every QR is on an n x l matrix and the column side is touched
    only by sparse products; ~5x faster than sklearn's TruncatedSVD on such shapes, same
    subspace. Returns unit-norm U*S rows (= TruncatedSVD.fit_transform, normalised), the share
    of ||X||_F^2 captured, the rank used, and the number of rows projected to zero."""
    n, m = X.shape
    k = int(min(dims, m - 1, n - 1))
    l = min(k + oversample, n, m)
    rng = np.random.default_rng(seed)
    X = X.astype(np.float32).tocsr()
    XT = X.T.tocsr()
    Q, _ = np.linalg.qr(X @ (XT @ rng.standard_normal((n, l)).astype(np.float32)))
    for _ in range(n_iter):
        Q, _ = np.linalg.qr(X @ (XT @ Q))
    B = np.asarray((XT @ Q).T, dtype=np.float64)          # l x m (dense, l small)
    Ub, s2, _ = np.linalg.svd(B @ B.T)                     # eigen-decomposition of B B^T
    s = np.sqrt(np.clip(s2[:k], 0, None))
    E = (Q @ Ub[:, :k]).astype(np.float32) * s.astype(np.float32)
    total = float(X.multiply(X).sum())
    nrm = np.linalg.norm(E, axis=1)
    zero = int((nrm == 0).sum())
    nrm[nrm == 0] = 1
    return E / nrm[:, None], float((s ** 2).sum() / total) if total else 0.0, k, zero


# ================================================================ kNN, communities
def knn(E, k, chunk=1024):
    n = E.shape[0]
    k = min(k, n - 1)
    idx = np.empty((n, k), dtype=np.int64)
    sim = np.empty((n, k), dtype=np.float32)
    dense = not sp.issparse(E)
    ET = E.T if dense else E.T.tocsc()
    for s in chunks(n, chunk):
        S = E[s] @ ET
        S = np.asarray(S.todense() if sp.issparse(S) else S, dtype=np.float32)
        S[np.arange(S.shape[0]), np.arange(s.start, s.stop)] = -np.inf
        part = np.argpartition(-S, k, axis=1)[:, :k] if k < n - 1 else np.argsort(-S, axis=1)[:, :k]
        idx[s] = part
        sim[s] = np.take_along_axis(S, part, axis=1)
    return idx, sim


def knn_overlap(a, b):
    """Mean Jaccard of each node's neighbour sets in two kNN results (same nodes, same k)."""
    n, k = a.shape
    ka = (np.arange(n)[:, None] * n + a).ravel()
    kb = (np.arange(n)[:, None] * n + b).ravel()
    inter = np.bincount(np.repeat(np.arange(n), k)[np.isin(ka, kb)], minlength=n)
    return float(np.mean(inter / (2 * k - inter)))


def knn_graph(idx, sim):
    n, k = idx.shape
    W = sp.csr_matrix((np.clip(sim.ravel(), 0, None), (np.repeat(np.arange(n), k), idx.ravel())), shape=(n, n))
    W = W.maximum(W.T).tocoo()
    m = (W.row < W.col) & (W.data > 0)
    return n, W.row[m], W.col[m], W.data[m].astype(np.float64)


class Partitioner:
    def __init__(self, graph, backend="auto", iterations=2):
        self.n, self.i, self.j, self.w = graph
        self.backend, self.iterations = backend, iterations
        if backend in ("auto", "leiden"):
            try:
                import igraph as ig
                import leidenalg  # noqa: F401
                g = ig.Graph(n=self.n, edges=np.column_stack([self.i, self.j]).tolist(), directed=False)
                g.es["weight"] = self.w.tolist()
                self.g, self.backend = g, "leiden"
            except ImportError:
                if backend == "leiden":
                    raise
                self.backend = "louvain-networkx"
        if self.backend == "louvain-networkx":
            import networkx as nx
            g = nx.Graph()
            g.add_nodes_from(range(self.n))
            g.add_weighted_edges_from(zip(self.i.tolist(), self.j.tolist(), self.w.tolist()))
            self.g = g

    def run(self, gamma, seed):
        if self.backend == "leiden":
            import leidenalg as la
            p = la.find_partition(self.g, la.RBConfigurationVertexPartition, weights="weight",
                                  resolution_parameter=gamma, seed=int(seed), n_iterations=self.iterations)
            return np.asarray(p.membership, dtype=np.int64)
        import networkx as nx
        lab = np.empty(self.n, dtype=np.int64)
        for c, nodes in enumerate(nx.community.louvain_communities(self.g, weight="weight", resolution=gamma, seed=int(seed))):
            lab[list(nodes)] = c
        return lab


def n_communities(lab, min_size):
    return int((np.bincount(lab) >= min_size).sum())


def tune_resolution(P, target, min_size, seed=0, iters=20):
    """Bisection on log(gamma) so that the number of communities of size >= min_size hits the
    target (tolerance 3%, at least 1). Returns (gamma, labels, K, trace)."""
    tol = max(1, round(0.03 * target))
    cache = {}

    def K(g):
        if g not in cache:
            lab = P.run(g, seed)
            cache[g] = (n_communities(lab, min_size), lab)
        return cache[g][0]

    lo, hi = 1e-2, 10.0
    for _ in range(8):
        if K(lo) <= target:
            break
        lo /= 10
    for _ in range(8):
        if K(hi) >= target:
            break
        hi *= 10
    best = min(cache, key=lambda g: abs(cache[g][0] - target))
    for _ in range(iters):
        if abs(cache[best][0] - target) <= tol:
            break
        mid = math.sqrt(lo * hi)
        k = K(mid)
        if abs(k - target) < abs(cache[best][0] - target):
            best = mid
        if k < target:
            lo = mid
        else:
            hi = mid
    trace = sorted((g, c[0]) for g, c in cache.items())
    return best, cache[best][1], cache[best][0], trace


def survival(a, b, min_size, thr=0.5):
    """Node-weighted share of a's communities (size >= min_size) whose best Jaccard match in b
    is >= thr, and the share of such communities."""
    sa, sb = np.bincount(a), np.bincount(b)
    C = sp.coo_matrix((np.ones(len(a)), (a, b)), shape=(len(sa), len(sb))).tocsr()
    C.sum_duplicates()
    Cc = C.tocoo()
    jac = Cc.data / (sa[Cc.row] + sb[Cc.col] - Cc.data)
    best = np.zeros(len(sa))
    np.maximum.at(best, Cc.row, jac)
    big = sa >= min_size
    alive = big & (best >= thr)
    return float(sa[alive].sum() / max(sa[big].sum(), 1)), float(alive.sum() / max(big.sum(), 1))


# ================================================================ professor-level
def qhat_groups(E, core_works, links, by_year):
    """Rao's quadratic entropy, unbiased U-statistic on unit vectors:
    Q = (2n/(n-1)) (1 - R^2), R = |mean vector|. Groups with n >= 2 only."""
    pos = {w: i for i, w in enumerate(core_works.tolist())}
    keys, gi, wi = {}, [], []
    for uid, w, y in links:
        i = pos.get(w)
        if i is None:
            continue
        key = (uid, y) if by_year else uid
        g = keys.setdefault(key, len(keys))
        gi.append(g)
        wi.append(i)
    if not keys:
        return {}
    M = sp.csr_matrix((np.ones(len(gi), dtype=np.float32), (gi, wi)), shape=(len(keys), len(core_works)))
    M.data[:] = 1
    M.sum_duplicates()
    M.data[:] = 1
    n = np.asarray(M.sum(axis=1)).ravel()
    S = M @ E
    if sp.issparse(S):
        sq = np.asarray(S.multiply(S).sum(axis=1)).ravel()
    else:
        sq = (np.asarray(S) ** 2).sum(axis=1)
    out = {}
    for key, g in keys.items():
        if n[g] >= 2:
            R2 = min(1.0, sq[g] / n[g] ** 2)
            out[key] = (int(n[g]), float(2 * n[g] / (n[g] - 1) * (1 - R2)))
    return out


def spearman(x, y):
    from scipy.stats import spearmanr
    if len(x) < 3:
        return None
    r = spearmanr(x, y).statistic
    return None if r is None or np.isnan(r) else float(r)


# ================================================================ run
def cmd_run(a):
    from sklearn.metrics import adjusted_mutual_info_score as ami, adjusted_rand_score as ari
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    depths = sorted({int(x) for x in a.depths.split(",")})
    targets = sorted({int(x) for x in a.target_k.split(",")})
    db = connect(a.db, readonly=True)
    store = connect(a.store, readonly=True) if a.store else db
    focal, frep = load_focal(db, a.works_sql)
    say(f"focal works {len(focal):,}", frep)
    G = load_graph(store, a.channel, focal)
    say(f"graph: {G.n:,} nodes, {G.A.nnz:,} {a.channel} edges")
    rows, deadline = eligible_rows(G, a.channel, focal, a.window, a.last_complete_year)
    if a.sample_works and a.sample_works < len(rows):
        pick = np.sort(np.random.default_rng(a.seed).choice(len(rows), a.sample_works, replace=False))
        rows, deadline = rows[pick], deadline[pick]
    say(f"eligible focal rows {len(rows):,}")
    if len(rows) < 10:
        sys.exit("fewer than 10 eligible focal works; fetch the channel first (citation_layers.py)")

    summary = {"params": {k: v for k, v in vars(a).items() if k != "func"}, "focal": frep,
               "eligible": int(len(rows)), "coverage": {}, "skipped": {}}
    usable = []
    for d in depths:
        cov, need = coverage(G, a.channel, rows, deadline, d)
        summary["coverage"][d] = {"logged_share": cov, "nodes_needed": need}
        say(f"depth {d}: neighbours needed for {need:,} nodes, logged {cov:.1%}")
        if cov < a.min_coverage and not a.allow_partial:
            summary["skipped"][d] = (f"coverage {cov:.1%} < {a.min_coverage:.0%}: fetch layer {d} "
                                     f"(citation_layers.py fetch --channel {a.channel} --layer {d})")
            continue
        usable.append(d)
    if not usable:
        _write(out, summary)
        sys.exit("no depth has enough coverage: " + json.dumps(summary["skipped"]))
    D = max(usable)

    say("pass 1: document frequencies")
    df, per_layer = document_frequencies(G, rows, deadline, D, a.mode, a.channel, a.chunk)
    N = len(rows)
    keep, est = {}, {}
    for d in usable:
        k = (df[d - 1] >= a.min_df) & (df[d - 1] <= a.max_df * N)
        keep[d] = k
        est[d] = int(df[d - 1][k].sum())
    budget = a.max_gb * 1e9 / 8          # float32 value + int32 index per stored entry
    while usable and sum(est[d] for d in usable) > budget:
        d = usable.pop()
        summary["skipped"][d] = (f"memory: ~{est[d] * 8 / 1e9:.1f} GB of features; raise --max-gb, "
                                 "lower --max-df, or --sample-works")
    if not usable:
        _write(out, summary)
        sys.exit("memory budget too small for depth 1")
    summary["features"] = {d: {"kept_columns": int(keep[d].sum()), "entries": est[d],
                               "median_hop_layer_sizes": [int(np.median(per_layer[h])) for h in range(d)]}
                           for d in usable}
    say("features:", summary["features"])

    say("pass 2: TF-IDF matrices")
    core, X = build_matrices(G, rows, deadline, usable, a.mode, a.channel, a.chunk, df, keep, a.alpha,
                             a.layer_weight == "balanced")
    core_works = G.ids[rows[core]]
    summary["core"] = int(len(core))
    summary["core_dropped_empty_depth1"] = int(N - len(core))
    say(f"core works {len(core):,} (dropped {N - len(core):,} with an empty depth-{min(usable)} vector)")

    # Two replicates per depth: A (SVD seed s, Leiden seeds 0..R-1) and B (SVD seed s+1, Leiden
    # seeds 1000..). Noise floors compare A with B of the SAME depth; depth comparisons compare
    # A of one depth with B of the other (and vice versa). Both therefore differ in every random
    # choice, so a floor and a between-depth value are commensurate. (Comparing depths under a
    # shared SVD seed would let the shared random projection inflate their agreement.)
    emb, info = {"A": {}, "B": {}}, {}
    for d in usable:
        if a.embed == "svd":
            emb["A"][d], ev, k, zero = embed(X[d], a.dims, a.seed)
            emb["B"][d], _, _, _ = embed(X[d], a.dims, a.seed + 1)
            info[d] = {"dims": k, "captured_energy": ev, "zero_rows": zero}
        else:
            emb["A"][d] = emb["B"][d] = X[d]
            info[d] = {"dims": int(X[d].shape[1]), "captured_energy": 1.0, "zero_rows": 0}
        say(f"embedding depth {d}:", info[d])
    summary["embedding"] = info

    say("kNN graphs")
    nn = {r: {d: knn(emb[r][d], a.knn) for d in usable} for r in "AB"}
    over = {}
    for i, d1 in enumerate(usable):
        over[(d1, d1)] = knn_overlap(nn["A"][d1][0], nn["B"][d1][0])
        for d2 in usable[i + 1:]:
            over[(d1, d2)] = (knn_overlap(nn["A"][d1][0], nn["B"][d2][0]) +
                              knn_overlap(nn["B"][d1][0], nn["A"][d2][0])) / 2
    summary["knn_overlap"] = {f"{x}-{y}": v for (x, y), v in over.items()}
    say("kNN overlap (diagonal = floor):", summary["knn_overlap"])

    ref = load_ref_labels(db, a.labels_sql, core_works) if a.labels_sql else None
    parts = {}
    summary["communities"] = {}
    P = {r: {d: Partitioner(knn_graph(*nn[r][d]), a.backend, a.leiden_iterations) for d in usable} for r in "AB"}
    for K in targets:
        res = {"depth": {}, "ami": {}, "ari": {}, "survival": {}}
        for d in usable:
            gamma, lab0, k0, trace = tune_resolution(P["A"][d], K, a.min_size, seed=0)
            labs = {"A": [lab0] + [P["A"][d].run(gamma, s) for s in range(1, a.seeds)],
                    "B": [P["B"][d].run(gamma, 1000 + s) for s in range(a.seeds)]}
            parts[(K, d)] = labs
            sizes = np.bincount(lab0)
            floor = [ami(x, y) for x in labs["A"] for y in labs["B"]]
            sf = survival(labs["A"][0], labs["B"][0], a.min_size)
            res["depth"][d] = {
                "gamma": gamma, "communities": k0, "all_labels": int(len(sizes)),
                "communities_B": [n_communities(x, a.min_size) for x in labs["B"]],
                "target_reached": abs(k0 - K) <= max(1, round(0.03 * K)),
                "largest_share": float(sizes.max() / len(lab0)),
                "fragment_share": float(sizes[sizes < a.min_size].sum() / len(lab0)),
                "ami_floor": _ms(floor), "survival_floor": sf[0], "bisection": trace,
                "ami_vs_reference": (_ms([ami(ref[0][ref[1]], x[ref[1]]) for x in labs["A"]])
                                     if ref is not None else None)}
            say(f"K={K} depth {d}: gamma {gamma:.4g}, {k0} communities, AMI floor {_ms(floor)}")
        for i, d1 in enumerate(usable):
            for d2 in usable[i + 1:]:
                L1, L2 = parts[(K, d1)], parts[(K, d2)]
                pairs = [(x, y) for x in L1["A"] for y in L2["B"]] + [(x, y) for x in L1["B"] for y in L2["A"]]
                res["ami"][f"{d1}-{d2}"] = _ms([ami(x, y) for x, y in pairs])
                res["ari"][f"{d1}-{d2}"] = _ms([ari(x, y) for x, y in pairs])
                fw = survival(L1["A"][0], L2["B"][0], a.min_size)
                bw = survival(L2["A"][0], L1["B"][0], a.min_size)
                res["survival"][f"{d1}-{d2}"] = {"nodes_fwd": fw[0], "communities_fwd": fw[1],
                                                 "nodes_bwd": bw[0], "communities_bwd": bw[1]}
                say(f"K={K} depth {d1} vs {d2}: AMI {res['ami'][f'{d1}-{d2}']}, survival {fw[0]:.1%}/{bw[0]:.1%}")
        summary["communities"][K] = res

    say("professor-level Q-hat")
    links = load_links(db, a.links_sql)
    summary["professors"] = prof = {}
    qrows = {}
    for by_year, name in ((False, "pooled"), (True, "person_year")):
        q = {d: qhat_groups(emb["A"][d], core_works, links, by_year) for d in usable}
        groups = sorted(set.intersection(*(set(q[d]) for d in usable)), key=str)
        prof[name] = {"groups_n_ge_2": len(groups),
                      "median_qhat": {d: (float(np.median([q[d][g][1] for g in groups])) if groups else None) for d in usable},
                      "spearman": {}}
        for i, d1 in enumerate(usable):
            for d2 in usable[i + 1:]:
                prof[name]["spearman"][f"{d1}-{d2}"] = spearman([q[d1][g][1] for g in groups],
                                                                [q[d2][g][1] for g in groups])
        if by_year:
            have = defaultdict(int)
            pos = set(core_works.tolist())
            for uid, w, y in links:
                if w in pos:
                    have[(uid, y)] += 1
            prof[name]["share_person_years_n_ge_2"] = (sum(v >= 2 for v in have.values()) / len(have)) if have else None
        else:
            qrows = {g: [q[d][g] for d in usable] for g in groups}
    say("professors:", json.dumps(prof, default=str))

    np.savez_compressed(out / "partitions.npz", works=core_works, depths=np.array(usable),
                        **{f"K{K}_d{d}": np.vstack(parts[(K, d)]["A"] + parts[(K, d)]["B"]) for (K, d) in parts})
    with open(out / "professor_qhat.csv", "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["professor_uid", "n_core_works"] + [f"qhat_d{d}" for d in usable])
        for g, vals in qrows.items():
            w.writerow([g, vals[0][0]] + [f"{v[1]:.6f}" for v in vals])
    if a.save_embeddings and a.embed == "svd":
        for d in usable:
            np.save(out / f"embedding_d{d}.npy", emb["A"][d])
    summary["usable_depths"] = usable
    for con in {id(db): db, id(store): store}.values():
        con.close()
    _write(out, summary)
    (out / "report.md").write_text(report(summary), encoding="utf-8")
    say(f"wrote {out}/summary.json, report.md, partitions.npz, professor_qhat.csv")


def _ms(v):
    return {"mean": float(np.mean(v)), "sd": float(np.std(v)), "n": len(v)} if v else None


def _write(out, summary):
    (out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1, default=str), encoding="utf-8")


def load_ref_labels(db, sql, core_works):
    """(work_id, label) -> (codes per core row, mask of rows with a label). Majority label."""
    votes = defaultdict(lambda: defaultdict(int))
    try:
        for w, lab in db.execute(sql):
            n = wid(w)
            if n is not None and lab is not None:
                votes[n][str(lab)] += 1
    except Exception as e:
        say("reference labels unavailable:", e)
        return None
    labels = [max(votes[w].items(), key=lambda kv: kv[1])[0] if w in votes else None for w in core_works.tolist()]
    mask = np.array([x is not None for x in labels])
    if mask.sum() < 10:
        return None
    _, codes = np.unique(np.array([x or "" for x in labels]), return_inverse=True)
    return codes, mask


def load_links(db, sql):
    out = []
    for uid, w, y in db.execute(sql):
        n = wid(w)
        if n is not None:
            out.append((str(uid), n, None if y is None else int(y)))
    return out


# ================================================================ report
def _fmt(x, pct=False):
    if x is None:
        return "–"
    if isinstance(x, dict):
        return f"{x['mean']:.3f} ± {x['sd']:.3f}"
    return f"{x:.1%}" if pct else f"{x:.3f}"


def report(s):
    p, U = s["params"], s["usable_depths"]
    L = [f"# 깊이 비교 — {p['channel']} 채널", "",
         f"- 노드: 교수 논문 core {s['core']:,}편 (eligible {s['eligible']:,}, depth-{min(U)} 벡터가 빈 "
         f"{s['core_dropped_empty_depth1']:,}편 제외). 모든 깊이에서 같은 노드.",
         f"- 특징: {p['mode']}, 층 가중 {p['layer_weight']}, α={p['alpha']}, min_df={p['min_df']}, "
         f"max_df={p['max_df']}; 임베딩 {p['embed']} {p['dims']}차원; kNN k={p['knn']}; "
         f"Leiden seed {p['seeds']}개; 최소 커뮤니티 크기 {p['min_size']}", ""]
    if p["channel"] == "cites":
        L.insert(3, f"- 피인용 창: 출판 후 {p['window']}년, 모든 홉에 적용. year + {p['window']} ≤ {p['last_complete_year']} 인 논문만.")
    if s["skipped"]:
        L += ["**제외된 깊이**", ""] + [f"- depth {d}: {why}" for d, why in s["skipped"].items()] + [""]
    L += ["## 1. 커버리지와 특징", "", "| depth | 이웃이 필요한 노드 | 수집됨 | 유지 열 | 항목 수 | 홉별 이웃 수 중앙값 | SVD 포착 에너지 |",
          "|---|---|---|---|---|---|---|"]
    for d in U:
        c, f, e = s["coverage"][d], s["features"][d], s["embedding"][d]
        L.append(f"| {d} | {c['nodes_needed']:,} | {c['logged_share']:.1%} | {f['kept_columns']:,} | {f['entries']:,} | "
                 f"{', '.join(map(str, f['median_hop_layer_sizes']))} | {e['captured_energy']:.1%} |")
    L += ["", "## 2. kNN 이웃 보존 (분할 없음, 해상도 무관)", "",
          "대각선 = 같은 깊이, 다른 SVD seed(잡음 바닥). 비대각선도 서로 다른 seed끼리 잰다. 비대각선이 대각선과 비슷하면 깊이가 이웃을 바꾸지 않는다.", "",
          "| | " + " | ".join(f"d{d}" for d in U) + " |", "|---" * (len(U) + 1) + "|"]
    for d1 in U:
        row = []
        for d2 in U:
            k = f"{min(d1, d2)}-{max(d1, d2)}"
            row.append(_fmt(s["knn_overlap"].get(k)))
        L.append(f"| d{d1} | " + " | ".join(row) + " |")
    for K, r in s["communities"].items():
        L += ["", f"## 3. 커뮤니티 K = {K}", "", "| depth | γ | K (도달) | 최대 비율 | 조각 비율 | 잡음 바닥 AMI | 잡음 바닥 생존 | AMI vs subfield (기술용) |",
              "|---|---|---|---|---|---|---|---|"]
        for d in U:
            x = r["depth"][d]
            hit = "" if x["target_reached"] else " ✗"
            L.append(f"| {d} | {x['gamma']:.4g} | {x['communities']}{hit} | {x['largest_share']:.1%} | {x['fragment_share']:.1%} | "
                     f"{_fmt(x['ami_floor'])} | {x['survival_floor']:.1%} | {_fmt(x['ami_vs_reference'])} |")
        if r["ami"]:
            L += ["", "| 쌍 | AMI | ARI | 생존(노드, →) | 생존(노드, ←) | 생존(커뮤니티, →) |", "|---|---|---|---|---|---|"]
            for k in r["ami"]:
                v = r["survival"][k]
                L.append(f"| {k} | {_fmt(r['ami'][k])} | {_fmt(r['ari'][k])} | {v['nodes_fwd']:.1%} | {v['nodes_bwd']:.1%} | "
                         f"{v['communities_fwd']:.1%} |")
    L += ["", "## 4. 교수 수준 결론이 바뀌는가 (Rao Q̂, n ≥ 2)", "",
          "| 단위 | 집단 수 | " + " | ".join(f"Q̂ 중앙값 d{d}" for d in U) + " | Spearman |", "|---" * (len(U) + 3) + "|"]
    for name, x in s["professors"].items():
        sp_ = ", ".join(f"{k}: {_fmt(v)}" for k, v in x["spearman"].items()) or "–"
        L.append(f"| {name} | {x['groups_n_ge_2']:,} | " + " | ".join(_fmt(x['median_qhat'][d]) for d in U) + f" | {sp_} |")
    py = s["professors"].get("person_year", {}).get("share_person_years_n_ge_2")
    if py is not None:
        L += ["", f"core 논문이 있는 교수-연도 중 2편 이상인 비율: {py:.1%} (낮으면 2–3년 창으로)"]
    L += ["", "판독 규칙은 README.md §판독 규칙. 수치는 사전에 정한 규칙으로만 읽는다.", ""]
    return "\n".join(L)


# ================================================================ compare (cross-channel)
def cmd_compare(a):
    from sklearn.metrics import adjusted_mutual_info_score as ami
    A, B = Path(a.run_a), Path(a.run_b)
    pa, pb = np.load(A / "partitions.npz"), np.load(B / "partitions.npz")
    wa, wb = pa["works"], pb["works"]
    common, ia, ib = np.intersect1d(wa, wb, return_indices=True)
    out = {"common_works": int(len(common)), "a": str(A), "b": str(B), "ami": {}}
    if len(common) < 10:
        sys.exit("fewer than 10 common works")
    Ks = sorted({k.split("_")[0] for k in pa.files if k.startswith("K")} & {k.split("_")[0] for k in pb.files if k.startswith("K")})
    for K in Ks:
        for ka in sorted(k for k in pa.files if k.startswith(K + "_")):
            for kb in sorted(k for k in pb.files if k.startswith(K + "_")):
                la, lb = pa[ka][:, ia], pb[kb][:, ib]
                vals = [ami(x, y) for x in la for y in lb]
                out["ami"][f"{ka} vs {kb}"] = _ms(vals)
    qa, qb = _read_q(A / "professor_qhat.csv"), _read_q(B / "professor_qhat.csv")
    common_p = sorted(set(qa) & set(qb))
    out["professors_common"] = len(common_p)
    out["spearman_qhat"] = {}
    if common_p:
        for ca in qa[common_p[0]]:
            for cb in qb[common_p[0]]:
                out["spearman_qhat"][f"a.{ca} vs b.{cb}"] = spearman([qa[p][ca] for p in common_p],
                                                                     [qb[p][cb] for p in common_p])
    Path(a.out).mkdir(parents=True, exist_ok=True)
    (Path(a.out) / "compare.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(json.dumps(out, indent=1))


def _read_q(path):
    out = {}
    with open(path) as fh:
        for r in csv.DictReader(fh):
            out[r["professor_uid"]] = {k: float(v) for k, v in r.items() if k.startswith("qhat_")}
    return out


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--db", required=True)
    r.add_argument("--store", help="SQLite with cd_* tables (default: --db)")
    r.add_argument("--channel", choices=("refs", "cites"), required=True)
    r.add_argument("--depths", default="1,2,3")
    r.add_argument("--out", required=True)
    r.add_argument("--works-sql", default=DEFAULT_WORKS_SQL)
    r.add_argument("--links-sql", default=DEFAULT_LINKS_SQL, help="SELECT professor_uid, work_id, publication_year")
    r.add_argument("--labels-sql", default=DEFAULT_LABELS_SQL, help="SELECT work_id, label (descriptive reference); '' to skip")
    r.add_argument("--window", type=int, default=3)
    r.add_argument("--last-complete-year", type=int, default=2025)
    r.add_argument("--mode", choices=("reach", "paths"), default="reach")
    r.add_argument("--layer-weight", choices=("balanced", "raw"), default="balanced")
    r.add_argument("--alpha", type=float, default=1.0, help="weight of hop h is alpha^(h-1)")
    r.add_argument("--min-df", type=int, default=2)
    r.add_argument("--max-df", type=float, default=1.0, help="drop features in more than this share of works")
    r.add_argument("--embed", choices=("svd", "none"), default="svd")
    r.add_argument("--dims", type=int, default=128)
    r.add_argument("--knn", type=int, default=20)
    r.add_argument("--target-k", default="30,60,120")
    r.add_argument("--min-size", type=int, default=5)
    r.add_argument("--seeds", type=int, default=5)
    r.add_argument("--seed", type=int, default=0)
    r.add_argument("--backend", choices=("auto", "leiden", "louvain-networkx"), default="auto")
    r.add_argument("--leiden-iterations", type=int, default=2,
                   help="leidenalg default 2; -1 iterates to convergence (slow when gamma fragments the graph)")
    r.add_argument("--min-coverage", type=float, default=0.98)
    r.add_argument("--allow-partial", action="store_true")
    r.add_argument("--max-gb", type=float, default=6.0)
    r.add_argument("--chunk", type=int, default=1000)
    r.add_argument("--sample-works", type=int)
    r.add_argument("--save-embeddings", action="store_true")
    r.set_defaults(func=cmd_run)
    c = sub.add_parser("compare", help="cross-channel agreement of two runs (e.g. refs vs cites)")
    c.add_argument("run_a")
    c.add_argument("run_b")
    c.add_argument("--out", required=True)
    c.set_defaults(func=cmd_compare)
    a = p.parse_args(argv)
    a.func(a)


if __name__ == "__main__":
    main()
