import { useEffect, useMemo, useRef, useState } from 'react';
import type { Professor } from './types';
import { institutionDisplayName, institutionSearchText } from './schoolIdentity';
import { type Hypergraph, type HypergraphLayout, type Hyperedge } from './constellation/hypergraph';
import { createLifetimeIndex, type LifetimeStage } from './constellation/lifetime';
import { toResearcherRecords } from './constellation/records';
import type { CareerSummary } from './constellation/careerCatalog';
import CareerDirectory from './CareerDirectory';
import './constellation.css';
import TrajectoryPanel from './TrajectoryPanel';
import { smoothEnvelope } from './constellation/smoothEnvelope';
import { visibleEdges, envelopePaddings } from './constellation/edgePresentation';
import { lifetimePeriod, lifetimeStageColors, lifetimeStageLabels } from './lifetimePresentation';

const W = 1400, H = 1000;
const subjects: Record<string, string> = { mathematics: '수학', physics: '물리', chemistry: '화학', biology: '생물' };
const colors: Record<string, string> = { mathematics: '#8662b5', physics: '#287dba', chemistry: '#d99338', biology: '#269686' };
type Result = { graph: Hypergraph; layout: HypergraphLayout };
type Camera = { x: number; y: number; scale: number };
const initialCamera: Camera = { x: W / 2, y: H / 2, scale: 1 };
function graphCamera(points: readonly { x: number; y: number }[]): Camera {
  if (!points.length) return initialCamera;
  const minX = Math.min(...points.map(p => p.x)), maxX = Math.max(...points.map(p => p.x));
  const minY = Math.min(...points.map(p => p.y)), maxY = Math.max(...points.map(p => p.y));
  return { x: (minX + maxX) / 2, y: (minY + maxY) / 2,
    scale: Math.min(6, Math.max(.5, Math.min((W - 120) / (maxX - minX + 120), (H - 120) / (maxY - minY + 120)))) };
}
const edgeDisplayLabel = (edge: Hyperedge) => edge.institution
  ? edge.label.replace(edge.institution, institutionDisplayName(edge.institution)) : edge.label;

