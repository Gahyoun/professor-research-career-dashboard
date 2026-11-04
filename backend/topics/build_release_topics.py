#!/usr/bin/env python3
"""Real-data topic release: source DB → OpenAlex references → per-researcher alluvial.json.

Every step writes kept / dropped / changes files and appends to STEP_LOG.md in --work-dir,
which must be outside the public repository (it holds titles, DOIs and raw work ids).

  python3 -I backend/topics/build_release_topics.py select --private DIR --work-dir W
  python3 -I backend/topics/build_release_topics.py fetch  --work-dir W --cache C --env-file F
  python3 -I backend/topics/build_release_topics.py build  --private DIR --work-dir W --cache C \
      --dashboard public/data/dashboard.json

Then export with export_public_index.py --manifest W/manifest.txt.

Step 01 select   identity_decision=keep, KOAD namesake_paper excluded, journal types,
                 publication_year <= 2026 (2026 is the source snapshot and therefore partial).
Step 02 fetch    OpenAlex id, referenced_works, abstract, keywords, topics, cited_by_count,
                 venue in 100-id batches; resumable shards; the API key is read from --env-file
                 inside this process only and never printed.
Step 03 build    eras from the public dashboard career segments; weighted Louvain on the
                 bibliographic-coupling network: edge when c_ij ≥ 2 shared references, weight
                 w_ij = c_ij / sqrt(|R_i||R_j|) (Salton cosine), louvain_communities(weight="weight",
                 resolution=1.05, seed=4);
                 papers with no coupling edge and singleton communities form one residual
                 topic labelled "Other"; parent topic = best coupling from birth-era papers to
                 earlier-era papers (pipeline/scripts/branching.py rule). recip is not computed.
"""
import argparse, base64, csv, gzip, hashlib, hmac, json, math, os, re, sqlite3, sys, threading, time
import urllib.error, urllib.parse, urllib.request
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime
from pathlib import Path

JOURNAL_TYPES = ("article", "review", "letter", "editorial")
MAX_YEAR = 2026
BATCH = 100
SELECT = "id,referenced_works,abstract_inverted_index,keywords,topics,cited_by_count,primary_location"


def short(w):
    return (w or "").rstrip("/").rsplit("/", 1)[-1]


def log(work, step, lines):
    with open(work / "STEP_LOG.md", "a", encoding="utf-8") as fh:
        fh.write(f"\n## {step} — {datetime.now().isoformat(timespec='seconds')}\n")
        for line in lines:
            fh.write(f"- {line}\n")
    print("\n".join([step] + lines))


def source_db(private):
    return Path((private / "backend/cache/2026/source_db_path.txt").read_text().strip())


def anon_id(salt, uid):
    return "P-" + base64.b32encode(hmac.new(salt, uid.encode(), hashlib.sha256).digest()).decode().rstrip("=")[:10]


