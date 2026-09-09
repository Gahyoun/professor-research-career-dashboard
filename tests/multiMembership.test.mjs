import assert from 'node:assert/strict';
import test from 'node:test';
import { readFileSync } from 'node:fs';
import { createLifetimeIndex } from '../work/test-dist/constellation/lifetime.js';
import { buildTrajectoryHypergraph } from '../work/test-dist/constellation/trajectoryGraph.js';
import { toResearcherRecords } from '../work/test-dist/constellation/records.js';
import { mergeMetadata } from '../work/test-dist/metadata.js';
import { applyInstitutionSuccessions } from '../work/test-dist/institutionSuccession.js';

const options = { releaseYear: 2026, includeEstimated: true, estimatedYears: 5, includeInferredDepartments: true };
const researcher = (id, postdocInstitution) => ({
  id, subject: 'physics', phd_institution: 'Doctoral School', phd_country: 'KR',
  phd_department: 'Physics', phd_year: id === 'A' ? 2010 : 2009,
  career: [{ stage: 'postdoc', institution: postdocInstitution, country: 'US',
    start_year: 2011, end_year: 2014, is_estimated: false }],
  current_position: { institution: 'Current University', country: 'KR', department: 'Physics',
    observation_year: 2026, evidence_kind: 'semester_roster', evidence_status: 'observed' },
});
const pair = () => [researcher('A', 'Postdoc Alpha'), researcher('B', 'Postdoc Beta')];
const memberIds = (graph, edge) => edge.members.map(i => graph.nodes[i].id);
const incidentStages = (graph, id) => graph.incidence[graph.nodes.findIndex(n => n.id === id)]
  .map(i => graph.edges[i].lifetimeStage);

test('different postdocs never make shared doctoral and current memberships mutually exclusive', () => {
  const rows = pair(), before = JSON.stringify(rows);
  const lifetime = createLifetimeIndex(rows, options).get('A');
  assert.deepEqual(lifetime.peers.map(p => [p.id, p.stageCount]), [['B', 2]]);
  const graph = buildTrajectoryHypergraph(rows, 'A', options);
  assert.deepEqual(graph.edges.map(e => e.lifetimeStage), ['doctoral', 'current']);
  assert.equal(new Set(graph.edges.map(e => e.id)).size, 2);
  for (const edge of graph.edges) {
    assert.deepEqual(memberIds(graph, edge), ['A', 'B']);
    assert.ok(edge.weight > 0);
    assert.equal(edge.overlapAdjustment, .5);
  }
  assert.deepEqual(incidentStages(graph, 'A'), ['doctoral', 'current']);
  assert.deepEqual(incidentStages(graph, 'B'), ['doctoral', 'current']);
  assert.deepEqual(graph.edges.map(e => [e.startYear, e.endYear]), [[2005, 2010], [2026, 2026]]);
  assert.deepEqual(graph.edges.map(e => e.memberEvidence.map(x => [x.startYear, x.endYear])), [[[2005, 2009]], [[2026, 2026]]]);
  assert.equal(JSON.stringify(rows), before);
});

test('partially overlapping groups preserve shared members and their distinct-only colleagues', () => {
  const [a, b] = pair(), doctoralOnly = researcher('doctoral-only', 'Postdoc Gamma'), currentOnly = researcher('current-only', 'Postdoc Delta');
  doctoralOnly.current_position.institution = 'Another Employer';
  currentOnly.phd_institution = 'Another Doctoral School';
  const graph = buildTrajectoryHypergraph([a, b, doctoralOnly, currentOnly], 'A', options);
  assert.deepEqual(memberIds(graph, graph.edges.find(e => e.lifetimeStage === 'doctoral')), ['A', 'B', 'doctoral-only']);
  assert.deepEqual(memberIds(graph, graph.edges.find(e => e.lifetimeStage === 'current')), ['A', 'B', 'current-only']);
  assert.deepEqual(incidentStages(graph, 'B'), ['doctoral', 'current']);
  assert.deepEqual(incidentStages(graph, 'doctoral-only'), ['doctoral']);
  assert.deepEqual(incidentStages(graph, 'current-only'), ['current']);
  assert.equal(graph.diagnostics.incidenceCount, 6);
});

