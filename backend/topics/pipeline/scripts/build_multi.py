#!/usr/bin/env python3
"""여러 연구자를 하나의 토픽축 위에 겹쳐 본다.

각자 따로 돌린 토픽은 서로 비교할 수 없다 — 번호도 경계도 다르기 때문이다.
그래서 전원의 논문을 **한 번에 모아** 공유 참고문헌으로 다시 클러스터링하고,
그 공통 토픽축 위에 사람별로 색을 달리해 얹는다.

  python3 build_multi.py --seeds data/a/seeds.json --seeds data/b/seeds.json \\
      --mode overlay --semantic multi-semantic.json --out output/multi.html

  --mode overlay : 토픽 레인 하나에 사람별 띠를 쌓는다 (누가 어느 토픽을 하는지)
  --mode stack   : 사람마다 레인 묶음을 따로 둔다 (각자의 궤적을 나란히)
"""
import argparse, html, json, math, os, sys
from collections import Counter

import networkx as nx

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from label_topics import ctfidf_labels, exemplars  # noqa: E402
from render_alluvial import PALETTE, page, ribbon  # noqa: E402
from semantic_index import fetch_text  # noqa: E402

PCOL = ["#2f6f9f", "#c2572c", "#5a8f5a", "#8a5fa8", "#c9972b", "#39b5a4", "#b0485f", "#7a6a4f"]


def coupling(a, b):
    return len(a & b) / math.sqrt(len(a) * len(b)) if a and b else 0.0


def shared_topics(works, refs, min_shared, resolution, rng):
    G = nx.Graph()
    G.add_nodes_from(works)
    ids = list(works)
    for i in range(len(ids)):
        for j in range(i + 1, len(ids)):
            x, y = ids[i], ids[j]
            if len(refs[x] & refs[y]) >= min_shared:
                G.add_edge(x, y, weight=coupling(refs[x], refs[y]))
    com = sorted(nx.community.louvain_communities(G, weight="weight", seed=rng,
                                                  resolution=resolution), key=len, reverse=True)
    return com


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--seeds", action="append", required=True)
    p.add_argument("--labels", default=None, help="토픽 라벨 json {\"0\": \"...\"}")
    p.add_argument("--semantic", default=None)
    p.add_argument("--mode", choices=["overlay", "stack"], default="overlay")
    p.add_argument("--out", default="multi.html")
    p.add_argument("--min-shared", type=int, default=2)
    p.add_argument("--resolution", type=float, default=1.0)
    p.add_argument("--seed-rng", type=int, default=4)
    p.add_argument("--min-topic", type=int, default=3, help="이 편수 미만 토픽은 '기타'로 묶는다")
    p.add_argument("--mailto", default="research@example.com")
    p.add_argument("--cache", default=".oa_cache")
    a = p.parse_args()

    works, who, people = {}, {}, []
    for path in a.seeds:
        D = json.load(open(path))
        people.append(D["name"])
        for w in D["works"]:
            works[w["id"]] = w
            who[w["id"]] = D["name"]
    refs = {i: set(w.get("referenced_works") or []) for i, w in works.items()}
    print(f"연구자 {len(people)}명 · 논문 {len(works)}편 — 공통 토픽축 계산")

    com = shared_topics(works, refs, a.min_shared, a.resolution, a.seed_rng)
    keep = [c for c in com if len(c) >= a.min_topic]
    rest = [n for c in com if len(c) < a.min_topic for n in c]
    tid = {n: k for k, c in enumerate(keep) for n in c}
    if rest:
        for n in rest:
            tid[n] = len(keep)
    # 라벨은 c-TF-IDF 로 뽑는다. OpenAlex topics 최빈값을 쓰면 "Complex Network
    # Analysis Techniques" 가 세 토픽에 똑같이 붙는다 — 그 분류가 이 코퍼스보다 거칠다.
    members = {k: list(c) for k, c in enumerate(keep)}
    if rest:
        members[len(keep)] = list(rest)
    text = fetch_text(list(works), a.mailto, a.cache)
    for i in works:
        if not text.get(i, "").strip():
            text[i] = works[i].get("title") or ""
    auto = ctfidf_labels({k: [text[i] for i in ms] for k, ms in members.items()})
    labels = {k: v[0] for k, v in auto.items()}
    exs = exemplars(text, members)
    if rest:
        labels[len(keep)] = f'{labels[len(keep)]} (기타 {len(rest)}편)'
    if a.labels:
        for k, v in json.load(open(a.labels)).items():
            labels[int(k)] = v

    papers = []
    for i, w in works.items():
        if not w.get("publication_year"):
            continue
        papers.append({"id": i, "title": w["title"], "year": w["publication_year"],
                       "topic": tid[i], "who": who[i], "doi": w.get("doi"),
                       "cited": w["cited_by_count"],
                       "venue": (((w.get("primary_location") or {}).get("source") or {})
                                 .get("display_name") or "")})
    for k in sorted(labels):
        c = Counter(p["who"] for p in papers if p["topic"] == k)
        print(f"  T{k} ({sum(c.values())}편) {labels[k][:52]}")
        print(f"      {' / '.join(f'{n.split()[-1]} {v}' for n, v in c.most_common())}")
        for i in exs.get(k, [])[:2]:
            print(f"      · {works[i]['title'][:62]}")

    D = {"name": " · ".join(people), "people": people, "papers": papers,
         "topics": [{"id": k, "label": labels[k],
                     "size": sum(1 for p in papers if p["topic"] == k)}
                    for k in sorted(labels)]}
    w, h, svg = draw(D, a.mode)
    sem = json.load(open(a.semantic)) if a.semantic and os.path.exists(a.semantic) else None
    title = f"공통 토픽축 비교 — {len(people)}명"
    sub = (f'연구자 {len(people)}명 · 논문 {len(papers)}편 · 토픽 {len(labels)}개 · '
           f'{min(p["year"] for p in papers)}–{max(p["year"] for p in papers)} · '
           f'{"토픽 레인에 사람별로 쌓음" if a.mode == "overlay" else "사람별 레인 묶음"}')
    foot = ("출처: OpenAlex. 토픽은 전원의 논문을 한 번에 모아 공유 참고문헌으로 "
            "다시 클러스터링한 공통 축이다. 각자 따로 돌린 토픽 번호와는 다르다.")
    open(a.out, "w").write(page(D, title, foot, w, h, svg, sem, people, sub))
    print(f"→ {a.out}")


