import assert from 'node:assert/strict';
import test from 'node:test';
import { buildHypergraph } from '../work/test-dist/constellation/hypergraph.js';
import { layoutLifetimeHypergraph } from '../work/test-dist/constellation/lifetimeLayout.js';

const options = { width: 1400, height: 1000, padding: 55, minDistance: 14, chronologicalStrength: .45 };
function graphFor(ids, definitions, years = {}) {
  const graph = buildHypergraph(ids.map(id => ({ id, subject: 'physics' })), { spatialEnabled: false, temporalEnabled: false, cohortEnabled: false });
  graph.nodes.forEach(node => { if (years[node.id] !== undefined) node.layoutYear = years[node.id]; });
  graph.edges = definitions.map(([id, stage, members, startYear, weight = 1]) => ({
    id, kind: 'cohort', lifetimeStage: stage, label: id, startYear, endYear: startYear,
    members: members.map(member => ids.indexOf(member)), weight, sizeAdjustment: 1, overlapAdjustment: 1,
  }));
  graph.incidence = ids.map((_, index) => graph.edges.flatMap((edge, edgeIndex) => edge.members.includes(index) ? [edgeIndex] : []));
  return graph;
}
const pointMap = layout => new Map(layout.positions.map(point => [point.id, point]));
const dist = (a, b) => Math.hypot(a.x - b.x, a.y - b.y);
function weightedAnchor(layout, graph, id) {
  const nodeIndex = graph.nodes.findIndex(node => node.id === id);
  const anchors = graph.incidence[nodeIndex].map(edgeIndex => layout.edgeAnchors.find(anchor => anchor.id === graph.edges[edgeIndex].id));
  const total = anchors.reduce((sum, anchor) => sum + anchor.weight, 0);
  return anchors.reduce((point, anchor) => ({ x: point.x + anchor.x * anchor.weight / total, y: point.y + anchor.y * anchor.weight / total }), { x: 0, y: 0 });
}
function audit(graph, layout, settings = options) {
  assert.deepEqual(layout.positions.map(point => point.id), graph.nodes.map(node => node.id));
  assert.equal(new Set(layout.positions.map(point => point.id)).size, graph.nodes.length);
  assert.equal(layout.edgeAnchors.length, graph.edges.length);
  for (const point of layout.positions) {
    assert.ok(Number.isFinite(point.x) && Number.isFinite(point.y));
    assert.ok(point.x >= settings.padding - 1e-8 && point.x <= settings.width - settings.padding + 1e-8);
    assert.ok(point.y >= settings.padding - 1e-8 && point.y <= settings.height - settings.padding + 1e-8);
  }
  let collisions = 0;
  for (let i = 0; i < layout.positions.length; i++) for (let j = 0; j < i; j++) {
    if (dist(layout.positions[i], layout.positions[j]) < layout.diagnostics.effectiveMinDistance - 1e-7) collisions++;
  }
  assert.equal(collisions, 0);
  assert.equal(layout.diagnostics.collisionPairs, collisions);
  assert.ok(Number.isFinite(layout.diagnostics.objective));
  assert.match(layout.diagnostics.method, /heuristic/);
  assert.match(layout.diagnostics.objectiveDefinition, /after collision repair, not globally minimized/);
}

test('shared doctoral and current members remain near their joint anchors despite divergent postdocs and historical years', () => {
  const definitions = [
    ['doctoral', 'doctoral', ['ego', 'a', 'b'], 2005],
    ['postdoc-a', 'postdoc', ['ego', 'a', 'p'], 2010],
    ['postdoc-b', 'postdoc', ['ego', 'b', 'q'], 2017],
    ['current', 'current', ['ego', 'a', 'b', 'r'], 2026],
  ];
  const graph = graphFor(['ego', 'a', 'b', 'p', 'q', 'r'], definitions, { a: 1960, b: 2026 });
  const original = JSON.stringify(graph);
  const layout = layoutLifetimeHypergraph(graph, options), points = pointMap(layout);
  audit(graph, layout);
  for (const id of ['a', 'b']) assert.ok(dist(points.get(id), weightedAnchor(layout, graph, id)) < 1e-8);
  assert.ok(dist(points.get('a'), points.get('b')) < 180, 'a common current group must not be separated into distant historical-year lanes');
  const doctoral = layout.edgeAnchors.find(anchor => anchor.id === 'doctoral');
  const current = layout.edgeAnchors.find(anchor => anchor.id === 'current');
  const joint = { x: (doctoral.x + current.x) / 2, y: (doctoral.y + current.y) / 2 };
  for (const [id, postdoc] of [['a', 'postdoc-a'], ['b', 'postdoc-b']]) {
    assert.ok(dist(points.get(id), joint) < dist(points.get(id), layout.edgeAnchors.find(anchor => anchor.id === postdoc)));
  }
  const changedYears = graphFor(graph.nodes.map(node => node.id), definitions, { a: 2026, b: 1900, ego: 1950 });
  assert.deepEqual(layoutLifetimeHypergraph(changedYears, options).positions, layout.positions);
  assert.equal(JSON.stringify(graph), original, 'layout must preserve all edge members and incidence arrays');
});

