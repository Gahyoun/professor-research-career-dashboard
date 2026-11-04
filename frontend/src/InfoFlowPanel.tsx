import { useEffect, useMemo, useRef, useState } from 'react';
import { conditionalEntropies, normalizeInfoFlow, topicColors, type InfoFlow, type InfoKey, type InfoTransition, type TopicResearcher } from './topics';

type Scale = 'bits' | 'norm';
type Series = { key: InfoKey | 'nmi'; label: string; color: string };
const SERIES: Record<Scale, Series[]> = {
  bits: [
    { key: 'diverge', label: '분기 H(Kₜ₊₁|Kₜ)', color: '#e5484d' },
    { key: 'merge', label: '합류 H(Kₜ|Kₜ₊₁)', color: '#256ef4' },
    { key: 'continuity', label: '연속성 I(Kₜ;Kₜ₊₁)', color: '#12a150' },
  ],
  norm: [
    { key: 'diverge_norm', label: '분기 / H(Kₜ₊₁)', color: '#e5484d' },
    { key: 'merge_norm', label: '합류 / H(Kₜ)', color: '#256ef4' },
    { key: 'nmi', label: 'NMI', color: '#12a150' },
  ],
};
const f2 = (v: number | null | undefined) => v === null || v === undefined ? '—' : v.toFixed(2);
const pct = (v: number | null | undefined) => v === null || v === undefined ? '—' : `${Math.round(v * 100)}%`;
const span = ([a, b]: [number, number]) => a === b ? `${a}` : `${a}–${String(b).slice(2)}`;

function valueOf(t: InfoTransition, key: Series['key']): number | null {
  return key === 'nmi' ? t.nmi : t.measures[key]?.value ?? null;
}

function useWidth<T extends HTMLElement>() {
  const ref = useRef<T>(null);
  const [width, setWidth] = useState(880);
  useEffect(() => {
    const node = ref.current;
    if (!node) return;
    const observer = new ResizeObserver(([entry]) => setWidth(Math.max(320, Math.round(entry.contentRect.width))));
    observer.observe(node);
    return () => observer.disconnect();
  }, []);
  return [ref, width] as const;
}

