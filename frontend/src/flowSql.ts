import type { Database, SqlValue } from 'sql.js';
import type { ResearchAreas } from './researchAreas';

export class FlowSqlError extends Error {}

export const MAX_FLOW_SQL_LENGTH = 20_000;
export const MAX_FLOW_SQL_ROWS = 100_000;

export type FlowSqlRequest = {
  requestId: number;
  sql: string;
  databaseUrl: string;
  /** Optional OpenAlex research areas JSON; becomes the professor_research_areas table. */
  areasUrl?: string;
  releaseYear: number;
  professorIds: string[];
};
export type FlowSqlResponse =
  | { requestId: number; phase: 'ready' }
  | { requestId: number; ok: true; ids: string[]; rowCount: number }
  | { requestId: number; ok: false; error: string };
export type FlowSqlResult = { ids: string[]; rowCount: number };

export const FLOW_SQL_PRESETS: readonly { label: string; sql: string }[] = [
  { label: '전체 연구자', sql: 'SELECT professor_id\nFROM professors;' },
  { label: '물리 · 미국 박사', sql: "SELECT professor_id\nFROM professors\nWHERE subject = 'physics'\n  AND phd_country = 'United States';" },
  { label: '서울대학교 재직', sql: "SELECT professor_id\nFROM professors\nWHERE current_institution = 'Seoul National University';" },
  { label: '주저자 논문 100편 이상', sql: 'SELECT professor_id\nFROM professors\nWHERE lead_work_count >= 100;' },
  { label: 'OpenAlex · 통계·비선형 물리 20% 이상', sql: "SELECT professor_id\nFROM professor_research_areas\nWHERE level = 'subfield'\n  AND area = 'Statistical and Nonlinear Physics'\n  AND share >= 0.2;" },
  { label: '화학과 · OpenAlex 재료과학 중심', sql: "SELECT a.professor_id\nFROM professor_research_areas a\nJOIN professors p USING (professor_id)\nWHERE p.subject = 'chemistry'\n  AND a.level = 'field'\n  AND a.area = 'Materials Science'\n  AND a.share >= 0.4;" },
];

export const FLOW_SQL_SCHEMA = [
  { table: 'professors', columns: 'professor_id, subject, current_institution, department, bachelor_institution, phd_institution, phd_country, phd_year, appointment_year, first_faculty_institution, latest_faculty_institution, lead_work_count' },
  { table: 'career_segments', columns: 'professor_id, stage, institution, start_year, end_year, confidence, is_estimated' },
  { table: 'yearly_lead_output', columns: 'professor_id, year, career_stage, total_count, first_author_count, corresponding_author_count, mean_journal_2yr_citedness, article_citations_total' },
  { table: 'professor_journal_output', columns: 'professor_id, journal, lead_work_count, openalex_2yr_mean_citedness' },
  { table: 'professor_research_areas', columns: 'professor_id, level (field·subfield·topic), area, subfield, field, domain, work_count, share' },
] as const;

const forbiddenWords = new Set([
  'INSERT', 'UPDATE', 'DELETE', 'CREATE', 'ALTER', 'DROP',
  'PRAGMA', 'ATTACH', 'DETACH', 'VACUUM', 'REINDEX', 'ANALYZE',
  'BEGIN', 'COMMIT', 'ROLLBACK', 'SAVEPOINT', 'RELEASE',
]);

/** Inspect SQL syntax outside strings, quoted identifiers and comments.
 * This is an allowlist guard, not a replacement for SQLite's parser/query_only.
 */
export function validateFlowSql(sql: string): string {
  if (typeof sql !== 'string' || !sql.trim()) throw new FlowSqlError('SELECT 조회문을 입력해 주세요.');
  if (sql.length > MAX_FLOW_SQL_LENGTH) throw new FlowSqlError(`SQL은 ${MAX_FLOW_SQL_LENGTH.toLocaleString()}자 이내로 입력해 주세요.`);
  if (sql.includes('\0')) throw new FlowSqlError('SQL에 사용할 수 없는 문자가 포함되어 있습니다.');
  let index = 0, firstWord = '', terminated = false;
  while (index < sql.length) {
    const char = sql[index], next = sql[index + 1];
    if (/\s/.test(char)) { index += 1; continue; }
    if (char === '-' && next === '-') {
      index += 2;
      while (index < sql.length && sql[index] !== '\n' && sql[index] !== '\r') index += 1;
      continue;
    }
    if (char === '/' && next === '*') {
      const end = sql.indexOf('*/', index + 2);
      if (end < 0) throw new FlowSqlError('SQL 주석을 닫아 주세요.');
      index = end + 2;
      continue;
    }
    if (terminated) throw new FlowSqlError('SELECT 조회문은 한 번에 하나만 실행할 수 있습니다.');
    if (char === ';') { terminated = true; index += 1; continue; }
    if (char === "'" || char === '"' || char === '`' || char === '[') {
      const endQuote = char === '[' ? ']' : char;
      index += 1;
      let closed = false;
      while (index < sql.length) {
        if (sql[index] === endQuote) {
          if (char !== '[' && sql[index + 1] === endQuote) { index += 2; continue; }
          index += 1; closed = true; break;
        }
        index += 1;
      }
      if (!closed) throw new FlowSqlError('SQL 문자열 또는 식별자의 따옴표를 닫아 주세요.');
      if (!firstWord) throw new FlowSqlError('SELECT 또는 WITH로 시작하는 조회문만 실행할 수 있습니다.');
      continue;
    }
    if (/[A-Za-z_]/.test(char)) {
      const start = index++;
      while (index < sql.length && /[A-Za-z0-9_$]/.test(sql[index])) index += 1;
      const word = sql.slice(start, index).toUpperCase();
      if (!firstWord) {
        firstWord = word;
        if (word !== 'SELECT' && word !== 'WITH') throw new FlowSqlError('SELECT 또는 WITH로 시작하는 조회문만 실행할 수 있습니다.');
      }
      if (forbiddenWords.has(word)) throw new FlowSqlError('데이터를 변경하는 명령과 PRAGMA는 실행할 수 없습니다. SELECT 조회문을 사용해 주세요.');
      continue;
    }
    if (!firstWord) throw new FlowSqlError('SELECT 또는 WITH로 시작하는 조회문만 실행할 수 있습니다.');
    index += 1;
  }
  if (!firstWord) throw new FlowSqlError('SELECT 조회문을 입력해 주세요.');
  return sql;
}

