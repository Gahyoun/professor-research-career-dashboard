import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import initSqlJs from 'sql.js';
import {
  validateFlowSql, collectFlowSqlResult, configureFlowSqlDatabase, runFlowSqlQuery,
  FLOW_SQL_PRESETS, MAX_FLOW_SQL_LENGTH, MAX_FLOW_SQL_ROWS,
} from '../work/test-dist/flowSql.js';

const SQL = await initSqlJs();
const firstId = 'P-AAAAAAAAAA', secondId = 'P-BBBBBBBBBB';
const ids = [firstId, secondId];

function fixture(year = 2026) {
  const db = new SQL.Database();
  db.run('CREATE TABLE release_metadata (key TEXT PRIMARY KEY, value TEXT); CREATE TABLE professors (professor_id TEXT PRIMARY KEY, subject TEXT, note TEXT);');
  db.run('INSERT INTO release_metadata VALUES (?, ?)', ['release_year', String(year)]);
  db.run('INSERT INTO professors VALUES (?, ?, ?), (?, ?, ?)', [firstId, 'physics', "update; 'alpha'", secondId, 'biology', 'other']);
  configureFlowSqlDatabase(db, 2026);
  return db;
}

test('accepts SELECT/CTEs with comments, quoted semicolons, escaped strings and CASE END', () => {
  for (const sql of [
    'SELECT professor_id FROM professors;',
    '/* lead; comment */ WITH chosen AS (SELECT professor_id FROM professors) SELECT professor_id FROM chosen; -- tail;',
    "SELECT professor_id FROM professors WHERE note = 'update; ''alpha''';",
    'SELECT professor_id, CASE WHEN subject = \'physics\' THEN 1 ELSE 0 END AS chosen FROM professors',
    'SELECT "professor_id", \'DELETE\' AS "update" FROM [professors]',
  ]) assert.equal(validateFlowSql(sql), sql);
});

test('rejects multiple statements, hidden writes, transaction/pragma commands and malformed inputs', () => {
  for (const sql of [
    '', '/* only comment */', '; SELECT professor_id FROM professors',
    'SELECT professor_id FROM professors; SELECT professor_id FROM professors',
    'SELECT professor_id FROM professors;;',
    'SELECT professor_id FROM professors; /* tail */ DROP TABLE professors',
    'PRAGMA query_only=OFF', 'ATTACH DATABASE \'x\' AS x',
    'WITH chosen AS (SELECT professor_id FROM professors) DELETE FROM professors RETURNING professor_id',
    'WITH chosen AS (SELECT professor_id FROM professors) UPDATE professors SET subject=\'physics\' RETURNING professor_id',
    'INSERT INTO professors VALUES (1)', 'REPLACE INTO professors VALUES (1)', 'VACUUM', 'BEGIN',
    'SELECT professor_id FROM professors /* unfinished',
    "SELECT professor_id FROM professors WHERE note='unfinished",
    'SELECT professor_id\0 FROM professors',
    `SELECT ${' '.repeat(MAX_FLOW_SQL_LENGTH)}professor_id FROM professors`,
  ]) assert.throws(() => validateFlowSql(sql), Error, sql.slice(0, 80));
});

test('deduplicates joined rows but reports raw row count and accepts an empty cohort', () => {
  assert.deepEqual(collectFlowSqlResult(['professor_id', 'total'], [[firstId, 2], [firstId, 3], [secondId, 4]], ids), { ids, rowCount: 3 });
  assert.deepEqual(collectFlowSqlResult(['PROFESSOR_ID'], [], ids), { ids: [], rowCount: 0 });
});

test('requires an unambiguous professor_id column and rejects unknown/null/non-ID values', () => {
  assert.throws(() => collectFlowSqlResult(['count'], [[3]], ids), /professor_id/);
  assert.throws(() => collectFlowSqlResult(['professor_id', 'PROFESSOR_ID'], [[firstId, secondId]], ids), /professor_id/);
  for (const value of [null, 1, new Uint8Array([1]), 'P-CCCCCCCCCC', 'not-an-id']) {
    assert.throws(() => collectFlowSqlResult(['professor_id'], [[value]], ids), /현재 공개 자료에 없는/);
  }
  function* tooMany() { for (let i = 0; i <= MAX_FLOW_SQL_ROWS; i++) yield [firstId]; }
  assert.throws(() => collectFlowSqlResult(['professor_id'], tooMany(), ids), /행을 넘었습니다/);
});

