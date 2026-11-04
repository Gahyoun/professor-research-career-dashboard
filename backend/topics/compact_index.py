#!/usr/bin/env python3
"""Compact layout for the public topic index (same schema, smaller file, fewer objects to parse).

  python3 -I backend/topics/compact_index.py public/data/topics/index.json   # rewrite in place

Two lossless changes; frontend/src/topics.ts reads both the old and the compact layout:

* ``papers: [{year, topic, era, cited}, …]`` → ``paper_cols: {year: [...], topic: [...], era: [...], cited: [...]}``
  (one array per column, rows in year order).
* ``tags`` is left out of a topic when it equals ``english_tags(label, keywords)``; the page rebuilds it
  from the label and keywords with the same rule (``deriveTags`` in topics.ts).
"""
import argparse, json, os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from topic_semantics import english_tags  # noqa: E402

COLUMNS = ("year", "topic", "era", "cited")


def compact_researcher(r):
    papers = r.pop("papers", None)
    if papers is not None:
        papers = sorted(papers, key=lambda p: p["year"])
        r["paper_cols"] = {k: [p.get(k) if k != "cited" else p.get(k, 0) for p in papers] for k in COLUMNS}
    for t in r.get("topics", []):
        if "tags" in t and t["tags"] == english_tags(t.get("label"), t.get("keywords") or []):
            del t["tags"]
    return r


def compact_index(index):
    for r in index["researchers"]:
        compact_researcher(r)
    return index


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("index", help="topic index.json to rewrite in place")
    a = p.parse_args()
    before = os.path.getsize(a.index)
    index = compact_index(json.load(open(a.index, encoding="utf-8")))
    with open(a.index, "w", encoding="utf-8") as fh:
        json.dump(index, fh, ensure_ascii=False, separators=(",", ":"))
    kept = sum(1 for r in index["researchers"] for t in r["topics"] if "tags" in t)
    print(f"{a.index}: {before / 1e6:.1f} MB → {os.path.getsize(a.index) / 1e6:.1f} MB; tags kept on {kept} topics")


if __name__ == "__main__":
    main()
