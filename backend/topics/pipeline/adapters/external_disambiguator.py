#!/usr/bin/env python3
"""외부 동명이인 판별기 → seeds.json 어댑터 (템플릿).

이 파일만 고치면 기존 판별기를 파이프라인에 끼울 수 있다. 하위 단계(topics.py,
branching.py, render_alluvial.py)가 읽는 것은 각 논문의 `eras`, `era_idx`,
`referenced_works`, `title`, `publication_year` 뿐이다.

  python3 adapters/external_disambiguator.py \
      --works works.json \
      --verdicts path/to/your/disambiguation_output.json \
      --institutions path/to/your/institution_data.json \
      --out seeds.json

TODO 표시된 두 함수만 리포지토리 스키마에 맞춰 고친다.
"""
import argparse, json, re, sys
from collections import Counter

sys.path.insert(0, __file__.rsplit("/", 2)[0] + "/scripts")
from disambiguate import merge_versions, src, NONARTICLE, PREPRINT  # noqa: E402


# ──────────────────────────────────────────────────────────────────────
# TODO 1: 판별 결과를 {work_id: bool} 로 바꾼다.
# ──────────────────────────────────────────────────────────────────────
def load_verdicts(path):
    """외부 판별기의 출력 → {OpenAlex work id: 이 사람 것인가}.

    work id 는 'https://openalex.org/W123...' 전체 URL로 정규화한다.
    판별기가 점수를 낸다면 임계값을 여기서 적용하고, 그 임계값을 근거와 함께
    docs/INTEGRATION.md 에 적어둔다.
    """
    raw = json.load(open(path))
    out = {}
    for rec in raw if isinstance(raw, list) else raw.get("works", []):
        wid = rec.get("work_id") or rec.get("id") or rec.get("openalex_id")
        if not wid:
            continue
        if not wid.startswith("http"):
            wid = f"https://openalex.org/{wid.lstrip('/')}"
        verdict = rec.get("is_target")
        if verdict is None:
            score = rec.get("score", rec.get("confidence"))
            verdict = (score is not None and float(score) >= 0.5)
        out[wid] = bool(verdict)
    return out


# ──────────────────────────────────────────────────────────────────────
# TODO 2: 기관 정보 → 시기 구간
# ──────────────────────────────────────────────────────────────────────
def load_eras(path):
    """기관 연속성 데이터 → [{label, start, end, ror, match}] (연도 오름차순).

    기존 데이터에 ROR id 와 재직 구간이 있다면 그대로 쓰는 편이 정규식보다 정확하다.
    ROR 이 없고 문자열뿐이면 match 정규식을 만들어 두고, 같은 기관 다른 학과
    동명이인이 있는 시기에는 exclude 를 함께 넣는다(method.md §3).
    """
    raw = json.load(open(path))
    eras = []
    for rec in raw if isinstance(raw, list) else raw.get("affiliations", []):
        eras.append({
            "label": rec.get("label") or rec.get("name") or rec.get("institution"),
            "start": int(rec.get("start_year") or rec.get("from") or 0),
            "end": int(rec.get("end_year") or rec.get("to") or 9999),
            "ror": rec.get("ror") or rec.get("ror_id"),
            "match": rec.get("match"),
            "exclude": rec.get("exclude"),
        })
    eras.sort(key=lambda e: (e["start"], e["end"]))
    return eras


# ──────────────────────────────────────────────────────────────────────
# 여기부터는 고치지 않아도 된다.
# ──────────────────────────────────────────────────────────────────────
def own_affil_blobs(w, author_ids):
    """본인 authorship의 소속 원문 + ROR id."""
    raws, rors = [], set()
    for a in w.get("authorships", []):
        aid = ((a.get("author") or {}).get("id") or "").split("/")[-1]
        if aid in author_ids:
            raws += a.get("raw_affiliation_strings") or []
            for inst in a.get("institutions", []):
                if inst.get("ror"):
                    rors.add(inst["ror"].rstrip("/").split("/")[-1])
    return raws, rors


