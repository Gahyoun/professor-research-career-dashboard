import type { CitationGroup, NodeCitation } from './abaNodes';
import type { AbaPaper } from './abaVault';

type Props = {
  nodeLabel: string;
  groups: CitationGroup[];
  activeGroup: CitationGroup | undefined;
  routeIndex: number;
  activeRoute: NodeCitation | undefined;
  status: string;
  onGroup: (id: number) => void;
  onRoute: (index: number) => void;
  onClose: () => void;
  detailRef: React.Ref<HTMLElement>;
  children?: React.ReactNode;
};

function Work({ stage, paper }: { stage: string; paper: AbaPaper }) {
  return <li>
    <span>{stage} <time>{paper.year}</time></span>
    <a href={`https://openalex.org/W${paper.id}`} target="_blank" rel="noreferrer">{paper.title}</a>
  </li>;
}

export default function AbaNodeDetail({ nodeLabel, groups, activeGroup, routeIndex, activeRoute, status, onGroup, onRoute, onClose, detailRef, children }: Props) {
  const count = groups.reduce((sum, group) => sum + group.routes.length, 0);
  return <section className="aba-node-detail" aria-label="선택한 노드의 A–B–A 인용" ref={detailRef} tabIndex={-1}>
    <header>
      <div><h4>A–B–A 인용</h4><p>{nodeLabel}{count > 0 && ` · B ${groups.length.toLocaleString('ko-KR')}편 · ${count.toLocaleString('ko-KR')}개 경로`}</p></div>
      <button className="v2-btn-quiet" type="button" onClick={onClose}>닫기</button>
    </header>
    {status && <p className="aba-node-status" role="status">{status}</p>}
    {activeGroup && activeRoute && <>
      {(groups.length > 1 || activeGroup.routes.length > 1) && <div className="aba-node-controls">
        {groups.length > 1 && <label>가운데 B 논문
          <select value={activeGroup.middle.id} onChange={e => onGroup(Number(e.target.value))}>
            {groups.map(group => <option value={group.middle.id} key={group.middle.id}>{group.middle.year} · {group.middle.title}</option>)}
          </select>
        </label>}
        {activeGroup.routes.length > 1 && <div className="aba-node-pager" role="group" aria-label="같은 B를 거치는 경로">
          <button type="button" className="v2-btn-quiet" disabled={routeIndex === 0} onClick={() => onRoute(routeIndex - 1)}>이전</button>
          <span aria-live="polite">{routeIndex + 1} / {activeGroup.routes.length}</span>
          <button type="button" className="v2-btn-quiet" disabled={routeIndex + 1 === activeGroup.routes.length} onClick={() => onRoute(routeIndex + 1)}>다음</button>
        </div>}
      </div>}
      <ol className="aba-node-works" aria-label="A₁, B, A₂ 논문">
        <Work stage="A₁" paper={activeRoute.path.first} />
        <Work stage="B" paper={activeRoute.path.middle} />
        <Work stage="A₂" paper={activeRoute.path.last} />
      </ol>
    </>}
    {children}
  </section>;
}
