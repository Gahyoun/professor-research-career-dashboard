import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { parseResearcherQuery, containsTerm, indexResearchers, searchResearchers, matchContext } from '../work/test-dist/researcherQuery.js';
import { normalizeResearchAreas, bestAreaMatch } from '../work/test-dist/researchAreas.js';

const people = [
  { id: 'P-AAAAAAAAAA', subject: 'physics', current_institution: 'Gyeongsang National University', bachelor_institution: 'Seoul National University', phd_institution: 'Korea Advanced Institute of Science and Technology' },
  { id: 'P-BBBBBBBBBB', subject: 'chemistry', current_institution: 'Seoul National University', bachelor_institution: 'Korea University', phd_institution: 'Seoul National University' },
  { id: 'P-CCCCCCCCCC', subject: 'mathematics', current_institution: 'Korea University', bachelor_institution: 'Korea University', phd_institution: 'Massachusetts Institute of Technology' },
];
const areas = normalizeResearchAreas({
  schema: 'kstem-research-areas/2', release_year: 2026,
  domains: ['Physical Sciences'], fields: [['Physics and Astronomy', 0], ['Mathematics', 0]],
  subfields: [['Statistical and Nonlinear Physics', 0], ['Applied Mathematics', 1]],
  topics: [['Complex Network Analysis Techniques', 0], ['Stochastic processes', 1]],
  researchers: {
    'P-AAAAAAAAAA': { n: 10, f: [[0, 8]], s: [[0, 6]], t: [[0, 4]] },
    'P-CCCCCCCCCC': { n: 20, f: [[1, 20]], s: [[1, 18]], t: [[1, 2], [0, 10]] },
  },
});
const ids = (text, names = null) => searchResearchers(indexResearchers(people, names, areas.profiles), text).map(hit => hit.person.id);

test('field prefixes scope each value; free words match any field', () => {
  assert.deepEqual(parseResearcherQuery('학부:서울대 박사: kaist 계열:물리 extra'), { free: ['extra'], scoped: [
    { field: 'bachelor', terms: ['서울대'] }, { field: 'phd', terms: ['kaist'] }, { field: 'subject', terms: ['물리'] }] });
  assert.deepEqual(parseResearcherQuery('박사:"seoul national"').scoped, [{ field: 'phd', terms: ['seoul', 'national'] }]);
  assert.deepEqual(ids('학부:서울대'), ['P-AAAAAAAAAA']);
  assert.deepEqual(ids('재직:서울대'), ['P-BBBBBBBBBB']);
  assert.deepEqual(ids('박사:서울대'), ['P-BBBBBBBBBB']);
  assert.deepEqual(ids('서울대').sort(), ['P-AAAAAAAAAA', 'P-BBBBBBBBBB']);
  assert.deepEqual(ids('계열:화학'), ['P-BBBBBBBBBB']);
  assert.deepEqual(ids('계열:수학 학부:고려대'), ['P-CCCCCCCCCC']);
  assert.deepEqual(ids('박사:MIT'), ['P-CCCCCCCCCC']);
  assert.equal(containsTerm('smith college', 'mit'), false);
  assert.equal(containsTerm('mit-harvard center', 'mit'), true);
});

test('names are searchable only when the caller passes decrypted names', () => {
  assert.deepEqual(ids('홍길동'), []);
  assert.deepEqual(ids('홍길동', { 'P-BBBBBBBBBB': '홍길동' }), ['P-BBBBBBBBBB']);
});

test('OpenAlex areas: hierarchy paths, scoped search ranked by share, explained in the result line', () => {
  const profile = areas.profiles.get('P-CCCCCCCCCC');
  assert.deepEqual(profile.topics[1].path, ['Physical Sciences', 'Physics and Astronomy', 'Statistical and Nonlinear Physics', 'Complex Network Analysis Techniques']);
  assert.equal(bestAreaMatch(profile, ['network']).share, 0.5);
  assert.deepEqual(ids('연구:network'), ['P-CCCCCCCCCC', 'P-AAAAAAAAAA']); // 50% before 40%
  assert.deepEqual(ids('연구:"nonlinear physics"'), ['P-AAAAAAAAAA']);
  const [hit] = searchResearchers(indexResearchers(people, null, areas.profiles), '학부:서울대 network');
  assert.equal(matchContext(hit), '학부 Seoul National University · Complex Network Analysis Techniques 40%');
  assert.equal(normalizeResearchAreas({ schema: 'other' }), null);
});

test('shipped research_areas.json parses and covers released researchers only', () => {
  const raw = JSON.parse(readFileSync(new URL('../public/data/research_areas.json', import.meta.url), 'utf8'));
  const dashboard = JSON.parse(readFileSync(new URL('../public/data/dashboard.json', import.meta.url), 'utf8'));
  const parsed = normalizeResearchAreas(raw);
  const released = new Set(dashboard.professors.map(p => p.id));
  assert.ok(parsed.profiles.size > 3000);
  for (const id of parsed.profiles.keys()) assert.ok(released.has(id));
  assert.equal(parsed.releaseYear, dashboard.meta.release_year);
  assert.doesNotMatch(JSON.stringify(raw), /https?:|doi|W\d{6,}|A\d{6,}/i);
});
