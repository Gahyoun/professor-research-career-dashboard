import { useCallback, useId, useMemo, useState } from 'react';
import type { KeyboardEvent } from 'react';
import type { Professor } from './types';
import { buildInstitutionOptions, buildSankey, colorOfOrigin, institutionLabel, layoutSankey, ribbonPath, STAGES, STAGE_LABELS, SUBJECT_LABELS } from './sankey';
import type { FlowNode, FlowLink, FlowRoute, FlowStage } from './sankey';
import { institutionSearchText } from './schoolIdentity';
import ZoomableFlowViewport from './ZoomableFlowViewport';
import './sankey.css';

type Props = { professors: Professor[]; names: Record<string, string> | null; onSelect: (id: string) => void; releaseYear: number };
type Selection = { label: string; ids: string[] };
const count = (n: number) => n.toLocaleString('ko-KR');
const labelWidth = 244, labelLineHeight = 23;
function nodeTextLines(label: string) {
  const measure = (s: string) => [...s].reduce((sum, char) => sum + (/[^\u0000-\u024f]/.test(char) ? 18 : /[MW]/.test(char) ? 15 : char === ' ' ? 5 : 10), 0);
  const lines: string[] = [];
  let line = '';
  for (const word of label.split(/\s+/)) {
    if (line && measure(`${line} ${word}`) > labelWidth) { lines.push(line); line = ''; }
    if (measure(word) <= labelWidth) { line = line ? `${line} ${word}` : word; continue; }
    // An unusually long unspaced name still remains complete.
    for (const char of word) {
      if (line && measure(line + char) > labelWidth) { lines.push(line); line = ''; }
      line += char;
    }
  }
  if (line) lines.push(line);
  return lines;
}
const pageSize = 10;

