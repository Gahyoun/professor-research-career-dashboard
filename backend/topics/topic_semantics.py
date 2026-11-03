#!/usr/bin/env python3
"""Topic keywords, bilingual tags and a shared LSA space for the public topic index.

Three things the page needs per topic (community):
  keywords  c-TF-IDF terms — words unusually frequent in this community (English, from
            titles/abstracts/OpenAlex keywords). Same estimator as pipeline/label_topics.py.
  tags      {"ko": [...], "en": [...]} — the human label split on "·", the keywords, and
            glossary translations in both directions. Searchable in either language.
  vector    the topic centroid in one LSA space shared by *all* researchers, so a query
            ranks topics across people. Per-researcher LSA spaces are not comparable.

The browser averages query-term vectors and takes cosines; no model runs at query time.
Korean query words reach the English LSA space through ``tag_glossary.json``.
"""
import json, math, os, re
from collections import Counter

import numpy as np
from sklearn.decomposition import TruncatedSVD
from sklearn.feature_extraction.text import CountVectorizer, TfidfVectorizer

HERE = os.path.dirname(os.path.abspath(__file__))
TOKEN = r"[a-zA-Z][a-zA-Z-]{2,}"
STOP_EXTRA = {"networks", "network", "model", "models", "using", "based", "study", "results", "paper",
              "show", "data", "approach", "method", "methods", "analysis", "complex", "systems", "system",
              "new", "propose", "proposed", "effect", "effects", "role", "properties", "theory", "theoretical",
              "advanced", "research", "science", "applications", "application", "challenges", "programs", "evaluating", "impact"}


def load_glossary(path=None):
    """{"en term": ["한국어", ...]} → (en→ko, ko→en) maps, all lower-case."""
    raw = json.load(open(path or os.path.join(HERE, "tag_glossary.json"), encoding="utf-8"))
    en2ko, ko2en = {}, {}
    for en, kos in raw["terms"].items():
        en = en.lower()
        en2ko[en] = list(kos)
        for ko in kos:
            ko2en.setdefault(ko, []).append(en)
    return en2ko, ko2en


def ctfidf_terms(docs, n_terms=6, max_share=0.6, ngram=(1, 2)):
    """{community: [texts]} → {community: [terms]}. Terms in ≥ max_share of communities
    are dropped first; with few communities idf alone does not suppress shared words."""
    keys = list(docs)
    if not keys:
        return {}
    cv = CountVectorizer(stop_words="english", ngram_range=ngram, token_pattern=TOKEN)
    X = cv.fit_transform([" ".join(docs[k]) for k in keys]).toarray().astype(float)
    terms = np.array(cv.get_feature_names_out())
    generic = (X > 0).sum(axis=0) > max(1, math.floor(max_share * len(keys)))
    extra = np.array([len(t.split()) == 1 and t in STOP_EXTRA for t in terms])
    keep = ~(generic | extra)
    X, terms = X[:, keep], terms[keep]
    if not X.size:
        return {k: [] for k in keys}
    tf = X / np.maximum(X.sum(axis=1, keepdims=True), 1)
    idf = np.log(1 + X.sum(axis=1).mean() / np.maximum(X.sum(axis=0), 1))
    S = tf * idf
    out = {}
    for i, k in enumerate(keys):
        picked = []
        for j in np.argsort(-S[i]):
            t = terms[j]
            if S[i, j] <= 0:
                break
            if len(t) < 4 or any(t in q or q in t for q in picked):
                continue
            picked.append(t)
            if len(picked) == n_terms:
                break
        out[k] = picked
    return out


def bilingual_tags(label, keywords, en2ko, ko2en):
    """Human label pieces + c-TF-IDF keywords, each mirrored through the glossary."""
    ko, en = [], []
    for piece in re.split(r"[·,/()]|\s{2,}", label or ""):
        piece = piece.strip()
        if not piece or piece.startswith("기타"):
            continue
        (ko if re.search(r"[가-힣]", piece) else en).append(piece.lower() if not re.search(r"[가-힣]", piece) else piece)
    en += [k.lower() for k in keywords]
    for term in list(en):
        for word in [term] + term.split():
            ko += en2ko.get(word, [])
    for term in list(ko):
        for key, ens in ko2en.items():
            if key == term or key in term:
                en += ens
    dedupe = lambda xs: list(dict.fromkeys(x for x in xs if x))
    return {"ko": dedupe(ko)[:12], "en": dedupe(en)[:12]}


def build_lsa(texts, dims=48, max_terms=2400):
    """texts: list[str] → (vocab, term_vectors[n_terms, d], doc_vectors[n_docs, d]).
    Dimensions are capped at n_docs/2: near n_docs LSA degenerates to raw TF-IDF and
    stops generalising across co-occurring words."""
    vec = TfidfVectorizer(stop_words="english", token_pattern=TOKEN, max_features=max_terms, sublinear_tf=True)
    X = vec.fit_transform(texts)
    d = max(2, min(dims, X.shape[0] // 2, X.shape[1] - 1))
    svd = TruncatedSVD(n_components=d, random_state=0)
    docs = svd.fit_transform(X)
    terms = svd.components_.T * svd.singular_values_  # term loadings in the same space
    unit = lambda M: M / (np.linalg.norm(M, axis=1, keepdims=True) + 1e-12)
    return list(vec.get_feature_names_out()), unit(terms), unit(docs)


def quantize(M):
    """Unit vectors → int8 lists; cosine survives quantisation to ~1e-2."""
    return [[int(v) for v in row] for row in np.clip(np.round(M * 127), -127, 127)]


def semantic_block(vocab, term_vectors, ko2en):
    return {"dims": int(term_vectors.shape[1]), "scale": 127,
            "terms": dict(zip(vocab, quantize(term_vectors))),
            "glossary": {ko: sorted(set(ens)) for ko, ens in ko2en.items()}}


def topic_vectors(doc_vectors, members):
    """{topic_key: [doc indices]} → {topic_key: int8 centroid}."""
    out = {}
    for k, rows in members.items():
        if rows:
            c = doc_vectors[rows].mean(axis=0)
            out[k] = quantize((c / (np.linalg.norm(c) + 1e-12))[None, :])[0]
    return out


def most_common_tags(index, n=30):
    counts = Counter(t for r in index["researchers"] for topic in r["topics"] for t in topic.get("tags", {}).get("ko", []))
    return [t for t, _ in counts.most_common(n)]
