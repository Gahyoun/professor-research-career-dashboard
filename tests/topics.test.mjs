import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { normalizeInfoFlow as parseInfo, parseEraLabel, normalizeTopicIndex, layoutAlluvial, queryResearchers, orderedTopics, topicDepths, topicColors, eraOfYear, validatePaperTitles, validateTitleRows, doiText, normalizeCurated, curatedFor, curatedSearch, bandTextWidth, fitBandText, deriveTags, TOPIC_SCHEMA } from '../work/test-dist/topics.js';

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

test('compact paper columns and derived tags read the same as row objects', () => {
  const rows = researcher();
  rows.topics[1] = { ...rows.topics[1], label: 'Mesoscale · Other things', keywords: ['Community Detection', 'mesoscale'], tags: { ko: [], en: ['mesoscale', 'community detection'] } };
  const cols = { ...rows, papers: undefined, topics: rows.topics.map(t => ({ ...t, tags: undefined })),
    paper_cols: Object.fromEntries(['year', 'topic', 'era', 'cited'].map(k => [k, rows.papers.map(p => p[k])])) };
  delete cols.papers;
  cols.topics.forEach(t => delete t.tags);
  const a = normalizeTopicIndex(index([rows])).researchers[0], b = normalizeTopicIndex(index([cols])).researchers[0];
  assert.deepEqual(b.papers, a.papers);
  assert.deepEqual(b.topics[1].tags, a.topics[1].tags);
  assert.deepEqual(deriveTags('네트워크 구조', ['Hub']), { ko: [], en: ['hub'] });
  assert.throws(() => normalizeTopicIndex(index([{ ...cols, paper_cols: { ...cols.paper_cols, title: ['secret'] } }])), /unexpected paper columns/);
});

test('normalized index keeps only papers whose topic exists', () => {
  const raw = researcher();
  raw.papers.push({ year: 2016, topic: 9, era: 2, cited: 1 });
  const r = normalizeTopicIndex(index([raw])).researchers[0];
  assert.equal(r.papers.length, 8);
  assert.equal(r.eras[1].start, 2011);
  assert.deepEqual(orderedTopics(r).map(t => t.id), [0, 1, 2]);
});

