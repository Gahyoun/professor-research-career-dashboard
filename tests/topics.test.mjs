import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { parseEraLabel, normalizeTopicIndex, layoutAlluvial, queryResearchers, orderedTopics, eraOfYear, validatePaperTitles, TOPIC_SCHEMA } from '../work/test-dist/topics.js';

const researcher = (extra = {}) => ({
  id: 'P-AAAAAAAAAA', subject: 'physics', institution: 'Example University',
  eras: ['기관 A (~2010)', '기관 B (2011-13)', '기관 C (2012-16)', '예시대학교 물리 (2020-)'],
  topics: [
    { id: 0, label: '네트워크 구조', size: 4, birth_year: 2006, parent: null },
    { id: 1, label: '메조스케일', size: 3, birth_year: 2011, parent: { from: 0, sim: 0.2, from_year: 2008, to_year: 2011 } },
    { id: 2, label: '모빌리티', size: 1, birth_year: 2021, parent: null },
  ],
  papers: [
    { year: 2006, topic: 0, era: 0, cited: 10 }, { year: 2006, topic: 0, era: 0, cited: 1 }, { year: 2008, topic: 0, era: 0, cited: 3 },
    { year: 2011, topic: 1, era: 1, cited: 5 }, { year: 2013, topic: 1, era: 2, cited: 0 }, { year: 2014, topic: 0, era: 2, cited: 2 },
    { year: 2015, topic: 1, era: 2, cited: 7 }, { year: 2021, topic: 2, era: 3, cited: 1 },
  ],
  recip: [{ from_topic: 0, to_topic: 1, from_year: 2006, to_year: 2013, x_year: 2009 }],
  ...extra,
});
const index = (people) => ({ schema: TOPIC_SCHEMA, source: 'release', generated_at: '2026-11-03', method: {}, researchers: people });

test('era labels parse open, closed and two-digit spans', () => {
  assert.deepEqual(parseEraLabel('기관 A (~2010)'), { start: null, end: 2010 });
  assert.deepEqual(parseEraLabel('기관 B (2011-13)'), { start: 2011, end: 2013 });
  assert.deepEqual(parseEraLabel('예시대학교 물리 (2020-)'), { start: 2020, end: null });
  assert.deepEqual(parseEraLabel('No years'), { start: null, end: null });
});

test('public index rejects paper titles and unknown schema', () => {
  assert.throws(() => normalizeTopicIndex({ schema: 'x', researchers: [] }));
  const leaky = researcher({ papers: [{ year: 2006, topic: 0, cited: 1, title: 'secret' }] });
  assert.throws(() => normalizeTopicIndex(index([leaky])), /titles/);
});

test('normalized index keeps only papers whose topic exists', () => {
  const raw = researcher();
  raw.papers.push({ year: 2016, topic: 9, era: 2, cited: 1 });
  const r = normalizeTopicIndex(index([raw])).researchers[0];
  assert.equal(r.papers.length, 8);
  assert.equal(r.eras[1].start, 2011);
  assert.deepEqual(orderedTopics(r).map(t => t.id), [0, 1, 2]);
});

test('year layout places every paper exactly once and branches downward from the parent', () => {
  const r = normalizeTopicIndex(index([researcher()])).researchers[0];
  for (const mode of ['year', 'era']) {
    const layout = layoutAlluvial(r, mode);
    assert.equal(layout.placed + layout.unplaced, r.papers.length);
    assert.equal(layout.dots.reduce((s, d) => s + d.count, 0), layout.placed);
    assert.equal(layout.ribbons.length, 3);
    assert.equal(layout.branches.length, 1);
    assert.equal(layout.births.filter(b => b.independent).length, 2);
    const lanes = layout.lanes.map(l => l.mid);
    assert.deepEqual([...lanes].sort((a, b) => a - b), lanes);
  }
  const years = layoutAlluvial(r, 'year');
  assert.equal(years.unplaced, 0);
  assert.equal(years.columns.length, 2021 - 2006 + 1);
  assert.equal(years.arcs.length, 1);
  assert.ok(years.bands.length >= 3 && years.bandRows === 2, 'overlapping eras stack into a second band row');
});

test('era of year follows the latest containing era', () => {
  const r = normalizeTopicIndex(index([researcher()])).researchers[0];
  assert.equal(eraOfYear(r, 2011), 1);
  assert.equal(eraOfYear(r, 2012), 2, "overlap goes to the later era");
  assert.equal(eraOfYear(r, 2013), 2);
  assert.equal(eraOfYear(r, 2018), null);
});

test('query matches names only when provided and groups institutions', () => {
  const entries = [
    { id: 'P-AAAAAAAAAA', name: '홍길동', alias: null, subject: 'physics', institution: 'Example National University', institutionText: 'Example National University 예시국립대학교', hasTopics: true },
    { id: 'P-BBBBBBBBBB', name: null, alias: null, subject: 'chemistry', institution: 'Example National University', institutionText: 'Example National University 예시국립대학교', hasTopics: false },
  ];
  const byName = queryResearchers(entries, '홍길동', {});
  assert.deepEqual(byName.researchers.map(e => e.id), ['P-AAAAAAAAAA']);
  const byInstitution = queryResearchers(entries, '예시국립', {});
  assert.equal(byInstitution.institutions[0].count, 2);
  assert.equal(byInstitution.institutions[0].withTopics, 1);
  assert.equal(byInstitution.researchers[0].id, 'P-AAAAAAAAAA');
  assert.equal(queryResearchers(entries.map(e => ({ ...e, name: null })), '홍길동', {}).researchers.length, 0);
});