# ---------------------------------------------------------------- 01 select
def cmd_select(a):
    priv, work = Path(a.private), Path(a.work_dir)
    work.mkdir(parents=True, exist_ok=True)
    db = source_db(priv)
    con = sqlite3.connect(f"file:{db}?mode=ro&immutable=1", uri=True)
    koad = sqlite3.connect(f"file:{db.parent / 'identity_decisions.sqlite'}?mode=ro&immutable=1", uri=True)
    namesake = {(u, w) for u, w in koad.execute("SELECT professor_uid, work_id FROM work_decision WHERE decision='namesake_paper'")}
    kept, dropped, reasons = [], [], Counter()
    rows = con.execute("SELECT professor_uid, work_id, publication_year, work_type, identity_decision, doi, title "
                       "FROM work_authorship_evidence")
    for uid, wid, year, wtype, decision, doi, title in rows:
        reason = ("identity_not_keep" if decision != "keep" else
                  "koad_namesake" if (uid, wid) in namesake else
                  "non_journal_type" if wtype not in JOURNAL_TYPES else
                  "no_year" if year is None else
                  "after_2026" if year > MAX_YEAR else None)
        rec = {"professor_uid": uid, "work_id": short(wid), "year": year, "type": wtype}
        if reason:
            reasons[reason] += 1
            dropped.append({**rec, "reason": reason})
        else:
            kept.append({**rec, "doi": doi or "", "title": title or ""})
    for name, recs in (("01_selected.csv", kept), ("01_dropped.csv", dropped)):
        with open(work / name, "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=list(recs[0]))
            w.writeheader()
            w.writerows(recs)
    ids = sorted({r["work_id"] for r in kept})
    (work / "01_work_ids.txt").write_text("\n".join(ids) + "\n")
    years = Counter(r["year"] for r in kept)
    log(work, "Step 01 select", [
        f"source rows {len(kept) + len(dropped):,}; kept {len(kept):,}; dropped {len(dropped):,}",
        "dropped by reason: " + ", ".join(f"{k} {v:,}" for k, v in reasons.most_common()),
        f"professors with works {len({r['professor_uid'] for r in kept}):,}; distinct works {len(ids):,}",
        f"works in 2025 {years.get(2025, 0):,}; in 2026 (partial snapshot) {years.get(2026, 0):,}",
        "outputs: 01_selected.csv, 01_dropped.csv, 01_work_ids.txt"])


# ---------------------------------------------------------------- 02 fetch
def read_key(env_file):
    for line in Path(env_file).read_text().splitlines():
        m = re.match(r"\s*(?:export\s+)?OPENALEX_API_KEY=(.*)$", line)
        if m:
            v = m.group(1).strip()
            if v[:1] in "'\"" and v[-1:] == v[:1]:
                v = v[1:-1]
            return v.replace("\\", "") if v else None
    return None


def abstract_text(inv):
    if not inv:
        return ""
    n = max((p for ps in inv.values() for p in ps), default=-1) + 1
    words = [""] * n
    for word, ps in inv.items():
        for p in ps:
            if 0 <= p < n:
                words[p] = word
    return " ".join(w for w in words if w)


BOILERPLATE = re.compile(r"\borcid\b|more papers by this author|search for more papers|google scholar|pubmed|"
                         r"corresponding author|e-?mail|\S+@\S+\.\w+|\bdepartment of\b|\buniversity\b|"
                         # cover-art blurbs and notices name the authors ("in article number …, A, B and co-workers")
                         r"article number|co-?workers|\bet al\b|\b(back|front|inside)( front| back)? cover\b|frontispiece|"
                         r"cover (image|picture|art)|correction (for|to)\b|and colleagues|in memoriam|obituary", re.I)
MARKUP = re.compile(r"<[^>]{0,200}>|\\[a-zA-Z]+|\$[^$]{0,200}\$|[{}^_]")   # MathML tags, LaTeX commands, inline math, braces
COPYRIGHT = re.compile(r"(©|\(c\)\s*\d{4}|copyright\b|all rights reserved).*$", re.I | re.S)


def clean_abstract(text):
    """Scraped landing-page text (ORCID links, author search, addresses) is not an abstract:
    drop it. A trailing copyright line is cut."""
    if not text or BOILERPLATE.search(text):
        return ""
    text = MARKUP.sub(" ", COPYRIGHT.sub("", text))
    return re.sub(r"\s+", " ", text).strip()


def compact(w):
    src = ((w.get("primary_location") or {}).get("source") or {})
    return {"id": short(w["id"]), "refs": [short(r) for r in (w.get("referenced_works") or [])],
            "abstract": abstract_text(w.get("abstract_inverted_index")),
            "keywords": [k.get("display_name", "") for k in (w.get("keywords") or [])[:8]],
            "topics": [t.get("display_name", "") for t in (w.get("topics") or [])[:3]],
            "cited": w.get("cited_by_count") or 0, "venue": src.get("display_name") or ""}


def cmd_fetch(a):
    work, cache = Path(a.work_dir), Path(a.cache)
    cache.mkdir(parents=True, exist_ok=True)
    key = read_key(a.env_file)
    if not key:
        sys.exit("OPENALEX_API_KEY not found in --env-file")
    ids = (work / "01_work_ids.txt").read_text().split()
    batches = [ids[i:i + BATCH] for i in range(0, len(ids), BATCH)]
    todo = [i for i in range(len(batches)) if not (cache / f"b{i:05d}.jsonl.gz").exists()]
    lock, stats, t0 = threading.Lock(), Counter(), time.time()
    quota = {}

    def run(i):
        params = {"filter": "openalex:" + "|".join(batches[i]), "per-page": BATCH, "select": SELECT, "api_key": key}
        url = "https://api.openalex.org/works?" + urllib.parse.urlencode(params)
        for attempt in range(6):
            try:
                with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "professor-career-dashboard/1"}), timeout=120) as r:
                    data = json.loads(r.read())
                    with lock:
                        quota["remaining"] = r.headers.get("X-RateLimit-Remaining")
                        quota["limit"] = r.headers.get("X-RateLimit-Limit")
                break
            except urllib.error.HTTPError as e:
                if e.code in (401, 403):
                    raise SystemExit(f"OpenAlex refused the key (HTTP {e.code})")
                time.sleep(min(60, 2 ** attempt * (5 if e.code == 429 else 1)))
            except Exception:
                time.sleep(2 ** attempt)
        else:
            with lock:
                stats["failed_batches"] += 1
            return
        tmp = cache / f"b{i:05d}.jsonl.gz.tmp"
        with gzip.open(tmp, "wt", encoding="utf-8") as fh:
            for w in data.get("results", []):
                fh.write(json.dumps(compact(w), ensure_ascii=False) + "\n")
        tmp.rename(cache / f"b{i:05d}.jsonl.gz")
        with lock:
            stats["batches"] += 1
            stats["works"] += len(data.get("results", []))
            if stats["batches"] % 100 == 0:
                print(f"{stats['batches']}/{len(todo)} batches, {time.time() - t0:.0f}s, quota remaining {quota.get('remaining')}", flush=True)

    with ThreadPoolExecutor(a.threads) as ex:
        for f in as_completed([ex.submit(run, i) for i in todo]):
            f.result()
    got = set()
    for i in range(len(batches)):
        p = cache / f"b{i:05d}.jsonl.gz"
        if p.exists():
            with gzip.open(p, "rt", encoding="utf-8") as fh:
                got |= {json.loads(line)["id"] for line in fh}
    missing = sorted(set(ids) - got)
    (work / "02_missing_in_openalex.txt").write_text("\n".join(missing) + ("\n" if missing else ""))
    log(work, "Step 02 fetch", [
        f"batches {len(batches):,} ({len(todo):,} fetched this run, {stats['failed_batches']} failed); {time.time() - t0:.0f}s",
        f"works requested {len(ids):,}; returned {len(got):,}; missing {len(missing):,} (02_missing_in_openalex.txt — merged or withdrawn ids)",
        f"daily quota after run: remaining {quota.get('remaining')} of {quota.get('limit')}",
        f"cache: {cache} (outside the repo)"])


