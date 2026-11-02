import initSqlJs from 'sql.js';
import type { Database } from 'sql.js';
// Vite uses sql.js's browser export; keep its WASM companion from the same build.
import wasmUrl from 'sql.js/dist/sql-wasm-browser.wasm?url';
import { configureFlowSqlDatabase, FlowSqlError, runFlowSqlQuery, validateFlowSql } from './flowSql';
import type { FlowSqlRequest, FlowSqlResponse } from './flowSql';

let database: Database | null = null;
let databaseKey = '';
let busy = false;

function respond(message: FlowSqlResponse) { self.postMessage(message); }

self.onmessage = async (event: MessageEvent<FlowSqlRequest>) => {
  const request = event.data;
  if (busy) { respond({ requestId: request.requestId, ok: false, error: '이전 SQL 조회가 끝난 뒤 다시 실행해 주세요.' }); return; }
  busy = true;
  let ready = false;
  try {
    validateFlowSql(request.sql);
    if (!Number.isInteger(request.releaseYear) || !Array.isArray(request.professorIds) || !request.professorIds.every(id => typeof id === 'string')) {
      throw new FlowSqlError('SQL 조회 자료를 확인할 수 없습니다. 화면을 새로고침해 주세요.');
    }
    const url = new URL(request.databaseUrl, self.location.href);
    if (url.origin !== self.location.origin || !['http:', 'https:'].includes(url.protocol)) throw new FlowSqlError('같은 서비스의 공개 SQL 자료만 불러올 수 있습니다.');
    const key = `${request.releaseYear}:${url.href}`;
    if (!database || databaseKey !== key) {
      database?.close(); database = null; databaseKey = '';
      const [SQL, response] = await Promise.all([
        initSqlJs({ locateFile: () => wasmUrl }),
        fetch(url.href, { credentials: 'omit' }),
      ]);
      if (!response.ok) throw new FlowSqlError('공개 SQL 자료를 불러오지 못했습니다. 잠시 후 다시 실행해 주세요.');
      const opened = new SQL.Database(new Uint8Array(await response.arrayBuffer()));
      try { configureFlowSqlDatabase(opened, request.releaseYear); }
      catch (error) { opened.close(); throw error; }
      database = opened; databaseKey = key;
    }
    ready = true;
    respond({ requestId: request.requestId, phase: 'ready' });
    const result = runFlowSqlQuery(database, request.sql, request.professorIds);
    respond({ requestId: request.requestId, ok: true, ...result });
  } catch (error) {
    // SQL.js parser messages contain no rows; never send SQL source or names to logs.
    const detail = error instanceof FlowSqlError ? error.message : ready
      ? 'SQL 구문과 테이블·열 이름을 확인해 주세요. professor_id를 반환하는 SELECT 조회문만 실행할 수 있습니다.'
      : 'SQL 실행기와 공개 자료를 준비하지 못했습니다. 연결을 확인한 후 다시 실행해 주세요.';
    respond({ requestId: request.requestId, ok: false, error: detail });
  } finally { busy = false; }
};
