import { useEffect, useMemo, useRef, useState } from 'react';
import type { Professor } from './types';
import { canonicalSchool, institutionDisplayName, institutionSearchText } from './schoolIdentity';
import {
  layoutAlluvial, layoutMulti, normalizeTopicDetail, normalizeTopicIndex, orderedTopics, queryResearchers, searchTopics, seriesFromHits, tagCloud, topicColors, withDetail, yearRange,
  type AlluvialMode, type EncryptedPaperTitles, type MultiMode, type QueryEntry, type TopicDetail, type TopicHit, type TopicIndex, type TopicResearcher,
} from './topics';
import type { TopicTitleSource } from './topicTitles';
import ResearchAreaTree from './ResearchAreaTree';
import { researcherTexts } from './researcherQuery';
import { useResearchAreas } from './useResearchAreas';
import InfoFlowPanel from './InfoFlowPanel';
import { downloadSvg, figureDate, printSvgAsPdf, type FigureMeta } from './exportFigure';
import './topics.css';

type Props = { professors: Professor[]; names: Record<string, string> | null; titles: TopicTitleSource | null; releaseYear: number; onOpenCareer: (id: string) => void };
const PAGE = 60;
type Selection = { kind: 'none' } | { kind: 'institution'; key: string } | { kind: 'researcher'; id: string } | { kind: 'topic'; q: string };
const SUBJECTS: Record<string, string> = { mathematics: '수학', physics: '물리', chemistry: '화학', biology: '생물' };
const n = (value: number) => value.toLocaleString('ko-KR');

function readSelection(): Selection {
  const params = new URLSearchParams(window.location.hash.split('?')[1] || '');
  const r = params.get('r'), i = params.get('i'), q = params.get('q');
  return r ? { kind: 'researcher', id: r } : i ? { kind: 'institution', key: i } : q ? { kind: 'topic', q } : { kind: 'none' };
}
function writeSelection(selection: Selection) {
  const query = selection.kind === 'researcher' ? `?r=${encodeURIComponent(selection.id)}` : selection.kind === 'institution' ? `?i=${encodeURIComponent(selection.key)}` : selection.kind === 'topic' ? `?q=${encodeURIComponent(selection.q)}` : '';
  const hash = `#/topics${query}`;
  if (window.location.hash !== hash) window.history.replaceState(null, '', hash);
}
const institutionName = (value: string | null) => value ? (/[가-힣]/.test(value) ? value : institutionDisplayName(value)) : '기관 미상';

function Thumbnail({ researcher }: { researcher: TopicResearcher }) {
  const layout = useMemo(() => layoutAlluvial(researcher, 'year', { compact: true, columnWidth: 7 }), [researcher]);
  return <svg className="tp-thumb" viewBox={`0 0 ${layout.width} ${Math.max(layout.height, 24)}`} preserveAspectRatio="none" aria-hidden="true">
    {layout.ribbons.map(r => <path key={r.topic} d={r.d} fill={r.color} fillOpacity=".55" />)}
  </svg>;
}

function ResearcherCard({ researcher, label, onOpen }: { researcher: TopicResearcher; label: string; onOpen: () => void }) {
  const range = yearRange(researcher);
  return <button type="button" className="tp-card" onClick={onOpen}>
    <span className="tp-card-head"><strong>{label}</strong><span className="tp-chip">{SUBJECTS[researcher.subject] || researcher.subject}</span></span>
    <small>{institutionName(researcher.institution)}</small>
    <Thumbnail researcher={researcher} />
    <span className="tp-card-meta"><span>토픽 <b>{researcher.topics.length}</b></span><span>논문 <b>{researcher.papers.length}</b></span><span>{range ? `${range[0]}–${range[1]}` : '—'}</span></span>
  </button>;
}

/** Column width that fills the card; falls back to horizontal scroll when there are many columns. */
function useFitColumns(columns: number, left: number, minimum: number, maximum: number) {
  const ref = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(0);
  useEffect(() => {
    const node = ref.current;
    if (!node) return;
    const observer = new ResizeObserver(entries => setWidth(entries[0].contentRect.width));
    observer.observe(node);
    return () => observer.disconnect();
  }, []);
  const fit = columns ? (width - left - 24) / columns : minimum;
  return { ref, columnWidth: Math.max(minimum, Math.min(maximum, fit || minimum)) };
}

type Tip = { x: number; y: number; topic: number; column: number; count: number; cited: number } | null;

