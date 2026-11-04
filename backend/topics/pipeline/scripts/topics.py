#!/usr/bin/env python3
"""공유 참고문헌(bibliographic coupling)으로 논문을 토픽 클러스터로 나눈다.

초록 임베딩 대신 이것을 쓰는 이유: 같은 문제의식을 가진 논문은 쓰는 단어가 달라도
같은 선행연구를 인용한다. 그리고 다음 단계(분기 계산)가 같은 지표를 쓰므로
토픽 경계와 분기선이 같은 척도 위에 놓인다.

  python3 topics.py --seeds seeds.json --out topics.json
"""
import argparse, json, math
from collections import Counter

import networkx as nx


def coupling(ra, rb):
    """코사인 정규화. 참고문헌이 많은 논문이 모든 것과 묶이는 것을 막는다."""
    if not ra or not rb:
        return 0.0
    return len(ra & rb) / math.sqrt(len(ra) * len(rb))


def coupling_graph(refs, min_shared=2):
    """{work id: set(references)} → weighted coupling graph.

    Pairs are found through an inverted reference index, so a researcher with ~1,000
    papers costs the shared references actually present, not all n² pairs."""
    G = nx.Graph()
    G.add_nodes_from(refs)
    citing = {}
    for i, rs in refs.items():
        for r in rs:
            citing.setdefault(r, []).append(i)
    shared = Counter()
    for ws in citing.values():
        if len(ws) < 2:
            continue
        ws = sorted(ws)
        for x in range(len(ws)):
            for y in range(x + 1, len(ws)):
                shared[(ws[x], ws[y])] += 1
    for (i, j), n in shared.items():
        if n >= min_shared:
            G.add_edge(i, j, weight=coupling(refs[i], refs[j]))
    return G


def cluster(refs, min_shared=2, resolution=1.05, seed=4):
    """{work id: references} → (communities sorted by size desc, graph). Same Louvain call as the CLI."""
    G = coupling_graph({i: set(r or []) for i, r in refs.items()}, min_shared)
    com = nx.community.louvain_communities(G, weight="weight", seed=seed, resolution=resolution) if len(G) else []
    return sorted((set(c) for c in com), key=lambda c: (-len(c), min(c))), G


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--seeds", required=True)
    p.add_argument("--out", default="topics.json")
    p.add_argument("--min-shared", type=int, default=2,
                   help="이 편수 이상 참고문헌을 공유해야 간선을 만든다")
    p.add_argument("--resolution", type=float, default=1.05)
    p.add_argument("--seed-rng", type=int, default=4)
    a = p.parse_args()

    D = json.load(open(a.seeds))
    W = {w["id"]: w for w in D["works"]}
    refs = {i: set(w.get("referenced_works") or []) for i, w in W.items()}

    ids = list(W)
    com, G = cluster(refs, a.min_shared, a.resolution, a.seed_rng)

    topics = []
    for k, c in enumerate(com):
        lab = Counter()
        for n in c:
            for tp in (W[n].get("topics") or [])[:2]:
                lab[tp["display_name"]] += 1
        members = sorted(c, key=lambda n: (W[n].get("publication_year") or 0))
        topics.append({
            "id": k,
            "label": "; ".join(x for x, _ in lab.most_common(2)) or "(미분류)",
            "auto_label": [x for x, _ in lab.most_common(4)],
            "size": len(c),
            "members": members,
        })

    json.dump({"topics": topics,
               "assign": {n: t["id"] for t in topics for n in t["members"]}},
              open(a.out, "w"), ensure_ascii=False)

    density = G.number_of_edges() / max(1, len(ids) * (len(ids) - 1) / 2)
    print(f"{len(ids)}편 / 간선 {G.number_of_edges()} (밀도 {density:.2f}) → 토픽 {len(topics)}개")
    for t in topics:
        print(f"\nT{t['id']} ({t['size']}편) {t['label']}")
        for n in t["members"]:
            print(f"   {W[n].get('publication_year')} {W[n]['title'][:58]}")
    print("\n※ 자동 라벨은 뭉툭하다. topics.json의 label을 사람 말로 고쳐 쓸 것.")
    print("※ 1편짜리 클러스터를 지우지 말 것 — 그것이 보여주려는 '신규 토픽'이다.")


if __name__ == "__main__":
    main()
