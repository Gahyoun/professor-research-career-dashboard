import type { Hyperedge, Hypergraph, HypergraphLayout, LayoutOptions } from './hypergraph';

export interface LifetimeEdgeAnchor {
  id: string; x: number; y: number; stage?: Hyperedge['lifetimeStage'];
  startYear?: number; endYear?: number; weight: number;
}
export interface LifetimeHypergraphLayout extends HypergraphLayout {
  edgeAnchors: LifetimeEdgeAnchor[];
  diagnostics: HypergraphLayout['diagnostics'] & {
    objectiveDefinition: string; collisionRepairs: number; gridRepairs: number;
  };
}
type Point = { x: number; y: number };
const stageOrder = { doctoral: 0, postdoc: 1, first_faculty: 2, current: 3 };
const positive = (value: number | undefined, fallback: number) => Number.isFinite(value) && value! > 0 ? value! : fallback;
const lexical = (a: string, b: string) => a < b ? -1 : a > b ? 1 : 0;
function hash(value: string) {
  let valueHash = 2166136261;
  for (let i = 0; i < value.length; i++) valueHash = Math.imul(valueHash ^ value.charCodeAt(i), 16777619);
  return valueHash >>> 0;
}
const edgeYear = (value: number | undefined) => Number.isFinite(value) ? value! : Infinity;

/**
 * One position per researcher, averaged over ALL incident stage-window anchors.
 * This is a display heuristic, not a spectral embedding or a global optimum.
 * Years can reorder only a small cloud of incidence-identical researchers;
 * an unrelated old career can never overwrite a shared current group's y coordinate.
 */
