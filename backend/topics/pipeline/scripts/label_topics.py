#!/usr/bin/env python3
"""토픽 라벨을 c-TF-IDF 로 뽑는다.

OpenAlex 의 `topics` 최빈값을 쓰면 "Complex Network Analysis Techniques" 가 세 토픽에
똑같이 붙는다. 그 분류 체계가 이 코퍼스보다 거칠기 때문이다. 필요한 것은 빈도가 아니라
**이 군집에만 유난히 많이 나오는 말**이다.

c-TF-IDF: 군집 하나를 문서 하나로 합친 뒤, 군집 내 빈도에 군집 간 희소성을 곱한다.
  tf(t,c) = count(t,c) / Σ_t count(t,c)
  idf(t)  = log(1 + A / f(t))     A = 군집당 평균 단어 수, f(t) = 전체 군집에서의 총 빈도
군집 수가 적으면 idf 만으로는 공통어가 덜 눌리므로, **군집의 60% 이상에 등장하는 말은
먼저 버린다**. 이것이 라벨 중복을 막는 실질적인 장치다.

  python3 label_topics.py --seeds seeds.json --topics topics.json
  python3 label_topics.py --seeds a.json --seeds b.json --assign assign.json --print-only
"""
import argparse, json, math, os, sys
from collections import Counter

import numpy as np
from sklearn.feature_extraction.text import CountVectorizer, TfidfVectorizer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from semantic_index import fetch_text  # noqa: E402

STOP_EXTRA = {"networks", "network", "model", "models", "using", "based", "study",
              "results", "paper", "show", "data", "approach", "method", "methods",
              "analysis", "complex", "systems", "system", "new", "propose", "proposed"}


def ctfidf_labels(docs, n_terms=3, max_share=0.6, ngram=(1, 2)):
    """{군집키: 텍스트들} → {군집키: (라벨, [특징어...])}"""
    keys = list(docs)
    corpus = [" ".join(docs[k]) for k in keys]
    cv = CountVectorizer(stop_words="english", ngram_range=ngram, min_df=1,
                         token_pattern=r"[a-zA-Z][a-zA-Z-]{2,}")
    X = cv.fit_transform(corpus).toarray().astype(float)
    terms = np.array(cv.get_feature_names_out())

    # 군집의 max_share 이상에 등장하는 말은 변별력이 없다 — 먼저 버린다
    present = (X > 0).sum(axis=0)
    generic = present > max(1, math.floor(max_share * len(keys)))
    # 불용어 보강: 분야 전체의 상투어
    extra = np.array([any(w in STOP_EXTRA for w in t.split()) and len(t.split()) == 1
                      for t in terms])
    keep = ~(generic | extra)
    X, terms = X[:, keep], terms[keep]

    tf = X / np.maximum(X.sum(axis=1, keepdims=True), 1)
    A = X.sum(axis=1).mean()
    idf = np.log(1 + A / np.maximum(X.sum(axis=0), 1))
    S = tf * idf

    out = {}
    for i, k in enumerate(keys):
        order = np.argsort(-S[i])
        picked = []
        for j in order:
            t = terms[j]
            if S[i, j] <= 0:
                break
            # 이미 고른 말에 포함되는 하위 표현은 건너뛴다 (temporal / temporal networks)
            if len(t.split()) == 1 and len(t) < 4:
                continue        # 'spa' 같은 조각어가 라벨에 섞이는 것을 막는다
            if any(t in q or q in t for q in picked):
                continue
            picked.append(t)
            if len(picked) == n_terms:
                break
        label = " · ".join(w.title() if w.isupper() is False else w for w in picked)
        out[k] = (label, picked)
    return out


def exemplars(docs_per_item, members, n=3):
    """군집 중심에 가장 가까운 논문 — 라벨이 맞는지 사람이 확인할 근거."""
    ids = [i for ms in members.values() for i in ms]
    vec = TfidfVectorizer(stop_words="english", min_df=1,
                          token_pattern=r"[a-zA-Z][a-zA-Z-]{2,}")
    M = vec.fit_transform([docs_per_item.get(i, "") for i in ids]).toarray()
    M = M / (np.linalg.norm(M, axis=1, keepdims=True) + 1e-9)
    pos = {i: n_ for n_, i in enumerate(ids)}
    out = {}
    for k, ms in members.items():
        if not ms:
            out[k] = []
            continue
        rows = [pos[i] for i in ms]
        c = M[rows].mean(axis=0)
        c = c / (np.linalg.norm(c) + 1e-9)
        sc = sorted(((float(M[pos[i]] @ c), i) for i in ms), reverse=True)
        out[k] = [i for _, i in sc[:n]]
    return out


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--seeds", action="append", required=True)
    p.add_argument("--topics", default=None, help="topics.json (members 포함). 라벨을 여기에 쓴다")
    p.add_argument("--assign", default=None, help="{work_id: topic_id} json (topics.json 대신)")
    p.add_argument("--out", default=None, help="기본값: --topics 를 제자리에 갱신")
    p.add_argument("--overwrite", action="store_true",
                   help="사람이 고친 라벨도 덮어쓴다 (기본은 보존)")
    p.add_argument("--print-only", action="store_true")
    p.add_argument("--terms", type=int, default=3)
    p.add_argument("--mailto", default="research@example.com")
    p.add_argument("--cache", default=".oa_cache")
    a = p.parse_args()

    works = {}
    for path in a.seeds:
        for w in json.load(open(path))["works"]:
            works[w["id"]] = w

    if a.topics:
        T = json.load(open(a.topics))
        members = {t["id"]: [m for m in t["members"] if m in works] for t in T["topics"]}
    else:
        assign = json.load(open(a.assign))
        members = {}
        for i, k in assign.items():
            members.setdefault(int(k), []).append(i)
        T = None

    text = fetch_text(list(works), a.mailto, a.cache)
    for i in works:
        if not text.get(i, "").strip():
            text[i] = works[i].get("title") or ""

    docs = {k: [text[i] for i in ms] for k, ms in members.items() if ms}
    labels = ctfidf_labels(docs, n_terms=a.terms)
    exs = exemplars(text, {k: ms for k, ms in members.items() if ms})

    print(f"군집 {len(docs)}개 — c-TF-IDF 특징어\n")
    for k in sorted(docs):
        lab, picked = labels[k]
        print(f"T{k} ({len(members[k])}편)  {lab}")
        print(f"     특징어: {', '.join(picked)}")
        for i in exs.get(k, []):
            print(f"     · {works[i]['title'][:66]}")
        print()

    if a.print_only or not T:
        if not a.print_only:
            json.dump({str(k): labels[k][0] for k in labels},
                      open(a.out or "labels.json", "w"), ensure_ascii=False, indent=1)
            print(f"→ {a.out or 'labels.json'}")
        return

    auto = {"; ".join(t.get("auto_label", [])) for t in T["topics"]}
    for t in T["topics"]:
        k = t["id"]
        if k not in labels:
            continue
        lab, picked = labels[k]
        was_auto = t.get("label", "") in auto or t.get("label", "").startswith("(미분류)")
        t["ctfidf"] = picked
        t["exemplars"] = [works[i]["title"] for i in exs.get(k, [])]
        if a.overwrite or was_auto or not t.get("label"):
            t["label"] = lab
    out = a.out or a.topics
    json.dump(T, open(out, "w"), ensure_ascii=False)
    print(f"→ {out} (사람이 고친 라벨은 보존, 덮어쓰려면 --overwrite)")


if __name__ == "__main__":
    main()
