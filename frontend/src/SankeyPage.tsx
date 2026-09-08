import { useMemo, useState } from 'react';
import type { KeyboardEvent } from 'react';
import type { Professor } from './types';
import { buildSankey, institutionLabel, layoutSankey, ORIGIN_COLORS, ORIGIN_LABELS, ribbonPath, STAGES, STAGE_LABELS, SUBJECT_LABELS } from './sankey';
import type { FlowNode, FlowLink, FlowRoute, Origin } from './sankey';
import { institutionSearchText } from './schoolIdentity';
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
  const [topN, setTopN] = useState(10);
  const [groupForeign, setGroupForeign] = useState(true);
  const [origin, setOrigin] = useState<Origin | 'all'>('all');
  const [selfHireOnly, setSelfHireOnly] = useState(false);
  const [selection, setSelection] = useState<Selection | null>(null);
  const [hover, setHover] = useState<Selection | null>(null);
  const [page, setPage] = useState(0);
  const [peoplePage, setPeoplePage] = useState(0);
  const [search, setSearch] = useState('');
  const data = useMemo(() => buildSankey(professors, { subject, topN, groupForeign, origin, selfHireOnly }), [professors, subject, topN, groupForeign, origin, selfHireOnly]);
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
  function choose(value: Selection) { setSelection(value); setHover(null); setPeoplePage(0); setPage(0); setSearch(''); }
  function nodeSelection(n: FlowNode): Selection { return { label: `${STAGE_LABELS[n.stage]} · ${n.label}`, ids: n.personIds }; }
  function linkSelection(l: FlowLink): Selection {
    return { label: `${nodes.get(l.source)!.label} → ${nodes.get(l.target)!.label} · ${ORIGIN_LABELS[l.origin]} 출신${l.selfHire ? ' · 학부 모교 재직' : ''}`, ids: l.personIds };
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

    <div className="sk-controls" aria-label="학력 흐름 필터">
      <label><span>연구 분야</span><select value={subject} onChange={e => { setSubject(e.target.value); resetSelection(); }}><option value="">전체 분야</option>{subjects.map(s => <option key={s} value={s}>{SUBJECT_LABELS[s] ?? s}</option>)}</select></label>
      <label><span>개별 표시 기관</span><select value={topN} onChange={e => { setTopN(Number(e.target.value)); setHover(null); }}><option value={6}>단계별 주요 6개</option><option value={10}>단계별 주요 10개</option><option value={14}>단계별 주요 14개</option></select></label>
      <label className="sk-origin-filter"><span>학부 출신</span><select value={origin} onChange={e => { setOrigin(e.target.value as Origin | 'all'); resetSelection(); }}><option value="all">전체 출신</option>{Object.entries(ORIGIN_LABELS).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select>{origin !== 'all' && <small className="sk-filter-value">{ORIGIN_LABELS[origin]}</small>}</label>
      <div className="sk-checks"><label><input type="checkbox" checked={groupForeign} onChange={e => { setGroupForeign(e.target.checked); setHover(null); }} />해외 교육기관을 권역별로 묶기</label><label><input type="checkbox" checked={selfHireOnly} onChange={e => { setSelfHireOnly(e.target.checked); resetSelection(); }} />학부 모교 재직만 보기</label></div>
    </div>

    <div className="sk-metrics" aria-live="polite">
      <div><span>현재 표시 연구자</span><strong>{count(data.count)}<small>명</small></strong><p>세 단계에 동일한 인원 반영</p></div>
      <div><span>학부 모교 재직</span><strong>{count(data.selfHireCount)}<small>명 · {data.count ? (100 * data.selfHireCount / data.count).toFixed(1) : '0.0'}%</small></strong><p>학사기관과 현재 재직기관이 같은 경우</p></div>
      <div><span>학력 정보 완비율</span><strong>{data.subjectCount ? (100 * data.completeCount / data.subjectCount).toFixed(1) : '0.0'}<small>%</small></strong><p>선택 분야 {count(data.subjectCount)}명 중 {count(data.missingCount)}명 제외</p></div>
    </div>

    <section className="sk-chart-card" aria-labelledby="sk-chart-title">
      <div className="sk-chart-heading"><div><h2 id="sk-chart-title">학사 → 박사 → 현재 재직</h2><p>흐름의 두께는 연구자 수에 비례합니다. 기관이나 연결을 선택하면 해당 연구자의 경로가 드러납니다.</p></div><button className="sk-button sk-button-subtle" onClick={resetSelection} disabled={!selection}>선택 초기화</button></div>
      <ul className="sk-legend" aria-label="학부 출신별 색상 범례">{Object.entries(ORIGIN_LABELS).map(([key, label]) => <li key={key}><i style={{ backgroundColor: ORIGIN_COLORS[key as Origin] }} /><span>{label}</span></li>)}<li className="sk-legend-self"><i /><span>진한 흐름: 학부 모교 재직</span></li></ul>
      {data.count === 0 ? <div className="sk-empty"><strong>선택한 조건에 맞는 완비 경로가 없습니다.</strong><p>연구 분야 또는 학부 출신 필터를 조정해 주세요.</p></div> : <>
        <div className="sk-scroll-note">화면이 좁으면 도표를 좌우로 이동해 볼 수 있습니다. 아래 경로 표로도 탐색할 수 있습니다.</div>
        <div className="sk-chart-scroll" tabIndex={0} aria-label="학력 흐름 도표. 좌우 스크롤 가능">
          <div className="sk-column-labels">{STAGES.map((s, i) => <div key={s}><span>0{i + 1}</span><strong>{STAGE_LABELS[s]}</strong><small>{count(data.count)}명</small></div>)}</div>
          <svg className="sk-svg" viewBox={`0 0 ${layout.width} ${layout.height}`} width={layout.width} height={layout.height} aria-labelledby="sk-svg-title sk-svg-description">
            <title id="sk-svg-title">{SUBJECT_LABELS[subject] ?? '전체 분야'} 연구자 {count(data.count)}명의 학력과 재직기관 흐름</title>
            <desc id="sk-svg-description">기관은 세 단계에 따로 표시됩니다. 모든 연결의 폭은 인원에 선형 비례합니다. 기관을 선택하려면 탭과 엔터를 사용하세요. 연결 경로는 아래 표에서도 선택할 수 있습니다.</desc>
            {[...new Set(layout.nodes.map(node => node.x + 6))].map(x => <line key={x} x1={x} x2={x} y1={14} y2={layout.height - 14} stroke="#eef1f4" strokeDasharray="2 5" />)}
            <g className="sk-ribbons">{layout.links.map(link => {
              const info = linkSelection(link);
              return <path key={link.id} d={link.path} fill={ORIGIN_COLORS[link.origin]} fillOpacity={focused ? 0.055 : link.selfHire ? 0.6 : 0.23} role="button" tabIndex={-1} aria-label={`${info.label}, ${count(link.count)}명`} onClick={() => choose(info)} onKeyDown={event => keyChoose(event, info)} onMouseEnter={() => setHover(info)} onMouseLeave={() => setHover(null)}><title>{info.label} · {count(link.count)}명</title></path>;
            })}</g>
            {focused && <g className="sk-highlight-ribbons" pointerEvents="none">{layout.links.map(link => {
              const selected = link.personIds.filter(id => focusIds.has(id)).length;
              if (!selected) return null;
              const h = selected * layout.scale, offset = (link.height - h) / 2;
              return <path key={link.id} d={ribbonPath(link.sourceX, link.targetX, link.sourceY + offset, link.targetY + offset, h)} fill={ORIGIN_COLORS[link.origin]} fillOpacity={0.72} />;
            })}</g>}
            <g>{layout.nodes.map(node => {
              const info = nodeSelection(node), selected = node.personIds.filter(id => focusIds.has(id)).length;
              const first = node.stage === 'bachelor';
              const x = first ? node.x - 12 : node.x + 24;
              const color = first && node.key in ORIGIN_COLORS ? ORIGIN_COLORS[node.key as Origin] : node.stage === 'current' ? '#30475e' : '#6386b5';
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
        </div>
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
      <div className="sk-section-heading"><div><p className="sk-eyebrow">경로 자세히 보기</p><h2 id="sk-routes-title">기관별 학력 · 재직 경로</h2><p>묶음 표시를 펼친 실제 기관명입니다. {selectedIds.size ? '선택한 연구자에 해당하는 경로만 표시합니다.' : '각 행은 세 기관을 모두 거친 연구자를 나타냅니다.'}</p></div><button className="sk-button" onClick={downloadTable} disabled={!routes.length}>집계표 내려받기 <span aria-hidden="true">↓</span></button></div>
      <div className="sk-table-scroll"><table><caption className="sk-sr-only">학사기관, 박사기관, 현재 재직기관별 완전 경로의 인원</caption><thead><tr><th scope="col">학사기관</th><th scope="col">박사기관</th><th scope="col">현재 재직기관</th><th scope="col" className="sk-number">인원</th><th scope="col">경로 탐색</th></tr></thead><tbody>{routes.slice(currentPage * pageSize, (currentPage + 1) * pageSize).map(route => <tr key={route.id}>{route.labels.map((label, i) => <td key={i}>{i === 0 && <i className="sk-origin-dot" style={{ background: ORIGIN_COLORS[route.origin] }} />}{label}{i === 2 && route.selfHire && <span className="sk-self-badge">학부 모교</span>}</td>)}<td className="sk-number">{count(route.count)}명</td><td><button className="sk-table-button" onClick={() => chooseRoute(route)} aria-label={`${route.labels.join(' → ')}, ${count(route.count)}명 경로 보기`}>경로 보기 <span aria-hidden="true">→</span></button></td></tr>)}</tbody></table></div>
      {!routes.length && <p className="sk-empty-small">표시할 경로가 없습니다.</p>}
      <Pagination page={currentPage} total={routes.length} onChange={setPage} label="경로 표" />
    </section>

    <details className="sk-method"><summary>데이터와 읽는 방법</summary><div>
      <p>한 연구자는 학사 → 박사, 박사 → 현재 재직의 두 연결에 각각 한 번씩 포함됩니다. 같은 화면에서는 모든 단계와 연결에 동일한 인원당 폭을 적용합니다. 분야나 필터를 바꾸면 화면에 맞추어 폭을 다시 계산하므로, 서로 다른 화면의 두께를 직접 비교하지 마세요.</p>
      <p>선택 분야 {count(data.subjectCount)}명 중 학사·박사·재직기관이 모두 기재된 {count(data.completeCount)}명을 대상으로 합니다. 하나 이상 누락된 {count(data.missingCount)}명은 제외합니다. 단계별 누락은 학사 {count(data.missingByStage.bachelor)}명, 박사 {count(data.missingByStage.phd)}명, 재직 {count(data.missingByStage.current)}명이며, 중복될 수 있습니다.</p>
      <p>기관 수를 줄여도 연구자는 제외하지 않고 나머지를 ‘기타’로 묶습니다. 학부 출신 다섯 기관과 해외 권역 묶음은 별도 표시합니다. 해외 권역은 데이터에 기록된 국가만으로 분류하며, 국가가 없으면 국내로 추정하지 않습니다. 현재 표시 중 학사 또는 박사 국가 미확인 {count(data.unknownCountryCount)}명, 숫자 코드만 있어 기관명이 미확인인 연구자 {count(data.unresolvedInstitutionCount)}명입니다.</p>
      <p>‘학부 모교 재직’은 정규화한 학사기관과 현재 재직기관의 일치를 뜻합니다. 학과 일치나 실제 임용 경위를 뜻하지 않습니다. 이는 별자리 페이지의 국내 ‘학교+학과’ 공간 일치 기준과 다른, 학교 단위 학력 흐름 지표입니다. 분교는 명시적으로 같은 본교 캠퍼스로 확인된 표기를 제외하고 합치지 않습니다.</p>
      <p>이 도표는 제공된 노트북의 학사–박사–재직 흐름, 학부 출신 색상, 모교 재직 강조를 웹으로 옮겼습니다. 인원은 그대로 보존하고, 선의 교차를 줄이는 반복 정렬을 사용합니다. 노트북의 HITS 순위나 임의 기관 점수 보정은 적용하지 않습니다.</p>
    </div></details>
  </section>;
}

function Pagination({ page, total, onChange, label }: { page: number; total: number; onChange: (page: number) => void; label: string }) {
  const pages = Math.max(1, Math.ceil(total / pageSize));
  return <nav className="sk-pagination" aria-label={`${label} 페이지`}><span>총 {count(total)}개{total ? ` · ${count(page * pageSize + 1)}–${count(Math.min((page + 1) * pageSize, total))}` : ''}</span><div><button className="sk-button" onClick={() => onChange(page - 1)} disabled={page === 0} aria-label={`${label} 이전 페이지`}>← 이전</button><span>{page + 1} / {pages}</span><button className="sk-button" onClick={() => onChange(page + 1)} disabled={page + 1 >= pages} aria-label={`${label} 다음 페이지`}>다음 →</button></div></nav>;
}