export function layoutLifetimeHypergraph(graph: Hypergraph, options: LayoutOptions = {}): LifetimeHypergraphLayout {
  const started = performance.now();
  const width = Math.max(100, positive(options.width, 1200));
  const height = Math.max(100, positive(options.height, 800));
  const padding = Math.min(Math.min(width, height) / 4, positive(options.padding, 44));
  const innerWidth = width - 2 * padding, innerHeight = height - 2 * padding;
  const requestedDistance = positive(options.minDistance, 9);
  // This leaves at least four distance-spaced grid sites per researcher for the
  // rare repair step. Normal positions are continuous sunflower clouds, not a grid.
  const distance = Math.min(requestedDistance, .5 * Math.sqrt(innerWidth * innerHeight / Math.max(1, graph.nodes.length)));
  const chronologicalStrength = Number.isFinite(options.chronologicalStrength)
    ? Math.min(1, Math.max(0, options.chronologicalStrength!)) : .35;
  const sortedEdges = graph.edges.map((edge, index) => ({ edge, index })).sort((a, b) =>
    (stageOrder[a.edge.lifetimeStage!] ?? 4) - (stageOrder[b.edge.lifetimeStage!] ?? 4) ||
    edgeYear(a.edge.startYear) - edgeYear(b.edge.startYear) ||
    edgeYear(a.edge.endYear) - edgeYear(b.edge.endYear) || lexical(a.edge.id, b.edge.id));
  const incident = graph.nodes.map((_, nodeIndex) => [...new Set(graph.incidence[nodeIndex] ?? [])]
    .filter(edgeIndex => graph.edges[edgeIndex]).sort((a, b) => lexical(graph.edges[a].id, graph.edges[b].id)));
  const clouds = new Map<string, number[]>();
  incident.forEach((edges, nodeIndex) => {
    const key = JSON.stringify(edges.map(edgeIndex => graph.edges[edgeIndex].id));
    if (!clouds.has(key)) clouds.set(key, []);
    clouds.get(key)!.push(nodeIndex);
  });
  const maxCloudSize = Math.max(1, ...[...clouds.values()].map(cloud => cloud.length));
  const cloudClearance = distance * (.72 * Math.sqrt(maxCloudSize) + 1);
  const anchorRadiusX = Math.min(innerWidth * .29, Math.max(distance, innerWidth / 2 - cloudClearance));
  const anchorRadiusY = Math.min(innerHeight * .29, Math.max(distance, innerHeight / 2 - cloudClearance));
  const anchorsByIndex: LifetimeEdgeAnchor[] = [];
  const edgeAnchors = sortedEdges.map(({ edge, index }, rank) => {
    const angle = -3 * Math.PI / 4 + 2 * Math.PI * rank / sortedEdges.length;
    const anchor: LifetimeEdgeAnchor = { id: edge.id,
      x: width / 2 + (sortedEdges.length > 1 ? Math.cos(angle) * anchorRadiusX : 0),
      y: height / 2 + (sortedEdges.length > 1 ? Math.sin(angle) * anchorRadiusY : 0),
      stage: edge.lifetimeStage, startYear: edge.startYear, endYear: edge.endYear,
      weight: positive(edge.weight, 1),
    };
    anchorsByIndex[index] = anchor;
    return anchor;
  });
  const targets = incident.map(edges => {
    if (!edges.length) return { x: width / 2, y: height / 2 };
    const totalWeight = edges.reduce((sum, edgeIndex) => sum + anchorsByIndex[edgeIndex].weight, 0);
    return edges.reduce((point, edgeIndex) => {
      const anchor = anchorsByIndex[edgeIndex], weight = anchor.weight / totalWeight;
      point.x += anchor.x * weight; point.y += anchor.y * weight;
      return point;
    }, { x: 0, y: 0 });
  });
  const desired = targets.map(point => ({ ...point }));
  for (const [key, members] of clouds) {
    if (members.length < 2) continue;
    const phase = hash(key) / 4294967296 * 2 * Math.PI;
    const offsets = members.map((_, rank) => {
      const radius = distance * .72 * Math.sqrt(rank + .5), angle = phase + rank * 2.399963229728653;
      return { x: Math.cos(angle) * radius, y: Math.sin(angle) * radius };
    });
    const mean = offsets.reduce((sum, point) => ({ x: sum.x + point.x / members.length, y: sum.y + point.y / members.length }), { x: 0, y: 0 });
    const dated = members.filter(index => Number.isFinite(graph.nodes[index].layoutYear))
      .sort((a, b) => graph.nodes[a].layoutYear! - graph.nodes[b].layoutYear! || lexical(graph.nodes[a].id, graph.nodes[b].id));
    const yearRank = new Map(dated.map((index, rank) => [index, dated.length > 1 ? rank / (dated.length - 1) : .5]));
    const score = (index: number) => {
      const randomOrder = hash(graph.nodes[index].id) / 4294967296;
      return yearRank.has(index) && dated.length > 1
        ? chronologicalStrength * yearRank.get(index)! + (1 - chronologicalStrength) * randomOrder : randomOrder;
    };
    const order = [...members].sort((a, b) => score(a) - score(b) || lexical(graph.nodes[a].id, graph.nodes[b].id));
    // Only assignment within the same small cloud changes with the year ordering.
    offsets.sort((a, b) => a.y - b.y || a.x - b.x);
    order.forEach((nodeIndex, rank) => {
      desired[nodeIndex].x += offsets[rank].x - mean.x;
      desired[nodeIndex].y += offsets[rank].y - mean.y;
    });
  }

  const positions: Point[] = desired.map(point => ({ ...point }));
  const occupied = new Map<string, number[]>();
  const cell = (x: number, y: number) => `${Math.floor(x / distance)},${Math.floor(y / distance)}`;
  const inside = (point: Point) => point.x >= padding && point.x <= width - padding && point.y >= padding && point.y <= height - padding;
  const free = (point: Point) => {
    if (!inside(point)) return false;
    const gx = Math.floor(point.x / distance), gy = Math.floor(point.y / distance);
    for (let dx = -1; dx <= 1; dx++) for (let dy = -1; dy <= 1; dy++) {
      for (const index of occupied.get(`${gx + dx},${gy + dy}`) ?? []) {
        if (Math.hypot(point.x - positions[index].x, point.y - positions[index].y) < distance - 1e-7) return false;
      }
    }
    return true;
  };
  let collisionRepairs = 0, gridRepairs = 0;
  const order = graph.nodes.map((_, index) => index).sort((a, b) => incident[b].length - incident[a].length || lexical(graph.nodes[a].id, graph.nodes[b].id));
  for (const index of order) {
    const target = { x: Math.max(padding, Math.min(width - padding, desired[index].x)), y: Math.max(padding, Math.min(height - padding, desired[index].y)) };
    let chosen: Point | undefined = free(target) ? target : undefined;
    if (!chosen) {
      collisionRepairs++;
      const phase = hash(graph.nodes[index].id) / 4294967296 * 2 * Math.PI;
      for (let ring = 1; ring <= 24 && !chosen; ring++) {
        const radius = ring * distance / 2, samples = Math.max(8, Math.ceil(2 * Math.PI * ring));
        for (let sample = 0; sample < samples; sample++) {
          const angle = phase + 2 * Math.PI * sample / samples;
          const candidate = { x: target.x + Math.cos(angle) * radius, y: target.y + Math.sin(angle) * radius };
          if (free(candidate)) { chosen = candidate; break; }
        }
      }
    }
    if (!chosen) {
      gridRepairs++;
      let nearest = Infinity;
      for (let column = 0; column <= Math.floor(innerWidth / distance); column++) for (let row = 0; row <= Math.floor(innerHeight / distance); row++) {
        const candidate = { x: padding + column * distance, y: padding + row * distance };
        const squaredDistance = (candidate.x - target.x) ** 2 + (candidate.y - target.y) ** 2;
        if (squaredDistance < nearest && free(candidate)) { chosen = candidate; nearest = squaredDistance; }
      }
    }
    // With the conservative capacity bound, previously placed points cannot cover
    // all grid sites. Do not silently return an overlapping point if this fails.
    if (!chosen) throw new Error('Lifetime layout has no available collision-free position');
    positions[index] = chosen;
    const key = cell(chosen.x, chosen.y);
    if (!occupied.has(key)) occupied.set(key, []);
    occupied.get(key)!.push(index);
  }
  options.onProgress?.({ phase: 'overlap', progress: 1 });

  const parents = graph.nodes.map((_, index) => index);
  const root = (index: number): number => {
    while (parents[index] !== index) { parents[index] = parents[parents[index]]; index = parents[index]; }
    return index;
  };
  for (const edge of graph.edges) for (let i = 1; i < edge.members.length; i++) parents[root(edge.members[i])] = root(edge.members[0]);
  let objective = 0, connectedNodes = 0;
  const squaredDiagonal = innerWidth ** 2 + innerHeight ** 2;
  incident.forEach((edges, nodeIndex) => {
    if (!edges.length) return;
    connectedNodes++;
    const totalWeight = edges.reduce((sum, edgeIndex) => sum + anchorsByIndex[edgeIndex].weight, 0);
    for (const edgeIndex of edges) {
      const anchor = anchorsByIndex[edgeIndex];
      objective += anchor.weight / totalWeight * ((positions[nodeIndex].x - anchor.x) ** 2 + (positions[nodeIndex].y - anchor.y) ** 2) / squaredDiagonal;
    }
  });
  objective /= Math.max(1, connectedNodes);
  return { positions: positions.map((point, index) => ({ id: graph.nodes[index].id, ...point })), edgeAnchors,
    diagnostics: {
      method: 'Deterministic all-incidence stage-anchor barycentres with local sunflower clouds and collision repair (display heuristic)',
      objectiveDefinition: 'Mean, over connected nodes, of incident-edge-weight-normalized squared distance to every anchor, divided by viewport inner diagonal squared; evaluated after collision repair, not globally minimized.',
      objective, candidateObjectives: [objective], iterations: graph.nodes.length ? 1 : 0, restarts: 1,
      components: new Set(graph.nodes.map((_, index) => root(index))).size,
      collisionPairs: 0, collisionRepairs, gridRepairs,
      requestedMinDistance: requestedDistance, effectiveMinDistance: distance,
      chronologicalStrength, elapsedMs: performance.now() - started,
    },
  };
}
