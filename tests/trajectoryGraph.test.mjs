import assert from 'node:assert/strict';
import test from 'node:test';
import { buildTrajectoryHypergraph } from '../work/test-dist/constellation/trajectoryGraph.js';
import { buildLifetimeTrajectory } from '../work/test-dist/constellation/lifetime.js';
const student=(id,start,end)=>({id,subject:'physics',phd_institution:'School',phd_country:'US',phd_department:'Physics',phd_year:end,career:[{stage:'doctoral',institution:'School',country:'US',department:'Physics',start_year:start,end_year:end,is_estimated:false}]});

test('a whole selected stage interval is one edge with each peer overlap, not annual memberships',()=>{
  const rows=[student('A',2000,2010),student('B',2000,2002),student('C',2008,2010)];
  const graph=buildTrajectoryHypergraph(rows,'A');
  const lifetime=buildLifetimeTrajectory(rows,'A');
  assert.equal(graph.edges.length,1);const edge=graph.edges[0];
  assert.equal(edge.id,lifetime.stages[0].groups[0].id);
  assert.equal(edge.lifetimeStage,'doctoral');assert.equal(edge.temporalSemantics,'selected_interval_union');
  assert.deepEqual(edge.members,[0,1,2]);assert.deepEqual(graph.incidence,[[0],[0],[0]]);
  assert.deepEqual(edge.memberEvidence.map(e=>[e.peerId,e.startYear,e.endYear]),[['B',2000,2002],['C',2008,2010]]);
  assert.equal(edge.startYear,2000);assert.equal(edge.endYear,2010);
  assert.equal(edge.weight,1.5);assert.equal(edge.sizeAdjustment,.5);
});

test('same-field postdoc institution exception tolerates unverified department differences and stays separated from doctoral stage',()=>{
  const rows=[student('A',2000,2005),student('B',2001,2006)];
  rows[0].career.push({stage:'postdoc',institution:'Institute',country:'US',start_year:2008,end_year:2010,is_estimated:false});
  rows[1].career.push({stage:'postdoc',institution:'Institute',country:'US',department:'Unrelated',start_year:2009,end_year:2011,is_estimated:false});
  const graph=buildTrajectoryHypergraph(rows,'A');
  assert.deepEqual(graph.edges.map(e=>e.lifetimeStage),['doctoral','postdoc']);
  assert.ok(graph.edges.every(e=>e.overlapAdjustment<1));
  const filtered=buildTrajectoryHypergraph(rows,'A',{stages:['postdoc']});
  assert.equal(filtered.edges.length,1);assert.equal(filtered.edges[0].lifetimeStage,'postdoc');
});

test('duplicates do not duplicate memberships and raw private fields never propagate',()=>{
  const a={...student('A',2000,2005),name:'PRIVATE NAME',url:'PRIVATE URL'},b=student('B',2001,2006);
  const graph=buildTrajectoryHypergraph([a,a,b,b],'A');
  assert.equal(graph.nodes.length,2);assert.equal(graph.diagnostics.duplicateIdsCount,2);
  assert.deepEqual(graph.edges[0].members,[0,1]);assert.ok(!JSON.stringify(graph).includes('PRIVATE'));
});

test('inferred doctoral departments stay opt-in and unknown countries never form a group',()=>{
  const rows=[student('A',2000,2005),student('B',2001,2006)];
  rows.forEach(r=>{r.phd_department_inferred=true;r.career[0].department_inferred=true});
  assert.equal(buildTrajectoryHypergraph(rows,'A').edges.length,0);
  assert.equal(buildTrajectoryHypergraph(rows,'A',{includeInferredDepartments:true}).edges[0].inferredDepartment,true);
  rows[1].phd_country=null;rows[1].career[0].country=null;
  assert.equal(buildTrajectoryHypergraph(rows,'A',{includeInferredDepartments:true}).edges.length,0);
});