export function collectFlowSqlResult(
  columns: readonly string[], rows: Iterable<readonly SqlValue[]>, professorIds: readonly string[],
): FlowSqlResult {
  const indexes = columns.flatMap((column, index) => column.toLowerCase() === 'professor_id' ? [index] : []);
  if (indexes.length !== 1) throw new FlowSqlError('조회 결과에 professor_id 열을 정확히 하나 포함해 주세요.');
  const knownIds = new Set(professorIds), ids = new Set<string>();
  let rowCount = 0;
  for (const row of rows) {
    rowCount += 1;
    if (rowCount > MAX_FLOW_SQL_ROWS) throw new FlowSqlError(`조회 결과가 ${MAX_FLOW_SQL_ROWS.toLocaleString()}행을 넘었습니다. 조건을 좁히거나 DISTINCT professor_id를 사용해 주세요.`);
    const value = row[indexes[0]];
    if (typeof value !== 'string' || !/^P-[A-Z2-7]{10}$/.test(value) || !knownIds.has(value)) {
      throw new FlowSqlError('조회 결과에 현재 공개 자료에 없는 professor_id가 있습니다. professors 테이블의 professor_id를 반환해 주세요.');
    }
    ids.add(value);
  }
  return { ids: [...ids], rowCount };
}

/** Load OpenAlex areas into an application-owned table. Runs before query_only and before any user SQL. */
export function attachResearchAreas(database: Database, areas: ResearchAreas): number {
  database.run(`CREATE TABLE IF NOT EXISTS professor_research_areas (
    professor_id TEXT NOT NULL, level TEXT NOT NULL, area TEXT NOT NULL, subfield TEXT, field TEXT, domain TEXT,
    work_count INTEGER NOT NULL, share REAL NOT NULL)`);
  const insert = database.prepare('INSERT INTO professor_research_areas VALUES (?, ?, ?, ?, ?, ?, ?, ?)');
  let count = 0;
  try {
    database.run('BEGIN');
    for (const [id, profile] of areas.profiles) {
      for (const area of [...profile.fields, ...profile.subfields, ...profile.topics]) {
        const [domain = null, field = null, subfield = null] = area.path;
        insert.run([id, area.level, area.name, area.level === 'field' ? null : subfield, field, domain, area.works, Math.round(area.share * 1e4) / 1e4]);
        count += 1;
      }
    }
    database.run('COMMIT');
  } finally { insert.free(); }
  return count;
}

/** Configure only application-owned pragmas before accepting any user SQL. */
export function configureFlowSqlDatabase(database: Database, releaseYear: number): void {
  const statement = database.prepare("SELECT value FROM release_metadata WHERE key = 'release_year'");
  try {
    if (!statement.step() || Number(statement.get()[0]) !== releaseYear) throw new FlowSqlError('SQL 자료와 현재 화면의 공개 연도가 다릅니다. 화면을 새로고침해 주세요.');
  } finally { statement.free(); }
  database.run('PRAGMA query_only = ON;');
}

export function runFlowSqlQuery(database: Database, sql: string, professorIds: readonly string[]): FlowSqlResult {
  validateFlowSql(sql);
  // A parser-backed second check supplements the lexical statement boundary guard.
  let result: FlowSqlResult | undefined;
  // for..of finalizes the iterator even when validation or stepping throws.
  for (const statement of database.iterateStatements(sql)) {
    if (result) throw new FlowSqlError('SELECT 조회문은 한 번에 하나만 실행할 수 있습니다.');
    const columns = statement.getColumnNames();
    // Read names before stepping: a valid query returning zero rows remains valid.
    function* rows(): Generator<SqlValue[]> {
      while (statement.step()) yield statement.get();
    }
    result = collectFlowSqlResult(columns, rows(), professorIds);
  }
  if (!result) throw new FlowSqlError('SELECT 조회문을 입력해 주세요.');
  return result;
}
