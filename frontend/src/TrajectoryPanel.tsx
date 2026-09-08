import type { TrajectoryCoverage, TrajectoryPeer, ResearcherRecord, TrajectoryInterval } from './constellation/hypergraph';

const stages: Record<string, string> = { doctoral: '박사과정', postdoc: '포닥·연구원', faculty: '교수' };
export default function TrajectoryPanel({ record, intervals: calculatedIntervals, peers, coverage, labelFor, onSelect, focused, onFocus }: {
  record: ResearcherRecord; intervals: TrajectoryInterval[]; peers: TrajectoryPeer[]; coverage: TrajectoryCoverage;
  labelFor: (id: string) => string; onSelect: (id: string) => void; focused: boolean; onFocus: () => void;
}) {
  const intervals = calculatedIntervals.map(c => ({ ...c, start_year: c.startYear, end_year: c.endYear, is_estimated: c.estimated, department_inferred: c.inferredDepartment })).toSorted((a,b) => a.startYear-b.startYear);
  const min = Math.min(...intervals.map(c => c.start_year!)), max = Math.max(...intervals.map(c => c.end_year!), min + 1);
  const span = max - min + 1;
  return <section className="trajectory-panel" aria-labelledby="trajectory-title">
    <div className="atlas-section-title"><div><span className="eyebrow">RESEARCH TRAJECTORY</span><h2 id="trajectory-title">{labelFor(record.id)}의 경로와 겹치는 연구자</h2></div><button className={focused ? 'selected' : ''} onClick={onFocus} disabled={focused}>{focused ? '경로 하이퍼그래프 표시 중' : '이 경로의 하이퍼그래프 보기'}</button></div>
    <p>같은 기관 단위와 같은 연도를 동시에 공유한 경력을 비교합니다. 국내는 학교+학과, 국외는 학교 단위입니다.</p>
    {intervals.length > 0 ? <div className="trajectory-timeline"><div className="trajectory-axis"><span>{min}</span><span>{max}</span></div>{intervals.map((c, i) => <div className="trajectory-stage" key={i}><span><b>{stages[c.stage] || c.stage}</b><small>{c.institution}{c.department ? ` · ${c.department}` : ''}</small>{c.department_inferred && <em>학과 추정</em>}</span><div className="trajectory-track"><i className={c.stage} style={{ left: `${(c.start_year! - min) / span * 100}%`, width: `${(c.end_year! - c.start_year! + 1) / span * 100}%` }}/><span>{c.start_year}–{c.end_year}{c.is_estimated ? ' · 기간 추정' : ''}</span></div></div>)}</div> : <p className="trajectory-empty">현재 조건에서 비교 가능한 경력 구간이 없습니다.</p>}
    <div className="trajectory-coverage" role="status">비교 가능한 경력 {coverage.eligibleIntervals}/{coverage.totalIntervals}개 · 일치 연구자 {peers.length.toLocaleString()}명{coverage.excludedInferredDepartmentIntervals > 0 && ` · 추정 학과 제외 ${coverage.excludedInferredDepartmentIntervals}개`}{coverage.missingDepartmentIntervals > 0 && ` · 국내 학과 미상 ${coverage.missingDepartmentIntervals}개`}{coverage.missingCountryIntervals > 0 && ` · 국가 미상 ${coverage.missingCountryIntervals}개`}</div>
    {peers.length ? <div className="trajectory-peers">{peers.slice(0, 30).map(peer => <article key={peer.id}><div className="trajectory-peer-heading"><button onClick={() => onSelect(peer.id)}>{labelFor(peer.id)} <span>이 연구자 기준으로 ↗</span></button><strong>{(peer.score * 100).toFixed(1)}% <small>경로 유사도</small></strong></div><p>일치 기관·연도 {peer.sharedUnitYears}개 / 두 경로의 합집합 {peer.unionUnitYears}개</p><ul>{peer.evidence.map((e, i) => <li key={i}><span>{e.startYear}–{e.endYear}</span><div><b>{e.institution}{e.department ? ` · ${e.department}` : ''}</b><small>선택 연구자 {stages[e.selectedStage]} · 비교 연구자 {stages[e.peerStage]}{e.estimated ? ' · 기간 추정' : ''}{e.inferredDepartment ? ' · 학과 추정' : ''}</small></div></li>)}</ul></article>)}</div> : <div className="trajectory-empty">현재 근거와 조건에서 겹치는 경로가 없습니다. 학과·국가 정보가 없는 구간은 비교에서 제외되므로, 결과 없음이 실제 접점 없음을 뜻하지 않습니다.</div>}
    <p className="trajectory-note">경로 유사도는 기관 단위–연도 집합의 교집합 ÷ 합집합(Jaccard)입니다. 중복 소속은 한 번만 셉니다. 실제 친분의 확률이나 이동 순서의 일치도는 아닙니다.{peers.length > 30 ? ' 유사도가 높은 30명을 표시합니다.' : ''}</p>
  </section>;
}