test('lanes follow the time-axis tree: children under their parent, Other last, colours by birth', () => {
  const p = (from) => ({ from, sim: 0.1, from_year: 2008, to_year: 2012 });
  const raw = researcher({
    topics: [
      { id: 0, label: 'Other · misc', size: 9, birth_year: 2004, parent: null },
      { id: 1, label: 'Root A', size: 5, birth_year: 2006, parent: null },
      { id: 2, label: 'Root B', size: 6, birth_year: 2008, parent: null },
      { id: 3, label: 'Child of A', size: 2, birth_year: 2014, parent: p(1) },
      { id: 4, label: 'Grandchild', size: 1, birth_year: 2016, parent: p(3) },
      { id: 5, label: 'Early child of A', size: 2, birth_year: 2010, parent: p(1) },
      { id: 6, label: 'Loop X', size: 1, birth_year: 2018, parent: p(7) },
      { id: 7, label: 'Loop Y', size: 1, birth_year: 2019, parent: p(6) },
    ],
    papers: [0, 1, 2, 3, 4, 5, 6, 7].map(topic => ({ year: 2004 + topic * 2, topic, era: 0, cited: 0 })),
    recip: [],
  });
  const r = normalizeTopicIndex(index([raw])).researchers[0];
  assert.deepEqual(orderedTopics(r).map(t => t.id), [1, 5, 3, 4, 2, 6, 7, 0]);
  const depth = topicDepths(r);
  assert.deepEqual([1, 5, 3, 4, 2, 6, 7].map(id => depth.get(id)), [0, 1, 1, 2, 0, 0, 1]);
  const layout = layoutAlluvial(r, 'year');
  assert.deepEqual(layout.lanes.map(l => l.depth), [0, 1, 1, 2, 0, 0, 1, 0]);
  assert.equal(layout.branches.length, 5);
  assert.ok(!layout.births.find(b => b.topic === 0).independent);   // Other is a residual bucket, not a new topic
  const colors = topicColors(r);
  assert.equal(colors.get(1), topicColors(normalizeTopicIndex(index([{ ...raw, topics: raw.topics.map(t => ({ ...t, parent: null })) }])).researchers[0]).get(1));
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

test('long overlapping era labels get their own room in each band row', () => {
  const eras = [
    'Seoul National University · doctoral (2006-2010)',
    'University of Waterloo · postdoc (2010-2011)',
    'Government of the Republic of Korea · faculty (2011-2012)',
    'Korea Electronics Technology Institute · researcher (2011-2013)',
    'Seoul National University · postdoc (2014-2015)',
    'Incheon National University · faculty (2016-)',
  ];
  const papers = Array.from({ length: 2025 - 2006 + 1 }, (_, i) => ({ year: 2006 + i, topic: 0, era: 0, cited: 0 }));
  const r = normalizeTopicIndex(index([researcher({ eras, papers, recip: [],
    topics: [{ id: 0, label: 'Ionic liquids', size: papers.length, birth_year: 2006, parent: null }] })])).researchers[0];
  for (const columnWidth of [34, 44, 72]) {
    const { bands, width } = layoutAlluvial(r, 'year', { columnWidth });
    assert.equal(bands.length, eras.length);
    for (const band of bands) {
      assert.ok(band.extent >= band.width, 'label room covers the band');
      assert.ok(band.x + band.extent <= width, 'label room stays inside the chart');
      assert.ok(bandTextWidth(band.text) <= band.extent - 16 + 1e-9, `label fits its room: ${band.text}`);
    }
    const rows = new Map();
    for (const band of bands) rows.set(band.row, [...(rows.get(band.row) || []), band]);
    for (const row of rows.values()) {
      row.sort((a, b) => a.x - b.x);
      for (let i = 1; i < row.length; i++) assert.ok(row[i - 1].x + row[i - 1].extent <= row[i].x, `labels in one row do not overlap (${columnWidth}px)`);
    }
  }
  assert.equal(fitBandText('Seoul National University', 1000), 'Seoul National University');
  assert.ok(fitBandText('Government of the Republic of Korea', 80).endsWith('…'));
  assert.ok(bandTextWidth(fitBandText('Government of the Republic of Korea', 80)) <= 80);
  assert.ok(bandTextWidth('서울대학교') > bandTextWidth('Seoul'), 'Hangul counts wider than Latin');
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
  assert.equal(validateTitleRows([{ year: 2007, topic: 0, title: 'C', doi: 'https://doi.org/not-a-doi' }])[0].doi, null);
  assert.equal(doiText('https://doi.org/10.1103/PhysRevE.1'), 'doi:10.1103/PhysRevE.1');
});

test('shipped topic index is valid and title-free', () => {
  const raw = JSON.parse(readFileSync('public/data/topics/index.json', 'utf8'));
  const parsed = normalizeTopicIndex(raw);
  assert.ok(parsed.researchers.length > 0);
  for (const r of parsed.researchers) assert.equal(layoutAlluvial(r, 'year').unplaced, 0);
});

test('shipped release index is anonymous: dashboard ids only, no titles, DOIs or work ids', () => {
  const raw = JSON.parse(readFileSync('public/data/topics/index.json', 'utf8'));
  if (raw.source !== 'release') return;
  const ids = new Set(JSON.parse(readFileSync('public/data/dashboard.json', 'utf8')).professors.map(p => p.id));
  for (const r of raw.researchers) {
    assert.ok(ids.has(r.id), r.id);
    const keys = r.paper_cols ? Object.keys(r.paper_cols) : (r.papers || []).flatMap(p => Object.keys(p));
    assert.deepEqual(keys.filter(k => !['year', 'topic', 'era', 'cited'].includes(k)), []);
  }
  const text = readFileSync('public/data/topics/index.json', 'utf8');
  assert.doesNotMatch(text, /openalex\.org|doi\.org|"W\d{6,}"|"title"|orcid/i);
});

test('split info-flow files exist for every shipped researcher and parse', () => {
  const index = shipped();
  if (!index.infoPath) return;
  for (const r of index.researchers) {
    const info = parseInfo(JSON.parse(readFileSync(`public/data/topics/${index.infoPath}/${r.id}.json`, 'utf8')), new Set(r.topics.map(t => t.id)));
    assert.ok(info, r.id);
    for (const t of info.transitions) assert.ok(t.measures.diverge.value >= 0 && t.measures.merge.value >= 0 && t.measures.continuity.value >= 0, r.id);
  }
});

import { searchTopics, expandTerms, tokenizeQuery, layoutMulti, seriesFromHits, tagCloud } from '../work/test-dist/topics.js';

const shipped = () => normalizeTopicIndex(JSON.parse(readFileSync('public/data/topics/index.json', 'utf8')));
// Search behaviour is pinned to the synthetic demo index; the shipped index is checked for invariants only.
const demo = () => normalizeTopicIndex(JSON.parse(readFileSync('tests/fixtures/topic_index_demo.json', 'utf8')));

test('korean query expands through the glossary and ranks the matching topic first', () => {
  const index = demo();
  assert.deepEqual(tokenizeQuery('동기화, 전력망!'), ['동기화', '전력망']);
  assert.ok(expandTerms(['동기화'], index.semantic).includes('synchronization'));
  const ko = searchTopics(index, '동기화');
  const en = searchTopics(index, 'synchronization oscillators');
  assert.equal(ko.method, 'semantic');
  assert.match(en.hits[0].topic.label, /kuramoto|synchronization/i);
  assert.equal(ko.hits[0].topic, en.hits[0].topic);
  assert.equal(searchTopics(index, '').hits.length, 0);
});

test('topic names and features are English only — no translated labels or tags', () => {
  for (const index of [demo(), shipped()]) {
    for (const r of index.researchers) for (const t of r.topics) {
      assert.ok(t.label.length > 0);
      assert.doesNotMatch(t.label, /[가-힣]/, t.label);
      assert.equal(t.tags.ko.length, 0, t.label);
      for (const tag of [...t.tags.en, ...t.keywords]) assert.doesNotMatch(tag, /[가-힣]/);
    }
    const cloud = tagCloud(index);
    assert.ok(cloud.length > 0 && cloud.every(c => c.count >= 1 && !/[가-힣]/.test(c.tag)));
  }
  for (const r of demo().researchers) for (const t of r.topics) assert.ok(t.tags.en.length > 0 && t.keywords.length > 0, t.label);
});

test('multi layout keeps every selected paper in stack and overlay modes', () => {
  const index = demo();
  const hits = searchTopics(index, 'network').hits.slice(0, 5);
  const series = seriesFromHits(hits, id => id);
  const papers = series.reduce((sum, s) => sum + [...s.counts.values()].reduce((a, b) => a + b, 0), 0);
  for (const mode of ['stack', 'overlay']) {
    const layout = layoutMulti(series, mode);
    assert.equal(layout.shapes.length, series.length);
    assert.equal(layout.lanes.reduce((sum, l) => sum + l.total, 0), papers);
  }
  assert.deepEqual(layoutMulti(series, 'overlay').totals, []);
});

test('multi lanes report matched-topic papers out of all papers', () => {
  const index = demo();
  const series = seriesFromHits(searchTopics(index, 'network').hits.slice(0, 5), id => id);
  const byId = new Map(index.researchers.map(r => [r.id, r]));
  for (const mode of ['stack', 'overlay']) for (const lane of layoutMulti(series, mode).lanes) {
    assert.equal(lane.all, byId.get(lane.key).papers.length);
    assert.ok(lane.total > 0 && lane.total <= lane.all, lane.key);
  }
});

const pathYs = d => [...d.matchAll(/(-?[\d.]+),(-?[\d.]+)/g)].map(m => Number(m[2]));

test('topic counts are drawn as lines above a baseline, never mirrored below it', () => {
  const r = normalizeTopicIndex(index([researcher()])).researchers[0];
  const layout = layoutAlluvial(r, 'year');
  for (const lane of layout.lanes) {
    const ribbon = layout.ribbons.find(x => x.topic === lane.topic.id);
    assert.ok(pathYs(ribbon.line).every(y => y <= lane.base + 1e-6), lane.topic.label);
    assert.ok(pathYs(ribbon.line).some(y => y < lane.base - 1), lane.topic.label);
  }
  const series = seriesFromHits(searchTopics(demo(), 'network').hits.slice(0, 5), id => id);
  for (const mode of ['stack', 'overlay']) {
    const multi = layoutMulti(series, mode);
    multi.shapes.forEach((shape, i) => assert.ok(pathYs(shape.line).every(y => y <= multi.lanes[i].mid + 5 + 1e-6), mode));
  }
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

test('info-flow measures are non-negative and normalised forms stay within [0, 1]', () => {
  for (const r of demo().researchers) assert.ok(r.info && r.info.transitions.length > 0, r.id);
  for (const r of [...demo().researchers, ...shipped().researchers]) {
    for (const t of r.info?.transitions || []) {
      const { diverge, merge, continuity } = t.measures;
      assert.ok(diverge.value >= 0 && merge.value >= 0 && continuity.value >= 0);
      if (t.measures.diverge_norm) assert.ok(t.measures.diverge_norm.value <= 1);
    }
  }
});

test('a Korean query reaches English phrase tags through the glossary', () => {
  const hits = searchTopics(demo(), '단일세포').hits.slice(0, 2);
  assert.equal(hits.length, 2);
  for (const h of hits) assert.ok(h.topic.tags.en.some(t => t.split(' ').includes('single-cell')), h.topic.label);
});

test('glossary expansion uses the exact Korean entry before substrings', () => {
  assert.ok(!expandTerms(['유전자'], demo().semantic).includes('electron'));   // 전자 ⊂ 유전자
});

import { singular } from '../work/test-dist/topics.js';

test('plural and singular English forms meet in topic search', () => {
  assert.equal(singular('lithium-ion batteries'), 'lithium-ion battery');
  assert.equal(singular('random matrices'), 'random matrice');            // both sides fold the same way
  assert.equal(singular('analysis'), 'analysis');
  assert.equal(singular('gas'), 'gas');
  const index = demo();
  for (const q of ['battery', 'batteries', '배터리']) assert.match(searchTopics(index, q).hits[0]?.topic.label || '', /batter/i, q);
});

test('curated group: its keyword shows only members, each at least once', () => {
  const groups = normalizeCurated({ schema: 'kstem-topic-curated/1', groups: [{ key: 'sp', label: 'Statistical physics', match: ['Statistical Physics', '통계물리'], ids: ['P-AAAAAAAAAA', 'P-BBBBBBBBBB', 'bad id'] }] });
  assert.equal(groups[0].ids.length, 2);
  assert.equal(curatedFor(groups, '  "statistical   physics" ')?.key, 'sp');
  assert.equal(curatedFor(groups, '통계물리')?.key, 'sp');
  assert.equal(curatedFor(groups, 'statistical'), null);
  const topic = (id, label, size) => ({ id, label, size, birth_year: 2000, parent: null, tags: { en: [], ko: [] }, keywords: [] });
  const person = (id, topics) => ({ id, topics, papers: [] });
  const a = person('P-AAAAAAAAAA', [topic(0, 'Ising', 5)]), b = person('P-BBBBBBBBBB', [topic(0, 'Other · x', 9), topic(1, 'Lasers', 3)]), c = person('P-CCCCCCCCCC', [topic(0, 'Ising', 7)]);
  const hit = (researcher, t, score) => ({ researcher, topic: t, score, tagScore: score, semanticScore: 0, matched: [] });
  const found = { hits: [hit(c, c.topics[0], 0.9), hit(a, a.topics[0], 0.8)], terms: [], expanded: [], method: 'tags' };
  const out = curatedSearch({ researchers: [a, b, c] }, found, groups[0]);
  assert.deepEqual(out.hits.map(h => `${h.researcher.id}:${h.topic.label}`), ['P-AAAAAAAAAA:Ising', 'P-BBBBBBBBBB:Lasers']);
});
