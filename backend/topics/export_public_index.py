#!/usr/bin/env python3
"""Per-researcher alluvial.json → public topic index + encrypted title bundle.

  python3 backend/topics/export_public_index.py \
      --researcher data/topics/<slug>=P-XXXXXXXXXX [--researcher ...] \
      --dashboard public/data/dashboard.json --out-dir public/data/topics

Each researcher directory holds the pipeline outputs (alluvial.json, seeds.json,
optionally topics.json with human labels). The public index follows the dashboard's
privacy rules (docs/SECURITY.md): anonymous ID only, no names, no paper titles or DOIs.
Titles, venues and DOIs go to ``encrypted_titles.json`` (PBKDF2-SHA256 600k → AES-256-GCM,
same scheme as encrypted_names.json) when ``NAMES_PASSWORD`` is set, so the page can show
them after unlock. Keywords, bilingual tags and one shared LSA space are added through
topic_semantics.py. Topic merge/diverge measures (info_flow.py) are computed here from
reference lists and only the aggregated topic×topic masses are published.
"""
import argparse, base64, hashlib, json, os, secrets, sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from info_flow import analyse, stable_seed  # noqa: E402
from topic_semantics import bilingual_tags, build_lsa, ctfidf_terms, load_glossary, semantic_block, topic_vectors  # noqa: E402

SCHEMA = "kstem-topic-alluvial/1"
ITERATIONS = 600_000
AAD = b"topic-titles-v1"


def text_of(work):
    """Title + abstract + OpenAlex topics/keywords when seeds.json carries them (no API calls)."""
    parts = [work.get("title") or ""]
    inv = work.get("abstract_inverted_index") or {}
    if inv:
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


def encrypt(payload, password):
    salt, nonce = secrets.token_bytes(16), secrets.token_bytes(12)
    key = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, ITERATIONS, 32)
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    ct = AESGCM(key).encrypt(nonce, json.dumps(payload, ensure_ascii=False).encode(), AAD)
    b64 = lambda b: base64.b64encode(b).decode()
    return {"version": 1, "kdf": "PBKDF2-SHA256", "iterations": ITERATIONS, "salt": b64(salt),
            "nonce": b64(nonce), "aad": b64(AAD), "ciphertext": b64(ct)}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--researcher", action="append", required=True, help="DIR=ANON_ID")
    p.add_argument("--dashboard", default="public/data/dashboard.json")
    p.add_argument("--out-dir", default="public/data/topics")
    p.add_argument("--dims", type=int, default=48)
    p.add_argument("--password-env", default="NAMES_PASSWORD")
    p.add_argument("--window", type=int, default=3, help="info-flow window width in years")
    p.add_argument("--null", type=int, default=200)
    a = p.parse_args()

    dashboard = json.load(open(a.dashboard, encoding="utf-8"))
    public = {x["id"]: x for x in dashboard["professors"]}
    en2ko, ko2en = load_glossary()
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
        keywords, vectors = ctfidf_terms(docs), topic_vectors(doc_vecs, members)
        for t in r["topics"]:
            t["keywords"] = keywords.get(t["id"], [])
            t["tags"] = bilingual_tags(t["label"], t["keywords"], en2ko, ko2en)
            t["vector"] = vectors.get(t["id"])

    os.makedirs(a.out_dir, exist_ok=True)
    out = {"schema": SCHEMA, "source": "release", "generated_at": str(date.today()),
           "method": {"disambiguation": dashboard["meta"].get("identity_filter_version", "KOAD"),
                      "clustering": "공유 참고문헌 코사인 가중 Louvain", "labels": "c-TF-IDF 자동 라벨 후 사람 검수",
                      "branching": "탄생기 논문 × 이전 시기 논문의 bibliographic coupling 최댓값"},
           "semantic": semantic_block(vocab, term_vecs, ko2en), "researchers": researchers}
    with open(os.path.join(a.out_dir, "index.json"), "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, separators=(",", ":"))
    password = os.environ.get(a.password_env)
    if password:
        with open(os.path.join(a.out_dir, "encrypted_titles.json"), "w", encoding="utf-8") as fh:
            json.dump(encrypt(titles, password), fh)
    print(f"index.json: {len(researchers)} researchers, {len(texts)} papers, LSA {term_vecs.shape[1]}d × {len(vocab)} terms;"
          f" titles {'encrypted' if password else 'NOT written (set ' + a.password_env + ')'}")


if __name__ == "__main__":
    main()
