import { formatShare, type ResearchProfile } from './researchAreas';

type Node = { name: string; share: number | null; children: Node[] };

/** Field › subfield › topic outline of one researcher's OpenAlex areas. Shares are of all retained works. */
export function areaTree(profile: ResearchProfile): { domain: string; fields: Node[] } [] {
  const shares = new Map([...profile.fields, ...profile.subfields, ...profile.topics].map(a => [a.path.join('\u0000'), a.share]));
  const roots = new Map<string, Map<string, Node>>();
  const child = (list: Node[], name: string, key: string) => {
    let node = list.find(n => n.name === name);
    if (!node) list.push(node = { name, share: shares.get(key) ?? null, children: [] });
    return node;
  };
  for (const area of [...profile.fields, ...profile.subfields, ...profile.topics]) {
    const [domain, field, ...rest] = area.path;
    if (!domain || !field) continue;
    const fields = roots.get(domain) ?? new Map<string, Node>();
    roots.set(domain, fields);
    const fieldNode = fields.get(field) ?? { name: field, share: shares.get([domain, field].join('\u0000')) ?? null, children: [] };
    fields.set(field, fieldNode);
    let parent = fieldNode, key = [domain, field];
    for (const name of rest) { key = [...key, name]; parent = child(parent.children, name, key.join('\u0000')); }
  }
  const order = (nodes: Node[]): Node[] => nodes.sort((a, b) => (b.share ?? 0) - (a.share ?? 0)).map(n => ({ ...n, children: order(n.children) }));
  return [...roots].map(([domain, fields]) => ({ domain, fields: order([...fields.values()]) }))
    .sort((a, b) => (b.fields[0]?.share ?? 0) - (a.fields[0]?.share ?? 0));
}

function Branch({ nodes, depth }: { nodes: Node[]; depth: number }) {
  if (!nodes.length) return null;
  return <ul className={`area-tree-level area-tree-${depth}`}>{nodes.map(node => <li key={node.name}>
    <span className="area-tree-row"><span className="area-tree-name">{node.name}</span>{node.share !== null && <span className="area-tree-share">{formatShare(node.share)}</span>}</span>
    <Branch nodes={node.children} depth={depth + 1} />
  </li>)}</ul>;
}

export default function ResearchAreaTree({ profile, title = 'OpenAlex 연구분야' }: { profile: ResearchProfile | undefined; title?: string }) {
  if (!profile) return null;
  const tree = areaTree(profile);
  return <section className="area-tree" aria-label={title}>
    <h3>{title} <small>domain › field › subfield › topic · 논문 {profile.works.toLocaleString('ko-KR')}편 기준</small></h3>
    {tree.map(({ domain, fields }) => <div key={domain}><p className="area-tree-domain">{domain}</p><Branch nodes={fields} depth={0} /></div>)}
    <p className="area-tree-note">각 논문의 OpenAlex primary topic을 집계했습니다. 비율은 동명이인 제외 후 남은 전체 논문 대비이며, 상위 항목만 표시합니다.</p>
  </section>;
}
