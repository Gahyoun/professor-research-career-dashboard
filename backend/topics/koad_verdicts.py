#!/usr/bin/env python3
"""KOAD stage-1 output → verdicts.json for pipeline/adapters/external_disambiguator.py.

KOAD (korea-openalex-disambiguation) already decides keep/drop per work for the
dashboard release. The topic pipeline must use the *same* decisions, otherwise the
career page and the topic page count different papers for one researcher.

  python3 backend/topics/koad_verdicts.py --koad-dir outputs/run-2026 \
      --professor-uid prof:physics:xxxx --out data/<slug>/verdicts.json

Review-queue records follow ``--review``: ``drop`` (default, same as the strict
dashboard release), ``keep``, or ``skip`` (left without a verdict; the adapter then
reports them as "판별기에 판정이 없는 레코드").
"""
import argparse, json, os


def rows(path):
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--koad-dir", required=True)
    p.add_argument("--professor-uid", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--review", choices=["drop", "keep", "skip"], default="drop")
    a = p.parse_args()

    verdicts, seen = [], set()
    sources = [("true_papers.jsonl", True), ("namesake_papers.jsonl", False), ("review_queue.jsonl", None)]
    counts = {"keep": 0, "drop": 0, "review": 0}
    for name, default in sources:
        for r in rows(os.path.join(a.koad_dir, name)):
            if r.get("professor_uid") != a.professor_uid or r.get("work_id") in seen:
                continue
            seen.add(r["work_id"])
            action = r.get("recommended_action")
            if action == "keep" or (default is True and action != "drop"):
                verdict = True
            elif action == "drop" or default is False:
                verdict = False
            else:
                counts["review"] += 1
                if a.review == "skip":
                    continue
                verdict = a.review == "keep"
            counts["keep" if verdict else "drop"] += 1
            wid = r["work_id"] if str(r["work_id"]).startswith("http") else f"https://openalex.org/{r['work_id']}"
            verdicts.append({"work_id": wid, "is_target": verdict, "koad_decision": r.get("decision"),
                             "koad_confidence": r.get("confidence")})
    with open(a.out, "w", encoding="utf-8") as fh:
        json.dump(verdicts, fh, ensure_ascii=False)
    print(f"{a.out}: keep {counts['keep']} · drop {counts['drop']} · review {counts['review']} (policy {a.review})")


if __name__ == "__main__":
    main()
