import SankeyPage from './SankeyPage';
import TemporalInstitutionsPage from './TemporalInstitutionsPage';
import { loadDashboard } from './metadata';
import { decryptNameMap, type EncryptedNames } from './privacy';
import { useEffect, useMemo, useRef, useState } from 'react';

import type { Stage, Career, YearPoint, Professor, Dashboard } from './types';
import Constellation from './Constellation';

type Filters = { subject: string; institution: string };

type ViewMode = 'individual' | 'group' | 'constellation' | 'sankey' | 'institutions';
function routeView(): ViewMode { const path = window.location.hash.split('?')[0]; return path === '#/institutions' ? 'institutions' : path === '#/flows' ? 'sankey' : path === '#/career' ? 'individual' : 'constellation'; }

const emptyFilters: Filters = { subject: '', institution: '' };
const stageColors: Record<Stage, string> = { doctoral: '#d63d4a', postdoc: '#228738', faculty: '#256ef4' };
const subjectLabels: Record<string, string> = { mathematics: '수학', physics: '물리', chemistry: '화학', biology: '생물' };

function aggregateYearly(professors: Professor[]): YearPoint[] {
  const years = new Map<number, YearPoint>();
  for (const professor of professors) for (const row of professor.yearly) {
    const current = years.get(row.year) || {
      year: row.year, stage: null, total: 0, first_author: 0, corresponding_author: 0,
      impact_low: 0, impact_medium: 0, impact_high: 0, impact_unknown: 0,
      mean_journal_2yr_citedness: null, article_citations: 0,
    };
    current.total += row.total; current.first_author += row.first_author;
    current.corresponding_author += row.corresponding_author;
    current.impact_low += row.impact_low; current.impact_medium += row.impact_medium;
    current.impact_high += row.impact_high; current.impact_unknown += row.impact_unknown;
    current.article_citations += row.article_citations;
    years.set(row.year, current);
  }
  return [...years.values()].sort((a, b) => a.year - b.year);
}

function degreeColor(index: number, count: number) {
  const start = [253, 232, 235];
  const end = [214, 61, 74];
  const ratio = count <= 1 ? 1 : index / (count - 1);
  return `rgb(${start.map((value, channel) => Math.round(value + (end[channel] - value) * ratio)).join(',')})`;
}

