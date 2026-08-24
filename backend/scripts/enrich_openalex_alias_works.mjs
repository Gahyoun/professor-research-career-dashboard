#!/usr/bin/env node
import fs from 'node:fs/promises';
import path from 'node:path';
import zlib from 'node:zlib';
import crypto from 'node:crypto';
import {fileURLToPath} from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
const year = process.env.RELEASE_YEAR || '2026';
const cache = path.join(root, 'backend', 'cache', year);
const primaryIds = new Set(JSON.parse(await fs.readFile(path.join(cache, 'author_ids.json'), 'utf8')));
const aliasRecords = JSON.parse(await fs.readFile(path.join(cache, 'author_aliases.json'), 'utf8'));
const ids = [...new Set(aliasRecords.flatMap(row => row.openalex_ids || []).filter(id => !primaryIds.has(id)))].sort();
const outDir = path.join(cache, 'alias_work_role_batches');
await fs.mkdir(outDir, {recursive: true});
if (!process.env.OPENALEX_API_KEY) throw new Error('OPENALEX_API_KEY is required');

const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
const batches = [];
for (let i = 0; i < ids.length; i += 25) batches.push(ids.slice(i, i + 25));

async function fetchJson(url, label) {
  for (let attempt = 1; attempt <= 10; attempt++) {
    const res = await fetch(url, {headers: {'User-Agent': 'professor-career-dashboard/1.0'}});
    if (res.ok) return res.json();
    if (res.status === 429 || res.status >= 500) {
      console.error(`retry ${label} attempt=${attempt} status=${res.status}`);
      await sleep(Math.min(120000, attempt * attempt * 3000));
      continue;
    }
    throw new Error(`OpenAlex ${res.status}: ${await res.text()}`);
  }
  throw new Error(`OpenAlex failed after retries: ${label}`);
}

async function processBatch(targets) {
  const targetSet = new Set(targets);
  const hash = crypto.createHash('sha256').update(targets.join('|')).digest('hex').slice(0, 16);
  const dest = path.join(outDir, `batch_${hash}.jsonl.gz`);
  try {
    if ((await fs.stat(dest)).size > 20) return {cached: true, rows: 0};
  } catch {}
  let cursor = '*';
  let pages = 0;
  const lines = [];
  while (cursor) {
    const url = new URL('https://api.openalex.org/works');
    url.searchParams.set('filter', `author.id:${targets.join('|')},from_publication_date:1950-01-01,to_publication_date:${year}-12-31`);
    url.searchParams.set('per_page', '100');
    url.searchParams.set('cursor', cursor);
    url.searchParams.set('select', 'id,type,publication_date,publication_year,cited_by_count,primary_location,authorships');
    url.searchParams.set('api_key', process.env.OPENALEX_API_KEY);
    const data = await fetchJson(url, `alias=${hash} page=${pages}`);
    for (const work of data.results || []) {
      for (const authorship of work.authorships || []) {
        const aid = authorship.author?.id?.split('/').pop();
        if (!targetSet.has(aid)) continue;
        const source = work.primary_location?.source || null;
        lines.push(JSON.stringify({
          target_author_id: aid,
          work_id: work.id?.split('/').pop() || null,
          work_type: work.type || null,
          publication_date: work.publication_date || null,
          publication_year: work.publication_year || null,
          cited_by_count: work.cited_by_count || 0,
          author_position: authorship.author_position || null,
          is_corresponding: Boolean(authorship.is_corresponding),
          institutions: (authorship.institutions || []).map(inst => inst.id?.split('/').pop()).filter(Boolean),
          source: source ? {
            id: source.id?.split('/').pop() || null,
            display_name: source.display_name || null,
            issn_l: source.issn_l || null,
            type: source.type || null,
          } : null,
        }));
      }
    }
    pages++;
    cursor = data.results?.length ? data.meta?.next_cursor : null;
    await sleep(120);
  }
  const tmp = `${dest}.tmp`;
  await fs.writeFile(tmp, zlib.gzipSync(lines.length ? `${lines.join('\n')}\n` : '', {level: 6}));
  await fs.rename(tmp, dest);
  console.log(`alias batch ${hash}: pages=${pages}, rows=${lines.length}`);
  return {cached: false, rows: lines.length};
}

const concurrency = 6;
for (let start = 0; start < batches.length; start += concurrency) {
  await Promise.all(batches.slice(start, start + concurrency).map(processBatch));
}
console.log(JSON.stringify({year, alias_authors: ids.length, batches: batches.length}));
