#!/usr/bin/env python3
"""Write a clearly synthetic topic index so the page can be reviewed before real data.

Every researcher, institution and topic here is fictitious (ids DEMO-xxxx). The page
shows an "예시 데이터" badge whenever ``source == "demo"``. Replace the output with
``export_public_index.py`` once real alluvial.json files are prepared.

Reference lists are synthetic too: each topic draws from its own drifting pool, a young
child topic also from its parent's pool, "기타" topics from other pools, plus a small
shared pool. They exist only to feed info_flow.py and are not written out.

  python3 backend/topics/make_demo_index.py --out public/data/topics/index.json
"""
import argparse, json, os, random, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from info_flow import analyse, stable_seed  # noqa: E402
from topic_semantics import bilingual_tags, build_lsa, ctfidf_terms, load_glossary, semantic_block, topic_vectors  # noqa: E402

SCHEMA = "kstem-topic-alluvial/1"
NOISE = ["dynamics", "measurement", "theory", "experiment", "framework", "structure", "behavior", "evidence"]
PEOPLE = [
    ("physics", "예시 물리학자 A", "예시대학교 (Demo University)",
     [("예시공과대 박사 (2004-09)", 2004, 2009), ("해외 연구소 포닥 (2010-13)", 2010, 2013),
      ("예시고등과학원 (2013-17)", 2013, 2017), ("예시대학교 물리학과 (2017-)", 2017, None)],
     [("네트워크 구조·임계현상", 2005, None, "network percolation critical phase transition ising scaling degree"), ("메조스케일 구조", 2010, 0, "community core-periphery mesoscale structure modularity detection"),
      ("동기화·안정성", 2012, 0, "synchronization oscillator kuramoto power grid stability basin"),
      ("시간 네트워크·확산", 2015, 1, "temporal network epidemic spreading outbreak diffusion contact"), ("도시 모빌리티", 2019, None, "urban mobility human travel spatial flows"), ("기타 소군집", 2016, None, "citation collaboration hiring inequality")]),
    ("chemistry", "예시 화학자 B", "예시대학교 (Demo University)",
     [("예시대 화학과 박사 (2008-13)", 2008, 2013), ("해외대학 포닥 (2013-16)", 2013, 2016),
      ("예시대학교 화학과 (2016-)", 2016, None)],
     [("유기 광촉매", 2009, None, "photocatalysis photocatalytic organic visible light catalysis radical"), ("C–H 활성화", 2013, 0, "activation catalysis organic synthesis bond functionalization"), ("전기화학 합성", 2018, 1, "electrochemical electrochemistry synthesis electrode reaction"), ("기계학습 반응 예측", 2021, None, "machine learning prediction reaction yield deep learning")]),
    ("biology", "예시 생물학자 C", "샘플과학기술원 (Sample Institute)",
     [("샘플대 생명과학 박사 (2002-08)", 2002, 2008), ("해외 의대 포닥 (2008-12)", 2008, 2012),
      ("샘플과학기술원 (2012-)", 2012, None)],
     [("단백질 접힘", 2003, None, "protein folding molecular simulation chaperone"), ("세포 신호전달", 2009, 0, "cell signaling pathway kinase immune"), ("단일세포 전사체", 2015, 1, "single-cell transcriptome rna sequencing gene expression"),
      ("공간 전사체", 2020, 2, "spatial transcriptome tissue single-cell imaging"), ("기타 소군집", 2011, None, "microbiome ecology population")]),
    ("mathematics", "예시 수학자 D", "샘플과학기술원 (Sample Institute)",
     [("샘플대 수학과 박사 (2010-15)", 2010, 2015), ("해외 수학연구소 (2015-18)", 2015, 2018),
      ("샘플과학기술원 (2018-)", 2018, None)],
     [("확률 그래프 이론", 2011, None, "random graph probability combinatorics percolation threshold"), ("랜덤 행렬", 2016, 0, "random matrix eigenvalue probability spectrum universality"), ("최적 수송", 2019, None, "optimal transport geometry pde wasserstein")]),
    ("physics", "예시 물리학자 E", "샘플과학기술원 (Sample Institute)",
     [("예시공과대 박사 (2000-06)", 2000, 2006), ("해외 국립연구소 (2006-11)", 2006, 2011),
      ("샘플과학기술원 (2011-)", 2011, None)],
     [("강상관 전자계", 2001, None, "correlated electron superconductivity hubbard lattice"), ("위상 물질", 2008, 0, "topological insulator quantum spin edge"), ("양자 스핀 액체", 2013, 1, "quantum spin liquid magnetic frustration lattice"),
      ("모아레 초격자", 2019, 1, "moire graphene twisted superconductivity electron"), ("양자 시뮬레이션", 2022, None, "quantum simulation entanglement information")]),
    ("chemistry", "예시 화학자 F", "예시대학교 (Demo University)",
     [("예시대 화학과 박사 (2012-17)", 2012, 2017), ("해외대학 포닥 (2017-20)", 2017, 2020),
      ("예시대학교 화학과 (2020-)", 2020, None)],
     [("금속-유기 골격체", 2013, None, "metal-organic framework porous crystal adsorption"), ("탄소 포집", 2018, 0, "carbon capture adsorption co2 framework"), ("고체 전해질", 2021, None, "solid-state electrolyte battery ion conduction")]),
]


