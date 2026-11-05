#!/usr/bin/env python3
"""One fixed-seed Louvain partition of ALL faculty works, from depth-1 citation neighbours
in both directions:

  up    references of the work            (cd_refs)
  down  works citing it within W years    (cd_citers; same window as the collector)

Each work's neighbour set is the union of the two, kept apart by channel (a paper that is
both cited by p and citing q is two different features). Two works are linked when they
share at least --min-shared neighbours; the weight is the Salton cosine
w_ij = c_ij / sqrt(|N_i| |N_j|) — the per-researcher dashboard rule
(build_release_topics.py), applied once to the whole faculty instead of per person.
Louvain (igraph multilevel; resolution 1.05, seed 4 by default, as the dashboard). Works
with no link are left unclustered (community -1).

  python3 -I faculty_louvain.py --db MAIN.sqlite --out runs/louvain
  python3 -I faculty_louvain.py --db MAIN.sqlite --channels refs --out runs/louvain_refs

Outputs: work_communities.csv, communities.csv, professor_communities.csv, summary.json,
report.md. The seed fixes the result; --stability-seeds reports how far other seeds land
(AMI), so the fixed partition is not mistaken for the only one.
"""
import argparse
import csv
import json
import random
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
import scipy.sparse as sp

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cdcommon import DEFAULT_LINKS_SQL, DEFAULT_WORKS_SQL, connect, load_focal, wid  # noqa: E402

DEFAULT_LABELS_SQL = ("SELECT work_id, subfield_name FROM work_authorship_evidence "
                      "WHERE subfield_name IS NOT NULL")
T0 = time.time()


def say(*x):
    print(f"[{time.time() - T0:7.1f}s]", *x, flush=True)


# ---------------------------------------------------------------- neighbour matrix
def neighbour_matrix(store, focal, channels, window):
    """Binary works x features matrix. Rows: focal works in id order. Columns: channel-tagged
    neighbours. Returns (works, X_by_channel {ch: csr}, row_logged {ch: bool array})."""
    works = np.array(sorted(focal), dtype=np.int64)
    pos = {w: i for i, w in enumerate(works.tolist())}
    year = np.array([focal[w] if focal[w] is not None else -1 for w in works.tolist()], dtype=np.int64)
    meta_year = dict(store.execute("SELECT work, year FROM cd_meta WHERE year IS NOT NULL"))
    for i, w in enumerate(works.tolist()):          # OpenAlex year, as the collector uses
        if w in meta_year:
            year[i] = meta_year[w]
    X, logged = {}, {}
    for ch in channels:
        lg = np.zeros(len(works), dtype=bool)
        for (w,) in store.execute("SELECT work FROM cd_log WHERE channel = ? AND status = 'ok'", (ch,)):
            i = pos.get(w)
            if i is not None:
                lg[i] = True
        rows, cols = [], []
        if ch == "refs":
            q = store.execute("SELECT src, dst FROM cd_refs")
            for src, dst in q:
                i = pos.get(src)
                if i is not None:
                    rows.append(i)
                    cols.append(dst)
        else:
            q = store.execute("SELECT c.dst, c.src, m.year FROM cd_citers c LEFT JOIN cd_meta m ON m.work = c.src")
            for dst, src, y in q:
                i = pos.get(dst)
                if i is not None and y is not None and year[i] >= 0 and y <= year[i] + window:
                    rows.append(i)
                    cols.append(src)
        cols = np.asarray(cols, dtype=np.int64)
        uniq, ci = np.unique(cols, return_inverse=True)
        M = sp.csr_matrix((np.ones(len(ci), dtype=np.float32), (np.asarray(rows, dtype=np.int64), ci)),
                          shape=(len(works), len(uniq)))
        M.sum_duplicates()
        M.data[:] = 1
        X[ch], logged[ch] = M, lg
    return works, year, X, logged


