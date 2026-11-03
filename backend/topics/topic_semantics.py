#!/usr/bin/env python3
"""Topic names, features and a shared LSA space for the public topic index — English only.

Per topic (community):
  keywords  c-TF-IDF terms — words unusually frequent in this community (from titles,
            abstracts, OpenAlex keywords). Same estimator as pipeline/label_topics.py.
  label     the leading c-TF-IDF terms ("Temporal network · epidemic · spreading"), or a
            curated English label when one is given. Residual clusters read "Other · …".
  tags      {"en": [...], "ko": []} — keywords plus curated label pieces. No machine
            translation is attached to a topic; ``ko`` stays empty for schema compatibility.
  vector    the topic centroid in one LSA space shared by *all* researchers, so a query
            ranks topics across people. Per-researcher LSA spaces are not comparable.

Korean *queries* still work: the browser maps query words to English terms through the
glossary shipped in ``semantic.glossary`` (from ``tag_glossary.json``) before matching
tags and the LSA space. The glossary is a search aid only and is never shown as a name.
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


def ctfidf_terms(docs, n_terms=6, max_share=0.6, ngram=(1, 2), phrase_bonus=1.5):
    """{community: [texts]} → {community: [terms]}. Terms in ≥ max_share of communities
    are dropped first; with few communities idf alone does not suppress shared words.
    A recurring phrase ties with its own words on frequency, so multi-word terms get
    ``phrase_bonus``; the words of a chosen phrase are then skipped as substrings."""
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
    S = tf * idf * np.array([phrase_bonus if " " in t else 1.0 for t in terms])
    out = {}
    for i, k in enumerate(keys):
        picked = []
        for j in np.argsort(-S[i]):
            t = terms[j]
            if S[i, j] <= 0:
                break
            if len(t) < 4 or any(t in q or q in t for q in picked):
                continue
            covered = {w for q in picked for w in q.split()}
            if " " in t and all(w in covered for w in t.split()):
                continue  # "law spectral" after "local law", "spectral universality"
            picked.append(t)
            if len(picked) == n_terms:
                break
        out[k] = picked
    return out


HANGUL = re.compile(r"[가-힣]")
MISC = re.compile(r"^\s*(기타|other|misc)", re.I)


def is_misc(label):
    return bool(label and MISC.search(label))


def english_label(keywords, curated=None, n=3):
    """Curated label when it is English, else the leading c-TF-IDF terms; residual clusters
    get an "Other · " prefix."""
    misc = is_misc(curated)
    if curated and not HANGUL.search(curated) and not misc:
        return curated.strip()
    terms, stems = [], set()
    for k in keywords:
        keys = {w[:7] for w in k.split()}   # electrochemistry ~ electrochemical; no repeated word
        if k and not keys & stems:
            terms.append(k)
            stems |= keys
        if len(terms) == n:
            break
    if not terms:
        return "Other" if misc else "Unlabelled"
    text = " · ".join(terms)
    return f"Other · {text}" if misc else text[0].upper() + text[1:]


def english_tags(label, keywords, n=12):
    """Keywords plus English label pieces; nothing translated."""
    pieces = [] if HANGUL.search(label or "") else [x.strip().lower() for x in re.split(r"[·,/()]", label or "") if x.strip()]
    en = [x for x in pieces if not MISC.search(x)] + [k.lower() for k in keywords]
    return {"en": list(dict.fromkeys(x for x in en if x))[:n], "ko": []}


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
    counts = Counter(t for r in index["researchers"] for topic in r["topics"] for t in topic.get("tags", {}).get("en", []))
    return [t for t, _ in counts.most_common(n)]
