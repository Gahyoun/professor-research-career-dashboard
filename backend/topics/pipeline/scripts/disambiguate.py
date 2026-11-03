#!/usr/bin/env python3
"""소속 연속성으로 동명이인을 걸러내고, preprint/저널 중복을 합친다.

판정 근거는 논문에 **본인 이름으로 찍힌 소속 원문**(raw_affiliation_strings) 하나다.
분야나 저널로 거르면 연구자의 분야 전환까지 같이 지워진다.

  python3 disambiguate.py --works works.json --timeline timeline.json --out seeds.json

timeline.json:
  {"eras": [{"label": "기관 A (~2010)",
             "match": "Institution A|INST-A",
             "exclude": "Mechanical Engineering"}, ...]}

교체 가능 지점: 더 나은 동명이인 판별기가 있으면 works.json → seeds.json 스키마만
맞추면 그대로 끼워 넣을 수 있다. 하위 단계는 eras / referenced_works만 쓴다.
"""
import argparse, json, re, sys
from collections import Counter

NONARTICLE = re.compile(
    r"Institutional Repository|Bulletin of the American Physical|"
    r"Open Access System for Information|Proceedings of the \w+ Annual Meeting", re.I)
PREPRINT = re.compile(r"arXiv|bioRxiv|medRxiv|SSRN|Research Square|Preprints", re.I)


def src(w):
    return (((w.get("primary_location") or {}).get("source") or {}).get("display_name") or "?")


def own_affils(w, author_ids):
    """본인 authorship의 소속 원문 + 공저자 이름."""
    raws, co = [], set()
    for a in w.get("authorships", []):
        aid = ((a.get("author") or {}).get("id") or "").split("/")[-1]
        if aid in author_ids:
            raws += a.get("raw_affiliation_strings") or []
        else:
            n = (a.get("author") or {}).get("display_name")
            if n:
                co.add(n)
    return raws, co


def match_eras(raws, eras):
    out = []
    for i, e in enumerate(eras):
        pat = re.compile(e["match"], re.I)
        bad = re.compile(e["exclude"], re.I) if e.get("exclude") else None
        for r in raws:
            if pat.search(r) and not (bad and bad.search(r)):
                out.append(i)
                break
    return out


def toks(t):
    return set(re.sub(r"[^a-z0-9 ]", " ", (t or "").lower()).split())


def merge_versions(items, jac=0.55, contain=0.85):
    """같은 연구의 여러 버전을 묶는다. 제목이 바뀌어 출판되는 경우가 있어 DOI로는 부족하다."""
    groups = []
    for w in sorted(items, key=lambda x: (x.get("publication_year") or 0)):
        tk = toks(w["title"])
        placed = False
        for g in groups:
            gk = toks(g[0]["title"])
            inter = len(tk & gk)
            if not inter:
                continue
            if inter / max(1, len(tk | gk)) >= jac or \
               inter / max(1, min(len(tk), len(gk))) >= contain:
                g.append(w)
                placed = True
                break
        if not placed:
            groups.append([w])
    return groups


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--works", required=True)
    p.add_argument("--timeline", required=True)
    p.add_argument("--out", default="seeds.json")
    p.add_argument("--recover-coauthors", action="store_true",
                   help="소속 기록이 빈 레코드를 알려진 공저자로 건져 후보로 보고")
    p.add_argument("--known-coauthor", action="append", default=[])
    p.add_argument("--report", default=None, help="정제 내역을 적을 마크다운 경로")
    a = p.parse_args()

    D = json.load(open(a.works))
    author_ids = set(D["author_ids"])
    eras = json.load(open(a.timeline))["eras"]
    known = set(a.known_coauthor)

    mine, no_affil, rejected = [], [], []
    for w in D["works"]:
        raws, co = own_affils(w, author_ids)
        if not raws:
            no_affil.append((w, co))
            continue
        hit = match_eras(raws, eras)
        if hit:
            w = dict(w, eras=[eras[i]["label"] for i in hit], era_idx=hit, raw=raws[0])
            mine.append(w)
        else:
            rejected.append((w, raws[0]))

    recovered = []
    if a.recover_coauthors and known:
        for w, co in no_affil:
            if co & known and not NONARTICLE.search(src(w)):
                recovered.append(w)

    groups = merge_versions(mine)
    uniq = []
    for g in groups:
        g.sort(key=lambda w: (1 if PREPRINT.search(src(w)) else 0, -w["cited_by_count"]))
        b = dict(g[0])
        b["versions"] = [x["title"] for x in g]
        b["eras"] = sorted({e for x in g for e in x["eras"]},
                           key=lambda e: [x["label"] for x in eras].index(e))
        b["era_idx"] = sorted({i for x in g for i in x["era_idx"]})
        b["preprint_only"] = bool(PREPRINT.search(src(b)))
        uniq.append(b)

    dropped_nonart = [w for w in uniq if NONARTICLE.search(src(w))]
    uniq = [w for w in uniq if not NONARTICLE.search(src(w))]
    uniq.sort(key=lambda w: (w.get("publication_year") or 0))

    json.dump({"name": D["name"], "author_ids": D["author_ids"],
               "eras": [e["label"] for e in eras], "works": uniq},
              open(a.out, "w"), ensure_ascii=False)

    print(f"원본 {len(D['works'])}건")
    print(f"  소속 연속성 통과 {len(mine)}건 / 소속 불일치(동명이인 등) {len(rejected)}건"
          f" / 소속 결측 {len(no_affil)}건")
    print(f"  버전 병합 -{sum(len(g) - 1 for g in groups)}건, 비논문 제외 -{len(dropped_nonart)}건")
    print(f"  → 최종 {len(uniq)}편 ({a.out})")
    if recovered:
        print(f"\n소속 결측이지만 공저자로 회수되는 후보 {len(recovered)}건 — 사람이 확인할 것:")
        for w in recovered:
            print(f"  ? {w.get('publication_year')} {src(w)[:26]:<26} {w['title'][:54]}")
    by_era = Counter(w["eras"][-1] for w in uniq)
    print("\n시기별 편수")
    for e in eras:
        print(f"  {e['label']:<28} {by_era.get(e['label'], 0)}")

    if a.report:
        with open(a.report, "w") as f:
            f.write(f"# {D['name']} 정제 내역\n\n")
            f.write(f"원본 {len(D['works'])} → 최종 {len(uniq)}\n\n## 소속 불일치로 제외\n\n")
            cnt = Counter()
            for w, raw in rejected:
                cnt[re.sub(r"^.*?,\s*", "", raw)[:60]] += 1
            for k, v in cnt.most_common(20):
                f.write(f"- {v:>3}건 — {k}\n")
            f.write("\n## 버전 병합\n\n")
            for w in uniq:
                if len(w["versions"]) > 1:
                    f.write(f"- {w['title'][:60]} ← {len(w['versions'])}개 버전\n")
        print(f"\n정제 내역 → {a.report}")


if __name__ == "__main__":
    main()
