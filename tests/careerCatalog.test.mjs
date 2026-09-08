import assert from 'node:assert/strict';
import test from 'node:test';
import { readFileSync } from 'node:fs';
import { mergeMetadata } from '../work/test-dist/metadata.js';
import { applyInstitutionSuccessions } from '../work/test-dist/institutionSuccession.js';
import { toResearcherRecords } from '../work/test-dist/constellation/records.js';
import { createLifetimeIndex } from '../work/test-dist/constellation/lifetime.js';
import { summarizeCareer } from '../work/test-dist/constellation/careerCatalog.js';

test('the worker projection excludes identity extras from nested records without mutating sources', () => {
  const unit = { institution: 'School', country: 'KR', department: 'Physics', name: 'PRIVATE NAME', source_url: 'https://PRIVATE.example' };
  const rows = [{ id: 'anonymous', name: 'PRIVATE NAME', subject: 'physics', phd_institution: 'School',
    career: [{ ...unit, stage: 'doctoral', start_year: 2000, end_year: 2005, is_estimated: false }],
    faculty_appointments: [{ ...unit, role: 'faculty', start_year: 2010, end_year: 2015, evidence_kind: 'verified_cv', evidence_status: 'verified' }],
    current_position: { ...unit, observation_year: 2026, evidence_kind: 'semester_roster', evidence_status: 'observed' },
  }];
  const before = JSON.stringify(rows);
  const projected = toResearcherRecords(rows);
  assert.ok(!JSON.stringify(projected).includes('PRIVATE'));
  assert.equal(projected[0].faculty_appointments[0].evidence_kind, 'verified_cv');
  assert.equal(projected[0].career[0].is_estimated, false);
  assert.equal(JSON.stringify(rows), before);
});

test('catalogue summaries distinguish missing evidence, unmatched intervals and shared peers across stages', () => {
  const current = { institution: 'School', country: 'KR', department: 'Physics', observation_year: 2026, evidence_kind: 'semester_roster', evidence_status: 'observed' };
  const student = id => ({ id, phd_institution: 'School', phd_country: 'KR', phd_department: 'Physics', phd_year: 2005, current_position: current });
  const index = createLifetimeIndex([student('A'), student('B'), { id: 'missing' }, { ...student('alone'), phd_institution: 'Other', current_position: null }], { releaseYear: 2026 });
  const connected = summarizeCareer(index.get('A'));
  assert.equal(connected.groupCount, 2);
  assert.equal(connected.peerCount, 1, 'the same colleague across stages is counted once');
  assert.deepEqual(connected.stages.doctoral, { intervalCount: 1, groupCount: 1, peerCount: 1 });
  assert.deepEqual(connected.stages.current, { intervalCount: 1, groupCount: 1, peerCount: 1 });
  assert.equal(summarizeCareer(index.get('missing')).eligibleStages, 0);
  assert.deepEqual(summarizeCareer(index.get('alone')).stages.doctoral, { intervalCount: 1, groupCount: 0, peerCount: 0 });
});

test('every released professor has a four-stage catalogue row, including people without graph edges', () => {
  const dashboard = JSON.parse(readFileSync('public/data/dashboard.json', 'utf8'));
  const metadata = JSON.parse(readFileSync('public/data/constellation_metadata.json', 'utf8'));
  const merged = applyInstitutionSuccessions(mergeMetadata(dashboard, metadata));
  const records = toResearcherRecords(merged.professors);
  const started = performance.now();
  const index = createLifetimeIndex(records, { releaseYear: dashboard.meta.release_year, includeEstimated: true, estimatedYears: 5, includeInferredDepartments: true });
  assert.equal(index.ids.length, dashboard.meta.professor_count);
  assert.deepEqual(new Set(index.ids), new Set(dashboard.professors.map(person => person.id)));
  let connected = 0, noEvidence = 0, unmatched = 0;
  const stages = {};
  for (const id of index.ids) {
    const result = index.get(id), summary = summarizeCareer(result);
    assert.equal(result.selectedFound, true);
    assert.equal(summary.id, id);
    assert.equal(Object.keys(summary.stages).length, 4);
    assert.ok(!JSON.stringify(summary).includes('source_url'));
    if (summary.groupCount) connected++;
    else if (summary.eligibleStages) unmatched++;
    else noEvidence++;
    for (const [stage, row] of Object.entries(summary.stages)) {
      stages[stage] ||= { eligible: 0, connected: 0 };
      stages[stage].eligible += Number(row.intervalCount > 0);
      stages[stage].connected += Number(row.groupCount > 0);
      assert.ok(row.groupCount <= row.intervalCount);
      assert.ok(row.peerCount <= summary.peerCount);
    }
  }
  assert.equal(connected + noEvidence + unmatched, dashboard.meta.professor_count);
  assert.ok(connected > 0 && noEvidence > 0 && unmatched > 0);
  console.log(JSON.stringify({ careerCatalog: { total: index.ids.length, connected, noEvidence, unmatched, stages, elapsedMs: Math.round(performance.now() - started) } }));
});
