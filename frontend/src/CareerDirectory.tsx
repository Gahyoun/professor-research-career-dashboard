import { useMemo, useRef, useState } from 'react';
import type { CareerSummary } from './constellation/careerCatalog';
import type { LifetimeStage } from './constellation/lifetime';
import type { Professor } from './types';
import { lifetimeStageColors, lifetimeStageLabels } from './lifetimePresentation';
import { institutionDisplayName, institutionSearchText } from './schoolIdentity';
import './career-directory.css';

type Props = {
  professors: Professor[];
  names: Record<string, string> | null;
  summaries: Record<string, CareerSummary> | null;
  progress: number;
  error?: string;
  selectedId: string;
  includeFirstFaculty?: boolean;
  onSelect: (id: string) => void;
};
type ConnectionFilter = 'all' | 'connected' | 'unconnected';
const defaultStages: LifetimeStage[] = ['doctoral', 'postdoc', 'current'];
const allStages: LifetimeStage[] = ['doctoral', 'postdoc', 'first_faculty', 'current'];
const subjectLabels: Record<string, string> = { mathematics: '수학', physics: '물리학', chemistry: '화학', biology: '생물학' };
const pageSize = 50;
const count = (value: number) => value.toLocaleString('ko-KR');
const searchable = (value: string) => value.normalize('NFKC').toLocaleLowerCase('ko-KR').trim();
// Presentation names never replace the source institution value used by this filter.
const institutionValue = (value: string | null) => JSON.stringify(value?.trim() || null);
const institutionLabel = (value: string | null) => value?.trim() ? institutionDisplayName(value) : '재직기관 미확인';

