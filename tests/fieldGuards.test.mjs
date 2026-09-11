import assert from 'node:assert/strict';
import test from 'node:test';
import { readFileSync } from 'node:fs';
import { createLifetimeIndex } from '../work/test-dist/constellation/lifetime.js';
import { buildTrajectoryHypergraph } from '../work/test-dist/constellation/trajectoryGraph.js';
import { normalizeInstitution } from '../work/test-dist/constellation/hypergraph.js';
import { toResearcherRecords } from '../work/test-dist/constellation/records.js';
import { mergeMetadata } from '../work/test-dist/metadata.js';
import { applyInstitutionSuccessions } from '../work/test-dist/institutionSuccession.js';

const options = { releaseYear: 2026, includeEstimated: true, estimatedYears: 5, includeInferredDepartments: true };
const historicalUnit = { institution: 'Graduate University', country: 'KR', department: 'Physics' };
const faculty = (extra = {}) => ({ ...historicalUnit, role: 'faculty', start_year: 2012, end_year: 2016,
  evidence_kind: 'verified_cv', evidence_status: 'verified', ...extra });
const researcher = (id, subject = 'physics') => ({ id, subject, phd_year: 2010,
  phd_institution: 'Graduate University', phd_country: 'KR', phd_department: 'Physics',
  career: [{ stage: 'postdoc', institution: 'Research Institute', country: 'KR', department: null,
    start_year: 2011, end_year: 2013, is_estimated: false }],
  faculty_appointments: [faculty({ rank: 'assistant_professor', first_assistant_professor_verified: true })],
  current_position: { institution: 'Current University', country: 'KR', department: null,
    observation_year: 2026, evidence_kind: 'semester_roster', evidence_status: 'observed' },
});
const stage = (result, name) => result.stages.find(item => item.stage === name);
const members = (graph, edge) => edge.members.map(i => graph.nodes[i].id);

test('every lifetime stage requires the same valid recorded field without relabeling it as a department', () => {
  const rows = [researcher('A'), researcher('B'), researcher('different-field', 'biology')];
  const prepared = createLifetimeIndex(rows, options).get('A');
  const graph = buildTrajectoryHypergraph(rows, 'A', options, prepared);
  assert.deepEqual(graph.edges.map(edge => edge.lifetimeStage), ['doctoral', 'postdoc', 'first_faculty', 'current']);
  for (const edge of graph.edges) {
    assert.deepEqual(members(graph, edge), ['A', 'B']);
    const departmentRequired = ['doctoral', 'first_faculty'].includes(edge.lifetimeStage);
    for (const value of [edge, ...edge.memberEvidence]) {
      assert.equal(value.subject, 'physics');
      assert.equal(value.subjectProvenance, 'recorded_researcher_subject');
      assert.equal(value.matchingBasis, departmentRequired ? 'institution_department_subject' : 'institution_subject');
      assert.equal(value.department, departmentRequired ? 'Physics' : undefined);
    }
  }
  assert.deepEqual(prepared.peers.map(peer => peer.id), ['B']);
  assert.equal(prepared.peers[0].stageCount, 4);
});

test('doctoral and first faculty retain historical department guards after the recorded field guard', () => {
  const rows = [researcher('A'), researcher('B'), researcher('different-department'), researcher('missing-department')];
  rows[2].phd_department = 'Mathematics'; rows[2].faculty_appointments[0].department = 'Mathematics';
  rows[3].phd_department = null; rows[3].faculty_appointments[0].department = null;
  const result = createLifetimeIndex(rows, options).get('A');
  for (const name of ['doctoral', 'first_faculty']) assert.deepEqual(stage(result, name).groups[0].members, ['A', 'B']);
  for (const name of ['postdoc', 'current']) assert.deepEqual(stage(result, name).groups[0].members, ['A', 'B', 'different-department', 'missing-department']);
  const inferred = [researcher('A'), researcher('B')];
  inferred.forEach(row => { row.phd_department_inferred = true; row.faculty_appointments[0].department_inferred = true; });
  const strict = createLifetimeIndex(inferred, { ...options, includeInferredDepartments: false }).get('A');
  assert.equal(stage(strict, 'doctoral').groups.length, 0);
  assert.equal(stage(strict, 'first_faculty').groups.length, 0);
  assert.equal(stage(strict, 'postdoc').groups.length, 1);
  assert.equal(stage(strict, 'current').groups.length, 1);
});

test('missing and unsupported recorded fields exclude selections and peers at all stages with no fallback', () => {
  const rows = [researcher('A'), researcher('B')];
  for (const [i, subject] of [undefined, null, '', 'Physics', 'engineering'].entries()) {
    const row = researcher(`missing-${i}`); row.subject = subject; row.department = 'Physics';
    rows.push(row);
  }
  const index = createLifetimeIndex(rows, options);
  for (const result of index.get('A').stages) assert.deepEqual(result.groups[0].members, ['A', 'B']);
  for (const row of rows.slice(2)) {
    const result = index.get(row.id);
    assert.equal(result.coverage.eligibleIntervals, 0);
    assert.equal(result.peers.length, 0);
    assert.ok(result.stages.every(item => item.excludedReasons.some(reason => reason.includes('계열 정보'))));
  }
});

test('doctoral faculty peers must share both their historical department and their recorded field', () => {
  const rows = [researcher('A'), { id: 'physics-professor', subject: 'physics', faculty_appointments: [faculty({ start_year: 2000, end_year: 2010 })] },
    { id: 'biology-professor', subject: 'biology', faculty_appointments: [faculty({ start_year: 2000, end_year: 2010 })] }];
  const group = stage(createLifetimeIndex(rows, options).get('A'), 'doctoral').groups[0];
  assert.deepEqual(group.members, ['A', 'physics-professor']);
  assert.equal(group.memberEvidence[0].peerStage, 'faculty');
  assert.equal(group.memberEvidence[0].department, 'Physics');
});

