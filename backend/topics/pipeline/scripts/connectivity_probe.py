#!/usr/bin/env python3
"""연결성분으로 토픽을 나눌 수 있는지 먼저 재본다.

references/method.md §1 의 두 표를 새 코퍼스에서 그대로 다시 찍는다.
거대성분이 80% 아래면 연결성분 분할도 후보가 되지만, 보통은 그렇지 않다.

  python3 connectivity_probe.py --seeds seeds.json
  python3 connectivity_probe.py --seeds seeds.json --depth2   # 2차 조상까지(API 호출)
"""
import argparse, json, os, time, urllib.parse, urllib.request
from collections import Counter

import networkx as nx

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


def components(A, drop=frozenset()):
    ids = list(A)
    G = nx.Graph()
    G.add_nodes_from(ids)
    for x in range(len(ids)):
        for y in range(x + 1, len(ids)):
            if (A[ids[x]] - drop) & (A[ids[y]] - drop):
                G.add_edge(ids[x], ids[y])
    cc = sorted(nx.connected_components(G), key=len, reverse=True)
    n = len(ids)
    dens = 2 * G.number_of_edges() / max(1, n * (n - 1))
    return cc, dens


def report(A, label):
    cc, dens = components(A)
    n = len(A)
    avg = sum(len(v) for v in A.values()) // max(1, n)
    print(f"  {label:<26} 평균조상 {avg:>6} | 성분 {len(cc):>2}개 | "
          f"최대 {len(cc[0])}/{n} ({100*len(cc[0])//n}%) | 밀도 {dens:.2f}")
    return cc


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--seeds", required=True)
    p.add_argument("--depth2", action="store_true")
    p.add_argument("--mailto", default="research@example.com")
    p.add_argument("--cache", default=".oa_cache")
    a = p.parse_args()

    W = {w["id"]: w for w in json.load(open(a.seeds))["works"]}
    A1 = {i: set(w.get("referenced_works") or []) for i, w in W.items()}
    print(f"시드 {len(W)}편 — '조상을 하나라도 공유하면 연결'")
    report(A1, "depth=1 (직접 참고문헌)")

    A = A1
    if a.depth2:
        ids = sorted(set().union(*A1.values()))
        meta = {}
        for i in range(0, len(ids), 100):
            chunk = [x.split("/")[-1] for x in ids[i:i + 100]]
            r = get(f"{BASE}/works?filter=openalex_id:{'|'.join(chunk)}&per-page=100"
                    f"&select=id,referenced_works", a.mailto, a.cache)
            for w in r.get("results", []):
                meta[w["id"]] = set(w.get("referenced_works") or [])
        A2 = {i: set(s) | set().union(*[meta.get(r, set()) for r in s]) if s else set()
              for i, s in A1.items()}
        report(A2, "depth=2")
        A = A2

    print("\n[허브 제거] 공유 빈도 상위 k개 조상을 빼면 갈라지는가")
    cnt = Counter()
    for s in A.values():
        cnt.update(s)
    univ = [k for k, _ in cnt.most_common()]
    for k in [0, 10, 50, 200, 1000, 5000]:
        if k > len(univ):
            break
        cc, _ = components(A, set(univ[:k]))
        iso = sum(1 for c in cc if len(c) == 1)
        print(f"  k={k:<5} 성분 {len(cc):>2}개 | 최대 {len(cc[0])}/{len(A)} | 고립 {iso}편")

    shared = sum(1 for v in cnt.values() if v >= 2)
    print(f"\n조상 {len(cnt)}편 중 둘 이상이 공유하는 것 {shared}편 "
          f"({100*shared//max(1,len(cnt))}%), 최다 공유 {max(cnt.values())}/{len(A)}")
    print("\n거대성분이 80% 아래면 연결성분 분할도 후보다. 그렇지 않으면 topics.py(가중 Louvain)를 쓴다.")


if __name__ == "__main__":
    main()
