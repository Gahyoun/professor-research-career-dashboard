#!/usr/bin/env python3
"""Topic summary corpus ↔ Claude Code.

``topic_batch.py corpus`` stores one text per topic (distinctive terms, active period, papers per
year, representative papers with dates, titles and abstract excerpts) in the private topics DB.
A Claude Code session reads it in chunks, writes the summaries itself and submits them back;
this script validates and stores them. Nothing here calls a model.

  python3 backend/topics/topic_corpus.py status            # progress and pending chunks
  python3 backend/topics/topic_corpus.py rules             # the summary rules to follow
  python3 backend/topics/topic_corpus.py next [--chunk K]  # pending topics of one chunk
  python3 backend/topics/topic_corpus.py submit FILE       # JSONL {"id", "en", "ko"} (FILE or - for stdin)

A summary is stored only when both languages are present and it does not repeat a whole paper
title (or eight consecutive title words); rejected ones are reported so they can be rewritten.
"""
import argparse
import json
import os
import sqlite3
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import topic_batch as tb  # noqa: E402

PENDING = """
  SELECT c.members_hash, c.chunk, c.prompt, c.titles FROM summary_corpus c
  WHERE c.prompt_version=? AND NOT EXISTS (
    SELECT 1 FROM summaries s WHERE s.members_hash=c.members_hash AND s.status='ok' AND s.prompt_version=?)
"""


def connect(a):
    path = Path(a.topics_db) if a.topics_db else Path(a.project_root) / ".private" / f"topics_{a.year}.sqlite"
    if not path.exists():
        raise SystemExit(f"topics DB not found: {path} — run topic_batch.py works/fetch/cluster/corpus first")
    return tb.open_topics(path)


def pending(con, chunk=None):
    q = PENDING + (" AND c.chunk=?" if chunk is not None else "") + " ORDER BY c.chunk, c.members_hash"
    args = [tb.PROMPT_VERSION, tb.PROMPT_VERSION] + ([chunk] if chunk is not None else [])
    return con.execute(q, args).fetchall()


def cmd_status(con, a):
    total = con.execute("SELECT COUNT(*) FROM summary_corpus WHERE prompt_version=?", (tb.PROMPT_VERSION,)).fetchone()[0]
    rows = pending(con)
    by_chunk = Counter(r[1] for r in rows)
    statuses = dict(con.execute("""SELECT s.status, COUNT(*) FROM summaries s JOIN summary_corpus c USING(members_hash)
                                   WHERE s.prompt_version=? GROUP BY s.status""", (tb.PROMPT_VERSION,)).fetchall())
    print(f"corpus (prompt v{tb.PROMPT_VERSION}): {total:,} topics, {total - len(rows):,} done, {len(rows):,} pending "
          f"in {len(by_chunk):,} chunks; stored statuses {statuses or '{}'}")
    if by_chunk:
        shown = sorted(by_chunk.items())[:a.list]
        print("pending chunks (chunk:topics): " + " ".join(f"{k}:{v}" for k, v in shown) + (" …" if len(by_chunk) > a.list else ""))


def cmd_rules(con, a):
    print(tb.SUMMARY_SYSTEM)
    print('\nSubmit one JSON object per line: {"id": "<topic id>", "en": "<summary_en>", "ko": "<summary_ko>"}')


def cmd_next(con, a):
    chunk = a.chunk
    if chunk is None:
        first = pending(con)
        if not first:
            print("nothing pending — run 'status', then topic_batch.py export")
            return
        chunk = first[0][1]
    rows = pending(con, chunk)[:a.n] if a.n else pending(con, chunk)
    if not rows:
        print(f"chunk {chunk}: nothing pending")
        return
    print(f"# chunk {chunk}: {len(rows)} pending topics (prompt v{tb.PROMPT_VERSION})")
    print('# For each topic write {"id": ..., "en": ..., "ko": ...} following `topic_corpus.py rules`, then submit the JSONL.\n')
    for members_hash, _, prompt, _ in rows:
        print(f"## id: {members_hash}\n{prompt}\n")


def cmd_submit(con, a):
    text = sys.stdin.read() if a.file == "-" else Path(a.file).read_text(encoding="utf-8")
    corpus = {h: json.loads(t) for h, t in con.execute(
        "SELECT members_hash, titles FROM summary_corpus WHERE prompt_version=?", (tb.PROMPT_VERSION,))}
    rows, problems = [], []
    for n, line in enumerate(text.splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError as e:
            problems.append(f"line {n}: not JSON ({e.msg})")
            continue
        h = str(item.get("id") or "").strip()
        if h not in corpus:
            problems.append(f"line {n}: unknown id {h!r}")
            continue
        row = tb.judge(h, item.get("en"), item.get("ko"), corpus[h], a.model)
        rows.append(row)
        if row[1] != "ok":
            problems.append(f"{h}: {row[1]} — rewrite and resubmit" + (" (repeats a paper title)" if row[1] == "rejected_title_overlap" else ""))
    tb.store_summaries(con, rows)
    counts = Counter(r[1] for r in rows)
    print(f"submitted {len(rows)}: " + ", ".join(f"{k} {v}" for k, v in sorted(counts.items())))
    for p in problems:
        print("  " + p)
    left = len(pending(con))
    print(f"pending topics left: {left:,}")
    if problems:
        sys.exit(1)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("command", choices=["status", "rules", "next", "submit"])
    p.add_argument("file", nargs="?", default="-", help="submit: JSONL file, or - for stdin")
    p.add_argument("--year", default=os.environ.get("RELEASE_YEAR", "2026"))
    p.add_argument("--project-root", default=str(tb.ROOT))
    p.add_argument("--topics-db")
    p.add_argument("--chunk", type=int)
    p.add_argument("--n", type=int, default=0, help="next: at most N topics")
    p.add_argument("--list", type=int, default=40, help="status: chunks to list")
    p.add_argument("--model", default="claude-code", help="submit: label stored with the summaries")
    a = p.parse_args(argv)
    con = connect(a)
    try:
        {"status": cmd_status, "rules": cmd_rules, "next": cmd_next, "submit": cmd_submit}[a.command](con, a)
    finally:
        con.close()


if __name__ == "__main__":
    main()
