import { useEffect, useMemo, useRef, useState } from 'react';
import type { Professor } from './types';
import { buildResearcherTrajectory, findTrajectoryPeers, type ResearcherRecord, type Hypergraph, type HypergraphLayout } from './constellation/hypergraph';
import './constellation.css';
import TrajectoryPanel from './TrajectoryPanel';
import { bubbleEnvelope } from './constellation/envelope';

const W = 1400, H = 1000;
const subjects: Record<string, string> = { mathematics: '수학', physics: '물리', chemistry: '화학', biology: '생물' };
const colors: Record<string, string> = { mathematics: '#8662b5', physics: '#287dba', chemistry: '#d99338', biology: '#269686' };
type Result = { graph: Hypergraph; layout: HypergraphLayout };
type Camera = { x: number; y: number; scale: number };
const initialCamera: Camera = { x: W / 2, y: H / 2, scale: 1 };

export default function Constellation({ professors, names, releaseYear, onSelect, initialSelectedId = '' }: {
  initialSelectedId?: string; professors: Professor[]; names: Record<string, string> | null; releaseYear: number; onSelect: (id: string) => void;
}) {
  const [subject, setSubject] = useState('');
  const [scope, setScope] = useState<'institution' | 'researcher'>(initialSelectedId ? 'researcher' : 'institution');
  const [institution, setInstitution] = useState(() => { const counts = new Map<string, number>(); professors.forEach(p => { const value = p.phd_institution_canonical || p.phd_institution; if (value && !/^\d+$/.test(value)) counts.set(value, (counts.get(value) || 0) + 1); }); return [...counts].sort((a,b) => b[1]-a[1])[0]?.[0] || ''; });
  const [level, setLevel] = useState<'phd' | 'bachelor'>('phd');
  const [spatial, setSpatial] = useState(true), [temporal, setTemporal] = useState(true);
  const [years, setYears] = useState(5), [includeEstimated, setIncludeEstimated] = useState(true);
  const [balance, setBalance] = useState(35), [spacing, setSpacing] = useState(14);
  const [bachelorTime, setBachelorTime] = useState(false), [cohortEnabled, setCohortEnabled] = useState(true);
  const [includeInferredDepartments, setIncludeInferredDepartments] = useState(true);
  const [rosterPage, setRosterPage] = useState(0);
  const [query, setQuery] = useState(''), [selectedId, setSelectedId] = useState(initialSelectedId);
  const [hoverId, setHoverId] = useState(''), [selectedEdge, setSelectedEdge] = useState('');
  const [storedResult, setResult] = useState<(Result & { requestKey: string }) | null>(null);
  const [status, setStatus] = useState('연결을 계산하고 있습니다.'), [error, setError] = useState('');
  const [camera, setCamera] = useState<Camera>(initialCamera);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const drag = useRef<{ px: number; py: number; x: number; y: number; moved: boolean } | null>(null);
  const envelopes = useRef(new Map<string, Path2D>());
  const [size, setSize] = useState({ width: 1000, height: 700 });
  const allRecords = useMemo<ResearcherRecord[]>(() => professors.map(p => ({
    id: p.id, subject: p.subject, phd_institution: p.phd_institution_canonical || p.phd_institution,
    bachelor_institution: p.bachelor_institution_canonical || p.bachelor_institution, phd_year: p.phd_year,
    phd_country: p.phd_country, bachelor_country: p.bachelor_country,
    phd_department: p.phd_department, bachelor_department: p.bachelor_department,
    phd_department_inferred: p.phd_department_inferred, bachelor_department_inferred: p.bachelor_department_inferred,
    career: p.career.map(c => ({ stage: c.stage, start_year: c.start_year, end_year: c.end_year,
      is_estimated: c.is_estimated, institution: c.institution_canonical || c.institution,
      country: c.country, department: c.department, department_inferred: c.department_inferred })),
  })), [professors]);
  const trajectory = useMemo(() => findTrajectoryPeers(allRecords, selectedId, { includeEstimated, estimatedYears: years, includeInferredDepartments }), [allRecords, selectedId, includeEstimated, years, includeInferredDepartments]);
  const peerIds = useMemo(() => new Set([selectedId, ...trajectory.peers.map(p => p.id)]), [selectedId, trajectory]);

  const scopePeers = scope === 'researcher' ? peerIds : null;
  const scopeSelectedId = scope === 'researcher' ? selectedId : '';
  const filtered = useMemo(() => professors.filter(p => (!subject || p.subject === subject || (scope === 'researcher' && p.id === scopeSelectedId)) && (scope === 'researcher' ? !!scopeSelectedId && !!scopePeers?.has(p.id) : !!institution && (level === 'phd' ? p.phd_institution_canonical || p.phd_institution : p.bachelor_institution_canonical || p.bachelor_institution) === institution)), [professors, subject, scope, scopeSelectedId, scopePeers, institution, level]);
  const byId = useMemo(() => new Map(professors.map(p => [p.id, p])), [professors]);
  const graphRecords = useMemo(() => { const ids = new Set(filtered.map(p => p.id)); return allRecords.filter(p => ids.has(p.id)); }, [filtered, allRecords]);
  const institutions = useMemo(() => [...new Set(professors.filter(p => !subject || p.subject === subject).map(p => level === 'phd' ? p.phd_institution_canonical || p.phd_institution : p.bachelor_institution_canonical || p.bachelor_institution).filter((s): s is string => !!s && !/^\d+$/.test(s)))].sort(), [professors, subject, level]);

  const requestKey = useMemo(() => JSON.stringify({ records: graphRecords, scopeSelectedId, spatial, temporal, level, includeEstimated, includeInferredDepartments, years, balance, spacing, cohortEnabled, bachelorTime }), [graphRecords, scopeSelectedId, spatial, temporal, level, includeEstimated, includeInferredDepartments, years, balance, spacing, cohortEnabled, bachelorTime]);
  const result = storedResult?.requestKey === requestKey ? storedResult : null;
  const calculatedTrajectory = useMemo(() => { const record = allRecords.find(p => p.id === selectedId); return record ? buildResearcherTrajectory(record, { includeEstimated, estimatedYears: years, includeInferredDepartments }) : null; }, [allRecords, selectedId, includeEstimated, years, includeInferredDepartments]);

  const label = (id: string) => names?.[id] || id;
  const selected = byId.get(selectedId);
  const focusId = hoverId || selectedId;

  useEffect(() => {
    const element = canvasRef.current;
    if (!element) return;
    const observer = new ResizeObserver(([entry]) => setSize({ width: entry.contentRect.width, height: entry.contentRect.height }));
    observer.observe(element);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    const worker = new Worker(new URL('./constellation/layout.worker.ts', import.meta.url), { type: 'module' });
    let active = true;
    worker.onmessage = ({ data }) => {
      if (!active) return;
      if (data.type === 'error') { setError('별자리를 계산하지 못했습니다. 조건을 바꾸거나 새로고침해 주세요.'); setStatus(''); }
      if (data.type === 'result') { envelopes.current.clear(); setResult({ ...data.result, requestKey }); setStatus(''); setError(''); setCamera(initialCamera); }
    };
    worker.onerror = () => { setError('계산 도구를 불러오지 못했습니다. 새로고침해 주세요.'); setStatus(''); };
    worker.postMessage({
      // Only public, anonymous fields cross into the layout worker.
      records: graphRecords, selectedId: scopeSelectedId,
      options: { spatialEnabled: spatial, temporalEnabled: temporal, institutionLevel: level,
        includeEstimated, includeInferredDepartments, cohortEnabled, bachelorTemporalEnabled: bachelorTime, bachelorStartOffset: 10, bachelorEndOffset: 8, estimatedYears: years, spatialWeight: (100 - balance) / 100, temporalWeight: balance / 100 },
      layout: { width: W, height: H, padding: 55, minDistance: spacing, chronologicalStrength: .45, iterations: 100, restarts: 3 },
    });
    return () => { active = false; worker.terminate(); };
  }, [graphRecords, scopeSelectedId, spatial, temporal, level, includeEstimated, includeInferredDepartments, years, balance, spacing, cohortEnabled, bachelorTime, requestKey]);

  function recompute(action: () => void) { setStatus('연결과 노드 간격을 최적화하고 있습니다.'); setResult(null); setError(''); setHoverId(''); if (scope !== 'researcher') setSelectedId(''); setSelectedEdge(''); setRosterPage(0); action(); }
  const index = useMemo(() => new Map(result?.graph.nodes.map((n, i) => [n.id, i]) || []), [result]);
  const activeEdges = useMemo(() => {
    if (!result) return [];
    if (selectedEdge) return result.graph.edges.filter(edge => edge.id === selectedEdge);
    const i = index.get(selectedId);
    if (i === undefined) return [];
    const edges = result.graph.edges.filter(edge => edge.members.includes(i)).sort((a,b) => (a.kind === 'temporal' ? 1 : 0) - (b.kind === 'temporal' ? 1 : 0) || a.members.length - b.members.length);
    return edges.slice(0, 1);
  }, [result, selectedEdge, selectedId, index]);
  const activeMembers = useMemo(() => new Set(activeEdges.flatMap(edge => edge.members)), [activeEdges]);
  const edgeList = useMemo(() => (selectedId && result
    ? result.graph.edges.filter(e => e.members.includes(index.get(selectedId) ?? -1)) : result?.graph.edges || [])
    .toSorted((a, b) => (a.kind === 'cohort' ? 0 : a.kind === 'spatial' ? 1 : 2) - (b.kind === 'cohort' ? 0 : b.kind === 'spatial' ? 1 : 2) || (a.years?.[0] ?? 0) - (b.years?.[0] ?? 0) || b.members.length - a.members.length), [result, index, selectedId]);
  const matches = useMemo(() => query.trim() ? professors.filter(p => (names?.[p.id] || p.id).toLocaleLowerCase().includes(query.trim().toLocaleLowerCase())).slice(0, 30) : [], [professors, names, query]);

  const roster = useMemo(() => {
    const edge = result?.graph.edges.find(e => e.id === selectedEdge);
    const ids = edge ? new Set(edge.members.map(i => result!.graph.nodes[i].id)) : null;
    return filtered.filter(p => !ids || ids.has(p.id)).toSorted((a, b) => (a.phd_year ?? 9999) - (b.phd_year ?? 9999) || a.id.localeCompare(b.id));
  }, [filtered, result, selectedEdge]);
  const page = Math.min(rosterPage, Math.max(0, Math.ceil(roster.length / 50) - 1));

  const fitScale = Math.min(size.width / W, size.height / H) * .94;
  const scale = fitScale * camera.scale;
  const project = (x: number, y: number) => ({ x: (x - camera.x) * scale + size.width / 2, y: (y - camera.y) * scale + size.height / 2 });

  useEffect(() => {
    const canvas = canvasRef.current;
    const ctx = canvas?.getContext('2d');
    if (!canvas || !ctx) return;
    const dpr = window.devicePixelRatio || 1;
    canvas.width = Math.round(size.width * dpr); canvas.height = Math.round(size.height * dpr);
    ctx.scale(dpr, dpr); ctx.fillStyle = '#fff'; ctx.fillRect(0, 0, size.width, size.height);
    if (!result) return;
    const positions = result.layout.positions.map(p => ({ x: (p.x - camera.x) * scale + size.width / 2, y: (p.y - camera.y) * scale + size.height / 2 }));
    const hasFocus = activeEdges.length > 0 || !!selectedId;
    activeEdges.forEach(edge => {
      let path = envelopes.current.get(edge.id);
      if (!path) {
        path = new Path2D(bubbleEnvelope(edge.members.map(i => result.layout.positions[i]), Math.max(13, spacing * 1.25)).path);
        if (envelopes.current.size > 60) envelopes.current.delete(envelopes.current.keys().next().value!);
        envelopes.current.set(edge.id, path);
      }
      ctx.save();
      ctx.translate(size.width / 2 - camera.x * scale, size.height / 2 - camera.y * scale); ctx.scale(scale, scale);
      ctx.fillStyle = edge.kind === 'spatial' ? '#256ef4' : edge.kind === 'temporal' ? '#d08a24' : '#347f65'; ctx.strokeStyle = ctx.fillStyle;
      ctx.globalAlpha = .12; ctx.fill(path, 'evenodd');
      ctx.globalAlpha = .8; ctx.lineWidth = (edge.id === selectedEdge ? 1.6 : .8) / scale;
      ctx.setLineDash(edge.kind === 'temporal' ? [5 / scale, 3 / scale] : []); ctx.stroke(path); ctx.restore();
    });

    ctx.setLineDash([]);
    result.graph.nodes.forEach((node, i) => {
      const p = positions[i];
      if (p.x < -15 || p.y < -15 || p.x > size.width + 15 || p.y > size.height + 15) return;
      const focused = node.id === focusId;
      ctx.globalAlpha = hasFocus && !activeMembers.has(i) && !focused ? .15 : .88;
      ctx.fillStyle = colors[node.subject] || '#607284';
      const baseRadius = result.graph.nodes.length < 80 ? Math.min(3.2, 2.2 * camera.scale) : Math.max(.8, Math.min(3.2, spacing * scale * .32));
      const radius = focused ? 5 : activeMembers.has(i) ? Math.max(2.2, baseRadius) : baseRadius;
      ctx.beginPath(); ctx.arc(p.x, p.y, radius, 0, Math.PI * 2); ctx.fill();
      if (focused) {
        ctx.strokeStyle = ctx.fillStyle; ctx.lineWidth = 1; ctx.globalAlpha = .35;
        ctx.beginPath(); ctx.arc(p.x, p.y, 9, 0, Math.PI * 2); ctx.stroke();
        ctx.globalAlpha = 1; ctx.font = '600 13px -apple-system, sans-serif';
        const text = names?.[node.id] || node.id, tw = ctx.measureText(text).width;
        const tx = Math.min(size.width - tw - 18, Math.max(8, p.x + 14)), ty = Math.max(22, p.y - 11);
        ctx.fillStyle = '#fff'; ctx.fillRect(tx - 5, ty - 15, tw + 10, 23);
        ctx.fillStyle = '#253846'; ctx.fillText(text, tx, ty);
      }
    });
    ctx.globalAlpha = 1;
  }, [result, size, camera, scale, names, focusId, activeEdges, activeMembers, spacing, selectedId, selectedEdge]);

  function hit(clientX: number, clientY: number) {
    const rect = canvasRef.current?.getBoundingClientRect();
    if (!rect || !result) return '';
    let nearest = '', distance = 13;
    result.layout.positions.forEach(p => { const screen = project(p.x, p.y), d = Math.hypot(screen.x - (clientX - rect.left), screen.y - (clientY - rect.top)); if (d < distance) { nearest = p.id; distance = d; } });
    return nearest;
  }
  function pick(id: string) { setSelectedId(id); setSelectedEdge(''); setHoverId(''); setRosterPage(0); }
  function selectEdge(id: string) {
    setSelectedEdge(id); setHoverId(''); setRosterPage(0);
    const edge = result?.graph.edges.find(e => e.id === id);
    if (edge && result) {
      const points = edge.members.map(i => result.layout.positions[i]);
      const minX = Math.min(...points.map(p => p.x)), maxX = Math.max(...points.map(p => p.x));
      const minY = Math.min(...points.map(p => p.y)), maxY = Math.max(...points.map(p => p.y));
      const zoom = Math.max(1, Math.min(6, Math.min(size.width / (maxX - minX + 90), size.height / (maxY - minY + 90)) / fitScale * .8));
      setCamera({ x: (minX + maxX) / 2, y: (minY + maxY) / 2, scale: zoom });
      canvasRef.current?.scrollIntoView({ block: 'center', behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'instant' : 'smooth' });
    }
  }
  function zoomTo(factor: number) { setCamera(c => ({ ...c, scale: Math.max(.5, Math.min(8, c.scale * factor)) })); }
  const estimatedCount = filtered.filter(p => p.phd_year && !p.career.some(c => c.stage === 'doctoral' && !c.is_estimated && c.start_year !== null && c.end_year !== null)).length;
  const missingCount = filtered.filter(p => !p.phd_year && !p.career.some(c => c.stage === 'doctoral' && c.start_year !== null && c.end_year !== null)).length;

  return <section className="atlas" aria-labelledby="atlas-title">
    <div className="atlas-heading"><div><div className="atlas-kicker">K–STEM ATLAS <span>/ {releaseYear}</span></div><h1 id="atlas-title">Career trajectory hypergraph</h1><p>학교 또는 연구자를 선택해 출신기관과 재학 시기가 일치하는 집단을 탐색합니다.</p></div><div className="atlas-count"><strong>{filtered.length.toLocaleString()}</strong><span>연구자 <i>·</i> {result?.graph.edges.length.toLocaleString() ?? '…'} 하이퍼엣지</span></div></div>
    <div className="atlas-scope"><div className="atlas-segment" role="group" aria-label="탐색 범위"><button className={scope === 'institution' ? 'selected' : ''} onClick={() => recompute(() => { setScope('institution'); setSelectedId(''); })}>학교별</button><button className={scope === 'researcher' ? 'selected' : ''} onClick={() => { setStatus('연구자를 선택해 주세요.'); setResult(null); setScope('researcher'); }}>연구자별</button></div>{scope === 'institution' ? <label>출신학교<select value={institution} onChange={e => recompute(() => setInstitution(e.target.value))}><option value="">학교를 선택하세요</option>{institutions.map(v => <option key={v}>{v}</option>)}</select></label> : <label>연구자 선택<select value={selectedId} onChange={e => { setStatus('일치하는 경로를 계산하고 있습니다.'); setResult(null); setSelectedId(e.target.value); setSelectedEdge(''); }}><option value="">연구자를 선택하세요</option>{professors.filter(p => !subject || p.subject === subject || p.id === selectedId).map(p => <option key={p.id} value={p.id}>{label(p.id)}</option>)}</select></label>}<p>{scope === 'institution' ? '선택한 학교의 연구자만 표시합니다.' : '선택 연구자와 기관·연도가 동시에 겹치는 연구자를 표시합니다.'}</p></div>
    <div className="atlas-workspace">
      <div className="atlas-map-column">
        <div className="atlas-map-toolbar"><div className="atlas-subjects" role="group" aria-label="연구 분야"><button className={!subject ? 'selected' : ''} onClick={() => recompute(() => { setSubject(''); })}>전체</button>{Object.entries(subjects).map(([key, name]) => <button key={key} className={subject === key ? 'selected' : ''} onClick={() => recompute(() => { setSubject(key); })}><i style={{ background: colors[key] }}/>{name}</button>)}</div><span className="atlas-map-caption">노드·묶음을 선택해 영역 표시</span></div>
        <div className="atlas-canvas-wrap">
          <canvas ref={canvasRef} className="atlas-canvas" aria-label={`연구자 ${filtered.length}명의 시간·출신기관 하이퍼그래프. 아래 검색과 연결 목록으로도 탐색할 수 있습니다.`}
            tabIndex={0} onKeyDown={e => { if (['+', '=', '-', '0', 'Escape', 'ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown'].includes(e.key)) e.preventDefault(); if (e.key === '+' || e.key === '=') zoomTo(1.3); if (e.key === '-') zoomTo(1 / 1.3); if (e.key === '0') setCamera(initialCamera); if (e.key === 'Escape') { pick(''); setSelectedEdge(''); } const dx = e.key === 'ArrowLeft' ? -60 : e.key === 'ArrowRight' ? 60 : 0, dy = e.key === 'ArrowUp' ? -60 : e.key === 'ArrowDown' ? 60 : 0; if (dx || dy) setCamera(c => ({ ...c, x: c.x + dx / scale, y: c.y + dy / scale })); }}
            onWheel={e => { if (e.ctrlKey || e.metaKey) zoomTo(e.deltaY > 0 ? .9 : 1.1); }}
            onPointerDown={e => { drag.current = { px: e.clientX, py: e.clientY, x: camera.x, y: camera.y, moved: false }; e.currentTarget.setPointerCapture(e.pointerId); }}
            onPointerMove={e => { if (drag.current) { const dx = e.clientX - drag.current.px, dy = e.clientY - drag.current.py; if (Math.hypot(dx, dy) > 4) drag.current.moved = true; if (drag.current.moved) setCamera(c => ({ ...c, x: drag.current!.x - dx / scale, y: drag.current!.y - dy / scale })); } else setHoverId(hit(e.clientX, e.clientY)); }}
            onPointerUp={e => { if (drag.current && !drag.current.moved) { pick(hit(e.clientX, e.clientY)); } drag.current = null; }} onPointerCancel={() => { drag.current = null; }} onPointerLeave={() => setHoverId('')}/>
          {(status || error || !result || !filtered.length) && <div className="atlas-map-status" role="status">{error || (filtered.length ? status || '연결과 노드 간격을 계산하고 있습니다.' : scope === 'researcher' && !selectedId ? '위에서 연구자를 선택하세요.' : !institution ? '위에서 학교를 선택하세요.' : '현재 학교·분야에 일치하는 연구자가 없습니다.')}{status && !error && <span>익명 공개 데이터로 계산 중</span>}</div>}
          <div className="atlas-map-index" aria-hidden="true">{String(filtered.length).padStart(4, '0')} NODES<br/><span>TIME × INSTITUTION</span></div>
          <div className="atlas-map-controls"><button onClick={() => zoomTo(1.35)} aria-label="별자리 확대">+</button><button onClick={() => zoomTo(1 / 1.35)} aria-label="별자리 축소">−</button><button onClick={() => setCamera(initialCamera)} aria-label="별자리 전체 보기">↗</button></div>
          <div className="atlas-scale">{Math.round(camera.scale * 100)}% <span>드래그 이동 · + / − 확대 · 0 전체</span></div>
        </div>
        <div className="atlas-map-footer">{scope === 'institution' ? <><span><i className="atlas-line spatial"/>같은 출신기관</span><span><i className="atlas-line temporal"/>겹치는 박사과정 시기</span></> : <span><i className="atlas-line cohort"/>같은 기관·연도의 경력</span>}<span>굴곡진 영역: 선택한 연결 묶음</span><button onClick={() => { pick(''); setSelectedEdge(''); }}>선택 해제</button></div>
      </div>
      <aside className="atlas-sidebar" aria-label="별자리 탐색 조건">
        <div className="atlas-sidebar-section"><h2>연결을 따라가기 <span>01</span></h2><label className="atlas-search-label" htmlFor="atlas-search">{names ? '연구자 이름 또는 익명 ID' : '익명 연구자 ID 검색'}</label><div className="atlas-search"><span aria-hidden="true">⌕</span><input id="atlas-search" value={query} onChange={e => setQuery(e.target.value)} placeholder={names ? '이름 또는 Prof ID' : 'Prof ID를 입력하세요'} autoComplete="off"/></div>
          {query && <div className="atlas-search-results" role="region" aria-label="연구자 검색 결과">{matches.length ? matches.map(p => <button key={p.id} onClick={() => { setScope('researcher'); setStatus('일치하는 경로를 계산하고 있습니다.'); pick(p.id); setQuery(''); const pos = result?.layout.positions.find(n => n.id === p.id); if (pos) setCamera({ x: pos.x, y: pos.y, scale: 2 }); }}>{label(p.id)}<small>{subjects[p.subject]}</small></button>) : <p>일치하는 연구자가 없습니다.</p>}</div>}
          {scope === 'institution' && <label className="atlas-field">출신기관<select value={institution} onChange={e => recompute(() => setInstitution(e.target.value))}><option value="">학교를 선택하세요</option>{institutions.map(v => <option key={v}>{v}</option>)}</select></label>}
        </div>
        <div className="atlas-sidebar-section"><h2>어떤 연결을 볼까요 <span>02</span></h2>{scope === 'researcher' && <p className="atlas-quiet">박사·포닥·교수 경력에서 기관과 연도가 동시에 일치하는 묶음입니다.</p>}<fieldset className="atlas-degree-controls" disabled={scope === 'researcher'}><label className="atlas-switch"><span><i className="atlas-line spatial"/><b>공간적 일치</b><small>국내 학교+학과 · 국외 학교</small></span><input type="checkbox" checked={spatial} onChange={e => recompute(() => setSpatial(e.target.checked))}/></label><div className="atlas-segment" role="group" aria-label="출신기관 학위"><button className={level === 'phd' ? 'selected' : ''} onClick={() => recompute(() => { setLevel('phd'); setInstitution(''); })}>박사 출신</button><button className={level === 'bachelor' ? 'selected' : ''} onClick={() => recompute(() => { setLevel('bachelor'); setInstitution(''); })}>학부 출신</button></div>
          </fieldset><label className="atlas-check"><input type="checkbox" checked={includeInferredDepartments} onChange={e => recompute(() => setIncludeInferredDepartments(e.target.checked))}/>논문 소속으로 추정한 학과 포함</label><p className="atlas-quiet">국내 학과가 없으면 공간 연결에서 제외됩니다.</p>
          <fieldset className="atlas-degree-controls" disabled={scope === 'researcher'}><label className="atlas-switch"><span><i className="atlas-line temporal"/><b>시간적 일치</b><small>같은 해를 포함하는 박사과정 구간</small></span><input type="checkbox" checked={temporal} onChange={e => recompute(() => setTemporal(e.target.checked))}/></label>
          <label className="atlas-check"><input type="checkbox" checked={cohortEnabled} onChange={e => recompute(() => setCohortEnabled(e.target.checked))}/>같은 기관·시기의 코호트 묶음</label><label className="atlas-check"><input type="checkbox" checked={bachelorTime} onChange={e => recompute(() => setBachelorTime(e.target.checked))}/>학부 추정 시기 포함 (학위 10–8년 전)</label>
          </fieldset><label className="atlas-check"><input type="checkbox" checked={includeEstimated} onChange={e => recompute(() => setIncludeEstimated(e.target.checked))}/>학위연도 기반 추정 구간 포함</label>
          <label className="atlas-field atlas-years">추정 시작 <select value={years} disabled={!includeEstimated || (scope === 'institution' && !temporal)} onChange={e => recompute(() => setYears(Number(e.target.value)))}>{[3, 4, 5, 6, 7].map(y => <option key={y} value={y}>학위 취득 {y}년 전</option>)}</select></label>
        </div>
        <div className="atlas-sidebar-section"><h2>별자리 배치 <span>03</span></h2><label className="atlas-range">기관 ↔ 시간 비중 <output>{100 - balance} : {balance}</output><input type="range" min="10" max="90" step="5" value={balance} disabled={scope === 'researcher' || !spatial || !temporal} onChange={e => recompute(() => setBalance(Number(e.target.value)))}/></label><label className="atlas-range">노드 사이 여백 <output>{spacing}</output><input type="range" min="7" max="18" value={spacing} onChange={e => recompute(() => setSpacing(Number(e.target.value)))}/></label><p className="atlas-quiet">큰 집단의 영향과 반복되는 연결을 보정합니다.</p>{result && <p className="atlas-quiet">공간 연결 가능 {result.graph.diagnostics.spatialEligibleCount}명 · 국내 학과 미상 {result.graph.diagnostics.missingDepartmentCount}명 · 추정 학과 제외 {result.graph.diagnostics.excludedInferredDepartmentCount}명</p>}</div>
      </aside>
    </div>
    <div className="atlas-lower"><section className="atlas-selection"><div className="atlas-section-title"><h2>{selected ? label(selected.id) : '연구자와 연결 근거'}</h2>{selected && <button onClick={() => onSelect(selected.id)}>경력과 논문 보기 ↗</button>}</div>{selected ? <><p>{subjects[selected.subject] || selected.subject} · {selected.current_institution || '현재기관 미상'}</p><dl><div><dt>박사 출신기관</dt><dd>{selected.phd_institution || '정보 없음'}</dd></div><div><dt>박사 학위연도</dt><dd>{selected.phd_year || '정보 없음'}</dd></div><div><dt>연결 묶음</dt><dd>{edgeList.length}개</dd></div></dl></> : <p>노드를 선택하면 그 연구자가 속한 기관과 시기 묶음이 드러납니다. 같은 묶음의 모든 연구자를 하나의 하이퍼엣지로 잇습니다.</p>}
        <div className="atlas-disclosure"><strong>시간 연결은 재학 사실의 확인이 아닙니다.</strong><p>현재 선택에서 학위연도 기반 추정 대상 {estimatedCount.toLocaleString()}명, 기간 정보 없음 {missingCount.toLocaleString()}명. 추정 구간은 학위연도−{years}부터 학위연도까지이며 양 끝 연도를 포함합니다. 기관·시기의 일치는 친분이나 공동연구를 뜻하지 않습니다.</p></div>
      </section><section className="atlas-groups"><div className="atlas-section-title"><h2>{selected ? '이 연구자의 연결 묶음' : '연결 묶음 탐색'}</h2><span>{edgeList.length}개</span></div><div className="atlas-edge-list">{edgeList.slice(0, 40).map(edge => <button key={edge.id} className={selectedEdge === edge.id ? 'active' : ''} onClick={() => selectEdge(edge.id)}><i className={`atlas-line ${edge.kind}`}/><span>{edge.label}<small>{scope === 'researcher' ? '경력의 기관·연도 일치' : edge.kind === 'spatial' ? (level === 'phd' ? '박사 출신기관' : '학부 출신기관') : edge.kind === 'temporal' ? '공통 재학 추정 시기' : '같은 기관·시기 코호트'}</small></span><b>{edge.members.length}<small>명</small></b></button>)}{edgeList.length > 40 && <p className="atlas-quiet">코호트·시간 순으로 40개 묶음 표시 · 노드 선택으로 개별 연결 탐색</p>}{!edgeList.length && <p className="atlas-quiet">현재 조건에 두 명 이상이 공유하는 연결이 없습니다.</p>}</div></section></div>
    <details className="atlas-roster"><summary>{selectedEdge ? '선택한 하이퍼엣지' : '현재 그래프'}의 연구자 목록 · {roster.length.toLocaleString()}명</summary><p>박사학위 연도 순 · 연구자를 선택하면 연결 근거를 확인할 수 있습니다.</p><div className="atlas-roster-table"><table><thead><tr><th>연구자</th><th>분야</th><th>박사 출신학교</th><th>학위연도</th></tr></thead><tbody>{roster.slice(page * 50, (page + 1) * 50).map(p => <tr key={p.id}><td><button onClick={() => pick(p.id)}>{label(p.id)}</button></td><td>{subjects[p.subject]}</td><td>{p.phd_institution_canonical || p.phd_institution || '미상'}</td><td>{p.phd_year || '미상'}</td></tr>)}</tbody></table></div>{roster.length > 50 && <div className="atlas-roster-pages"><button disabled={!page} onClick={() => setRosterPage(page - 1)}>이전</button><span>{page + 1} / {Math.ceil(roster.length / 50)}</span><button disabled={(page + 1) * 50 >= roster.length} onClick={() => setRosterPage(page + 1)}>다음</button></div>}</details>
    {selected && <TrajectoryPanel record={allRecords.find(p => p.id === selected.id)!} intervals={calculatedTrajectory?.intervals || []} peers={trajectory.peers} coverage={trajectory.selectedCoverage} labelFor={label} onSelect={id => { setScope('researcher'); pick(id); }} focused={scope === 'researcher'} onFocus={() => { setScope('researcher'); setSelectedEdge(''); }}/>}
    <details className="atlas-method"><summary>연결과 임베딩의 계산 기준</summary><p>국내는 학교+학과, 국외는 학교 단위로 공간 집합을 만듭니다. 국가 또는 국내 학과가 불명인 기록은 공간 연결에서 제외합니다. ‘추정 학과 포함’을 켜면 같은 기관·경력 기간의 저자 소속에서 단일 학과만 확인되는 경우를 추정 근거로 사용합니다. 기관별·연도별로 연구자 집합을 만든 뒤 구성원이 같은 시간 묶음을 합칩니다. 하이퍼엣지는 쌍별 친분 관계가 아니라 한 집합 전체를 뜻합니다. 선택한 하이퍼엣지는 구성원 노드를 감싸는 굴곡진 영역으로 표시합니다. 영역 안에 우연히 포함된 흐린 점은 구성원이 아니며, 밝게 강조된 노드가 실제 구성원입니다.</p><p>집합 크기와 집합 간 중첩을 보정한 정규화 하이퍼그래프 임베딩을 여러 초기값에서 계산하고, 목적함수를 비교해 배치를 선택합니다. 마지막으로 노드 충돌을 줄입니다. 전역 최적해를 보장하지 않으며 화면상 거리 자체가 실제 교류의 강도는 아닙니다. 연결을 끄거나 조건을 바꾸면 배치를 다시 계산합니다.</p><p>계산은 공개 익명 데이터만으로 브라우저에서 이루어집니다. 비밀번호 해제 후의 이름은 화면 표시에만 쓰이며 배치 계산이나 브라우저 저장소에 전달하지 않습니다.</p></details>
  </section>;
}