function CareerTimeline({ rows }: { rows: Career[] }) {
  if (!rows.length) return <p className="empty">표시할 경력 구간이 없습니다.</p>;
  const min = Math.min(...rows.map(row => row.start_year || 2026));
  const max = Math.max(...rows.map(row => row.end_year || row.start_year || 2026), 2026);
  const span = Math.max(1, max - min + 1);
  const ticks = Array.from(new Set([min, min + Math.floor(span / 2), max])).sort((a, b) => a - b);
  return (
    <div className="timeline" role="img" aria-label="박사과정, 기관별 포닥, 교수 경력 타임라인">
      <div className="timeline-axis" aria-hidden="true">{ticks.map(tick => <span key={tick}>{tick}</span>)}</div>
      {rows.map((row, index) => {
        const start = row.start_year || min, end = row.end_year || start;
        const left = ((start - min) / span) * 100, width = ((end - start + 1) / span) * 100;
        const degreeStage = row.stage === 'doctoral';
        const degreeYears = degreeStage ? Array.from({ length: Math.max(1, end - start + 1) }, (_, yearIndex) => start + yearIndex) : [];
        return (
          <div className="career-row" key={`${row.stage}-${row.institution}-${index}`}>
            <div className="career-label"><span className={`stage-dot ${row.stage}`} /><span><b>{row.institution}</b><small>{row.evidence_basis}</small></span>{row.is_estimated && <em>추정</em>}{row.is_institution_successor && <em>기관 승계</em>}</div>
            <div className="career-track">
              <div className={`career-bar ${degreeStage ? 'degree-gradient' : ''}`} style={{ left: `${left}%`, width: `${width}%`, background: degreeStage ? undefined : stageColors[row.stage] }}>
                {degreeStage && degreeYears.map((degreeYear, yearIndex) => <i key={degreeYear} style={{ background: degreeColor(yearIndex, degreeYears.length) }} title={`${degreeYear}년 · 추정`} />)}
                <span>{start}–{end}</span>
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
}

function ProductivityChart({ data, group }: { data: YearPoint[]; group: boolean }) {
  if (!data.length || data.every(row => row.total === 0)) return <p className="empty">선택 조건의 주저자 논문이 없습니다.</p>;
  const width = Math.max(860, data.length * 44), height = 290, pad = 42;
  const max = Math.max(...data.map(d => d.total), 1);
  const gridMax = Math.max(4, Math.ceil(max / 4) * 4);
  const barWidth = Math.min(28, (width - pad * 2) / data.length * .68);
  return (
    <>
      <div className="chart-scroll">
        <svg className="chart" viewBox={`0 0 ${width} ${height}`} style={{ minWidth: `${Math.min(width, 1400)}px` }} role="img" aria-labelledby="chart-title chart-desc">
          <title id="chart-title">연도별 주저자 논문 생산량</title>
          <desc id="chart-desc">저널 2년 평균 인용도 구간별 누적 막대그래프. {group ? '현재 필터 그룹 합계' : '선택 교수 값'}.</desc>
          {[0, .25, .5, .75, 1].map(ratio => {
            const tick = Math.round(gridMax * ratio), y = height - pad - ratio * (height - pad * 2);
            return <g key={ratio}><line x1={pad} y1={y} x2={width - pad} y2={y} className="grid-line"/><text x={pad - 10} y={y + 4} textAnchor="end">{tick}</text></g>;
          })}
          {data.map((d, i) => {
            const x = pad + (i + .5) * ((width - pad * 2) / data.length) - barWidth / 2;
            let y = height - pad;
            const pieces = [
              { value: d.impact_unknown, color: '#cdd1d5' }, { value: d.impact_low, color: '#b8cdfc' },
              { value: d.impact_medium, color: '#6192f8' }, { value: d.impact_high, color: '#0b50d0' },
            ];
            return <g key={d.year}>{pieces.map((piece, n) => {
              const h = (piece.value / gridMax) * (height - pad * 2); y -= h;
              return <rect key={n} x={x} y={y} width={barWidth} height={Math.max(0, h)} fill={piece.color} rx="2"><title>{d.year}: {d.total}편</title></rect>;
            })}<text x={x + barWidth / 2} y={height - 13} textAnchor="middle">{d.year}</text></g>;
          })}
        </svg>
      </div>
      <details className="data-table"><summary>연도별 수치 표로 보기</summary><div><table><thead><tr><th>연도</th><th>합계</th><th>낮음</th><th>중간</th><th>높음</th><th>미분류</th></tr></thead><tbody>{data.map(row => <tr key={row.year}><td>{row.year}</td><td>{row.total}</td><td>{row.impact_low}</td><td>{row.impact_medium}</td><td>{row.impact_high}</td><td>{row.impact_unknown}</td></tr>)}</tbody></table></div></details>
    </>
  );
}

function ProfessorRows({ rows, labelFor, onSelect, minimumImpact }: { rows: Professor[]; labelFor: (p: Professor) => string; onSelect: (id: string) => void; minimumImpact: number }) {
  const visible = [...rows].sort((a, b) => b.lead_work_count - a.lead_work_count).slice(0, 24);
  const allYears = visible.flatMap(p => p.yearly.map(y => y.year));
  const minYear = allYears.length ? Math.min(...allYears) : 1990;
  const maxYear = allYears.length ? Math.max(...allYears) : 2026;
  const span = Math.max(1, maxYear - minYear);
  const maxOutput = Math.max(...visible.flatMap(p => p.yearly.map(y => y.total)), 1);
  const ticks = Array.from({ length: Math.floor((maxYear - Math.ceil(minYear / 5) * 5) / 5) + 1 }, (_, index) => Math.ceil(minYear / 5) * 5 + index * 5);
  function pathFor(points: YearPoint[], close = false) {
    if (!points.length) return '';
    const coordinates = points.map(point => `${((point.year - minYear) / span) * 720},${38 - (point.total / maxOutput) * 34}`);
    return `${close ? `M${coordinates[0].split(',')[0]},38 L` : 'M'}${coordinates.join(' L')}${close ? ` L${coordinates.at(-1)?.split(',')[0]},38 Z` : ''}`;
  }
  return <div className="professor-rows">
    <div className="professor-axis" aria-hidden="true"><span>교수 · 학부 → 박사 → 현재기관</span><i>{ticks.map(tick => <b key={tick} style={{ left: `${((tick - minYear) / span) * 100}%` }}>{tick}</b>)}</i><em>논문</em></div>
    {visible.map(p => { const qualifyingJournals = p.journals.filter(journal => journal.openalex_2yr_mean_citedness !== null && journal.openalex_2yr_mean_citedness >= minimumImpact); const qualifyingPapers = qualifyingJournals.reduce((sum, journal) => sum + journal.lead_work_count, 0); return <button key={p.id} onClick={() => onSelect(p.id)} className="professor-row"><span><strong>{labelFor(p)}</strong><small className="current-affiliation">{p.current_institution || '현재기관 미상'}</small><small>{[p.bachelor_institution, p.phd_institution].filter(Boolean).join(' → ') || '출신기관 미상'}</small></span><svg className="spark-track" viewBox="0 0 720 40" preserveAspectRatio="none" role="img" aria-label={`${labelFor(p)} 연도별 주저자 생산성`}>{(['doctoral', 'postdoc', 'faculty'] as Stage[]).map(stage => { const points = p.yearly.filter(point => point.stage === stage); return <g key={stage}><path d={pathFor(points, true)} fill={stageColors[stage]} opacity=".22"/><path d={pathFor(points)} fill="none" stroke={stageColors[stage]} strokeWidth="2" vectorEffect="non-scaling-stroke"/></g>; })}</svg><em><b>{qualifyingPapers}편</b><small>{qualifyingJournals.length}개 저널</small></em></button> })}
  </div>;
}

export default function App() {
  const [dashboard, setDashboard] = useState<Dashboard | null>(null);
  const [filters, setFilters] = useState<Filters>(emptyFilters);
  const [selectedId, setSelectedId] = useState('');
  const [viewMode, setViewState] = useState<ViewMode>(routeView);
  const [graphSelectionId, setGraphSelectionId] = useState('');
  function setViewMode(mode: ViewMode) { setViewState(mode); const hash = mode === 'institutions' ? '#/institutions' : mode === 'sankey' ? '#/flows' : mode === 'constellation' ? '#/constellations' : '#/career'; if (window.location.hash !== hash) window.location.hash = hash; }
  useEffect(() => { const changed = () => setViewState(routeView()); window.addEventListener('hashchange', changed); return () => window.removeEventListener('hashchange', changed); }, []);
  const [groupPhd, setGroupPhd] = useState('');
  const [groupCountry, setGroupCountry] = useState('');
  const [minimumImpact, setMinimumImpact] = useState(0);
  const [minimumPapers, setMinimumPapers] = useState(0);
  const [minimumJournals, setMinimumJournals] = useState(0);
  const [password, setPassword] = useState('');
  const [unlocking, setUnlocking] = useState(false);
  const authGeneration = useRef(0);
  useEffect(() => () => { authGeneration.current += 1; }, []);
  const [names, setNames] = useState<Record<string, string> | null>(null);
  const [message, setMessage] = useState('실명은 암호화되어 있습니다.');
  const [zoom, setZoom] = useState(100);
  const [contrast, setContrast] = useState(false);
  const [loadError, setLoadError] = useState('');

  useEffect(() => {
    let active = true;
    loadDashboard(import.meta.env.BASE_URL).then(({ dashboard: data, metadataAvailable }) => {
      if (!active) return;
      setDashboard(data); setSelectedId(data.professors[0]?.id || '');
      if (!metadataAvailable) setMessage('실명은 암호화되어 있습니다. 학과·국가 보충자료를 불러오지 못해 해당 근거가 없는 공간 연결은 제외됩니다.');
    }).catch(() => { if (active) setLoadError('공개 데이터 파일을 불러오지 못했습니다.'); });
    return () => { active = false; };
  }, []);

  const filtered = useMemo(() => dashboard?.professors.filter(p =>
    (!filters.subject || p.subject === filters.subject) &&
    (!filters.institution || p.current_institution === filters.institution)
  ) || [], [dashboard, filters]);
  const availableInstitutions = useMemo(() => [...new Set((dashboard?.professors || [])
    .filter(p => !filters.subject || p.subject === filters.subject)
    .map(p => p.current_institution).filter((value): value is string => Boolean(value)))].sort(), [dashboard, filters.subject]);
  const selected = filtered.find(p => p.id === selectedId) || filtered[0] || null;
  const labelFor = (p: Professor) => names?.[p.id] || p.id;
  const availablePhdInstitutions = useMemo(() => [...new Set(filtered.map(p => p.phd_institution).filter((value): value is string => Boolean(value)))].sort(), [filtered]);
  const availablePhdCountries = useMemo(() => [...new Set(filtered.map(p => p.phd_country).filter((value): value is string => Boolean(value)))].sort(), [filtered]);
  const groupFiltered = useMemo(() => filtered.filter(p =>
    (!groupPhd || p.phd_institution === groupPhd) && (!groupCountry || p.phd_country === groupCountry) && (() => {
      if (minimumImpact <= 0 && minimumPapers <= 0 && minimumJournals <= 0) return true;
      const journals = p.journals.filter(journal => journal.openalex_2yr_mean_citedness !== null && journal.openalex_2yr_mean_citedness >= minimumImpact);
      const papers = journals.reduce((sum, journal) => sum + journal.lead_work_count, 0);
      return papers >= minimumPapers && journals.length >= minimumJournals;
    })()
  ), [filtered, groupPhd, groupCountry, minimumImpact, minimumPapers, minimumJournals]);
  const chartData = viewMode === 'group' ? aggregateYearly(groupFiltered) : selected?.yearly || [];

  async function unlock(event: React.FormEvent) {
    event.preventDefault();
    const generation = ++authGeneration.current;
    const submittedPassword = password;
    setPassword(''); setUnlocking(true);
    try {
      const response = await fetch(`${import.meta.env.BASE_URL}data/encrypted_names.json`);
      if (!response.ok) throw new Error('Name bundle unavailable');
      const payload = await response.json() as EncryptedNames;
      const decrypted = await decryptNameMap(submittedPassword, payload);
      if (generation !== authGeneration.current) return;
      setNames(decrypted); setMessage('실명과 그룹 쿼리가 이 기기의 메모리에서만 활성화되었습니다.');
    } catch { if (generation === authGeneration.current) setMessage('비밀번호가 맞지 않거나 실명 파일을 불러오지 못했습니다.'); }
    finally { if (generation === authGeneration.current) setUnlocking(false); }
  }

  function chooseProfessor(id: string) { setFilters(emptyFilters); setSelectedId(id); setViewMode('individual'); window.scrollTo({ top: 0 }); }
  function updateFilter(key: keyof Filters, value: string) {
    setFilters(current => key === 'subject' ? { subject: value, institution: '' } : ({ ...current, [key]: value }));
    setSelectedId('');
    if (key === 'subject') { setGroupPhd(''); setGroupCountry(''); }
  }

  if (loadError) return <main className="load-state"><h1>데이터를 열 수 없습니다</h1><p>{loadError}</p></main>;
  if (!dashboard) return <main className="load-state" aria-live="polite"><h1>연구경력 데이터를 준비하고 있습니다.</h1></main>;

  const postdocs = selected?.career.filter(row => row.stage === 'postdoc').length || 0;
  const doctoral = selected?.career.find(row => row.stage === 'doctoral');
  const totalLead = groupFiltered.reduce((sum, p) => sum + p.lead_work_count, 0);
  return (
    <div className={`app ${contrast ? 'high-contrast' : ''}`} style={{ fontSize: `${zoom}%` }}>
      <a className="skip-link" href="#main" onClick={e => { e.preventDefault(); const main = document.getElementById('main'); main?.focus(); main?.scrollIntoView(); }}>본문 바로가기</a>
      <header className="site-header"><div className="header-inner">
        <div className="brand"><span className="brand-mark" aria-hidden="true">N</span><div><strong>기초자연과학 연구경력</strong><span>교수 주저자 논문 대시보드</span></div></div>
        <form className="unlock" onSubmit={unlock}>{names ? <button type="button" className="lock" onClick={() => { authGeneration.current += 1; setNames(null); setPassword(''); setUnlocking(false); if (viewMode === 'group') setViewMode('individual'); setMessage('실명과 그룹 쿼리를 다시 잠갔습니다.'); }}>실명·쿼리 잠그기</button> : <><label htmlFor="name-password">실명·쿼리 보기</label><input id="name-password" type="password" value={password} onChange={e => setPassword(e.target.value)} placeholder="비밀번호" autoComplete="current-password" required/><button type="submit" disabled={unlocking}>{unlocking ? '확인 중' : '해제'}</button></>}</form>
      </div></header>

      <main id="main" tabIndex={-1} className={`container ${viewMode === 'constellation' || viewMode === 'sankey' || viewMode === 'institutions' ? 'atlas-container' : ''}`}>
        <nav className="atlas-nav" aria-label="탐색 화면">
          <button className={viewMode === 'constellation' ? 'active' : ''} onClick={() => setViewMode('constellation')}>경력 하이퍼그래프</button>
          <button className={viewMode === 'individual' || viewMode === 'group' ? 'active' : ''} onClick={() => setViewMode('individual')}>경력과 논문</button>
          <button className={viewMode === 'sankey' ? 'active' : ''} onClick={() => setViewMode('sankey')}>학력·임용 흐름</button>
          <button className={viewMode === 'institutions' ? 'active' : ''} onClick={() => setViewMode('institutions')}>기관 시계열</button>
          <span className="atlas-access" role="status" title={message}>{names ? '실명 보기 활성화' : '익명으로 탐색 중'}</span>
        </nav>
        <p className="atlas-auth-message" role="status">{message}</p>
        {viewMode === 'constellation' ? <Constellation key={names ? 'unlocked' : 'locked'} initialSelectedId={graphSelectionId} professors={dashboard.professors} names={names} releaseYear={dashboard.meta.release_year} onSelect={chooseProfessor}/> : viewMode === 'institutions' ? <TemporalInstitutionsPage professors={dashboard.professors} releaseYear={dashboard.meta.release_year}/> : viewMode === 'sankey' ? <SankeyPage key={names ? 'unlocked' : 'locked'} professors={dashboard.professors} names={names} releaseYear={dashboard.meta.release_year} onSelect={chooseProfessor}/> : <>

        <section className="title-row"><div><span className="eyebrow">{dashboard.meta.release_year} DATA RELEASE</span><h1>교수 연구경력과 주저자 생산성</h1><p>박사과정부터 기관별 포닥·교수 임용까지의 경력과 필터링된 1저자·교신저자 논문을 확인합니다.</p></div><div className="display-settings"><label htmlFor="zoom">글자 크기</label><select id="zoom" value={zoom} onChange={e => setZoom(Number(e.target.value))}><option value="90">90%</option><option value="100">100%</option><option value="110">110%</option><option value="130">130%</option><option value="150">150%</option></select><label className="contrast"><input type="checkbox" checked={contrast} onChange={e => setContrast(e.target.checked)}/> 선명한 화면</label></div></section>

        <section className="filter-panel" aria-labelledby="filter-title"><div className="panel-heading"><div><span className="step">01</span><h2 id="filter-title">조회 조건</h2></div><button className="reset" type="button" onClick={() => { setFilters(emptyFilters); setSelectedId(''); setGroupPhd(''); setGroupCountry(''); setMinimumImpact(0); setMinimumPapers(0); setMinimumJournals(0); }}>초기화</button></div>
          <div className="filter-grid">
            <label>분야<select value={filters.subject} onChange={e => updateFilter('subject', e.target.value)}><option value="">전체 분야</option>{dashboard.filters.subjects.map(v => <option key={v} value={v}>{subjectLabels[v] || v}</option>)}</select></label>
            <label>현재 재직기관<select value={filters.institution} onChange={e => updateFilter('institution', e.target.value)}><option value="">전체 기관</option>{availableInstitutions.map(v => <option key={v}>{v}</option>)}</select></label>
            <label>교수 (Prof ID)<select value={selected?.id || ''} onChange={e => { setSelectedId(e.target.value); setViewMode('individual'); }}><option value="">교수 선택</option>{filtered.map(p => <option key={p.id} value={p.id}>{labelFor(p)}</option>)}</select></label>
          </div><p className="status-message" role="status">필터 결과 {filtered.length.toLocaleString()}명</p>
        </section>

        <div className="view-toggle" role="group" aria-label="보기 방식"><button className={viewMode === 'individual' ? 'active' : ''} onClick={() => setViewMode('individual')}>선택 교수</button><button className={viewMode === 'group' ? 'active' : ''} onClick={() => setViewMode('group')} disabled={!names} title={names ? '그룹 조건 쿼리' : '실명·쿼리 잠금을 먼저 해제하세요'}>그룹 쿼리 {!names && '🔒'}</button></div>
        {viewMode === 'group' && <section className="group-filter" aria-labelledby="group-filter-title"><div className="group-filter-copy"><h2 id="group-filter-title">그룹 쿼리 조건</h2><p>출신 배경과 공개 저널 영향도·논문 수를 조합합니다. 결과 {groupFiltered.length.toLocaleString()}명</p></div><label>박사 출신기관<select value={groupPhd} onChange={e => setGroupPhd(e.target.value)}><option value="">전체 출신기관</option>{availablePhdInstitutions.map(value => <option key={value}>{value}</option>)}</select></label><label>박사학위 국가<select value={groupCountry} onChange={e => setGroupCountry(e.target.value)}><option value="">전체 국가</option>{availablePhdCountries.map(value => <option key={value}>{value}</option>)}</select></label><label>저널 영향도 M 이상<input type="number" min="0" step="0.1" value={minimumImpact} onChange={e => setMinimumImpact(Math.max(0, Number(e.target.value)))}/></label><label>주저자 논문 N편 이상<input type="number" min="0" step="1" value={minimumPapers} onChange={e => setMinimumPapers(Math.max(0, Number(e.target.value)))}/></label><label>서로 다른 저널 K개 이상<input type="number" min="0" step="1" value={minimumJournals} onChange={e => setMinimumJournals(Math.max(0, Number(e.target.value)))}/></label></section>}
        <section className="summary-grid" aria-label="조회 결과 요약">
          {viewMode === 'individual' && selected ? <>
            <article className="summary-card"><span>선택 교수</span><strong>{labelFor(selected)}</strong><small>{subjectLabels[selected.subject] || selected.subject} · {selected.department || '학과 미상'}</small></article>
            <article className="summary-card bachelor-card"><span>학부 출신기관</span><strong>{selected.bachelor_institution || '정보 없음'}</strong><small>실제 재학연도 미상 · 하이퍼그래프에서 추정 구간 선택 가능</small></article>
            <article className="summary-card doctoral-card"><span>박사과정 · 학위연도 기준</span><strong>{doctoral ? `${doctoral.start_year}–${doctoral.end_year}` : '연도 미상'}</strong><small>{selected.phd_institution || '기관 미상'}</small></article>
            <article className="summary-card"><span>포닥·연구원 기관</span><strong>{postdocs}개 구간</strong><small>동일기관은 학위 이후 논문 증거가 있을 때만 분리</small></article>
            <article className="summary-card"><span>주저자 논문</span><strong>{selected.lead_work_count.toLocaleString()}편</strong><small>1저자 또는 교신저자 · 후보 제외</small></article>
          </> : <>
            <article className="summary-card"><span>그룹 인원</span><strong>{groupFiltered.length.toLocaleString()}명</strong><small>익명 교수 ID 기준</small></article>
            <article className="summary-card"><span>현재기관</span><strong>{new Set(groupFiltered.map(p => p.current_institution).filter(Boolean)).size}개</strong><small>본·분교를 구분한 기관 풀네임</small></article>
            <article className="summary-card"><span>박사 출신기관</span><strong>{new Set(groupFiltered.map(p => p.phd_institution).filter(Boolean)).size}개</strong><small>{groupPhd || '전체 출신기관'}</small></article>
            <article className="summary-card"><span>박사학위 국가</span><strong>{new Set(groupFiltered.map(p => p.phd_country).filter(Boolean)).size}개</strong><small>{groupCountry || '전체 국가'}</small></article>
            <article className="summary-card"><span>주저자 논문</span><strong>{totalLead.toLocaleString()}편</strong><small>현재 필터 그룹 합계</small></article>
          </>}
        </section>

        {viewMode === 'individual' && selected && <section className="content-panel"><div className="panel-heading"><div><span className="step">02</span><h2 id="career-title">경력 타임라인</h2></div><div className="legend"><span><i className="doctoral"/>박사과정</span><span><i className="postdoc"/>포닥·연구원</span><span><i className="faculty"/>교수</span></div></div><CareerTimeline rows={selected.career}/><button className="trajectory-open" onClick={() => { setGraphSelectionId(selected.id); setViewMode('constellation'); window.scrollTo({ top: 0 }); }}>이 연구자의 시공간 경로 비교 ↗</button></section>}

        <section className="content-panel"><div className="panel-heading"><div><span className="step">{viewMode === 'individual' ? '03' : '02'}</span><h2>연도별 주저자 논문 생산성</h2></div><span className="metric-note">저널 영향도: OpenAlex 2-year mean citedness</span></div><div className="impact-legend"><span><i className="unknown"/>미분류</span><span><i className="low"/>낮음 (&lt;2)</span><span><i className="medium"/>중간 (2–5)</span><span><i className="high"/>높음 (≥5)</span></div><ProductivityChart data={chartData} group={viewMode === 'group'}/><p className="data-note">※ Clarivate JIF가 아닌 공개 재현 가능한 OpenAlex 저널 2년 평균 인용도입니다.</p></section>

        {viewMode === 'group' && <section className="content-panel"><div className="panel-heading"><div><span className="step">03</span><h2>조건 일치 교수 목록과 생산성</h2></div><span className="metric-note">상위 24명 · 그룹 실제 최소–최대 연도 공통축</span></div><ProfessorRows rows={groupFiltered} labelFor={labelFor} onSelect={chooseProfessor} minimumImpact={minimumImpact}/></section>}

        <section className="download-panel"><div><h2>공개 DB와 SQL</h2><p>실명과 원본 식별자를 제거한 SQLite 및 재사용 가능한 조회문입니다.</p></div><div><a href={`${import.meta.env.BASE_URL}downloads/professor_dashboard_${dashboard.meta.release_year}.sqlite`} download>익명 SQLite</a><a href={`${import.meta.env.BASE_URL}downloads/schema_public.sql`} download>스키마 SQL</a><a href={`${import.meta.env.BASE_URL}downloads/queries_public.sql`} download>예제 쿼리</a></div></section>
        </>}
      </main>
      <footer><div className="container">{dashboard.meta.release_year} 공개 릴리스 · 공개 화면에는 익명화·집계된 정보만 포함됩니다.</div></footer>
    </div>
  );
}
