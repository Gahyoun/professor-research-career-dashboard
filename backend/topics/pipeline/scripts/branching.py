#!/usr/bin/env python3
"""시기 × 토픽 흐름, 토픽의 탄생과 모(母)토픽, 상호 인용 쌍을 계산한다.

  python3 branching.py --seeds seeds.json --topics topics.json --out alluvial.json
  python3 branching.py ... --citers        # 피인용까지 받아 상호 쌍 계산(API 호출)
"""
import argparse, json, math, os, re, time, urllib.parse, urllib.request
from collections import Counter

BASE = "https://api.openalex.org"
SELECT = "id,title,publication_year,cited_by_count,referenced_works,authorships"


def get(url, mailto, cache=None):
    if cache:
        key = os.path.join(cache, urllib.parse.quote(url, safe="")[:180] + ".json")
        if os.path.exists(key):
            return json.load(open(key))
    req = urllib.request.Request(url, headers={"User-Agent": f"mailto:{mailto}"})
    for a in range(3):
        try:
            data = json.load(urllib.request.urlopen(req, timeout=90))
            break
        except Exception:
            if a == 2:
                return {"results": []}
            time.sleep(2)
    if cache:
        os.makedirs(cache, exist_ok=True)
        json.dump(data, open(key, "w"))
    return data


def norm_name(s):
    return re.sub(r"[^a-z]", "", (s or "").lower())


def my_orcids(works, author_ids):
    """시드 논문들에서 본인 ORCID 를 모은다. author ID 가 갈려 있어도 ORCID 는 하나다."""
    out = set()
    for w in works:
        for a in w.get("authorships", []):
            au = a.get("author") or {}
            if (au.get("id") or "").split("/")[-1] in author_ids and au.get("orcid"):
                out.add(au["orcid"].rstrip("/").split("/")[-1])
    return out


def is_self(w, author_ids, myname, orcids):
    """중간 논문 X 에 본인이 저자로 들어 있는가.

    ORCID → author ID → 정규화한 이름 순으로 본다. 이름 매칭은 'G. D. Hong' 같은
    축약 표기를 놓치므로 마지막 보루일 뿐이다. 세 가지를 모두 통과한 논문만
    '다른 연구자의 논문'으로 인정한다."""
    for a in w.get("authorships", []):
        au = a.get("author") or {}
        oc = (au.get("orcid") or "").rstrip("/").split("/")[-1]
        if oc and oc in orcids:
            return True
        if (au.get("id") or "").split("/")[-1] in author_ids:
            return True
        if myname and norm_name(au.get("display_name")) == myname:
            return True
    return False