function AlluvialChart({ researcher, mode, showArcs, focus, setFocus, titles, svgRef }: {
  researcher: TopicResearcher; mode: AlluvialMode; showArcs: boolean; focus: number | null; setFocus: (topic: number | null) => void;
  titles: EncryptedPaperTitles[string] | null; svgRef?: React.Ref<SVGSVGElement>;
}) {
  const columnCount = mode === 'year' ? (yearRange(researcher) ? yearRange(researcher)![1] - yearRange(researcher)![0] + 1 : 0) : researcher.eras.length;
  const { ref: wrap, columnWidth } = useFitColumns(columnCount, 228, mode === 'year' ? 34 : 120, mode === 'year' ? 72 : 260);
  const layout = useMemo(() => layoutAlluvial(researcher, mode, { columnWidth }), [researcher, mode, columnWidth]);
  const [tip, setTip] = useState<Tip>(null);
  const [pinned, setPinned] = useState(false);
  const shown = new Map(layout.lanes.map(l => [l.topic.id, l]));
  const dim = (topic: number) => focus !== null && focus !== topic;
  const tipLane = tip ? shown.get(tip.topic) : null;
  const tipColumn = tip ? layout.columns[tip.column] : null;
  const tipTitles = tip && titles && tipColumn ? titles.filter(t => t.topic === tip.topic && (mode === 'year' ? t.year === Number(tipColumn.label) : (tipColumn.start === null || t.year >= tipColumn.start) && (tipColumn.end === null || t.year <= tipColumn.end))) : [];
  function showTip(event: React.MouseEvent | React.FocusEvent, dot: typeof layout.dots[number]) {
    if (pinned) return;
    const box = wrap.current?.getBoundingClientRect(), target = (event.currentTarget as Element).getBoundingClientRect();
    if (!box) return;
    setTip({ x: target.left - box.left + target.width / 2 + (wrap.current?.scrollLeft || 0), y: target.top - box.top, topic: dot.topic, column: dot.column, count: dot.count, cited: dot.cited });
    setFocus(dot.topic);
  }
  const clear = () => { if (!pinned) { setTip(null); setFocus(null); } };
  return <div className="tp-chart-scroll" ref={wrap} onMouseLeave={clear}>
    {!layout.lanes.length ? <p className="tp-empty">표시할 논문이 없습니다.</p> : <svg ref={svgRef} className="tp-chart" width={layout.width} height={layout.height} viewBox={`0 0 ${layout.width} ${layout.height}`} role="img" aria-labelledby="tp-chart-title tp-chart-desc">
      <title id="tp-chart-title">{mode === 'year' ? '연도별' : '경력 시기별'} 연구 토픽 흐름</title>
      <desc id="tp-chart-desc">토픽 {layout.lanes.length}개, 논문 {layout.placed}편. 띠의 두께는 해당 {mode === 'year' ? '연도' : '시기'} 논문 수, 점선은 모토픽에서의 분기입니다.</desc>
      {layout.bands.map((band, i) => <g key={i} className="tp-band"><rect x={band.x} y={12 + band.row * 28} width={band.width} height={24} rx="6" /><text x={band.x + 8} y={12 + band.row * 28 + 16}>{band.label}<title>{band.label}</title></text></g>)}
      {layout.ticks.map((tick, i) => <g key={i} className={`tp-tick ${tick.major ? 'major' : ''}`}>
        <line x1={tick.x} x2={tick.x} y1={layout.top - 10} y2={layout.height - 8} />
        {mode === 'year' ? (tick.major && <text x={tick.x} y={layout.top - 16} textAnchor="middle">{tick.label}</text>)
          : <text x={tick.x} y={layout.top - 26} textAnchor="middle"><tspan x={tick.x}>{tick.label.replace(/\s*\(.*\)\s*$/, '').slice(0, 14)}</tspan><tspan x={tick.x} dy="15" className="tp-tick-sub">{tick.label.match(/\(([^)]*)\)\s*$/)?.[1] || ''}</tspan></text>}
      </g>)}
      {layout.lanes.map(lane => <g key={lane.topic.id} className={`tp-lane-label ${dim(lane.topic.id) ? 'is-dim' : ''}`} onMouseEnter={() => !pinned && setFocus(lane.topic.id)} onMouseLeave={clear}>
        <rect x={12} y={lane.mid - 5} width={10} height={10} rx="3" fill={lane.color} />
        {(() => {
          // English c-TF-IDF names: leading term on the first line, the rest below.
          const [head, ...rest] = lane.topic.label.split(' · ');
          const clip = (s: string, n: number) => s.length > n ? `${s.slice(0, n - 1)}…` : s;
          return rest.length
            ? <text x={30} y={lane.mid - 2}>{clip(head, 22)}<tspan x={30} dy="14" className="tp-lane-sub">{clip(rest.join(' · '), 28)}</tspan><title>{lane.topic.label}</title></text>
            : <text x={30} y={lane.mid + 4}>{clip(head, 22)}<title>{lane.topic.label}</title></text>;
        })()}
        <text x={layout.left - 14} y={lane.mid + 4} textAnchor="end" className="tp-lane-n">{lane.counts.reduce((a, b) => a + b, 0)}</text>
      </g>)}
      {layout.ribbons.map(r => <path key={r.topic} d={r.d} className={`tp-ribbon ${dim(r.topic) ? 'is-dim' : ''} ${focus === r.topic ? 'is-focus' : ''}`} fill={r.color} stroke={r.color} />)}
      {layout.branches.map(b => <path key={`${b.from}-${b.to}`} d={b.d} className={`tp-branch ${dim(b.to) && dim(b.from) ? 'is-dim' : ''}`} stroke={shown.get(b.to)?.color}><title>{`${shown.get(b.from)?.topic.label} → ${shown.get(b.to)?.topic.label} · coupling ${b.sim}`}</title></path>)}
      {showArcs && layout.arcs.map((arc, i) => <path key={i} d={arc.d} className={`tp-arc ${dim(arc.to) && dim(arc.from) ? 'is-dim' : ''}`} />)}
      {layout.births.filter(b => b.independent).map(b => <g key={b.topic} className={`tp-new ${dim(b.topic) ? 'is-dim' : ''}`}><rect x={b.x - 30} y={b.y - 8} width={26} height={16} rx="8" /><text x={b.x - 17} y={b.y + 3.5} textAnchor="middle">NEW</text></g>)}
      {layout.dots.map(dot => <circle key={`${dot.topic}-${dot.column}`} cx={dot.x} cy={dot.y} r={dot.r} className={`tp-dot ${dim(dot.topic) ? 'is-dim' : ''}`} stroke={shown.get(dot.topic)?.color} tabIndex={0}
        aria-label={`${layout.columns[dot.column].label} ${shown.get(dot.topic)?.topic.label} ${dot.count}편`}
        onMouseEnter={e => showTip(e, dot)} onFocus={e => showTip(e, dot)} onBlur={clear}
        onClick={e => { if (pinned) { setPinned(false); setTip(null); setFocus(null); } else { showTip(e, dot); setPinned(true); } }} />)}
    </svg>}
    {tip && tipLane && tipColumn && <div className={`tp-tip ${pinned ? 'is-pinned' : ''}`} style={{ left: tip.x, top: tip.y }} role="status">
      <span className="tp-tip-head"><i style={{ background: tipLane.color }} />{tipLane.topic.label}</span>
      <strong>{tipColumn.label} · {tip.count}편</strong>
      <small>피인용 합계 {n(tip.cited)}</small>
      {tipTitles.length > 0 && <ul>{tipTitles.slice(0, 5).map((t, i) => <li key={i}>{t.doi ? <a href={t.doi} target="_blank" rel="noreferrer">{t.title}</a> : t.title}{t.venue && <em>{t.venue}</em>}</li>)}</ul>}
      {!titles && <small className="tp-tip-lock">잠금 해제 시 논문 제목 표시</small>}
      {pinned && <small className="tp-tip-lock">점을 다시 누르면 닫힙니다</small>}
    </div>}
  </div>;
}

