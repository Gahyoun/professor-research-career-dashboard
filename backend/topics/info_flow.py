#!/usr/bin/env python3
"""Topic merge / diverge between adjacent time windows, in bits.

Papers of one researcher are binned into windows of ``width`` years. For each pair of
adjacent non-empty windows (t, t+1) a joint distribution P(K_t, K_{t+1}) over topics is
built from bibliographic coupling (cosine of reference sets):

  * every paper q in t+1 carries unit mass, split over source topics a in proportion to
    sum_{p in a} cos(p, q). A paper with zero coupling to window t goes to source ∅ (birth).
  * every paper p in t with zero coupling to window t+1 adds unit mass to (k_p, ∅) (ending).

From the joint:
  diverge     H(K_{t+1} | K_t)   spread of successors given a source topic
  merge       H(K_t | K_{t+1})   spread of sources given a successor topic
  continuity  I(K_t ; K_{t+1})   structure carried over; NMI = 2I / (H_t + H_{t+1})
plus the per-window diversity H(K_t), drift JSD(P_t || P_{t+1}) of paper-count shares and
the birth share P(∅ → ·).

Normalised forms divide by the marginal: diverge / H(K_{t+1}) and merge / H(K_t) are the
shares of uncertainty left after knowing the other side (0 = determined, 1 = independent).

Entropies use the Miller–Madow correction (windows hold 10–30 papers; plug-in entropy is
biased low). Uncertainty: bootstrap over papers within each window. Null: topic labels
are permuted among papers inside each window, so both windows keep their topic
composition and the coupling graph is untouched; only the link between a paper's
references and its topic label is broken. That is the finite-size baseline of every
measure at that composition. Permuting years instead mixes topics into every window and
inflates H(K_t), so its I is not comparable with the observed one.

Stdlib only — the data:test CI job installs no Python packages.

  python3 backend/topics/info_flow.py --alluvial DIR/alluvial.json --seeds DIR/seeds.json \
      --out DIR/info_flow.json [--width 3] [--null 200] [--boot 200]
"""
import argparse, hashlib, json, math, random
from collections import defaultdict

NONE = None  # the ∅ state (birth on the source side, ending on the target side)
LOG2 = math.log(2)
KEYS = ("diverge", "merge", "continuity", "diverge_norm", "merge_norm")


# ---------- entropies (bits) ----------

def entropy(masses, corrected=True):
    """Shannon entropy of a mass vector; Miller–Madow adds (m − 1) / (2N) nats."""
    masses = [m for m in masses if m > 0]
    total = sum(masses)
    if total <= 0:
        return 0.0
    h = -sum(m / total * math.log(m / total) for m in masses)
    if corrected:
        h += (len(masses) - 1) / (2 * total)
    return h / LOG2


def jsd(p, q):
    """Jensen–Shannon divergence (bits) between two count dicts; plug-in, in [0, 1]."""
    keys = set(p) | set(q)
    sp, sq = sum(p.values()), sum(q.values())
    if not sp or not sq:
        return None
    P = {k: p.get(k, 0) / sp for k in keys}
    Q = {k: q.get(k, 0) / sq for k in keys}
    M = {k: (P[k] + Q[k]) / 2 for k in keys}
    kl = lambda A: sum(A[k] * math.log2(A[k] / M[k]) for k in keys if A[k] > 0)
    return (kl(P) + kl(Q)) / 2


def joint_measures(joint):
    """{(a, b): mass} → diverge, merge, continuity, NMI and marginal entropies."""
    row, col = defaultdict(float), defaultdict(float)
    for (a, b), m in joint.items():
        row[a] += m
        col[b] += m
    h_ab = entropy(joint.values())
    h_a, h_b = entropy(row.values()), entropy(col.values())
    mi = max(0.0, h_a + h_b - h_ab)
    div, mer = max(0.0, h_ab - h_a), max(0.0, h_ab - h_b)
    return {"diverge": div, "merge": mer, "continuity": mi,
            "diverge_norm": min(1.0, div / h_b) if h_b > 0 else None, "merge_norm": min(1.0, mer / h_a) if h_a > 0 else None,
            "nmi": (2 * mi / (h_a + h_b)) if h_a + h_b > 0 else None, "h_from": h_a, "h_to": h_b,
            "mass": sum(joint.values())}