export default function CareerDirectory({ professors, names, summaries, progress, error, selectedId, includeFirstFaculty = false, onSelect }: Props) {
  const stages = includeFirstFaculty ? allStages : defaultStages;
  const stageDescription = stages.map(stage => lifetimeStageLabels[stage]).join('·');
  const [open, setOpen] = useState(true);
  const [queryState, setQueryState] = useState({ names, text: '' });
  const query = queryState.names === names ? queryState.text : '';
  // Keep selection and filters while discarding searches from the previous auth state.
  if (queryState.names !== names) setQueryState({ names, text: '' });
  function setQuery(text: string) { setQueryState({ names, text }); }
  const [subject, setSubject] = useState('');
  const [institution, setInstitution] = useState('');
  const [connection, setConnection] = useState<ConnectionFilter>('all');
  const [page, setPage] = useState(0);
  const tableScroll = useRef<HTMLDivElement>(null);
  const subjects = useMemo(() => [...new Set(professors.map(person => person.subject))].sort((a, b) => {
    const order = Object.keys(subjectLabels);
    return (order.indexOf(a) === -1 ? order.length : order.indexOf(a)) - (order.indexOf(b) === -1 ? order.length : order.indexOf(b)) || a.localeCompare(b);
  }), [professors]);
  const institutions = useMemo(() => [...new Map(professors.map(person => [institutionValue(person.current_institution), institutionLabel(person.current_institution)])).entries()].sort((a, b) => a[1].localeCompare(b[1], 'en')), [professors]);
  const completedCount = useMemo(() => professors.reduce((total, person) => total + (summaries?.[person.id] ? 1 : 0), 0), [professors, summaries]);
  const connectedCount = useMemo(() => professors.reduce((total, person) => total + ((summaries?.[person.id]?.groupCount ?? 0) > 0 ? 1 : 0), 0), [professors, summaries]);
  const incompleteCount = professors.length - completedCount;
  const rows = useMemo(() => {
    const terms = searchable(query).split(/\s+/).filter(Boolean);
    return professors.filter(person => {
      if (subject && person.subject !== subject) return false;
      if (institution && institutionValue(person.current_institution) !== institution) return false;
      const summary = summaries?.[person.id];
      if (connection !== 'all' && (!summary || (connection === 'connected' ? summary.groupCount === 0 : summary.groupCount > 0))) return false;
      const haystack = searchable(`${person.id} ${names?.[person.id] ?? ''} ${institutionSearchText(person.current_institution)}`);
      return terms.every(term => haystack.includes(term));
    }).sort((a, b) => a.id.localeCompare(b.id));
  }, [professors, names, summaries, query, subject, institution, connection]);
  const pageCount = Math.max(1, Math.ceil(rows.length / pageSize));
  const currentPage = Math.min(page, pageCount - 1);
  const pageRows = rows.slice(currentPage * pageSize, (currentPage + 1) * pageSize);
  const fraction = Number.isFinite(progress) ? Math.max(0, Math.min(1, progress)) : 0;
  const hasFilters = Boolean(query || subject || institution || connection !== 'all');
  function goToPage(nextPage: number) { setPage(nextPage); if (tableScroll.current) tableScroll.current.scrollTop = 0; }
  function resetFilters() { setQuery(''); setSubject(''); setInstitution(''); setConnection('all'); goToPage(0); }

  return <details className="career-directory" open={open} onToggle={event => setOpen(event.currentTarget.open)}>
    <summary className="cd-summary"><span><strong>전체 교수 경력 탐색</strong><span className="cd-total">전체 대상 {count(professors.length)}명</span></span><span className="cd-toggle" aria-hidden="true">{open ? '목록 접기' : '목록 펼치기'} <span>{open ? '−' : '+'}</span></span></summary>
    <div className="cd-body">
      <div className="cd-intro"><p>모든 교수의 {stageDescription} 경력 연결을 확인하고 개인 그래프를 여세요. 경력 근거가 부족하거나 연결 상대가 없는 교수도 목록에 포함합니다.</p><span className="cd-privacy">{names ? '이름 공개 상태' : '익명 탐색 중'}</span></div>
      <p className="cd-coverage">전체 {count(professors.length)}명 중 요약 완료 {count(completedCount)}명 · 하나 이상 연결된 교수 {count(connectedCount)}명{incompleteCount > 0 ? ' (계산 완료 기준)' : ''}</p>

      <div className="cd-filters" role="group" aria-label="교수 목록 필터">
        <label className="cd-search"><span>연구자 · 현직 기관 검색</span><input type="search" value={query} onChange={event => { setQuery(event.target.value); goToPage(0); }} placeholder={names ? '이름, 익명 ID 또는 기관명' : '익명 ID 또는 기관명'} /></label>
        <label><span>연구 분야</span><select value={subject} onChange={event => { setSubject(event.target.value); goToPage(0); }}><option value="">전체 분야</option>{subjects.map(value => <option key={value} value={value}>{subjectLabels[value] ?? value}</option>)}</select></label>
        <label className="cd-institution"><span>현재 재직기관</span><select value={institution} onChange={event => { setInstitution(event.target.value); goToPage(0); }}><option value="">전체 기관</option>{institutions.map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select>{institution && <small>{institutions.find(([value]) => value === institution)?.[1]}</small>}</label>
        <label><span>연결 상태</span><select value={connection} onChange={event => { setConnection(event.target.value as ConnectionFilter); goToPage(0); }}><option value="all">전체 교수</option><option value="connected">연결 있음</option><option value="unconnected">연결 없음</option></select></label>
        <button type="button" className="cd-button cd-reset" disabled={!hasFilters} onClick={resetFilters}>필터 초기화</button>
      </div>

      {incompleteCount > 0 && <div className={`cd-computation${error ? ' cd-computation-error' : ''}`} role="status">{error ? <p>경력 연결 계산을 완료하지 못했습니다. 교수 목록과 개별 그래프는 계속 탐색할 수 있습니다. 계산 미완료 {count(incompleteCount)}명.</p> : <><span>전체 경력 연결 계산 중 · {Math.round(fraction * 100)}%</span><progress value={fraction} max={1} aria-label="전체 교수 경력 연결 계산 진행률" /><span>계산 완료 {count(completedCount)} / {count(professors.length)}명</span></>}</div>}
      <div className="cd-results" aria-live="polite"><p><strong>필터 결과 {count(rows.length)}명</strong><span> / 전체 대상 {count(professors.length)}명</span></p><span>페이지당 50명</span></div>
      {connection !== 'all' && incompleteCount > 0 && <p className="cd-note">연결 상태 필터는 계산이 끝난 교수에게만 적용됩니다. 아직 계산되지 않은 {count(incompleteCount)}명은 ‘전체 교수’에서 볼 수 있습니다.</p>}
      <p className="cd-guide">전체 교수를 대상으로 현재 추정 설정을 적용하되, 각 연구자의 연결 상대는 명부의 분야가 같은 사람으로 제한합니다. 명부 분야는 과거 학과를 확인한 근거가 아닙니다. 박사·첫 조교수는 과거 학교·학과, 포닥은 기관의 일치와 겹친 기간도 필요합니다. 현직은 같은 학교·명부 분야를 묶으며 세부 학과명으로 나누지 않습니다. 단계별 표시는 연결된 집단 수입니다. ‘겹친 상대 없음’은 경력 구간은 있지만 조건이 겹친 상대를 찾지 못한 경우이며, ‘근거 부족’은 연결에 필요한 경력 근거가 없는 경우입니다.</p>
      <p className="cd-scroll-hint">좁은 화면에서는 표를 좌우로 이동할 수 있습니다.</p>

      <div ref={tableScroll} className="cd-table-scroll" tabIndex={0} role="region" aria-label={`전체 교수 ${stageDescription} 경력 목록. 좌우와 위아래 스크롤 가능`}>
        <table className="cd-table"><caption className="cd-sr-only">전체 대상 {count(professors.length)}명 중 필터 결과 {count(rows.length)}명. {stageDescription}의 연결 집단과 전체 동료 수</caption><colgroup><col className="cd-col-person" /><col className="cd-col-subject" />{stages.map(stage => <col key={stage} className="cd-col-stage" />)}<col className="cd-col-peers" /><col className="cd-col-action" /></colgroup>
          <thead><tr><th scope="col">연구자 · 현재 재직기관</th><th scope="col">분야</th>{stages.map(stage => <th key={stage} scope="col"><span className="cd-stage-title"><i style={{ backgroundColor: lifetimeStageColors[stage] }} aria-hidden="true" />{lifetimeStageLabels[stage]}</span></th>)}<th scope="col" className="cd-number">전체 동료</th><th scope="col">개인 그래프</th></tr></thead>
          <tbody>{pageRows.map(person => {
            const summary = summaries?.[person.id];
            const label = names?.[person.id] || person.id;
            const current = institutionLabel(person.current_institution);
            const selected = person.id === selectedId;
            return <tr key={person.id} className={selected ? 'cd-selected' : undefined} aria-selected={selected}>
              <th scope="row"><strong>{label}</strong><span className="cd-person-institution">{current}</span>{names?.[person.id] && <small className="cd-anon-id">{person.id}</small>}{selected && <span className="cd-selected-tag">선택한 연구자</span>}</th>
              <td>{subjectLabels[person.subject] ?? person.subject}</td>
              {stages.map(stage => {
                const result = summary?.stages[stage];
                return <td key={stage}>{result ? result.groupCount > 0 ? <span className="cd-stage-count" style={{ color: lifetimeStageColors[stage] }}>{count(result.groupCount)}개 집단</span> : <span className="cd-no-group">{result.intervalCount > 0 ? '겹친 상대 없음' : '근거 부족'}</span> : <span className="cd-pending">{error ? '계산 미완료' : '계산 중'}</span>}</td>;
              })}
              <td className="cd-number">{summary ? <><strong>{count(summary.peerCount)}</strong>명</> : <span className="cd-pending">{error ? '계산 미완료' : '계산 중'}</span>}</td>
              <td><button type="button" className="cd-button cd-open" onClick={() => onSelect(person.id)} aria-label={`${label}, ${current} 개인 경력 그래프 열기`}>그래프 열기 <span aria-hidden="true">↗</span></button></td>
            </tr>;
          })}</tbody>
        </table>
        {!pageRows.length && <p className="cd-empty">현재 조건에 맞는 교수가 없습니다.{incompleteCount > 0 && connection !== 'all' ? ' 연결 계산이 진행 중이거나 미완료인 교수는 전체 교수에서 확인하세요.' : ' 검색어나 필터를 조정해 주세요.'}</p>}
      </div>

      <nav className="cd-pagination" aria-label="전체 교수 목록 페이지"><span>{rows.length ? `${count(currentPage * pageSize + 1)}–${count(Math.min((currentPage + 1) * pageSize, rows.length))} / ${count(rows.length)}명` : '0명'}</span><div><button type="button" className="cd-button" disabled={currentPage === 0} onClick={() => goToPage(currentPage - 1)}>← 이전</button><label className="cd-page-select"><span className="cd-sr-only">이동할 페이지</span><select value={currentPage} onChange={event => goToPage(Number(event.target.value))}>{Array.from({ length: pageCount }, (_, index) => <option key={index} value={index}>{count(index + 1)}</option>)}</select><span> / {count(pageCount)}</span></label><button type="button" className="cd-button" disabled={currentPage + 1 >= pageCount} onClick={() => goToPage(currentPage + 1)}>다음 →</button></div></nav>
      <p className="cd-note">전체 동료는 표시된 {stageDescription} 단계에서 연결된 서로 다른 연구자 수이며, 단계별 인원을 더한 값이 아닙니다. 계산된 연결이 없다는 표시는 실제 인적 관계가 없다는 뜻이 아닙니다. {names ? '이름과 익명 ID로 검색할 수 있습니다.' : '비밀번호로 이름을 공개하기 전에는 익명 ID와 현직 기관으로 탐색합니다.'}</p>
    </div>
  </details>;
}