function MultiChart({ hits, mode, labelFor }: { hits: TopicHit[]; mode: MultiMode; labelFor: (id: string) => string }) {
  const series = useMemo(() => seriesFromHits(hits, labelFor), [hits, labelFor]);
  const years = series.flatMap(s => [...s.counts.keys()]);
  const { ref, columnWidth } = useFitColumns(years.length ? Math.max(...years) - Math.min(...years) + 1 : 0, mode === 'stack' ? 240 : 64, 30, 64);
  const layout = useMemo(() => layoutMulti(series, mode, { columnWidth }), [series, mode, columnWidth]);
  const [focus, setFocus] = useState<string | null>(null);
  return <>
    <div className="tp-chart-scroll" ref={ref}>{!layout.shapes.length ? <p className="tp-empty">선택한 토픽에 논문이 없습니다.</p> : <svg className="tp-chart" width={layout.width} height={layout.height} viewBox={`0 0 ${layout.width} ${layout.height}`} role="img" aria-label={`토픽 검색 결과 ${layout.lanes.length}명의 연도별 논문 수 (${mode === 'stack' ? '연구자별 레인' : '연구자별 색 누적'})`}>
      {layout.ticks.map((t, i) => <g key={i} className={`tp-tick ${t.major ? 'major' : ''}`}><line x1={t.x} x2={t.x} y1={layout.top - 8} y2={layout.height - 8} />{t.major && <text x={t.x} y={layout.top - 14} textAnchor="middle">{t.label}</text>}</g>)}
      {layout.shapes.map(shape => <path key={shape.key} d={shape.d} fill={shape.color} stroke={shape.color} className={`tp-ribbon ${focus && focus !== shape.key ? 'is-dim' : ''} ${focus === shape.key ? 'is-focus' : ''}`} onMouseEnter={() => setFocus(shape.key)} onMouseLeave={() => setFocus(null)}><title>{layout.lanes.find(l => l.key === shape.key)?.label}</title></path>)}
      {mode === 'stack' && layout.lanes.map(lane => <g key={lane.key} className={`tp-lane-label ${focus && focus !== lane.key ? 'is-dim' : ''}`} onMouseEnter={() => setFocus(lane.key)} onMouseLeave={() => setFocus(null)}>
        <rect x={12} y={lane.mid - 5} width={10} height={10} rx="3" fill={lane.color} />
        <text x={30} y={lane.mid + 4}>{lane.label.length > 18 ? `${lane.label.slice(0, 17)}…` : lane.label}<title>{`${lane.label} — ${lane.sublabel}`}</title></text>
        <text x={layout.left - 14} y={lane.mid + 4} textAnchor="end" className="tp-lane-n">{lane.total}</text></g>)}
      {mode === 'overlay' && layout.totals.map((t, i) => <text key={i} x={t.x} y={t.y} textAnchor="middle" className="tp-total">{t.n}</text>)}
    </svg>}</div>
    <ul className="tp-legend">{layout.lanes.map(lane => <li key={lane.key} className={focus && focus !== lane.key ? 'is-dim' : ''} onMouseEnter={() => setFocus(lane.key)} onMouseLeave={() => setFocus(null)}><i style={{ background: lane.color }} /><b>{lane.label}</b><span>{lane.sublabel}</span><em>{lane.total}편</em></li>)}</ul>
  </>;
}

function TopicTable({ researcher, focus, setFocus }: { researcher: TopicResearcher; focus: number | null; setFocus: (t: number | null) => void }) {
  const colors = topicColors(researcher);
  const byId = new Map(researcher.topics.map(t => [t.id, t]));
  return <div className="tp-table-wrap"><table className="tp-table">
    <thead><tr><th>토픽 · 특징어 (c-TF-IDF) · 요약</th><th className="num">논문</th><th>활동</th><th>기원</th></tr></thead>
    <tbody>{orderedTopics(researcher).map(topic => {
      const years = researcher.papers.filter(p => p.topic === topic.id).map(p => p.year);
      return <tr key={topic.id} className={focus === topic.id ? 'is-focus' : ''} onMouseEnter={() => setFocus(topic.id)} onMouseLeave={() => setFocus(null)}>
        <th scope="row"><i style={{ background: colors.get(topic.id) }} />{topic.label}{topic.tags.en.length > 0 && <span className="tp-tags">{topic.tags.en.filter(tag => !topic.label.toLowerCase().includes(tag)).slice(0, 5).map(tag => <em key={tag}>{tag}</em>)}</span>}
          {topic.summary && <span className="tp-summary">{topic.summary.ko && <span lang="ko">{topic.summary.ko}</span>}{topic.summary.en && <small lang="en">{topic.summary.en}</small>}</span>}</th>
        <td className="num">{years.length}</td>
        <td>{years.length ? `${Math.min(...years)}–${Math.max(...years)}` : '—'}</td>
        <td>{topic.misc ? <span className="tp-muted">작은 군집 묶음</span> : topic.parent ? <span className="tp-origin">← {byId.get(topic.parent.from)?.label || `T${topic.parent.from}`}<small>coupling {topic.parent.sim}</small></span> : <span className="tp-chip tp-chip-new">독립 신규</span>}</td>
      </tr>;
    })}</tbody>
  </table></div>;
}

