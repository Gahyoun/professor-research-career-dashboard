import assert from 'node:assert/strict';
import test from 'node:test';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import vm from 'node:vm';
import { createLifetimeIndex } from '../work/test-dist/constellation/lifetime.js';
import { toResearcherRecords } from '../work/test-dist/constellation/records.js';

const require = createRequire(import.meta.url);
const ts = require('typescript');
const workerRequire = createRequire(new URL('../work/test-dist/constellation/layout.worker.js', import.meta.url));
const workerCode = ts.transpileModule(readFileSync('frontend/src/constellation/layout.worker.ts', 'utf8'), {
  compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS },
}).outputText;
function runWorker(payload) {
  const messages = [];
  const self = { postMessage: message => messages.push(structuredClone(message)) };
  vm.runInNewContext(workerCode, { exports: {}, require: workerRequire, self });
  self.onmessage({ data: structuredClone(payload) });
  assert.equal(messages.length, 1);
  return messages[0];
}
const options = { releaseYear: 2026, includeEstimated: true, estimatedYears: 5, includeInferredDepartments: false, stages: ['doctoral', 'postdoc', 'current'] };
const current = country => ({ institution: 'School X', country, department: null, observation_year: 2026, evidence_kind: 'semester_roster', evidence_status: 'observed', source_url: 'PRIVATE-URL' });
const doctoral = { stage: 'doctoral', institution: 'Graduate School', country: 'US', department: 'Physics', start_year: 2000, end_year: 2005, is_estimated: false };
function fixture() {
  return toResearcherRecords([
    { id: 'a', subject: 'physics', name: 'PRIVATE-NAME', current_position: current('KR'), career: [doctoral] },
    { id: 'b', subject: 'physics', current_position: current('KR'), career: [] },
    { id: 'unknown', subject: 'physics', current_position: current(null), career: [doctoral] },
    { id: 'foreign', subject: 'biology', current_position: current('US'), career: [] },
  ]);
}
function payload(records, lifetime, stages = options.stages) {
  const visible = lifetime.stages.filter(stage => stages.includes(stage.stage));
  const ids = new Set([lifetime.selectedId, ...visible.flatMap(stage => stage.groups.flatMap(group => group.members))]);
  return { records: records.filter(record => ids.has(record.id)), selectedId: lifetime.selectedId, preparedLifetime: lifetime,
    options: { ...options, stages }, layout: { width: 1400, height: 1000, minDistance: 14 } };
}
const currentGroup = lifetime => lifetime.stages.find(stage => stage.stage === 'current').groups[0];
const edgeMembers = (graph, edge) => edge.members.map(index => graph.nodes[index].id);

test('worker consumes full-context groups without merging an unknown-country historical peer into current membership', () => {
  const records = fixture();
  const lifetime = createLifetimeIndex(records, options).get('a');
  assert.deepEqual(currentGroup(lifetime).members, ['a', 'b']);
  const input = payload(records, lifetime), original = JSON.stringify(input);
  assert.deepEqual(input.records.map(record => record.id), ['a', 'b', 'unknown']);
  const result = runWorker(input);
  assert.equal(result.type, 'result');
  const graph = result.result.graph;
  const currentEdge = graph.edges.find(edge => edge.lifetimeStage === 'current');
  assert.equal(currentEdge.id, currentGroup(lifetime).id);
  assert.deepEqual(edgeMembers(graph, currentEdge), ['a', 'b']);
  for (const group of lifetime.stages.flatMap(stage => stage.groups)) {
    const edge = graph.edges.find(candidate => candidate.id === group.id);
    assert.ok(edge);
    assert.deepEqual(new Set(edgeMembers(graph, edge)), new Set(group.members));
  }
  assert.equal(JSON.stringify(input), original);
  assert.ok(!original.includes('PRIVATE'));
  assert.ok(!JSON.stringify(result).includes('PRIVATE'));
});

test('subject filtering keeps whole-release country partitions before the smaller worker projection', () => {
  const records = fixture();
  const whole = createLifetimeIndex(records, options).get('a');
  const physics = records.filter(record => record.subject === 'physics');
  const filtered = createLifetimeIndex(physics, options, records).get('a');
  assert.deepEqual(currentGroup(filtered), currentGroup(whole));
  const result = runWorker(payload(physics, filtered));
  assert.equal(result.type, 'result');
  const edge = result.result.graph.edges.find(candidate => candidate.lifetimeStage === 'current');
  assert.equal(edge.id, currentGroup(whole).id);
  assert.deepEqual(edgeMembers(result.result.graph, edge), ['a', 'b']);
});

test('current-only rendering preserves the exact prepared group ID and can restore historical layers', () => {
  const records = fixture(), lifetime = createLifetimeIndex(records, options).get('a');
  const currentOnly = runWorker(payload(records, lifetime, ['current']));
  assert.equal(currentOnly.type, 'result');
  assert.equal(currentOnly.result.graph.edges.length, 1);
  assert.equal(currentOnly.result.graph.edges[0].id, currentGroup(lifetime).id);
  assert.deepEqual(currentOnly.result.graph.nodes.map(node => node.id), ['a', 'b']);
  const restored = runWorker(payload(records, lifetime));
  assert.equal(restored.type, 'result');
  assert.deepEqual(restored.result.graph.edges.map(edge => edge.id), lifetime.stages.flatMap(stage => stage.groups.map(group => group.id)));
});

test('missing current country remains null through worker evidence and never relaxes generic school matching', () => {
  const records = fixture().filter(record => record.id !== 'foreign');
  const lifetime = createLifetimeIndex(records, options).get('unknown');
  const result = runWorker(payload(records, lifetime, ['current']));
  assert.equal(result.type, 'result');
  const currentEdge = result.result.graph.edges[0];
  assert.equal(currentEdge.country, null);
  assert.equal(currentEdge.matchingBasis, 'institution_subject');
  assert.equal(currentEdge.subject, 'physics');
  assert.ok(currentEdge.memberEvidence.every(evidence => evidence.country === null));
  const generic = runWorker({ records: records.map(record => ({ ...record, phd_institution: 'School X', phd_country: null, phd_department: 'Physics' })), selectedId: '', preparedLifetime: lifetime,
    options: { spatialEnabled: true, temporalEnabled: false, cohortEnabled: false } });
  assert.equal(generic.type, 'result');
  assert.equal(generic.result.graph.edges.length, 0);
  assert.equal(generic.result.graph.diagnostics.missingCountryCount, records.length);
});

test('a prepared lifetime for another selected researcher fails without identity-bearing errors', () => {
  const records = fixture(), lifetime = createLifetimeIndex(records, options).get('a');
  const result = runWorker({ ...payload(records, lifetime), selectedId: 'b' });
  assert.deepEqual(result, { type: 'error' });
});
