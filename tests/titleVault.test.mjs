import { test } from 'node:test';
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { mkdtempSync, readFileSync, writeFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { openTitleVault, readTitles } from '../work/test-dist/titleVault.js';

// Python writes the files (backend/topics/encrypt_titles.py); the browser code must open them.
const writer = `
import sys; sys.path.insert(0, 'backend/topics')
from encrypt_titles import write_title_vault
write_title_vault({'P-AAAAAAAAAA': [{'year': 2010, 'topic': 0, 'title': 'Secret title', 'venue': 'Phys. Rev. E', 'doi': 'https://doi.org/10.1/x'}],
                   'P-BBBBBBBBBB': [{'year': 2012, 'topic': 1, 'title': 'Other', 'venue': None, 'doi': None}]}, sys.argv[1], sys.argv[2])
`;

function withFiles(dir, fn) {
  const real = globalThis.fetch;
  globalThis.fetch = async url => {
    try { const body = readFileSync(join(dir, String(url).replace(/^base\//, ''))); return { ok: true, json: async () => JSON.parse(body) }; }
    catch { return { ok: false, json: async () => null }; }
  };
  return fn().finally(() => { globalThis.fetch = real; });
}

test('title vault: Python-encrypted files open in the browser code, per researcher', async t => {
  const dir = mkdtempSync(join(tmpdir(), 'kstem-titles-'));
  try {
    const made = spawnSync('python3', ['-I', '-c', writer, 'correct horse', dir], { encoding: 'utf8' });
    if (made.status !== 0) { t.skip(`python3 + cryptography unavailable: ${made.stderr.split('\n').filter(Boolean).pop()}`); return; }
    const files = join(dir, 'titles');
    assert.doesNotMatch(readFileSync(join(files, 'P-AAAAAAAAAA.json'), 'utf8'), /Secret|doi\.org|Phys/);
    await withFiles(files, async () => {
      assert.equal(await openTitleVault('wrong', 'base/'), null);
      const vault = await openTitleVault('correct horse', 'base/');
      assert.ok(vault);
      assert.deepEqual(await readTitles(vault, 'P-AAAAAAAAAA'), [{ year: 2010, topic: 0, title: 'Secret title', venue: 'Phys. Rev. E', doi: 'https://doi.org/10.1/x' }]);
      assert.equal(await readTitles(vault, 'P-CCCCCCCCCC'), null);
      assert.equal(await readTitles(vault, '../key'), null);
    });
    // A file moved onto another researcher's name fails the AES-GCM additional-data check.
    writeFileSync(join(files, 'P-BBBBBBBBBB.json'), readFileSync(join(files, 'P-AAAAAAAAAA.json')));
    await withFiles(files, async () => {
      const vault = await openTitleVault('correct horse', 'base/');
      assert.equal(await readTitles(vault, 'P-BBBBBBBBBB'), null);
    });
  } finally { rmSync(dir, { recursive: true, force: true }); }
});
