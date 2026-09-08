import { useMemo, useState } from 'react';
import type { Professor } from './types';
import { buildInstitutionStatistics, type CountShare, type InstitutionMovement } from './institutionStatistics';
import './temporal-institutions.css';

const subjects: Record<string, string> = { mathematics: '수학', physics: '물리', chemistry: '화학', biology: '생물' };
const count = (value: number | null | undefined) => value === null || value === undefined ? '—' : value.toLocaleString('ko-KR');
const share = (value: number | null) => value === null ? '—' : `${(value * 100).toFixed(1)}%`;
const degreeYear = (value: number | null) => value === null ? '—' : `${value.toLocaleString('ko-KR', { useGrouping: false, maximumFractionDigits: 1 })}년`;
const countryNames = new Intl.DisplayNames(['ko'], { type: 'region' });
const countryLabel = (value: string | null) => value && /^[A-Z]{2}$/.test(value) ? countryNames.of(value) || value : value || '국가 미상';
const fieldNames = (rows: CountShare[]) => rows.filter(row => row.count > 0).map(row => subjects[row.label] || row.label).join(' · ') || '관측 분야 없음';

function Distribution({ title, rows, denominator, empty }: { title: string; rows: CountShare[]; denominator: string; empty: string }) {
  const [expanded, setExpanded] = useState(false);
  const visible = expanded ? rows : rows.slice(0, 12);
  return <article className="iw-distribution"><h3>{title}</h3><p className="iw-denominator">{denominator}</p>{rows.length ? <><div className="iw-distribution-rows">{visible.map(row => <div className="iw-distribution-row" key={row.label}><span>{row.label}</span><strong>{count(row.count)}명</strong><small>{share(row.share)}</small><i aria-hidden="true" style={{ width: `${Math.max(0, Math.min(100, (row.share ?? 0) * 100))}%` }}/></div>)}</div>{rows.length > 12 && <button className="iw-text-button" onClick={() => setExpanded(value => !value)} aria-expanded={expanded}>{expanded ? '상위 12개만 보기' : `전체 ${rows.length}개 항목 보기`}</button>}</> : <p className="iw-empty-inline">{empty}</p>}</article>;
}

function MovementDetails({ movement, currentCount, year, termLabel }: { movement: InstitutionMovement; currentCount: number; year: number; termLabel: string }) {
  if (!movement.comparable) return <div className="iw-comparison-unavailable" role="status"><strong>이전 연도와 이동을 비교할 수 없습니다.</strong><p>{movement.reason || '같은 학기와 분야의 인접 연도 명부가 필요합니다.'}</p><p>관측된 인원은 표시하며, 증감·유입·유출을 채용이나 퇴직으로 해석하지 않습니다.</p></div>;
  return <>
    <div className="iw-movement-heading"><h3>{movement.previousYear} → {year}년 {termLabel} 명부</h3><p>{count(movement.previousCount)}명 → {count(currentCount)}명 · 같은 기관에서 다시 관측된 연구자 {count(movement.retained)}명</p></div>
    <div className="iw-movement-columns">
      <article><h4>이번 명부에 새로 관측 <strong>{count(movement.added)}명</strong></h4><dl><div><dt>다른 단일 기관에서 관측</dt><dd>{count(movement.movesIn)}명</dd></div><div><dt>대학 통합에 따른 기관 승계</dt><dd>{count(movement.mergerIn)}명</dd></div><div><dt>전년도 명부에 미관측</dt><dd>{count(movement.priorUnobserved)}명</dd></div><div><dt>복수·미해소 기관으로 이동 판정 보류</dt><dd>{count(movement.ambiguousIn)}명</dd></div></dl></article>
      <article><h4>이번 명부에서 빠짐 <strong>{count(movement.removed)}명</strong></h4><dl><div><dt>다른 단일 기관에서 관측</dt><dd>{count(movement.movesOut)}명</dd></div><div><dt>대학 통합에 따른 기관 승계</dt><dd>{count(movement.mergerOut)}명</dd></div><div><dt>이번 명부에 미관측</dt><dd>{count(movement.nextUnobserved)}명</dd></div><div><dt>복수·미해소 기관으로 이동 판정 보류</dt><dd>{count(movement.ambiguousOut)}명</dd></div></dl></article>
    </div>
    <p className="iw-help">명부에 새로 등장하거나 빠진 사실을 채용·퇴직으로 간주하지 않습니다. 서로 다른 단일 기관에서 관측된 경우만 소속 변경으로 분류하고, 통합 승계와 복수·미해소 기관, 다른 해의 미관측을 분리합니다.</p>
    <div className="iw-two-columns"><Distribution title="관측 유입의 출발 기관" rows={movement.sources} denominator={`분모: 통합 승계를 제외한 단일 기관 간 관측 유입 ${count(movement.movesIn)}명`} empty="조건에 해당하는 소속 변경이 없습니다."/><Distribution title="관측 유출의 도착 기관" rows={movement.destinations} denominator={`분모: 통합 승계를 제외한 단일 기관 간 관측 유출 ${count(movement.movesOut)}명`} empty="조건에 해당하는 소속 변경이 없습니다."/></div>
  </>;
}