def coupling_edges(X, min_shared, chunk):
    """Upper-triangle pairs with c_ij >= min_shared over the union of channels; returns
    (i, j, c_total, c_by_channel {ch: array}, w) with the Salton cosine as weight."""
    chans = list(X)
    full = sp.hstack([X[c] for c in chans]).tocsr()
    deg = np.asarray(full.sum(axis=1)).ravel()
    FT = full.T.tocsr()
    parts_i, parts_j, parts_c = [], [], []
    parts_ch = {c: [] for c in chans}
    T = {c: X[c].T.tocsr() for c in chans}
    n = full.shape[0]
    for s in range(0, n, chunk):
        e = min(n, s + chunk)
        C = (full[s:e] @ FT).tocoo()
        r = C.row + s
        keep = (C.col > r) & (C.data >= min_shared)
        ii, jj, cc = r[keep], C.col[keep], C.data[keep]
        parts_i.append(ii.astype(np.int32))
        parts_j.append(jj.astype(np.int32))
        parts_c.append(cc.astype(np.float32))
        for c in chans:                              # channel split of the same pairs
            Cc = (X[c][s:e] @ T[c]).tocsr()
            parts_ch[c].append(np.asarray(Cc[ii - s, jj]).ravel().astype(np.float32))
    i = np.concatenate(parts_i) if parts_i else np.zeros(0, np.int32)
    j = np.concatenate(parts_j) if parts_j else np.zeros(0, np.int32)
    c = np.concatenate(parts_c) if parts_c else np.zeros(0, np.float32)
    by = {ch: (np.concatenate(v) if v else np.zeros(0, np.float32)) for ch, v in parts_ch.items()}
    w = c / np.sqrt(deg[i] * deg[j])
    return i, j, c, by, w, deg


# ---------------------------------------------------------------- Louvain
def louvain(n, i, j, w, resolution, seed, backend):
    """Membership array; -1 for works without any link."""
    lab = np.full(n, -1, dtype=np.int64)
    linked = np.zeros(n, dtype=bool)
    linked[i] = linked[j] = True
    if not linked.any():
        return lab, None
    if backend == "networkx":
        import networkx as nx
        G = nx.Graph()
        G.add_nodes_from(np.flatnonzero(linked).tolist())
        G.add_weighted_edges_from(zip(i.tolist(), j.tolist(), w.tolist()))
        com = nx.community.louvain_communities(G, weight="weight", seed=seed, resolution=resolution)
        q = nx.community.modularity(G, com, weight="weight", resolution=resolution)
        for k, nodes in enumerate(sorted(com, key=lambda c: (-len(c), min(c)))):
            lab[list(nodes)] = k
        return lab, float(q)
    import igraph as ig
    g = ig.Graph(n=n, edges=np.column_stack([i, j]).tolist(), directed=False)
    g.es["weight"] = w.astype(np.float64).tolist()
    random.seed(seed)                                # python-igraph draws from Python's RNG
    part = g.community_multilevel(weights="weight", resolution=resolution)
    mem = np.asarray(part.membership, dtype=np.int64)
    q = float(g.modularity(mem.tolist(), weights="weight", resolution=resolution))
    # relabel: largest community 0; isolated nodes -1
    sizes = Counter(mem[linked].tolist())
    order = {c: k for k, (c, _) in enumerate(sorted(sizes.items(), key=lambda kv: (-kv[1], kv[0])))}
    lab[linked] = [order[c] for c in mem[linked].tolist()]
    return lab, q