test('postdoc peers of every allowed role share the recorded field while historical department remains optional', () => {
  const rows = [researcher('A'), researcher('postdoc-physics'), researcher('postdoc-math', 'mathematics')];
  rows[1].career[0].department = 'Different paper affiliation'; rows[1].career[0].department_inferred = true;
  for (const subject of ['physics', 'biology']) {
    rows.push({ id: `student-${subject}`, subject, phd_institution: 'Research Institute', phd_country: 'KR', phd_year: 2015 });
    rows.push({ id: `faculty-${subject}`, subject, faculty_appointments: [faculty({ institution: 'Research Institute', department: null })] });
  }
  for (const includeInferredDepartments of [false, true]) {
    const group = stage(createLifetimeIndex(rows, { ...options, includeInferredDepartments }).get('A'), 'postdoc').groups[0];
    assert.deepEqual(group.members, ['A', 'postdoc-physics', 'student-physics', 'faculty-physics']);
    assert.ok(group.memberEvidence.every(item => item.subject === 'physics' && item.department === undefined && item.inferredDepartment === false));
    assert.deepEqual(new Set(group.memberEvidence.map(item => item.peerStage)), new Set(['postdoc', 'doctoral', 'faculty']));
  }
  rows[1].career[0].start_year = 2014;
  rows.find(row => row.id === 'student-physics').phd_country = null;
  rows.find(row => row.id === 'faculty-physics').faculty_appointments[0].evidence_status = 'inferred';
  assert.equal(stage(createLifetimeIndex(rows, options).get('A'), 'postdoc').groups.length, 0);
});

function loadRecords() {
  return toResearcherRecords(applyInstitutionSuccessions(mergeMetadata(
    JSON.parse(readFileSync('public/data/dashboard.json', 'utf8')),
    JSON.parse(readFileSync('public/data/constellation_metadata.json', 'utf8')),
  )).professors);
}

test('the full release has no cross-field lifetime membership and preserves the complete observed current groups', () => {
  const records = loadRecords(), byId = new Map(records.map(row => [row.id, row]));
  const index = createLifetimeIndex(records, options);
  const expectedCurrent = new Map();
  const currentKey = row => `${normalizeInstitution(row.current_position.institution_canonical ?? row.current_position.institution)}::${row.subject}`;
  // Independent roster aggregation: the release has KR/unknown current countries
  // only, so no conflicting-country partition is needed for these observations.
  for (const row of records) if (row.current_position?.observation_year === 2026) {
    assert.ok(['KR', null, undefined].includes(row.current_position.country));
    const key = currentKey(row); if (!expectedCurrent.has(key)) expectedCurrent.set(key, []);
    expectedCurrent.get(key).push(row.id);
  }
  let connected = 0, noEvidence = 0, unmatched = 0;
  const counts = { doctoral: [0, 0], postdoc: [0, 0], first_faculty: [0, 0], current: [0, 0] };
  for (const id of index.ids) {
    const result = index.get(id), subject = byId.get(id).subject;
    if (result.coverage.groupCount) connected++; else if (result.coverage.eligibleIntervals) unmatched++; else noEvidence++;
    for (const item of result.stages) {
      if (item.intervals.length) counts[item.stage][0]++;
      if (item.groups.length) counts[item.stage][1]++;
      for (const value of [...item.intervals, ...item.groups, ...item.groups.flatMap(group => group.memberEvidence)]) {
        assert.equal(value.subject, subject); assert.equal(value.subjectProvenance, 'recorded_researcher_subject');
      }
      for (const group of item.groups) for (const member of group.members) assert.equal(byId.get(member).subject, subject);
    }
    for (const peer of result.peers) {
      assert.equal(byId.get(peer.id).subject, subject);
      assert.ok(peer.evidence.every(item => item.subject === subject));
    }
    const current = stage(result, 'current');
    if (current.intervals.length) {
      const expected = [...expectedCurrent.get(currentKey(byId.get(id)))].sort();
      assert.equal(current.groups.length, expected.length > 1 ? 1 : 0);
      if (current.groups.length) assert.deepEqual([...current.groups[0].members].sort(), expected);
    }
    // Build every ego graph from its prepared evidence to exercise both exported
    // hyperedges and incidence, without repeatedly scanning unrelated records.
    const localIds = new Set([id, ...result.peers.map(peer => peer.id)]);
    const graph = buildTrajectoryHypergraph([...localIds].map(member => byId.get(member)), id, options, result);
    for (const edge of graph.edges) {
      assert.equal(edge.subject, subject); assert.equal(edge.subjectProvenance, 'recorded_researcher_subject');
      assert.ok(members(graph, edge).every(member => byId.get(member).subject === subject));
      assert.ok(edge.memberEvidence.every(item => item.subject === subject));
    }
  }
  // Release sentinel after applying the strict KOAD namesake decision set to
  // every bibliographic input while recovering postdoc intervals only when a
  // strictly retained work supplies institution-and-time continuity evidence.
  assert.deepEqual({ total: index.ids.length, connected, noEvidence, unmatched, counts }, {
    total: 3937, connected: 3299, noEvidence: 610, unmatched: 28,
    counts: { doctoral: [801, 427], postdoc: [2130, 1782], first_faculty: [1, 0], current: [3241, 3240] },
  });
});