def synthetic_refs(rnd, n, tid, year, birth, parent, labels, k=18):
    """Reference ids for one demo paper; the pool window drifts 4 ids per year."""
    out = set()
    other = [t for t in range(len(labels)) if t != tid]
    while len(out) < k:
        r = rnd.random()
        if labels[tid].startswith("기타") and other and r < 0.6:
            src, base = rnd.choice(other), 0
        elif parent is not None and year - birth <= 3 and r < 0.35:
            src, base = parent, 40
        elif r < 0.04:
            out.add(f"G{n}-{rnd.randrange(120)}")
            continue
        else:
            src, base = tid, 4 * (year - birth)
        out.add(f"R{n}-{src}-{base + rnd.randrange(30)}")
    return sorted(out)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--out", required=True)
    p.add_argument("--seed", type=int, default=2026)
    a = p.parse_args()
    rnd = random.Random(a.seed)
    researchers, texts = [], []
    for n, (subject, alias, inst, eras, topics) in enumerate(PEOPLE, 1):
        end_year = 2026
        papers, topic_rows = [], []
        for tid, (label, birth, parent, _words) in enumerate(topics):
            # Each topic peaks a few years after birth and fades; "기타" stays sparse.
            sparse = label.startswith("기타")
            peak = birth + rnd.randint(2, 5)
            span_end = min(end_year, birth + rnd.randint(6, 14))
            for year in range(birth, span_end + 1):
                lam = (0.4 if sparse else 2.4) * max(0.15, 1 - abs(year - peak) / 7)
                k = sum(1 for _ in range(6) if rnd.random() < lam / 6)
                if year == birth:
                    k = max(1, k)
                for _ in range(k):
                    papers.append({"year": year, "topic": tid, "cited": int(rnd.paretovariate(1.3) * 6),
                                   "_refs": synthetic_refs(rnd, n, tid, year, birth, parent, [t[0] for t in topics])})
                    # Pseudo-abstract: the topic vocabulary plus a little shared noise.
                    texts.append((n - 1, tid, " ".join(rnd.sample(_words.split(), k=min(4, len(_words.split()))) + rnd.sample(NOISE, 2))))
            topic_rows.append((tid, label, birth, parent))
        for p_ in papers:
            p_["era"] = max((i for i, (_, s, e) in enumerate(eras) if s <= p_["year"] <= (e or end_year)), default=None)
        size = {tid: sum(1 for p_ in papers if p_["topic"] == tid) for tid, *_ in topic_rows}
        out_topics = []
        for tid, label, birth, parent in topic_rows:
            par = None
            if parent is not None:
                par = {"from": parent, "sim": round(rnd.uniform(0.03, 0.31), 3),
                       "from_year": birth - rnd.randint(1, 3), "to_year": birth}
            out_topics.append({"id": tid, "label": label, "size": size[tid], "birth_year": birth, "parent": par})
        recip = []
        for _ in range(rnd.randint(2, 6)):
            f, t = rnd.choice(topic_rows), rnd.choice(topic_rows)
            fy = rnd.randint(f[2], min(end_year - 3, f[2] + 6))
            ty = rnd.randint(fy + 2, min(end_year, fy + 9))
            recip.append({"from_topic": f[0], "to_topic": t[0], "from_year": fy, "to_year": ty, "x_year": rnd.randint(fy + 1, ty)})
        papers.sort(key=lambda x: x["year"])
        info = analyse([x["year"] for x in papers], [x["topic"] for x in papers], [x.pop("_refs") for x in papers],
                       width=3, n_null=200, n_boot=200, seed=stable_seed(f"DEMO-{n:04d}"))
        researchers.append({
            "id": f"DEMO-{n:04d}", "alias": alias, "subject": subject, "institution": inst,
            "eras": [{"label": l, "start": s, "end": e} for l, s, e in eras],
            "topics": out_topics, "papers": sorted(papers, key=lambda x: x["year"]), "recip": recip,
            "counts": {"source_works": len(papers) * 3 + rnd.randint(5, 40), "kept_works": len(papers) + rnd.randint(2, 9),
                       "merged_versions": rnd.randint(1, 8)},
            "fetched_at": "2026-11-03", "info": info,
        })
    # Keywords, bilingual tags and topic vectors via the same code path as real exports.
    en2ko, ko2en = load_glossary()
    vocab, term_vecs, doc_vecs = build_lsa([t for _, _, t in texts], dims=24)
    for ri, r in enumerate(researchers):
        docs = {}
        members = {}
        for row, (owner, tid, text) in enumerate(texts):
            if owner == ri:
                docs.setdefault(tid, []).append(text)
                members.setdefault(tid, []).append(row)
        keywords = ctfidf_terms(docs, n_terms=5)
        vectors = topic_vectors(doc_vecs, members)
        for topic in r["topics"]:
            topic["keywords"] = keywords.get(topic["id"], [])
            topic["tags"] = bilingual_tags(topic["label"], topic["keywords"], en2ko, ko2en)
            topic["vector"] = vectors.get(topic["id"])
    out = {"schema": SCHEMA, "source": "demo", "generated_at": "2026-11-03",
           "method": {"disambiguation": "KOAD 1.1-strict-namesake-drop (예시 데이터에는 적용 대상 없음)",
                      "clustering": "공유 참고문헌 코사인 가중 Louvain",
                      "labels": "c-TF-IDF 자동 라벨 후 사람 검수",
                      "branching": "탄생기 논문 × 이전 시기 논문의 bibliographic coupling 최댓값"},
           "semantic": semantic_block(vocab, term_vecs, ko2en),
           "researchers": researchers}
    with open(a.out, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, separators=(",", ":"))
    print(f"{a.out}: demo researchers {len(researchers)}, papers {sum(len(r['papers']) for r in researchers)}")


if __name__ == "__main__":
    main()
