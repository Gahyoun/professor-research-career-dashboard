import assert from 'node:assert/strict';
import { test } from 'node:test';
import { currentInstitutionName, isInstitutionSuccession, applyInstitutionSuccessions } from '../work/test-dist/institutionSuccession.js';

test('merger identity changes only at its dated annual boundary and uses explicit aliases', () => {
  const old = 'Gyeongnam National University of Science and Technology';
  assert.equal(currentInstitutionName(old, 2020), old);
  assert.equal(currentInstitutionName(old, 2021), '경상국립대학교');
  assert.equal(currentInstitutionName('Gangneung–Wonju National University', 2025), 'Gangneung–Wonju National University');
  assert.equal(currentInstitutionName('Gangneung–Wonju National University', 2026), '강원대학교 (통합)');
  assert.equal(currentInstitutionName('Gyeongsangnam-do Agricultural Research and Extension Services', 2026), 'Gyeongsangnam-do Agricultural Research and Extension Services');
  assert.equal(currentInstitutionName('Kangwon National University Hospital', 2026), 'Kangwon National University Hospital');
});
test('pre-merger moves and moves to unrelated institutions are not succession exceptions', () => {
  assert.equal(isInstitutionSuccession('경남과기대', '경상대', 2020), false);
  assert.equal(isInstitutionSuccession('경남과기대', '경상국립대', 2021), true);
  assert.equal(isInstitutionSuccession('강릉원주대', '강원대', 2025), false);
  assert.equal(isInstitutionSuccession('강릉원주대', '강원대', 2026), true);
  assert.equal(isInstitutionSuccession('경상대', '강원대', 2026), false);
});
test('current grouping and dated succession badges preserve raw degree/career names and inputs', () => {
  const row = (institution, start_year) => ({ stage: 'faculty', institution, start_year, end_year: 2026, is_institution_successor: false, evidence_basis: 'source' });
  const input = {meta:{release_year:2026},filters:{current_institutions:['강릉원주대','강원대']},professors:[
    {id:'a',current_institution:'강릉원주대',phd_institution:'강릉원주대',current_position:{institution:'강릉원주대',observation_year:2025},career:[row('강릉원주대',2020),row('강원대',2026)]},
    {id:'b',current_institution:'강원대',career:[row('강릉원주대',2020),row('강원대',2025)]},
  ]};
  const original = JSON.stringify(input), result = applyInstitutionSuccessions(input);
  assert.equal(JSON.stringify(input), original);
  assert.deepEqual(result.filters.current_institutions,['강원대학교 (통합)']);
  assert.equal(result.professors[0].phd_institution,'강릉원주대');
  assert.equal(result.professors[0].career[0].institution,'강릉원주대');
  assert.equal(result.professors[0].career[1].is_institution_successor,true);
  assert.equal(result.professors[1].career[1].is_institution_successor,false);
  assert.equal(result.professors[0].current_position.observation_year,2025);
  assert.deepEqual(applyInstitutionSuccessions(result),result);
});