# ---------------------------------------------------------------- 03 build
def load_cache(cache):
    out = {}
    for p in sorted(Path(cache).glob("b*.jsonl.gz")):
        with gzip.open(p, "rt", encoding="utf-8") as fh:
            for line in fh:
                w = json.loads(line)
                out[w["id"]] = w
    return out


def eras_of(prof):
    """Public dashboard career segments → [{label, start, end}] in time order."""
    out = []
    for c in sorted(prof.get("career") or [], key=lambda c: (c.get("start_year") or 0, c.get("end_year") or 9999)):
        s, e = c.get("start_year"), c.get("end_year")
        span = f"{s or ''}–{e or ''}" if e != s else f"{s}"
        out.append({"label": f"{c.get('institution') or 'Unknown'} · {c.get('stage') or 'position'} ({span})", "start": s, "end": e})
    return out or [{"label": "All years", "start": None, "end": None}]


def era_index(eras, year):
    """Latest segment containing the year; before the first → 0; gaps → latest started segment."""
    found = None
    for i, e in enumerate(eras):
        if (e["start"] is None or e["start"] <= year) and (e["end"] is None or year <= e["end"]):
            found = i
    if found is not None:
        return found
    started = [i for i, e in enumerate(eras) if e["start"] is not None and e["start"] <= year]
    return started[-1] if started else 0


def cosine(ra, rb):
    return len(ra & rb) / math.sqrt(len(ra) * len(rb)) if ra and rb else 0.0


def communities(ids, refs, min_shared, resolution, seed):
    import networkx as nx
    G = nx.Graph()
    G.add_nodes_from(ids)
    citing = defaultdict(list)
    for i in ids:
        for r in refs[i]:
            citing[r].append(i)
    shared = Counter()
    for papers in citing.values():
        if 1 < len(papers):
            for x in range(len(papers)):
                for y in range(x + 1, len(papers)):
                    shared[(papers[x], papers[y]) if papers[x] < papers[y] else (papers[y], papers[x])] += 1
    for (i, j), n in shared.items():
        if n >= min_shared:
            G.add_edge(i, j, weight=n / math.sqrt(len(refs[i]) * len(refs[j])))
    com = nx.community.louvain_communities(G, weight="weight", seed=seed, resolution=resolution)
    return [c for c in com], G


