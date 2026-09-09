import assert from 'node:assert/strict';
import test from 'node:test';
import { readFileSync } from 'node:fs';
import { createLifetimeIndex } from '../work/test-dist/constellation/lifetime.js';
import { buildTrajectoryHypergraph } from '../work/test-dist/constellation/trajectoryGraph.js';
import { toResearcherRecords } from '../work/test-dist/constellation/records.js';
import { mergeMetadata } from '../work/test-dist/metadata.js';
import { applyInstitutionSuccessions } from '../work/test-dist/institutionSuccession.js';

const options = { releaseYear: 2026, includeEstimated: true, includeInferredDepartments: false };
const current = (id, position = {}, fields = {}) => ({
  id, subject: 'physics', ...fields,
  current_position: { institution: 'Current University', country: 'KR', department: 'Physics',
    observation_year: 2026, evidence_kind: 'semester_roster', evidence_status: 'observed', ...position },
});
const currentStage = result => result.stages.find(stage => stage.stage === 'current');
const graphMembers = (graph, edge) => edge.members.map(i => graph.nodes[i].id);

// Broad field is an explicit current-only grouping attribute. It is never
// copied into department or used to relax historical degree/employment rules.
test('current school and recorded subject unify different, missing and inferred departments', () => {
  const rows = [current('A'), current('B', { department: 'Physics and Research Institute of Natural Science' }),
    current('C', { department: null }), current('D', { department: 'Mathematics', department_inferred: true })];
  const strict = createLifetimeIndex(rows, options);
  const inferred = createLifetimeIndex(rows, { ...options, includeInferredDepartments: true });
  const ids = new Set();
  for (const id of strict.ids) {
    const result = currentStage(strict.get(id));
    assert.deepEqual(result, currentStage(inferred.get(id)));
    const group = result.groups[0];
    ids.add(group.id);
    assert.deepEqual([...group.members].sort(), ['A', 'B', 'C', 'D']);
    for (const item of [group, ...result.intervals, ...group.memberEvidence]) {
      assert.equal(item.matchingBasis, 'institution_subject');
      assert.equal(item.subject, 'physics');
      assert.equal(item.department, undefined);
      assert.equal(item.inferredDepartment, false);
    }
  }
  assert.equal(ids.size, 1);
});

test('different or missing current subjects never inherit a department or doctoral field', () => {
  const rows = [current('A'), current('B'), current('math', {}, { subject: 'mathematics' }),
    current('missing', {}, { subject: undefined, phd_department: 'Physics' }),
    current('unsupported', {}, { subject: 'engineering' }),
    current('other-campus', { institution: 'Current University Other Campus' })];
  const index = createLifetimeIndex(rows, options);
  assert.deepEqual(currentStage(index.get('A')).groups[0].members, ['A', 'B']);
  for (const id of ['missing', 'unsupported']) {
    const stage = currentStage(index.get(id));
    assert.equal(stage.intervals.length, 0);
    assert.ok(stage.excludedReasons.some(reason => reason.includes('계열 정보')));
  }
  assert.equal(currentStage(index.get('math')).groups.length, 0);
  assert.equal(currentStage(index.get('other-campus')).groups.length, 0);
});

test('current employment still requires an observed or verified position in the release year', () => {
  const rows = [current('A'), current('B'), current('stale', { observation_year: 2025 }),
    current('inferred', { evidence_status: 'inferred' }), current('paper', { evidence_kind: 'publication_affiliation' }),
    current('missing-school', { institution: null }), current('numeric-school', { institution: '101' }),
    { id: 'no-position', subject: 'physics', current_institution: 'Current University', department: 'Physics' }];
  const index = createLifetimeIndex(rows, options);
  assert.deepEqual(currentStage(index.get('A')).groups[0].members, ['A', 'B']);
  for (const id of index.ids.slice(2)) assert.equal(currentStage(index.get(id)).intervals.length, 0, id);
});

test('missing current country can join an observed specific school without inventing a country', () => {
  for (const countries of [['KR', null, undefined], [null, null, undefined]]) {
    const rows = countries.map((country, i) => current(String(i), { country }));
    const index = createLifetimeIndex(rows, options);
    for (const id of index.ids) {
      const stage = currentStage(index.get(id));
      assert.deepEqual([...stage.groups[0].members].sort(), ['0', '1', '2']);
      assert.equal(stage.intervals[0].country, countries[Number(id)] ?? null);
      assert.ok(stage.groups[0].memberEvidence.every(item => item.country === null));
      assert.equal(index.get(id).coverage.missingCountryIntervals, 0);
    }
    assert.equal(new Set(index.ids.map(id => currentStage(index.get(id)).groups[0].id)).size, 1);
  }
});

test('conflicting known current school countries partition known and unknown records', () => {
  const rows = [current('KR-A'), current('KR-B'), current('US-A', { country: 'US' }),
    current('US-B', { country: 'US' }), current('unknown-A', { country: null }), current('unknown-B', { country: null })];
  const index = createLifetimeIndex(rows, options);
  for (const [selected, members] of [['KR-A', ['KR-A', 'KR-B']], ['US-A', ['US-A', 'US-B']], ['unknown-A', ['unknown-A', 'unknown-B']]]) {
    assert.deepEqual(currentStage(index.get(selected)).groups[0].members, members);
  }
  assert.equal(new Set(index.ids.map(id => currentStage(index.get(id)).groups[0].id)).size, 3);
});