export default function TopicsPage({ professors, names, titles, releaseYear, onOpenCareer }: Props) {
  const [index, setIndex] = useState<TopicIndex | null>(null);
  const areas = useResearchAreas();
  const chartSvg = useRef<SVGSVGElement>(null);
  // Exports name the researcher by alias or anonymous ID only; decrypted names stay on screen.
  const chartMeta = (r: TopicResearcher): FigureMeta => ({
    title: `연구 토픽 흐름 · ${r.alias || r.id}`,
    subtitle: `${mode === 'year' ? '연도별' : '경력 시기별'} · 띠 두께 = 논문 수 · 점선 = 모토픽에서의 분기${showArcs ? ' · ABA 경로 표시' : ''}`,
    note: `K–STEM Research Atlas · ${releaseYear} 공개 자료 · 토픽 = 공유 참고문헌 Louvain 군집, 이름 = c-TF-IDF 특징어 · ${figureDate()} 내보냄`,
    filename: `kstem-topic-flow-${r.id}-${mode}-${figureDate()}`,
  });
  const [error, setError] = useState('');
  const [query, setQuery] = useState('');
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const [subject, setSubject] = useState('');
  const [selection, setSelectionState] = useState<Selection>(readSelection);
  const [mode, setMode] = useState<AlluvialMode>('year');
  const [showArcs, setShowArcs] = useState(true);
  const [focus, setFocus] = useState<number | null>(null);
  const [searchMode, setSearchMode] = useState<'people' | 'topic'>(() => readSelection().kind === 'topic' ? 'topic' : 'people');
  const [topicQuery, setTopicQuery] = useState(() => { const sel = readSelection(); return sel.kind === 'topic' ? sel.q : ''; });
  const [multiMode, setMultiMode] = useState<MultiMode>('stack');
  const [excluded, setExcluded] = useState<Set<string>>(new Set());
  const [details, setDetails] = useState<Map<string, TopicDetail | 'error'>>(new Map());
  const [paperTitles, setPaperTitles] = useState<{ id: string; rows: EncryptedPaperTitles[string] | null } | null>(null);
  const [paging, setPaging] = useState({ key: '', n: PAGE });
  const input = useRef<HTMLInputElement>(null);
  function select(next: Selection) { setSelectionState(next); writeSelection(next); setOpen(false); setQuery(''); setFocus(null); window.scrollTo({ top: 0, behavior: 'smooth' }); }

  useEffect(() => {
    let alive = true;
    fetch(`${import.meta.env.BASE_URL}data/topics/index.json`).then(r => { if (!r.ok) throw new Error(String(r.status)); return r.json(); })
      .then(raw => { if (alive) setIndex(normalizeTopicIndex(raw)); })
      .catch(() => { if (alive) setError('토픽 색인을 불러오지 못했습니다.'); });
    return () => { alive = false; };
  }, []);
  useEffect(() => {
    // Links and back/forward change ?r= / ?i= / ?q= without remounting the page.
    const changed = () => { const next = readSelection(); setSelectionState(next); if (next.kind === 'topic') { setSearchMode('topic'); setTopicQuery(next.q); } };
    window.addEventListener('hashchange', changed);
    return () => window.removeEventListener('hashchange', changed);
  }, []);
  useEffect(() => {
    const key = (event: KeyboardEvent) => { if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') { event.preventDefault(); input.current?.focus(); setOpen(true); } };
    window.addEventListener('keydown', key);
    return () => window.removeEventListener('keydown', key);
  }, []);

  const topicById = useMemo(() => new Map((index?.researchers || []).map(r => [r.id, r])), [index]);
  const selectedId = selection.kind === 'researcher' ? selection.id : null;
  const selectedBase = selectedId ? topicById.get(selectedId) || null : null;
  useEffect(() => {
    // Sharded releases keep info flow and summaries per researcher; fetch the shard once when opened.
    if (!selectedBase?.detail || details.has(selectedBase.id)) return;
    let alive = true;
    const base = selectedBase;
    fetch(`${import.meta.env.BASE_URL}data/topics/${base.detail}`).then(r => { if (!r.ok) throw new Error(String(r.status)); return r.json(); })
      .then(raw => { if (alive) setDetails(prev => new Map(prev).set(base.id, normalizeTopicDetail(raw, base))); })
      .catch(() => { if (alive) setDetails(prev => new Map(prev).set(base.id, 'error')); });
    return () => { alive = false; };
  }, [selectedBase, details]);
  useEffect(() => {
    if (!titles || !selectedId) return;
    let alive = true;
    titles(selectedId).then(rows => { if (alive) setPaperTitles({ id: selectedId, rows }); });
    return () => { alive = false; };
  }, [titles, selectedId]);
  const professorById = useMemo(() => new Map(professors.map(p => [p.id, p])), [professors]);
  const entries = useMemo<QueryEntry[]>(() => {
    const list: QueryEntry[] = professors.map(p => {
      const school = canonicalSchool(p.current_institution);
      return { id: p.id, name: names?.[p.id] || null, alias: null, subject: p.subject, institution: school,
        institutionText: `${institutionSearchText(p.current_institution)} ${institutionDisplayName(p.current_institution)} ${p.department || ''}`,
        otherText: Object.values(researcherTexts(p, null, areas?.profiles.get(p.id))).join(' '), hasTopics: topicById.has(p.id) };
    });
    for (const r of index?.researchers || []) if (!professorById.has(r.id)) list.push({ id: r.id, name: null, alias: r.alias, subject: r.subject, institution: r.institution, institutionText: r.institution || '', hasTopics: true });
    return list;
  }, [professors, names, index, topicById, professorById, areas]);
  const visibleEntries = useMemo(() => subject ? entries.filter(e => e.subject === subject) : entries, [entries, subject]);
  const results = useMemo(() => queryResearchers(visibleEntries, query, SUBJECTS), [visibleEntries, query]);
  const options = [...results.institutions.map(i => ({ kind: 'institution' as const, key: i.key })), ...results.researchers.map(r => ({ kind: 'researcher' as const, id: r.id }))];
  const labelFor = (id: string) => names?.[id] || topicById.get(id)?.alias || id;
  const entryById = useMemo(() => new Map(entries.map(e => [e.id, e])), [entries]);
  const activeTopicQuery = selection.kind === 'topic' ? selection.q : '';
  const topicResults = useMemo(() => index ? searchTopics(index, activeTopicQuery) : null, [index, activeTopicQuery]);
  const subjectHits = useMemo(() => (topicResults?.hits || []).filter(h => !subject || h.researcher.subject === subject), [topicResults, subject]);
  const chosenHits = useMemo(() => subjectHits.slice(0, 12).filter(h => !excluded.has(`${h.researcher.id}:${h.topic.id}`)), [subjectHits, excluded]);
  const labelForStable = useMemo(() => (id: string) => names?.[id] || index?.researchers.find(r => r.id === id)?.alias || id, [names, index]);
  const cloud = useMemo(() => index ? tagCloud(index, 22) : [], [index]);
  function runTopicSearch(q: string) { setTopicQuery(q); setExcluded(new Set()); select(q.trim() ? { kind: 'topic', q: q.trim() } : { kind: 'none' }); }

  if (error) return <section className="tp-page"><p className="tp-empty" role="alert">{error}</p></section>;
  if (!index) return <section className="tp-page"><p className="tp-empty" aria-live="polite">토픽 색인을 불러오는 중입니다.</p></section>;

  const withTopics = index.researchers.filter(r => !subject || r.subject === subject);
  // Card paging restarts whenever the field filter or the selection changes.
  const pageKey = `${subject}|${JSON.stringify(selection)}`;
  const shown = paging.key === pageKey ? paging.n : PAGE;
  const more = () => setPaging({ key: pageKey, n: shown + PAGE });
  const detail = selectedBase ? details.get(selectedBase.id) : undefined;
  const researcher = selectedBase ? withDetail(selectedBase, detail && detail !== 'error' ? detail : null) : null;
  const detailPending = Boolean(selectedBase?.detail) && detail === undefined;
  const recipComputed = index.method.recip !== 'not_computed';
  const researcherTitles = titles && paperTitles && researcher && paperTitles.id === researcher.id ? paperTitles.rows : null;
  const selectedEntry = selection.kind === 'researcher' ? entryById.get(selection.id) : null;
  const institutionMembers = selection.kind === 'institution' ? visibleEntries.filter(e => e.institution === selection.key) : [];
  const totalPapers = index.researchers.reduce((s, r) => s + r.papers.length, 0);

  function onKey(event: React.KeyboardEvent) {
    if (!options.length) return;
    if (event.key === 'ArrowDown') { event.preventDefault(); setActive(a => (a + 1) % options.length); }
    if (event.key === 'ArrowUp') { event.preventDefault(); setActive(a => (a - 1 + options.length) % options.length); }
    if (event.key === 'Enter') { event.preventDefault(); select(options[Math.min(active, options.length - 1)]); }
    if (event.key === 'Escape') setOpen(false);
  }

  return <section className="tp-page" aria-labelledby="tp-title">
    <header className="tp-hero">
      <div>
        <span className="v2-kicker">Topic alluvial · {releaseYear}</span>
        <h1 id="tp-title">연구 토픽 흐름</h1>
        <p>교수별 논문을 공유 참고문헌으로 클러스터링한 토픽을 연도·경력 시기 축에 배치합니다. 토픽의 생성 시점, 모토픽, 연도별 논문 수를 표시합니다. 토픽 이름과 특징어는 c-TF-IDF 영문 용어이고, 토픽 요약은 대표 논문에서 생성했습니다. 검색: 소속 기관·익명 ID·토픽 키워드(영문, 한국어 검색어는 용어집으로 영문 변환), 이름은 잠금 해제 후.</p>
      </div>
      <div className="v2-stats">
        <div className="v2-stat"><span>토픽 데이터 연구자</span><strong>{n(index.researchers.length)}</strong><small>전체 {n(professors.length)}명 중</small></div>
        <div className="v2-stat"><span>클러스터링 논문</span><strong>{n(totalPapers)}</strong><small>동명이인 제외 후</small></div>
      </div>
    </header>
    {index.source === 'demo' && <p className="tp-demo" role="note"><b>예시 데이터</b>현재 화면의 토픽 흐름은 화면 검토용 합성 데이터입니다(ID DEMO-…). 실제 연구자·기관·논문이 아니며, 공개 릴리스로 교체되면 이 표시가 사라집니다.</p>}

    <div className="tp-mode v2-seg" role="group" aria-label="검색 대상">
      <button type="button" className={searchMode === 'people' ? 'is-on' : ''} aria-pressed={searchMode === 'people'} onClick={() => setSearchMode('people')}>연구자 · 기관</button>
      <button type="button" className={searchMode === 'topic' ? 'is-on' : ''} aria-pressed={searchMode === 'topic'} onClick={() => setSearchMode('topic')}>토픽 · 키워드</button>
    </div>
    {searchMode === 'topic' ? <div className="tp-query">
      <form className="tp-search" onSubmit={e => { e.preventDefault(); runTopicSearch(topicQuery); }} role="search">
        <label className="tp-search-input"><span aria-hidden="true">⌕</span>
          <input value={topicQuery} onChange={e => setTopicQuery(e.target.value)} aria-label="토픽 키워드 검색 (영문, 한국어 검색어 지원)" placeholder="토픽·키워드 검색 — 예: epidemic spreading, optimal transport, 동기화" />
          <button type="submit" className="v2-button v2-button-dark tp-search-go">검색</button></label>
      </form>
      <div className="v2-seg" role="group" aria-label="분야">
        {['', ...Object.keys(SUBJECTS)].map(key => <button type="button" key={key || 'all'} className={subject === key ? 'is-on' : ''} aria-pressed={subject === key} onClick={() => setSubject(key)}>{key ? SUBJECTS[key] : '전체'}</button>)}
      </div>
    </div> : <div className="tp-query">
      <div className={`tp-search ${open && query ? 'is-open' : ''}`}>
        <label className="tp-search-input"><span aria-hidden="true">⌕</span>
          <input ref={input} value={query} role="combobox" aria-expanded={open && Boolean(query)} aria-controls="tp-results" aria-autocomplete="list"
            aria-label="연구자 이름, 소속 기관, 익명 ID 검색" placeholder={names ? '교수 이름, 소속 기관, 익명 ID' : '소속 기관 또는 익명 ID (이름 검색은 잠금 해제 후)'}
            onChange={e => { setQuery(e.target.value); setOpen(true); setActive(0); }} onFocus={() => setOpen(true)} onBlur={() => setTimeout(() => setOpen(false), 120)} onKeyDown={onKey} />
          <kbd>⌘K</kbd></label>
        {open && query && <div className="tp-results" id="tp-results" role="listbox">
          {!options.length && <p className="tp-results-empty">일치하는 연구자나 기관이 없습니다.</p>}
          {results.institutions.length > 0 && <b>기관</b>}
          {results.institutions.map((inst, i) => <button type="button" role="option" aria-selected={active === i} key={inst.key} className={active === i ? 'is-active' : ''} onMouseDown={() => select({ kind: 'institution', key: inst.key })}>
            <i>기</i><span>{institutionName(inst.key)}<small>토픽 데이터 {n(inst.withTopics)}명</small></span><em>{n(inst.count)}명</em></button>)}
          {results.researchers.length > 0 && <b>연구자</b>}
          {results.researchers.map((r, j) => { const i = results.institutions.length + j; return <button type="button" role="option" aria-selected={active === i} key={r.id} className={active === i ? 'is-active' : ''} onMouseDown={() => select({ kind: 'researcher', id: r.id })}>
            <i>{(SUBJECTS[r.subject] || r.subject).slice(0, 1)}</i><span>{labelFor(r.id)}{labelFor(r.id) !== r.id && <code>{r.id}</code>}<small>{institutionName(r.institution)} · {SUBJECTS[r.subject] || r.subject}</small></span>
            <em className={r.hasTopics ? 'is-ready' : ''}>{r.hasTopics ? `토픽 ${topicById.get(r.id)?.topics.length}` : '준비 중'}</em></button>; })}
        </div>}
      </div>
      <div className="v2-seg" role="group" aria-label="분야">
        {['', ...Object.keys(SUBJECTS)].map(key => <button type="button" key={key || 'all'} className={subject === key ? 'is-on' : ''} aria-pressed={subject === key} onClick={() => setSubject(key)}>{key ? SUBJECTS[key] : '전체'}</button>)}
      </div>
    </div>}
    {searchMode === 'topic' && <div className="tp-cloud" aria-label="특징어">{cloud.map(c => <button type="button" key={c.tag} onClick={() => runTopicSearch(c.tag)}>{c.tag}<small>{c.count}</small></button>)}</div>}

    {selection.kind !== 'none' && selection.kind !== 'topic' && <nav className="tp-crumbs" aria-label="현재 위치"><button type="button" onClick={() => select({ kind: 'none' })}>전체</button><span>/</span>
      {selection.kind === 'institution' ? <strong>{institutionName(selection.key)}</strong> : <>
        {selectedEntry?.institution && <><button type="button" onClick={() => select({ kind: 'institution', key: selectedEntry.institution! })}>{institutionName(selectedEntry.institution)}</button><span>/</span></>}
        <strong>{labelFor(selection.id)}</strong></>}</nav>}

    {selection.kind === 'topic' && topicResults && <section className="tp-detail" aria-label="토픽 검색 결과">
      <div className="tp-section-head"><div><h2>“{selection.q}” 토픽을 하는 연구자</h2>
        <p>{topicResults.method === 'semantic' ? '의미 검색 (LSA 코사인 0.55 + 태그 일치 0.45)' : '태그 일치'} · 질의어 {topicResults.expanded.slice(0, 8).join(', ') || '—'} · 결과 {n(subjectHits.length)}개 토픽</p></div>
        <div className="tp-controls"><div className="v2-seg" role="group" aria-label="겹쳐 보기 방식">
          <button type="button" className={multiMode === 'stack' ? 'is-on' : ''} aria-pressed={multiMode === 'stack'} onClick={() => setMultiMode('stack')}>스택</button>
          <button type="button" className={multiMode === 'overlay' ? 'is-on' : ''} aria-pressed={multiMode === 'overlay'} onClick={() => setMultiMode('overlay')}>오버랩</button></div></div></div>
      {subjectHits.length ? <>
        <section className="tp-chart-card"><div className="tp-chart-bar"><div><h3>연도별 논문 수 · {multiMode === 'stack' ? '연구자별 레인' : '연구자별 색 누적'}</h3><p>각 연구자의 토픽은 따로 클러스터링한 결과입니다. 같은 질의에 걸린 토픽을 같은 연도축에 놓은 비교이며, 공통 토픽 축이 아닙니다.</p></div></div>
          <MultiChart hits={chosenHits} mode={multiMode} labelFor={labelForStable} /></section>
        <div className="tp-panel"><h3>일치한 토픽 <small>상위 12개 중 선택</small></h3><ol className="tp-hits">{subjectHits.slice(0, 12).map(hit => { const key = `${hit.researcher.id}:${hit.topic.id}`; return <li key={key}>
          <label><input type="checkbox" checked={!excluded.has(key)} onChange={() => setExcluded(prev => { const next = new Set(prev); if (next.has(key)) next.delete(key); else next.add(key); return next; })} />
            <span><b>{hit.topic.label}</b><small>{labelFor(hit.researcher.id)} · {institutionName(hit.researcher.institution)} · {hit.topic.size}편</small>
              <span className="tp-tags">{hit.matched.map(tag => <em key={tag} className="is-hit">{tag}</em>)}{hit.topic.keywords.slice(0, 3).filter(k => !hit.matched.includes(k)).map(k => <em key={k}>{k}</em>)}</span></span></label>
          <span className="tp-score" title={`LSA ${hit.semanticScore.toFixed(2)} · 태그 ${hit.tagScore.toFixed(2)}`}>{hit.score.toFixed(2)}</span>
          <button type="button" className="v2-button" onClick={() => select({ kind: 'researcher', id: hit.researcher.id })}>열기</button></li>; })}</ol></div>
      </> : <p className="tp-empty">일치하는 토픽이 없습니다. 다른 표현이나 영어 키워드로 검색해 보세요.</p>}
    </section>}

    {selection.kind === 'researcher' && researcher && (() => {
      const range = yearRange(researcher)!;
      const independent = researcher.topics.filter(t => !t.parent && !t.misc).length;
      const branched = researcher.topics.filter(t => t.parent && !t.misc).length;
      return <article className="tp-detail">
        <header className="tp-profile">
          <div><span className="tp-chip">{SUBJECTS[researcher.subject] || researcher.subject}</span>
            <h2>{labelFor(researcher.id)}</h2>
            <p>{institutionName(researcher.institution)}{labelFor(researcher.id) !== researcher.id && <code>{researcher.id}</code>}</p>
            <ol className="tp-eras">{researcher.eras.map((era, i) => <li key={i}>{era.label}</li>)}</ol>
          </div>
          {professorById.has(researcher.id) && <button type="button" className="v2-button" onClick={() => onOpenCareer(researcher.id)}>경력·생산성 보기 →</button>}
        </header>
        <div className={`v2-stats ${recipComputed ? 'v2-stats-4' : ''}`}>
          <div className="v2-stat"><span>논문</span><strong>{n(researcher.papers.length)}</strong><small>{researcher.counts?.source_works ? `원본 ${n(researcher.counts.source_works)}건에서 판별` : '판별 후 고유 논문'}</small></div>
          <div className="v2-stat"><span>토픽</span><strong>{researcher.topics.length}</strong><small>독립 신규 {independent} · 분기 {branched}{researcher.topics.some(t => t.misc) ? ' · 기타 1' : ''}</small></div>
          <div className="v2-stat"><span>활동 기간</span><strong>{range[1] - range[0] + 1}<em>년</em></strong><small>{range[0]} – {range[1]}</small></div>
          {recipComputed && <div className="v2-stat"><span>ABA 경로</span><strong>{researcher.recip.length}</strong><small>피인용 상위 표본</small></div>}
        </div>
        <section className="tp-chart-card" aria-label="토픽 흐름 다이어그램">
          <div className="tp-chart-bar">
            <div><h3>토픽 흐름</h3><p>띠 두께 = {mode === 'year' ? '그 해' : '그 시기'} 논문 수 · 점선 = 모토픽에서의 분기 · 가는 선 = 논문 없는 해</p></div>
            <div className="tp-controls">
              <div className="v2-seg" role="group" aria-label="시간 단위">
                <button type="button" className={mode === 'year' ? 'is-on' : ''} aria-pressed={mode === 'year'} onClick={() => setMode('year')}>연도</button>
                <button type="button" className={mode === 'era' ? 'is-on' : ''} aria-pressed={mode === 'era'} onClick={() => setMode('era')}>경력 시기</button>
              </div>
              {recipComputed && <label className="v2-switch"><input type="checkbox" checked={showArcs} onChange={e => setShowArcs(e.target.checked)} /><span />ABA 경로</label>}
              <button type="button" className="v2-btn-quiet" onClick={() => chartSvg.current && printSvgAsPdf(chartSvg.current, chartMeta(researcher))}>PDF 저장</button>
              <button type="button" className="v2-btn-quiet" onClick={() => chartSvg.current && downloadSvg(chartSvg.current, chartMeta(researcher).filename)}>SVG 저장</button>
            </div>
          </div>
          <AlluvialChart researcher={researcher} mode={mode} showArcs={showArcs && recipComputed} focus={focus} setFocus={setFocus} titles={researcherTitles} svgRef={chartSvg} />
        </section>
        {detailPending ? <p className="tp-muted" aria-live="polite">분기·합류 정보량과 토픽 요약을 불러오는 중입니다.</p>
          : detail === 'error' ? <p className="tp-muted" role="alert">분기·합류 정보량과 토픽 요약을 불러오지 못했습니다.</p>
          : <InfoFlowPanel key={researcher.id} researcher={researcher} />}
        <ResearchAreaTree profile={areas?.profiles.get(researcher.id)} title="OpenAlex 연구분야 계층" />
        <section className="tp-split">
          <div className="tp-panel"><h3>토픽과 분기</h3><TopicTable researcher={researcher} focus={focus} setFocus={setFocus} /></div>
          <div className="tp-panel tp-notes"><h3>읽는 법과 한계</h3><ul>
            <li><b>토픽</b> 공유 참고문헌 양을 코사인 정규화한 가중 Louvain 군집입니다. 이름은 c-TF-IDF 영문 특징어이고, 작은 군집은 ‘Other’로 묶습니다.</li>
            {researcher.topics.some(t => t.summary) && <li><b>요약</b> 토픽별 대표 논문의 제목·초록·출판일을 Claude가 읽고 주제와 시기별 전개를 요약했습니다. 논문 제목을 그대로 옮긴 요약은 싣지 않습니다.</li>}
            <li><b>분기</b> 새 토픽의 탄생기 논문과 그 이전 논문 사이 coupling 최댓값으로 모토픽을 정합니다. 연결이 없으면 독립 신규로 표시합니다.</li>
            {recipComputed && <li><b>ABA 경로</b> 본인이 저자가 아닌 논문이 초기 논문을 인용하고 후기 논문이 그것을 다시 인용한 경우입니다. 피인용 상위 표본이며 전수가 아닙니다.</li>}
            <li><b>동명이인</b> KOAD 경력 연속성 판별을 통과한 논문만 씁니다. 국내 학회지·단행본·학위논문은 OpenAlex 수록이 불균일합니다.</li>
            {researcher.fetched_at && <li><b>수집일</b> {researcher.fetched_at}</li>}
          </ul></div>
        </section>
      </article>;
    })()}

    {selection.kind === 'researcher' && !researcher && <article className="tp-detail"><div className="tp-pending">
      <h2>{labelFor(selection.id)}</h2>
      <p>{selectedEntry ? `${institutionName(selectedEntry.institution)} · ${SUBJECTS[selectedEntry.subject] || selectedEntry.subject}` : '공개 모집단에 없는 ID입니다.'}</p>
      <p className="tp-muted">이 연구자의 토픽 클러스터링은 아직 공개 색인에 없습니다. 데이터가 업로드되면 같은 주소에서 바로 보입니다.</p>
      {professorById.has(selection.id) && <button type="button" className="v2-button" onClick={() => onOpenCareer(selection.id)}>경력·생산성 보기 →</button>}
    </div></article>}

    {selection.kind === 'institution' && <section className="tp-grid-section">
      <div className="tp-section-head"><h2>{institutionName(selection.key)}</h2><p>{n(institutionMembers.length)}명 중 토픽 데이터 {n(institutionMembers.filter(m => m.hasTopics).length)}명</p></div>
      <div className="tp-grid">{institutionMembers.filter(m => m.hasTopics).slice(0, shown).map(m => <ResearcherCard key={m.id} researcher={topicById.get(m.id)!} label={labelFor(m.id)} onOpen={() => select({ kind: 'researcher', id: m.id })} />)}</div>
      {institutionMembers.filter(m => m.hasTopics).length > shown && <button type="button" className="v2-button tp-more" onClick={more}>더 보기 ({n(shown)} / {n(institutionMembers.filter(m => m.hasTopics).length)})</button>}
      {institutionMembers.some(m => !m.hasTopics) && <details className="tp-waiting"><summary>토픽 데이터 준비 중 {n(institutionMembers.filter(m => !m.hasTopics).length)}명</summary>
        <div>{institutionMembers.filter(m => !m.hasTopics).slice(0, 120).map(m => <button type="button" key={m.id} onClick={() => select({ kind: 'researcher', id: m.id })}>{labelFor(m.id)}<small>{SUBJECTS[m.subject] || m.subject}</small></button>)}</div></details>}
    </section>}

    {selection.kind === 'none' && <section className="tp-grid-section">
      <div className="tp-section-head"><h2>토픽 데이터가 있는 연구자</h2><p>{n(withTopics.length)}명 · 카드의 작은 그림은 연도별 토픽 띠입니다</p></div>
      {withTopics.length ? <div className="tp-grid">{withTopics.slice(0, shown).map(r => <ResearcherCard key={r.id} researcher={r} label={labelFor(r.id)} onOpen={() => select({ kind: 'researcher', id: r.id })} />)}</div>
        : <p className="tp-empty">이 분야에는 아직 토픽 데이터가 없습니다.</p>}
      {withTopics.length > shown && <button type="button" className="v2-button tp-more" onClick={more}>더 보기 ({n(shown)} / {n(withTopics.length)})</button>}
    </section>}
  </section>;
}