def conditional_rows(joint, axis):
    """Per-topic branching (axis=0: H(K_{t+1}|K_t=a)) or merging (axis=1: H(K_t|K_{t+1}=b))."""
    groups = defaultdict(dict)
    for (a, b), m in joint.items():
        key, other = (a, b) if axis == 0 else (b, a)
        groups[key][other] = groups[key].get(other, 0) + m
    return [[k, round(entropy(v.values(), corrected=False), 4), round(sum(v.values()), 3)]
            for k, v in sorted(groups.items(), key=lambda kv: (kv[0] is None, kv[0] if kv[0] is not None else 0))]


# ---------- coupling and transitions ----------

def coupling_table(refs):
    """refs: list of reference sets (one per paper) → {(i, j): cosine} for i < j, nonzero only."""
    owners = defaultdict(list)
    for i, rs in enumerate(refs):
        for r in rs:
            owners[r].append(i)
    shared = defaultdict(int)
    for idx in owners.values():
        for x in range(len(idx)):
            for y in range(x + 1, len(idx)):
                shared[(idx[x], idx[y])] += 1
    size = [len(rs) for rs in refs]
    return {k: n / math.sqrt(size[k[0]] * size[k[1]]) for k, n in shared.items()}


def transition_joint(src, dst, topic, cos):
    """src, dst: paper indices in windows t and t+1 → {(a, b): mass} with ∅ = None."""
    c = lambda i, j: cos.get((i, j) if i < j else (j, i), 0.0) if i != j else 1.0
    joint = defaultdict(float)
    linked_src = set()
    for q in dst:
        weights = defaultdict(float)
        for p in src:
            w = c(p, q)
            if w > 0:
                weights[topic[p]] += w
                linked_src.add(p)
        total = sum(weights.values())
        if total <= 0:
            joint[(NONE, topic[q])] += 1.0
        else:
            for a, w in weights.items():
                joint[(a, topic[q])] += w / total
    for p in src:
        if p not in linked_src:
            joint[(topic[p], NONE)] += 1.0
    return dict(joint)


def bin_windows(years, width, first=None):
    lo = first if first is not None else min(years)
    hi = max(years)
    return [(s, min(s + width - 1, hi)) for s in range(lo, hi + 1, width)]


def assign(years, wins):
    out = defaultdict(list)
    for i, y in enumerate(years):
        for w, (s, e) in enumerate(wins):
            if s <= y <= e:
                out[w].append(i)
                break
    return out


def pairs_of(members, n_windows):
    return [(w, w + 1) for w in range(n_windows - 1) if members.get(w) and members.get(w + 1)]


def summarise(rows, key):
    vals = [(r[key], r["mass"]) for r in rows if r.get(key) is not None]
    total = sum(m for _, m in vals)
    return round(sum(v * m for v, m in vals) / total, 4) if total else None


