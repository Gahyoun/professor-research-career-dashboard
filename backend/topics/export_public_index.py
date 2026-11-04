#!/usr/bin/env python3
"""Per-researcher alluvial.json → public topic index + encrypted title bundle.

  python3 backend/topics/export_public_index.py \
      --researcher data/topics/<slug>=P-XXXXXXXXXX [--researcher ...] \
      --dashboard public/data/dashboard.json --out-dir public/data/topics

Each researcher directory holds the pipeline outputs (alluvial.json, seeds.json,
optionally topics.json with human labels). The public index follows the dashboard's
privacy rules (docs/SECURITY.md): anonymous ID only, no names, no paper titles or DOIs.
Titles, venues and DOIs go to per-researcher ciphertext files under ``titles/`` (one
PBKDF2-SHA256 600k key, AES-256-GCM per file; see encrypt_titles.py) when ``NAMES_PASSWORD``
is set, so the page can show them after unlock. Topic names, keywords and tags are English (c-TF-IDF; a curated label is
kept only when it is English), with one shared LSA space, via topic_semantics.py. Topic merge/diverge measures (info_flow.py) are computed here from
reference lists and only the aggregated topic×topic masses are published.
"""
import argparse, json, os, sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from info_flow import analyse, stable_seed  # noqa: E402
from encrypt_titles import normalise_doi, write_title_vault  # noqa: E402
from topic_semantics import build_lsa, ctfidf_terms, english_label, english_tags, load_glossary, semantic_block, topic_vectors  # noqa: E402

SCHEMA = "kstem-topic-alluvial/1"