test('title bundle keeps only DOI links', () => {
  const titles = validatePaperTitles({ X: [{ year: 2006, topic: 0, title: 'A', doi: 'javascript:alert(1)' }, { year: 2007, topic: 0, title: 'B', doi: 'https://doi.org/10.1/x' }] });
  assert.equal(titles.X[0].doi, null);
  assert.equal(titles.X[1].doi, 'https://doi.org/10.1/x');
});

test('shipped topic index is valid and title-free', () => {
  const raw = JSON.parse(readFileSync('public/data/topics/index.json', 'utf8'));
  const parsed = normalizeTopicIndex(raw);
  assert.ok(parsed.researchers.length > 0);
  for (const r of parsed.researchers) assert.equal(layoutAlluvial(r, 'year').unplaced, 0);
});

import { searchTopics, expandTerms, tokenizeQuery, layoutMulti, seriesFromHits, tagCloud } from '../work/test-dist/topics.js';

const shipped = () => normalizeTopicIndex(JSON.parse(readFileSync('public/data/topics/index.json', 'utf8')));

test('korean query expands through the glossary and ranks the matching topic first', () => {
  const index = shipped();
  assert.deepEqual(tokenizeQuery('동기화, 전력망!'), ['동기화', '전력망']);
  assert.ok(expandTerms(['동기화'], index.semantic).includes('synchronization'));
  const ko = searchTopics(index, '동기화');
  const en = searchTopics(index, 'synchronization oscillator');
  assert.equal(ko.method, 'semantic');
  assert.equal(ko.hits[0].topic.label, '동기화·안정성');
  assert.equal(en.hits[0].topic.label, '동기화·안정성');
  assert.equal(searchTopics(index, '').hits.length, 0);
});

test('topic tags are bilingual and the tag cloud counts korean tags', () => {
  const index = shipped();
  for (const r of index.researchers) for (const t of r.topics) if (!/기타/.test(t.label)) {
    assert.ok(t.tags.ko.length > 0 && t.tags.en.length > 0, `${t.label} has both languages`);
    assert.ok(t.keywords.length > 0);
  }
  assert.ok(tagCloud(index).every(c => c.count >= 1));
});

test('multi layout keeps every selected paper in stack and overlay modes', () => {
  const index = shipped();
  const hits = searchTopics(index, 'network').hits.slice(0, 5);
  const series = seriesFromHits(hits, id => id);
  const papers = series.reduce((sum, s) => sum + [...s.counts.values()].reduce((a, b) => a + b, 0), 0);
  for (const mode of ['stack', 'overlay']) {
    const layout = layoutMulti(series, mode);
    assert.equal(layout.shapes.length, series.length);
    assert.equal(layout.lanes.reduce((sum, l) => sum + l.total, 0), papers);
  }
  assert.equal(layoutMulti(series, 'overlay').totals.reduce((s, t) => s + t.n, 0), papers);
});

import { normalizeInfoFlow, conditionalEntropies } from '../work/test-dist/topics.js';

test('info-flow block parses measures, drops unknown topics and bad windows', () => {
  const info = normalizeInfoFlow({
    estimator: 'Miller–Madow, bits', width: 3, null: { kind: 'within-window topic-label permutation', n: 50 },
    windows: [{ start: 2001, end: 2003, n: 4 }, { start: 'x' }],
    transitions: [
      { from: [2001, 2003], to: [2004, 2006], n_from: 4, n_to: 5, diverge: 0.5, diverge_ci: [0.2, 0.9], diverge_null: [1.1, 0.2], diverge_z: -3,
        continuity: 1.2, nmi: 0.6, birth_share: 0.2, ending_share: 0, sparse: true,
        flows: [[0, 1, 2], [0, 0, 2], [null, 1, 1], [7, 1, 1], [0, null, 1]] },
      { from: [2004], to: [2007, 2009] },
    ],
    summary: { diverge: 0.5, transitions: 1 },
  }, new Set([0, 1]));
  assert.equal(info.windows.length, 1);
  assert.equal(info.transitions.length, 1);
  const t = info.transitions[0];
  assert.deepEqual(t.measures.diverge, { value: 0.5, ci: [0.2, 0.9], null: [1.1, 0.2], z: -3 });
  assert.equal(t.measures.merge, undefined);
  assert.equal(t.flows.length, 4);                       // topic 7 is not in the researcher's topics
  assert.deepEqual(info.summary, { diverge: 0.5 });
  assert.equal(normalizeInfoFlow(null, new Set()), null);
});

test('per-topic branching and merging entropies from flows', () => {
  const flows = [{ from: 0, to: 1, mass: 2 }, { from: 0, to: 2, mass: 2 }, { from: 3, to: 1, mass: 4 }, { from: null, to: 2, mass: 1 }];
  const branching = Object.fromEntries(conditionalEntropies(flows, 'from').map(r => [String(r.topic), r]));
  assert.equal(branching['0'].bits, 1);
  assert.equal(branching['0'].partners, 2);
  assert.equal(branching['3'].bits, 0);
  const merging = Object.fromEntries(conditionalEntropies(flows, 'to').map(r => [String(r.topic), r]));
  assert.ok(Math.abs(merging['1'].bits - (-(1 / 3) * Math.log2(1 / 3) - (2 / 3) * Math.log2(2 / 3))) < 1e-12);
});

test('shipped demo index carries info-flow measures for every researcher', () => {
  for (const r of shipped().researchers) {
    assert.ok(r.info && r.info.transitions.length > 0, r.id);
    for (const t of r.info.transitions) {
      const { diverge, merge, continuity } = t.measures;
      assert.ok(diverge.value >= 0 && merge.value >= 0 && continuity.value >= 0);
      if (t.measures.diverge_norm) assert.ok(t.measures.diverge_norm.value <= 1);
    }
  }
});