test('identical memberships retain separate stage anchors and use every edge weight, with one position per person', () => {
  const graph = graphFor(['a', 'b'], [
    ['current', 'current', ['a', 'b'], 2026, 1],
    ['doctoral', 'doctoral', ['a', 'b'], 2005, 3],
  ]);
  const layout = layoutLifetimeHypergraph(graph, options);
  audit(graph, layout);
  assert.deepEqual(layout.edgeAnchors.map(anchor => anchor.id), ['doctoral', 'current']);
  assert.ok(dist(...layout.edgeAnchors) > 300);
  const centroid = { x: (layout.positions[0].x + layout.positions[1].x) / 2, y: (layout.positions[0].y + layout.positions[1].y) / 2 };
  assert.ok(dist(centroid, weightedAnchor(layout, graph, 'a')) < 1e-8);
  assert.equal(graph.edges.length, 2);
  assert.deepEqual(graph.incidence, [[0, 1], [0, 1]]);
});

test('year ordering stays inside a bounded incidence-identical cloud, independent of absolute year spread', () => {
  const ids = Array.from({ length: 20 }, (_, index) => `r${index}`);
  const definitions = [['doctoral', 'doctoral', ids, 2000], ['current', 'current', ids, 2026]];
  const years = Object.fromEntries(ids.map((id, index) => [id, 1900 + index * 6]));
  const graph = graphFor(ids, definitions, years), layout = layoutLifetimeHypergraph(graph, { ...options, chronologicalStrength: 1 });
  audit(graph, layout);
  const center = weightedAnchor(layout, graph, ids[0]);
  assert.ok(layout.positions.every(point => dist(point, center) < 60));
  const ordered = pointMap(layout);
  for (let index = 1; index < ids.length; index++) assert.ok(ordered.get(ids[index]).y >= ordered.get(ids[index - 1]).y);
  const narrowYears = Object.fromEntries(ids.map((id, index) => [id, 2000 + index]));
  assert.deepEqual(layoutLifetimeHypergraph(graphFor(ids, definitions, narrowYears), { ...options, chronologicalStrength: 1 }).positions, layout.positions);
});

test('dense layouts are finite, deterministic, collision-free and keep requested versus feasible spacing honest', () => {
  const ids = Array.from({ length: 640 }, (_, index) => `person-${index}`);
  const graph = graphFor(ids, [['current', 'current', ids, 2026]]);
  const settings = { ...options, width: 300, height: 200, padding: 20, minDistance: 20 };
  const layout = layoutLifetimeHypergraph(graph, settings);
  audit(graph, layout, settings);
  assert.deepEqual(layoutLifetimeHypergraph(graph, settings).positions, layout.positions);
  assert.equal(layout.diagnostics.requestedMinDistance, 20);
  assert.ok(layout.diagnostics.effectiveMinDistance < 20);
  assert.equal(layout.diagnostics.components, 1);
});

test('input permutation does not change positions; all three or four enabled stages keep distinct anchors', () => {
  const ids = ['ego', 'a', 'b', 'c', 'd'];
  const definitions = [
    ['current', 'current', ['ego', 'a', 'b', 'c'], 2026],
    ['postdoc-later', 'postdoc', ['ego', 'b'], 2015],
    ['doctoral', 'doctoral', ['ego', 'a'], 2001],
    ['first', 'first_faculty', ['ego', 'd'], 2020],
    ['postdoc-earlier', 'postdoc', ['ego', 'c'], 2010],
  ];
  for (const includeFirst of [false, true]) {
    const edges = definitions.filter(definition => includeFirst || definition[1] !== 'first_faculty');
    const graph = graphFor(ids, edges), layout = layoutLifetimeHypergraph(graph, options);
    const reversed = layoutLifetimeHypergraph(graphFor([...ids].reverse(), [...edges].reverse()), options);
    audit(graph, layout);
    assert.deepEqual(pointMap(reversed), pointMap(layout));
    assert.deepEqual(layout.edgeAnchors.map(anchor => anchor.id), ['doctoral', 'postdoc-earlier', 'postdoc-later', ...(includeFirst ? ['first'] : []), 'current']);
  }
});

test('empty and singleton graphs are valid, and disconnected researchers remain separate nodes', () => {
  const empty = graphFor([], []), emptyLayout = layoutLifetimeHypergraph(empty, options);
  audit(empty, emptyLayout); assert.equal(emptyLayout.diagnostics.components, 0);
  const single = graphFor(['only'], []), singleLayout = layoutLifetimeHypergraph(single, options);
  audit(single, singleLayout); assert.deepEqual(singleLayout.positions, [{ id: 'only', x: 700, y: 500 }]);
  const isolated = graphFor(['one', 'two', 'three'], []), isolatedLayout = layoutLifetimeHypergraph(isolated, options);
  audit(isolated, isolatedLayout); assert.equal(isolatedLayout.diagnostics.components, 3);
});