test('a subject-filtered index retains country conflicts from the full current-school context', () => {
  const rows = [current('A'), current('B'), current('unknown', { country: null }),
    current('foreign-other-field', { country: 'US' }, { subject: 'biology' })];
  const physics = rows.filter(row => row.subject === 'physics');
  const full = createLifetimeIndex(rows, options);
  const filtered = createLifetimeIndex(physics, options, rows);
  assert.deepEqual(filtered.ids, ['A', 'B', 'unknown']);
  assert.deepEqual(currentStage(filtered.get('A')).groups, currentStage(full.get('A')).groups);
  assert.deepEqual(currentStage(filtered.get('A')).groups[0].members, ['A', 'B']);
  assert.equal(currentStage(filtered.get('unknown')).groups.length, 0);
  assert.equal(filtered.get('foreign-other-field').selectedFound, false);
});

test('prepared full-population lifetime preserves current country partitions in an induced graph', () => {
  const phd = { phd_institution: 'Doctoral University', phd_country: 'KR', phd_department: 'Physics', phd_year: 2010 };
  const rows = [current('A', {}, phd), current('B'), current('C', { country: null }, phd), current('D', { country: 'US' })];
  const prepared = createLifetimeIndex(rows, options).get('A');
  const before = JSON.stringify(prepared);
  const local = rows.filter(row => row.id !== 'D');
  const graph = buildTrajectoryHypergraph(local, 'A', options, prepared);
  const edge = graph.edges.find(item => item.lifetimeStage === 'current');
  const group = currentStage(prepared).groups[0];
  assert.equal(edge.id, group.id);
  assert.deepEqual(graphMembers(graph, edge), ['A', 'B']);
  assert.deepEqual(edge.memberEvidence, group.memberEvidence);
  assert.deepEqual(graphMembers(graph, graph.edges.find(item => item.lifetimeStage === 'doctoral')), ['A', 'C']);
  assert.equal(graph.diagnostics.incidenceCount, 4);
  assert.throws(() => buildTrajectoryHypergraph(local, 'C', options, prepared), /selection/);
  assert.deepEqual(buildTrajectoryHypergraph(local, 'A', { ...options, stages: ['current'] }, prepared).edges.map(item => item.lifetimeStage), ['current']);
  const cropped = buildTrajectoryHypergraph([rows[0], rows[2]], 'A', options, prepared);
  assert.deepEqual(cropped.edges.map(item => item.lifetimeStage), ['doctoral']);
  assert.ok(cropped.edges.every(item => item.memberEvidence.every(evidence => graphMembers(cropped, item).includes(evidence.peerId))));
  assert.equal(JSON.stringify(prepared), before);
});

let releaseRecords;
function actualRecords() {
  releaseRecords ??= toResearcherRecords(applyInstitutionSuccessions(mergeMetadata(
    JSON.parse(readFileSync('public/data/dashboard.json', 'utf8')),
    JSON.parse(readFileSync('public/data/constellation_metadata.json', 'utf8')),
  )).professors);
  return releaseRecords;
}

test('both formerly split GNU physics selections belong to the exact same ten-person current group', () => {
  const records = actualRecords();
  const selectedIds = ['P-XKPSPQXY7D', 'P-DUVZEAA6LK'];
  let expected;
  for (const includeInferredDepartments of [false, true]) {
    const index = createLifetimeIndex(records, { ...options, includeInferredDepartments });
    for (const selectedId of selectedIds) {
      const result = index.get(selectedId), group = currentStage(result).groups[0];
      const members = [...group.members].sort();
      assert.equal(members.length, 10);
      assert.ok(selectedIds.every(id => members.includes(id)));
      expected ??= { id: group.id, members };
      assert.deepEqual({ id: group.id, members }, expected);
      const graph = buildTrajectoryHypergraph(records.filter(row => group.members.includes(row.id)), selectedId, { ...options, stages: ['current'] }, result);
      assert.equal(graph.edges.length, 1);
      assert.equal(graph.edges[0].id, group.id);
      assert.equal(graph.edges[0].matchingBasis, 'institution_subject');
      assert.equal(graph.edges[0].subject, 'physics');
      assert.equal(graph.edges[0].department, undefined);
      assert.deepEqual(graphMembers(graph, graph.edges[0]).sort(), members);
    }
  }
});

test('the release current population retains all observed subjects including missing-country records', () => {
  const index = createLifetimeIndex(actualRecords(), { ...options, stages: ['current'] });
  let eligible = 0, grouped = 0, unknownCountry = 0;
  const units = new Set(), groups = new Set();
  for (const id of index.ids) {
    const stage = currentStage(index.get(id));
    if (stage.intervals.length) eligible++;
    if (stage.groups.length) grouped++;
    for (const interval of stage.intervals) { units.add(interval.unitKey); if (interval.country === null) unknownCountry++; }
    for (const group of stage.groups) groups.add(group.id);
  }
  assert.deepEqual({ total: index.ids.length, eligible, grouped, unknownCountry, units: units.size, groups: groups.size },
    { total: 3937, eligible: 3241, grouped: 3240, unknownCountry: 95, units: 232, groups: 231 });
});
