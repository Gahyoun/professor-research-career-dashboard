import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import test from 'node:test';

// Uses only the released anonymous files; never reads a password, a private DB,
// a plaintext name map, or the HMAC salt. Override the repository for another
// working copy with DASHBOARD_REPO=/absolute/path node --test this-file.mjs.
const repo = process.env.DASHBOARD_REPO || fileURLToPath(new URL('../', import.meta.url));
const readJSON = async relative => JSON.parse(await readFile(path.join(repo, relative), 'utf8'));
const dashboard = await readJSON('public/data/dashboard.json');
const encrypted = await readJSON('public/data/encrypted_names.json');
const released = await readJSON('data/releases/2026/dashboard.json');

const professorFields = [
  'id', 'subject', 'current_institution', 'department', 'bachelor_institution',
  'phd_institution', 'phd_country', 'phd_year', 'appointment_year',
  'first_faculty_institution', 'latest_faculty_institution', 'career', 'yearly',
  'lead_work_count', 'journals',
];
const careerFields = ['stage', 'position_no', 'institution', 'start_period', 'end_period', 'start_year', 'end_year', 'confidence', 'is_institution_successor', 'evidence_basis', 'is_estimated'];
const yearlyFields = ['year', 'stage', 'total', 'first_author', 'corresponding_author', 'impact_low', 'impact_medium', 'impact_high', 'impact_unknown', 'mean_journal_2yr_citedness', 'article_citations'];
const journalFields = ['journal', 'lead_work_count', 'openalex_2yr_mean_citedness'];

function assertKeys(value, expected, location) {
  assert.deepEqual(Object.keys(value).sort(), [...expected].sort(), `${location}: unexpected public schema field`);
}

function walk(value, visit, location = '$') {
  if (Array.isArray(value)) value.forEach((entry, index) => walk(entry, visit, `${location}[${index}]`));
  else if (value && typeof value === 'object') {
    for (const [key, entry] of Object.entries(value)) {
      visit(key, entry, location);
      walk(entry, visit, `${location}.${key}`);
    }
  }
}

test('2026 public graph source covers all 3,937 anonymous researchers without sampling', () => {
  assert.equal(dashboard.meta.release_year, 2026);
  assert.equal(dashboard.meta.professor_count, 3937);
  assert.equal(dashboard.professors.length, 3937);
  assert.equal(new Set(dashboard.professors.map(person => person.id)).size, 3937);
  for (const person of dashboard.professors) {
    assert.ok(/^P-[A-Z2-7]{10}$/.test(person.id), 'Every public researcher ID must use the HMAC-derived anonymous format');
    assertKeys(person, professorFields, 'professor');
    person.career.forEach(row => assertKeys(row, careerFields, 'career'));
    person.yearly.forEach(row => assertKeys(row, yearlyFields, 'yearly'));
    person.journals.forEach(row => assertKeys(row, journalFields, 'journal'));
  }
});

test('public researcher payload excludes name fields, original identifiers and work-level links', () => {
  const forbiddenKeys = /^(?:name|names|fullname|namekr|nameen|professorname|displayname|rawid|sourceid|professoruid|sourceprofessorid|openalexid|authorid|orcid|doi|email|password|privatekey|anonsalt|workid|worktitle)$/i;
  const forbiddenValues = /(?:https?:\/\/)?(?:openalex\.org\/A\d+|orcid\.org\/\d|doi\.org\/10\.)|\b10\.\d{4,9}\/[\w.()[\];:/-]+|\b\d{4}-\d{4}-\d{4}-\d{3}[\dX]\b/i;
  walk(dashboard.professors, (key, value, location) => {
    assert.ok(!forbiddenKeys.test(key.replace(/[_-]/g, '')), `${location}: forbidden private field ${key}`);
    if (typeof value === 'string') assert.ok(!forbiddenValues.test(value), `${location}.${key}: private identifier or work-level link found`);
  });
  assert.equal(dashboard.meta.names_encrypted, true);
});

test('existing public release stays unchanged when adding the constellation UI', () => {
  assert.deepEqual(dashboard, released);
});

test('name bundle remains an authenticated ciphertext envelope, with unchanged strong KDF parameters', () => {
  assertKeys(encrypted, ['version', 'kdf', 'iterations', 'salt', 'nonce', 'aad', 'ciphertext'], 'encrypted bundle');
  assert.equal(encrypted.version, 1);
  assert.equal(encrypted.kdf, 'PBKDF2-SHA256');
  assert.ok(encrypted.iterations >= 600000);
  for (const field of ['salt', 'nonce', 'aad', 'ciphertext']) {
    assert.ok(/^[A-Za-z0-9+/]+={0,2}$/.test(encrypted[field]), `${field}: expected base64 envelope field`);
    assert.equal(Buffer.from(encrypted[field], 'base64').toString('base64'), encrypted[field]);
  }
  assert.ok(Buffer.from(encrypted.salt, 'base64').length >= 16);
  assert.equal(Buffer.from(encrypted.nonce, 'base64').length, 12);
  assert.ok(Buffer.from(encrypted.ciphertext, 'base64').length > 16);
});

test('public dates retain the estimated-period flag instead of implying verified co-attendance', () => {
  const doctoral = dashboard.professors.flatMap(person => person.career.filter(segment => segment.stage === 'doctoral'));
  assert.equal(doctoral.length, 3729);
  assert.equal(dashboard.professors.filter(person => person.phd_year == null).length, 208);
  for (const segment of doctoral) {
    assert.equal(segment.is_estimated, true);
    assert.equal(segment.confidence, 'estimated');
    assert.equal(segment.end_year - segment.start_year, 5);
    assert.ok(segment.evidence_basis.includes('추정'));
  }
});

test('adding the constellation preserves the existing encrypted name bundle byte-for-byte', async () => {
  const publicBytes = await readFile(path.join(repo, 'public/data/encrypted_names.json'));
  const releaseBytes = await readFile(path.join(repo, 'data/releases/2026/encrypted_names.json'));
  assert.equal(Buffer.compare(publicBytes, releaseBytes), 0);
});
