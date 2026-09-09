import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { performance } from 'node:perf_hooks';
import { mergeMetadata } from '../work/test-dist/metadata.js';
import { applyInstitutionSuccessions } from '../work/test-dist/institutionSuccession.js';
import { buildSankey, buildInstitutionOptions, colorOfOrigin, layoutSankey, countryRegion, institutionKey, STAGES } from '../work/test-dist/sankey.js';

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
test('every university remains visible without top-N or other buckets and optional regions conserve original paths', () => {
  const rows = Array.from({ length: 90 }, (_, i) => person(`r${i}`, `Bachelor ${i % 30}`, `PhD ${i % 25}`, `Current ${i % 24}`, { phd_country: i % 3 ? 'Korea' : 'United States' }));
  for (const groupForeign of [true, false]) {
    const data = buildSankey(rows, { groupForeign });
    assert.equal(data.count, rows.length);
    assert.ok(data.nodes.every(n => !n.key.startsWith('other:')));
    if (!groupForeign) assert.deepEqual(STAGES.map(stage => data.nodes.filter(node => node.stage === stage).length), [30, 25, 24]);
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
  const data = buildSankey([...rows, rows[0]], { subject: 'physics', selfHireOnly: true, institutions: { bachelor: institutionKey('SNU') } });
  assert.equal(data.count, 1);
  assert.equal(data.duplicateCount, 1);
  assert.equal(JSON.stringify(rows), original);
  assert.ok(!JSON.stringify(data).includes('PRIVATE-NAME'));
  audit(data);
});
test('empty input and empty filters produce finite empty layouts', () => { audit(buildSankey([])); audit(buildSankey([person('a')], { subject: 'missing' })); });
test('all three institution filters combine with subject and self-hire before missing-data denominators', () => {
  const rows = [person('match', 'SNU', 'KAIST', 'Seoul National University'),
    person('missing-phd', 'Seoul', null, 'SNU'), person('wrong-phd', 'SNU', 'Harvard', 'SNU'),
    person('wrong-current', 'SNU', 'KAIST', 'Korea University'), person('wrong-bachelor', 'Korea University', 'KAIST', 'SNU'),
    person('other-field', 'SNU', 'KAIST', 'SNU', { subject: 'biology' }), person('missing-bachelor', null, 'KAIST', 'SNU')];
  const basic = { subject: 'physics', institutions: { current: institutionKey('SNU') } };
  const school = buildSankey(rows, basic);
  assert.equal(school.subjectCount, 6); assert.equal(school.filterCount, 5);
  assert.equal(school.completeCount, 3); assert.equal(school.missingCount, 2);
  assert.deepEqual(school.missingByStage, { bachelor: 1, phd: 1, current: 0 });
  const self = buildSankey(rows, { ...basic, selfHireOnly: true });
  assert.equal(self.filterCount, 3); assert.equal(self.count, 2); assert.equal(self.missingCount, 1);
  const selected = buildSankey(rows, { ...basic, selfHireOnly: true,
    institutions: { bachelor: institutionKey('서울대'), phd: institutionKey('한국과학기술원'), current: institutionKey('Seoul National University') } });
  assert.deepEqual(selected.records.map(row => row.id), ['match']);
  assert.equal(selected.filterCount, 1); assert.equal(selected.missingCount, 0);
  audit(school); audit(self); audit(selected);
});

test('institution options include all schools from incomplete people and count each identity once', () => {
  const rows = [person('a', 'SNU', null, 'University A'), person('b', 'Seoul National University', 'PhD A', null),
    person('c', null, 'PhD B', 'University B'), person('campus', 'Korea University (Sejong Campus)'),
    person('code-a', '101'), person('code-b', '112'), person('bio', 'Another Bachelor', null, 'University A', { subject: 'biology' })];
  const original = JSON.stringify(rows);
  const options = buildInstitutionOptions([...rows, rows[0]], { subject: 'physics' });
  assert.equal(options.bachelor.find(item => item.key === institutionKey('SNU')).count, 2);
  assert.equal(options.bachelor.find(item => item.key === institutionKey('SNU')).label, 'Seoul National University');
  assert.equal(options.phd.find(item => item.key === institutionKey('PhD B')).count, 1);
  assert.equal(options.current.find(item => item.key === institutionKey('University B')).count, 1);
  assert.equal(options.bachelor.find(item => item.key === 'unresolved').count, 2);
  assert.ok(!options.bachelor.some(item => item.key === institutionKey('Another Bachelor')));
  const campus = buildSankey(rows, { institutions: { bachelor: institutionKey('Korea_sejong') } });
  assert.deepEqual(campus.records.map(item => item.id), ['campus']);
  assert.equal(JSON.stringify(rows), original);
  audit(campus);
});

test('continuing universities match current Korean labels without absorbing historical predecessor schools', () => {
  assert.equal(institutionKey('Gyeongsang National University'), institutionKey('경상국립대학교'));
  assert.equal(institutionKey('Kangwon National University'), institutionKey('강원대학교 (통합)'));
  assert.notEqual(institutionKey('Gyeongnam National University of Science and Technology'), institutionKey('경상국립대학교'));
  assert.notEqual(institutionKey('Gangneung-Wonju National University'), institutionKey('강원대학교 (통합)'));
  const rows = [person('continuing', 'Gyeongsang National University', 'KAIST', '경상국립대학교'),
    person('predecessor', 'Gyeongnam National University of Science and Technology', 'KAIST', '경상국립대학교')];
  const data = buildSankey(rows, { institutions: { current: institutionKey('Gyeongsang National University') } });
  assert.equal(data.count, 2); assert.equal(data.selfHireCount, 1);
  assert.equal(data.nodes.find(node => node.stage === 'current').label, 'Gyeongsang National University');
  assert.equal(buildInstitutionOptions(rows).current.length, 1);
  audit(data);
});

test('selected foreign schools stay explicit while other overseas stages may aggregate by region', () => {
  const rows = [person('harvard', 'Harvard', 'University of Oxford', 'Korea University', { bachelor_country: 'US', phd_country: 'GB' }),
    person('stanford', 'Stanford', 'University of Cambridge', 'Korea University', { bachelor_country: 'US', phd_country: 'GB' })];
  const selected = buildSankey(rows, { groupForeign: true, institutions: { bachelor: institutionKey('Harvard University') } });
  assert.equal(selected.count, 1);
  assert.ok(selected.nodes.some(node => node.stage === 'bachelor' && node.key === institutionKey('Harvard') && node.label === 'Harvard University'));
  assert.ok(selected.nodes.some(node => node.stage === 'phd' && node.key === 'region:europe'));
  const both = buildSankey(rows, { groupForeign: true, institutions: { bachelor: institutionKey('Harvard'), phd: institutionKey('Oxford') } });
  assert.ok(both.nodes.every(node => !node.key.startsWith('region:')));
  audit(selected); audit(both);
});

test('numeric unresolved institutions never masquerade as a foreign region or establish self-hiring', () => {
  const rows = [person('a', '101', '112', '101', { bachelor_country: 'US', phd_country: 'GB' }),
    person('b', '112', 'Harvard', '112', { bachelor_country: null })];
  const selected = buildSankey(rows, { groupForeign: true, institutions: { bachelor: 'unresolved' } });
  assert.equal(selected.count, 2); assert.equal(selected.unresolvedInstitutionCount, 2); assert.equal(selected.selfHireCount, 0);
  assert.equal(selected.nodes.find(node => node.stage === 'bachelor').key, 'unresolved');
  assert.equal(selected.nodes.find(node => node.stage === 'bachelor').label, '기관명 미확인');
  assert.ok(selected.nodes.some(node => node.stage === 'phd' && node.key === 'unresolved'));
  assert.equal(buildSankey(rows, { selfHireOnly: true }).filterCount, 0);
  audit(selected);
});

test('every bachelor school has a distinct origin identity and stable filter-independent color and label', () => {
  const rows = Array.from({ length: 30 }, (_, i) => person(String(i), `Bachelor ${i}`, 'Shared PhD', 'Shared Current'));
  const all = buildSankey(rows), grouped = buildSankey(rows, { groupForeign: true });
  assert.equal(all.origins.length, 30); assert.equal(new Set(all.links.map(link => link.origin)).size, 30);
  assert.equal(all.origins.reduce((sum, item) => sum + item.count, 0), rows.length);
  for (const record of all.records) {
    assert.equal(record.origin, record.keys.bachelor); assert.equal(record.originLabel, record.labels.bachelor);
    const filtered = buildSankey(rows, { institutions: { bachelor: record.origin } });
    assert.deepEqual(filtered.origins, all.origins.filter(item => item.key === record.origin));
    assert.equal(filtered.origins[0].color, colorOfOrigin(record.origin));
    assert.ok(filtered.links.every(link => link.originLabel === record.originLabel));
    assert.ok(filtered.routes.every(route => route.originLabel === record.originLabel));
  }
  assert.deepEqual(grouped.origins, all.origins);
  audit(all); audit(grouped);
});

test('institution filters may intentionally select zero complete people and empty strings mean all', () => {
  const rows = [person('incomplete', null, 'Unique PhD', 'Unique Employer')];
  const selected = buildSankey(rows, { institutions: { phd: institutionKey('Unique PhD') } });
  assert.equal(selected.filterCount, 1); assert.equal(selected.count, 0); assert.equal(selected.missingCount, 1);
  assert.equal(buildSankey(rows, { institutions: { phd: institutionKey('Missing School') } }).filterCount, 0);
  assert.deepEqual(buildSankey(rows, { institutions: { bachelor: '', phd: '', current: '' } }), buildSankey(rows));
  audit(selected);
});

test('deduplication is performed before population filters and conflicting duplicate rows do not add identities', () => {
  const first = person('same', 'SNU', 'KAIST', 'SNU', { subject: 'biology' });
  const duplicate = person('same', 'Korea University', 'KAIST', 'Korea University');
  const data = buildSankey([first, duplicate], { subject: 'physics' });
  assert.equal(data.duplicateCount, 1); assert.equal(data.subjectCount, 0); assert.equal(data.filterCount, 0);
  assert.deepEqual(buildInstitutionOptions([first, duplicate], { subject: 'physics' }), { bachelor: [], phd: [], current: [] });
  audit(data);
});

test('public release and every available institution filter conserve the selected population without truncation', () => {
  const dashboard = JSON.parse(readFileSync('public/data/dashboard.json', 'utf8'));
  const metadata = JSON.parse(readFileSync('public/data/constellation_metadata.json', 'utf8'));
  const rows = applyInstitutionSuccessions(mergeMetadata(dashboard, metadata)).professors;
  const started = performance.now(), data = buildSankey(rows), built = performance.now();
  const layout = layoutSankey(data), laidOut = performance.now();
  audit(data);
  const choices = buildInstitutionOptions(rows);
  for (const [filters, subject, expected] of [
    [{ current: institutionKey('Gyeongsang National University') }, '', [67, 66, 1]],
    [{ current: institutionKey('Gyeongsang National University') }, 'physics', [10, 10, 0]],
    [{ bachelor: institutionKey('KAIST') }, '', [293, 293, 0]],
    [{ phd: institutionKey('KAIST') }, '', [393, 387, 6]],
    [{ bachelor: institutionKey('KAIST'), phd: institutionKey('KAIST') }, '', [200, 200, 0]],
    [{ current: institutionKey('Gyeongsang National University'), bachelor: institutionKey('KAIST'), phd: institutionKey('KAIST') }, 'physics', [3, 3, 0]],
  ]) {
    const selected = buildSankey(rows, { institutions: filters, subject });
    assert.deepEqual([selected.filterCount, selected.count, selected.missingCount], expected);
    audit(selected);
  }
  for (const subject of ['', ...new Set(rows.map(p => p.subject))]) for (const groupForeign of [true, false]) {
    const filtered = buildSankey(rows, { subject, groupForeign }); audit(filtered);
    assert.equal(filtered.count + filtered.missingCount, filtered.filterCount);
    assert.equal(filtered.filterCount, filtered.subjectCount);
  }
  for (const stage of STAGES) for (const choice of choices[stage]) {
    const filtered = buildSankey(rows, { institutions: { [stage]: choice.key } });
    assert.equal(filtered.filterCount, choice.count);
    assert.equal(filtered.count + filtered.missingCount, filtered.filterCount);
    assert.ok(filtered.records.every(record => record.keys[stage] === choice.key));
    if (filtered.count) assert.equal(filtered.nodes.filter(node => node.stage === stage).length, 1);
    assert.equal(filtered.routes.reduce((sum, route) => sum + route.count, 0), filtered.count);
  }
  for (const stage of STAGES) {
    const keys = new Set(data.records.map(record => record.keys[stage]));
    assert.equal(data.nodes.filter(node => node.stage === stage).length, keys.size);
  }
  assert.ok(data.nodes.every(node => !node.key.startsWith('other:') && !node.key.startsWith('region:')));
  console.log(JSON.stringify({ releaseCount: rows.length, included: data.count, excluded: data.missingCount, selfHire: data.selfHireCount,
    unknownCountry: data.unknownCountryCount, stageNodes: STAGES.map(s => data.nodes.filter(n => n.stage === s).length),
    optionCounts: STAGES.map(s => choices[s].length), routes: data.routes.length, links: data.links.length,
    buildMs: Math.round(built - started), layoutMs: Math.round(laidOut - built), height: layout.height }));
});