export default function Constellation({ professors, names, releaseYear, onSelect, initialSelectedId = '' }: {
  initialSelectedId?: string; professors: Professor[]; names: Record<string, string> | null; releaseYear: number; onSelect: (id: string) => void;
}) {
  const [subject, setSubject] = useState('');
  const [scope, setScope] = useState<'institution' | 'researcher'>('researcher');
  const [institution, setInstitution] = useState(() => { const counts = new Map<string, number>(); professors.forEach(p => { const value = p.phd_institution_canonical || p.phd_institution; if (value && !/^\d+$/.test(value)) counts.set(value, (counts.get(value) || 0) + 1); }); return [...counts].sort((a,b) => b[1]-a[1])[0]?.[0] || ''; });
  const [level, setLevel] = useState<'phd' | 'bachelor'>('phd');
  const [spatial, setSpatial] = useState(true), [temporal, setTemporal] = useState(true);
  const [years, setYears] = useState(5), [includeEstimated, setIncludeEstimated] = useState(true);
  const [balance, setBalance] = useState(35), [spacing, setSpacing] = useState(14);
  const [bachelorTime, setBachelorTime] = useState(false), [cohortEnabled, setCohortEnabled] = useState(true);
  const [includeInferredDepartments, setIncludeInferredDepartments] = useState(true);
  const [includeFirstFaculty, setIncludeFirstFaculty] = useState(false);
  const enabledStages = useMemo<LifetimeStage[]>(() => includeFirstFaculty ? ['doctoral', 'postdoc', 'first_faculty', 'current'] : ['doctoral', 'postdoc', 'current'], [includeFirstFaculty]);
  const [lifetimeStage, setLifetimeStage] = useState<LifetimeStage | 'all'>('all');
  const [rosterPage, setRosterPage] = useState(0);
  const [queryState, setQueryState] = useState({ names, text: '' });
  const query = queryState.names === names ? queryState.text : '';
  // Clear only the search on an authentication change, before an old name can render.
  if (queryState.names !== names) setQueryState({ names, text: '' });
  function setQuery(text: string) { setQueryState({ names, text }); }
  const [selectedId, setSelectedId] = useState(initialSelectedId);
  const [hoverId, setHoverId] = useState(''), [selectedEdge, setSelectedEdge] = useState('');
  const [inspectedId, setInspectedId] = useState('');
  const [storedResult, setResult] = useState<(Result & { requestKey: string }) | null>(null);
  const [status, setStatus] = useState('연결을 계산하고 있습니다.'), [error, setError] = useState('');
  const [camera, setCamera] = useState<Camera>(initialCamera);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const drag = useRef<{ px: number; py: number; x: number; y: number; moved: boolean } | null>(null);
  const envelopes = useRef(new Map<string, Path2D>());
  const [size, setSize] = useState({ width: 1000, height: 700 });
  const allRecords = useMemo(() => toResearcherRecords(professors), [professors]);
  const comparisonRecords = useMemo(() => !subject ? allRecords : allRecords.filter(p => p.subject === subject || p.id === selectedId), [allRecords, subject, selectedId]);
  const lifetimeIndex = useMemo(() => createLifetimeIndex(comparisonRecords, { releaseYear, includeEstimated, estimatedYears: years, includeInferredDepartments, stages: enabledStages }), [comparisonRecords, releaseYear, includeEstimated, years, includeInferredDepartments, enabledStages]);
  const lifetime = useMemo(() => { const value = lifetimeIndex.get(selectedId); return { ...value, stages: value.stages.filter(stage => enabledStages.includes(stage.stage)) }; }, [lifetimeIndex, selectedId, enabledStages]);
  const catalogRequest = useMemo(() => ({ records: allRecords, options: { releaseYear, includeEstimated, estimatedYears: years, includeInferredDepartments, stages: enabledStages } }), [allRecords, releaseYear, includeEstimated, years, includeInferredDepartments, enabledStages]);
  const [catalogState, setCatalogState] = useState<{ request: typeof catalogRequest; summaries: Record<string, CareerSummary> | null; progress: number; error: string } | null>(null);
  const catalog = catalogState?.request === catalogRequest ? catalogState : null;

  useEffect(() => {
    const worker = new Worker(new URL('./constellation/catalog.worker.ts', import.meta.url), { type: 'module' });
    let active = true;
    const fail = () => { if (active) setCatalogState(previous => ({ request: catalogRequest, summaries: previous?.request === catalogRequest ? previous.summaries : null, progress: previous?.request === catalogRequest ? previous.progress : 0, error: '전체 경력 계산을 불러오지 못했습니다. 새로고침해 주세요.' })); };
    worker.onmessage = ({ data }) => {
      if (!active) return;
      if (data.type === 'progress') setCatalogState(previous => ({ request: catalogRequest, summaries: { ...(previous?.request === catalogRequest ? previous.summaries : {}), ...data.summaries }, progress: data.progress, error: '' }));
      if (data.type === 'result') setCatalogState({ request: catalogRequest, summaries: data.summaries, progress: 1, error: '' });
      if (data.type === 'error') fail();
    };
    worker.onerror = fail;
    worker.postMessage(catalogRequest);
    return () => { active = false; worker.terminate(); };
  }, [catalogRequest]);
  const lifetimeGroups = useMemo(() => lifetime.stages.filter(stage => lifetimeStage === 'all' || stage.stage === lifetimeStage).flatMap(stage => stage.groups), [lifetime, lifetimeStage]);
  const peerIds = useMemo(() => new Set([selectedId, ...lifetimeGroups.flatMap(group => group.members)]), [selectedId, lifetimeGroups]);

  const scopePeers = scope === 'researcher' ? peerIds : null;
  const scopeSelectedId = scope === 'researcher' ? selectedId : '';
  const filtered = useMemo(() => professors.filter(p => (!subject || p.subject === subject || (scope === 'researcher' && p.id === scopeSelectedId)) && (scope === 'researcher' ? !!scopeSelectedId && !!scopePeers?.has(p.id) : !!institution && (level === 'phd' ? p.phd_institution_canonical || p.phd_institution : p.bachelor_institution_canonical || p.bachelor_institution) === institution)), [professors, subject, scope, scopeSelectedId, scopePeers, institution, level]);
  const byId = useMemo(() => new Map(professors.map(p => [p.id, p])), [professors]);
  const graphRecords = useMemo(() => { const ids = new Set(filtered.map(p => p.id)); return allRecords.filter(p => ids.has(p.id)); }, [filtered, allRecords]);
  const institutions = useMemo(() => [...new Set(professors.filter(p => !subject || p.subject === subject).map(p => level === 'phd' ? p.phd_institution_canonical || p.phd_institution : p.bachelor_institution_canonical || p.bachelor_institution).filter((s): s is string => !!s && !/^\d+$/.test(s)))].sort(), [professors, subject, level]);

  const requestKey = useMemo(() => JSON.stringify({ records: graphRecords, scopeSelectedId, lifetimeStage, enabledStages, releaseYear, spatial, temporal, level, includeEstimated, includeInferredDepartments, years, balance, spacing, cohortEnabled, bachelorTime }), [graphRecords, scopeSelectedId, lifetimeStage, enabledStages, releaseYear, spatial, temporal, level, includeEstimated, includeInferredDepartments, years, balance, spacing, cohortEnabled, bachelorTime]);
  const result = storedResult?.requestKey === requestKey ? storedResult : null;
  const overviewCamera = useMemo(() => scope === 'researcher' ? graphCamera(result?.layout.positions ?? []) : initialCamera, [scope, result]);

  const label = (id: string) => names?.[id] || id;
  const institutionFor = (id: string) => institutionDisplayName(byId.get(id)?.current_institution);
  const identityLabel = (id: string) => `${label(id)} · ${institutionFor(id)}`;
  const selected = byId.get(selectedId);
  const focusId = hoverId || inspectedId || selectedId;

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
      if (data.type === 'error') { setError('그래프를 계산하지 못했습니다. 조건을 바꾸거나 새로고침해 주세요.'); setStatus(''); }
      if (data.type === 'result') { envelopes.current.clear(); setResult({ ...data.result, requestKey }); setStatus(''); setError(''); setCamera(scopeSelectedId ? graphCamera(data.result.layout.positions) : initialCamera); }
    };
    worker.onerror = () => { setError('계산 도구를 불러오지 못했습니다. 새로고침해 주세요.'); setStatus(''); };
    worker.postMessage({
      // Only public, anonymous fields cross into the layout worker.
      records: graphRecords, selectedId: scopeSelectedId,
      options: { spatialEnabled: spatial, temporalEnabled: temporal, institutionLevel: level,
        releaseYear, stages: lifetimeStage === 'all' ? enabledStages : [lifetimeStage],
        includeEstimated, includeInferredDepartments, cohortEnabled, bachelorTemporalEnabled: bachelorTime, bachelorStartOffset: 10, bachelorEndOffset: 8, estimatedYears: years, spatialWeight: (100 - balance) / 100, temporalWeight: balance / 100 },
      layout: { width: W, height: H, padding: 55, minDistance: scopeSelectedId ? Math.max(24, spacing * 1.7) : spacing, chronologicalStrength: .45, iterations: 100, restarts: 3 },
    });
    return () => { active = false; worker.terminate(); };
  }, [graphRecords, scopeSelectedId, lifetimeStage, enabledStages, releaseYear, spatial, temporal, level, includeEstimated, includeInferredDepartments, years, balance, spacing, cohortEnabled, bachelorTime, requestKey]);

  function recompute(action: () => void) { setStatus('연결과 노드 간격을 최적화하고 있습니다.'); setResult(null); setError(''); setHoverId(''); setInspectedId(''); if (scope !== 'researcher') setSelectedId(''); setSelectedEdge(''); setRosterPage(0); action(); }
  const index = useMemo(() => new Map(result?.graph.nodes.map((n, i) => [n.id, i]) || []), [result]);
  const activeEdges = useMemo(() => visibleEdges(result?.graph.edges ?? [], scope, selectedEdge, index.get(selectedId)), [result, selectedEdge, selectedId, index, scope]);
  const edgePadding = useMemo(() => envelopePaddings(result?.graph.edges ?? [], Math.max(22, spacing * 1.7)), [result, spacing]);
  const activeMembers = useMemo(() => new Set(activeEdges.flatMap(edge => edge.members)), [activeEdges]);
  const focusedMembers = useMemo(() => new Set((selectedEdge ? activeEdges.filter(edge => edge.id === selectedEdge) : activeEdges).flatMap(edge => edge.members)), [activeEdges, selectedEdge]);
  const focusEdges = useMemo(() => activeEdges.filter(edge => edge.members.includes(index.get(focusId) ?? -1)), [activeEdges, index, focusId]);
  const edgeList = useMemo(() => (selectedId && result
    ? result.graph.edges.filter(e => e.members.includes(index.get(selectedId) ?? -1)) : result?.graph.edges || [])
    .toSorted((a, b) => (a.kind === 'cohort' ? 0 : a.kind === 'spatial' ? 1 : 2) - (b.kind === 'cohort' ? 0 : b.kind === 'spatial' ? 1 : 2) || (a.years?.[0] ?? 0) - (b.years?.[0] ?? 0) || b.members.length - a.members.length), [result, index, selectedId]);
  const matches = useMemo(() => query.trim() ? professors.filter(p => `${names?.[p.id] || ''} ${p.id} ${institutionSearchText(p.current_institution)}`.toLocaleLowerCase().includes(query.trim().toLocaleLowerCase())).slice(0, 30) : [], [professors, names, query]);

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
    activeEdges.toSorted((a, b) => Number(a.id === selectedEdge) - Number(b.id === selectedEdge) || (edgePadding.get(b.id) ?? 0) - (edgePadding.get(a.id) ?? 0)).forEach(edge => {
      let path = envelopes.current.get(edge.id);
      if (!path) {
        path = new Path2D(smoothEnvelope(edge.members.map(i => result.layout.positions[i]), edgePadding.get(edge.id)));
        if (envelopes.current.size > 60) envelopes.current.delete(envelopes.current.keys().next().value!);
        envelopes.current.set(edge.id, path);
      }
      ctx.save();
      ctx.translate(size.width / 2 - camera.x * scale, size.height / 2 - camera.y * scale); ctx.scale(scale, scale);
      ctx.fillStyle = edge.lifetimeStage ? lifetimeStageColors[edge.lifetimeStage] : edge.kind === 'spatial' ? '#256ef4' : edge.kind === 'temporal' ? '#d08a24' : '#347f65'; ctx.strokeStyle = ctx.fillStyle;
      const emphasized = edge.id === selectedEdge, context = !!selectedEdge && !emphasized;
      ctx.globalAlpha = emphasized ? .1 : context ? .025 : .055; ctx.fill(path);
      ctx.globalAlpha = context ? .4 : .85; ctx.lineWidth = (emphasized ? 2.5 : 1.4) / scale;
      ctx.setLineDash(edge.kind === 'temporal' ? [5 / scale, 3 / scale] : []); ctx.stroke(path); ctx.restore();
    });

    ctx.setLineDash([]);
    result.graph.nodes.forEach((node, i) => {
      const p = positions[i];
      if (p.x < -15 || p.y < -15 || p.x > size.width + 15 || p.y > size.height + 15) return;
      const focused = node.id === focusId;
      ctx.globalAlpha = hasFocus && !activeMembers.has(i) && !focused ? .15 : selectedEdge && !focusedMembers.has(i) && !focused ? .5 : .9;
      ctx.fillStyle = colors[node.subject] || '#607284';
      const baseRadius = result.graph.nodes.length < 80 ? Math.min(3.2, 2.2 * camera.scale) : Math.max(.8, Math.min(3.2, spacing * scale * .32));
      const radius = focused ? 5 : activeMembers.has(i) ? Math.max(2.2, baseRadius) : baseRadius;
      ctx.beginPath(); ctx.arc(p.x, p.y, radius, 0, Math.PI * 2); ctx.fill();
      if (scope === 'researcher') {
        const memberships = result.graph.incidence[i].map(e => result.graph.edges[e]).filter(edge => edge.lifetimeStage);
        // Every incident group owns a ring segment; a node is never assigned one winning group.
        memberships.forEach((edge, memberIndex) => {
          const arc = Math.PI * 2 / memberships.length, gap = memberships.length > 1 ? .15 : 0;
          ctx.strokeStyle = lifetimeStageColors[edge.lifetimeStage!]; ctx.lineWidth = edge.id === selectedEdge ? 2.8 : 2;
          ctx.globalAlpha = edge.id === selectedEdge ? 1 : .85;
          ctx.beginPath(); ctx.arc(p.x, p.y, radius + 3.5, memberIndex * arc - Math.PI / 2 + gap / 2, (memberIndex + 1) * arc - Math.PI / 2 - gap / 2); ctx.stroke();
        });
      }
      if (focused) {
        ctx.strokeStyle = ctx.fillStyle; ctx.lineWidth = 1; ctx.globalAlpha = .35;
        ctx.beginPath(); ctx.arc(p.x, p.y, 9, 0, Math.PI * 2); ctx.stroke();
        ctx.globalAlpha = 1; ctx.font = '600 15px Pretendard, -apple-system, sans-serif';
        const text = names?.[node.id] || node.id;
        const institution = institutionDisplayName(byId.get(node.id)?.current_institution);
        const lines = [text]; let line = '';
        for (const character of institution) {
          if (line && ctx.measureText(line + character).width > Math.min(250, size.width - 40)) { lines.push(line); line = ''; }
          line += character;
        }
        if (line) lines.push(line);
        const tw = Math.max(...lines.map(value => ctx.measureText(value).width));
        const tx = Math.min(size.width - tw - 12, Math.max(12, p.x + 14)), ty = Math.max(24, Math.min(size.height - lines.length * 18, p.y - 11));
        ctx.fillStyle = '#fff'; ctx.fillRect(tx - 5, ty - 16, tw + 10, lines.length * 18 + 8);
        lines.forEach((value, n) => { ctx.fillStyle = n ? '#464c53' : '#1e2124'; ctx.fillText(value, tx, ty + n * 18); });
      }
    });
    ctx.globalAlpha = 1;
  }, [result, size, camera, scale, names, byId, focusId, activeEdges, activeMembers, focusedMembers, edgePadding, spacing, selectedId, selectedEdge, scope]);

  function hit(clientX: number, clientY: number) {
    const rect = canvasRef.current?.getBoundingClientRect();
    if (!rect || !result) return '';
    let nearest = '', distance = 13;
    result.layout.positions.forEach(p => { const screen = project(p.x, p.y), d = Math.hypot(screen.x - (clientX - rect.left), screen.y - (clientY - rect.top)); if (d < distance) { nearest = p.id; distance = d; } });
    return nearest;
  }
  function pick(id: string) { setSelectedId(id); setSelectedEdge(''); setHoverId(''); setInspectedId(''); setRosterPage(0); setLifetimeStage('all'); }
  function openResearcher(id: string) {
    setScope('researcher'); setSubject(''); pick(id);
    setStatus('선택한 교수의 전체 경력 연결을 계산하고 있습니다.');
    requestAnimationFrame(() => document.getElementById('lifetime-explorer-title')?.scrollIntoView({ block: 'start', behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'instant' : 'smooth' }));
  }
  function filterStage(stage: LifetimeStage | 'all') { setLifetimeStage(stage); setSelectedEdge(''); setHoverId(''); setInspectedId(''); setRosterPage(0); setStatus('선택한 단계의 집단을 계산하고 있습니다.'); }
  function selectEdge(id: string) {
    if (selectedEdge === id) { setSelectedEdge(''); setHoverId(''); setRosterPage(0); setCamera(overviewCamera); return; }
    setSelectedEdge(id); setHoverId(''); setRosterPage(0);
    const edge = result?.graph.edges.find(e => e.id === id);
    if (edge && result && scope !== 'researcher') {
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
    <div className="atlas-heading"><div><div className="atlas-kicker">K–STEM ATLAS <span>/ {releaseYear}</span></div><h1 id="atlas-title">Career trajectory hypergraph</h1><p>연구자의 경력 단계별로 학교·학과와 활동 기간이 겹치는 집단을 탐색합니다.</p></div><div className="atlas-count"><strong>{professors.length.toLocaleString()}</strong><span>전체 교수 <i>·</i> 현재 그래프 {filtered.length.toLocaleString()}명</span></div></div>
    <CareerDirectory professors={professors} names={names} summaries={catalog?.summaries || null} progress={catalog?.progress || 0} error={catalog?.error} selectedId={selectedId} onSelect={openResearcher} includeFirstFaculty={includeFirstFaculty}/>
    <div className="atlas-scope">
      <div className="atlas-segment" role="group" aria-label="탐색 범위"><button className={scope === 'institution' ? 'selected' : ''} onClick={() => recompute(() => { setScope('institution'); pick(''); })}>학교별</button><button className={scope === 'researcher' ? 'selected' : ''} onClick={() => { setScope('researcher'); setSelectedEdge(''); }}>연구자별</button></div>
      {scope === 'institution' ? <label>출신학교<select value={institution} onChange={e => recompute(() => setInstitution(e.target.value))}><option value="">학교를 선택하세요</option>{institutions.map(v => <option key={v} value={v}>{institutionDisplayName(v)}</option>)}</select></label> : <label>연구자 · 현재기관<select value={selectedId} onChange={e => { setStatus('단계별 집단을 계산하고 있습니다.'); pick(e.target.value); }}><option value="">연구자를 선택하세요</option>{professors.filter(p => !subject || p.subject === subject || p.id === selectedId).map(p => <option key={p.id} value={p.id}>{identityLabel(p.id)} · {subjects[p.subject]}</option>)}</select></label>}
      <button className="atlas-reset" onClick={() => { setQuery(''); setSubject(''); pick(''); setCamera(overviewCamera); setIncludeEstimated(true); setIncludeInferredDepartments(true); setIncludeFirstFaculty(false); setYears(5); setSpacing(14); setBalance(35); setSpatial(true); setTemporal(true); setCohortEnabled(true); setBachelorTime(false); setLevel('phd'); setStatus(''); }}>초기화</button>
    </div>
    {scope === 'researcher' && <section className="lifetime-explorer" aria-labelledby="lifetime-explorer-title">
      <div className="atlas-section-title"><div><h2 id="lifetime-explorer-title">{selected ? label(selected.id) : '연구자 선택 후 경력 단계를 탐색하세요'}</h2>{selected && <p className="atlas-current-identity">{institutionFor(selected.id)} <span>· {subjects[selected.subject] || selected.subject}</span></p>}</div><button className={lifetimeStage === 'all' ? 'selected' : ''} onClick={() => filterStage('all')} aria-pressed={lifetimeStage === 'all'}>모든 단계 함께 보기</button></div>
      <label className="atlas-check lifetime-first-option"><input type="checkbox" checked={includeFirstFaculty} onChange={event => { setIncludeFirstFaculty(event.target.checked); filterStage('all'); }}/>첫 조교수 단계 추가 · 첫 임용 근거가 확인된 경우</label>
      <div className="lifetime-stage-filters" style={{ '--stage-count': enabledStages.length } as React.CSSProperties} role="group" aria-label="경력 단계별 하이퍼엣지 필터">{lifetime.stages.map((stage, i) => <button key={stage.id} className={lifetimeStage === stage.stage ? 'active' : ''} style={{ '--stage-color': lifetimeStageColors[stage.stage] } as React.CSSProperties} onClick={() => filterStage(stage.stage)} aria-pressed={lifetimeStage === stage.stage}>
        <span className="lifetime-stage-name"><i aria-hidden="true"/>{String(i + 1).padStart(2, '0')} {lifetimeStageLabels[stage.stage]}</span><strong>{stage.groups.length}개 집단</strong><small>{stage.intervals.length ? [...new Set(stage.intervals.map(interval => lifetimePeriod(interval.startYear, interval.endYear)))].join(' · ') : '확인 가능한 기간 없음'}</small><small>{stage.condition}</small>
      </button>)}</div>
      <p className="lifetime-rule">하나의 하이퍼엣지 = 선택한 경력 단계·기관·기간의 집단. 한 연구자는 여러 집단에 동시에 포함됩니다. 그 기간 중 한 번이라도 겹친 동료와 근거가 있는 재직 교수를 함께 묶습니다. 구성원마다 실제로 겹친 연도는 아래 근거 목록에서 확인합니다.</p>
      {lifetime.stages.filter(stage => lifetimeStage !== 'all' && stage.stage === lifetimeStage).map(stage => <div key={stage.id} className="lifetime-stage-explanation" style={{ '--stage-color': lifetimeStageColors[stage.stage] } as React.CSSProperties}><strong>{stage.label}</strong><p>{stage.condition}</p>{stage.excludedReasons.map((reason, i) => <p key={i}>{reason}</p>)}</div>)}
    </section>}
    <div className="atlas-workspace">
      <div className="atlas-map-column">
        <div className="atlas-map-toolbar"><div className="atlas-subjects" role="group" aria-label="연구 분야"><button className={!subject ? 'selected' : ''} onClick={() => recompute(() => setSubject(''))}>전체</button>{Object.entries(subjects).map(([key, name]) => <button key={key} className={subject === key ? 'selected' : ''} onClick={() => recompute(() => setSubject(key))}><i style={{ background: colors[key] }}/>{name}</button>)}</div><span className="atlas-map-caption">점 색상 = 연구 분야</span></div>
        <div className="atlas-canvas-wrap">
          <canvas ref={canvasRef} className="atlas-canvas" aria-label={`연구자 ${filtered.length}명의 경력 하이퍼그래프. 아래 검색과 집단별 구성원 근거 목록으로도 탐색할 수 있습니다.`}
            tabIndex={0} onKeyDown={e => { if (['+', '=', '-', '0', 'Escape', 'ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown'].includes(e.key)) e.preventDefault(); if (e.key === '+' || e.key === '=') zoomTo(1.3); if (e.key === '-') zoomTo(1 / 1.3); if (e.key === '0') setCamera(overviewCamera); if (e.key === 'Escape') { setSelectedEdge(''); setHoverId(''); setInspectedId(''); } const dx = e.key === 'ArrowLeft' ? -60 : e.key === 'ArrowRight' ? 60 : 0, dy = e.key === 'ArrowUp' ? -60 : e.key === 'ArrowDown' ? 60 : 0; if (dx || dy) setCamera(c => ({ ...c, x: c.x + dx / scale, y: c.y + dy / scale })); }}
            onWheel={e => { if (e.ctrlKey || e.metaKey) zoomTo(e.deltaY > 0 ? .9 : 1.1); }}
            onPointerDown={e => { drag.current = { px: e.clientX, py: e.clientY, x: camera.x, y: camera.y, moved: false }; e.currentTarget.setPointerCapture(e.pointerId); }}
            onPointerMove={e => { if (drag.current) { const dx = e.clientX - drag.current.px, dy = e.clientY - drag.current.py; if (Math.hypot(dx, dy) > 4) drag.current.moved = true; if (drag.current.moved) setCamera(c => ({ ...c, x: drag.current!.x - dx / scale, y: drag.current!.y - dy / scale })); } else setHoverId(hit(e.clientX, e.clientY)); }}
            onPointerUp={e => { if (drag.current && !drag.current.moved) { const id = hit(e.clientX, e.clientY); if (id) { if (scope === 'researcher') { setInspectedId(id); setHoverId(''); } else pick(id); } else { setSelectedEdge(''); setHoverId(''); setInspectedId(''); } } drag.current = null; }} onPointerCancel={() => { drag.current = null; }} onPointerLeave={() => setHoverId('')}/>
          {(error || !result || !filtered.length) && <div className="atlas-map-status" role="status">{error || (filtered.length ? status || '연결과 노드 간격을 계산하고 있습니다.' : scope === 'researcher' ? '위에서 연구자를 선택하세요.' : !institution ? '위에서 학교를 선택하세요.' : '현재 학교·분야에 일치하는 연구자가 없습니다.')}{!error && filtered.length > 0 && <span>공개 익명 데이터로 계산 중</span>}</div>}
          <div className="atlas-map-index" aria-hidden="true">{String(filtered.length).padStart(4, '0')} NODES<br/><span>{scope === 'researcher' ? 'LIFETIME GROUPS' : 'TIME × INSTITUTION'}</span></div>
          <div className="atlas-map-controls"><button onClick={() => zoomTo(1.35)} aria-label="하이퍼그래프 확대">+</button><button onClick={() => zoomTo(1 / 1.35)} aria-label="하이퍼그래프 축소">−</button><button onClick={() => setCamera(overviewCamera)} aria-label="하이퍼그래프 전체 보기">↗</button></div>
          <div className="atlas-scale">{Math.round(camera.scale * 100)}% <span>드래그 이동 · + / − 확대 · 0 전체</span></div>
        </div>
        <div className="atlas-map-footer">{scope === 'researcher' ? <><b>윤곽 색상 = 경력 단계</b>{Object.entries(lifetimeStageLabels).filter(([stage]) => enabledStages.includes(stage as LifetimeStage)).map(([stage, text]) => <span key={stage}><i className="atlas-line" style={{ borderColor: lifetimeStageColors[stage as LifetimeStage] }}/>{text}</span>)}</> : <><span><i className="atlas-line spatial"/>같은 출신기관</span><span><i className="atlas-line temporal"/>겹치는 박사과정 시기</span></>}<span>{scope === 'researcher' ? '점 둘레 색상 = 동시에 속한 경력 단계' : '밝은 점 = 해당 집단의 구성원'}</span><button onClick={() => { setSelectedEdge(''); setHoverId(''); setCamera(overviewCamera); }}>집단 강조 해제</button></div>
      </div>
      <aside className="atlas-sidebar" aria-label="하이퍼그래프 탐색 조건">
        {scope === 'researcher' && result && focusId && <section className="atlas-sidebar-section atlas-memberships" aria-label="선택한 점의 동시 소속">
          <h2>이 점의 소속 집단 <span>{focusEdges.length}개</span></h2>
          <strong>{label(focusId)}</strong><p>{institutionFor(focusId)}</p>
          <div>{focusEdges.map(edge => <button key={edge.id} onClick={() => selectEdge(edge.id)} aria-pressed={selectedEdge === edge.id} style={{ '--membership-color': edge.lifetimeStage ? lifetimeStageColors[edge.lifetimeStage] : '#607284' } as React.CSSProperties}><i aria-hidden="true"/><span>{edge.lifetimeStage ? lifetimeStageLabels[edge.lifetimeStage] : edge.kind}<small>{edge.startYear !== undefined && lifetimePeriod(edge.startYear, edge.endYear ?? edge.startYear)}</small></span></button>)}</div>
          {!focusEdges.length && <p>현재 표시 범위에서 연결 집단이 없습니다.</p>}
          <p className="atlas-quiet">점 선택으로 동시 소속을 확인합니다. 집단을 강조해도 다른 소속은 계속 표시합니다.</p>
          {focusId !== selectedId && <button className="atlas-member-recenter" onClick={() => openResearcher(focusId)}>이 연구자 중심으로 보기 ↗</button>}
        </section>}
        <div className="atlas-sidebar-section"><h2>연구자 찾기 <span>01</span></h2><label className="atlas-search-label" htmlFor="atlas-search">{names ? '이름 · 익명 ID · 현재기관' : '익명 ID · 현재기관'}</label><div className="atlas-search"><span aria-hidden="true">⌕</span><input id="atlas-search" value={query} onChange={e => setQuery(e.target.value)} placeholder={names ? '이름 또는 현재기관' : 'Prof ID 또는 현재기관'} autoComplete="off"/></div>
          {query && <div className="atlas-search-results" role="region" aria-label="연구자 검색 결과">{matches.length ? matches.map(p => <button key={p.id} onClick={() => { openResearcher(p.id); setQuery(''); }}><strong>{label(p.id)}</strong><span>{institutionDisplayName(p.current_institution)}</span><small>{subjects[p.subject] || p.subject}</small></button>) : <p>일치하는 연구자가 없습니다.</p>}</div>}
          {selected && <div className="atlas-selected-identity"><strong>{label(selected.id)}</strong><span>{institutionFor(selected.id)}</span><small>{subjects[selected.subject] || selected.subject}</small></div>}
        </div>
        <div className="atlas-sidebar-section"><h2>{scope === 'researcher' ? '기간과 근거' : '연결 조건'} <span>02</span></h2>
          {scope === 'institution' && <><label className="atlas-switch"><span><i className="atlas-line spatial"/><b>공간적 일치</b><small>국내외 모두 학교+학과</small></span><input type="checkbox" checked={spatial} onChange={e => recompute(() => setSpatial(e.target.checked))}/></label><div className="atlas-segment" role="group" aria-label="출신기관 학위"><button className={level === 'phd' ? 'selected' : ''} onClick={() => recompute(() => { setLevel('phd'); setInstitution(''); })}>박사 출신</button><button className={level === 'bachelor' ? 'selected' : ''} onClick={() => recompute(() => { setLevel('bachelor'); setInstitution(''); })}>학부 출신</button></div><label className="atlas-switch"><span><i className="atlas-line temporal"/><b>시간적 일치</b><small>같은 해를 포함하는 박사과정 구간</small></span><input type="checkbox" checked={temporal} onChange={e => recompute(() => setTemporal(e.target.checked))}/></label><label className="atlas-check"><input type="checkbox" checked={cohortEnabled} onChange={e => recompute(() => setCohortEnabled(e.target.checked))}/>같은 학교·학과·시기 묶음</label><label className="atlas-check"><input type="checkbox" checked={bachelorTime} onChange={e => recompute(() => setBachelorTime(e.target.checked))}/>학부 추정 시기 포함 (학위 10–8년 전)</label></>}
          {scope === 'researcher' && <p className="atlas-quiet">박사·첫 조교수·현직은 국내외 모두 학교+학과가 일치해야 합니다. 포닥 단계는 예외적으로 학교·기관만 비교합니다.</p>}
          <label className="atlas-check"><input type="checkbox" checked={includeEstimated} onChange={e => recompute(() => setIncludeEstimated(e.target.checked))}/>추정 경력 기간 포함</label>
          <label className="atlas-field atlas-years">박사과정 시작 <select value={years} disabled={!includeEstimated || (scope === 'institution' && !temporal)} onChange={e => recompute(() => setYears(Number(e.target.value)))}>{[3, 4, 5, 6, 7].map(y => <option key={y} value={y}>학위 취득 {y}년 전</option>)}</select></label>
          <p className="atlas-quiet">직접 확인한 박사 재학 기간이 없으면 학위연도−{years}부터 학위연도까지 사용합니다. 양 끝 연도를 포함합니다.</p>
          <label className="atlas-check"><input type="checkbox" checked={includeInferredDepartments} onChange={e => recompute(() => setIncludeInferredDepartments(e.target.checked))}/>논문 소속에서 추정한 학과 포함</label><p className="atlas-quiet">학과 추정과 기간 추정은 별개입니다. 필요한 학과·기간·재직 근거가 없으면 해당 집단에 연결하지 않습니다.</p>
        </div>
        <div className="atlas-sidebar-section"><h2>배치 <span>03</span></h2>{scope === 'institution' && <label className="atlas-range">기관 ↔ 시간 비중 <output>{100 - balance} : {balance}</output><input type="range" min="10" max="90" step="5" value={balance} disabled={!spatial || !temporal} onChange={e => recompute(() => setBalance(Number(e.target.value)))}/></label>}<label className="atlas-range">노드 사이 여백 <output>{spacing}</output><input type="range" min="7" max="18" value={spacing} onChange={e => recompute(() => setSpacing(Number(e.target.value)))}/></label><p className="atlas-quiet">여러 집단에 속한 연구자는 모든 소속을 함께 반영해 배치합니다. 점 둘레의 색상은 소속 단계를 뜻합니다. 화면상 거리는 교류 강도가 아닙니다.</p></div>
      </aside>
    </div>
    <div className="atlas-lower"><section className="atlas-selection"><div className="atlas-section-title"><div><h2>{selected ? label(selected.id) : '연구자와 연결 근거'}</h2>{selected && <p className="atlas-current-identity">{institutionFor(selected.id)}</p>}</div>{selected && <button onClick={() => onSelect(selected.id)}>경력과 논문 보기 ↗</button>}</div>{selected ? <><p>{subjects[selected.subject] || selected.subject}</p>{scope === 'institution' && <button className="trajectory-open" onClick={() => { setScope('researcher'); setSelectedEdge(''); }}>이 연구자의 경력 단계별 집단 보기 ↗</button>}<dl><div><dt>박사 출신기관</dt><dd>{institutionDisplayName(selected.phd_institution)}</dd></div><div><dt>박사 학위연도</dt><dd>{selected.phd_year || '정보 없음'}</dd></div><div><dt>표시 중인 집단</dt><dd>{edgeList.length}개</dd></div></dl></> : <p>연구자를 선택하면 경력 단계별 집단과 구성원 근거를 확인할 수 있습니다.</p>}
      <div className="atlas-disclosure"><strong>단계 전체의 연결 집단입니다.</strong><p>{scope === 'researcher' ? '같은 집단의 모든 구성원이 같은 해에 함께 있었다는 뜻은 아닙니다. 각 구성원과 선택 연구자가 겹친 기간을 따로 표시합니다. 첫 조교수는 직급과 최초 임용이 명확한 기록만 사용하며, 현직은 관측된 연도만 사용합니다.' : `학위연도 기반 추정 대상 ${estimatedCount.toLocaleString()}명, 기간 정보 없음 ${missingCount.toLocaleString()}명. 추정 구간은 학위연도−${years}부터 학위연도까지입니다.`} 기관·시기의 일치는 친분이나 공동연구를 뜻하지 않습니다.</p></div>
    </section><section className="atlas-groups"><div className="atlas-section-title"><h2>하이퍼엣지 · 집단 선택</h2><span>{edgeList.length}개</span></div><div className="atlas-edge-list">{edgeList.slice(0, 40).map(edge => <button key={edge.id} className={selectedEdge === edge.id ? 'active' : ''} onClick={() => selectEdge(edge.id)}><i className={`atlas-line ${edge.kind}`} style={edge.lifetimeStage ? { borderColor: lifetimeStageColors[edge.lifetimeStage] } : undefined}/><span>{edgeDisplayLabel(edge)}<small>{edge.condition || (edge.kind === 'spatial' ? '같은 학교·학과' : edge.kind === 'temporal' ? '공통 박사과정 추정 기간' : '같은 학교·학과·시기')} {edge.startYear !== undefined && ` · ${edge.startYear}–${edge.endYear}`}</small></span><b>{edge.members.length}<small>명</small></b></button>)}{edgeList.length > 40 && <p className="atlas-quiet">40개 집단 표시 · 연구자나 단계로 범위를 좁힐 수 있습니다.</p>}{!edgeList.length && <p className="atlas-quiet">현재 근거와 조건에서 두 명 이상이 공유하는 집단이 없습니다.</p>}</div></section></div>
    {selected && scope === 'researcher' && <TrajectoryPanel lifetime={lifetime} stageFilter={lifetimeStage} selectedGroupId={selectedEdge} labelFor={label} institutionFor={institutionFor} subjectFor={id => subjects[byId.get(id)?.subject || ''] || '분야 미상'} onSelect={id => { setScope('researcher'); pick(id); }} onSelectGroup={selectEdge}/>}
    <details className="atlas-roster"><summary>{selectedEdge ? '선택한 하이퍼엣지' : '현재 그래프'}의 연구자 목록 · {roster.length.toLocaleString()}명</summary><p>박사학위 연도 순 · 연구자를 선택하면 해당 연구자를 중심으로 다시 탐색합니다.</p><div className="atlas-roster-table"><table><thead><tr><th>연구자 · 현재기관</th><th>분야</th><th>박사 출신학교</th><th>학위연도</th></tr></thead><tbody>{roster.slice(page * 50, (page + 1) * 50).map(p => <tr key={p.id}><td><button onClick={() => pick(p.id)}><strong>{label(p.id)}</strong><span>{institutionDisplayName(p.current_institution)}</span></button></td><td>{subjects[p.subject]}</td><td>{institutionDisplayName(p.phd_institution)}</td><td>{p.phd_year || '미상'}</td></tr>)}</tbody></table></div>{roster.length > 50 && <div className="atlas-roster-pages"><button disabled={!page} onClick={() => setRosterPage(page - 1)}>이전</button><span>{page + 1} / {Math.ceil(roster.length / 50)}</span><button disabled={(page + 1) * 50 >= roster.length} onClick={() => setRosterPage(page + 1)}>다음</button></div>}</details>
    <details className="atlas-method"><summary>집단과 임베딩의 계산 기준</summary><p>국내외 모두 학교+학과 단위로 비교하며, 포닥 단계만 기관 단위로 비교합니다. 과거 학과를 현재 학과로 대신 채우지 않습니다. 논문 소속에서 추정한 학과를 포함한 경우는 각 집단과 구성원 근거에 별도로 표시합니다.</p><p>연구자별 하이퍼엣지는 선택 연구자의 단계·기관·기간을 기준으로 만든 집합입니다. 박사과정 집단은 재학 기간이 겹친 동료와 재직 근거가 있는 교수를 함께 포함합니다. 연도마다 잘게 나누지 않으며, 구성원별 겹친 기간을 보존합니다. 첫 조교수 단계는 일반 교수 경력의 순번에서 추측하지 않습니다. 현직은 공개 자료에서 관측된 시점을 사용합니다.</p><p>매끈한 윤곽은 집단의 표시입니다. 윤곽 안에 들어온 점도 구성원이 아닐 수 있으며, 실제 소속은 점 둘레의 단계 색상과 구성원 목록으로 확인합니다. 동일 구성원의 집단도 별도 윤곽으로 표시하며, 집단 선택은 강조만 바꿉니다. 연구자별 화면에서는 소속된 모든 집단 중심의 가중 평균으로 배치하고 노드 충돌을 줄입니다. 시간 순서는 같은 소속 조합 안에서만 반영합니다. 학교별 화면은 집합 크기와 중첩을 보정한 스펙트럴 임베딩을 여러 초기값에서 계산합니다. 전역 최적해를 보장하지 않으며, 거리는 실제 교류 강도가 아닙니다.</p><p>계산은 공개 익명 데이터만으로 브라우저에서 이루어집니다. 비밀번호 해제 후 이름은 화면 표시에만 사용하며 계산 작업과 브라우저 저장소에 전달하지 않습니다.</p></details>
  </section>;
}
