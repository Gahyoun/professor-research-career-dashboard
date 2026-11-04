---
name: topic-summaries
description: Write the English and Korean summaries for the research-topic corpus in the private topics DB (backend/topics/topic_corpus.py). Use when asked to summarize topics, fill in topic summaries, or run /topic-summaries after `topic_batch.py corpus`.
---

# Topic summaries from the corpus

The topic pipeline has already stored one text per research topic in the private topics DB
(`.private/topics_YEAR.sqlite`, table `summary_corpus`). Each text holds a topic's distinctive
terms, active period, papers per year and representative papers in publication order (date,
title, abstract excerpt). You write the summaries yourself from that text and submit them back.
Do not call the Claude API or `claude -p`, and do not look anything up on the web: the corpus
text is the only source.

## Start

```bash
python3 backend/topics/topic_corpus.py status   # progress and pending chunk numbers
python3 backend/topics/topic_corpus.py rules    # the summary rules — read them before writing
```

If the topics DB or corpus is missing, stop and tell the user to run
`python3 backend/topics/topic_batch.py all` first.

## Work loop for one chunk

1. `python3 backend/topics/topic_corpus.py next --chunk K` prints every pending topic of chunk K
   (about 20), each under `## id: <id>`.
2. For each topic write `summary_en` and `summary_ko` following the rules: the shared research
   problem, the systems studied and the approach, then how the theme developed over the years
   shown (when it began, when it was most active, what it moved toward). Paraphrase; never copy a
   paper title. No people, institutions, countries, journals or citation numbers.
3. Submit all of the chunk's summaries at once as JSON Lines, one object per topic:

   ```bash
   python3 backend/topics/topic_corpus.py submit - <<'JSONL'
   {"id": "<id>", "en": "<English summary>", "ko": "<한국어 요약>"}
   JSONL
   ```

4. The command reports each rejected id (empty field, or a paper title repeated). Rewrite only
   those and submit them again until the chunk reports nothing pending.

## Covering the whole corpus

There are usually thousands of chunks. Work through them in order with the loop above. When
there are more than a few chunks pending, hand out disjoint chunk ranges to subagents (for
example four at a time, each given a range such as chunks 0–49) with this file's loop and rules
in the brief; ask each to report only how many topics it submitted and any ids it could not
fix. Keep the paper text out of your own context. Run `status` between rounds to see what is
left; a chunk worked on twice is harmless because only pending topics are shown.

Stop when the user asks, or when `status` shows nothing pending. Then tell the user to run:

```bash
python3 backend/topics/topic_batch.py export
```