export default function TemporalInstitutionsPage({ professors, releaseYear }: { professors: Professor[]; releaseYear: number }) {
  const [subject, setSubject] = useState('');
  const [term, setTerm] = useState<'spring' | 'fall'>('spring');
  const [year, setYear] = useState<number | null>(null);
  const [institutionId, setInstitutionId] = useState('');
  const globalData = useMemo(() => buildInstitutionStatistics(professors, { releaseYear, term }), [professors, releaseYear, term]);
  const data = useMemo(() => subject ? buildInstitutionStatistics(professors, { releaseYear, term, subject }) : globalData, [professors, releaseYear, term, subject, globalData]);
  const availableYears = globalData.years;
  const selectedYear = year !== null && availableYears.includes(year) ? year : availableYears.at(-1) ?? releaseYear;
  const institution = data.institutions.find(row => row.id === institutionId) ?? [...data.institutions].sort((a, b) => (b.years.find(row => row.year === selectedYear)?.count ?? 0) - (a.years.find(row => row.year === selectedYear)?.count ?? 0) || a.label.localeCompare(b.label, 'ko'))[0];
  const point = institution?.years.find(row => row.year === selectedYear);
  const annualGlobal = globalData.coverage.annual.find(row => row.year === selectedYear);
  const annualSelected = data.coverage.annual.find(row => row.year === selectedYear);
  const series = institution?.years.filter(row => availableYears.includes(row.year)) ?? [];
  const maximumCount = Math.max(1, ...series.map(row => row.count));
  const termLabel = term === 'spring' ? '봄학기' : '가을학기';
  const subjectLabel = subjects[subject] || '전체 분야';
  const origins = point?.origins;
  const originCountryGroups = origins ? [
    { label: '국내 박사', count: origins.domestic, color: '#256ef4' },
    { label: '국외 박사', count: origins.foreign, color: '#008575' },
    { label: '국가 미상', count: origins.unknownCountry, color: '#89929b' },
  ] : [];
  const comparable = point?.movement.comparable === true;
  const difference = comparable ? point?.change : null;
  return <section className="workforce-page" aria-labelledby="iw-title">
    <header className="iw-intro"><p className="iw-kicker">Institutional workforce statistics</p><h1 id="iw-title">기관 인력 통계</h1><p>같은 학기 명부를 비교해 관측 인원, 기관 간 소속 변경과 박사 출신 구성을 살펴봅니다.</p></header>
    <div className="iw-scope-note"><strong>명부에서 실제로 관측된 연구자만 셉니다.</strong><p>이 페이지는 {releaseYear}년 공개 자료에 포함된 연구자들의 학기별 기록을 설명합니다. 과거 기관 전체 인력이나 채용·퇴직 현황이 아니며, 경력 구간에서 빈 학기를 추정해 채우지 않습니다.</p></div>
    <div className="iw-controls" aria-label="통계 조회 조건">
      <label><span>학기</span><select value={term} onChange={e => { setTerm(e.target.value as 'spring' | 'fall'); setYear(null); }}><option value="spring">봄학기</option><option value="fall">가을학기</option></select></label>
      <label><span>연도</span><select value={selectedYear} disabled={!availableYears.length} onChange={e => setYear(Number(e.target.value))}>{availableYears.length ? availableYears.map(value => <option key={value} value={value}>{value}년</option>) : <option value={releaseYear}>관측 명부 없음</option>}</select></label>
      <label><span>연구 분야</span><select value={subject} onChange={e => { setSubject(e.target.value); setInstitutionId(''); }}><option value="">전체 분야</option>{Object.entries(subjects).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
      <label className="iw-institution-select"><span>기관 · 국가</span><select value={institution?.id || ''} disabled={!data.institutions.length} onChange={e => setInstitutionId(e.target.value)}>{data.institutions.length ? data.institutions.map(row => <option key={row.id} value={row.id}>{row.label} · {countryLabel(row.country)}</option>) : <option value="">선택 분야의 관측 기관 없음</option>}</select></label>
    </div>
    <section className="iw-coverage-banner" aria-labelledby="iw-coverage-summary"><h2 id="iw-coverage-summary">{selectedYear}년 {termLabel} 관측 범위</h2><div><p><span>전체 관측 명부</span><strong>{count(annualGlobal?.people)}명</strong><small>{annualGlobal ? fieldNames(annualGlobal.subjects) : '이 학기의 관측 명부 없음'}</small></p><p><span>{subjectLabel} 관측 명부</span><strong>{count(annualSelected?.people)}명</strong><small>{count(annualSelected?.institutions)}개 기관</small></p></div><p className="iw-help">분야별 관측 범위가 다른 인접 연도는 증감과 이동을 비교하지 않습니다. 아래 연도별 관측 범위 표에서 비교의 분모를 확인할 수 있습니다.</p></section>
    {institution && point ? <>
      <section className="iw-institution-heading"><div><h2>{institution.label}</h2><p>{selectedYear}년 {termLabel} · {subjectLabel} · {countryLabel(institution.country)}</p></div><span className="iw-scope-chip">실제 학기 명부 기준</span></section>
      <div className="iw-summary-grid">
        <article><span>관측 인원</span><strong>{count(point.count)}<small>명</small></strong><p>같은 기관의 중복 기록은 한 번만</p></article>
        <article><span>선택 분야 명부 내 비중</span><strong>{share(point.shareOfObserved)}</strong><p>분모 {count(point.totalObservedPeople)}명</p></article>
        <article><span>전년 같은 학기 대비 관측 증감</span><strong>{difference === null || difference === undefined ? '—' : `${difference > 0 ? '+' : ''}${count(difference)}`}<small>{difference === null || difference === undefined ? '' : '명'}</small></strong><p>{comparable ? '명부 인원의 차이 · 고용 증감 아님' : '관측 범위 비교 불가'}</p></article>
        <article><span>다른 단일 기관에서 / 으로 관측</span><strong>{comparable ? `${count(point.movement.movesIn)} / ${count(point.movement.movesOut)}` : '—'}<small>{comparable ? '명' : ''}</small></strong><p>유입 / 유출 · 통합 승계 제외</p></article>
      </div>
      {!comparable && <div className="iw-comparison-note" role="status"><strong>이 연도의 증감·이동 수치는 표시하지 않습니다.</strong><p>{point.movement.reason || '비교 가능한 이전 연도 명부가 없습니다.'}</p></div>}
      <section className="iw-panel" aria-labelledby="iw-chart-title"><div className="iw-section-heading"><div><h2 id="iw-chart-title">같은 학기의 연도별 관측 인원</h2><p>{institution.label} · {termLabel} · {subjectLabel}</p></div><span>단위: 명</span></div>
        <div className="iw-count-chart" role="group" aria-label={`${institution.label}의 같은 학기 연도별 명부 관측 인원`}>{series.map(row => <button key={row.year} className={`iw-year-bar ${row.year === selectedYear ? 'selected' : ''}`} onClick={() => setYear(row.year)} aria-pressed={row.year === selectedYear} aria-label={`${row.year}년 ${termLabel} ${count(row.count)}명 선택`}><span className="iw-bar-value">{count(row.count)}</span><span className="iw-bar-track" aria-hidden="true"><i style={{ height: `${row.count / maximumCount * 100}%` }}/></span><strong>{row.year}</strong><small>{globalData.coverage.annual.find(coverage => coverage.year === row.year)?.subjects.filter(item => item.count > 0).length === Object.keys(subjects).length ? '4개 분야 관측' : fieldNames(globalData.coverage.annual.find(coverage => coverage.year === row.year)?.subjects || [])}</small></button>)}</div>
        <p className="iw-help">막대를 선택하면 해당 연도의 상세 통계를 표시합니다. 관측 범위가 달라지는 연도 사이에는 증가·감소를 해석하지 않습니다. 자료가 없는 연도·학기는 이전 명부로 대신하지 않습니다.</p>
      </section>
      <section className="iw-panel" aria-labelledby="iw-movement-title"><div className="iw-section-heading"><div><h2 id="iw-movement-title">관측 소속 변경과 미관측 분해</h2><p>전년과 같은 학기 사이에 누구의 소속 기록이 달라졌는지 구분합니다.</p></div></div><MovementDetails key={`${institution.id}:${selectedYear}:${term}:${subject}`} movement={point.movement} currentCount={point.count} year={selectedYear} termLabel={termLabel}/></section>
      {origins && <section className="iw-panel" aria-labelledby="iw-origin-title"><div className="iw-section-heading"><div><h2 id="iw-origin-title">박사 출신 구성</h2><p>모든 비중의 분모는 선택한 기관·분야·학기 명부의 {count(origins.total)}명이며, 미상도 포함합니다.</p></div></div>
        <div className="iw-origin-strip" aria-label="박사 취득 국가의 국내·국외·미상 구성">{originCountryGroups.map(group => <div key={group.label}><i aria-hidden="true" style={{ background: group.color }}/><span>{group.label}</span><strong>{count(group.count)}명</strong><small>{share(origins.total ? group.count / origins.total : null)}</small></div>)}</div>
        <div className="iw-composition-bar" aria-hidden="true">{originCountryGroups.map(group => <i key={group.label} style={{ background: group.color, width: `${origins.total ? group.count / origins.total * 100 : 0}%` }}/>)}</div>
        {origins.foreignShareBounds && <p className="iw-help">국가 미상에 따른 해외박사 비율 범위: {share(origins.foreignShareBounds.lower)}–{share(origins.foreignShareBounds.upper)}. 미상을 모두 국내 또는 모두 해외로 놓았을 때의 범위이며, 신뢰구간이 아닙니다.</p>}
        <div className="iw-two-columns"><Distribution key={`schools:${institution.id}:${selectedYear}:${term}:${subject}`} title="박사 출신 학교" rows={origins.schools} denominator={`분모 ${count(origins.total)}명 · 출신 학교 미상 ${count(origins.unknownSchool)}명 포함`} empty="표시할 명부 구성원이 없습니다."/><Distribution key={`countries:${institution.id}:${selectedYear}:${term}:${subject}`} title="박사 취득 국가" rows={origins.countries.map(row => ({ ...row, label: countryLabel(row.label) }))} denominator={`분모 ${count(origins.total)}명 · 취득 국가 미상 ${count(origins.unknownCountry)}명 포함`} empty="표시할 명부 구성원이 없습니다."/></div>
        <div className="iw-degree-years"><h3>박사 학위연도 · 보조 통계</h3><dl><div><dt>유효한 학위연도</dt><dd>{count(origins.validPhdYears)}명</dd></div><div><dt>미상·유효하지 않은 연도</dt><dd>{count(origins.missingOrInvalidPhdYears)}명</dd></div><div><dt>중앙값</dt><dd>{degreeYear(origins.medianPhdYear)}</dd></div><div><dt>중앙 50% 범위 · 1–3사분위</dt><dd>{degreeYear(origins.q1PhdYear)} – {degreeYear(origins.q3PhdYear)}</dd></div></dl><p className="iw-help">중앙값과 사분위수는 유효한 박사 학위연도가 있는 연구자만으로 계산합니다. 연령이나 근속기간을 뜻하지 않습니다.</p></div>
      </section>}
    </> : <div className="iw-empty"><h2>선택 조건의 관측 명부가 없습니다.</h2><p>다른 연도·학기·분야를 선택할 수 있습니다. 미관측을 인원 0명이나 기관의 부재로 해석하지 않습니다.</p></div>}
    <section className="iw-panel" aria-labelledby="iw-coverage-title"><div className="iw-section-heading"><div><h2 id="iw-coverage-title">연도별 관측 범위 · {termLabel}</h2><p>전체 분야의 명부 범위를 보여줍니다. 분야 필터를 바꾸어도 이 표의 전체 관측 분모는 유지합니다.</p></div></div><div className="iw-table-scroll"><table><caption>동일 학기의 실제 명부 관측 · 분야별 인원</caption><thead><tr><th scope="col">연도</th><th scope="col">전체 관측 인원</th><th scope="col">관측 기관</th><th scope="col">기관 미해소 연구자</th>{Object.values(subjects).map(label => <th key={label} scope="col">{label}</th>)}<th scope="col">관측 분야</th></tr></thead><tbody>{globalData.coverage.annual.map(row => <tr key={row.year} className={row.year === selectedYear ? 'selected' : ''}><th scope="row"><button onClick={() => setYear(row.year)}>{row.year}년</button></th><td>{count(row.people)}</td><td>{count(row.institutions)}</td><td>{count(row.unresolvedInstitutionPeople)}</td>{Object.keys(subjects).map(key => { const item = row.subjects.find(entry => entry.label === key); return <td key={key}>{item ? count(item.count) : '미관측'}</td>; })}<td>{fieldNames(row.subjects)}</td></tr>)}</tbody></table></div><p className="iw-help">학기 근거가 없는 명부 행 {count(globalData.coverage.missingTermRows)}개는 학기에 배정하지 않았습니다. 기관 정보가 없는 행 {count(globalData.coverage.missingInstitutionRows)}개는 기관별 집계에서 제외했습니다. 기관 미해소 연구자도 전체 관측 인원의 분모에는 포함하며, 국가만 미상인 기관은 기관 목록에도 그대로 포함합니다.</p></section>
    <section className="iw-method" aria-labelledby="iw-method-title"><h2 id="iw-method-title">계산과 해석 범위</h2><ul><li>학기별 교수 명부의 실제 관측만 사용합니다. 이력서·논문 소속·추정 경력 구간으로 학기별 인원을 보충하지 않습니다.</li><li>소속 변경은 인접 연도 같은 학기의 관측 분야 범위가 같을 때만 비교합니다. 두 시점 모두 단일 기관이 확인된 이동과 대학 통합 승계, 복수·미해소 기관, 미관측을 구분합니다. 같은 분야 범위여도 기관별 수집 완전성을 보장하지 않습니다.</li><li>강원대·경상대의 기관 집계 ID는 이름이 바뀌어도 유지합니다. 강릉원주대·경남과기대는 각각 통합 시행연도부터 승계 기관에 합치며, 원래 기준 기관에 계속 있던 사람을 신규 승계 인원으로 세지 않습니다.</li><li>출신 구성은 선택 명부 전체를 분모로 삼습니다. 미상 항목을 빼서 비중을 높이지 않으며, 학위연도 요약의 유효 인원은 따로 표시합니다. 복수 기관에 관측된 사람은 각 기관에서 세므로 기관별 비중의 합은 100%를 넘을 수 있습니다.</li></ul><p>이 자료는 과거 교수 전체를 무작위로 뽑은 표본이 아닙니다. 명부의 선택과 누락으로 기관 전체에 일반화할 수 없는 차이가 생길 수 있습니다. 이러한 선택·포괄 범위의 제한은 <a href="https://www150.statcan.gc.ca/n1/edu/power-pouvoir/ch13/nonprob/5214898-eng.htm" target="_blank" rel="noreferrer">Statistics Canada의 비확률 표본 설명</a>을 참고하세요. 이 페이지는 자동 유의확률이나 신뢰구간을 제시하지 않습니다.</p></section>
  </section>;
}