def build_one(prof, rows, oa, args):
    """rows: [{work_id, year, doi, title}] for one professor → (seeds, alluvial, stats)."""
    eras = eras_of(prof)
    works = {}
    for r in rows:
        w = oa.get(r["work_id"])
        if w is None or r["work_id"] in works:
            continue
        works[r["work_id"]] = {**r, **w, "year": int(r["year"])}
    ids = sorted(works, key=lambda i: (works[i]["year"], i))
    refs = {i: set(works[i]["refs"]) for i in ids}
    com, G = communities(ids, refs, args.min_shared, args.resolution, args.seed)
    real = sorted([c for c in com if len(c) >= 2], key=lambda c: (-len(c), min(works[i]["year"] for i in c)))
    residual = sorted(i for c in com if len(c) < 2 for i in c)
    assign, labels = {}, {}
    for k, c in enumerate(real):
        for i in c:
            assign[i] = k
        labels[k] = None
    if residual:
        k = len(real)
        for i in residual:
            assign[i] = k
        labels[k] = "Other"
    papers = [{"id": i, "title": works[i]["title"], "year": works[i]["year"], "era": era_index(eras, works[i]["year"]),
               "topic": assign[i], "cited": works[i]["cited"], "doi": works[i]["doi"] or None,
               "venue": works[i]["venue"] or None} for i in ids]
    by_topic = defaultdict(list)
    for p in papers:
        by_topic[p["topic"]].append(p)
    topics = []
    for k in sorted(by_topic):
        ps = by_topic[k]
        birth = min(p["era"] for p in ps)
        best = None
        if labels[k] != "Other":
            earlier = [r for r in papers if r["era"] < birth and r["topic"] != k and labels[r["topic"]] != "Other"]
            for q in (x for x in ps if x["era"] == birth):
                for r in earlier:
                    s = cosine(refs[q["id"]], refs[r["id"]])
                    if best is None or s > best[2]:
                        best = (r, q, s)
        parent = ({"from": best[0]["topic"], "sim": round(best[2], 3), "from_year": best[0]["year"], "to_year": best[1]["year"]}
                  if best and best[2] > 0 else None)
        topics.append({"id": k, "label": labels[k], "size": len(ps), "birth": birth,
                       "birth_year": min(p["year"] for p in ps), "parent": parent})
    era_span = []
    for i, e in enumerate(eras):
        ys = [p["year"] for p in papers if p["era"] == i]
        era_span.append({**e, "n": len(ys)})
    seeds = {"works": [{"id": i, "title": works[i]["title"], "referenced_works": works[i]["refs"],
                        "abstract": clean_abstract(works[i]["abstract"]),
                        "topics": [{"display_name": t} for t in works[i]["topics"]],
                        "keywords": [{"display_name": t} for t in works[i]["keywords"]]} for i in ids]}
    alluvial = {"eras": [e["label"] for e in eras], "era_span": era_span, "topics": topics, "papers": papers,
                "recip": [], "fetched_at": args.fetched_at}
    stats = {"selected": len({r["work_id"] for r in rows}), "kept": len(ids), "topics": len(real),
             "residual": len(residual), "no_refs": sum(1 for i in ids if not refs[i]), "edges": G.number_of_edges(),
             "abstract_dropped": sum(1 for i in ids if works[i]["abstract"] and not clean_abstract(works[i]["abstract"]))}
    return seeds, alluvial, stats


def name_terms(db):
    con = sqlite3.connect(f"file:{db}?mode=ro&immutable=1", uri=True)
    raw = [n for n, in con.execute("SELECT name FROM professors")]
    for (alts,) in con.execute("SELECT name_alternatives_json FROM professors"):
        try:
            raw += [x for x in json.loads(alts or "[]") if isinstance(x, str)]
        except ValueError:
            pass
    raw += [n for n, in con.execute("SELECT display_name FROM openalex_author_profiles")]
    out = set()
    for n in raw:
        toks = [t for t in re.split(r"[^a-z]+", (n or "").lower()) if len(t) > 1]   # initials dropped
        if len(toks) < 2:
            continue
        for seq in (toks, toks[::-1]):
            out.add(" ".join(seq))
            out |= {" ".join(seq[i:i + 2]) for i in range(len(seq) - 1)}
            if len(seq) == 3:
                out.add(f"{seq[0]} {seq[2]}")
    return out