def analyse(years, topics, refs, width=3, n_null=200, n_boot=200, seed=0):
    """Core computation. years/topics/refs are per-paper lists of equal length."""
    if not years:
        return None
    rnd = random.Random(seed)
    cos = coupling_table([set(r) for r in refs])
    wins = bin_windows(years, width)
    members = assign(years, wins)
    pairs = pairs_of(members, len(wins))

    def measure(mem, w0, w1, labels):
        return joint_measures(transition_joint(mem[w0], mem[w1], labels, cos))

    def permuted(w0, w1):
        """Topic labels shuffled inside each window: composition and coupling graph kept."""
        labels = topics[:]
        for w in (w0, w1):
            vals = [labels[i] for i in members[w]]
            rnd.shuffle(vals)
            for i, v in zip(members[w], vals):
                labels[i] = v
        return labels

    rows = []
    for w0, w1 in pairs:
        joint = transition_joint(members[w0], members[w1], topics, cos)
        m = joint_measures(joint)
        null, boot = defaultdict(list), defaultdict(list)
        for _ in range(n_null):
            b = measure(members, w0, w1, permuted(w0, w1))
            for k in KEYS:
                if b[k] is not None:
                    null[k].append(b[k])
        for _ in range(n_boot):
            mem = {w0: [rnd.choice(members[w0]) for _ in members[w0]], w1: [rnd.choice(members[w1]) for _ in members[w1]]}
            b = measure(mem, w0, w1, topics)
            for k in KEYS:
                if b[k] is not None:
                    boot[k].append(b[k])
        count0 = defaultdict(int)
        count1 = defaultdict(int)
        for i in members[w0]:
            count0[topics[i]] += 1
        for i in members[w1]:
            count1[topics[i]] += 1
        births = sum(v for (a, _), v in joint.items() if a is NONE)
        endings = sum(v for (_, b), v in joint.items() if b is NONE)
        row = {"from": list(wins[w0]), "to": list(wins[w1]), "n_from": len(members[w0]), "n_to": len(members[w1]),
               "mass": round(m["mass"], 3), "nmi": None if m["nmi"] is None else round(m["nmi"], 4),
               "jsd": None if jsd(count0, count1) is None else round(jsd(count0, count1), 4),
               "birth_share": round(births / len(members[w1]), 4), "ending_share": round(endings / len(members[w0]), 4),
               "flows": [[a, b, round(v, 3)] for (a, b), v in sorted(joint.items(), key=lambda kv: -kv[1])],
               "branching": conditional_rows(joint, 0), "merging": conditional_rows(joint, 1),
               "sparse": min(len(members[w0]), len(members[w1])) < 5}
        for k in KEYS:
            if m[k] is None:
                row[k] = row[k + "_ci"] = row[k + "_null"] = row[k + "_z"] = None
                continue
            row[k] = round(m[k], 4)
            bs = sorted(boot[k])
            row[k + "_ci"] = [round(bs[int(0.025 * (len(bs) - 1))], 4), round(bs[int(0.975 * (len(bs) - 1))], 4)] if bs else None
            ns = null[k]
            if ns:
                mean = sum(ns) / len(ns)
                sd = math.sqrt(sum((x - mean) ** 2 for x in ns) / max(1, len(ns) - 1))
                row[k + "_null"] = [round(mean, 4), round(sd, 4)]
                row[k + "_z"] = round((m[k] - mean) / sd, 2) if sd > 1e-9 else None
            else:
                row[k + "_null"], row[k + "_z"] = None, None
        rows.append(row)

    windows = []
    for w, (s, e) in enumerate(wins):
        counts = defaultdict(int)
        for i in members.get(w, []):
            counts[topics[i]] += 1
        h = entropy(counts.values()) if counts else None
        windows.append({"start": s, "end": e, "n": len(members.get(w, [])),
                        "diversity": None if h is None else round(h, 4),
                        "effective_topics": None if h is None else round(2 ** h, 3)})
    excess = [(r["continuity"] - r["continuity_null"][0], r["mass"]) for r in rows if r["continuity_null"]]
    summary = {k: summarise(rows, k) for k in KEYS + ("nmi", "jsd")}
    summary["continuity_excess"] = round(sum(v * m for v, m in excess) / sum(m for _, m in excess), 4) if excess else None
    summary["birth_share"] = round(sum(r["birth_share"] * r["n_to"] for r in rows) / sum(r["n_to"] for r in rows), 4) if rows else None
    summary["transitions"] = len(rows)
    return {"estimator": "Miller–Madow, bits", "width": width, "null": {"kind": "within-window topic-label permutation", "n": n_null},
            "bootstrap": n_boot, "windows": windows, "transitions": rows, "summary": summary}


def stable_seed(key):
    return int(hashlib.sha256(str(key).encode()).hexdigest()[:8], 16)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--alluvial", required=True)
    p.add_argument("--seeds", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--width", type=int, default=3)
    p.add_argument("--null", type=int, default=200)
    p.add_argument("--boot", type=int, default=200)
    a = p.parse_args()
    A = json.load(open(a.alluvial, encoding="utf-8"))
    seeds = {w["id"]: w for w in json.load(open(a.seeds, encoding="utf-8"))["works"]}
    papers = [x for x in A["papers"] if x.get("year")]
    refs = [seeds.get(x["id"], {}).get("referenced_works") or [] for x in papers]
    out = analyse([x["year"] for x in papers], [x["topic"] for x in papers], refs,
                  width=a.width, n_null=a.null, n_boot=a.boot, seed=stable_seed(a.alluvial))
    with open(a.out, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=1)
    s = out["summary"] if out else {}
    print(f"{a.out}: {s.get('transitions', 0)} transitions · diverge {s.get('diverge')} · merge {s.get('merge')} · "
          f"continuity {s.get('continuity')} (excess over null {s.get('continuity_excess')}) bits")


if __name__ == "__main__":
    main()