test('SQLite execution handles CTEs and zero-row results without losing column names', () => {
  const db = fixture();
  try {
    assert.deepEqual(runFlowSqlQuery(db, "WITH chosen AS (SELECT professor_id FROM professors WHERE subject='physics') SELECT professor_id FROM chosen", ids), { ids: [firstId], rowCount: 1 });
    assert.deepEqual(runFlowSqlQuery(db, "SELECT professor_id FROM professors WHERE subject='chemistry'", ids), { ids: [], rowCount: 0 });
    assert.throws(() => runFlowSqlQuery(db, 'SELECT count(*) FROM professors WHERE 0', ids), /professor_id/);
    assert.throws(() => runFlowSqlQuery(db, 'SELECT missing FROM professors', ids), /no such column/);
    // Failed queries must release statements so subsequent valid queries keep working.
    assert.deepEqual(runFlowSqlQuery(db, 'SELECT professor_id FROM professors', ids), { ids, rowCount: 2 });
  } finally { db.close(); }
});

test('query_only protects the underlying database independently of the lexical guard', () => {
  const db = fixture();
  try {
    for (const sql of ['DELETE FROM professors', "UPDATE professors SET subject='chemistry'", 'DROP TABLE professors', 'CREATE TABLE injected(x)']) {
      assert.throws(() => db.exec(sql), /readonly/i);
    }
    assert.equal(db.exec('SELECT count(*) FROM professors')[0].values[0][0], 2);
  } finally { db.close(); }
  assert.throws(() => fixture(2025), /공개 연도가 다릅니다/);
});

test('REPLACE scalar functions remain available while CTE REPLACE writes stay read-only', () => {
  const db = fixture();
  try {
    assert.deepEqual(runFlowSqlQuery(db, "SELECT REPLACE(professor_id, 'P-', 'P-') AS professor_id FROM professors", ids), { ids, rowCount: 2 });
    const write = "WITH source AS (SELECT professor_id, 'chemistry' AS subject, note FROM professors) REPLACE INTO professors SELECT * FROM source RETURNING professor_id";
    assert.equal(validateFlowSql(write), write);
    assert.throws(() => runFlowSqlQuery(db, write, ids), /readonly/i);
    assert.deepEqual(db.exec('SELECT subject FROM professors ORDER BY professor_id')[0].values, [['physics'], ['biology']]);
    assert.deepEqual(runFlowSqlQuery(db, 'SELECT professor_id FROM professors', ids), { ids, rowCount: 2 });
  } finally { db.close(); }
});

test('all shipped presets return validated IDs from the actual public SQLite release', () => {
  const db = new SQL.Database(readFileSync(new URL('../public/downloads/professor_dashboard_2026.sqlite', import.meta.url)));
  try {
    configureFlowSqlDatabase(db, 2026);
    const publicIds = db.exec('SELECT professor_id FROM professors')[0].values.map(row => row[0]);
    const expectedCounts = [3937, 299, 199, 164];
    for (const [index, preset] of FLOW_SQL_PRESETS.entries()) {
      const result = runFlowSqlQuery(db, preset.sql, publicIds);
      assert.equal(result.ids.length, expectedCounts[index], preset.label);
      assert.equal(result.rowCount, expectedCounts[index], preset.label);
    }
    const joined = runFlowSqlQuery(db, "SELECT p.professor_id FROM professors p JOIN yearly_lead_output y USING (professor_id) WHERE p.subject='physics'", publicIds);
    assert.ok(joined.rowCount > joined.ids.length);
    assert.ok(joined.ids.length > 0 && joined.ids.length <= 846);
  } finally { db.close(); }
});
