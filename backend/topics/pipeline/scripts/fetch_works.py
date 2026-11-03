#!/usr/bin/env python3
"""OpenAlex에서 한 연구자 후보 논문을 전부 받는다.

이름만으로 저자 ID를 찾지 않는다. 확실한 대표 논문 제목으로 author ID를 역추적한 뒤,
그 ID에 묶인 논문을 전부 가져온다(동명이인 포함 — 거르는 일은 disambiguate.py 담당).

  python3 fetch_works.py --name "Hong Gildong" \
      --seed-title "<대표 논문 제목 1>" \
      --seed-title "<대표 논문 제목 2>" --out works.json
"""
import argparse, json, os, sys, time, urllib.parse, urllib.request

BASE = "https://api.openalex.org"
SELECT = ("id,doi,title,publication_year,cited_by_count,referenced_works,"
          "authorships,primary_location,topics,type")


def get(url, mailto, cache=None, tries=3):
    if cache:
        key = os.path.join(cache, urllib.parse.quote(url, safe="")[:180] + ".json")
        if os.path.exists(key):
            return json.load(open(key))
    req = urllib.request.Request(url, headers={"User-Agent": f"mailto:{mailto}"})
    for a in range(tries):
        try:
            data = json.load(urllib.request.urlopen(req, timeout=90))
            break
        except Exception as e:
            if a == tries - 1:
                print(f"  ! 요청 실패: {e}", file=sys.stderr)
                return {"results": [], "meta": {"count": 0}}
            time.sleep(2)
    if cache:
        os.makedirs(cache, exist_ok=True)
        json.dump(data, open(key, "w"))
    return data


def resolve_authors(titles, name, mailto, cache):
    """대표 논문 제목 → 그 논문에서 name과 일치하는 author ID 집계."""
    hits = {}
    surname = name.split()[-1].lower()
    for t in titles:
        q = urllib.parse.quote(t)
        r = get(f"{BASE}/works?filter=title.search:{q}&per-page=2"
                f"&select=id,title,authorships", mailto, cache)
        for w in r.get("results", [])[:1]:
            for a in w["authorships"]:
                au = a.get("author") or {}
                dn = (au.get("display_name") or "").lower()
                if surname in dn and au.get("id"):
                    aid = au["id"].split("/")[-1]
                    hits.setdefault(aid, {"name": au["display_name"], "n": 0})
                    hits[aid]["n"] += 1
            print(f"  · '{w['title'][:50]}' 매칭")
    return hits


def works_of(author_ids, mailto, cache):
    out = {}
    for aid in author_ids:
        page = 1
        while True:
            r = get(f"{BASE}/works?filter=author.id:{aid}&per-page=200&page={page}"
                    f"&select={SELECT}", mailto, cache)
            res = r.get("results", [])
            for w in res:
                out[w["id"]] = w
            if len(res) < 200:
                break
            page += 1
    return out


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--name", required=True)
    p.add_argument("--seed-title", action="append", required=True,
                   help="확실히 그 사람 것인 논문 제목. 2~3개 권장")
    p.add_argument("--out", default="works.json")
    p.add_argument("--mailto", default="research@example.com")
    p.add_argument("--cache", default=".oa_cache")
    p.add_argument("--min-hits", type=int, default=1,
                   help="대표 논문 중 몇 편 이상에 등장한 author ID만 채택")
    a = p.parse_args()

    print(f"[1/2] '{a.name}' author ID 역추적")
    hits = resolve_authors(a.seed_title, a.name, a.mailto, a.cache)
    if not hits:
        sys.exit("대표 논문에서 저자를 찾지 못했다. 제목을 확인할 것.")
    ids = [k for k, v in sorted(hits.items(), key=lambda kv: -kv[1]["n"])
           if v["n"] >= a.min_hits]
    for k in ids:
        print(f"  → {k} ({hits[k]['name']}, 대표논문 {hits[k]['n']}편에 등장)")

    print(f"[2/2] 논문 수집")
    works = works_of(ids, a.mailto, a.cache)
    json.dump({"author_ids": ids, "name": a.name, "works": list(works.values())},
              open(a.out, "w"), ensure_ascii=False)
    print(f"  {len(works)}건 저장 → {a.out}")
    print("  ※ 이 안에는 동명이인이 섞여 있다. 다음은 disambiguate.py.")


if __name__ == "__main__":
    main()
