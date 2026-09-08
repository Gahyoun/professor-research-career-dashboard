import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { buildSankey, layoutSankey, countryRegion, institutionKey, STAGES } from '../work/test-dist/sankey.js';

const person = (id, bachelor = 'Seoul National University', phd = 'Harvard University', current = 'Korea University (Seoul Campus)', extra = {}) => ({ id, subject: 'physics', bachelor_institution: bachelor, phd_institution: phd, current_institution: current, bachelor_country: 'Korea', phd_country: 'United States', current_country: 'Korea', ...extra });
function audit(data) {
  const recordIds = new Set(data.records.map(r => r.id));
  assert.equal(recordIds.size, data.count);
  for (const stage of STAGES) {
    const nodes = data.nodes.filter(n => n.stage === stage);
    assert.equal(nodes.reduce((n, x) => n + x.count, 0), data.count);
    const ids = nodes.flatMap(n => n.personIds);
    assert.deepEqual(new Set(ids), recordIds);
    assert.equal(ids.length, data.count);
    for (const node of nodes) {
      const incoming = data.links.filter(l => l.target === node.id);
      const outgoing = data.links.filter(l => l.source === node.id);
      if (stage !== 'bachelor') assert.equal(incoming.reduce((n, l) => n + l.count, 0), node.count);
      if (stage !== 'current') assert.equal(outgoing.reduce((n, l) => n + l.count, 0), node.count);
      for (const link of [...incoming, ...outgoing]) {
        assert.equal(link.count, new Set(link.personIds).size);
        for (const id of link.personIds) assert.ok(node.personIds.includes(id));
      }
    }
  }
  assert.equal(data.links.reduce((n, l) => n + l.count, 0), 2 * data.count);
  assert.equal(data.routes.reduce((n, l) => n + l.count, 0), data.count);
  const layout = layoutSankey(data);
  for (const stage of STAGES) {
    let previousBottom = -Infinity;
    for (const node of layout.nodes.filter(n => n.stage === stage).sort((a, b) => a.y - b.y)) {
      assert.ok(Number.isFinite(node.y));
      assert.ok(node.y > previousBottom);
      assert.ok(node.y + node.height < layout.height);
      assert.equal(node.height, node.count * layout.scale);
      previousBottom = node.y + node.height;
    }
  }
  for (const link of layout.links) {
    const source = layout.nodes.find(n => n.id === link.source), target = layout.nodes.find(n => n.id === link.target);
    assert.equal(link.height, link.count * layout.scale);
    assert.ok(link.sourceY >= source.y - 1e-8);
    assert.ok(link.sourceY + link.height <= source.y + source.height + 1e-8);
    assert.ok(link.targetY >= target.y - 1e-8);
    assert.ok(link.targetY + link.height <= target.y + target.height + 1e-8);
    assert.ok(!/NaN|Infinity/.test(link.path));
  }
}

