import type { buildLifetimeTrajectory, LifetimeStage } from './constellation/lifetime';
import { careerSubjectLabels, lifetimePeriod, lifetimeStageColors, lifetimeStageLabels } from './lifetimePresentation';
import type { CSSProperties } from 'react';
import { institutionDisplayName } from './schoolIdentity';

const peerStageLabels: Record<string, string> = {
  doctoral: '박사과정 동료', postdoc: '포닥·연구원', faculty: '재직 교수',
  first_faculty: '첫 조교수', current: '현직',
};

export default function TrajectoryPanel({ lifetime, stageFilter, selectedGroupId, labelFor, institutionFor, subjectFor, onSelect, onSelectGroup }: {
  lifetime: ReturnType<typeof buildLifetimeTrajectory>; stageFilter: LifetimeStage | 'all'; selectedGroupId: string;
  labelFor: (id: string) => string; institutionFor: (id: string) => string; subjectFor: (id: string) => string;
  onSelect: (id: string) => void; onSelectGroup: (id: string) => void;
}) {
  const stages = lifetime.stages.filter(stage => stageFilter === 'all' || stage.stage === stageFilter);
  const allGroups = stages.flatMap(stage => stage.groups);
  const groups = allGroups.filter(group => !selectedGroupId || group.id === selectedGroupId);
  const selectedIntervals = new Map(stages.flatMap(stage => stage.intervals).map(interval => [interval.id, interval]));
  return <section className="trajectory-panel" aria-labelledby="trajectory-title">
    <div className="atlas-section-title"><div><span className="eyebrow">GROUP MEMBERSHIP EVIDENCE</span><h2 id="trajectory-title">집단 구성원과 겹친 기간</h2><p className="atlas-current-identity">{labelFor(lifetime.selectedId)} · {institutionDisplayName(institutionFor(lifetime.selectedId))}</p></div><span>{selectedGroupId ? `강조 집단 근거 · 전체 ${allGroups.length}개 중 ${groups.length}개` : `${groups.length}개 집단`}</span></div>
    <p>단계의 전체 기간 중 선택 연구자와 겹친 시점을 구성원별로 표시합니다. 집단 전체가 동시에 재학·재직했다는 의미는 아닙니다.</p>
    {groups.map(group => <article key={group.id} className={`lifetime-evidence-group ${selectedGroupId === group.id ? 'active' : ''}`} style={{ '--stage-color': lifetimeStageColors[group.stage] } as CSSProperties}>
      <div className="lifetime-evidence-heading"><div><span className="lifetime-phase-label"><i aria-hidden="true"/>{lifetimeStageLabels[group.stage]} · {lifetimePeriod(group.startYear, group.endYear)}</span><h3>{institutionDisplayName(group.institution)}{group.matchingBasis === 'institution_subject' ? ` · ${careerSubjectLabels[group.subject || ''] || group.subject} 계열` : group.department ? ` · ${group.department}` : ''}</h3></div><button onClick={() => onSelectGroup(group.id)} aria-pressed={selectedGroupId === group.id}>{selectedGroupId === group.id ? '집단 강조 해제' : '지도에서 이 집단 강조'}</button></div>
      <dl className="lifetime-group-facts"><div><dt>연결 조건</dt><dd>{group.condition}</dd></div><div><dt>선택 연구자의 기간</dt><dd>{lifetimePeriod(group.startYear, group.endYear)}{selectedIntervals.get(group.id)?.estimated ? ' · 추정' : ''}</dd></div><div><dt>{group.stage === 'current' ? '계열 기준' : '학과 근거'}</dt><dd>{group.matchingBasis === 'institution_subject' ? `명부의 ${careerSubjectLabels[group.subject || ''] || group.subject} 계열 · 세부 학과명과 학과 추정 여부 무관` : group.stage === 'postdoc' ? '기관 단위 비교 · 학과 조건 없음' : group.inferredDepartment ? '논문 소속에서 추정한 학과 포함' : '기록된 학과'}</dd></div><div><dt>구성원</dt><dd>{group.members.length}명 · 선택 연구자 포함</dd></div></dl>
      <div className="lifetime-member-table"><table><thead><tr><th>연구자 · 현재기관</th><th>겹친 역할과 기간</th><th>근거와 추정 여부</th></tr></thead><tbody>{group.members.map(id => {
        const evidence = group.memberEvidence.filter(item => item.peerId === id);
        const selected = id === lifetime.selectedId;
        return <tr key={id}><td><button className="lifetime-member-button" disabled={selected} onClick={() => onSelect(id)}><strong>{labelFor(id)}{selected && <em>선택 연구자</em>}</strong><span>{institutionDisplayName(institutionFor(id))}</span><small>{subjectFor(id)}{!selected && ' · 이 연구자 기준으로 ↗'}</small></button><div className="lifetime-shared-memberships" aria-label={`${labelFor(id)}의 현재 그래프 소속`}>{allGroups.filter(item => item.members.includes(id)).map(item => <button key={item.id} onClick={() => onSelectGroup(item.id)} aria-pressed={selectedGroupId === item.id} style={{ borderColor: lifetimeStageColors[item.stage], color: lifetimeStageColors[item.stage] }} title={`${institutionDisplayName(item.institution)} · ${lifetimePeriod(item.startYear, item.endYear)}`}>{lifetimeStageLabels[item.stage]} · {lifetimePeriod(item.startYear, item.endYear)}</button>)}</div></td><td>{selected ? <p>{lifetimeStageLabels[group.stage]}<br/><b>{lifetimePeriod(group.startYear, group.endYear)}</b></p> : evidence.map((item, i) => <p key={i}>{peerStageLabels[item.peerStage] || item.peerStage}<br/><b>{lifetimePeriod(item.startYear, item.endYear)}</b></p>)}</td><td>{selected ? <p>{selectedIntervals.get(group.id)?.basis.join(' · ') || '선택 경력 기록'}{selectedIntervals.get(group.id)?.inferredDepartment && ' · 학과 추정 포함'}</p> : evidence.map((item, i) => <p key={i}>{item.basis.join(' · ') || '경력 기록'}<span className="lifetime-evidence-flags">{item.estimated && <em>기간 추정</em>}{item.inferredDepartment && <em>학과 추정</em>}</span></p>)}</td></tr>;
      })}</tbody></table></div>
    </article>)}
    {stages.filter(stage => !stage.groups.length).map(stage => <div key={stage.id} className="lifetime-unavailable" style={{ '--stage-color': lifetimeStageColors[stage.stage] } as CSSProperties}><strong>{lifetimeStageLabels[stage.stage]} · 연결 가능한 집단 없음</strong><p>{stage.condition}</p>{stage.excludedReasons.map((reason, i) => <p key={i}>{reason}</p>)}</div>)}
    {!groups.length && !stages.some(stage => !stage.groups.length) && <p className="trajectory-empty">선택한 집단의 근거를 불러올 수 없습니다. 집단 선택을 해제해 다시 탐색하세요.</p>}
    <p className="trajectory-note">이 자료에 포함된 연구자 사이의 접점만 비교합니다. 일치 결과 없음은 실제 접점이 없었다는 뜻이 아닙니다. 과거 교수 재직과 첫 조교수 임용은 각각 해당 역할을 뒷받침하는 자료가 필요합니다.</p>
  </section>;
}