def text_of(work):
    """Title + abstract + OpenAlex topics/keywords when seeds.json carries them (no API calls)."""
    parts = [work.get("title") or ""]
    inv = work.get("abstract_inverted_index") or {}
    if work.get("abstract"):
        parts.append(work["abstract"])
    elif inv:
        n = max((p for ps in inv.values() for p in ps), default=-1) + 1
        words = [""] * n
        for word, ps in inv.items():
            for p in ps:
                if 0 <= p < n:
                    words[p] = word
        parts.append(" ".join(words))
    parts += [t.get("display_name", "") for t in (work.get("topics") or [])[:3]]
    parts += [k.get("display_name", "") for k in (work.get("keywords") or [])[:8]]
    return " ".join(p for p in parts if p)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--researcher", action="append", default=[], help="DIR=ANON_ID")
    p.add_argument("--manifest", help="file with one DIR=ANON_ID per line (large releases)")
    p.add_argument("--dashboard", default="public/data/dashboard.json")
    p.add_argument("--out-dir", default="public/data/topics")
    p.add_argument("--dims", type=int, default=48)
    p.add_argument("--password-env", default="NAMES_PASSWORD")
    p.add_argument("--window", type=int, default=3, help="info-flow window width in years")
    p.add_argument("--null", type=int, default=200)
    p.add_argument("--split-info", action="store_true",
                   help="write each researcher's info-flow block to <out-dir>/info/<id>.json (loaded on demand)")
    p.add_argument("--exclude-terms", help="private file, one phrase per line, never used as a topic term (names)")
    p.add_argument("--coverage", default=None, help="one-line note on the year coverage shown on the page")
    a = p.parse_args()
    if a.manifest:
        a.researcher += [line.strip() for line in open(a.manifest, encoding="utf-8") if line.strip()]
    if not a.researcher:
        p.error("give --researcher or --manifest")

    dashboard = json.load(open(a.dashboard, encoding="utf-8"))
    public = {x["id"]: x for x in dashboard["professors"]}
    _, ko2en = load_glossary()  # query-side Korean → English map only
    exclude = frozenset(x.strip() for x in open(a.exclude_terms, encoding="utf-8") if x.strip()) if a.exclude_terms else frozenset()
    researchers, titles, texts, owners = [], {}, [], []
    for spec in a.researcher:
        folder, anon = spec.rsplit("=", 1)
        if anon not in public:
            sys.exit(f"{anon} is not in the public dashboard population — refusing to publish")
        A = json.load(open(os.path.join(folder, "alluvial.json"), encoding="utf-8"))
        seeds = {w["id"]: w for w in json.load(open(os.path.join(folder, "seeds.json"), encoding="utf-8"))["works"]}
        spans = A.get("era_span") or [{"label": e} for e in A["eras"]]
        papers, private, refs = [], [], []
        for paper in sorted(A["papers"], key=lambda x: (x.get("year") or 0)):
            if not paper.get("year"):
                continue
            papers.append({"year": paper["year"], "topic": paper["topic"], "era": paper.get("era"), "cited": paper.get("cited", 0)})
            private.append({"year": paper["year"], "topic": paper["topic"], "title": paper["title"],
                            "venue": paper.get("venue") or None, "doi": paper.get("doi") or None})
            texts.append(text_of(seeds.get(paper["id"], {"title": paper["title"]})))
            refs.append(seeds.get(paper["id"], {}).get("referenced_works") or [])
            owners.append((len(researchers), paper["topic"]))
        topics = [{"id": t["id"], "label": t["label"], "size": t["size"], "birth_year": t.get("birth_year"),
                   "parent": ({k: t["parent"].get(k) for k in ("from", "sim", "from_year", "to_year")} if t.get("parent") else None)}
                  for t in A["topics"]]
        recip = [{k: r.get(k) for k in ("from_topic", "to_topic", "from_year", "to_year", "x_year")} for r in A.get("recip", [])]
        prof = public[anon]
        researchers.append({"id": anon, "alias": None, "subject": prof["subject"], "institution": prof.get("current_institution"),
                            "eras": [{"label": e.get("label"), "start": e.get("start"), "end": e.get("end")} for e in spans],
                            "topics": topics, "papers": papers, "recip": recip,
                            "counts": {"source_works": None, "kept_works": len(papers), "merged_versions": None},
                            "fetched_at": A.get("fetched_at") or str(date.today()),
                            "info": analyse([x["year"] for x in papers], [x["topic"] for x in papers], refs,
                                            width=a.window, n_null=a.null, n_boot=a.null, seed=stable_seed(anon))})
        titles[anon] = private

    vocab, term_vecs, doc_vecs = build_lsa(texts, dims=a.dims)
    for ri, r in enumerate(researchers):
        docs, members = {}, {}
        for row, (owner, tid) in enumerate(owners):
            if owner == ri:
                docs.setdefault(tid, []).append(texts[row])
                members.setdefault(tid, []).append(row)
        keywords, vectors = ctfidf_terms(docs, n_terms=8, exclude=exclude), topic_vectors(doc_vecs, members)
        for t in r["topics"]:
            t["keywords"] = keywords.get(t["id"], [])
            t["label"] = english_label(t["keywords"], curated=t["label"])
            t["tags"] = english_tags(t["label"], t["keywords"])
            t["vector"] = vectors.get(t["id"])

    os.makedirs(a.out_dir, exist_ok=True)
    if a.split_info:
        info_dir = os.path.join(a.out_dir, "info")
        os.makedirs(info_dir, exist_ok=True)
        for old_file in os.listdir(info_dir):
            if old_file.endswith(".json"):
                os.remove(os.path.join(info_dir, old_file))
        for r in researchers:
            with open(os.path.join(info_dir, f"{r['id']}.json"), "w", encoding="utf-8") as fh:
                json.dump(r.pop("info"), fh, ensure_ascii=False, separators=(",", ":"))
    out = {"schema": SCHEMA, "source": "release", "generated_at": str(date.today()),
           "method": {"disambiguation": dashboard["meta"].get("identity_filter_version", "KOAD"),
                      "clustering": "weighted Louvain on bibliographic coupling: w_ij = c_ij / sqrt(|R_i||R_j|) (Salton cosine), c_ij >= 2, resolution 1.05, seed 4", "labels": "c-TF-IDF top terms (English); curated English labels kept",
                      "branching": "탄생기 논문 × 이전 시기 논문의 bibliographic coupling 최댓값",
                      **({"coverage": a.coverage} if a.coverage else {}),
                      **({"recip": "not computed"} if not any(r["recip"] for r in researchers) else {})},
           **({"info_path": "info"} if a.split_info else {}),
           "semantic": semantic_block(vocab, term_vecs, ko2en), "researchers": researchers}
    with open(os.path.join(a.out_dir, "index.json"), "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, separators=(",", ":"))
    password = os.environ.get(a.password_env)
    if password:
        write_title_vault({k: [{**row, "doi": normalise_doi(row["doi"])} for row in rows] for k, rows in titles.items()}, password, a.out_dir)
    print(f"index.json: {len(researchers)} researchers, {len(texts)} papers, LSA {term_vecs.shape[1]}d × {len(vocab)} terms;"
          f" titles {'encrypted' if password else 'NOT written (set ' + a.password_env + ')'}")


if __name__ == "__main__":
    main()