test('explicit stage filtering hides only requested layers and does not erase membership on return', () => {
  const rows = pair(), complete = buildTrajectoryHypergraph(rows, 'A', options);
  for (const stage of ['doctoral', 'current']) {
    const filtered = buildTrajectoryHypergraph(rows, 'A', { ...options, stages: [stage] });
    assert.deepEqual(incidentStages(filtered, 'B'), [stage]);
  }
  assert.deepEqual(buildTrajectoryHypergraph(rows, 'A', options), complete);
});

test('the default three stages retain current membership when a verified first appointment shares that institution', () => {
  const rows = pair();
  rows[1].career[0].institution = rows[0].career[0].institution;
  const faculty = { institution: 'Current University', country: 'KR', department: 'Physics',
    role: 'faculty', evidence_kind: 'verified_cv', evidence_status: 'verified' };
  rows[0].faculty_appointments = [{ ...faculty, start_year: 2015, end_year: 2018,
    rank: 'assistant_professor', first_assistant_professor_verified: true }];
  rows[1].faculty_appointments = [{ ...faculty, start_year: 2016, end_year: 2026 }];
  const defaultStages = ['doctoral', 'postdoc', 'current'];
  const defaults = buildTrajectoryHypergraph(rows, 'A', { ...options, stages: defaultStages });
  assert.deepEqual(incidentStages(defaults, 'B'), defaultStages);
  assert.equal(defaults.edges.some(e => e.lifetimeStage === 'first_faculty'), false);
  const optedIn = buildTrajectoryHypergraph(rows, 'A', { ...options, stages: [...defaultStages, 'first_faculty'] });
  assert.deepEqual(incidentStages(optedIn, 'B'), ['doctoral', 'postdoc', 'first_faculty', 'current']);
  const current = optedIn.edges.find(e => e.lifetimeStage === 'current');
  const first = optedIn.edges.find(e => e.lifetimeStage === 'first_faculty');
  assert.notEqual(first.id, current.id);
  assert.deepEqual(memberIds(optedIn, first), ['A', 'B']);
  assert.deepEqual(first.members, current.members);
  assert.ok(first.weight > 0 && current.weight > 0);
  assert.deepEqual(current.memberEvidence, defaults.edges.find(e => e.lifetimeStage === 'current').memberEvidence);
  assert.deepEqual(buildTrajectoryHypergraph(rows, 'A', { ...options, stages: defaultStages }), defaults);
});

test('missing or stale current evidence removes only that current membership, never the doctoral group', () => {
  for (const changed of [{ observation_year: 2025 }, { evidence_status: 'inferred' }, { institution: null }]) {
    const rows = pair(); Object.assign(rows[1].current_position, changed);
    const graph = buildTrajectoryHypergraph(rows, 'A', { ...options, includeInferredDepartments: false });
    assert.deepEqual(incidentStages(graph, 'B'), ['doctoral']);
    assert.equal(graph.edges[0].memberEvidence[0].peerStage, 'doctoral');
  }
});

test('the 2026 release retains both memberships for a real doctoral pair with different postdocs', () => {
  const dashboard = JSON.parse(readFileSync('public/data/dashboard.json', 'utf8'));
  const metadata = JSON.parse(readFileSync('public/data/constellation_metadata.json', 'utf8'));
  const records = toResearcherRecords(applyInstitutionSuccessions(mergeMetadata(dashboard, metadata)).professors);
  // Public anonymous identifiers only; no name or private identity lookup.
  const selectedId = 'P-SB67DFLSYC', peerId = 'P-B5ACEKWB77';
  const graph = buildTrajectoryHypergraph(records, selectedId, options);
  assert.deepEqual(incidentStages(graph, peerId), ['doctoral', 'current']);
  const overlapping = graph.edges.filter(e => e.memberEvidence.some(x => x.peerId === peerId));
  assert.deepEqual(overlapping.map(e => [e.lifetimeStage, e.institution]), [
    ['doctoral', 'Chosun University'], ['current', 'Chosun University'],
  ]);
  assert.ok(overlapping.every(e => memberIds(graph, e).includes(selectedId) && memberIds(graph, e).includes(peerId)));
});
