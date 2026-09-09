import assert from 'node:assert/strict';
import test from 'node:test';
import { visibleEdges, envelopePaddings } from '../work/test-dist/constellation/edgePresentation.js';
import { smoothEnvelope } from '../work/test-dist/constellation/smoothEnvelope.js';

const edges = [
  { id: 'doctoral', lifetimeStage: 'doctoral', startYear: 2000, kind: 'cohort', members: [0, 1, 2] },
  { id: 'postdoc', lifetimeStage: 'postdoc', startYear: 2006, kind: 'cohort', members: [0, 3] },
  { id: 'current', lifetimeStage: 'current', startYear: 2026, kind: 'cohort', members: [0, 1, 2] },
];
test('emphasizing any career group retains both shared and unrelated stage contexts', () => {
  const before = structuredClone(edges);
  for (const selected of ['', 'doctoral', 'postdoc', 'current']) {
    const visible = visibleEdges(edges, 'researcher', selected, 0);
    assert.deepEqual(visible.map(edge => edge.id), ['doctoral', 'postdoc', 'current']);
    assert.deepEqual(visible.filter(edge => edge.members.includes(1)).map(edge => edge.id), ['doctoral', 'current']);
  }
  assert.deepEqual(edges, before);
  assert.deepEqual(visibleEdges(edges, 'institution', 'current', 0).map(edge => edge.id), ['current']);
});
test('identical memberships have separate stable envelopes, independent of edge input order', () => {
  const padding = envelopePaddings(edges, 24);
  assert.notEqual(padding.get('doctoral'), padding.get('current'));
  const reversed = envelopePaddings([...edges].reverse(), 24);
  for (const edge of edges) assert.equal(padding.get(edge.id), reversed.get(edge.id));
  const points = [{ x: 120, y: 130 }, { x: 180, y: 170 }, { x: 170, y: 100 }];
  assert.notEqual(smoothEnvelope(points, padding.get('doctoral')), smoothEnvelope(points, padding.get('current')));
});