/** ``infoUrl``: per-researcher info-flow file, fetched when the index does not carry the block inline. */
export default function InfoFlowPanel({ researcher, infoUrl }: { researcher: TopicResearcher; infoUrl?: string }) {
  const [loaded, setLoaded] = useState<InfoFlow | null>(null);
  useEffect(() => {
    if (researcher.info || !infoUrl) return;
    let live = true;
    fetch(infoUrl).then(r => r.ok ? r.json() : null)
      .then(raw => { if (live && raw) setLoaded(normalizeInfoFlow(raw, new Set(researcher.topics.map(t => t.id)))); })
      .catch(() => undefined);
    return () => { live = false; };
  }, [researcher, infoUrl]);
  const info = researcher.info || loaded;
  const [scale, setScale] = useState<Scale>('bits');
  const [picked, setPicked] = useState<number | null>(null);
  const [box, width] = useWidth<HTMLDivElement>();
  const colors = useMemo(() => topicColors(researcher), [researcher]);
  const labels = useMemo(() => new Map(researcher.topics.map(t => [t.id, t.label])), [researcher]);
  if (!info || !info.transitions.length) return null;

  const rows = info.transitions;
  const series = SERIES[scale];
  const left = 48, right = 44, top = 16, bottom = 40, height = 260;
  const plotW = width - left - right, plotH = height - top - bottom;
  const max = scale === 'norm' ? 1 : Math.max(1, ...rows.flatMap(t => series.map(s => {
    const m = s.key === 'nmi' ? null : t.measures[s.key];
    return Math.max(valueOf(t, s.key) ?? 0, m?.ci?.[1] ?? 0);
  })));
  const yMax = scale === 'norm' ? 1 : Math.ceil(max * 2) / 2;
  // Narrow plots label each transition by the target window's first year only.
  const step = rows.length > 1 ? plotW / (rows.length - 1) : plotW;
  const compact = step < 76, every = step < 40 ? 2 : 1;
  const x = (i: number) => left + (rows.length === 1 ? plotW / 2 : (i / (rows.length - 1)) * plotW);
  const y = (v: number) => top + plotH - (v / yMax) * plotH;
  const ticks = Array.from({ length: 5 }, (_, i) => (yMax * i) / 4);
  const path = (key: Series['key']) => rows.map((t, i) => [i, valueOf(t, key)] as const).filter(([, v]) => v !== null)
    .map(([i, v], k) => `${k ? 'L' : 'M'}${x(i).toFixed(1)},${y(v!).toFixed(1)}`).join('');
  const band = (key: InfoKey) => {
    const pts = rows.map((t, i) => [i, t.measures[key]?.ci] as const).filter((p): p is readonly [number, [number, number]] => Boolean(p[1]));
    if (pts.length < 2) return '';
    return `M${pts.map(([i, ci]) => `${x(i).toFixed(1)},${y(ci[1]).toFixed(1)}`).join('L')}L${[...pts].reverse().map(([i, ci]) => `${x(i).toFixed(1)},${y(ci[0]).toFixed(1)}`).join('L')}Z`;
  };
  const nullLine = scale === 'bits' ? rows.map((t, i) => [i, t.measures.continuity?.null?.[0]] as const).filter(([, v]) => v !== undefined)
    .map(([i, v], k) => `${k ? 'L' : 'M'}${x(i).toFixed(1)},${y(v!).toFixed(1)}`).join('') : '';
  const s = info.summary;
  const current = picked !== null ? rows[picked] : null;
  const name = (topic: number | null, side: 'from' | 'to') => topic === null ? (side === 'from' ? '∅ 신규 (선행 연결 없음)' : '∅ 종료 (후속 연결 없음)') : labels.get(topic) || `T${topic}`;
  const dot = (topic: number | null) => <i style={{ background: topic === null ? 'transparent' : colors.get(topic), borderColor: topic === null ? 'var(--v2-faint)' : 'transparent' }} />;

  return <section className="tp-chart-card tp-info" aria-label="토픽 분기·합류 정보량">
    <div className="tp-chart-bar">
      <div><h3>토픽 분기·합류 정보량</h3>
        <p>{info.width}년 창 · 인접 창 논문 사이 bibliographic coupling으로 만든 결합분포 P(Kₜ, Kₜ₊₁) · {info.estimator} · 영가설: {info.nullKind === 'within-window topic-label permutation' ? '창 내부 토픽 라벨 순열' : info.nullKind} {info.nullRuns}회</p></div>
      <div className="tp-controls"><div className="v2-seg" role="group" aria-label="척도">
        <button type="button" className={scale === 'bits' ? 'is-on' : ''} aria-pressed={scale === 'bits'} onClick={() => setScale('bits')}>bits</button>
        <button type="button" className={scale === 'norm' ? 'is-on' : ''} aria-pressed={scale === 'norm'} onClick={() => setScale('norm')}>정규화 (0–1)</button>
      </div></div>
    </div>
    <div className="v2-stats v2-stats-4 tp-info-stats">
      <div className="v2-stat"><span>분기 H(Kₜ₊₁|Kₜ)</span><strong>{f2(s.diverge)}<em>bits</em></strong><small>후속 토픽 불확실성 중 {pct(s.diverge_norm)} 잔존</small></div>
      <div className="v2-stat"><span>합류 H(Kₜ|Kₜ₊₁)</span><strong>{f2(s.merge)}<em>bits</em></strong><small>선행 토픽 불확실성 중 {pct(s.merge_norm)} 잔존</small></div>
      <div className="v2-stat"><span>연속성 I(Kₜ;Kₜ₊₁)</span><strong>{f2(s.continuity)}<em>bits</em></strong><small>영가설 대비 +{f2(s.continuity_excess)} · NMI {f2(s.nmi)}</small></div>
      <div className="v2-stat"><span>신규 생성 비율</span><strong>{pct(s.birth_share)}</strong><small>직전 창과 참고문헌 공유 0인 논문</small></div>
    </div>
    <div ref={box} className="tp-info-plot">
      <svg width={width} height={height} role="img" aria-label="창 전이별 분기·합류·연속성">
        {ticks.map(v => <g key={v}><line x1={left} x2={width - right} y1={y(v)} y2={y(v)} className="tp-grid-line" /><text x={left - 8} y={y(v) + 4} textAnchor="end" className="tp-axis">{v.toFixed(scale === 'norm' ? 2 : 1)}</text></g>)}
        {rows.map((t, i) => <g key={i}>
          <rect x={x(i) - 18} y={top} width={36} height={plotH} className={`tp-info-hit${picked === i ? ' is-on' : ''}`} onClick={() => setPicked(picked === i ? null : i)} />
          {compact
            ? (i % every === 0 || i === rows.length - 1) && <text x={x(i)} y={height - 14} textAnchor="middle" className="tp-axis">→{t.to[0]}</text>
            : <><text x={x(i)} y={height - 22} textAnchor="middle" className="tp-axis">{span(t.from)}</text>
              <text x={x(i)} y={height - 8} textAnchor="middle" className="tp-axis">→ {span(t.to)}</text></>}
        </g>)}
        {scale === 'bits' && series.map(sr => sr.key !== 'nmi' && <path key={`b-${sr.key}`} d={band(sr.key)} fill={sr.color} fillOpacity=".07" stroke="none" />)}
        {nullLine && <path d={nullLine} fill="none" stroke="#8a949e" strokeDasharray="4 4" strokeWidth={1.5} />}
        {series.map(sr => <path key={sr.key} d={path(sr.key)} fill="none" stroke={sr.color} strokeWidth={2} />)}
        {series.map(sr => rows.map((t, i) => {
          const v = valueOf(t, sr.key);
          return v === null ? null : <circle key={`${sr.key}-${i}`} cx={x(i)} cy={y(v)} r={t.sparse ? 3.5 : 4} fill={t.sparse ? '#fff' : sr.color} stroke={sr.color} strokeWidth={1.5} pointerEvents="none" />;
        }))}
      </svg>
    </div>
    <ul className="tp-legend">
      {series.map(sr => <li key={sr.key}><i style={{ background: sr.color }} />{sr.label}</li>)}
      {scale === 'bits' && <li><i className="tp-legend-dash" />연속성 영가설 평균</li>}
      {scale === 'bits' && <li><i className="tp-legend-band" />부트스트랩 95% 구간</li>}
      <li><i className="tp-legend-hollow" />창 논문 5편 미만</li>
    </ul>

    <div className="tp-split tp-info-split">
      <div className="tp-table-wrap"><table className="tp-table tp-info-table">
        <thead><tr><th>전이</th><th className="num">논문</th><th className="num">분기</th><th className="num">합류</th><th className="num">연속성 [95%]</th><th className="num">영가설</th><th className="num">z</th><th className="num">JSD</th><th className="num">신규·종료</th></tr></thead>
        <tbody>{rows.map((t, i) => {
          const c = t.measures.continuity;
          return <tr key={i} className={picked === i ? 'is-focus' : ''} onClick={() => setPicked(picked === i ? null : i)} tabIndex={0} onKeyDown={e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); setPicked(picked === i ? null : i); } }}>
            <th scope="row">{span(t.from)} → {span(t.to)}</th>
            <td className="num">{t.n_from}→{t.n_to}</td>
            <td className="num">{f2(t.measures.diverge?.value)}</td>
            <td className="num">{f2(t.measures.merge?.value)}</td>
            <td className="num">{f2(c?.value)} <small>{c?.ci ? `[${f2(c.ci[0])}, ${f2(c.ci[1])}]` : ''}</small></td>
            <td className="num">{c?.null ? `${f2(c.null[0])} ± ${f2(c.null[1])}` : '—'}</td>
            <td className="num">{c?.z === null || c?.z === undefined ? '—' : c.z.toFixed(1)}</td>
            <td className="num">{f2(t.jsd)}</td>
            <td className="num">{pct(t.birth_share)} · {pct(t.ending_share)}</td>
          </tr>;
        })}</tbody>
      </table></div>
      <div className="tp-panel tp-info-detail">
        {current ? <>
          <h4>{span(current.from)} → {span(current.to)} 흐름</h4>
          <ol className="tp-flows">{current.flows.slice(0, 8).map((f, k) => <li key={k}>
            <span>{dot(f.from)}{name(f.from, 'from')}</span><b>→</b><span>{dot(f.to)}{name(f.to, 'to')}</span><em>{f.mass.toFixed(1)}</em>
          </li>)}</ol>
          <h4>토픽별 분기 H(Kₜ₊₁|Kₜ=a)</h4>
          <ol className="tp-flows">{conditionalEntropies(current.flows, 'from').filter(r => r.topic !== null).slice(0, 5).map(r => <li key={String(r.topic)}>
            <span>{dot(r.topic)}{name(r.topic, 'from')}</span><em>{r.bits.toFixed(2)} bits · {r.partners}갈래</em></li>)}</ol>
          <h4>토픽별 합류 H(Kₜ|Kₜ₊₁=b)</h4>
          <ol className="tp-flows">{conditionalEntropies(current.flows, 'to').filter(r => r.topic !== null).slice(0, 5).map(r => <li key={String(r.topic)}>
            <span>{dot(r.topic)}{name(r.topic, 'to')}</span><em>{r.bits.toFixed(2)} bits · {r.partners}갈래</em></li>)}</ol>
        </> : <>
          <h4>읽는 법</h4>
          <ul className="tp-info-notes">
            <li><b>분기</b> 직전 창의 토픽을 알 때 다음 창 토픽에 남는 불확실성입니다. 0이면 한 토픽이 한 토픽으로만 이어지고, 1 bit는 두 갈래로 고르게 갈라진 것과 같습니다.</li>
            <li><b>합류</b> 다음 창의 토픽을 알 때 그 기원 토픽에 남는 불확실성입니다. 값이 크면 여러 선행 토픽이 한 토픽으로 모였습니다.</li>
            <li><b>연속성</b> 두 창 사이 상호정보량입니다. 영가설(창 내부 토픽 라벨 순열)은 같은 토픽 구성과 표본 크기에서 나오는 기준값입니다.</li>
            <li><b>신규·종료</b> 직전 창과 참고문헌을 하나도 공유하지 않는 논문(∅→토픽)과 다음 창으로 이어지지 않는 논문(토픽→∅)의 비율입니다.</li>
            <li>토픽은 coupling 군집이므로 연속성은 구조적으로 양수입니다. 연구자 간 비교는 정규화 값과 영가설 대비 차이로 합니다. 표의 행을 누르면 그 전이의 토픽 간 흐름이 표시됩니다.</li>
          </ul>
        </>}
      </div>
    </div>
  </section>;
}
