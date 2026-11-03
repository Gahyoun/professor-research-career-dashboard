#!/usr/bin/env python3
"""자연어 검색용 LSA 색인을 만든다.

브라우저에서 돌아야 하고 파일 하나로 끝나야 하므로, 질의 시점에 모델을 부르지 않는다.
대신 빌드 때 제목·초록·OpenAlex 토픽/키워드로 TF-IDF → SVD(LSA) 공간을 만들고,
**단어 벡터와 논문 벡터를 둘 다** HTML 에 굳혀 넣는다. 브라우저는 질의 단어를 찾아
평균 내고 코사인만 계산하면 된다 — 의존성 0, 네트워크 0.

LSA 는 같이 등장하는 말끼리 묶으므로 "network falls apart" 로 percolation·robustness
논문이 걸리는 정도의 동의어 효과는 난다. 코퍼스에 아예 없는 말은 못 찾는다.
그 경우 JS 가 부분일치로 자동 후퇴한다.

  python3 semantic_index.py --seeds seeds.json --out semantic.json
"""
import argparse, json, os, re, time, urllib.parse, urllib.request

import numpy as np
from sklearn.decomposition import TruncatedSVD
from sklearn.feature_extraction.text import TfidfVectorizer

BASE = "https://api.openalex.org"


def get(url, mailto, cache):
    key = os.path.join(cache, urllib.parse.quote(url, safe="")[:180] + ".json")
    if cache and os.path.exists(key):
        return json.load(open(key))
    req = urllib.request.Request(url, headers={"User-Agent": f"mailto:{mailto}"})
    for a in range(3):
        try:
            d = json.load(urllib.request.urlopen(req, timeout=90))
            break
        except Exception:
            if a == 2:
                return {"results": []}
            time.sleep(2)
    if cache:
        os.makedirs(cache, exist_ok=True)
        json.dump(d, open(key, "w"))
    return d


def abstract_of(w):
    """OpenAlex 는 초록을 역색인으로 준다. 위치 정보는 버리고 단어만 되살린다."""
    inv = w.get("abstract_inverted_index")
    if not inv:
        return ""
    n = max((p for ps in inv.values() for p in ps), default=-1) + 1
    out = [""] * n
    for word, ps in inv.items():
        for p in ps:
            if 0 <= p < n:
                out[p] = word
    return " ".join(out)


def fetch_text(ids, mailto, cache):
    out = {}
    for i in range(0, len(ids), 100):
        chunk = [x.split("/")[-1] for x in ids[i:i + 100]]
        r = get(f"{BASE}/works?filter=openalex_id:{'|'.join(chunk)}&per-page=100"
                f"&select=id,title,abstract_inverted_index,topics,keywords", mailto, cache)
        for w in r.get("results", []):
            parts = [w.get("title") or "", abstract_of(w)]
            parts += [t["display_name"] for t in (w.get("topics") or [])[:3]]
            parts += [k["display_name"] for k in (w.get("keywords") or [])[:8]]
            out[w["id"]] = " ".join(parts)
    return out


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--seeds", action="append", required=True,
                   help="seeds.json. 여러 연구자를 한 공간에 넣으려면 여러 번 준다")
    p.add_argument("--out", default="semantic.json")
    p.add_argument("--dims", type=int, default=48)
    p.add_argument("--max-terms", type=int, default=2600)
    p.add_argument("--mailto", default="research@example.com")
    p.add_argument("--cache", default=".oa_cache")
    a = p.parse_args()

    works = {}
    for path in a.seeds:
        for w in json.load(open(path))["works"]:
            works[w["id"]] = w
    ids = list(works)
    print(f"논문 {len(ids)}편 — 제목·초록·토픽·키워드 수집")
    text = fetch_text(ids, a.mailto, a.cache)
    miss = [i for i in ids if not text.get(i, "").strip()]
    for i in miss:                      # 초록이 없으면 제목만으로라도
        text[i] = works[i].get("title") or ""
    print(f"  초록 확보 {len(ids)-len(miss)}/{len(ids)}편")

    corpus = [text[i] for i in ids]
    vec = TfidfVectorizer(stop_words="english", min_df=2, max_df=0.6,
                          max_features=a.max_terms, token_pattern=r"[a-zA-Z][a-zA-Z-]{2,}")
    X = vec.fit_transform(corpus)
    # 문서가 적으면 차원을 줄여야 LSA 가 실제로 동의어를 묶는다.
    # 차원 ≈ 문서 수면 사실상 TF-IDF 그대로라 의미 검색이 되지 않는다.
    dims = min(a.dims, max(2, len(ids) // 2, min(X.shape) - 1) if len(ids) > 8 else 2)
    dims = min(dims, max(2, len(ids) // 2))
    svd = TruncatedSVD(n_components=dims, random_state=0)
    P = svd.fit_transform(X)                       # 논문 벡터
    T = svd.components_.T                          # 단어 벡터
    norm = lambda M: M / (np.linalg.norm(M, axis=1, keepdims=True) + 1e-9)
    P, T = norm(P), norm(T)

    terms = vec.get_feature_names_out()
    out = {"dims": dims,
           "terms": {t: [round(float(v), 3) for v in T[j]] for j, t in enumerate(terms)},
           "papers": {ids[i]: [round(float(v), 3) for v in P[i]] for i in range(len(ids))}}
    json.dump(out, open(a.out, "w"))
    kb = os.path.getsize(a.out) / 1024
    print(f"→ {a.out}  단어 {len(terms)} × {dims}차원, 논문 {len(ids)}편 ({kb:.0f} KB)")
    print(f"  설명분산 {svd.explained_variance_ratio_.sum():.2f}")


if __name__ == "__main__":
    main()