def fetch_citers(ids, mailto, cache, group=25, pages=3):
    """cites: 필터는 OR 를 받는다. 한 번에 묶어 던져 호출 수를 줄인다.
    피인용은 발산하므로 인용수 상위부터 가져오고, 표본임을 보고한다."""
    out = {}
    for i in range(0, len(ids), group):
        g = [x.split("/")[-1] for x in ids[i:i + group]]
        for pg in range(1, pages + 1):
            r = get(f"{BASE}/works?filter=cites:{'|'.join(g)}&per-page=200&page={pg}"
                    f"&sort=cited_by_count:desc&select={SELECT}", mailto, cache)
            res = r.get("results", [])
            for w in res:
                out[w["id"]] = w
            if len(res) < 200:
                break
    return out


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--seeds", required=True)
    p.add_argument("--topics", required=True)
    p.add_argument("--out", default="alluvial.json")
    p.add_argument("--citers", action="store_true")
    p.add_argument("--mailto", default="research@example.com")
    p.add_argument("--cache", default=".oa_cache")
    a = p.parse_args()

    D = json.load(open(a.seeds))
    T = json.load(open(a.topics))
    eras = D["eras"]
    W = {w["id"]: w for w in D["works"]}
    assign = {k: v for k, v in T["assign"].items()}
    refs = {i: set(w.get("referenced_works") or []) for i, w in W.items()}

    papers = []
    for i, w in W.items():
        papers.append({"id": i, "title": w["title"], "year": w.get("publication_year"),
                       "era": max(w["era_idx"]), "topic": assign[i],
                       "cited": w["cited_by_count"],
                       # DOI 는 호버 카드에서 바로가기로 쓴다. OpenAlex 는 전체 URL 로 준다.
                       "doi": w.get("doi"),
                       "era_label": w["eras"][-1] if w.get("eras") else "",
                       "venue": (((w.get("primary_location") or {}).get("source") or {})
                                 .get("display_name") or "")})
    papers.sort(key=lambda x: (x["year"] or 0))

    # 시기 × 토픽 흐름
    cells = Counter((p["era"], p["topic"]) for p in papers)

    # 토픽 탄생과 모토픽
    births, parents = {}, {}
    for t in T["topics"]:
        k = t["id"]
        ps = [p for p in papers if p["topic"] == k]
        if not ps:
            continue
        b = min(p["era"] for p in ps)
        births[k] = b
        best = None
        # 비교 범위를 탄생기 논문 × 그 이전 시기 논문으로 제한한다.
        # 전 기간에서 최대값을 찾으면 10년 뒤 논문이 초기 줄기의 부모가 되는 역방향 분기가 나온다.
        for q in [x for x in ps if x["era"] == b]:
            for r in papers:
                if r["era"] >= b or r["topic"] == k:
                    continue
                ra, rb = refs[q["id"]], refs[r["id"]]
                sim = (len(ra & rb) / math.sqrt(max(1, len(ra)) * max(1, len(rb)))) if ra and rb else 0
                if best is None or sim > best[2]:
                    best = (r, q, sim)
        parents[k] = ({"from": best[0]["topic"], "via": best[0]["title"],
                       "to": best[1]["title"], "sim": round(best[2], 3),
                       # 연도축으로 그릴 때 분기선을 정확한 논문 연도에 물린다
                       "from_year": best[0]["year"], "to_year": best[1]["year"]}
                      if best and best[2] > 0 else None)

    # 상호 쌍: 외부 논문 X 가 초기 논문을 인용 + 후기 논문이 X 를 인용
    # X 는 반드시 '다른 연구자'여야 한다. 본인이 저자인 논문이 끼면 양쪽 고리가 모두
    # 자기인용이 되어 측정하려는 것(자기 연구가 외부를 거쳐 돌아온 경로)이 아니게 된다.
    recip, selfcite = [], 0
    if a.citers:
        citers = fetch_citers(list(W), a.mailto, a.cache)
        allrefs = set().union(*refs.values()) if refs else set()
        aids = set(D.get("author_ids") or [])
        myname = norm_name(D.get("name", ""))
        orcids = my_orcids(D["works"], aids)
        for xid, xw in citers.items():
            if xid in W or xid not in allrefs:
                continue
            # 저자 레코드가 분리돼 있을 수 있으므로 ID와 이름을 함께 본다
            if is_self(xw, aids, myname, orcids):
                selfcite += 1
                continue
            xy = xw.get("publication_year") or 0
            early = [s for s in W if s in (xw.get("referenced_works") or [])]
            later = [s for s in W if xid in refs[s]]
            for ea in early:
                for lb in later:
                    if (W[ea].get("publication_year") or 0) < xy <= (W[lb].get("publication_year") or 0):
                        recip.append({"x": xw["title"], "x_year": xy,
                                      "x_cited": xw["cited_by_count"],
                                      "from_topic": assign[ea], "to_topic": assign[lb],
                                      # A(초기)와 B(후기) 양쪽의 시기·연도를 모두 싣는다.
                                      # 같은 기관 안에서 돌아온 경로도 시작/끝을 구분해 그려야 한다.
                                      "from_era": max(W[ea]["era_idx"]),
                                      "to_era": max(W[lb]["era_idx"]),
                                      "era": max(W[lb]["era_idx"]),  # 하위 호환
                                      "from_year": W[ea].get("publication_year"),
                                      "to_year": W[lb].get("publication_year"),
                                      "from_paper": W[ea]["title"], "to_paper": W[lb]["title"]})

    era_span = []
    for i, lab in enumerate(eras):
        ys = [p["year"] for p in papers if p["era"] == i and p["year"]]
        era_span.append({"label": lab, "start": min(ys) if ys else None,
                         "end": max(ys) if ys else None, "n": len(ys)})

    out = {"name": D["name"], "recip_excluded_self": selfcite, "era_span": era_span, "eras": eras,
           "topics": [{"id": t["id"], "label": t["label"], "size": t["size"],
                       "birth": births.get(t["id"]),
                       "birth_year": min((p["year"] for p in papers
                                          if p["topic"] == t["id"] and p["year"]), default=None),
                       "parent": parents.get(t["id"])}
                      for t in T["topics"] if t["id"] in births],
           "papers": papers,
           "cells": [{"era": e, "topic": k, "n": n} for (e, k), n in sorted(cells.items())],
           "recip": recip}
    json.dump(out, open(a.out, "w"), ensure_ascii=False)

    print(f"시기 {len(eras)} × 토픽 {len(out['topics'])} / 논문 {len(papers)}편")
    for t in out["topics"]:
        par = t["parent"]
        tag = (f"← T{par['from']} (유사도 {par['sim']})" if par else "독립 신규 생성")
        print(f"  T{t['id']:<2} {t['size']:>2}편  탄생 {eras[t['birth']]:<26} {tag}")
    if a.citers:
        print(f"\n상호 쌍 {len(recip)}건 (고유 외부 논문 {len({r['x'] for r in recip})}편)")
        print(f"  자기인용 경로로 제외한 중간 논문 {selfcite}편"
              + (f" (ORCID {len(orcids)}개로 대조)" if orcids else " (ORCID 없음 — 이름 대조만)"))
        print("  ※ 피인용은 인용수 상위 표본이다. 전수가 아님을 보고할 것.")
    print(f"→ {a.out}")


if __name__ == "__main__":
    main()