# ---------------------------------------------------------------- run
def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--db", required=True)
    p.add_argument("--store", help="SQLite with cd_* tables (default: --db)")
    p.add_argument("--out", required=True)
    p.add_argument("--channels", default="refs,cites", help="refs, cites, or refs,cites")
    p.add_argument("--window", type=int, default=3, help="citers within this many years after publication")
    p.add_argument("--works-sql", default=DEFAULT_WORKS_SQL)
    p.add_argument("--links-sql", default=DEFAULT_LINKS_SQL)
    p.add_argument("--labels-sql", default=DEFAULT_LABELS_SQL, help="(work_id, label) to describe communities; '' to skip")
    p.add_argument("--min-shared", type=int, default=2)
    p.add_argument("--resolution", type=float, default=1.05)
    p.add_argument("--seed", type=int, default=4)
    p.add_argument("--stability-seeds", default="0,1,2", help="extra seeds compared with the fixed one; '' to skip")
    p.add_argument("--backend", choices=("igraph", "networkx"), default="igraph")
    p.add_argument("--chunk", type=int, default=500)
    p.add_argument("--min-coverage", type=float, default=0.95)
    p.add_argument("--allow-partial", action="store_true")
    a = p.parse_args(argv)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    chans = [c.strip() for c in a.channels.split(",") if c.strip()]
    if not chans or set(chans) - {"refs", "cites"}:
        p.error("--channels takes refs and/or cites")

    db = connect(a.db, readonly=True)
    store = connect(a.store, readonly=True) if a.store else db
    focal, frep = load_focal(db, a.works_sql)
    say(f"focal works {len(focal):,}", frep)
    works, year, X, logged = neighbour_matrix(store, focal, chans, a.window)
    n = len(works)
    cov = {c: float(logged[c].mean()) for c in chans}
    say("collected share per channel:", {c: f"{v:.1%}" for c, v in cov.items()})
    bad = {c: v for c, v in cov.items() if v < a.min_coverage}
    if bad and not a.allow_partial:
        sys.exit(f"channels not collected enough {bad}: run citation_layers.py fetch --layer 1 for them "
                 "(cites: add --include-open-windows), or pass --allow-partial and report it")

    say("coupling pairs")
    i, j, c, by, w, deg = coupling_edges(X, a.min_shared, a.chunk)
    say(f"{len(i):,} links (c_ij >= {a.min_shared}) among {n:,} works")
    lab, q = louvain(n, i, j, w, a.resolution, a.seed, a.backend)
    lab2, _ = louvain(n, i, j, w, a.resolution, a.seed, a.backend)
    deterministic = bool(np.array_equal(lab, lab2))
    sizes = Counter(lab[lab >= 0].tolist())
    say(f"Louvain seed {a.seed}: {len(sizes):,} communities, modularity {q}, unclustered {int((lab < 0).sum()):,}, "
        f"rerun identical: {deterministic}")

    stab = {}
    if a.stability_seeds.strip():
        from sklearn.metrics import adjusted_mutual_info_score as ami
        m = lab >= 0
        for s in [int(x) for x in a.stability_seeds.split(",") if x.strip()]:
            other, _ = louvain(n, i, j, w, a.resolution, s, a.backend)
            stab[s] = {"ami": float(ami(lab[m], other[m])), "communities": len(set(other[other >= 0].tolist()))}
        say("other seeds:", stab)

    # descriptions
    labels = defaultdict(Counter)
    if a.labels_sql:
        pos = {wk: k for k, wk in enumerate(works.tolist())}
        try:
            for wk, l in db.execute(a.labels_sql):
                k = pos.get(wid(wk))
                if k is not None and l is not None:
                    labels[k][str(l)] += 1
        except Exception as e:
            say("labels unavailable:", e)
    work_label = {k: cnt.most_common(1)[0][0] for k, cnt in labels.items()}
    links = []
    pos = {wk: k for k, wk in enumerate(works.tolist())}
    for uid, wk, _ in db.execute(a.links_sql):
        k = pos.get(wid(wk))
        if k is not None:
            links.append((str(uid), k))
    prof_of = defaultdict(set)
    for uid, k in links:
        prof_of[k].add(uid)

    with open(out / "work_communities.csv", "w", newline="") as fh:
        wr = csv.writer(fh)
        wr.writerow(["work_id", "community", "community_size", "year", "degree_features"])
        for k, wk in enumerate(works.tolist()):
            wr.writerow([f"W{wk}", int(lab[k]), sizes.get(int(lab[k]), 0) if lab[k] >= 0 else 0,
                         int(year[k]) if year[k] >= 0 else "", int(deg[k])])
    comm_rows = []
    members = defaultdict(list)
    for k in range(n):
        members[int(lab[k])].append(k)
    for cid in sorted(members, key=lambda x: (x < 0, -len(members[x]), x)):
        ks = members[cid]
        lab_c = Counter(work_label[k] for k in ks if k in work_label)
        tot = sum(lab_c.values())
        profs = set().union(*(prof_of[k] for k in ks)) if ks else set()
        ys = [int(year[k]) for k in ks if year[k] >= 0]
        comm_rows.append({
            "community": cid, "size": len(ks), "professors": len(profs),
            "year_median": int(np.median(ys)) if ys else "",
            "year_range": f"{min(ys)}-{max(ys)}" if ys else "",
            "top_labels": "; ".join(f"{l} {v / tot:.0%}" for l, v in lab_c.most_common(3)) if tot else ""})
    with open(out / "communities.csv", "w", newline="") as fh:
        wr = csv.DictWriter(fh, fieldnames=list(comm_rows[0]))
        wr.writeheader()
        wr.writerows(comm_rows)
    pc = Counter((uid, int(lab[k])) for uid, k in links)
    with open(out / "professor_communities.csv", "w", newline="") as fh:
        wr = csv.writer(fh)
        wr.writerow(["professor_uid", "community", "n_works"])
        for (uid, cid), v in sorted(pc.items()):
            wr.writerow([uid, cid, v])

    tot_c = float(c.sum()) or 1.0
    size_list = sorted(sizes.values(), reverse=True)
    summary = {
        "params": {k: v for k, v in vars(a).items()},
        "focal": frep, "works": n, "collected_share": cov,
        "features": {ch: int(X[ch].shape[1]) for ch in chans},
        "median_neighbours": {ch: float(np.median(np.diff(X[ch].indptr))) for ch in chans},
        "works_without_neighbours": int((deg == 0).sum()),
        "links": int(len(i)),
        "shared_neighbour_share_by_channel": {ch: float(by[ch].sum() / tot_c) for ch in chans},
        "links_only_through": {ch: int(((by[ch] >= a.min_shared) & (c - by[ch] == 0)).sum()) for ch in chans},
        "communities": len(sizes), "modularity": q, "unclustered": int((lab < 0).sum()),
        "largest_sizes": size_list[:10],
        "communities_ge_10": sum(1 for s in size_list if s >= 10),
        "share_in_top10": float(sum(size_list[:10]) / max(1, (lab >= 0).sum())),
        "rerun_identical": deterministic, "other_seeds": stab,
    }
    (out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    (out / "report.md").write_text(report(summary, comm_rows), encoding="utf-8")
    say(f"wrote {out}/work_communities.csv, communities.csv, professor_communities.csv, summary.json, report.md")


def report(s, rows):
    p = s["params"]
    L = [f"# 전체 교수 Louvain 분할 ({', '.join(p['channels'].split(','))}, depth 1)", "",
         f"- 노드: 교수 논문 {s['works']:,}편. 이웃: " +
         ", ".join(f"{ch} 수집 {v:.1%}, 중앙값 {s['median_neighbours'][ch]:.0f}개" for ch, v in s["collected_share"].items()),
         f"- 링크: 공유 이웃 ≥ {p['min_shared']} → {s['links']:,}개, 가중치 Salton 코사인. 공유 이웃 중 채널 비중: " +
         ", ".join(f"{k} {v:.1%}" for k, v in s["shared_neighbour_share_by_channel"].items()),
         f"- Louvain: resolution {p['resolution']}, seed {p['seed']} ({p['backend']}). 같은 seed 재실행 동일: "
         f"{'예' if s['rerun_identical'] else '아니오'}",
         f"- 결과: 커뮤니티 {s['communities']:,}개 (10편 이상 {s['communities_ge_10']:,}개), modularity "
         f"{s['modularity']:.3f}, 미분류(링크 없음) {s['unclustered']:,}편, 상위 10개가 {s['share_in_top10']:.1%}", ""]
    if s["other_seeds"]:
        L += ["다른 seed와의 일치 (고정 seed 결과가 유일한 답이 아님을 보이기 위한 참고):", "",
              "| seed | AMI | 커뮤니티 수 |", "|---|---|---|"]
        L += [f"| {k} | {v['ami']:.3f} | {v['communities']:,} |" for k, v in s["other_seeds"].items()] + [""]
    L += ["## 상위 커뮤니티", "", "| id | 논문 | 교수 | 연도 중앙값 | 연도 범위 | 주요 subfield |", "|---|---|---|---|---|---|"]
    for r in rows[:40]:
        L.append(f"| {r['community']} | {r['size']:,} | {r['professors']:,} | {r['year_median']} | {r['year_range']} | {r['top_labels']} |")
    return "\n".join(L) + "\n"


if __name__ == "__main__":
    main()