def cmd_build(a):
    priv, work = Path(a.private), Path(a.work_dir)
    salt = (priv / ".private" / "anon_salt.bin").read_bytes()
    public = {p["id"]: p for p in json.load(open(a.dashboard, encoding="utf-8"))["professors"]}
    oa = load_cache(a.cache)
    per = defaultdict(list)
    with open(work / "01_selected.csv", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            per[r["professor_uid"]].append(r)
    out_root = work / "researchers"
    out_root.mkdir(exist_ok=True)
    manifest, stat_rows, dropped = [], [], []
    for uid in sorted(per):
        anon = anon_id(salt, uid)
        rows = per[uid]
        if anon not in public:
            dropped.append({"anon_id": anon, "reason": "not_in_public_dashboard", "works": len(rows)})
            continue
        seeds, alluvial, st = build_one(public[anon], rows, oa, a)
        if st["kept"] < a.min_works:
            dropped.append({"anon_id": anon, "reason": f"fewer_than_{a.min_works}_works_after_fetch", "works": st["kept"]})
            continue
        d = out_root / anon
        d.mkdir(exist_ok=True)
        json.dump(seeds, open(d / "seeds.json", "w", encoding="utf-8"), ensure_ascii=False)
        json.dump(alluvial, open(d / "alluvial.json", "w", encoding="utf-8"), ensure_ascii=False)
        manifest.append(f"{d}={anon}")
        stat_rows.append({"anon_id": anon, **st})
    (work / "manifest.txt").write_text("\n".join(manifest) + "\n")
    # Private stoplist for export (--exclude-terms): romanised researcher names, so a name that
    # slips through an abstract never becomes a topic term. Stays in the work dir, never published.
    (work / "03_name_terms.txt").write_text("\n".join(sorted(name_terms(source_db(priv)))) + "\n")
    for name, recs in (("03_researchers.csv", stat_rows), ("03_dropped_researchers.csv", dropped)):
        if recs:
            with open(work / name, "w", newline="", encoding="utf-8") as fh:
                w = csv.DictWriter(fh, fieldnames=list(recs[0]))
                w.writeheader()
                w.writerows(recs)
    tot = Counter()
    for s in stat_rows:
        tot.update({k: v for k, v in s.items() if k != "anon_id"})
    log(work, "Step 03 build", [
        f"researchers built {len(stat_rows):,}; dropped {len(dropped):,} (03_dropped_researchers.csv)",
        f"paper rows selected {tot['selected']:,}; kept with OpenAlex record {tot['kept']:,}; without references {tot['no_refs']:,}",
        f"topics (≥2 papers) {tot['topics']:,}; papers in residual 'Other' topic {tot['residual']:,}",
        f"Louvain resolution {a.resolution}, min shared refs {a.min_shared}, seed {a.seed}; eras from public dashboard career",
        f"abstracts dropped as page boilerplate (ORCID/author search/address text) {tot['abstract_dropped']:,}",
        "outputs: researchers/<anon>/{seeds,alluvial}.json, manifest.txt, 03_researchers.csv"])


def main():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("select")
    s.add_argument("--private", required=True)
    s.add_argument("--work-dir", required=True)
    f = sub.add_parser("fetch")
    f.add_argument("--work-dir", required=True)
    f.add_argument("--cache", required=True)
    f.add_argument("--env-file", required=True)
    f.add_argument("--threads", type=int, default=4)
    b = sub.add_parser("build")
    b.add_argument("--private", required=True)
    b.add_argument("--work-dir", required=True)
    b.add_argument("--cache", required=True)
    b.add_argument("--dashboard", default="public/data/dashboard.json")
    b.add_argument("--min-works", type=int, default=1)
    b.add_argument("--min-shared", type=int, default=2)
    b.add_argument("--resolution", type=float, default=1.05)
    b.add_argument("--seed", type=int, default=4)
    b.add_argument("--fetched-at", default=str(date.today()))
    a = p.parse_args()
    {"select": cmd_select, "fetch": cmd_fetch, "build": cmd_build}[a.cmd](a)


if __name__ == "__main__":
    main()