def draw(D, mode):
    """공통 연도축 위에 사람별 색으로 쌓는다."""
    papers, topics, people = D["papers"], D["topics"], D["people"]
    years = [p["year"] for p in papers]
    y0, y1 = min(years), max(years)
    YW, LEFT, UNIT, GAP, MINT = 34, 290, 7, 18, 4
    pcol = {n: PCOL[i % len(PCOL)] for i, n in enumerate(people)}

    def cx(yr):
        return LEFT + (yr - y0 + 0.5) * YW

    cells = Counter((p["year"], p["topic"], p["who"]) for p in papers)
    tot = Counter((p["year"], p["topic"]) for p in papers)

    # overlay: 토픽마다 레인 하나, 안에서 사람별로 쌓는다
    # stack:   사람마다 레인 묶음, 그 안에 토픽 레인
    if mode == "overlay":
        groups = [(None, [t["id"] for t in topics])]
    else:
        groups = [(n, [t["id"] for t in topics]) for n in people]

    lane_y, lane_h, heads, cur = {}, {}, [], 92
    for gname, tids in groups:
        if gname:
            heads.append((gname, cur))
            cur += 22
        for k in tids:
            if gname:
                hmax = max((cells.get((y, k, gname), 0) for y in range(y0, y1 + 1)), default=0)
            else:
                hmax = max((tot.get((y, k), 0) for y in range(y0, y1 + 1)), default=0)
            if hmax == 0 and gname:
                continue
            h = max(MINT, hmax * UNIT)
            lane_h[(gname, k)] = h
            lane_y[(gname, k)] = cur + h / 2
            cur += h + GAP
        cur += 10
    H = cur + 20
    W = LEFT + (y1 - y0 + 1) * YW + 40

    sv = []
    for yr in range(y0, y1 + 1):
        x = cx(yr) - YW / 2
        sv.append(f'<line class="grid" x1="{x:.0f}" y1="56" x2="{x:.0f}" y2="{H-16}"/>')
        if yr % 2 == 0:
            sv.append(f'<text class="yr" x="{cx(yr):.0f}" y="70">{yr}</text>')

    tl = {t["id"]: t["label"] for t in topics}
    for gname, tids in groups:
        if gname:
            yy = dict(heads)[gname]
            sv.append(f'<rect class="eband" x="{LEFT-6}" y="{yy-12}" '
                      f'width="{W-LEFT-28}" height="16" rx="2"/>')
            sv.append(f'<text class="era" x="{LEFT}" y="{yy}">{html.escape(gname)}</text>')
        for k in tids:
            if (gname, k) not in lane_y:
                continue
            ly, lh = lane_y[(gname, k)], lane_h[(gname, k)]
            subs = [gname] if gname else people
            base = {yr: ly + lh / 2 for yr in range(y0, y1 + 1)}
            for n in subs:
                live = [yr for yr in range(y0, y1 + 1) if cells.get((yr, k, n), 0)]
                if not live:
                    continue
                top, bot = [], []
                for yr in range(min(live), max(live) + 1):
                    c = cells.get((yr, k, n), 0)
                    hh = c * UNIT
                    b = base[yr]
                    for px in (cx(yr) - YW * 0.44, cx(yr) + YW * 0.44):
                        bot.append((px, b))
                        top.append((px, b - max(1.4, hh)))
                    base[yr] = b - hh
                sv.append(f'<path class="rib" fill="{pcol[n]}" d="{ribbon(top, bot)}">'
                          f'<title>{html.escape(n)} · {html.escape(tl[k][:40])}</title></path>')
                for yr in live:
                    c = cells[(yr, k, n)]
                    sv.append(f'<circle class="dot" data-k="{yr}|{k}|{n}" '
                              f'cx="{cx(yr):.0f}" cy="{base[yr]+c*UNIT/2:.0f}" '
                              f'r="{min(9, 3.2+c*1.5):.1f}" fill="{pcol[n]}"/>')
            lab = f'T{k} · {tl[k]}'
            sv.append(f'<text class="lane" x="{LEFT-14}" y="{ly+4:.0f}">'
                      f'{html.escape(lab[:34])}</text>')

    # 사람 색 범례
    x = LEFT
    for n in people:
        sv.append(f'<rect x="{x}" y="26" width="11" height="11" rx="2" fill="{pcol[n]}"/>')
        sv.append(f'<text class="era" x="{x+16}" y="36">{html.escape(n)}</text>')
        x += 26 + len(n) * 8.4
    return W, H, "\n".join(sv)


if __name__ == "__main__":
    main()