export default function SankeyPage({ professors, names, onSelect, releaseYear }: Props) {
  const [subject, setSubject] = useState('');
  const [institutions, setInstitutions] = useState<Partial<Record<FlowStage, string>>>({});
  const [institutionQueries, setInstitutionQueries] = useState<Partial<Record<FlowStage, string>>>({});
  const [groupForeign, setGroupForeign] = useState(false);
  const [selfHireOnly, setSelfHireOnly] = useState(false);
  const [selection, setSelection] = useState<Selection | null>(null);
  const [hover, setHover] = useState<Selection | null>(null);
  const [page, setPage] = useState(0);
  const [peoplePage, setPeoplePage] = useState(0);
  const [searchState, setSearchState] = useState({ names, text: '' });
  const search = searchState.names === names ? searchState.text : '';
  // Searches from the unlocked state must never survive relocking.
  if (searchState.names !== names) setSearchState({ names, text: '' });
  function setSearch(text: string) { setSearchState({ names, text }); }
  const institutionOptions = useMemo(() => buildInstitutionOptions(professors), [professors]);
  const data = useMemo(() => buildSankey(professors, { subject, institutions, groupForeign, selfHireOnly }), [professors, subject, institutions, groupForeign, selfHireOnly]);
  const [previousData, setPreviousData] = useState(data);
  // A changed cohort or grouping invalidates all interactions, including stale prop updates.
  if (previousData !== data) { setPreviousData(data); setSelection(null); setHover(null); setPage(0); setPeoplePage(0); setSearchState({ names, text: '' }); }
  const clearGraphHover = useCallback(() => setHover(null), []);
  const labelLines = useMemo(() => new Map(data.nodes.map(node => [node.id, nodeTextLines(node.label)])), [data]);
  const layout = useMemo(() => layoutSankey(data, new Map([...labelLines].map(([id, lines]) => [id, (lines.length + 1) * labelLineHeight + 12]))), [data, labelLines]);
  const professorMap = useMemo(() => new Map(professors.map(p => [p.id, p])), [professors]);
  const nodes = useMemo(() => new Map(data.nodes.map(n => [n.id, n])), [data]);
  const visibleIds = useMemo(() => new Set(data.records.map(r => r.id)), [data]);
  const selectedIds = useMemo(() => new Set(selection?.ids.filter(id => visibleIds.has(id)) ?? []), [selection, visibleIds]);
  const focusIds = useMemo(() => hover ? new Set(hover.ids) : selectedIds, [hover, selectedIds]);
  const focused = focusIds.size > 0;
  const selectedPeople = useMemo(() => [...selectedIds].map(id => professorMap.get(id)!).filter(Boolean).filter(p => {
    const query = search.trim().toLowerCase();
    return !query || p.id.toLowerCase().includes(query) || (names?.[p.id] ?? '').toLowerCase().includes(query) || institutionSearchText(p.current_institution).toLowerCase().includes(query);
  }).sort((a, b) => a.id.localeCompare(b.id)), [selectedIds, professorMap, search, names]);
  const routes = useMemo(() => selectedIds.size ? data.routes.flatMap(r => {
    const ids = r.personIds.filter(id => selectedIds.has(id));
    return ids.length ? [{ ...r, count: ids.length, personIds: ids }] : [];
  }) : data.routes, [data, selectedIds]);
  const currentPage = Math.min(page, Math.max(0, Math.ceil(routes.length / pageSize) - 1));
  const currentPeoplePage = Math.min(peoplePage, Math.max(0, Math.ceil(selectedPeople.length / pageSize) - 1));
  const subjects = [...new Set(professors.map(p => p.subject))].sort((a, b) => (['mathematics', 'physics', 'chemistry', 'biology'].indexOf(a) - ['mathematics', 'physics', 'chemistry', 'biology'].indexOf(b)));
  function resetSelection() { setSelection(null); setHover(null); setPage(0); setPeoplePage(0); setSearch(''); }
  function resetFilters() { setSubject(''); setInstitutions({}); setInstitutionQueries({}); setSelfHireOnly(false); setGroupForeign(false); resetSelection(); }
  const hasFilters = Boolean(subject || selfHireOnly || groupForeign || Object.values(institutions).some(Boolean) || Object.values(institutionQueries).some(Boolean));
  function choose(value: Selection) { setSelection(value); setHover(null); setPeoplePage(0); setPage(0); setSearch(''); }
  function nodeSelection(n: FlowNode): Selection { return { label: `${STAGE_LABELS[n.stage]} · ${n.label}`, ids: n.personIds }; }
  function linkSelection(l: FlowLink): Selection {
    return { label: `${nodes.get(l.source)!.label} → ${nodes.get(l.target)!.label} · ${l.originLabel} 출신${l.selfHire ? ' · 학부 모교 재직' : ''}`, ids: l.personIds };
  }
  function chooseRoute(r: FlowRoute) { choose({ label: r.labels.join(' → '), ids: r.personIds }); }
  function keyChoose(event: KeyboardEvent<SVGElement>, value: Selection) {
    if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); choose(value); }
    if (event.key === 'Escape') resetSelection();
  }
  function downloadTable() {
    // Aggregate export intentionally contains no researcher IDs or names.
    const csvCell = (value: string | number) => {
      let safe = String(value);
      if (/^[\s]*[=+@-]/.test(safe)) safe = "'" + safe;
      return `"${safe.replace(/"/g, '""')}"`;
    };
    const csv = '\uFEFF' + [['학사기관', '박사기관', '현재 재직기관', '인원', '학부 모교 재직'], ...routes.map(r => [...r.labels, r.count, r.selfHire ? '예' : '아니오'])].map(row => row.map(csvCell).join(',')).join('\r\n');
    const url = URL.createObjectURL(new Blob([csv], { type: 'text/csv;charset=utf-8' }));
    const anchor = document.createElement('a'); anchor.href = url; anchor.download = `education-career-flows-${releaseYear}${subject ? `-${subject}` : ''}.csv`; anchor.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  return <section className="sankey-page" aria-labelledby="sankey-title">
    <header className="sk-intro">
      <div><p className="sk-eyebrow">학력과 재직의 흐름</p><h1 id="sankey-title">Education and employment flows</h1><p className="sk-lead">학사 → 박사 → 현재 재직기관. 흐름의 폭은 연구자 수를 나타냅니다.</p></div>
      <div className="sk-release"><span className="sk-release-dot" /><span>{releaseYear} 공개 데이터</span></div>
    </header>

    <section className="sk-controls" aria-labelledby="sk-filter-title">
      <div className="sk-filter-heading"><div><h2 id="sk-filter-title">기관으로 흐름 좁히기</h2><p>재직기관과 학부·박사 출신기관을 자유롭게 선택하세요. 여러 기관 조건을 선택하면 모두 충족하는 연구자를 표시합니다.</p></div><button className="sk-button" onClick={resetFilters} disabled={!hasFilters}>모든 필터 초기화</button></div>
      <div className="sk-institution-filters">{(['current', 'bachelor', 'phd'] as FlowStage[]).map(stage => <InstitutionSelector key={stage} title={stage === 'current' ? '현재 재직기관' : stage === 'bachelor' ? '학부 출신기관' : '박사 출신기관'} options={institutionOptions[stage]} value={institutions[stage] || ''} query={institutionQueries[stage] || ''} onQuery={query => setInstitutionQueries(previous => ({ ...previous, [stage]: query }))} onChange={value => { setInstitutions(previous => ({ ...previous, [stage]: value })); resetSelection(); }} />)}</div>
      <div className="sk-secondary-filters"><label className="sk-subject-filter"><span>연구 분야</span><select value={subject} onChange={e => { setSubject(e.target.value); resetSelection(); }}><option value="">전체 분야</option>{subjects.map(s => <option key={s} value={s}>{SUBJECT_LABELS[s] ?? s}</option>)}</select></label><div className="sk-checks"><label><input type="checkbox" checked={selfHireOnly} onChange={e => { setSelfHireOnly(e.target.checked); resetSelection(); }} />학부 모교 재직만 보기</label><label><input type="checkbox" checked={groupForeign} onChange={e => { setGroupForeign(e.target.checked); resetSelection(); }} />해외 교육기관을 권역별로 묶기</label></div></div>
      {groupForeign && <p className="sk-filter-note">해외 권역으로 묶어도 직접 선택한 학부·박사 기관은 개별 표시합니다. 구성원과 집계 인원은 바뀌지 않습니다.</p>}
    </section>

    <div className="sk-metrics" aria-live="polite">
      <div><span>현재 표시 연구자</span><strong>{count(data.count)}<small>명</small></strong><p>필터 대상 {count(data.filterCount)}명 중 세 기관 경로 완비</p></div>
      <div><span>학부 모교 재직</span><strong>{count(data.selfHireCount)}<small>명{data.count > 0 && ` · ${(100 * data.selfHireCount / data.count).toFixed(1)}%`}</small></strong><p>학사기관과 현재 재직기관이 같은 경우</p></div>
      <div><span>필터 대상의 경로 완비율</span><strong>{data.filterCount ? (100 * data.completeCount / data.filterCount).toFixed(1) : '—'}{data.filterCount > 0 && <small>%</small>}</strong><p>기관 정보가 하나 이상 빠진 {count(data.missingCount)}명 제외</p></div>
    </div>

    <p className="sk-cohort-note">선택 분야 전체 {count(data.subjectCount)}명 → 기관·모교 재직 조건에 맞는 {count(data.filterCount)}명 → 세 단계 경로가 있는 {count(data.count)}명. 흐름도와 경로 표에는 마지막 {count(data.count)}명이 포함됩니다.</p>

    <section className="sk-chart-card" aria-labelledby="sk-chart-title">
      <div className="sk-chart-heading"><div><h2 id="sk-chart-title">학사 → 박사 → 현재 재직</h2><p>흐름의 두께는 연구자 수에 비례합니다. 기관이나 연결을 선택하면 해당 연구자의 경로가 드러납니다.</p></div><div className="sk-chart-actions"><button className="sk-button sk-button-subtle" onClick={() => { const heading = document.getElementById('sk-routes-title'); heading?.focus({ preventScroll: true }); heading?.scrollIntoView({ block: 'start' }); }}>경로 표로 이동</button><button className="sk-button sk-button-subtle" onClick={resetSelection} disabled={!selection}>선택 초기화</button></div></div>
      <div className="sk-legend" aria-label="흐름 색상 설명"><p><strong>학부 출신기관별 색상</strong> · 흐름을 가리키거나 아래 경로를 선택하면 실제 학부 기관을 확인할 수 있습니다.</p><p className="sk-legend-self"><i aria-hidden="true"/><span>진한 흐름: 학부 모교 재직</span></p></div>
      {data.count === 0 ? <div className="sk-empty"><strong>선택한 조건에 맞는 완비 경로가 없습니다.</strong><p>기관·연구 분야 필터를 조정하거나 모든 필터를 초기화해 주세요.</p></div> : <>
        <ZoomableFlowViewport width={layout.width} height={layout.height + 72} resetToken={data} onGestureStart={clearGraphHover}>
          <div className="sk-column-labels">{STAGES.map((s, i) => <div key={s}><span>0{i + 1}</span><strong>{STAGE_LABELS[s]}</strong><small>{count(data.count)}명 · {count(data.nodes.filter(node => node.stage === s).length)}개 표시 단위</small></div>)}</div>
          <svg className="sk-svg" viewBox={`0 0 ${layout.width} ${layout.height}`} width={layout.width} height={layout.height} aria-labelledby="sk-svg-title sk-svg-description">
            <title id="sk-svg-title">{SUBJECT_LABELS[subject] ?? '전체 분야'} 연구자 {count(data.count)}명의 학력과 재직기관 흐름</title>
            <desc id="sk-svg-description">기관은 세 단계에 따로 표시됩니다. 모든 연결의 폭은 인원에 선형 비례합니다. 기관을 선택하려면 탭과 엔터를 사용하세요. 연결 경로는 아래 표에서도 선택할 수 있습니다.</desc>
            {[...new Set(layout.nodes.map(node => node.x + 6))].map(x => <line key={x} x1={x} x2={x} y1={14} y2={layout.height - 14} stroke="#eef1f4" strokeDasharray="2 5" />)}
            <g className="sk-ribbons">{layout.links.map(link => {
              const info = linkSelection(link);
              return <path key={link.id} d={link.path} fill={colorOfOrigin(link.origin)} fillOpacity={focused ? 0.055 : link.selfHire ? 0.6 : 0.23} role="button" tabIndex={-1} aria-label={`${info.label}, ${count(link.count)}명`} onClick={() => choose(info)} onKeyDown={event => keyChoose(event, info)} onMouseEnter={() => setHover(info)} onMouseLeave={() => setHover(null)}><title>{info.label} · {count(link.count)}명</title></path>;
            })}</g>
            {focused && <g className="sk-highlight-ribbons" pointerEvents="none">{layout.links.map(link => {
              const selected = link.personIds.filter(id => focusIds.has(id)).length;
              if (!selected) return null;
              const h = selected * layout.scale, offset = (link.height - h) / 2;
              return <path key={link.id} d={ribbonPath(link.sourceX, link.targetX, link.sourceY + offset, link.targetY + offset, h)} fill={colorOfOrigin(link.origin)} fillOpacity={0.72} />;
            })}</g>}
            <g>{layout.nodes.map(node => {
              const info = nodeSelection(node), selected = node.personIds.filter(id => focusIds.has(id)).length;
              const first = node.stage === 'bachelor';
              const x = first ? node.x - 12 : node.x + 24;
              const color = first ? colorOfOrigin(node.key) : node.stage === 'current' ? '#30475e' : '#6386b5';
              const lines = labelLines.get(node.id)!;
              const textHeight = (lines.length + 1) * labelLineHeight;
              const textTop = node.labelY - textHeight / 2;
              return <g key={node.id} className={`sk-node ${selected ? 'is-active' : ''}`} role="button" tabIndex={0} aria-label={`${info.label}, ${count(node.count)}명. 선택하여 경로 보기`} aria-pressed={selected > 0} onClick={() => choose(info)} onKeyDown={event => keyChoose(event, info)} onFocus={() => setHover(info)} onBlur={() => setHover(null)} onMouseEnter={() => setHover(info)} onMouseLeave={() => setHover(null)}>
                <title>{info.label} · {count(node.count)}명{selected ? ` · 강조 ${count(selected)}명` : ''}</title>
                <rect className="sk-node-target" x={node.x - 5} y={node.y - 5} width={22} height={Math.max(16, node.height + 10)} fill="transparent" />
                <rect x={node.x} y={node.y} width={12} height={node.height} rx={2} fill={color} opacity={focused && !selected ? 0.38 : 1} />
                <rect className="sk-label-bg" x={first ? x - labelWidth - 4 : x - 6} y={textTop - 6} width={labelWidth + 10} height={textHeight + 12} rx={3} fill="#fff" fillOpacity={0.96} />
                <text x={x} y={textTop + 18} textAnchor={first ? 'end' : 'start'} fill={focused && !selected ? '#6d7882' : '#1e2124'} fontWeight={selected ? 700 : 400}>{lines.map((line, index) => <tspan key={index} x={x} dy={index ? labelLineHeight : 0}>{line}</tspan>)}<tspan x={x} dy={labelLineHeight} className="sk-node-count">{count(node.count)}명</tspan></text>
              </g>;
            })}</g>
          </svg>
        </ZoomableFlowViewport>
        <div className="sk-chart-status" aria-live="polite">{hover ? <><strong>{hover.label}</strong><span>{count(hover.ids.length)}명 · 클릭하여 경로 고정</span></> : selection && selectedIds.size ? <><strong>{selection.label}</strong><span>{count(selectedIds.size)}명 선택됨</span></> : <><strong>어떤 경로가 궁금한가요?</strong><span>기관이나 흐름을 선택해 보세요.</span></>}</div>
      </>}
    </section>

    {selection && selectedIds.size > 0 && <section className="sk-people" aria-labelledby="sk-people-title">
      <div className="sk-section-heading"><div><p className="sk-eyebrow">선택한 경로</p><h2 id="sk-people-title">이 흐름을 만든 연구자 {count(selectedIds.size)}명</h2><p>{selection.label}</p></div><span className="sk-privacy-badge">{names ? '이름 공개 상태' : '익명 탐색 중'}</span></div>
      <div className="sk-people-tools"><label><span>연구자 찾기</span><input type="search" value={search} onChange={e => { setSearch(e.target.value); setPeoplePage(0); }} placeholder={names ? '이름, 익명 ID 또는 재직기관' : '익명 ID 또는 재직기관'} /></label><p>{names ? '연구자를 선택하면 개인 경력과 시공간적으로 유사한 연구자를 볼 수 있습니다.' : '비밀번호로 이름을 공개하기 전에는 익명 ID와 재직기관을 표시합니다.'}</p></div>
      <div className="sk-person-grid">{selectedPeople.slice(currentPeoplePage * pageSize, (currentPeoplePage + 1) * pageSize).map(p => <button key={p.id} className="sk-person" onClick={() => onSelect(p.id)}><span className="sk-person-avatar" aria-hidden="true">{names?.[p.id] ? names[p.id].slice(0, 1) : '·'}</span><span><strong>{names?.[p.id] ?? p.id}</strong><small>{SUBJECT_LABELS[p.subject] ?? p.subject} · {p.current_institution ? institutionLabel(p.current_institution) : '재직기관 미확인'}</small></span><span aria-hidden="true">↗</span></button>)}</div>
      {!selectedPeople.length && <p className="sk-empty-small">검색 결과가 없습니다.</p>}
      <Pagination page={currentPeoplePage} total={selectedPeople.length} onChange={setPeoplePage} label="연구자 목록" />
    </section>}

    <section className="sk-routes" aria-labelledby="sk-routes-title">
      <div className="sk-section-heading"><div><p className="sk-eyebrow">경로 자세히 보기</p><h2 id="sk-routes-title" tabIndex={-1}>기관별 학력 · 재직 경로</h2><p>묶음 표시를 펼친 실제 기관명입니다. {selectedIds.size ? '선택한 연구자에 해당하는 경로만 표시합니다.' : '각 행은 세 기관을 모두 거친 연구자를 나타냅니다.'}</p></div><button className="sk-button" onClick={downloadTable} disabled={!routes.length}>집계표 내려받기 <span aria-hidden="true">↓</span></button></div>
      <div className="sk-table-scroll"><table><caption className="sk-sr-only">학사기관, 박사기관, 현재 재직기관별 완전 경로의 인원</caption><thead><tr><th scope="col">학사기관</th><th scope="col">박사기관</th><th scope="col">현재 재직기관</th><th scope="col" className="sk-number">인원</th><th scope="col">경로 탐색</th></tr></thead><tbody>{routes.slice(currentPage * pageSize, (currentPage + 1) * pageSize).map(route => <tr key={route.id}>{route.labels.map((label, i) => <td key={i}>{i === 0 && <i className="sk-origin-dot" style={{ background: colorOfOrigin(route.origin) }} />}{label}{i === 2 && route.selfHire && <span className="sk-self-badge">학부 모교</span>}</td>)}<td className="sk-number">{count(route.count)}명</td><td><button className="sk-table-button" onClick={() => chooseRoute(route)} aria-label={`${route.labels.join(' → ')}, ${count(route.count)}명 경로 보기`}>경로 보기 <span aria-hidden="true">→</span></button></td></tr>)}</tbody></table></div>
      {!routes.length && <p className="sk-empty-small">표시할 경로가 없습니다.</p>}
      <Pagination page={currentPage} total={routes.length} onChange={setPage} label="경로 표" />
    </section>

    <details className="sk-method"><summary>데이터와 읽는 방법</summary><div>
      <p>한 연구자는 학사 → 박사, 박사 → 현재 재직의 두 연결에 각각 한 번씩 포함됩니다. 같은 화면에서는 모든 단계와 연결에 동일한 인원당 폭을 적용합니다. 분야나 필터를 바꾸면 화면에 맞추어 폭을 다시 계산하므로, 서로 다른 화면의 두께를 직접 비교하지 마세요.</p>
      <p>선택 분야 {count(data.subjectCount)}명 중 기관·모교 재직 조건에 맞는 대상은 {count(data.filterCount)}명입니다. 그중 학사·박사·재직기관이 모두 기재된 {count(data.completeCount)}명을 흐름도에 표시합니다. 하나 이상 누락된 {count(data.missingCount)}명은 제외합니다. 단계별 누락은 학사 {count(data.missingByStage.bachelor)}명, 박사 {count(data.missingByStage.phd)}명, 재직 {count(data.missingByStage.current)}명이며, 중복될 수 있습니다.</p>
      <p>선택한 대상의 모든 기관을 개별 표시합니다. 해외 권역 묶음은 선택 사항이며, 직접 선택한 학부·박사 기관은 묶음에서 분리해 표시합니다. 해외 권역은 데이터에 기록된 국가만으로 분류하며, 국가가 없으면 국내로 추정하지 않습니다. 현재 표시 중 학사 또는 박사 국가 미확인 {count(data.unknownCountryCount)}명, 숫자 코드만 있어 기관명이 미확인인 연구자 {count(data.unresolvedInstitutionCount)}명입니다.</p>
      <p>‘학부 모교 재직’은 정규화한 학사기관과 현재 재직기관의 일치를 뜻합니다. 학과 일치나 실제 임용 경위를 뜻하지 않습니다. 이 페이지는 학교 단위 학력 흐름 지표이며, 연구자별 경력 집단의 학과·분야·시기 조건과 구분합니다. 분교는 명시적으로 같은 본교 캠퍼스로 확인된 표기를 제외하고 합치지 않습니다.</p>
      <p>이 도표는 제공된 노트북의 학사–박사–재직 흐름, 학부 출신 색상, 모교 재직 강조를 웹으로 옮겼습니다. 인원은 그대로 보존하고, 선의 교차를 줄이는 반복 정렬을 사용합니다. 노트북의 HITS 순위나 임의 기관 점수 보정은 적용하지 않습니다.</p>
    </div></details>
  </section>;
}

