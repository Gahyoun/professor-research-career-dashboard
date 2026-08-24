#!/usr/bin/env node
import fs from 'node:fs/promises';
import path from 'node:path';
import zlib from 'node:zlib';
import {fileURLToPath} from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
const year = process.env.RELEASE_YEAR || '2026';
const cache = path.join(root, 'backend', 'cache', year);
const roleDirs = [path.join(cache, 'work_role_batches'), path.join(cache, 'alias_work_role_batches')];
if (!process.env.OPENALEX_API_KEY) throw new Error('OPENALEX_API_KEY is required');

const sourceIds = new Set();
for (const roleDir of roleDirs) {
  let files = [];
  try { files = (await fs.readdir(roleDir)).filter(x => x.endsWith('.jsonl.gz')).sort(); } catch {}
  for (const file of files) {
    const text = zlib.gunzipSync(await fs.readFile(path.join(roleDir, file))).toString('utf8');
    for (const line of text.split('\n')) {
      if (!line) continue;
      const id = JSON.parse(line).source?.id;
      if (id) sourceIds.add(id);
    }
  }
}

const ids = [...sourceIds].sort();
const batches = [];
for (let i = 0; i < ids.length; i += 50) batches.push(ids.slice(i, i + 50));
const result = {};
let next = 0;
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));

async function worker() {
  while (true) {
    const index = next++;
    if (index >= batches.length) return;
    const url = new URL('https://api.openalex.org/sources');
    url.searchParams.set('filter', `openalex:${batches[index].join('|')}`);
    url.searchParams.set('per_page', '100');
    url.searchParams.set('select', 'id,display_name,issn_l,issn,type,works_count,cited_by_count,summary_stats');
    url.searchParams.set('api_key', process.env.OPENALEX_API_KEY);
    let data;
    for (let attempt = 1; attempt <= 10; attempt++) {
      const res = await fetch(url, {headers: {'User-Agent': 'professor-career-dashboard/1.0'}});
      if (res.ok) { data = await res.json(); break; }
      if (res.status === 429 || res.status >= 500) {
        await sleep(Math.min(60000, attempt * attempt * 2000));
        continue;
      }
      throw new Error(`OpenAlex ${res.status}: ${await res.text()}`);
    }
    if (!data) throw new Error(`source batch ${index + 1} failed`);
    for (const source of data.results || []) result[source.id.split('/').pop()] = source;
    console.log(`source batch ${index + 1}/${batches.length}`);
  }
}

await Promise.all(Array.from({length: Math.min(8, batches.length)}, worker));
await fs.writeFile(path.join(cache, 'sources.json'), JSON.stringify(result));
console.log(JSON.stringify({requested: ids.length, fetched: Object.keys(result).length}));
