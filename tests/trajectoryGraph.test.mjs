import assert from 'node:assert/strict';
import test from 'node:test';
import {buildTrajectoryHypergraph} from '../work/test-dist/constellation/trajectoryGraph.js';
const record=(id,phd_institution,phd_year,start=2000,end=2002,institution='Harvard',country='US',department)=>({
  id,phd_institution,phd_country:'US',phd_year,career:[{stage:'postdoc',institution,country,department,start_year:start,end_year:end,is_estimated:false}],
});

test('shared postdoc becomes a true cohort despite disjoint doctoral schools/eras',()=>{
  const graph=buildTrajectoryHypergraph([record('A','Oxford',1995),record('B','MIT',2010)],'A');
  assert.equal(graph.edges.length,1);assert.equal(graph.edges[0].kind,'cohort');
  assert.deepEqual(graph.edges[0].members,[0,1]);assert.deepEqual(graph.edges[0].years,[2000,2001,2002]);
  assert.deepEqual(graph.incidence,[[0],[0]]);assert.equal(graph.edges[0].weight,2);
  assert.deepEqual(graph.nodes.map(n=>n.layoutYear),[2001,2001]);
});

test('era, school and domestic department mismatches never create a cohort',()=>{
  const rows=[record('A','X',1990,2000,2002,'SNU','KR','Physics'),record('B','Y',2010,2003,2005,'SNU','KR','Physics'),record('C','Z',2020,2000,2002,'SNU','KR','Math'),record('D','Q',2030,2000,2002,'KAIST','KR','Physics')];
  const graph=buildTrajectoryHypergraph(rows,'A');assert.equal(graph.edges.length,0);assert.equal(graph.nodes.length,4);assert.equal(graph.diagnostics.isolatedCount,4);
});

test('annual memberships are exact and deduplicate only within the same unit',()=>{
  const graph=buildTrajectoryHypergraph([record('A','X',1990,2000,2004),record('B','Y',2010,2000,2002),record('C','Z',2020,2002,2004)],'A');
  assert.equal(graph.edges.length,3);
  assert.deepEqual(graph.edges.map(e=>[e.years,e.members]),[[[2000,2001],[0,1]],[[2002],[0,1,2]],[[2003,2004],[0,2]]]);
  assert.ok(graph.edges.every(e=>e.overlapAdjustment<1));
});

test('duplicates never duplicate selected/peer members and private names are stripped',()=>{
  const a={...record('A','X',1990),name:'DO NOT COPY'},b=record('B','Y',2010);
  const graph=buildTrajectoryHypergraph([a,a,b,b],'A');
  assert.equal(graph.nodes.length,2);assert.equal(graph.diagnostics.duplicateIdsCount,2);
  assert.deepEqual(graph.edges[0].members,[0,1]);assert.ok(!JSON.stringify(graph).includes('DO NOT COPY'));
});

test('inferred domestic units remain opt-in and unknown countries excluded',()=>{
  const rows=[record('A','X',1990,2000,2002,'SNU','KR','Physics'),record('B','Y',2010,2000,2002,'SNU','KR','Physics')];
  rows.forEach(r=>r.career[0].department_inferred=true);
  assert.equal(buildTrajectoryHypergraph(rows,'A').edges.length,0);
  assert.equal(buildTrajectoryHypergraph(rows,'A',{includeInferredDepartments:true}).edges[0].inferredDepartment,true);
  rows[1].career[0].country=null;
  assert.equal(buildTrajectoryHypergraph(rows,'A',{includeInferredDepartments:true}).edges.length,0);
});
