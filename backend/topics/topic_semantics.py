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
from sklearn.feature_extraction.text import ENGLISH_STOP_WORDS, CountVectorizer, TfidfVectorizer

HERE = os.path.dirname(os.path.abspath(__file__))
TOKEN = r"[a-zA-Z][a-zA-Z-]{2,}"
STOP_EXTRA = {"networks", "network", "model", "models", "using", "based", "study", "results", "paper",
              "show", "data", "approach", "method", "methods", "analysis", "complex", "systems", "system",
              "new", "propose", "proposed", "effect", "effects", "role", "properties", "theory", "theoretical",
              "advanced", "research", "science", "applications", "application", "challenges", "programs", "evaluating", "impact"}

# Page boilerplate and affiliation words that some OpenAlex abstracts carry (scraped landing
# pages: "ORCID", "search for more papers by this author", addresses). Never a topic feature.
BOILER = {"orcid", "org", "author", "authors", "papers", "search", "article", "title", "abstract", "copyright",
          "rights", "reserved", "elsevier", "springer", "wiley", "email", "mail", "university", "univ", "institute",
          "college", "department", "dept", "korea", "seoul", "affiliation",
          "scholar", "google", "pubmed", "crossref", "doi", "http", "https", "www", "com",
          # LaTeX / MathML markup left in abstracts and titles
          "mathrm", "ensuremath", "mathbf", "mathit", "mathcal", "mathsf", "mathbb", "textit", "textbf", "textrm", "text",
          "mml", "mrow", "msub", "msup", "mfrac", "mover", "munder", "mtext", "mspace", "formula", "inline",
          "displaystyle", "emph", "sub", "sup",
          # non-English function words (German / French titles)
          "der", "die", "und", "eine", "des", "von", "zur", "mit", "les", "une", "sur", "pour"}


# Romanised Korean name syllables. A multi-word term made only of these ("yong choi",
# "sang kyu") is a person's name, not a topic feature.
KO_SYLLABLES = set("""
kim lee yi park pak choi choe jung jeong chung kang cho jo yoon yun jang chang lim im han oh seo suh shin sin kwon hwang
ahn an song yoo yu ryu hong jeon chun go ko moon mun yang son sohn bae baek paik heo hur nam sim shim noh roh ha kwak sung
seong cha joo ju woo koo ku min jin ji eom um chae won bang kong hyun hyeon ham byun byeon yeom yeo choo chu seok sun ma
gil yeon pyo myung myong ki ra wang ok yook maeng je tak kook
young yong sang hyung hyeong hyo hee hui jae soo su seung kyung kyeong kyu gyu ho hoon hun hwan hwa joon jun yeol yul
woong ung wook uk hyuk hyeok sik shik sook suk jong mi mee na nyeong ryeong rim jee eun un hye hae il dong doo du dae
tae geun keun gun kwang gwang chul cheol bum beom bok byung byeong chan cheon chun deok duk gyeong gyu hak han heon
hwi hyun in jeom jik jip kun mo mok mun nae nam pil pyeong rae ran rok seob sub seon shik sil sok sol soon sun tak
wan wha woon yeop yup yeoung yoong yook ryong ryang ri yeun eon sung seung jin min ho hyun
man kee ung jeung chul hwan gyu kyum ok
""".split())
KO_SURNAMES = set("""kim lee yi park pak choi choe jung jeong chung kang cho jo yoon yun jang chang lim im han oh seo suh
shin sin kwon hwang ahn an song yoo yu ryu hong jeon chun go ko moon mun yang son sohn bae baek paik heo hur nam sim shim
noh roh ha kwak sung seong cha joo ju woo koo ku min jin ji eom um chae won bang kong hyun hyeon ham byun byeon yeom yeo
choo chu seok rhee rhim rho""".split())


def _english_words(path="/usr/share/dict/words"):
    try:
        return {w.strip().lower() for w in open(path, encoding="utf-8", errors="ignore")}
    except OSError:
        return set()


ENGLISH = _english_words()


def ko_name(term):
    """Every word is a romanised name syllable (or two run together: "seungnam") and at least
    one is not an English word — "main chain" and "sun light" stay, "yong choi" goes."""
    toks = term.split()
    if len(toks) < 2:
        return False
    def name_word(w):  # "seong-chul", "seungnam", "yong"
        return all(x in KO_SYLLABLES or any(x[:i] in KO_SYLLABLES and x[i:] in KO_SYLLABLES for i in range(1, len(x)))
                   for x in w.split("-") if x)
    if all(w in KO_SURNAMES for w in toks):   # "kim kim", "lee ahn": author lists
        return True
    rest = [w for w in toks if w not in KO_SURNAMES]
    if len(rest) < len(toks) and all("-" in w and all(x and len(x) <= 6 and x not in ENGLISH for x in w.split("-")) for w in rest):
        return True                            # "jeong-heui lee": surname + hyphenated given name
    return all(name_word(w) for w in toks) and any(x not in ENGLISH for w in toks for x in w.split("-"))


def excluded(term, exclude):
    """A private stoplist phrase equals the term or any adjacent word pair in it (hyphens split words)."""
    if not exclude:
        return False
    toks = [x for x in re.split(r"[\s-]+", term) if len(x) > 1]   # initials ("c-h bond") are not name words
    return " ".join(toks) in exclude or any(f"{a} {b}" in exclude for a, b in zip(toks, toks[1:]))


def boiler(term):
    return any(w in BOILER or (w.startswith("korea") and w != "korean") for w in term.split()) or ko_name(term)


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


def ctfidf_terms(docs, n_terms=6, max_share=0.6, ngram=(1, 2), phrase_bonus=1.5, exclude=frozenset()):
    """{community: [texts]} → {community: [terms]}. Terms in ≥ max_share of communities
    are dropped first; with few communities idf alone does not suppress shared words.
    ``exclude``: phrases never used as terms (e.g. a private stoplist of researcher names).
    A recurring phrase ties with its own words on frequency, so multi-word terms get
    ``phrase_bonus``; the words of a chosen phrase are then skipped as substrings."""
    keys = list(docs)
    if not keys:
        return {}
    cv = CountVectorizer(stop_words="english", ngram_range=ngram, token_pattern=TOKEN)
    X = cv.fit_transform([" ".join(docs[k]) for k in keys]).toarray().astype(float)
    terms = np.array(cv.get_feature_names_out())
    generic = (X > 0).sum(axis=0) > max(1, math.floor(max_share * len(keys)))
    extra = np.array([(len(t.split()) == 1 and t in STOP_EXTRA) or boiler(t) or excluded(t, exclude) for t in terms])
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
    stop = sorted(ENGLISH_STOP_WORDS | BOILER)
    vec = TfidfVectorizer(stop_words=stop, token_pattern=TOKEN, max_features=max_terms, sublinear_tf=True)
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