function InstitutionSelector({ title, options, value, query, onQuery, onChange }: {
  title: string; options: readonly { key: string; label: string; count: number }[];
  value: string; query: string; onQuery: (query: string) => void; onChange: (value: string) => void;
}) {
  const id = useId();
  const normalizeSearch = (text: string) => text.normalize('NFKC').toLocaleLowerCase('ko-KR').trim();
  const terms = normalizeSearch(query).split(/\s+/).filter(Boolean);
  const matches = options.filter(option => {
    const text = normalizeSearch(institutionSearchText(option.label));
    return terms.every(term => text.includes(term));
  });
  const selected = options.find(option => option.key === value);
  // Searching the list must not silently change or hide an already chosen school.
  const choices = selected && !matches.some(option => option.key === value) ? [selected, ...matches] : matches;
  return <fieldset className="sk-institution-selector"><legend>{title}</legend>
    <label className="sk-sr-only" htmlFor={`${id}-search`}>{title} 선택 목록 검색</label>
    <input id={`${id}-search`} type="search" value={query} onChange={event => onQuery(event.target.value)} placeholder="기관명·한글명·약칭 검색" autoComplete="off" aria-describedby={`${id}-hint`} />
    <label className="sk-sr-only" htmlFor={`${id}-select`}>{title} 선택</label>
    <div className="sk-institution-choice"><select id={`${id}-select`} value={value} onChange={event => onChange(event.target.value)} aria-describedby={`${id}-hint ${id}-selected`}><option value="">전체 기관</option>{value && !selected && <option value={value}>현재 자료에서 찾을 수 없는 기관</option>}{choices.map(option => <option key={option.key} value={option.key}>{option.label}</option>)}</select><button className="sk-button" onClick={() => { onQuery(''); onChange(''); }} disabled={!value && !query} aria-label={`${title} 조건 해제`}>해제</button></div>
    <p id={`${id}-hint`} className="sk-institution-hint">{query ? `검색 ${count(matches.length)}개 / 전체 ${count(options.length)}개 기관 · 아래 목록에서 선택` : `전체 ${count(options.length)}개 기관에서 선택`}</p>
    <p id={`${id}-selected`} className="sk-filter-value">{value ? <><b>선택</b> {selected?.label ?? '현재 자료에서 찾을 수 없는 기관'}</> : '선택하지 않으면 전체 기관을 표시합니다.'}</p>
  </fieldset>;
}

function Pagination({ page, total, onChange, label }: { page: number; total: number; onChange: (page: number) => void; label: string }) {
  const pages = Math.max(1, Math.ceil(total / pageSize));
  return <nav className="sk-pagination" aria-label={`${label} 페이지`}><span>총 {count(total)}개{total ? ` · ${count(page * pageSize + 1)}–${count(Math.min((page + 1) * pageSize, total))}` : ''}</span><div><button className="sk-button" onClick={() => onChange(page - 1)} disabled={page === 0} aria-label={`${label} 이전 페이지`}>← 이전</button><span>{page + 1} / {pages}</span><button className="sk-button" onClick={() => onChange(page + 1)} disabled={page + 1 >= pages} aria-label={`${label} 다음 페이지`}>다음 →</button></div></nav>;
}
