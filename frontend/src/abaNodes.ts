import type { AbaPaper, AbaPath } from './abaVault';
import { eraOfYear, yearRange, type AlluvialMode, type PaperTitle, type TopicResearcher } from './topics';

export type NodeCitation = { path: AbaPath; first: string | null; last: string | null };
export type CitationGroup = { middle: AbaPaper; routes: NodeCitation[] };

export const citationNodeKey = (topic: number, column: number) => `${topic}:${column}`;
const titleKey = (year: number, title: string) => `${year}:${title.normalize('NFC').trim().replace(/\s+/gu, ' ').toLowerCase()}`;

export function indexNodeCitations(paths: AbaPath[], titles: PaperTitle[], researcher: TopicResearcher, mode: AlluvialMode) {
  const topicByTitle = new Map<string, Set<number>>();
  for (const row of titles) {
    const key = titleKey(row.year, row.title);
    const topics = topicByTitle.get(key) ?? new Set<number>();
    topics.add(row.topic);
    topicByTitle.set(key, topics);
  }
  const columnsByCell = new Map<string, Set<number | null>>();
  const firstYear = yearRange(researcher)?.[0] ?? 0;
  for (const paper of researcher.papers) {
    const key = citationNodeKey(paper.topic, paper.year);
    const columns = columnsByCell.get(key) ?? new Set<number | null>();
    columns.add(mode === 'year' ? paper.year - firstYear : paper.era ?? eraOfYear(researcher, paper.year));
    columnsByCell.set(key, columns);
  }
  const endpoints = new Map<number, string | null>();
  const endpoint = (paper: AbaPaper) => {
    if (endpoints.has(paper.id)) return endpoints.get(paper.id)!;
    const topics = topicByTitle.get(titleKey(paper.year, paper.title));
    const topic = topics?.size === 1 ? [...topics][0] : null;
    const columns = topic === null ? undefined : columnsByCell.get(citationNodeKey(topic, paper.year));
    // The encrypted title rows don't carry an era. A mixed cell cannot identify the work's era.
    const column = columns?.size === 1 ? [...columns][0] : null;
    const node = topic !== null && column !== null ? citationNodeKey(topic, column) : null;
    endpoints.set(paper.id, node);
    return node;
  };
  const byNode = new Map<string, Map<number, CitationGroup>>();
  for (const path of paths) {
    const first = endpoint(path.first), last = endpoint(path.last);
    const route = { path, first, last };
    for (const key of new Set([first, last])) {
      if (key === null) continue;
      const groups = byNode.get(key) ?? new Map<number, CitationGroup>();
      const group = groups.get(path.middle.id) ?? { middle: path.middle, routes: [] };
      group.routes.push(route);
      groups.set(path.middle.id, group);
      byNode.set(key, groups);
    }
  }
  return byNode;
}
