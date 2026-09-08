import assert from 'node:assert/strict';
import { test } from 'node:test';
import { buildTemporalInstitutions, normalizedStageEntropy, jaccard, nodeOverlapAwareSimilarity } from '../work/test-dist/temporalInstitutions.js';
const c = (institution, start_year, end_year, extra = {}) => ({ institution, country: 'US', stage: 'faculty', start_year, end_year, is_estimated: false, ...extra });
const p = (id, career) => ({ id, subject: 'physics', career });
const build = (rows, extra = {}) => buildTemporalInstitutions(rows, { releaseYear: 2024, includeEstimated: false, ...extra });
test('hand-calculated adjacent-year Jaccard and turnover', () => {
 const d = build([p('a',[c('A',2020,2021)]),p('b',[c('A',2020,2022)]),p('c',[c('A',2021,2022)])]);
 const a=d.institutions[0];assert.equal(a.years[0].active,2); assert.equal(a.years[1].active,3);assert.equal(a.years[1].jaccard,2/3);assert.equal(a.years[1].turnover,1-2/3);assert.equal(a.years[2].jaccard,2/3);assert.equal(a.years[4].jaccard,null);
});
test('individual starts/ends are censored, real adjacent institutional changes count, release cutoff never becomes departure', () => {
 const d=build([p('a',[c('A',2020,2024)]),p('b',[c('B',2020,2020),c('A',2021,2021),c('B',2022,2024)]),p('c',[c('A',2021,2021)])]);
 const a=d.institutions.find(i=>i.label==='A');
 assert.equal(a.years[0].entries,null);assert.equal(a.years[0].leftCensored,1);
 assert.equal(a.years[1].entries,1);assert.equal(a.years[1].leftCensored,1);
 assert.equal(a.years[2].exits,1);assert.equal(a.years[2].rightCensored,1);
 assert.equal(a.years.at(-1).year,2024);assert.equal(a.years.at(-1).exits,0);assert.equal(a.years.at(-1).rightCensored,0);
});
test('missing intermediate years never imply confirmed institutional transitions', () => {
 const d=build([p('a',[c('A',2020,2020),c('B',2023,2024)])]); const a=d.institutions.find(i=>i.label==='A');
 assert.equal(a.years[1].exits,0);assert.equal(a.years[1].rightCensored,1);
});
test('same researcher/unit/year duplicate intervals do not inflate size or stages, identities never leave metric output', () => {
 const person=p('PRIVATE-ID',[c('A',2020,2024),c('A',2020,2024)]);const d=build([person,person]);
 assert.equal(d.duplicateIds,1);assert.equal(d.institutions[0].years[0].active,1);assert.equal(d.institutions[0].years[0].hyperedges,0);assert.equal(d.institutions[0].years[0].singletonUnits,1);assert.equal(d.institutions[0].years[0].stages.faculty,1);assert.ok(!JSON.stringify(d).includes('PRIVATE-ID'));
});
test('domestic department hyperedges remain separate with cross-department overlap counted once', () => {
 const a=c('A',2020,2024,{country:'KR',department:'Physics'}); const b=c('A',2020,2024,{country:'KR',department:'Math'});
 const d=build([p('x',[a,b]),p('y',[a]),p('z',[b])]);const v=d.institutions[0].years[0];
 assert.equal(v.active,3);assert.equal(v.hyperedges,2);assert.equal(v.meanHyperedgeSize,2);assert.equal(v.crossDepartmentPeople,1);assert.equal(v.crossDepartmentShare,1/3);
});
test('strict inferred-department filter retains empty institution catalogue without inventing zero observations', () => {
 const rows=[p('x',[c('A',2020,2024,{country:'KR',department:'Math',department_inferred:true})])];
 const strict=build(rows);assert.equal(strict.institutions.length,1);assert.equal(strict.institutions[0].years.length,0);assert.equal(strict.eligiblePeople,0);
 assert.equal(build(rows,{includeInferredDepartments:true}).institutions[0].years[0].active,1);
});
test('fixed-three-stage entropy handles concurrent stages with one researcher mass', () => {
 assert.equal(normalizedStageEntropy({doctoral:1,postdoc:1,faculty:1}),1);assert.equal(normalizedStageEntropy({doctoral:0,postdoc:0,faculty:1}),0);assert.equal(normalizedStageEntropy({doctoral:0,postdoc:0,faculty:0}),null);
 const d=build([p('a',[c('A',2020,2024,{stage:'postdoc'}),c('A',2020,2024)])]);const v=d.institutions[0].years[0];assert.equal(v.active,1);assert.equal(v.stages.postdoc,.5);assert.equal(v.stages.faculty,.5);assert.ok(Math.abs(v.stageDiversity-Math.log(2)/Math.log(3))<1e-12);
});
test('empty sets and future-only records remain empty',()=>{assert.equal(jaccard(new Set(),new Set()),null);assert.equal(build([]).institutions.length,0);assert.equal(build([p('a',[c('A',2030,2035)])]).institutions.length,0)});
test('selected 2026 δNOA formula gives symmetric partial, identical, disjoint and foreign single-edge matches',()=>{
 const set=(...ids)=>new Set(ids);
 assert.equal(nodeOverlapAwareSimilarity([set('a','b')],[set('a','c')]),1/3);
 assert.equal(nodeOverlapAwareSimilarity([set('a','b')],[set('c','d')]),0);
 assert.equal(nodeOverlapAwareSimilarity([set('a','b'),set('c','d')],[set('c','d'),set('a','b')]),1);
 assert.equal(nodeOverlapAwareSimilarity([set('a','b')],[set('a','b','c')]),2/3);
 assert.equal(nodeOverlapAwareSimilarity([set('a','b')],[]),null);
 assert.equal(nodeOverlapAwareSimilarity([set('a')],[set('a','b')]),null);
 // Simple hypergraph comparison deduplicates identical membership, even with distinct source unit labels.
 assert.equal(nodeOverlapAwareSimilarity([set('a','b'),set('b','a')],[set('a','b')]),1);
});
test('institutional δNOA detects a group split while total-roster Jaccard stays 1',()=>{
 const rows=['a','b','c','d'].map((id,index)=>p(id,[c('A',2020,2020,{country:'KR',department:'Together'}),c('A',2021,2024,{country:'KR',department:index<2?'Left':'Right'})]));
 const d=build(rows);const v=d.institutions[0].years[1];
 assert.equal(v.jaccard,1);assert.equal(v.hyperedgeContinuity,.5);assert.equal(v.hyperedges,2);
 assert.equal(d.institutions[0].years[2].hyperedgeContinuity,1);
 const prev=[new Set(['a','b','c','d'])],next=[new Set(['a','b']),new Set(['c','d'])];
 assert.equal(nodeOverlapAwareSimilarity(prev,next),nodeOverlapAwareSimilarity(next,prev));
});
