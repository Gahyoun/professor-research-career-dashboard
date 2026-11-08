import { useEffect, useMemo, useState } from 'react';
import { readAbaPaths, type AbaPaper, type AbaPath } from './abaVault';
import type { TitleVault } from './titleVault';

const PAGE_SIZE = 7;
const fmt = (v: number) => v.toLocaleString('ko-KR');
const workUrl = (paper: AbaPaper) => `https://openalex.org/W${paper.id}`;

function PaperRow({ stage, paper, middle = false }: { stage: string; paper: AbaPaper; middle?: boolean }) {
  return <li className={middle ? 'aba-paper aba-paper-b' : 'aba-paper'}>
    <span>{stage} · {paper.year}년</span>
    <a href={workUrl(paper)} target="_blank" rel="noreferrer">{paper.title}</a>
  </li>;
}

export default function AbaRibbons({ vault, researcher }: { vault: TitleVault | null; researcher: string }) {
  const [state, setState] = useState<AbaPath[] | 'loading' | 'error'>('loading');
  const [query, setQuery] = useState('');
  const [page, setPage] = useState(0);
  const [selected, setSelected] = useState(0);
  useEffect(() => {
    if (!vault) return;
    let active = true;
    readAbaPaths(vault, researcher).then(
      rows => { if (active) setState(rows); },
      () => { if (active) setState('error'); },
    );
    return () => { active = false; };
  }, [vault, researcher]);
  const filtered = useMemo(() => Array.isArray(state) ? state.filter(row =>
    row.middle.title.toLowerCase().includes(query.trim().toLowerCase())) : [], [state, query]);
  const visible = filtered.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE);
  const picked = visible[selected];
  const first = visible.length ? Math.min(...visible.map(row => row.first.year)) : 0;
  const last = visible.length ? Math.max(...visible.map(row => row.last.year)) : 0;
  const x = (year: number) => 60 + (year - first) * 780 / Math.max(last - first, 1);
  const changePage = (next: number) => { setPage(next); setSelected(0); };
  return <section className="tp-panel aba-panel" aria-label="A–B–A 인용 경로">
    <div className="aba-heading"><div>
      <h3>A–B–A 인용 경로</h3>
      <p className="tp-muted">다른 저자의 B가 이 교수의 A₁을 인용하고, 이후 같은 교수가 A₂에서 B를 인용한 경로입니다.</p>
    </div>{Array.isArray(state) && state.length > 0 && <span className="aba-total">{fmt(state.length)}개 경로</span>}</div>
    {!vault && <p className="tp-muted">잠금을 해제하면 가운데 B 논문과 인용 경로를 확인할 수 있습니다.</p>}
    {vault && state === 'loading' && <p role="status" className="tp-muted">인용 경로를 불러오는 중입니다.</p>}
    {vault && state === 'error' && <p role="status" className="tp-muted">인용 경로 자료를 불러오지 못했습니다.</p>}
    {Array.isArray(state) && !state.length && <p className="tp-muted">이 자료에서 세 논문과 B의 저자 목록을 확인한 경로가 없습니다.</p>}
    {Array.isArray(state) && state.length > 0 && <>
      <div className="aba-controls">
        <label>가운데 B 논문 <input type="search" value={query} placeholder="제목 검색" onChange={e => { setQuery(e.target.value); changePage(0); }} /></label>
        <div className="aba-pager" aria-label="인용 경로 페이지">
          <button type="button" className="v2-btn-quiet" disabled={page === 0} onClick={() => changePage(page - 1)}>이전</button>
          <span>{filtered.length ? `${page + 1} / ${Math.ceil(filtered.length / PAGE_SIZE)}` : '0 / 0'}</span>
          <button type="button" className="v2-btn-quiet" disabled={(page + 1) * PAGE_SIZE >= filtered.length} onClick={() => changePage(page + 1)}>다음</button>
        </div>
      </div>
      {!visible.length && <p className="tp-muted">검색에 맞는 B 논문이 없습니다.</p>}
      {!!visible.length && <div className="aba-figure-scroll">
        <svg className="aba-figure" viewBox={`0 0 900 ${visible.length * 52 + 38}`} role="group" aria-label="연도별 A–B–A 리본">
          <line x1={x(first)} x2={x(last)} y1={27} y2={27} className="aba-axis" />
          {Array.from({ length: last - first + 1 }, (_, i) => first + i)
            .filter(year => year === first || year === last || (year - first) % Math.max(1, Math.ceil((last - first) / 8)) === 0)
            .map(year => <g key={year}><text x={x(year)} y={18} textAnchor="middle">{year}</text>
              <line x1={x(year)} x2={x(year)} y1={24} y2={visible.length * 52 + 32} className="aba-axis" /></g>)}
          {visible.map((row, i) => {
            const a = x(row.first.year), b = x(row.middle.year), c = x(row.last.year), y = 42 + i * 52;
            const bend = (u: number, v: number, start: number, end: number) =>
              `M ${u},${start} C ${(u + v) / 2},${start} ${(u + v) / 2},${end} ${v},${end}`;
            return <g key={`${row.first.id}-${row.middle.id}-${row.last.id}`} className={`aba-ribbon ${i === selected ? 'aba-selected' : ''}`}
              tabIndex={0} role="button" aria-pressed={i === selected}
              aria-label={`${row.first.year}년 → ${row.middle.year}년 ${row.middle.title} → ${row.last.year}년`}
              onClick={() => setSelected(i)} onKeyDown={e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); setSelected(i); } }}>
              <rect x={2} y={y - 10} width={896} height={49} className="aba-target" />
              <path d={bend(a, b, y, y + 12)} className="aba-a-to-b" />
              <path d={bend(b, c, y + 12, y)} className="aba-b-to-a" />
              <circle cx={a} cy={y} r={4} className="aba-endpoint" />
              <circle cx={c} cy={y} r={4} className="aba-endpoint" />
              <circle cx={b} cy={y + 12} r={5.5} className="aba-middle-dot" />
              <text x={Math.min(759, Math.max(141, b))} y={y + 31} textAnchor="middle" className="aba-middle-label">
                B · {row.middle.title.length > 34 ? `${row.middle.title.slice(0, 33)}…` : row.middle.title}
              </text>
              <title>{row.middle.title}</title>
            </g>;
          })}
        </svg>
      </div>}
      {picked && <ol className="aba-papers" aria-label="선택한 경로의 논문">
        <PaperRow stage="A₁ · 초기 논문" paper={picked.first} />
        <PaperRow stage="B · 다른 저자의 논문" paper={picked.middle} middle />
        <PaperRow stage="A₂ · 후속 논문" paper={picked.last} />
      </ol>}
      <p className="tp-muted aba-note">A₁ 다음 해부터 3년간의 피인용을 확인했습니다. A₂는 B 이후에 출판됐으며 마지막 출판 기준일은 2025년 12월 31일입니다. 리본은 인용 경로를 보여줍니다.</p>
    </>}
  </section>;
}
