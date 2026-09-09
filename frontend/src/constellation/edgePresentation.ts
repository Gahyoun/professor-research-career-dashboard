import type { Hyperedge } from './hypergraph';

/** Focusing a group is an emphasis, never an exclusive membership assignment. */
export function visibleEdges(edges: readonly Hyperedge[], scope: 'institution' | 'researcher', selectedEdge: string, selectedIndex?: number): Hyperedge[] {
  if (scope === 'researcher') return [...edges];
  if (selectedEdge) return edges.filter(edge => edge.id === selectedEdge);
  if (selectedIndex === undefined) return [];
  return edges.filter(edge => edge.members.includes(selectedIndex))
    .sort((a, b) => (a.kind === 'temporal' ? 1 : 0) - (b.kind === 'temporal' ? 1 : 0) || a.members.length - b.members.length).slice(0, 1);
}

/** Stable offsets keep equal-membership edges separately visible at every focus state. */
export function envelopePaddings(edges: readonly Hyperedge[], base: number): Map<string, number> {
  const signatures = new Map<string, Hyperedge[]>();
  for (const edge of edges) {
    const signature = [...edge.members].sort((a, b) => a - b).join(',');
    const group = signatures.get(signature) ?? [];
    group.push(edge); signatures.set(signature, group);
  }
  const stages = ['doctoral', 'postdoc', 'first_faculty', 'current'];
  const result = new Map<string, number>();
  for (const group of signatures.values()) {
    group.sort((a, b) => stages.indexOf(a.lifetimeStage ?? '') - stages.indexOf(b.lifetimeStage ?? '') || (a.startYear ?? 0) - (b.startYear ?? 0) || a.id.localeCompare(b.id));
    group.forEach((edge, rank) => result.set(edge.id, base + rank * 12));
  }
  return result;
}
