import { useEffect, useId, useRef, useState } from 'react';
import { FLOW_SQL_PRESETS, MAX_FLOW_SQL_LENGTH } from './flowSql';
import type { FlowSqlRequest, FlowSqlResponse } from './flowSql';
import './flowSql.css';

type Props = {
  unlocked: boolean;
  releaseYear: number;
  professorIds: string[];
  appliedCount: number | null;
  onApply: (ids: string[] | null) => void;
};

type Pending = { requestId: number; timer: ReturnType<typeof setTimeout> };
const count = (n: number) => n.toLocaleString('ko-KR');

export default function FlowSqlQuery({ unlocked, releaseYear, professorIds, appliedCount, onApply }: Props) {
  const id = useId();
  const [sql, setSql] = useState(FLOW_SQL_PRESETS[0].sql);
  const [appliedSql, setAppliedSql] = useState<string | null>(null);
  const [phase, setPhase] = useState<'idle' | 'loading' | 'running'>('idle');
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const workerRef = useRef<Worker | null>(null);
  const pendingRef = useRef<Pending | null>(null);
  const nextRequest = useRef(0);
  const busy = phase !== 'idle';

  useEffect(() => () => {
    // Relocking remounts SankeyPage: no query, result, or worker survives that session.
    if (pendingRef.current) clearTimeout(pendingRef.current.timer);
    pendingRef.current = null;
    workerRef.current?.terminate();
    workerRef.current = null;
  }, []);

  function terminate() {
    if (pendingRef.current) clearTimeout(pendingRef.current.timer);
    pendingRef.current = null;
    workerRef.current?.terminate();
    workerRef.current = null;
    setPhase('idle');
  }

  function fail(message: string) {
    terminate();
    setError(message);
  }

  function run() {
    if (!unlocked || busy) return;
    setError('');
    setNotice('');
    if (!sql.trim()) { setError('실행할 SELECT 쿼리를 입력해 주세요.'); return; }
    const requestId = ++nextRequest.current;
    setPhase('loading');
    try {
      const worker = workerRef.current ?? new Worker(new URL('./flowSql.worker.ts', import.meta.url), { type: 'module' });
      workerRef.current = worker;
      pendingRef.current = { requestId, timer: setTimeout(() => fail('자료를 불러오는 시간이 길어져 실행을 중단했습니다. 다시 실행해 주세요.'), 60_000) };
      const onMessage = ({ data }: MessageEvent<FlowSqlResponse>) => {
        if (pendingRef.current?.requestId !== data.requestId) return;
        if ('phase' in data) {
          clearTimeout(pendingRef.current.timer);
          pendingRef.current.timer = setTimeout(() => fail('실행 시간이 10초를 넘어 중단했습니다. WHERE 조건이나 JOIN 범위를 줄여 주세요.'), 10_000);
          setPhase('running');
          return;
        }
        clearTimeout(pendingRef.current.timer);
        pendingRef.current = null;
        worker.removeEventListener('message', onMessage);
        worker.removeEventListener('error', onError);
        setPhase('idle');
        if (!data.ok) { setError(data.error); return; }
        onApply(data.ids);
        setAppliedSql(sql);
        setNotice(`${count(data.ids.length)}명을 조회했습니다.${data.rowCount !== data.ids.length ? ' 중복 연구자 ID는 한 번만 포함했습니다.' : ''}`);
      };
      const onError = (event: ErrorEvent) => {
        event.preventDefault();
        if (pendingRef.current?.requestId === requestId) fail('SQL 실행기를 시작하지 못했습니다. 연결을 확인한 후 다시 실행해 주세요.');
      };
      worker.addEventListener('message', onMessage);
      worker.addEventListener('error', onError);
      const request: FlowSqlRequest = {
        requestId, sql, releaseYear, professorIds,
        databaseUrl: new URL(`${import.meta.env.BASE_URL}downloads/professor_dashboard_${releaseYear}.sqlite`, window.location.href).href,
      };
      worker.postMessage(request);
    } catch {
      fail('SQL 실행기를 시작하지 못했습니다. 다시 실행해 주세요.');
    }
  }

  return <section className={`sk-sql ${unlocked ? '' : 'is-locked'}`} aria-labelledby={`${id}-title`}>
    <div className="sk-sql-heading"><div><p className="sk-eyebrow">QUERY YOUR COHORT</p><h2 id={`${id}-title`}>SQL로 연구자 선택</h2><p>조건에 맞는 연구자를 조회하면 학사 → 박사 → 현재 재직 흐름에 바로 반영됩니다.</p></div><span className="sk-sql-badge">{unlocked ? '잠금 해제됨' : '잠금 상태'}</span></div>
    {!unlocked ? <div className="sk-sql-lock"><p>상단의 비밀번호로 잠금을 해제하면 SQL을 직접 입력할 수 있습니다.</p><button className="sk-button" onClick={() => { const input = document.getElementById('name-password'); input?.scrollIntoView({ block: 'center', behavior: 'instant' }); input?.focus({ preventScroll: true }); }}>비밀번호 입력으로 이동 <span aria-hidden="true">↑</span></button></div> : <>
      <div className="sk-sql-presets" aria-label="SQL 예제"><span>예제로 시작</span>{FLOW_SQL_PRESETS.map(preset => <button key={preset.label} className="sk-button" disabled={busy} onClick={() => { setSql(preset.sql); setError(''); setNotice('예제를 불러왔습니다. 실행하면 흐름도에 반영됩니다.'); document.getElementById(`${id}-editor`)?.focus(); }}>{preset.label}</button>)}</div>
      <form onSubmit={event => { event.preventDefault(); run(); }}>
        <div className="sk-sql-editor-label"><label htmlFor={`${id}-editor`}>SELECT 쿼리</label><span>Ctrl / ⌘ + Enter로 실행</span></div>
        <textarea id={`${id}-editor`} className="sk-sql-editor" value={sql} onChange={event => setSql(event.target.value)} onKeyDown={event => { if (event.key === 'Enter' && (event.ctrlKey || event.metaKey)) { event.preventDefault(); run(); } }} maxLength={MAX_FLOW_SQL_LENGTH} spellCheck={false} autoComplete="off" autoCorrect="off" autoCapitalize="off" disabled={busy} aria-describedby={`${id}-hint${error ? ` ${id}-error` : ''}`} aria-invalid={Boolean(error)} rows={6} />
        <p id={`${id}-hint`} className="sk-sql-hint"><code>professor_id</code>를 반환하는 SELECT 한 개를 입력하세요. 조회 후에는 아래 필터로 더 좁힐 수 있습니다. 이름 대신 공개 ID와 학력·재직·연구실적 필드를 사용합니다.</p>
        <div className="sk-sql-actions"><button type="submit" className="sk-button sk-sql-run" disabled={busy || !sql.trim()}>{phase === 'loading' ? '자료 불러오는 중…' : phase === 'running' ? '조회 중…' : '쿼리 실행 · 흐름도 그리기'}<span aria-hidden="true">{busy ? '…' : '→'}</span></button>{busy && <button type="button" className="sk-button" onClick={() => { terminate(); setNotice('실행을 취소했습니다. 표시 중인 흐름은 유지됩니다.'); }}>실행 취소</button>}<button type="button" className="sk-button" disabled={busy || appliedCount === null} onClick={() => { onApply(null); setAppliedSql(null); setError(''); setNotice('전체 자료로 돌아왔습니다.'); }}>전체 자료로 돌아가기</button></div>
      </form>
      <div className="sk-sql-feedback" aria-live="polite" aria-atomic="true">{!error && <p role="status">{busy ? phase === 'loading' ? '공개 자료와 SQL 실행기를 준비하고 있습니다. 첫 실행은 시간이 걸릴 수 있습니다.' : '쿼리를 실행하고 있습니다.' : notice || '예제를 선택하거나 원하는 SELECT 조건을 입력해 보세요.'}</p>}{appliedCount !== null && <p className="sk-sql-applied"><strong>현재 SQL 대상 {count(appliedCount)}명</strong>{appliedSql !== sql && <span> · 편집한 쿼리는 아직 반영되지 않았습니다.</span>}</p>}</div>
      {error && <p id={`${id}-error`} className="sk-sql-error" role="alert">{error} 표시 중인 흐름은 유지됩니다.</p>}
      <details className="sk-sql-schema"><summary>테이블·열 안내와 작성 예시</summary><div>
        <p><code>professors</code> — 연구자 기본 정보. 분야는 <code>mathematics</code>, <code>physics</code>, <code>chemistry</code>, <code>biology</code>입니다.</p>
        <dl><dt>결과에 필수</dt><dd><code>professor_id</code> — 연구자 ID. JOIN 결과의 중복 ID는 한 명으로 합칩니다.</dd><dt>소속·학력</dt><dd><code>subject</code>, <code>department</code>, <code>current_institution</code>, <code>bachelor_institution</code>, <code>phd_institution</code>, <code>phd_country</code></dd><dt>시기·실적</dt><dd><code>phd_year</code>, <code>appointment_year</code>, <code>lead_work_count</code>, <code>first_faculty_institution</code>, <code>latest_faculty_institution</code></dd><dt>함께 조회할 테이블</dt><dd><code>career_segments</code> (stage, institution, start_year, end_year), <code>yearly_lead_output</code> (year, total_count, first_author_count, corresponding_author_count), <code>professor_journal_output</code> (journal, lead_work_count). 모두 <code>professor_id</code>로 연결합니다.</dd></dl>
        <p>기관명과 국가는 영문 원문을 사용합니다. 예: <code>Seoul National University</code>, <code>Korea University (Seoul Campus)</code>, <code>United States</code>. 동일 학교의 다른 표기는 다를 수 있으며, 모교 재직 여부는 아래 ‘학부 모교 재직만 보기’ 필터로 확인할 수 있습니다.</p>
        <pre><code>{"SELECT DISTINCT p.professor_id\nFROM professors AS p\nJOIN yearly_lead_output AS y\n  ON y.professor_id = p.professor_id\nWHERE y.year >= 2020\n  AND y.corresponding_author_count >= 5;"}</code></pre>
        <p>실행하면 기관·분야 필터와 경로 선택을 초기화합니다. 조회 0명은 빈 흐름도로 표시하며, 세 기관 정보가 모두 있는 연구자만 경로에 포함합니다. SQL과 조회 결과는 이 화면에서만 유지되고, 잠그거나 다른 탭으로 이동하면 초기화됩니다.</p>
      </div></details>
    </>}
  </section>;
}
