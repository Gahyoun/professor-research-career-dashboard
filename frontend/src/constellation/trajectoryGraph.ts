import { buildHypergraph, type Hypergraph, type ResearcherRecord } from './hypergraph';
import { buildLifetimeTrajectory, type LifetimeOptions } from './lifetime';

/** Stage-window ego unions, with individual overlap evidence on every member. */
export function buildTrajectoryHypergraph(records: readonly ResearcherRecord[], selectedId: string,
  options: LifetimeOptions = {}): Hypergraph {
  const graph = buildHypergraph(records, { spatialEnabled: false, temporalEnabled: false, cohortEnabled: false,
    includeEstimated: options.includeEstimated, estimatedYears: options.estimatedYears,
    includeInferredDepartments: options.includeInferredDepartments });
  const index = new Map(graph.nodes.map((node, i) => [node.id, i]));
  const selectedIndex = index.get(selectedId);
  graph.timeWindows = [];
  if (selectedIndex === undefined) return graph;
  const lifetime = buildLifetimeTrajectory(records, selectedId, options);
  const groups = lifetime.stages.flatMap(stage => stage.groups);
  const sharedYears = graph.nodes.map(() => new Set<number>());
  for (const group of groups) {
    const members = group.members.map(id => index.get(id)).filter((i): i is number => i !== undefined).sort((a, b) => a - b);
    if (members.length < 2) continue;
    const evidence = group.memberEvidence.filter(item => index.has(item.peerId));
    graph.edges.push({ id: group.id, kind: 'cohort', degree: group.stage === 'doctoral' ? 'phd' : undefined,
      label: group.label, members, institution: group.institution, department: group.department, country: group.country,
      years: Array.from({ length: group.endYear - group.startYear + 1 }, (_, i) => group.startYear + i),
      lifetimeStage: group.stage, condition: group.condition, startYear: group.startYear, endYear: group.endYear,
      estimated: group.estimated, inferredDepartment: group.inferredDepartment,
      temporalSemantics: group.temporalSemantics, memberEvidence: evidence,
      weight: 1, sizeAdjustment: 1, overlapAdjustment: 1 });
    graph.timeWindows.push({ nodeIndex: selectedIndex, startYear: group.startYear, endYear: group.endYear,
      estimated: group.estimated, degree: group.stage === 'doctoral' ? 'phd' : undefined });
    for (const item of evidence) {
      const peerIndex = index.get(item.peerId)!;
      graph.timeWindows.push({ nodeIndex: peerIndex, startYear: item.startYear, endYear: item.endYear, estimated: item.estimated });
      for (let year = item.startYear; year <= item.endYear; year++) {
        sharedYears[selectedIndex].add(year); sharedYears[peerIndex].add(year);
      }
    }
  }
  graph.nodes.forEach((node, i) => {
    const years = [...sharedYears[i]];
    if (years.length) node.layoutYear = Math.round(years.reduce((sum, year) => sum + year, 0) / years.length);
  });
  graph.edges.forEach((edge, edgeIndex) => { for (const member of edge.members) graph.incidence[member].push(edgeIndex); });
  const intersections = new Map<number, number>();
  const count = graph.edges.length;
  for (const incidence of graph.incidence) {
    for (let a = 0; a < incidence.length; a++) for (let b = a + 1; b < incidence.length; b++) {
      const key = incidence[a] * count + incidence[b];
      intersections.set(key, (intersections.get(key) ?? 0) + 1);
    }
  }
  const redundancy = new Float64Array(count);
  for (const [key, intersection] of intersections) {
    const a = Math.floor(key / count), b = key % count;
    const jaccard = intersection / (graph.edges[a].members.length + graph.edges[b].members.length - intersection);
    redundancy[a] += jaccard; redundancy[b] += jaccard;
  }
  graph.edges.forEach((edge, i) => {
    edge.sizeAdjustment = 1 / (edge.members.length - 1);
    edge.overlapAdjustment = 1 / (1 + redundancy[i]);
    edge.weight = edge.members.length * edge.sizeAdjustment * edge.overlapAdjustment;
  });
  graph.diagnostics.cohortEdgeCount = count;
  graph.diagnostics.isolatedCount = graph.incidence.filter(edges => edges.length === 0).length;
  graph.diagnostics.incidenceCount = graph.incidence.reduce((sum, edges) => sum + edges.length, 0);
  graph.diagnostics.missingDepartmentCount = lifetime.coverage.missingDepartmentIntervals;
  graph.diagnostics.missingCountryCount = lifetime.coverage.missingCountryIntervals;
  graph.diagnostics.excludedInferredDepartmentCount = lifetime.coverage.excludedInferredDepartmentIntervals;
  return graph;
}

export const buildLifetimeHypergraph = buildTrajectoryHypergraph;