test('all three stages and both transitions conserve people, including identical institution names at different stages', () => {
  const data = buildSankey([person('a'), person('b', 'Korea University'), person('c', 'Seoul National University', 'Seoul National University', 'Seoul National University')]);
  audit(data);
  assert.equal(data.count, 3);
  assert.equal(data.selfHireCount, 2);
  assert.equal(new Set(data.nodes.map(n => n.id)).size, data.nodes.length);
});
test('any missing stage excludes the entire researcher; per-stage missing counts may overlap', () => {
  const data = buildSankey([person('complete'), person('b', null), person('p', 'SNU', ' N/A '), person('c', 'SNU', 'KAIST', '—'), person('d', null, null, null)]);
  audit(data);
  assert.equal(data.count, 1);
  assert.equal(data.missingCount, 4);
  assert.deepEqual(data.missingByStage, { bachelor: 2, phd: 2, current: 2 });
});
test('school matches use explicit aliases and preserve regional campuses and institution types', () => {
  assert.equal(institutionKey('Korea University (Seoul Campus)'), institutionKey('Korea University'));
  assert.notEqual(institutionKey('Korea University (Sejong Campus)'), institutionKey('Korea University'));
  assert.notEqual(institutionKey('Yonsei University (Mirae Campus)'), institutionKey('Yonsei University'));
  assert.notEqual(institutionKey('Oxford Brookes University'), institutionKey('University of Oxford'));
  const data = buildSankey([person('main', 'Korea University'), person('campus', 'Korea University (Sejong Campus)'), person('numeric', '101', 'Harvard', '101')]);
  assert.equal(data.selfHireCount, 1);
  assert.equal(data.unresolvedInstitutionCount, 1);
  audit(data);
});
test('country classification uses explicit country data, never institutional-name guesses', () => {
  assert.equal(countryRegion(null), 'unknown');
  assert.equal(countryRegion('101'), 'unknown');
  assert.equal(countryRegion('unknown country code'), 'unknown');
  assert.equal(countryRegion('United States'), 'us');
  assert.equal(countryRegion('Hong Kong'), 'foreign');
  assert.equal(countryRegion('Germany'), 'europe');
  const data = buildSankey([person('a', 'Harvard University', 'SNU', 'Korea University', { bachelor_country: null, phd_country: null })]);
  assert.equal(data.unknownCountryCount, 1);
  assert.ok(data.nodes.some(n => n.label === 'Harvard University' && n.region === 'unknown'));
  assert.ok(!data.nodes.some(n => n.key.startsWith('region:')));
});
test('top-N and foreign grouping preserve all people and original paths', () => {
  const rows = Array.from({ length: 90 }, (_, i) => person(`r${i}`, `Bachelor ${i % 30}`, `PhD ${i % 25}`, `Current ${i % 24}`, { phd_country: i % 3 ? 'Korea' : 'United States' }));
  for (const groupForeign of [true, false]) {
    const data = buildSankey(rows, { topN: 6, groupForeign });
    assert.equal(data.count, rows.length);
    assert.ok(data.nodes.some(n => n.key.startsWith('other:')));
    assert.ok(data.routes.every(r => r.labels[0].startsWith('Bachelor ')));
    audit(data);
  }
});
test('route selection preserves observed triples and cannot invent paths across a shared doctorate node', () => {
  const data = buildSankey([person('a', 'A', 'P', 'X'), person('b', 'B', 'P', 'Y')], { groupForeign: false });
  assert.deepEqual(data.routes.map(r => r.labels), [['A', 'P', 'X'], ['B', 'P', 'Y']]);
  const first = data.links.find(l => l.personIds.includes('a'));
  assert.deepEqual(first.personIds, ['a']);
  assert.equal(data.links.filter(l => l.personIds.some(id => first.personIds.includes(id))).length, 2);
  audit(data);
});
test('filters count each unique professor once, inputs stay unchanged, private fields never enter the graph', () => {
  const rows = [person('a', 'SNU', 'Harvard', 'SNU', { name: 'PRIVATE-NAME-SHOULD-NEVER-LEAK' }), person('b', 'Korea University'), person('c', 'SNU', 'Harvard', 'Korea University', { subject: 'biology' })];
  const original = JSON.stringify(rows);
  const data = buildSankey([...rows, rows[0]], { subject: 'physics', selfHireOnly: true, origin: 'snu' });
  assert.equal(data.count, 1);
  assert.equal(data.duplicateCount, 1);
  assert.equal(JSON.stringify(rows), original);
  assert.ok(!JSON.stringify(data).includes('PRIVATE-NAME'));
  audit(data);
});
test('empty input and empty filters produce finite empty layouts', () => { audit(buildSankey([])); audit(buildSankey([person('a')], { subject: 'missing' })); });
test('public 2026 release, all four subjects and all grouping choices pass conservation and layout audit', () => {
  const dashboard = JSON.parse(readFileSync('public/data/dashboard.json', 'utf8'));
  let enrichment = {};
  try { enrichment = JSON.parse(readFileSync('public/data/constellation_metadata.json', 'utf8')); } catch { /* Optional country enrichment. */ }
  const metadata = enrichment.professors ?? enrichment.metadata ?? enrichment;
  const rows = dashboard.professors.map(p => ({ ...p, ...(metadata[p.id] ?? {}) }));
  for (const subject of ['', ...new Set(rows.map(p => p.subject))]) for (const topN of [6, 10, 14]) for (const groupForeign of [true, false]) {
    const data = buildSankey(rows, { subject, topN, groupForeign });
    audit(data);
    assert.equal(data.count + data.missingCount, data.subjectCount);
  }
  const data = buildSankey(rows);
  console.log(JSON.stringify({ releaseCount: rows.length, included: data.count, excluded: data.missingCount, selfHire: data.selfHireCount, unknownCountry: data.unknownCountryCount, stageNodes: STAGES.map(s => data.nodes.filter(n => n.stage === s).length), routes: data.routes.length }));
});
