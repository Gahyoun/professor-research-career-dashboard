import {
  buildHypergraph, buildResearcherTrajectory, findTrajectoryPeers,
  type Hypergraph, type Hyperedge, type ResearcherRecord, type TrajectoryOptions,
} from './hypergraph';

function yearLabel(years: number[]): string {
  const runs: string[] = [];
  for (let i = 0; i < years.length; i++) {
    const start = years[i]; let end = start;
    while (i + 1 < years.length && years[i + 1] === end + 1) end = years[++i];
    runs.push(start === end ? String(start) : `${start}–${end}`);
  }
  return runs.join(', ');
}

/**
 * Exact ego hypergraph of jointly observed career units and years.
 * Only selected–peer evidence is used. A peer's unrelated career never adds members.
 * Canonical units, missing metadata and inference policy come from the shared core.
 */
export function buildTrajectoryHypergraph(
  records: readonly ResearcherRecord[], selectedId: string, options: TrajectoryOptions = {},
): Hypergraph {
  const graph = buildHypergraph(records, {
    spatialEnabled: false, temporalEnabled: false, cohortEnabled: false,
    includeEstimated: options.includeEstimated, estimatedYears: options.estimatedYears,
    includeInferredDepartments: options.includeInferredDepartments,
  });
  const index = new Map(graph.nodes.map((node, i) => [node.id, i]));
  const selectedIndex = index.get(selectedId);
  if (selectedIndex === undefined) return graph;
  const firstRecords = new Map<string, ResearcherRecord>();
  for (const record of records) if (!firstRecords.has(record.id)) firstRecords.set(record.id, record);
  const trajectories = graph.nodes.map(node => buildResearcherTrajectory(firstRecords.get(node.id)!, options));
  graph.timeWindows = trajectories.flatMap((trajectory, nodeIndex) => trajectory.intervals.map(interval => ({
    nodeIndex, startYear: interval.startYear, endYear: interval.endYear, estimated: interval.estimated,
  })));
  graph.diagnostics.spatialEligibleCount = trajectories.filter(t => t.intervals.length > 0).length;
  graph.diagnostics.missingCountryCount = trajectories.filter(t => t.coverage.missingCountryIntervals > 0).length;
  graph.diagnostics.missingDepartmentCount = trajectories.filter(t => t.coverage.missingDepartmentIntervals > 0).length;
  graph.diagnostics.excludedInferredDepartmentCount = trajectories.filter(t => t.coverage.excludedInferredDepartmentIntervals > 0).length;
  graph.diagnostics.inferredDepartmentCount = trajectories.filter(t => t.coverage.inferredDepartmentIntervals > 0).length;

  const peers = findTrajectoryPeers(records, selectedId, options).peers;
  type Unit = {
    institution: string; country: string; department?: string; inferred: boolean;
    years: Map<number, Set<number>>;
  };
  const units = new Map<string, Unit>();
  for (const peer of peers) {
    const peerIndex = index.get(peer.id);
    if (peerIndex === undefined || peerIndex === selectedIndex) continue;
    for (const evidence of peer.evidence) {
      if (!units.has(evidence.unitKey)) units.set(evidence.unitKey, {
        institution: evidence.institution, country: evidence.country, department: evidence.department,
        inferred: false, years: new Map(),
      });
      const unit = units.get(evidence.unitKey)!;
      unit.inferred ||= evidence.inferredDepartment;
      for (let year = evidence.startYear; year <= evidence.endYear; year++) {
        if (!unit.years.has(year)) unit.years.set(year, new Set([selectedIndex]));
        unit.years.get(year)!.add(peerIndex);
      }
    }
  }

  const sharedYears = graph.nodes.map(() => new Set<number>());
  for (const [unitKey, unit] of [...units].sort(([a], [b]) => a.localeCompare(b, 'en'))) {
    const memberships = new Map<string, Hyperedge>();
    for (const [year, memberSet] of [...unit.years].sort(([a], [b]) => a - b)) {
      if (memberSet.size < 2) continue;
      const members = [...memberSet].sort((a, b) => a - b);
      for (const nodeIndex of members) sharedYears[nodeIndex].add(year);
      const key = members.join(',');
      const previous = memberships.get(key);
      if (previous) previous.years!.push(year);
      else {
        const edge: Hyperedge = {
          id: `trajectory:${unitKey}:${year}`, kind: 'cohort', label: '',
          institution: unit.institution, country: unit.country, department: unit.department,
          inferredDepartment: unit.inferred, members, years: [year],
          weight: 1, sizeAdjustment: 1, overlapAdjustment: 1,
        };
        memberships.set(key, edge); graph.edges.push(edge);
      }
    }
  }
  graph.nodes.forEach((node, i) => {
    const years = [...sharedYears[i]];
    // Round only the display anchor, never source dates or evidence intervals.
    if (years.length) node.layoutYear = Math.round(years.reduce((sum, year) => sum + year, 0) / years.length);
  });
  for (let i = 0; i < graph.edges.length; i++) {
    const edge = graph.edges[i];
    edge.label = `경력 교차 · ${edge.institution}${edge.department ? ` · ${edge.department}` : ''} · ${yearLabel(edge.years!)}`;
    for (const nodeIndex of edge.members) graph.incidence[nodeIndex].push(i);
  }

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
  return graph;
}