def assign_eras(w, eras, author_ids):
    """논문 → 시기 인덱스. ROR 일치가 1순위, 소속 원문 정규식이 2순위,
    둘 다 없으면 출판연도가 들어가는 구간으로 떨어뜨린다(약한 근거이므로 표시)."""
    raws, rors = own_affil_blobs(w, author_ids)
    year = w.get("publication_year") or 0
    hits, how = [], "none"
    for i, e in enumerate(eras):
        if e.get("ror") and e["ror"].rstrip("/").split("/")[-1] in rors:
            hits.append(i)
            how = "ror"
    if not hits:
        for i, e in enumerate(eras):
            if not e.get("match"):
                continue
            pat = re.compile(e["match"], re.I)
            bad = re.compile(e["exclude"], re.I) if e.get("exclude") else None
            if any(pat.search(r) and not (bad and bad.search(r)) for r in raws):
                hits.append(i)
                how = "affil-string"
    if not hits:
        hits = [i for i, e in enumerate(eras) if e["start"] <= year <= e["end"]]
        how = "year-only" if hits else "none"
    return hits, how


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--works", required=True)
    p.add_argument("--verdicts", required=True)
    p.add_argument("--institutions", required=True)
    p.add_argument("--out", default="seeds.json")
    p.add_argument("--keep-year-only", action="store_true",
                   help="소속 근거 없이 연도만으로 시기가 정해진 논문도 포함")
    a = p.parse_args()

    D = json.load(open(a.works))
    author_ids = set(D["author_ids"])
    verdicts = load_verdicts(a.verdicts)
    eras = load_eras(a.institutions)

    mine, unknown, weak = [], [], []
    for w in D["works"]:
        v = verdicts.get(w["id"])
        if v is None:
            unknown.append(w)
            continue
        if not v:
            continue
        idx, how = assign_eras(w, eras, author_ids)
        if not idx:
            weak.append((w, "시기 미배정"))
            continue
        if how == "year-only":
            weak.append((w, "연도만으로 배정"))
            if not a.keep_year_only:
                continue
        mine.append(dict(w, eras=[eras[i]["label"] for i in idx], era_idx=idx,
                         era_evidence=how))

    groups = merge_versions(mine)
    uniq = []
    for g in groups:
        g.sort(key=lambda w: (1 if PREPRINT.search(src(w)) else 0, -w["cited_by_count"]))
        b = dict(g[0])
        b["versions"] = [x["title"] for x in g]
        labels = [e["label"] for e in eras]
        b["eras"] = sorted({e for x in g for e in x["eras"]}, key=labels.index)
        b["era_idx"] = sorted({i for x in g for i in x["era_idx"]})
        b["preprint_only"] = bool(PREPRINT.search(src(b)))
        uniq.append(b)
    uniq = [w for w in uniq if not NONARTICLE.search(src(w))]
    uniq.sort(key=lambda w: (w.get("publication_year") or 0))

    json.dump({"name": D["name"], "author_ids": D["author_ids"],
               "eras": [e["label"] for e in eras], "works": uniq},
              open(a.out, "w"), ensure_ascii=False)

    ev = Counter(w.get("era_evidence") for w in uniq)
    print(f"판별기 판정 {len(verdicts)}건 중 본인 {sum(verdicts.values())}건")
    print(f"  시기 배정 근거: {dict(ev)}")
    print(f"  버전 병합 -{sum(len(g)-1 for g in groups)}건 → 최종 {len(uniq)}편 ({a.out})")
    if unknown:
        print(f"\n판별기에 판정이 없는 레코드 {len(unknown)}건 — 판별기 입력 범위를 확인할 것")
        for w in unknown[:10]:
            print(f"  ? {w.get('publication_year')} {w['title'][:56]}")
    if weak:
        print(f"\n근거가 약한 배정 {len(weak)}건 — 사람이 확인할 것")
        for w, why in weak[:10]:
            print(f"  ! {why}: {w.get('publication_year')} {w['title'][:50]}")


if __name__ == "__main__":
    main()
